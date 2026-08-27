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

# "kind:subject" -> the moment every session for that subject stopped counting.
#
# revoke() can only invalidate a token somebody is HOLDING, and these tokens
# are stateless: nothing here knows which jti belongs to whom. So there was no
# way to end all of one person's sessions — which is the entire point of
# changing a password. Telling somebody to change it because it leaked, while
# leaving whoever leaked it signed in, is theatre.
#
# One float per subject, bounded the same way _revoked is: a cutoff is useless
# once no token issued before it could still be valid.
_cutoffs: dict[str, float] = {}


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
    # `iat` carries sub-second precision on purpose. It used to be int(now),
    # and a whole-second stamp cannot be compared against a "sign everyone out"
    # moment without either leaving a one-second hole for the attacker or
    # killing the replacement token minted in the same second. Neither is a
    # rounding decision. `exp` stays whole — nothing compares against it that
    # finely.
    iat = round(now, 3)
    with _lock:
        # Signing somebody back in immediately after ending their sessions is a
        # normal thing to do — it is what a password change does. Wall-clock
        # alone cannot express "after" at this resolution, so the stamp is
        # nudged past the cutoff rather than left to collide with it. Without
        # this the replacement session dies on arrival and the person is logged
        # out by the act of securing their account.
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
        # Every session for this subject was ended after this token was minted.
        cutoff = _cutoffs.get(f"{payload.get('kind')}:{payload.get('sub')}")
        # <=, not <. A token stamped in the same millisecond as the change dies
        # with the ones before it. Anything issued afterwards is nudged past
        # the cutoff by issue(), so nothing legitimate lands on this boundary.
        if cutoff is not None and float(payload.get("iat", 0)) <= cutoff:
            return None
    return payload


def subject(token: str, kind: Optional[str] = None) -> Optional[str]:
    payload = verify(token, kind)
    return payload.get("sub") if payload else None


def invalidate_all(subject_: str, kind: str = "account") -> float:
    """End every session this subject currently holds. Returns the cutoff.

    Tokens issued from now on are unaffected, so the caller can sign the person
    straight back in — a password change should not require a second login, and
    one that does is a password change people avoid making.
    """
    # Rounded to the SAME precision `iat` carries. Keeping more here than a
    # token can record means a token minted a microsecond later still compares
    # as older than the cutoff, and the replacement session dies on arrival.
    # A test caught exactly that; a manual check with more slack between the
    # two calls had not.
    now = round(time.time(), 3)
    with _lock:
        _cutoffs[f"{kind}:{subject_}"] = now
        _prune()
    return now


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
    # A cutoff stops mattering once no token issued before it could still be
    # valid. The longest any token lives is ACCOUNT_TTL, so that is the window.
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
        # Cutoffs persist for the same reason revocations do: a restart that
        # un-ends everybody's sessions would hand the account back to whoever
        # the password was changed to lock out.
        return {"revoked": dict(_revoked), "cutoffs": dict(_cutoffs)}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("revoked")
    if not isinstance(rows, dict):
        # Older snapshots have no cutoffs either, and returning here used to be
        # harmless. It is not any more: skipping the rest would silently drop
        # every "sign everyone out" that had been recorded.
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
