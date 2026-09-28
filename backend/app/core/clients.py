"""Multi-tenant client registry.

Each client business needs:

  1. Its own login. A client sees only their business - never the founder's
     revenue, leads or other clients' data.
  2. Its own configuration: website, Instagram, logo, brand voice, locale.
  3. Isolation that fails closed. Every lookup is scoped by client_id, and an
     unknown or expired token resolves to nothing rather than everything.

Each client carries a trial_ends timestamp, and the dashboard shows days
remaining, so a trial expiry is never a surprise.

Storage is the same in-memory store + JSON persistence as the rest of the
app, so there's no new infrastructure.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Optional

_lock = threading.RLock()

# client_id -> record
_clients: dict[str, dict] = {}
# token -> (client_id, issued_at). The timestamp is compared against
# SESSION_TTL, so portal tokens expire instead of staying valid for the life
# of the process.
_sessions: dict[str, tuple[str, float]] = {}

TRIAL_DAYS_DEFAULT = 60          # the default two-month free trial
SESSION_TTL = 7 * 24 * 3600      # a week; they are business owners, not attackers


def _secret() -> str:
    # Reuse the app secret (core/appsecret.py) so tokens die when credentials are
    # rotated.
    from . import appsecret
    return appsecret.value()


def _mint(cid: str) -> str:
    """The only place a portal token is created, so no caller can add one
    without an expiry.
    """
    token = secrets.token_urlsafe(32)
    _sessions[token] = (cid, time.time())
    return token


def _hash_password(password: str, salt: str) -> str:
    """PBKDF2. Not bcrypt to avoid a dependency; 200k rounds of SHA-256 is plenty
    for a handful of business logins.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()


def create_client(
    business_name: str,
    username: str,
    password: str,
    *,
    website: str = "",
    instagram: str = "",
    industry: str = "",
    city: str = "",
    country: str = "Pakistan",
    logo_url: str = "",
    brand_voice: str = "",
    trial_days: int = TRIAL_DAYS_DEFAULT,
    notes: str = "",
) -> dict:
    """Register a business. Returns the record without the password hash."""
    username = (username or "").strip().lower()
    if not username or not password:
        raise ValueError("username and password are required")

    with _lock:
        if any(c["username"] == username for c in _clients.values()):
            raise ValueError(f"username '{username}' already exists")

        cid = f"cl_{secrets.token_hex(6)}"
        salt = secrets.token_hex(16)
        now = time.time()

        _clients[cid] = {
            "id": cid,
            "business_name": business_name,
            "username": username,
            "_salt": salt,
            "_pwhash": _hash_password(password, salt),
            "website": website.rstrip("/"),
            "instagram": instagram.lstrip("@"),
            "industry": industry,
            "city": city,
            "country": country,
            "logo_url": logo_url,
            "brand_voice": brand_voice,
            "notes": notes,
            "created_at": now,
            "trial_ends": now + trial_days * 86400,
            "status": "trial",
            "last_login": None,
            # Per-client work log. Everything Titan does for the client lands here, so
            # the client dashboard shows real activity.
            "activity": [],
            "metrics": {
                "seo_audits": 0, "posts_drafted": 0, "posts_approved": 0,
                "issues_found": 0, "issues_fixed": 0,
            },
        }
        return public(cid)


