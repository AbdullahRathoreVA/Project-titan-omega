"""An append-only record of who did what to whom.

Titan already had two things that look like this and are not:

* ``core/obs.py`` — structured request logging. Goes to stdout, is not stored,
  and is gone when the container recycles.
* ``core/events.py`` — the live activity stream the dashboard renders. It is a
  feed for humans watching now, not a record for answering "who suspended this
  organisation, and when" three weeks later.

This is the third thing: a durable-as-the-database record of the actions that
change who can do what. It exists so that a privilege change is answerable
after the fact, which is the entire point of an audit log.

Decisions worth defending
-------------------------
* **There is no update, and there is no delete.** Not "there is one and it is
  guarded" — the functions do not exist. An audit log an administrator can
  edit is a log that proves nothing, and the cheapest way to guarantee that is
  to never write the code.
* **Secrets are redacted on the way in, not on the way out.** A value that
  reaches the table has already been stored; filtering at read time leaves it
  on disk and in every backup. The key names are matched loosely on purpose —
  a new field called ``api_secret`` should be caught by the rule that already
  exists rather than by somebody remembering to add it.
* **A failed action is recorded too.** Six refused attempts to remove an owner
  is the signal; recording only successes throws away the half worth alerting
  on.
* **It says whether it survives a rebuild.** On the current free-tier host it
  does not (``durable: false``), and a compliance record that quietly
  evaporates is worse than an absent one, because you would rely on it.

Nothing here decides anything. It records what ``core/orgs.py`` and
``core/identity.py`` already decided.
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

# Substrings, not exact names. Anything whose key contains one of these has its
# value replaced before it is written. Loose on purpose: the failure mode worth
# designing out is a field nobody thought to add to a list.
_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                 "authorization", "auth", "credential", "cookie", "session",
                 "private", "signature", "card", "cvv", "pan")

REDACTED = "[redacted]"

# Bounded so one runaway caller cannot turn the audit table into the whole
# database on a host with no persistent storage to begin with.
MAX_META_CHARS = 4000


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def redact(meta: Optional[dict]) -> dict:
    """Strip anything that looks like a credential, recursively.

    Applied before the row is written. A secret that reaches the table has
    already been persisted, and no amount of filtering at read time takes it
    back off the disk or out of last night's backup.
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
    """Write one entry. Never raises — a failed audit write must not be the
    thing that breaks the action being audited, and a caller that has to wrap
    this in try/except will eventually forget to."""
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
        # Deliberately swallowed. See the docstring: losing one audit row is
        # bad, and refusing to suspend an abusive account because the audit
        # table is unavailable is worse.
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
    """Measured counts only. `durable` says out loud whether any of this
    survives the next rebuild — on the current free tier it does not, and a
    compliance record you wrongly believe is kept is worse than none."""
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
