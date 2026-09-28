"""Signed, expiring, revocable session tokens.

A token is ``payload.signature``: base64url JSON carrying subject, kind, issue
time, expiry and a random id, signed with HMAC-SHA256.

1. Verification is stateless, so a restart doesn't sign anyone out and no
   session table is needed.
2. Revocation therefore needs explicit state, because a stateless token is
   valid until it expires. A small list of revoked ids is persisted, and
   entries are dropped once the token they refer to would have expired
   anyway.

Signature comparison is constant-time, and expiry is checked after the
signature, so an unsigned token can't reveal timing information about a valid
one.
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

# Founder sessions are long enough not to be annoying and short enough that a
# leaked token isn't permanent. Guests are read-only, so shorter still.
DEFAULT_TTL = int(os.getenv("TITAN_SESSION_TTL", str(14 * 86400)))
GUEST_TTL = int(os.getenv("TITAN_GUEST_TTL", str(6 * 3600)))
ACCOUNT_TTL = int(os.getenv("TITAN_ACCOUNT_TTL", str(30 * 86400)))

_lock = threading.RLock()
# token id -> expiry. Bounded: an entry is useless once the token it names
# would have expired on its own.
_revoked: dict[str, float] = {}

# "kind:subject" -> the moment every session for that subject stopped counting.
#
# revoke() can only invalidate a token someone is holding, and since tokens are
# stateless nothing here knows which ids belong to whom. This is how all of one
# person's sessions are ended, e.g. after a password change.
#
# One float per subject, bounded like _revoked: a cutoff is useless once no
# token issued before it could still be valid.
_cutoffs: dict[str, float] = {}


def _secret() -> bytes:
    # Through core/appsecret.py, so sessions are never signed with a fallback
    # that's published in the repository.
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
    # `iat` keeps sub-second precision on purpose. With whole seconds, comparing
    # against a "sign everyone out" moment would either leave a one-second gap or
    # kill a replacement token minted in the same second. `exp` stays whole;
    # nothing compares against it that finely.
    iat = round(now, 3)
    with _lock:
        # Signing someone back in right after ending their sessions is normal - it's
        # what a password change does. Wall-clock time can't express "after" at this
        # resolution, so the stamp is nudged past the cutoff; otherwise the new
        # session would die immediately.
        cutoff = _cutoffs.get(f"{kind}:{subject}")
        if cutoff is not None and iat <= cutoff:
            iat = round(cutoff + 0.001, 3)
    payload = {"sub": subject, "kind": kind, "iat": iat,
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
    # Constant-time, and checked before anything is parsed or compared, so a
    # forged token can't leak timing information about a valid one.
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
        # Every session for this subject was ended after this token was minted.
        cutoff = _cutoffs.get(f"{payload.get('kind')}:{payload.get('sub')}")
        # <=, not <. A token stamped in the same millisecond as the change dies with
        # the older ones. Anything issued afterwards is nudged past the cutoff by
        # issue(), so nothing legitimate lands on this boundary.
        if cutoff is not None and float(payload.get("iat", 0)) <= cutoff:
            return None
    return payload


def subject(token: str, kind: Optional[str] = None) -> Optional[str]:
    payload = verify(token, kind)
    return payload.get("sub") if payload else None


def invalidate_all(subject_: str, kind: str = "account") -> float:
    """End every session this subject currently holds. Returns the cutoff.

    Tokens issued from now on are unaffected, so the caller can sign the
    person straight back in; a password change shouldn't force a second
    login.
    """
    # Rounded to the same precision as `iat`. With more precision here, a token
    # minted a microsecond later could still compare as older than the cutoff and
    # the replacement session would die on arrival.
    now = round(time.time(), 3)
    with _lock:
        _cutoffs[f"{kind}:{subject_}"] = now
        _prune()
    return now


def revoke(token: str) -> bool:
    """Invalidate one token before its expiry. Returns False if it was never
    valid - revoking a forged token isn't a success.
    """
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
    # A cutoff stops mattering once no token issued before it could still be
    # valid. The longest any token lives is ACCOUNT_TTL, so that's the window.
    oldest_useful = now - max(DEFAULT_TTL, GUEST_TTL, ACCOUNT_TTL)
    for key in [k for k, at in _cutoffs.items() if at <= oldest_useful]:
        del _cutoffs[key]


def revoked_count() -> int:
    with _lock:
        _prune()
        return len(_revoked)


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        _prune()
        # Cutoffs persist for the same reason revocations do: a restart that un-ends
        # everyone's sessions would hand the account back to whoever the password
        # change was meant to lock out.
        return {"revoked": dict(_revoked), "cutoffs": dict(_cutoffs)}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("revoked")
    if not isinstance(rows, dict):
        # Older snapshots have no cutoffs; returning early here would drop any
        # "sign everyone out" already recorded.
        rows = {}
    with _lock:
        _revoked.clear()
        for jti, exp in rows.items():
            try:
                _revoked[str(jti)] = float(exp)
            except Exception:
                continue
        _cutoffs.clear()
        for key, at in (data.get("cutoffs") or {}).items():
            try:
                _cutoffs[str(key)] = float(at)
            except Exception:
                continue
        _prune()


def reset() -> None:
    """Test seam."""
    with _lock:
        _revoked.clear()
        _cutoffs.clear()
