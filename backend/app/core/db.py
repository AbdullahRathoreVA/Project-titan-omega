"""SQLite storage for Titan's state.

Replaces a single JSON file that was rewritten in full on every save. That file
was the largest risk in the system, and the risk was data loss rather than
speed:

* **No atomicity.** A crash or a container stop mid-write left a truncated file
  that failed to parse — losing every subsystem at once, including accounts.
* **No concurrency control.** The heartbeat, an audit and a signup could all
  call save() at the same moment; last writer won, silently.
* **Full rewrite per save.** Every save serialised all fifteen subsystems,
  so the cost of persisting one lead grew with the size of everything else.
* **No schema and no migrations.** Any change to a stored shape risked the
  account table with no way to roll forward or back.

The design here is deliberately conservative. Each subsystem keeps its existing
``export_state()`` / ``import_state()`` contract and is stored as one row of
JSON in a ``state`` table. That fixes all four failure modes above without
rewriting fifteen modules in one commit — a change that touches billing,
transcripts and evidence simultaneously should not also be the change that
redesigns their shapes.

Moving individual subsystems to real relational tables (accounts first) is a
later, smaller, safer step, and this is the foundation that makes it possible.

WAL mode is on so a reader is never blocked by the writer. ``synchronous=FULL``
is deliberate: this container can be stopped without warning by the host, and
losing the last committed transaction to an OS buffer is exactly the failure
being designed out.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

SCHEMA_VERSION = 2

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_path: Optional[str] = None


# --- migrations ------------------------------------------------------------
# Append-only. Each entry runs once, in order, inside a transaction, and the
# applied version is recorded. Never edit a shipped migration — add another.
MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """),
    # The durable work queue. A real table rather than another JSON blob in
    # `state`, because a queue needs exactly what a blob cannot give: an atomic
    # claim, an index on what is due, and a row that survives the container
    # being killed halfway through the work.
    (2, """
        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            payload      TEXT NOT NULL,
            status       TEXT NOT NULL,
            attempts     INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            priority     INTEGER NOT NULL DEFAULT 5,
            run_at       REAL NOT NULL,
            lease_until  REAL,
            worker       TEXT,
            dedupe_key   TEXT,
            created_at   REAL NOT NULL,
            started_at   REAL,
            finished_at  REAL,
            duration_ms  REAL,
            result       TEXT,
            error        TEXT
        );
        CREATE INDEX IF NOT EXISTS jobs_due
            ON jobs (status, run_at, priority);
        CREATE INDEX IF NOT EXISTS jobs_lease
            ON jobs (status, lease_until);
        -- Uniqueness only among work not yet finished, so the same audit can
        -- be queued again tomorrow but never twice at once.
        CREATE UNIQUE INDEX IF NOT EXISTS jobs_dedupe_open
            ON jobs (dedupe_key)
            WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running');
    """),
]


def connect(path: str) -> sqlite3.Connection:
    """Open (or reopen) the database at `path` and bring the schema up to date."""
    global _conn, _path
    with _lock:
        if _conn is not None and _path == path:
            return _conn
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # check_same_thread=False: the heartbeat runs cycles on worker threads
        # via asyncio.to_thread, and every access here is already under _lock.
        conn = sqlite3.connect(path, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        _conn, _path = conn, path
        _migrate(conn)
        return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version "
                 "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = (row["v"] if row and row["v"] is not None else 0)
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        with conn:                      # one transaction per migration
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version, applied_at) "
                         "VALUES (?, ?)", (version, time.time()))


def version(path: Optional[str] = None) -> int:
    conn = connect(path) if path else _require()
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0)


def _require() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not connected — call connect(path) first.")
    return _conn


# --- state access ----------------------------------------------------------
def put(key: str, value: Any) -> None:
    """Write one subsystem's state. Atomic, and independent of every other."""
    conn = _require()
    blob = json.dumps(value, default=str)
    with _lock, conn:
        conn.execute(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, blob, time.time()))


def put_many(items: dict[str, Any]) -> None:
    """Write several subsystems in ONE transaction.

    This is the property the JSON file could not offer: a save either lands
    completely or not at all, so billing can never be written while the client
    registry that references it is lost.
    """
    conn = _require()
    now = time.time()
    rows = [(k, json.dumps(v, default=str), now) for k, v in items.items()]
    with _lock, conn:
        conn.executemany(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at", rows)


def get(key: str, default: Any = None) -> Any:
    conn = _require()
    with _lock:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        # A single corrupt row must not take the others down with it.
        return default


def all_state() -> dict[str, Any]:
    conn = _require()
    with _lock:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
    out: dict[str, Any] = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            continue
    return out


def stats() -> dict:
    """What is actually stored, for the founder screen and for debugging."""
    conn = _require()
    with _lock:
        rows = conn.execute(
            "SELECT key, LENGTH(value) AS bytes, updated_at FROM state "
            "ORDER BY bytes DESC").fetchall()
        ver = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    total = sum(r["bytes"] for r in rows)
    return {
        "path": _path,
        "schema_version": int(ver["v"] or 0),
        "subsystems": [{"key": r["key"], "bytes": r["bytes"],
                        "updated_at": r["updated_at"]} for r in rows],
        "total_bytes": total,
        "durable": bool(_path and not _path.startswith(
            __import__("tempfile").gettempdir())),
    }


def close() -> None:
    global _conn, _path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn, _path = None, None
