"""One private workspace per subscriber.

A workspace is an ordinary Store, so every engine that runs against the
founder's Store works on a subscriber's unchanged. main.auth_guard binds the
right one for each /api/me request (see store.bind).

New workspaces start empty: the agent roster is there, idle, and every
figure is zero until the subscriber does something. None of the founder's
seed data (Career Mind, Upwork, Kindle) is copied in.
"""

from __future__ import annotations

import threading
import time
from typing import Dict

from ..domain.enums import AgentStatus
from ..domain.network import AGENT_NETWORK
from ..store import AgentRuntime, Store, now

WAITING = "Waiting for your first business - add one in Clients"

_METRICS = ("mrr", "traffic", "pipeline_value", "customers", "conversion_rate")
# Fields that survive a restart: the same ones the founder's Store keeps, plus
# War Room research and content packs, since nothing regenerates those for a
# subscriber.
_DURABLE = ("metrics", "revenue_entries", "expenses", "leads", "decisions",
            "intel", "deliverables", "jobs")
_KEEP_DELIVERABLES = 50

_lock = threading.RLock()
_spaces: Dict[str, Store] = {}
_pending: Dict[str, dict] = {}     # restored snapshots not opened yet
_last_seen: Dict[str, float] = {}


def _seed(ws: Store) -> None:
    for spec in AGENT_NETWORK:
        ws.agents[spec.id] = AgentRuntime(
            spec=spec, status=AgentStatus.IDLE, current_task=WAITING,
            last_active=now())
    ws.metrics.update({k: 0.0 for k in _METRICS})
    ws.emit("executive-core", "system",
            "Your Titan workspace is live. Every number here is yours and "
            "starts at zero.", "success")


def _restore(ws: Store, snap: dict) -> None:
    metrics = snap.get("metrics")
    if isinstance(metrics, dict):
        ws.metrics.update({k: float(v) for k, v in metrics.items()
                           if isinstance(v, (int, float))})
    for name in ("revenue_entries", "expenses", "decisions"):
        if isinstance(snap.get(name), list):
            setattr(ws, name, snap[name])
    if isinstance(snap.get("leads"), dict):
        ws.leads = snap["leads"]
    if isinstance(snap.get("intel"), dict):
        ws.intel = snap["intel"]
    if isinstance(snap.get("deliverables"), dict):
        ws.deliverables = snap["deliverables"]
    if isinstance(snap.get("jobs"), dict):
        ws.jobs = snap["jobs"]


def for_account(email: str) -> Store:
    """The workspace for this subscriber, created on first use."""
    with _lock:
        ws = _spaces.get(email)
        if ws is None:
            ws = Store()
            _seed(ws)
            snap = _pending.pop(email, None)
            if snap:
                _restore(ws, snap)
            _spaces[email] = ws
        return ws


def touch(email: str) -> None:
    with _lock:
        _last_seen[email] = time.time()


def export_state() -> dict:
    with _lock:
        out = dict(_pending)
        for email, ws in _spaces.items():
            out[email] = {
                "metrics": {k: float(v) for k, v in ws.metrics.items()},
                "revenue_entries": ws.revenue_entries,
                "expenses": ws.expenses,
                "leads": ws.leads,
                "decisions": ws.decisions,
                "intel": ws.intel,
                # Insertion order is creation order; keep the newest.
                "deliverables": dict(list(ws.deliverables.items())[-_KEEP_DELIVERABLES:]),
                # Their Job Radar profile and finds.
                "jobs": ws.jobs,
            }
        return out


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    with _lock:
        for email, snap in data.items():
            if isinstance(email, str) and isinstance(snap, dict):
                _pending[email] = {k: snap[k] for k in _DURABLE if k in snap}


def reset() -> None:
    """Test seam."""
    with _lock:
        _spaces.clear()
        _pending.clear()
        _last_seen.clear()
