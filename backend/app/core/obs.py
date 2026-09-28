"""Structured logging, so production incidents can be diagnosed.

STORE.emit is an activity feed for people and core/events.py is an event bus
for subsystems; neither answers "which request was that, what did it do, and
how long did it take". This does.

- One line of JSON per event on stdout. Hugging Face Spaces, Docker, Render
  and log shippers all read stdout; a log file would be wiped on rebuild.
- A request id that follows the work. It's generated per request, held in a
  context variable, and picked up by every log line while the request is in
  flight, including from worker threads it starts. It's returned in the
  `X-Request-Id` header so a customer reporting a problem can quote it.
- Nothing sensitive is logged. Titan holds customers' site credentials,
  subscriber emails and voice transcripts, so redaction happens here rather
  than relying on every caller. Emails become a stable hash and any key that
  looks like a credential is replaced (see `_REDACT_KEYS`). A test checks
  that a credential passed to a log call doesn't appear in the output.

Durations are measured wall time; a value that wasn't measured is null, not 0.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from typing import Any, Optional

# INFO by default; TITAN_LOG_LEVEL=debug in development.
_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}
LEVEL = _LEVELS.get(os.getenv("TITAN_LOG_LEVEL", "info").strip().lower(), 20)

# Can be turned off for tests - hundreds of tests each writing JSON to stdout
# makes failures unreadable.
ENABLED = os.getenv("TITAN_LOG_ENABLED", "1").strip() not in ("0", "false", "")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "titan_request_id", default="")
_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "titan_tenant", default="")

_lock = threading.RLock()
# A small ring buffer so /api/founder/logs can show recent lines without a log
# shipper. Bounded: the container has 512MB.
MAX_RECENT = 300
_recent: list[dict] = []

# Any key matching these is replaced before it reaches stdout. Substring match,
# case-insensitive, so `wp_application_password` and `X-Account-Token` both hit.
_REDACT_KEYS = ("password", "secret", "token", "api_key", "apikey",
                "credential", "authorization", "cookie", "session",
                "private", "signature")

REDACTED = "[redacted]"


def _redact(value: Any, key: str = "") -> Any:
    """Strip anything that looks like a credential, at any depth."""
    lowered = key.lower()
    if any(marker in lowered for marker in _REDACT_KEYS):
        return REDACTED
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        # An email is personal data. A stable hash still lets two lines be linked to
        # the same person without storing who they are.
        if "@" in value and "." in value.split("@")[-1] and len(value) < 200:
            return "email:" + hashlib.sha256(value.encode()).hexdigest()[:12]
    return value


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def bind(request_id: str = "", tenant: str = "") -> None:
    """Attach identifiers to the current context."""
    if request_id:
        _request_id.set(request_id)
    if tenant:
        _tenant.set(tenant)


def current_request_id() -> str:
    return _request_id.get()


def log(event: str, level: str = "info", **fields: Any) -> dict:
    """Emit one structured line. Never raises; logging mustn't break a request."""
    try:
        severity = _LEVELS.get(level.lower(), 20)
        record = {
            "ts": round(time.time(), 3),
            "level": level.lower(),
            "event": event,
            "request_id": _request_id.get() or None,
            "tenant": _tenant.get() or None,
            **{k: _redact(v, k) for k, v in fields.items()},
        }
        record = {k: v for k, v in record.items() if v is not None}

        with _lock:
            _recent.append(record)
            if len(_recent) > MAX_RECENT:
                del _recent[:len(_recent) - MAX_RECENT]

        if ENABLED and severity >= LEVEL:
            # default=str so an unexpected object falls back to its repr instead of
            # raising inside a log call.
            sys.stdout.write(json.dumps(record, default=str) + "\n")
            sys.stdout.flush()
        return record
    except Exception:
        return {}


def info(event: str, **fields: Any) -> dict:
    return log(event, "info", **fields)


def warn(event: str, **fields: Any) -> dict:
    return log(event, "warn", **fields)


def error(event: str, **fields: Any) -> dict:
    return log(event, "error", **fields)


class timed:
    """Context manager that logs measured wall time.

    Used as `with obs.timed("crawl", url=url): ...`. On an exception it logs
    the failure with the elapsed time and re-raises; swallowing errors here
    would hide exactly what's being diagnosed.
    """

    def __init__(self, event: str, **fields: Any):
        self.event = event
        self.fields = fields
        self.started = 0.0

    def __enter__(self):
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = round((time.monotonic() - self.started) * 1000, 1)
        if exc_type is None:
            info(self.event, duration_ms=ms, ok=True, **self.fields)
        else:
            error(self.event, duration_ms=ms, ok=False,
                  error=f"{exc_type.__name__}: {str(exc)[:200]}", **self.fields)
        return False                      # never swallow


def recent(limit: int = 100, level: str = "", event: str = "") -> list[dict]:
    """Recent lines, newest first."""
    with _lock:
        rows = list(_recent)
    if level:
        rows = [r for r in rows if r.get("level") == level.lower()]
    if event:
        rows = [r for r in rows if event in r.get("event", "")]
    return list(reversed(rows[-limit:]))


def stats() -> dict:
    with _lock:
        rows = list(_recent)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("level", "info")] = counts.get(r.get("level", "info"), 0) + 1
    measured = [r["duration_ms"] for r in rows if isinstance(
        r.get("duration_ms"), (int, float))]
    return {
        "retained": len(rows),
        "capacity": MAX_RECENT,
        "by_level": counts,
        "level": next((k for k, v in _LEVELS.items() if v == LEVEL), "info"),
        "enabled": ENABLED,
        # None, not 0.0: "nothing timed yet" isn't "everything is instant".
        "slowest_ms": max(measured) if measured else None,
        "timed_operations": len(measured),
        "note": ("An in-process ring buffer of the last "
                 f"{MAX_RECENT} lines, for when no log shipper is attached. "
                 "The durable copy is the JSON on stdout. Nothing here "
                 "survives a restart."),
    }


def reset() -> None:
    """Test seam."""
    with _lock:
        _recent.clear()
