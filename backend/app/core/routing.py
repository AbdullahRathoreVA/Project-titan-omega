"""Model provider profiling and routing based on measured performance.

`llm._provider_chain()` has a fixed order based on free-tier quotas. On its
own, a provider whose key died would stay first in the chain and every call
would wait for its timeout before failing over. This records the outcome of
each call, keeps per-provider statistics, and reorders the chain from them.

1. A provider is never removed, only reordered. Dropping one on a transient
   outage could leave no provider at all when a rate limit hits; the worst a
   bad provider gets is last place.
2. Ranking needs evidence. Below `MIN_CALLS` samples a provider keeps its
   configured position, so one unlucky timeout doesn't demote a good provider.
3. Recovery is automatic. A demoted provider is retried normally once its
   cooldown expires.

State is persisted with the rest of the store: Hugging Face restarts Spaces
often, and stats that reset on every restart would never accumulate enough
evidence to route on.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import events

# A provider must have at least this many recorded calls before measurements
# outrank its configured position.
MIN_CALLS = 3
# Consecutive failures before a provider is pushed to the back of the chain.
TRIP_AFTER = 3
# How long a tripped provider stays demoted before it is tried normally again.
COOLDOWN_SECONDS = 900
# Bounded per-provider latency history - this runs in a small container.
MAX_SAMPLES = 50

_lock = threading.RLock()
_profiles: dict[str, dict] = {}


def _blank(name: str) -> dict:
    return {
        "provider": name,
        "calls": 0,
        "successes": 0,
        "failures": 0,
        "consecutive_failures": 0,
        "latencies_ms": [],
        "last_error": "",
        "last_ok_ts": 0.0,
        "last_call_ts": 0.0,
        "tripped_until": 0.0,
    }


def record(provider: str, *, ok: bool, latency_ms: int,
           error: str = "") -> dict:
    """Record one completion attempt. Never raises."""
    with _lock:
        p = _profiles.setdefault(provider, _blank(provider))
        p["calls"] += 1
        p["last_call_ts"] = time.time()
        if ok:
            p["successes"] += 1
            p["consecutive_failures"] = 0
            p["last_ok_ts"] = time.time()
            p["last_error"] = ""
            p["tripped_until"] = 0.0
            p["latencies_ms"].append(int(latency_ms))
            if len(p["latencies_ms"]) > MAX_SAMPLES:
                del p["latencies_ms"][:len(p["latencies_ms"]) - MAX_SAMPLES]
        else:
            p["failures"] += 1
            p["consecutive_failures"] += 1
            p["last_error"] = error[:200]
            if p["consecutive_failures"] >= TRIP_AFTER:
                p["tripped_until"] = time.time() + COOLDOWN_SECONDS
        snapshot = dict(p)

    events.emit(
        events.MODEL_SELECTED if ok else events.MODEL_FAILED,
        {"provider": provider, "ok": ok, "latency_ms": latency_ms,
         "error": error[:160]},
        actor="routing", severity="info" if ok else "warn")
    return snapshot


def _p50(values: list) -> int:
    if not values:
        return 0
    s = sorted(values)
    return int(s[len(s) // 2])


def _score(p: dict) -> float:
    """Higher is better. Success rate dominates; latency breaks ties.

    A provider that answers in 200ms but fails half the time is worse than one
    that takes 2s and always works, because every failure costs a full retry
    through the chain.
    """
    if p["calls"] < MIN_CALLS:
        return 0.0
    success_rate = p["successes"] / p["calls"]
    median = _p50(p["latencies_ms"]) or 5000
    # Latency contributes at most ~0.1, so it can only order providers whose
    # success rates are close.
    return success_rate + min(0.1, 1000.0 / (median * 100.0))


def order(chain: list) -> list:
    """Reorder a configured provider chain by measured performance.

    Providers with too little evidence keep their configured position. Tripped
    providers go last but are never dropped.
    """
    now = time.time()
    with _lock:
        profiles = {k: dict(v) for k, v in _profiles.items()}

    def sort_key(item):
        idx, name = item
        p = profiles.get(name)
        if not p:
            return (0, idx, 0.0)                    # unmeasured: keep position
        if p["tripped_until"] > now:
            return (2, idx, 0.0)                    # tripped: to the back
        if p["calls"] < MIN_CALLS:
            return (0, idx, 0.0)                    # not enough evidence yet
        return (1, 0, -_score(p))                   # measured: best first

    ranked = sorted(enumerate(chain), key=sort_key)
    # Group 0 keeps configured order; group 1 is best-measured first. Interleaved
    # so a measured provider only outranks an unmeasured one once it has proven
    # itself.
    unmeasured = [n for i, n in ranked if sort_key((i, n))[0] == 0]
    measured = [n for i, n in ranked if sort_key((i, n))[0] == 1]
    tripped = [n for i, n in ranked if sort_key((i, n))[0] == 2]
    return measured + unmeasured + tripped


def report() -> dict:
    """Per-provider measurements, for the dashboard and for routing decisions."""
    now = time.time()
    with _lock:
        rows = []
        for name, p in sorted(_profiles.items()):
            rate = (p["successes"] / p["calls"]) if p["calls"] else 0.0
            rows.append({
                "provider": name,
                "calls": p["calls"],
                "successes": p["successes"],
                "failures": p["failures"],
                "success_rate": round(rate * 100, 1),
                "p50_latency_ms": _p50(p["latencies_ms"]),
                "consecutive_failures": p["consecutive_failures"],
                "tripped": p["tripped_until"] > now,
                "cooldown_remaining_s": max(0, int(p["tripped_until"] - now)),
                "last_error": p["last_error"],
                "routable": p["calls"] >= MIN_CALLS,
            })
    return {
        "providers": rows,
        "min_calls_to_rank": MIN_CALLS,
        "trip_after_consecutive_failures": TRIP_AFTER,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "note": ("Routing order is derived from these numbers. A provider is "
                 "never dropped from the chain — the worst it gets is last "
                 "place, because losing a provider during a transient outage "
                 "would silence every agent."),
    }


# ---------------------------------------------------------- persistence --

def export_state() -> dict:
    with _lock:
        return {"profiles": {k: dict(v) for k, v in _profiles.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("profiles")
    if not isinstance(rows, dict):
        return
    # Every value is coerced to its expected type. The state file is JSON on disk
    # and can be truncated by a crash mid-write or edited by hand; one bad value
    # mustn't 500 the dashboard or abort the rest of the restore.
    def _int(v, default=0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _float(v, default=0.0) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    with _lock:
        _profiles.clear()
        for name, p in rows.items():
            if not isinstance(p, dict) or not isinstance(name, str):
                continue
            base = _blank(name)
            for key in ("calls", "successes", "failures", "consecutive_failures"):
                base[key] = max(0, _int(p.get(key)))
            for key in ("last_ok_ts", "last_call_ts", "tripped_until"):
                base[key] = _float(p.get(key))
            samples = p.get("latencies_ms")
            base["latencies_ms"] = (
                [_int(x) for x in samples[-MAX_SAMPLES:]]
                if isinstance(samples, list) else [])
            err = p.get("last_error")
            base["last_error"] = err[:200] if isinstance(err, str) else ""
            # A corrupt file could claim more successes than calls, giving a success rate
            # above 100%.
            base["successes"] = min(base["successes"], base["calls"])
            base["failures"] = min(base["failures"], base["calls"])
            _profiles[name] = base


def reset() -> None:
    """Test seam."""
    with _lock:
        _profiles.clear()
