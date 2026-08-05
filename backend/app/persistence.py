"""Lightweight JSON persistence for the running empire state.

Hugging Face Spaces (free tier) have an ephemeral filesystem: a writable path
survives process restarts / sleep-wake but is wiped on a fresh rebuild. We save
the real numbers that matter — revenue metrics and the order ledger — to a JSON
file so the dashboard remembers earnings across restarts.

Everything is best-effort and wrapped in try/except: persistence must never
crash the app. To make data permanent across rebuilds, mount HF persistent
storage at /data (or point TITAN_STATE_FILE at a mounted volume / database).
"""

from __future__ import annotations

import json
import os
import tempfile

from .core import billing, clients, learning, reflection, routing
from .store import STORE, Store


def _default_path() -> str:
    # Prefer a persistent mount if present, else fall back to the temp dir.
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/titan_state.json"
    return os.path.join(tempfile.gettempdir(), "titan_state.json")


STATE_FILE = os.getenv("TITAN_STATE_FILE", _default_path())


def save(store: Store = STORE) -> None:
    """Atomically write metrics + revenue ledger to disk. Never raises."""
    try:
        data = {
            "metrics": {k: float(v) for k, v in store.metrics.items()},
            "revenue_entries": store.revenue_entries,
            "expenses": store.expenses,
            "leads": store.leads,
            "decisions": store.decisions,
            # Learned preference must survive restarts, or Titan forgets his
            # judgement every rebuild and re-enters its cold start forever.
            "learning": learning.export_state(),
            "clients": clients.export_state(),
            # Model measurements must survive restarts: HF recycles Spaces
            # often, and profiling that resets never gathers enough evidence
            # to route on.
            "routing": routing.export_state(),
            # Calibration is only useful once it has accumulated evidence;
            # losing it on every Space restart would keep it at 1.0 forever.
            "reflection": reflection.export_state(),
            "billing": billing.export_state(),
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def load(store: Store = STORE) -> None:
    """Restore saved metrics + revenue ledger if a state file exists. Never raises."""
    try:
        if not os.path.exists(STATE_FILE):
            return
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        metrics = data.get("metrics")
        if isinstance(metrics, dict):
            store.metrics.update(
                {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
            )
        entries = data.get("revenue_entries")
        if isinstance(entries, list):
            store.revenue_entries = entries
        expenses = data.get("expenses")
        if isinstance(expenses, list):
            store.expenses = expenses
        leads = data.get("leads")
        if isinstance(leads, dict):
            store.leads = leads
        decisions = data.get("decisions")
        if isinstance(decisions, list):
            store.decisions = decisions
        learned = data.get("learning")
        if isinstance(learned, dict):
            learning.import_state(learned)
        client_rows = data.get("clients")
        if isinstance(client_rows, dict):
            clients.import_state(client_rows)
        routes = data.get("routing")
        if isinstance(routes, dict):
            routing.import_state(routes)
        refl = data.get("reflection")
        if isinstance(refl, dict):
            reflection.import_state(refl)
        bill = data.get("billing")
        if isinstance(bill, dict):
            billing.import_state(bill)
    except Exception:
        pass
