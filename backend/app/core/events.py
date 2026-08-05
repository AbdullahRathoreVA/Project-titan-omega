"""Typed event bus — the seam every subsystem talks through.

Spec Part 2 ("Everything communicates through events. Never tightly couple
services") and Part 7 ("All events should be logged, traceable, and
documented").

Titan already had ``STORE.emit()``, but that is a *human-readable activity feed*:
free-text messages for the dashboard. It cannot be subscribed to, carries no
structured payload, and nothing can react to it. This adds the machine-readable
layer beside it — typed events, structured payloads, synchronous subscribers,
and a bounded trace — and mirrors anything worth seeing into the existing feed
so the dashboard keeps working unchanged.

Deliberately synchronous and in-process. Titan runs as one container on a free
tier; a broker would be infrastructure to pay for and operate with no subscriber
that needs it yet. The interface is what matters — swapping the transport later
touches only this file.

A failing subscriber must never break the thing that emitted the event. Handler
exceptions are captured onto the event record rather than propagated: a broken
listener degrades observability, not the business action that fired it.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

# ---------------------------------------------------------------- taxonomy --
# Spec Part 7 names these explicitly. Keeping them as constants rather than bare
# strings means a typo is an AttributeError at import, not an event nobody
# receives and nobody notices.
TASK_CREATED = "TaskCreated"
TASK_ASSIGNED = "TaskAssigned"
TASK_COMPLETED = "TaskCompleted"
AGENT_STARTED = "AgentStarted"
AGENT_COMPLETED = "AgentCompleted"
AGENT_FAILED = "AgentFailed"
MEMORY_UPDATED = "MemoryUpdated"
KNOWLEDGE_INDEXED = "KnowledgeIndexed"
MODEL_SELECTED = "ModelSelected"
MODEL_FAILED = "ModelFailed"
TOOL_INVOKED = "ToolInvoked"
TOOL_FAILED = "ToolFailed"
PLAN_CREATED = "PlanCreated"
REFLECTION_RECORDED = "ReflectionRecorded"
DEPLOYMENT_SUCCEEDED = "DeploymentSucceeded"
DEPLOYMENT_FAILED = "DeploymentFailed"
NOTIFICATION_SENT = "NotificationSent"
CLIENT_ONBOARDED = "ClientOnboarded"
AUDIT_FINISHED = "AuditFinished"

KNOWN_EVENTS = frozenset({
    TASK_CREATED, TASK_ASSIGNED, TASK_COMPLETED,
    AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED,
    MEMORY_UPDATED, KNOWLEDGE_INDEXED,
    MODEL_SELECTED, MODEL_FAILED,
    TOOL_INVOKED, TOOL_FAILED,
    PLAN_CREATED, REFLECTION_RECORDED,
    DEPLOYMENT_SUCCEEDED, DEPLOYMENT_FAILED,
    NOTIFICATION_SENT, CLIENT_ONBOARDED, AUDIT_FINISHED,
})

MAX_TRACE = 500          # bounded: this runs in a 512MB free-tier container

_lock = threading.RLock()
_subscribers: dict[str, list[Callable]] = {}
_trace: list[dict] = []
_counter = 0


def subscribe(event: str, handler: Callable[[dict], None]) -> Callable[[], None]:
    """Register a handler. Returns an unsubscribe callable.

    Unknown event names are allowed — refusing them would make the bus a
    bottleneck on every new feature — but they are recorded so an event nobody
    documented still shows up in ``stats()``.
    """
    with _lock:
        _subscribers.setdefault(event, []).append(handler)

    def _off() -> None:
        with _lock:
            handlers = _subscribers.get(event, [])
            if handler in handlers:
                handlers.remove(handler)

    return _off


def emit(event: str, payload: Optional[dict] = None, *,
         actor: str = "system", severity: str = "info") -> dict:
    """Publish an event. Never raises."""
    global _counter
    with _lock:
        _counter += 1
        record = {
            "id": f"ev-{_counter:06d}",
            "event": event,
            "actor": actor,
            "severity": severity,
            "payload": dict(payload or {}),
            "ts": time.time(),
            "known": event in KNOWN_EVENTS,
            "errors": [],
        }
        handlers = list(_subscribers.get(event, []))

    for handler in handlers:
        try:
            handler(record)
        except Exception as exc:
            # A broken subscriber degrades observability; it must not break the
            # business action that emitted the event.
            record["errors"].append(f"{type(exc).__name__}: {str(exc)[:160]}")

    with _lock:
        _trace.append(record)
        if len(_trace) > MAX_TRACE:
            del _trace[:len(_trace) - MAX_TRACE]

    return record


def trace(limit: int = 50, event: str = "") -> list[dict]:
    """Most recent events, newest first, optionally filtered by name."""
    with _lock:
        rows = [r for r in _trace if not event or r["event"] == event]
        return list(reversed(rows[-limit:]))


def stats() -> dict:
    """What has been happening, for the dashboard and for health checks."""
    with _lock:
        counts: dict[str, int] = {}
        failures = 0
        unknown: set[str] = set()
        for r in _trace:
            counts[r["event"]] = counts.get(r["event"], 0) + 1
            if r["errors"]:
                failures += 1
            if not r["known"]:
                unknown.add(r["event"])
        return {
            "total": _counter,
            "in_trace": len(_trace),
            "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "subscriber_failures": failures,
            "undocumented_events": sorted(unknown),
            "subscribers": {k: len(v) for k, v in _subscribers.items() if v},
        }


def reset() -> None:
    """Test seam. Not called by application code."""
    global _counter
    with _lock:
        _subscribers.clear()
        _trace.clear()
        _counter = 0
