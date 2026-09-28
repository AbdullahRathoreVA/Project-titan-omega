"""Append-only record of who did what to whom.

Different from core/obs.py (request logs on stdout, gone when the container
recycles) and core/events.py (the live activity stream). This one answers
"who suspended this organisation, and when" weeks later.

- There is no update or delete function at all. An audit log an admin can
  edit proves nothing.
- Secrets are redacted on the way in, not on the way out; once a value
  reaches the table it's on disk and in every backup. Key names are matched
  loosely so a new field like ``api_secret`` is caught without anyone
  updating a list.
- Failed actions are recorded too. Six refused attempts to remove an owner is
  the signal worth alerting on.
- It reports whether it survives a rebuild. On the current free-tier host it
  doesn't (``durable: false``), so nobody relies on it by mistake.

It only records what core/orgs.py and core/identity.py decided.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Optional

_lock = threading.RLock()

OK = "ok"
REFUSED = "refused"
FAILED = "failed"

# Substrings, not exact names: any key containing one of these has its value
# replaced before it's written. Loose on purpose, to catch fields nobody added
# to a list.
_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                 "authorization", "auth", "credential", "cookie", "session",
                 "private", "signature", "card", "cvv", "pan")

REDACTED = "[redacted]"

# Bounded so one runaway caller can't grow the audit table without limit.
MAX_META_CHARS = 4000


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def redact(meta: Optional[dict]) -> dict:
    """Strip anything that looks like a credential, recursively.

    Applied before the row is written: once a secret reaches the table, read
    time filtering can't take it back off disk or out of a backup.
    """
    if not isinstance(meta, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in meta.items():
        name = str(key).lower()
        if any(hint in name for hint in _SECRET_HINTS):
            out[str(key)] = REDACTED
        elif isinstance(value, dict):
            out[str(key)] = redact(value)
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [redact(v) if isinstance(v, dict) else v
                             for v in value]
        else:
            out[str(key)] = value
    return out


def record(actor: str, action: str, target_type: str = "", target_id: str = "",
           result: str = OK, **meta) -> dict:
    """Write one entry. Never raises - a failed audit write mustn't break the
    action being audited, and callers shouldn't need their own try/except.
    """
    entry = {
        "id": "aud_" + uuid.uuid4().hex[:16],
        "ts": time.time(),
        "actor": str(actor or "")[:200],
        "action": str(action or "")[:120],
        "target_type": str(target_type or "")[:60],
        "target_id": str(target_id or "")[:120],
        "result": result if result in (OK, REFUSED, FAILED) else FAILED,
        "meta": redact(meta),
    }
    try:
        blob = json.dumps(entry["meta"], separators=(",", ":"))[:MAX_META_CHARS]
        conn = _conn()
        with _lock, conn:
            conn.execute(
                "INSERT INTO audit_log (id, ts, actor, action, target_type,"
                " target_id, result, meta) VALUES (?,?,?,?,?,?,?,?)",
                (entry["id"], entry["ts"], entry["actor"], entry["action"],
                 entry["target_type"], entry["target_id"], entry["result"],
                 blob))
    except Exception:
        # Swallowed on purpose: losing one audit row is bad, but refusing to
        # suspend an abusive account because the audit table is down is worse.
        pass
    return entry


def _row(r) -> dict:
    try:
        meta = json.loads(r["meta"]) if r["meta"] else {}
    except Exception:
        meta = {}
    return {
        "id": r["id"], "ts": r["ts"], "actor": r["actor"],
        "action": r["action"], "target_type": r["target_type"],
        "target_id": r["target_id"], "result": r["result"], "meta": meta,
    }


def recent(limit: int = 50, target_id: str = "", actor: str = "",
           action: str = "") -> list[dict]:
    """Newest first. Filters are ANDed; an empty filter is not applied."""
    limit = max(1, min(int(limit or 50), 500))
    where, params = [], []
    if target_id:
        where.append("target_id=?")
        params.append(target_id)
    if actor:
        where.append("actor=?")
        params.append(actor)
    if action:
        where.append("action=?")
        params.append(action)
    sql = "SELECT * FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    try:
        rows = _conn().execute(sql, tuple(params)).fetchall()
    except Exception:
        return []
    return [_row(r) for r in rows]


def count() -> int:
    try:
        return int(_conn().execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])
    except Exception:
        return 0


def stats() -> dict:
    """Counts only. `durable` says whether any of this survives the next
    rebuild; on the current free tier it doesn't.
    """
    durable = False
    try:
        from . import db
        durable = bool(db.stats().get("durable"))
    except Exception:
        durable = False
    return {
        "entries": count(),
        "durable": durable,
        "results": [OK, REFUSED, FAILED],
    }
