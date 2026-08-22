"""Durable state on a free private Hugging Face Dataset repo.

The problem this solves
-----------------------
A free Space has an ephemeral filesystem. ``/tmp`` is wiped on every rebuild,
which takes with it every account, organisation, audit row and — worst —
``site_fix``'s snapshots of the previous content of pages Titan has changed on
somebody's live website. Losing that store does not merely lose history, it
loses the ability to undo a change Titan made to another business.

Hugging Face's own answer is persistent storage mounted at ``/data``, which is
a paid add-on. Their *other* documented answer costs nothing: **a Dataset repo
is a durable store, and a Space can push to one.** The Hub docs say it plainly
— "use a dataset as a data store" for anything that must outlive the Space.
A private Dataset repo is free.

Why not ``CommitScheduler``
---------------------------
``huggingface_hub`` ships a ``CommitScheduler`` for exactly this, and it is the
wrong tool here. Its contract is **append-only**: the docs warn that
"deleting or overwriting a file might corrupt your repository", and it uploads
whatever is in a watched folder on a timer. A SQLite database is the opposite
of append-only — it is rewritten in place, constantly, including while the
uploader is reading it. Watching the live database directly would ship torn
files.

So this pushes a **verified snapshot** instead. ``core/backup.py`` already
takes a consistent copy through SQLite's own backup API and proves it by
restoring it into a scratch database and counting the rows. Only a backup that
passed that check is ever uploaded. The upload itself is a plain
``upload_file`` — a git commit replacing one blob, which is safe to overwrite
in a way the scheduler's incremental diffing is not.

What this is honestly worth
---------------------------
It is **not** continuous durability. It is snapshot durability with a recovery
point equal to the backup interval: a rebuild loses at most the work since the
last successful push, and :func:`status` reports that window rather than
implying otherwise. Persistent storage is still better. This is free.

Restoring only ever happens **towards** an empty database. If a state file
already exists locally, nothing is pulled — overwriting a live database with an
older snapshot is the one direction that can destroy data, so it is not a code
path that exists.

Configuration (all free)
------------------------
* ``HF_TOKEN`` — a write token, set as a Space secret. Already required by the
  deploy path.
* ``TITAN_STATE_REPO`` — e.g. ``careermind2026/titan-state``. Created private
  and automatically on first push.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# One well-known name. The repo keeps the history; the working copy is always
# "the latest", so a restore never has to guess which file it wants.
STATE_FILENAME = "titan_state.db"
MANIFEST_FILENAME = "titan_state.manifest.json"

_lock = threading.RLock()

# Set by a successful push, read by status(). Proof, not intent: a token being
# present says somebody meant to configure this, and says nothing about whether
# a byte ever reached the Hub.
_last_push: dict = {}


def token() -> str:
    return (os.getenv("HF_TOKEN", "") or os.getenv("TITAN_HF_TOKEN", "")).strip()


def repo_id() -> str:
    """Where snapshots go.

    Defaults to ``<owner>/titan-state``, derived from ``SPACE_ID``, which
    Hugging Face sets on every Space automatically. That is deliberate: the
    fewer variables somebody has to get exactly right at 2am, the fewer ways
    this silently does nothing. Setting ``TITAN_STATE_REPO`` overrides it.
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
        # Only reachable off-Space: on a Space, SPACE_ID supplies the default.
        out.append("TITAN_STATE_REPO")
    return out


def _api():
    # Imported inside the function, never at module load. reportlab took the
    # whole API down once by being imported at module level and absent; a
    # missing huggingface_hub must degrade to "not configured", not to a dead
    # deployment.
    from huggingface_hub import HfApi
    return HfApi(token=token())


# ------------------------------------------------------------------- push --
def push(path: str, *, note: str = "") -> dict:
    """Upload one verified snapshot. Never raises.

    `path` must be a backup that ``core/backup.py`` has already verified. This
    function does not check that for you, and deliberately does not verify it
    itself: a second opinion computed from the same file by the same process is
    not an independent one.
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

    **Refuses if `dest` already exists.** Overwriting a live database with an
    older snapshot is the one direction that loses data, so it is not
    something this function can be asked to do.
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
        # Copy rather than move: hf_hub_download returns a path inside its own
        # cache, and moving it out from under the cache makes the next call
        # re-download a file it believes it already has.
        shutil.copyfile(cached, dest)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "reason": f"could not place the snapshot: {exc}"}

    return {"ok": True, "bytes": os.path.getsize(dest), "repo": repo_id()}


def remote_manifest() -> Optional[dict]:
    """What the Hub currently holds, or None. Used to prove a snapshot exists
    rather than assuming one does because a token is set."""
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

    `check_remote` costs a network round trip, so it is off by default and the
    caller decides. Without it this reports what THIS process has done, which
    is the honest local answer.
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
        "cost": "free — a private Hugging Face Dataset repo",
    }

    if check_remote:
        manifest = remote_manifest()
        out["remote_snapshot"] = manifest
        out["has_remote_snapshot"] = manifest is not None
    return out


def recovery_window_seconds() -> Optional[float]:
    """How much work a rebuild would lose, from the backup interval.

    None when nothing is configured — an unknown window is not a zero one.
    """
    if not configured():
        return None
    try:
        return float(os.getenv("TITAN_BACKUP_INTERVAL", str(6 * 3600)))
    except ValueError:
        return float(6 * 3600)