def public(cid: str) -> dict:
    """A client record safe to send over the wire, with no secrets."""
    c = _clients.get(cid)
    if not c:
        return {}
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["trial_days_left"] = max(
        0, int((c["trial_ends"] - time.time()) // 86400))
    out["trial_expired"] = time.time() > c["trial_ends"]
    out["activity"] = c["activity"][-25:]
    return out


def authenticate(username: str, password: str) -> Optional[str]:
    """Return a session token, or None. Constant-time compare."""
    username = (username or "").strip().lower()
    with _lock:
        for cid, c in _clients.items():
            if c["username"] != username:
                continue
            candidate = _hash_password(password, c["_salt"])
            if not hmac.compare_digest(candidate, c["_pwhash"]):
                return None
            token = _mint(cid)
            c["last_login"] = time.time()
            _log(cid, "auth", f"{c['business_name']} signed in")
            return token
    return None


def issue_session(cid: str) -> Optional[str]:
    """A session for a business whose owner has already been authenticated.

    A subscriber's own business is created with a random, unusable portal
    password (see /api/account/onboard), because they already authenticate as
    the account holder. This mints a portal session for them directly.

    It does no authorisation of its own - the caller must have proved
    ownership first (`_owned` in api/router.py). Kept that way on purpose: a
    function that both mints sessions and decides who gets one is easy to call
    from the wrong place.
    """
    with _lock:
        if cid not in _clients:
            return None
        token = _mint(cid)
        _log(cid, "auth", f"{_clients[cid]['business_name']} opened by its owner")
        return token


def resolve(token: str) -> Optional[str]:
    """Token -> client_id. Fails closed: unknown or expired resolves to nothing.

    Expired tokens are removed here, not just refused, so the dict doesn't
    grow forever on a deployment that issues sessions to the public.
    """
    if not token:
        return None
    with _lock:
        entry = _sessions.get(token)
        if not entry:
            return None
        cid, issued = entry
        if time.time() - issued > SESSION_TTL:
            _sessions.pop(token, None)
            return None
        return cid


def revoke(token: str) -> None:
    _sessions.pop(token, None)


def get(cid: str) -> Optional[dict]:
    return _clients.get(cid)


def all_clients() -> list[dict]:
    with _lock:
        return [public(cid) for cid in _clients]


def update(cid: str, **fields) -> dict:
    """Patch editable fields. Credentials are not editable here."""
    editable = {
        "business_name", "website", "instagram", "industry", "city",
        "country", "logo_url", "brand_voice", "notes", "status",
    }
    with _lock:
        c = _clients.get(cid)
        if not c:
            return {}
        for k, v in fields.items():
            if k in editable and v is not None:
                c[k] = v.rstrip("/") if k == "website" else v
        return public(cid)


def update_raw(cid: str, **fields) -> None:
    """Set internal fields not exposed through the editable allow-list.

    Used for cached derived data (e.g. the last audit result) that the client
    can read but never set through the public update path.
    """
    with _lock:
        c = _clients.get(cid)
        if c:
            c.update(fields)


def set_password(cid: str, password: str) -> bool:
    with _lock:
        c = _clients.get(cid)
        if not c or not password:
            return False
        c["_salt"] = secrets.token_hex(16)
        c["_pwhash"] = _hash_password(password, c["_salt"])
        # Any existing session for this client is now invalid.
        for tok, (owner, _issued) in list(_sessions.items()):
            if owner == cid:
                _sessions.pop(tok, None)
        return True


def extend_trial(cid: str, days: int) -> dict:
    with _lock:
        c = _clients.get(cid)
        if not c:
            return {}
        base = max(c["trial_ends"], time.time())
        c["trial_ends"] = base + days * 86400
        _log(cid, "billing", f"trial extended by {days} days")
        return public(cid)


def delete_client(cid: str) -> bool:
    with _lock:
        if cid not in _clients:
            return False
        _clients.pop(cid)
        for tok, (owner, _issued) in list(_sessions.items()):
            if owner == cid:
                _sessions.pop(tok, None)
        return True


# ------------------------------------------------------------- activity -----
def _log(cid: str, kind: str, message: str, meta: dict | None = None) -> None:
    c = _clients.get(cid)
    if not c:
        return
    c["activity"].append({
        "ts": time.time(), "kind": kind, "message": message, "meta": meta,
    })
    # Bounded so a long-running client can't grow the state file forever.
    if len(c["activity"]) > 400:
        del c["activity"][:200]


def log_activity(cid: str, kind: str, message: str,
                 meta: dict | None = None) -> None:
    with _lock:
        _log(cid, kind, message, meta)


def bump(cid: str, metric: str, n: int = 1) -> None:
    with _lock:
        c = _clients.get(cid)
        if c and metric in c["metrics"]:
            c["metrics"][metric] += n


# ------------------------------------------------------------- overview -----
def admin_overview(only=None) -> dict:
    """Everything the founder needs on one screen.

    `only` limits it to those client ids - a subscriber's cockpit asks for its
    own businesses in this shape (api/mine.py).
    """
    with _lock:
        ids = [cid for cid in _clients if only is None or cid in only]
        rows = [public(cid) for cid in ids]

    active = [r for r in rows if not r["trial_expired"]]
    expiring = sorted(
        [r for r in active if r["trial_days_left"] <= 14],
        key=lambda r: r["trial_days_left"])

    return {
        "total": len(rows),
        "active": len(active),
        "expired": len(rows) - len(active),
        "expiring_soon": [
            {"id": r["id"], "business_name": r["business_name"],
             "days_left": r["trial_days_left"]} for r in expiring
        ],
        "totals": {
            k: sum(r["metrics"].get(k, 0) for r in rows)
            for k in ("seo_audits", "posts_drafted", "posts_approved",
                      "issues_found", "issues_fixed")
        },
        "clients": [
            {"id": r["id"], "business_name": r["business_name"],
             "industry": r.get("industry", ""), "website": r.get("website", ""),
             "instagram": r.get("instagram", ""), "status": r["status"],
             "trial_days_left": r["trial_days_left"],
             "last_login": r.get("last_login"),
             "metrics": r["metrics"]}
            for r in rows
        ],
    }


# ---------------------------------------------------------- persistence -----
def export_state() -> dict:
    with _lock:
        return {"clients": _clients}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("clients")
    if not isinstance(rows, dict):
        return
    with _lock:
        _clients.clear()
        for cid, rec in rows.items():
            if isinstance(rec, dict) and "username" in rec:
                rec.setdefault("activity", [])
                rec.setdefault("metrics", {
                    "seo_audits": 0, "posts_drafted": 0, "posts_approved": 0,
                    "issues_found": 0, "issues_fixed": 0})
                _clients[cid] = rec
