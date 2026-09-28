"""Durable state in a free, private Hugging Face Dataset repo.

A free Space has an ephemeral filesystem: ``/tmp`` is wiped on every rebuild,
along with every account, organisation and audit row, and ``site_fix``'s
snapshots of pages Titan changed on someone's live site. Losing those means
losing the ability to undo those changes.

Hugging Face's persistent storage at ``/data`` is a paid add-on. Their other
documented option is free: a Space can push to a Dataset repo and use it as a
data store, and a private Dataset repo costs nothing.

Why not ``CommitScheduler``
---------------------------
``huggingface_hub``'s ``CommitScheduler`` is append-only - the docs warn that
deleting or overwriting a file might corrupt the repository - and it uploads
a watched folder on a timer. A SQLite database is rewritten in place
constantly, including while the uploader reads it, so watching it directly
would ship torn files.

Instead this pushes a verified snapshot. ``core/backup.py`` takes a
consistent copy with SQLite's backup API and checks it by restoring it into a
scratch database and counting rows; only a backup that passes is uploaded.
The upload is a plain ``upload_file`` commit replacing one blob, which is safe
to overwrite.

Limits
------
This is snapshot durability, not continuous: a rebuild loses at most the work
since the last successful push, and :func:`status` reports that window.
Persistent storage would be better; this is free.

Restoring only ever happens into an empty database. If a state file already
exists locally nothing is pulled, since overwriting a live database with an
older snapshot is the one direction that destroys data.

Configuration (all free)
------------------------
* ``HF_TOKEN`` - a write token, set as a Space secret. Already needed for
  deploys.
* ``TITAN_STATE_REPO`` - e.g. ``careermind2026/titan-state``. Created
  private, automatically, on the first push.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# One fixed filename. The repo keeps the history; the working copy is always
# the latest, so a restore never has to guess.
STATE_FILENAME = "titan_state.db"
MANIFEST_FILENAME = "titan_state.manifest.json"

_lock = threading.RLock()

# Set by a successful push and read by status(). A token being present only
# shows intent; this shows a snapshot actually reached the Hub.
_last_push: dict = {}

# What happened to the restore on this container's boot. Recorded for every
# outcome, including "a local file already existed" and "no token set", so an
# empty dict can only mean the boot code never ran.
_last_restore: dict = {}


def token() -> str:
    return (os.getenv("HF_TOKEN", "") or os.getenv("TITAN_HF_TOKEN", "")).strip()


def repo_id() -> str:
    """Where snapshots go.

    Defaults to ``<owner>/titan-state``, derived from ``SPACE_ID``, which
    Hugging Face sets on every Space - fewer variables to get right means
    fewer ways for this to silently do nothing. ``TITAN_STATE_REPO``
    overrides it.
    """
    explicit = os.getenv("TITAN_STATE_REPO", "").strip()
    if explicit:
        return explicit
    space = os.getenv("SPACE_ID", "").strip()
    if "/" in space:
        return f"{space.split('/', 1)[0]}/titan-state"
    return ""


def configured() -> bool:
    return bool(token() and repo_id())


def missing() -> list:
    """What still has to be set. Both are free."""
    out = []
    if not token():
        out.append("HF_TOKEN")
    if not repo_id():
        # Only reachable off-Space; on a Space, SPACE_ID supplies the default.
        out.append("TITAN_STATE_REPO")
    return out


def _api():
    # Imported inside the function, never at module load, so a missing
    # huggingface_hub means "not configured" rather than a failed startup.
    from huggingface_hub import HfApi
    return HfApi(token=token())


# ------------------------------------------------------------------- push --
def push(path: str, *, note: str = "") -> dict:
    """Upload one verified snapshot. Never raises.

    `path` must be a backup that ``core/backup.py`` has already verified. It
    isn't re-verified here: a second check of the same file by the same
    process isn't an independent one.
    """
    if not configured():
        return {"ok": False, "reason": "not configured",
                "missing": missing()}
    if not path or not os.path.exists(path):
        return {"ok": False, "reason": f"no such snapshot: {path}"}

    size = os.path.getsize(path)
    started = time.time()
    try:
        import json as _json

        api = _api()
        api.create_repo(repo_id=repo_id(), repo_type="dataset", private=True,
                        exist_ok=True)
        api.upload_file(path_or_fileobj=path, path_in_repo=STATE_FILENAME,
                        repo_id=repo_id(), repo_type="dataset",
                        commit_message=f"state snapshot {int(started)}"
                                       + (f" ({note})" if note else ""))
        manifest = {
            "pushed_at": started,
            "bytes": size,
            "note": note,
            "source": os.path.basename(path),
        }
        api.upload_file(
            path_or_fileobj=_json.dumps(manifest, indent=2).encode(),
            path_in_repo=MANIFEST_FILENAME, repo_id=repo_id(),
            repo_type="dataset",
            commit_message=f"manifest {int(started)}")
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:200], "bytes": size}

    with _lock:
        _last_push.clear()
        _last_push.update({"at": started, "bytes": size,
                           "duration_s": round(time.time() - started, 2),
                           "repo": repo_id()})
    return {"ok": True, "bytes": size, "repo": repo_id(),
            "duration_s": round(time.time() - started, 2)}


# ------------------------------------------------------------------- pull --
def pull(dest: str) -> dict:
    """Download the latest snapshot to `dest`. Never raises.

    Refuses if `dest` already exists: overwriting a live database with an
    older snapshot is the one direction that loses data.
    """
    if not configured():
        return {"ok": False, "reason": "not configured", "missing": missing()}
    if os.path.exists(dest):
        return {"ok": False, "reason": "a state file already exists locally; "
                                       "refusing to overwrite it with a "
                                       "snapshot"}
    try:
        from huggingface_hub import hf_hub_download

        cached = hf_hub_download(repo_id=repo_id(), repo_type="dataset",
                                 filename=STATE_FILENAME, token=token())
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:200]}

    try:
        import shutil
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        # Copy rather than move: hf_hub_download returns a path inside its cache, and
        # moving it would make the next call re-download a file it thinks it has.
        shutil.copyfile(cached, dest)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "reason": f"could not place the snapshot: {exc}"}

    return {"ok": True, "bytes": os.path.getsize(dest), "repo": repo_id()}


def record_restore(outcome: str, detail: dict | None = None) -> None:
    """Remember how the boot restore went, so it can be asked about later.

    Called for every outcome, not just failures; otherwise "restore skipped"
    would look the same as "restore code never ran".
    """
    import time as _time
    _last_restore.clear()
    _last_restore.update({"at": _time.time(), "outcome": outcome,
                          **(detail or {})})


def last_restore() -> dict | None:
    """What happened on this container's boot, or None if nothing recorded."""
    return dict(_last_restore) or None


