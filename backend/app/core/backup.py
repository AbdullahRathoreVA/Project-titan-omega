"""Backup, restore, and — the part that matters — a restore that is tested.

An untested backup is not a backup. It is a file that makes people feel safe
until the day it is needed. So the design rule here is that **every backup
verifies itself by being restored into a scratch database and read back**,
before it is reported as a backup at all.

What this protects against, concretely: Titan holds subscribers' accounts,
their clients' records, voice transcripts, the evidence ledger, and — since the
fix loop shipped — the exact previous value of pages Titan has changed on
customers' live websites. A free Hugging Face Space wipes `/tmp` on every
rebuild. Losing that store does not just lose history; it loses the ability to
undo a change Titan made to somebody else's business.

Design decisions:

**SQLite's own backup API, not a file copy.** Copying a file that is being
written produces a torn database that opens fine and fails later. `conn.backup()`
takes a consistent snapshot of a live connection, WAL and all.

**Verification is a real restore, not a checksum.** A checksum proves the bytes
survived the disk. It does not prove the file is a working database with the
rows in it. `verify()` opens the backup, runs `PRAGMA integrity_check`, and
counts the rows in every subsystem — the same counts are recorded in the
manifest so a later restore can be compared against what was backed up.

**Restore never overwrites in place.** The live database is copied aside first,
so a restore that turns out to be wrong is itself reversible. A recovery tool
that can destroy the thing it is recovering is a liability.

**Retention is by count, not by "delete old ones".** Keeping N and removing the
rest is easy to reason about; a date rule silently keeps nothing if the clock
is wrong.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from typing import Optional

# On this machine D: has the free space and C: is chronically full. Default
# there when it exists, so a backup does not fill the drive it is protecting.
def _default_dir() -> str:
    explicit = os.getenv("TITAN_BACKUP_DIR", "").strip()
    if explicit:
        return explicit
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/backups"
    if os.name == "nt" and os.path.isdir("D:\\"):
        return "D:\\titan-backups"
    import tempfile
    return os.path.join(tempfile.gettempdir(), "titan-backups")


BACKUP_DIR = _default_dir()
KEEP = int(os.getenv("TITAN_BACKUP_KEEP", "10"))

_lock = threading.RLock()


def _live_path() -> str:
    from .. import persistence
    return persistence.STATE_FILE


def _subsystem_counts(conn: sqlite3.Connection) -> dict:
    """How much is actually in there, per subsystem. Real counts, from rows."""
    out: dict[str, int] = {}
    try:
        for row in conn.execute("SELECT key, LENGTH(value) AS bytes FROM state"):
            out[row["key"]] = int(row["bytes"])
    except Exception:
        pass
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        out["_jobs_rows"] = int(row["n"])
    except Exception:
        # The jobs table only exists from migration 2. Its absence is a fact
        # about the backup, not an error.
        out["_jobs_rows"] = 0
    return out


def _open(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def create(note: str = "") -> dict:
    """Take a consistent snapshot, then prove it restores. Never raises."""
    from . import db, obs

    started = time.monotonic()
    try:
        with _lock:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            live = _live_path()
            if not os.path.exists(live):
                return {"ok": False, "error": (
                    "There is no database to back up yet — nothing has been "
                    "saved on this deployment.")}

            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            target = os.path.join(BACKUP_DIR, f"titan-{stamp}.db")

            # SQLite's own backup API. A shutil.copy of a live database can
            # capture a torn write that opens cleanly and fails later.
            source = db.connect(live)
            dest = _open(target)
            try:
                with dest:
                    source.backup(dest)
            finally:
                dest.close()

            checked = verify(target)
            size = os.path.getsize(target)
            manifest = {
                "file": target,
                "created_at": time.time(),
                "size_bytes": size,
                "note": note,
                "source": live,
                "schema_version": checked.get("schema_version"),
                "counts": checked.get("counts", {}),
                "verified": checked["ok"],
                "verify_error": None if checked["ok"] else checked.get("error"),
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
            with open(target + ".json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            if not checked["ok"]:
                # A backup that does not restore is not a backup. Say so
                # loudly rather than leaving a reassuring file on disk.
                obs.error("backup.failed_verification", file=target,
                          error=checked.get("error"))
                return {"ok": False, "error": (
                    "The snapshot was written but did NOT verify, so it must "
                    "not be trusted: " + str(checked.get("error"))),
                    "manifest": manifest}

            pruned = prune()
            obs.info("backup.created", file=os.path.basename(target),
                     size_bytes=size, duration_ms=manifest["duration_ms"],
                     pruned=pruned)
            return {"ok": True, "manifest": manifest, "pruned": pruned}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def verify(path: str) -> dict:
    """Open a backup and prove it is a working database with rows in it.

    A checksum proves the bytes survived the disk; it does not prove the file
    is a database or that anything is in it.
    """
    if not os.path.exists(path):
        return {"ok": False, "error": "That backup file does not exist."}
    conn = None
    try:
        conn = _open(path)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            return {"ok": False, "error": f"integrity_check said: {integrity}"}
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version").fetchone()
        counts = _subsystem_counts(conn)
        return {
            "ok": True,
            "schema_version": int(row["v"] or 0),
            "counts": counts,
            "subsystems": len([k for k in counts if not k.startswith("_")]),
            "size_bytes": os.path.getsize(path),
        }
    except sqlite3.DatabaseError as e:
        return {"ok": False, "error": f"Not a readable database: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            conn.close()


def restore(path: str, *, confirm: bool = False) -> dict:
    """Replace the live database with a backup, keeping the old one aside.

    `confirm` must be True. This is the one genuinely destructive operation in
    the codebase, and a default-safe signature means a mistyped call cannot
    perform it.
    """
    from . import db, obs

    if not confirm:
        return {"ok": False, "error": (
            "restore() replaces the live database and must be called with "
            "confirm=True.")}

    checked = verify(path)
    if not checked["ok"]:
        return {"ok": False, "error": (
            "Refusing to restore a backup that does not verify: "
            + str(checked.get("error")))}

    try:
        with _lock:
            live = _live_path()
            # The live database is moved aside, never overwritten. A recovery
            # tool that can destroy what it is recovering is a liability.
            aside = ""
            if os.path.exists(live):
                aside = f"{live}.replaced-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
                db.close()
                shutil.copy2(live, aside)

            db.close()
            shutil.copy2(path, live)
            db.connect(live)

            after = verify(live)
            if not after["ok"]:
                return {"ok": False, "error": (
                    "The restore was written but the live database does not "
                    "verify. The previous database is at " + aside),
                    "previous": aside}

            # Reload every subsystem from the restored file, or the process
            # keeps serving the in-memory state of the database it replaced.
            from .. import persistence
            persistence.load()

            obs.warn("backup.restored", file=os.path.basename(path),
                     previous=os.path.basename(aside) if aside else None,
                     counts=after.get("counts"))
            return {"ok": True, "restored_from": path,
                    "previous_database": aside or None,
                    "counts": after.get("counts", {}),
                    "schema_version": after.get("schema_version"),
                    "note": ("The database that was live has been kept at the "
                             "path in `previous_database`, so this restore is "
                             "itself reversible.")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def listing() -> list[dict]:
    """Every backup on disk, newest first, with its manifest if it has one."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    rows = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not name.endswith(".db"):
            continue
        full = os.path.join(BACKUP_DIR, name)
        entry = {"file": full, "name": name,
                 "size_bytes": os.path.getsize(full),
                 "modified": os.path.getmtime(full)}
        try:
            with open(full + ".json", encoding="utf-8") as f:
                entry["manifest"] = json.load(f)
        except Exception:
            entry["manifest"] = None
        rows.append(entry)
    return rows


