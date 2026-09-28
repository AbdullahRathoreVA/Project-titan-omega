"""Rate limiting for unauthenticated and expensive endpoints.

The two that matter most:

* ``POST /api/signup`` is unauthenticated and creates a permanent account
  record. Without a limit, a loop fills the database and the founder's
  analytics with junk.
* ``POST /api/account/onboard`` crawls a URL the caller supplies. Unmetered,
  it turns Titan into a request amplifier aimed at someone else's server.

In-process and dependency-free: a single container has one memory space, so a
dict is enough and Redis would be an extra moving part. This does NOT survive
scaling to two containers - a second worker would need shared state.

A refusal says which limit was hit and when it clears, like the quota system.
A bare 429 looks like a fault.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# (requests, per_seconds) per bucket. Signup is tighter than onboarding because
# an account is permanent and a crawl isn't.
LIMITS: dict[str, tuple[int, int]] = {
    "signup": (5, 3600),        # 5 accounts per hour per address
    "onboard": (10, 3600),      # 10 crawls per hour per account
    "login": (12, 900),         # 12 attempts per 15 min - slows credential stuffing
    "demo": (30, 3600),         # demo sessions are cheap but not free
    "discover": (20, 3600),     # lead discovery burns Tavily quota
    "org": (10, 3600),          # an organisation is a permanent record
    "warroom": (10, 3600),      # a subscriber's scan/debate: web search + AI calls
}

# Can be switched off for tests: a suite that creates dozens of accounts would
# otherwise trip the limits. Production leaves it on.
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

    `identity` distinguishes the caller - a hashed address for anonymous
    endpoints, an account email for authenticated ones. It's only used as a
    key and isn't kept beyond the window.
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
    address comes from CF-Connecting-IP. It's used as a dict key for at most
    an hour and never persisted; Titan doesn't store visitor addresses.
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
