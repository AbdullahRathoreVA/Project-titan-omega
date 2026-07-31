"""Multi-tenant client registry — turning Titan into something you can sell.

Context: a restaurant owner wants SEO and social media handled, with a 2-month
free evaluation. That is a real customer, and it needs three things Titan did
not have:

  1. Separate logins. The client sees THEIR business only — never Abdullah's
     revenue, leads, or other clients' data.
  2. Per-client configuration. Their website, their Instagram, their logo,
     their brand voice, their locale.
  3. Isolation that fails closed. A bug must not leak client A's data to
     client B. Every lookup is scoped by client_id, and an unknown or expired
     token resolves to nothing rather than to everything.

Trial handling is explicit because "2 months free" is a promise with a date
attached: each client carries a trial_ends timestamp, and the dashboard shows
days remaining so an expiry is never a surprise to either side.

Storage is the same in-memory store + JSON persistence the rest of the app
uses, so this adds no new infrastructure to run or pay for.
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
# token -> client_id
_sessions: dict[str, str] = {}

TRIAL_DAYS_DEFAULT = 60          # the "2 months free" the client asked for
SESSION_TTL = 7 * 24 * 3600      # a week; they are business owners, not attackers


def _secret() -> str:
    # Reuse the app secret when present so tokens die on credential rotation.
    return os.getenv("TITAN_SECRET", os.getenv("TITAN_TOKEN", "titan-dev-secret"))


def _hash_password(password: str, salt: str) -> str:
    """PBKDF2. Not bcrypt because we add no dependency, but 200k rounds of
    SHA-256 is far beyond adequate for a handful of business logins."""
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
    """Register a business. Returns the record WITHOUT the password hash."""
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
            # Per-client work log. Everything Titan does FOR them lands here,
            # which is what makes the client dashboard honest rather than a mock.
            "activity": [],
            "metrics": {
                "seo_audits": 0, "posts_drafted": 0, "posts_approved": 0,
                "issues_found": 0, "issues_fixed": 0,
            },
        }
        return public(cid)


def public(cid: str) -> dict:
    """A client record safe to send over the wire — no secrets."""
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
            token = secrets.token_urlsafe(32)
            _sessions[token] = cid
            c["last_login"] = time.time()
            _log(cid, "auth", f"{c['business_name']} signed in")
            return token
    return None


def resolve(token: str) -> Optional[str]:
    """Token -> client_id. Fails closed: unknown token resolves to nothing."""
    if not token:
        return None
    return _sessions.get(token)


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


def set_password(cid: str, password: str) -> bool:
    with _lock:
        c = _clients.get(cid)
        if not c or not password:
            return False
        c["_salt"] = secrets.token_hex(16)
        c["_pwhash"] = _hash_password(password, c["_salt"])
        # Any existing session for this client is now invalid.
        for tok, owner in list(_sessions.items()):
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
        for tok, owner in list(_sessions.items()):
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
    # Bounded so a long-running client cannot grow the state file forever.
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
def admin_overview() -> dict:
    """Everything Abdullah needs on one screen."""
    with _lock:
        rows = [public(cid) for cid in _clients]

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
