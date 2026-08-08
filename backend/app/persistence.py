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

from .core import (analytics, billing, clients, evidence, learning, reflection,
                   knowledge, routing, traffic, voice_sessions)
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
            # What subscribers actually DID. Losing this on every restart would
            # reset the founder's only view of the funnel to empty, which is
            # indistinguishable from nobody having used the product.
            "analytics": analytics.export_state(),
            # Visitor counts are the top of the funnel. A restart that zeroes
            # them makes a launch day look like it never happened.
            "traffic": traffic.export_state(),
            # Transcripts and tool timelines are the replay record. Losing them
            # on restart would make session replay a feature that only works
            # until the container recycles.
            "voice": voice_sessions.export_state(),
            # Re-crawling every client on every restart to rebuild this would
            # be slow and rude to their servers.
            "knowledge": knowledge.export_state(),
            # Provenance is the whole value of the ledger. Losing it on restart
            # would leave values with no record of where they came from, which
            # is the state this replaced.
            "evidence": evidence.export_state(),
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
        stats = data.get("analytics")
        if isinstance(stats, dict):
            analytics.import_state(stats)
        visits = data.get("traffic")
        if isinstance(visits, dict):
            traffic.import_state(visits)
        voice = data.get("voice")
        if isinstance(voice, dict):
            voice_sessions.import_state(voice)
        kb = data.get("knowledge")
        if isinstance(kb, dict):
            knowledge.import_state(kb)
        ev = data.get("evidence")
        if isinstance(ev, dict):
            evidence.import_state(ev)
    except Exception:
        pass
