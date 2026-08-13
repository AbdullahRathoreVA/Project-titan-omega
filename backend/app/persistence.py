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

from .core import (analytics, billing, clients, db, evidence, learning,
                   reflection, knowledge, routing, sessions, site_access,
                   site_fix, traffic, voice_sessions)
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
            # Revoked session ids. Stateless tokens are valid until they
            # expire by definition, so revocation is the one part that needs
            # storage — and it must survive a restart or a signed-out token
            # starts working again.
            "sessions": sessions.export_state(),
            # Encrypted website credentials. The blob is useless without
            # TITAN_CREDENTIAL_KEY, which is why it is safe to store here at
            # all — but losing it would silently disconnect every client.
            "site_access": site_access.export_state(),
            # Fixes applied to a CUSTOMER'S live website, each carrying the
            # exact previous value. Losing this does not just lose history —
            # it loses the only way to undo a change Titan made to somebody
            # else's business. `durable` on every record says whether this
            # deployment actually keeps it.
            "site_fix": site_fix.export_state(),
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
        # One transaction for all fifteen subsystems. The JSON file could not
        # offer this: a crash mid-write left a truncated file that failed to
        # parse, losing accounts, transcripts and evidence together.
        db.connect(STATE_FILE)
        db.put_many(data)
    except Exception:
        pass


def export_json(path: str) -> bool:
    """Write the whole state to a JSON file, for backup or inspection.

    Kept deliberately after the move to SQLite. A database nobody can read
    without tooling is worse than a file for a solo operator, and this is the
    escape hatch if the schema ever needs to be rebuilt from scratch.
    """
    try:
        db.connect(STATE_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(db.all_state(), f, indent=2, default=str)
        return True
    except Exception:
        return False


def _read_state() -> dict:
    """Read state, migrating a legacy JSON file on first run.

    Existing deployments have a JSON file at this exact path. Opening it as a
    SQLite database would fail and silently discard every account, so the file
    is detected, imported once, and kept alongside as `.json.bak` rather than
    deleted — a migration that destroys its own source has no way back.
    """
    legacy = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                head = f.read(16)
            if not head.startswith(b"SQLite format 3"):
                with open(STATE_FILE, encoding="utf-8") as f:
                    legacy = json.load(f)
        except Exception:
            legacy = None

    if legacy is not None:
        backup = STATE_FILE + ".json.bak"
        try:
            os.replace(STATE_FILE, backup)
        except Exception:
            pass
        db.connect(STATE_FILE)
        db.put_many(legacy)
        return legacy

    db.connect(STATE_FILE)
    return db.all_state()


def load(store: Store = STORE) -> None:
    """Restore saved state if any exists. Never raises."""
    try:
        data = _read_state()
        if not data:
            return
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
        revoked = data.get("sessions")
        if isinstance(revoked, dict):
            sessions.import_state(revoked)
        sites = data.get("site_access")
        if isinstance(sites, dict):
            site_access.import_state(sites)
        fixes = data.get("site_fix")
        if isinstance(fixes, dict):
            site_fix.import_state(fixes)
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
