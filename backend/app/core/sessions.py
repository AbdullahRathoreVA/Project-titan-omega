"""Signed, expiring, revocable session tokens.

What this replaces, and why each part mattered:

* **The founder token was ``hmac(secret, username)``.** Deterministic, so the
  same string every time it was issued; non-expiring, so a token copied from a
  browser in March still worked in August; and unrevocable, because there was
  nothing to revoke — the only way to invalidate it was to change
  ``TITAN_SECRET`` and log out of everything everywhere.
* **Subscriber sessions were a module-level dict.** Every paying customer was
  silently signed out by a restart, which on a free-tier host happens often.

A token is now ``payload.signature``: base64url JSON carrying subject, kind,
issue time, expiry and a random id, signed with HMAC-SHA256. Two consequences
worth stating:

1. **Verification is stateless**, so a restart no longer signs anyone out —
   the fix for the subscriber problem falls out of the format rather than
   needing a session table.
2. **Revocation therefore needs explicit state**, because a stateless token is
   valid until it expires by definition. A small revoked-id list is persisted;
   it is bounded because entries can be dropped once the token they refer to
   would have expired anyway.

Signature comparison is constant-time. Expiry is checked after the signature,
so an unsigned token can never reveal timing information about a valid one.

**Existing tokens stop working.** Anyone signed in must sign in again once.
That is the correct trade for a credential that previously never expired, and
it is a one-time cost while there are no paying customers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Optional

# Founder sessions are long enough not to be irritating, short enough that a
# leaked token is not permanent. Guests are read-only, so shorter still.
DEFAULT_TTL = int(os.getenv("TITAN_SESSION_TTL", str(14 * 86400)))
GUEST_TTL = int(os.getenv("TITAN_GUEST_TTL", str(6 * 3600)))
ACCOUNT_TTL = int(os.getenv("TITAN_ACCOUNT_TTL", str(30 * 86400)))

_lock = threading.RLock()
# token id -> expiry. Bounded: an entry is useless once the token it names
# would have expired on its own.
_revoked: dict[str, float] = {}


def _secret() -> bytes:
    # One door — see core/appsecret.py. Signing sessions with a fallback that
    # is printed in the repository makes every token forgeable.
    from . import appsecret
    return appsecret.key()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(subject: str, kind: str = "founder",
          ttl: Optional[int] = None) -> str:
    """Mint a token. Two calls never produce the same string."""
    now = time.time()
    ttl = ttl if ttl is not None else DEFAULT_TTL
    payload = {"sub": subject, "kind": kind, "iat": int(now),
               "exp": int(now + ttl), "jti": secrets.token_urlsafe(9)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str, kind: Optional[str] = None) -> Optional[dict]:
    """Return the payload, or None. Never raises on malformed input."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    # Constant-time, and checked BEFORE anything is parsed or compared, so a
    # forged token cannot leak timing information about a valid one.
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if kind is not None and payload.get("kind") != kind:
        return None
    if float(payload.get("exp", 0)) <= time.time():
        return None
    with _lock:
        if payload.get("jti") in _revoked:
            return None
    return payload


def subject(token: str, kind: Optional[str] = None) -> Optional[str]:
    payload = verify(token, kind)
    return payload.get("sub") if payload else None


def revoke(token: str) -> bool:
    """Invalidate one token before its expiry. Returns False if it was never
    valid — revoking a forged token is not a success."""
    if not token or "." not in token:
        return False
    body, _, sig = token.partition(".")
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(_unb64(body))
        jti, exp = payload["jti"], float(payload["exp"])
    except Exception:
        return False
    with _lock:
        _revoked[jti] = exp
        _prune()
    return True


def _prune() -> None:
    now = time.time()
    for jti in [j for j, exp in _revoked.items() if exp <= now]:
        del _revoked[jti]


def revoked_count() -> int:
    with _lock:
        _prune()
        return len(_revoked)


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        _prune()
        return {"revoked": dict(_revoked)}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("revoked")
    if not isinstance(rows, dict):
        return
    with _lock:
        _revoked.clear()
        for jti, exp in rows.items():
            try:
                _revoked[str(jti)] = float(exp)
            except Exception:
                continue
        _prune()


def reset() -> None:
    """Test seam."""
    with _lock:
        _revoked.clear()
