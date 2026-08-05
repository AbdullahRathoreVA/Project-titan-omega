"""Load a local .env into the process environment. Stdlib only.

Why this exists: nothing read a .env file, so running Titan locally with any
provider configured meant exporting variables on the command line every time.
That is precisely how secrets end up pasted into shell history, screenshots and
chat logs — which has already cost this project one key rotation.

Two rules that matter more than the parsing:

1. **The real environment always wins.** A value already present in os.environ
   is never overwritten. On Hugging Face the Space secrets ARE the environment,
   so a stale .env accidentally shipped inside an image can never shadow the
   real production key with a dead one.

2. **Values are never logged.** The loader reports how many keys it set and
   their NAMES, never their contents. A "loaded FIRECRAWL_API_KEY=fc-..." line
   in container logs is a leak.

Not python-dotenv: this is fifteen lines of parsing, and a dependency that runs
at import time on a container holding client data is a supply-chain risk that
buys nothing here.
"""

from __future__ import annotations

import os
from pathlib import Path


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load(path: str | os.PathLike = ".env", *, override: bool = False) -> list:
    """Load KEY=VALUE lines. Returns the NAMES of variables it set.

    Never raises: a missing or malformed file must not stop the app booting.
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
        # "export FOO=bar" is what people paste out of shell instructions.
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        # Strip a trailing comment only when the value is not quoted, so a
        # value legitimately containing '#' survives.
        value = value.strip()
        if value[:1] not in ("'", '"') and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        value = _strip_quotes(value)

        if not override and os.environ.get(key):
            continue          # the real environment wins — see module docstring
        os.environ[key] = value
        applied.append(key)

    return applied


def autoload() -> list:
    """Load the nearest .env, searching from the backend dir upward.

    Called once at startup. Returns names only — callers must never log values.
    """
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / ".env"
        if candidate.is_file():
            return load(candidate)
    return []
