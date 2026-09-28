"""SQLite storage for Titan's state.

Replaces a single JSON file rewritten in full on every save, which had four
problems:

* No atomicity: a crash or container stop mid-write left a truncated file
  that failed to parse, losing every subsystem at once, accounts included.
* No concurrency control: the heartbeat, an audit and a signup could all save
  at once, and the last writer silently won.
* A full rewrite per save, so persisting one lead cost more as everything
  else grew.
* No schema or migrations.

Each subsystem keeps its ``export_state()`` / ``import_state()`` contract and
is stored as one JSON row in a ``state`` table. That fixes all four without
redesigning every subsystem's data at the same time. Moving individual
subsystems to real relational tables (accounts first) is a later, smaller
step.

WAL mode means readers are never blocked by the writer. ``synchronous=FULL``
is deliberate: the host can stop this container without warning, and losing
the last committed transaction to an OS buffer is exactly what this avoids.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

SCHEMA_VERSION = 9

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_path: Optional[str] = None


# --- migrations ------------------------------------------------------------
# Append-only. Each entry runs once, in order, inside a transaction, and the
# applied version is recorded. Never edit a shipped migration - add another.
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
    # The durable work queue. A real table rather than a JSON blob in `state`,
    # because a queue needs an atomic claim, an index on what's due, and rows that
    # survive the container being killed mid-job.
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
    # Self-improvement proposals. A table because the record has to be auditable:
    # who approved a change to Titan's behaviour, on what measured evidence, what
    # the value was before, and whether it was rolled back and why.
    #
    # `previous_value` is read from the live module at activation, not the shipped
    # default, because rollback has to restore what was actually running.
    (3, """
        CREATE TABLE IF NOT EXISTS proposals (
            id             TEXT PRIMARY KEY,
            param          TEXT NOT NULL,
            proposed_value REAL NOT NULL,
            baseline_value REAL,
            previous_value REAL,
            status         TEXT NOT NULL,
            reason         TEXT NOT NULL,
            evidence       TEXT,
            benchmark      TEXT,
            metric         TEXT,
            before_metric  REAL,
            after_metric   REAL,
            regression     INTEGER,
            approver       TEXT,
            decided_at     REAL,
            activated_at   REAL,
            rolled_back_at REAL,
            rollback_reason TEXT,
            automatic_rollback INTEGER NOT NULL DEFAULT 0,
            created_at     REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS proposals_status
            ON proposals (status, created_at);
        -- One open proposal per parameter. Two competing candidates for the
        -- same number cannot both be measured against the same baseline.
        CREATE UNIQUE INDEX IF NOT EXISTS proposals_one_open_per_param
            ON proposals (param)
            WHERE status IN ('proposed', 'evaluated', 'approved', 'active');
    """),
    # Real identity: people with passwords and roles, for organisations to build
    # on (see core/identity.py).
    #
    # A table rather than a JSON blob because a UNIQUE constraint on email is the
    # only way to guarantee two people can't register the same address under
    # concurrency.
    #
    # `pwhash` is self-describing (`pbkdf2_sha256$<iterations>$<salt>$<hash>`), so
    # the cost can be raised later and old hashes stay verifiable.
    (4, """
        CREATE TABLE IF NOT EXISTS users (
            id                  TEXT PRIMARY KEY,
            email               TEXT NOT NULL UNIQUE,
            pwhash              TEXT NOT NULL,
            role                TEXT NOT NULL,
            status              TEXT NOT NULL,
            created_at          REAL NOT NULL,
            last_login_at       REAL,
            password_changed_at REAL
        );
        CREATE INDEX IF NOT EXISTS users_role ON users (role);
    """),
    # Organisations: several people sharing one account with different privileges,
    # on top of the users table from migration 4. See core/orgs.py.
    #
    # `slug` is UNIQUE for the same reason as `users.email`: two organisations
    # can't have the same name, even under concurrency.
    #
    # Membership is keyed on user_id, not email, since an address can change. The
    # composite primary key makes "already a member" a constraint instead of a
    # race.
    (5, """
        CREATE TABLE IF NOT EXISTS orgs (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            slug       TEXT NOT NULL UNIQUE,
            status     TEXT NOT NULL,
            created_at REAL NOT NULL,
            created_by TEXT
        );
        CREATE TABLE IF NOT EXISTS org_members (
            org_id   TEXT NOT NULL,
            user_id  TEXT NOT NULL,
            role     TEXT NOT NULL,
            added_at REAL NOT NULL,
            PRIMARY KEY (org_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS org_members_user ON org_members (user_id);
        CREATE INDEX IF NOT EXISTS org_members_role ON org_members (org_id, role);
    """),
    # Who did what to whom. core/obs.py logs go to stdout and vanish on recycle;
    # core/events.py is a live feed. Neither answers "who suspended this
    # organisation, and when" weeks later.
    #
    # core/audit.py has no UPDATE or DELETE path at all; a log an administrator can
    # edit proves nothing.
    #
    # Indexed on ts DESC because every read is "most recent first", and on
    # target_id/actor for "what happened to this" and "what did this person do".
    (6, """
        CREATE TABLE IF NOT EXISTS audit_log (
            id          TEXT PRIMARY KEY,
            ts          REAL NOT NULL,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            target_type TEXT,
            target_id   TEXT,
            result      TEXT NOT NULL,
            meta        TEXT
        );
        CREATE INDEX IF NOT EXISTS audit_ts ON audit_log (ts DESC);
        CREATE INDEX IF NOT EXISTS audit_target ON audit_log (target_id, ts DESC);
        CREATE INDEX IF NOT EXISTS audit_actor ON audit_log (actor, ts DESC);
    """),
    # Subscription history. Churn and trial-to-paid conversion depend on how an
    # account changed over time, not its current state, and set_plan() overwrites
    # the plan in place - so without this those numbers can't be measured.
    #
    # Append-only like audit_log. `from_plan` is NULL for an account's first row,
    # which is what separates a signup from an upgrade.
    (7, """
        CREATE TABLE IF NOT EXISTS subscription_events (
            id         TEXT PRIMARY KEY,
            ts         REAL NOT NULL,
            email      TEXT NOT NULL,
            from_plan  TEXT,
            to_plan    TEXT NOT NULL,
            status     TEXT NOT NULL,
            granted    INTEGER NOT NULL DEFAULT 0,
            reason     TEXT
        );
        CREATE INDEX IF NOT EXISTS sub_events_ts ON subscription_events (ts DESC);
        CREATE INDEX IF NOT EXISTS sub_events_email
            ON subscription_events (email, ts DESC);
    """),
    # Feature flag overrides. Only the exceptions live here; a flag's default and
    # which plans include it are code in core/flags.py, since those are product
    # decisions that belong in code review.
    #
    # The composite primary key makes "set this flag for this user" idempotent
    # under concurrency. set_by and set_at record who changed it and when.
    (8, """
        CREATE TABLE IF NOT EXISTS feature_flags (
            key      TEXT NOT NULL,
            scope    TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            enabled  INTEGER NOT NULL,
            set_by   TEXT,
            set_at   REAL NOT NULL,
            PRIMARY KEY (key, scope, scope_id)
        );
        CREATE INDEX IF NOT EXISTS feature_flags_key ON feature_flags (key);
    """),
    # What a proposal did to the other numbers its benchmark measures, so a change
    # that improves one metric by worsening another can't be approved unnoticed.
    # JSON {metric: {"before", "after", "worse"}}.
    (9, """
        ALTER TABLE proposals ADD COLUMN guard_metrics TEXT;
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
    """Write several subsystems in one transaction.

    A save lands completely or not at all, so billing can never be written
    while the client registry it references is lost.
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
        # One corrupt row mustn't take the others down with it.
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
    """What's actually stored, for the founder screen and debugging."""
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
