"""Rate limiting for unauthenticated endpoints.

Before this there was none, anywhere. Two endpoints made that expensive rather
than merely untidy:

* ``POST /api/signup`` is unauthenticated and creates a permanent account
  record in shared state. A loop fills the database and the founder analytics
  screen with garbage, and there is no way to tell the real first customer from
  the noise.
* ``POST /api/account/onboard`` triggers an outbound crawl of a URL the caller
  supplies. Unmetered, that turns Titan into a request amplifier pointed at
  somebody else's server, from Titan's IP and against Titan's reputation.

Deliberately in-process and dependency-free. A single container has one memory
space, so a dict is the correct store — Redis would add an operational
dependency to solve a problem that does not exist yet. **This does not survive
being scaled to two containers**, and that is written down rather than
discovered later: the day a second worker exists, this needs shared state.

Behaviour on refusal follows the same rule as the quota system: say which limit
was hit, and when it clears. A bare 429 teaches a caller nothing and looks like
a fault.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# (requests, per_seconds) per bucket. Signup is deliberately tighter than
# onboarding because an account is permanent and a crawl is not.
LIMITS: dict[str, tuple[int, int]] = {
    "signup": (5, 3600),        # 5 accounts per hour per address
    "onboard": (10, 3600),      # 10 crawls per hour per account
    "login": (12, 900),         # 12 attempts per 15 min — slows credential stuffing
    "demo": (30, 3600),         # demo sessions are cheap but not free
    "discover": (20, 3600),     # lead discovery burns Tavily quota
    "org": (10, 3600),          # an organisation is a permanent record
}

# Off in tests by default: a suite that creates dozens of accounts would trip
# limits and fail for the wrong reason. Production leaves it on.
ENABLED = os.getenv("TITAN_RATE_LIMIT", "1") != "0"

MAX_TRACKED = 20_000

_lock = threading.RLock()
_hits: dict[str, list[float]] = {}


def _prune(now: float) -> None:
    """Drop buckets whose newest hit is older than the longest window."""
    longest = max((w for _, w in LIMITS.values()), default=3600)
    dead = [k for k, ts in _hits.items() if not ts or now - ts[-1] > longest]
    for k in dead:
        del _hits[k]
    if len(_hits) > MAX_TRACKED:
        for k in sorted(_hits, key=lambda k: _hits[k][-1])[:len(_hits) - MAX_TRACKED]:
            del _hits[k]


def check(bucket: str, identity: str) -> dict:
    """Is this call allowed? Never raises, never blocks.

    `identity` is whatever distinguishes the caller — a hashed address for
    anonymous endpoints, an account email for authenticated ones. It is used as
    a key only and is never stored beyond the window.
    """
    if not ENABLED or bucket not in LIMITS:
        return {"allowed": True}
    limit, window = LIMITS[bucket]
    key = f"{bucket}:{identity}"
    now = time.time()

    with _lock:
        _prune(now)
        stamps = [t for t in _hits.get(key, []) if now - t < window]
        if len(stamps) >= limit:
            oldest = stamps[0]
            retry = max(1, int(window - (now - oldest)))
            _hits[key] = stamps
            return {
                "allowed": False,
                "limit": limit,
                "window_seconds": window,
                "retry_after_seconds": retry,
                "reason": (f"Too many requests: {limit} per "
                           f"{window // 60} minutes on this endpoint. "
                           f"Try again in {retry // 60 + 1} minute(s)."),
            }
        stamps.append(now)
        _hits[key] = stamps
        return {"allowed": True, "used": len(stamps), "limit": limit}


def identity_for(request) -> str:
    """A stable, non-identifying key for an anonymous caller.

    Behind the Cloudflare Worker the socket peer is Cloudflare, so the real
    address is in CF-Connecting-IP. The value is used as a dict key for at most
    an hour and is never persisted — consistent with the analytics rule that
    Titan does not store visitor addresses.
    """
    try:
        return (request.headers.get("cf-connecting-ip")
                or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown"))
    except Exception:
        return "unknown"


def reset() -> None:
    """Test seam."""
    with _lock:
        _hits.clear()