def remote_manifest() -> Optional[dict]:
    """What the Hub currently holds, or None. Proves a snapshot exists rather
    than assuming it does because a token is set.
    """
    if not configured():
        return None
    try:
        import json as _json

        from huggingface_hub import hf_hub_download

        path = hf_hub_download(repo_id=repo_id(), repo_type="dataset",
                               filename=MANIFEST_FILENAME, token=token())
        with open(path, encoding="utf-8") as handle:
            return _json.load(handle)
    except Exception:
        return None


# ----------------------------------------------------------------- status --
def status(*, check_remote: bool = False) -> dict:
    """Where the state actually lives, and what would be lost.

    `check_remote` costs a network round trip, so it's off by default. Without
    it this reports what this process has done.
    """
    from .. import persistence

    local = persistence.STATE_FILE
    import tempfile
    on_temp = bool(local and local.startswith(tempfile.gettempdir()))

    out = {
        "configured": configured(),
        "missing": missing(),
        "repo": repo_id() or None,
        "local_path": local,
        "local_is_ephemeral": on_temp,
        "last_push": dict(_last_push) or None,
        # Whether the accounts came back on this boot. A backup that's never been
        # seen to restore can't be relied on.
        "last_restore": dict(_last_restore) or None,
        "cost": "free — a private Hugging Face Dataset repo",
    }

    if check_remote:
        manifest = remote_manifest()
        out["remote_snapshot"] = manifest
        out["has_remote_snapshot"] = manifest is not None
    return out


def recovery_window_seconds() -> Optional[float]:
    """How much work a rebuild would lose, based on the backup interval.

    None when nothing is configured - an unknown window isn't zero.
    """
    if not configured():
        return None
    try:
        return float(os.getenv("TITAN_BACKUP_INTERVAL", str(6 * 3600)))
    except ValueError:
        return float(6 * 3600)
