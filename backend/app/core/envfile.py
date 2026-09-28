"""Load a local .env into the process environment. Stdlib only.

Saves exporting keys on the command line, which is how secrets end up in
shell history and screenshots.

- The real environment wins: a variable already in os.environ is never
  overwritten, so a stray .env in an image can't shadow a production secret.
- Values are never logged, only the names of the variables that were set.

Not python-dotenv: the parsing is a few lines, and it isn't worth a
dependency that runs at import time.
"""

from __future__ import annotations

import os
from pathlib import Path


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load(path: str | os.PathLike = ".env", *, override: bool = False) -> list:
    """Load KEY=VALUE lines and return the names of the variables set.

    Never raises - a missing or malformed file must not stop the app booting.
    """
    p = Path(path)
    if not p.is_file():
        return []

    applied: list[str] = []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # "export FOO=bar" is what people paste from shell instructions.
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        # Strip a trailing comment only from unquoted values, so a quoted value
        # containing '#' survives.
        value = value.strip()
        if value[:1] not in ("'", '"') and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        value = _strip_quotes(value)

        if not override and os.environ.get(key):
            continue          # the real environment wins
        os.environ[key] = value
        applied.append(key)

    return applied


def autoload() -> list:
    """Load the nearest .env, searching upward from the backend directory.

    Called once at startup. Returns names only; never log the values.
    """
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / ".env"
        if candidate.is_file():
            return load(candidate)
    return []
