"""Durable work queue, so crawls don't run on the request path.

Running a crawl inside the request or heartbeat that asked for it means the
work only exists in that process. A container recycled mid-audit (which a free
Hugging Face Space does often) loses it with no record and no retry. So this
is a real table with a real index rather than another JSON blob in `state`:

* Atomic claims. A job moves `queued -> running` under the same lock and
  transaction that reads it, so two workers can't take the same row.
* A lease, not a lock. A claimed job is leased for a bounded time; if the
  container dies the lease expires and the job goes back to `queued` instead
  of sitting in `running` forever.
* Attempts are counted and capped. A job that keeps failing becomes `dead`
  with its last error, instead of retrying forever against someone else's
  server.
* Exponential backoff, so a site that just returned 500 isn't hit four times
  in a second.
* Dedupe on open work only. A partial unique index covers `queued` and
  `running` rows, so the same audit can't be queued twice at once but can be
  queued again tomorrow.

`duration_ms` is wall time recorded between claim and finish, and None for a
job that hasn't finished. `stats()` counts rows with SELECT, so zero means
zero rows.

This is a single-process queue: durable across restarts, not distributed. Two
containers sharing one SQLite file over a network filesystem would be a much
harder problem, and Titan runs one container.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable, Optional

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
DEAD = "dead"

STATUSES = (QUEUED, RUNNING, DONE, FAILED, DEAD)

# How long a claimed job may run before its lease expires and it's offered
# again. Well above the slowest handler (a full site audit with sitemap and
# robots fetches).
LEASE_SECONDS = 300.0

# Retry backoff: 30s, 60s, 120s, ... capped, so a failing crawl never becomes
# a hot loop against a client's server.
BACKOFF_BASE = 30.0
BACKOFF_CAP = 3600.0

# Finished rows are kept for a while so the founder screen can show what
# happened, then trimmed - the container has 512MB.
KEEP_FINISHED_SECONDS = 7 * 86400
MAX_FINISHED_ROWS = 2000

_lock = threading.RLock()
_handlers: dict[str, Callable[[dict], Any]] = {}


def _conn():
    """The shared connection, opening it if the app hasn't already.

    `db.connect` returns the existing connection when the path matches, so
    this is cheap per operation and keeps the queue working in tests that
    point STATE_FILE at a temp directory.
    """
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


# ---------------------------------------------------------------- handlers --
def register(kind: str, handler: Callable[[dict], Any]) -> None:
    """Bind a job kind to the function that performs it.

    Separate from enqueueing on purpose: a job whose handler isn't registered
    yet stays `queued` rather than failing, so a later deploy that adds the
    handler picks up work already waiting.
    """
    with _lock:
        _handlers[kind] = handler


def registered() -> list[str]:
    with _lock:
        return sorted(_handlers)


# --------------------------------------------------------------- enqueueing --
def enqueue(kind: str, payload: Optional[dict] = None, *,
            dedupe_key: str = "", delay: float = 0.0,
            max_attempts: int = 3, priority: int = 5) -> dict:
    """Add work. Returns the job, or the existing one when deduped."""
    now = time.time()
    job_id = f"job-{uuid.uuid4().hex[:16]}"
    key = dedupe_key or None
    conn = _conn()
    with _lock:
        if key:
            row = conn.execute(
                "SELECT * FROM jobs WHERE dedupe_key=? AND status IN (?, ?)",
                (key, QUEUED, RUNNING)).fetchone()
            if row:
                return {**_row(row), "deduped": True}
        with conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, payload, status, attempts, "
                "max_attempts, priority, run_at, dedupe_key, created_at) "
                "VALUES (?,?,?,?,0,?,?,?,?,?)",
                (job_id, kind, json.dumps(payload or {}, default=str), QUEUED,
                 int(max_attempts), int(priority), now + max(0.0, delay), key,
                 now))
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return {**_row(row), "deduped": False}


# ----------------------------------------------------------------- claiming --
def reclaim_expired(now: Optional[float] = None) -> int:
    """Return jobs whose lease expired to the queue.

    A container killed mid-job leaves a `running` row nobody will finish;
    without this the row survives but the work never happens.
    """
    now = time.time() if now is None else now
    conn = _conn()
    with _lock, conn:
        cur = conn.execute(
            "UPDATE jobs SET status=?, worker=NULL, lease_until=NULL, "
            "error=COALESCE(error,'') || ? "
            "WHERE status=? AND lease_until IS NOT NULL AND lease_until < ?",
            (QUEUED, "[lease expired; the worker died mid-job] ", RUNNING, now))
        return cur.rowcount or 0


def claim(worker: str = "heartbeat", now: Optional[float] = None) -> Optional[dict]:
    """Atomically take the next due job, or None.

    The SELECT and UPDATE share one transaction and lock, and the UPDATE
    re-checks the status, so a row can't be claimed twice.
    """
    now = time.time() if now is None else now
    conn = _conn()
    with _lock, conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status=? AND run_at<=? "
            "ORDER BY priority ASC, run_at ASC LIMIT 1",
            (QUEUED, now)).fetchone()
        if not row:
            return None
        cur = conn.execute(
            "UPDATE jobs SET status=?, worker=?, lease_until=?, attempts=attempts+1, "
            "started_at=COALESCE(started_at, ?) WHERE id=? AND status=?",
            (RUNNING, worker, now + LEASE_SECONDS, now, row["id"], QUEUED))
        if not cur.rowcount:
            return None
        claimed = conn.execute("SELECT * FROM jobs WHERE id=?",
                               (row["id"],)).fetchone()
    return _row(claimed)


# ---------------------------------------------------------------- finishing --
def complete(job_id: str, result: Any = None) -> Optional[dict]:
    now = time.time()
    conn = _conn()
    with _lock, conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        started = row["started_at"]
        conn.execute(
            "UPDATE jobs SET status=?, finished_at=?, duration_ms=?, "
            "result=?, error=NULL, lease_until=NULL WHERE id=?",
            (DONE, now,
             # Measured, not estimated. None if the job somehow never started.
             (now - started) * 1000.0 if started else None,
             json.dumps(result, default=str)[:4000] if result is not None else None,
             job_id))
        out = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(out)


def fail(job_id: str, error: str) -> Optional[dict]:
    """Record a failure and either schedule a retry or bury the job."""
    now = time.time()
    conn = _conn()
    with _lock, conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        attempts, cap = row["attempts"], row["max_attempts"]
        if attempts >= cap:
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, duration_ms=?, "
                "error=?, lease_until=NULL WHERE id=?",
                (DEAD, now,
                 (now - row["started_at"]) * 1000.0 if row["started_at"] else None,
                 str(error)[:2000], job_id))
        else:
            delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** max(0, attempts - 1)))
            conn.execute(
                "UPDATE jobs SET status=?, run_at=?, error=?, lease_until=NULL, "
                "worker=NULL WHERE id=?",
                (QUEUED, now + delay, str(error)[:2000], job_id))
        out = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(out)


# ------------------------------------------------------------------ running --
def run_one(worker: str = "heartbeat") -> Optional[dict]:
    """Claim and execute one job. Never raises."""
    job = claim(worker)
    if not job:
        return None
    handler = _handlers.get(job["kind"])
    if handler is None:
        # Not a failure - the handler may arrive in the next deploy. Requeue it with a
        # delay rather than burn an attempt.
        _requeue_unhandled(job["id"])
        return {**job, "status": QUEUED, "note": "no handler registered yet"}
    try:
        result = handler(job["payload"])
        return complete(job["id"], result)
    except Exception as exc:
        return fail(job["id"], f"{type(exc).__name__}: {exc}")


def _requeue_unhandled(job_id: str) -> None:
    conn = _conn()
    with _lock, conn:
        conn.execute(
            "UPDATE jobs SET status=?, run_at=?, attempts=MAX(0, attempts-1), "
            "lease_until=NULL, worker=NULL, error=? WHERE id=?",
            (QUEUED, time.time() + 60.0,
             "No handler registered for this kind yet.", job_id))


def drain(limit: int = 5, worker: str = "heartbeat") -> dict:
    """Run up to `limit` jobs. The heartbeat's entry point.

    Bounded so a deep backlog can't monopolise the heartbeat, which ticks
    every few seconds.
    """
    reclaimed = reclaim_expired()
    ran, done, failed = 0, 0, 0
    for _ in range(max(1, limit)):
        out = run_one(worker)
        if out is None:
            break
        ran += 1
        if out.get("status") == DONE:
            done += 1
        elif out.get("status") in (FAILED, DEAD):
            failed += 1
    return {"ran": ran, "done": done, "failed": failed,
            "reclaimed": reclaimed, "pending": pending_count()}


# ------------------------------------------------------------------ reading --
def _row(row) -> dict:
    out = dict(row)
    try:
        out["payload"] = json.loads(out.get("payload") or "{}")
    except Exception:
        out["payload"] = {}
    if out.get("result"):
        try:
            out["result"] = json.loads(out["result"])
        except Exception:
            pass
    return out


def get(job_id: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(row) if row else None


def pending_count() -> int:
    row = _conn().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status IN (?, ?)",
        (QUEUED, RUNNING)).fetchone()
    return int(row["n"])


def recent(limit: int = 50, kind: str = "", status: str = "") -> list[dict]:
    sql = "SELECT * FROM jobs"
    where, args = [], []
    if kind:
        where.append("kind=?")
        args.append(kind)
    if status:
        where.append("status=?")
        args.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit))
    return [_row(r) for r in _conn().execute(sql, args).fetchall()]


def stats() -> dict:
    """Counts from actual rows. Zero means zero rows."""
    from . import db
    conn = _conn()
    counts = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM jobs "
                          "GROUP BY status").fetchall():
        counts[r["status"]] = int(r["n"])
    # Only over jobs that finished - an unfinished job has no duration, and
    # counting it as zero would drag every average down.
    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(duration_ms) AS avg_ms, MAX(duration_ms) AS max_ms "
        "FROM jobs WHERE duration_ms IS NOT NULL").fetchone()
    measured = int(row["n"] or 0)
    oldest = conn.execute(
        "SELECT MIN(run_at) AS t FROM jobs WHERE status=?", (QUEUED,)).fetchone()
    try:
        durable = bool(db.stats().get("durable"))
    except Exception:
        durable = False
    return {
        "counts": counts,
        "pending": counts[QUEUED] + counts[RUNNING],
        "handlers": registered(),
        "measured_runs": measured,
        # None, not 0.0: "no job has finished yet" isn't "jobs take no time".
        "avg_duration_ms": round(row["avg_ms"], 1) if measured else None,
        "max_duration_ms": round(row["max_ms"], 1) if measured else None,
        "oldest_pending_age_s": (round(time.time() - oldest["t"], 1)
                                 if oldest and oldest["t"] else None),
        "durable": durable,
        "note": ("Durations are wall time measured between claim and finish, "
                 "over the " + str(measured) + " job(s) that have actually "
                 "finished." + ("" if durable else
                                " Storage is not durable in this deployment: "
                                "a rebuild would empty this queue.")),
    }


# ------------------------------------------------------------ housekeeping --
def trim(now: Optional[float] = None) -> int:
    """Drop old finished rows. The container has 512MB."""
    now = time.time() if now is None else now
    conn = _conn()
    with _lock, conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE status IN (?,?,?) AND finished_at < ?",
            (DONE, FAILED, DEAD, now - KEEP_FINISHED_SECONDS))
        removed = cur.rowcount or 0
        cur = conn.execute(
            "DELETE FROM jobs WHERE id IN ("
            "  SELECT id FROM jobs WHERE status IN (?,?,?) "
            "  ORDER BY finished_at DESC LIMIT -1 OFFSET ?)",
            (DONE, FAILED, DEAD, MAX_FINISHED_ROWS))
        return removed + (cur.rowcount or 0)


def reset() -> None:
    """Test seam. Clears the table and the handler registry."""
    conn = _conn()
    with _lock, conn:
        conn.execute("DELETE FROM jobs")
        _handlers.clear()