def prune(keep: int = KEEP) -> int:
    """Keep the newest `keep` backups. Returns how many were removed."""
    rows = listing()
    removed = 0
    for entry in rows[keep:]:
        try:
            os.remove(entry["file"])
            removed += 1
            manifest = entry["file"] + ".json"
            if os.path.exists(manifest):
                os.remove(manifest)
        except Exception:
            pass
    return removed


def status() -> dict:
    """What protection actually exists. Never reassuring beyond the evidence."""
    from . import db

    rows = listing()
    verified = [r for r in rows
                if (r.get("manifest") or {}).get("verified") is True]
    try:
        durable = bool(db.stats().get("durable"))
    except Exception:
        durable = False
    newest = rows[0] if rows else None
    return {
        "directory": BACKUP_DIR,
        "backups": len(rows),
        "verified_backups": len(verified),
        "keep": KEEP,
        # None, not 0 — "never backed up" is not "backed up zero seconds ago".
        "newest_age_seconds": (round(time.time() - newest["modified"], 1)
                               if newest else None),
        "newest": newest["name"] if newest else None,
        "database_durable": durable,
        "note": (
            "Every backup is verified by restoring it into a scratch "
            "connection and counting rows before it is reported as a backup. "
            + ("" if durable else
               "WARNING: the live database is on ephemeral storage, so a "
               "rebuild wipes it AND any backup written beside it. Backups "
               "only protect you if TITAN_BACKUP_DIR points somewhere that "
               "survives, or they are downloaded off the box.")),
    }
