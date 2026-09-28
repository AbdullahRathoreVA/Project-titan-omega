"""Persistence for the running state.

Hugging Face Spaces (free tier) have an ephemeral filesystem: a writable path
survives restarts and sleep/wake but is wiped on a fresh rebuild. State is
saved so the dashboard keeps its data across restarts.

Everything is best-effort and wrapped in try/except; persistence must never
crash the app. To keep data across rebuilds, mount HF persistent storage at
/data or point TITAN_STATE_FILE at a mounted volume.
"""

from __future__ import annotations

import json
import os
import tempfile

from .core import (analytics, billing, clients, db, evidence, learning,
                   reflection, knowledge, routing, sessions, site_access,
                   site_fix, telegram_links, traffic, voice_sessions,
                   workspaces)
from .store import STORE, Store, founder_store


def _default_path() -> str:
    # Prefer a persistent mount if present, else fall back to the temp dir.
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/titan_state.json"
    return os.path.join(tempfile.gettempdir(), "titan_state.json")


STATE_FILE = os.getenv("TITAN_STATE_FILE", _default_path())


def save(store: Store = STORE) -> None:
    """Atomically write metrics + revenue ledger to disk. Never raises."""
    # Routes call save(STORE). During a customer request STORE is that customer's
    # workspace, and saving it here would overwrite the founder's ledger with
    # theirs. Customer workspaces are saved below, by owner.
    if store is STORE:
        store = founder_store()
    try:
        data = {
            "metrics": {k: float(v) for k, v in store.metrics.items()},
            "revenue_entries": store.revenue_entries,
            "expenses": store.expenses,
            "leads": store.leads,
            "decisions": store.decisions,
            # Learned preferences must survive restarts, or ranking falls back to the
            # cold start after every rebuild.
            "learning": learning.export_state(),
            "clients": clients.export_state(),
            # Model measurements must survive restarts: HF recycles Spaces often, and
            # stats that reset never gather enough evidence to route on.
            "routing": routing.export_state(),
            # Calibration is only useful once it has evidence; losing it on every restart
            # would keep it at 1.0 forever.
            "reflection": reflection.export_state(),
            "billing": billing.export_state(),
            # What subscribers actually did. Losing this on restart would reset the
            # funnel to empty, which looks like nobody ever used the product.
            "analytics": analytics.export_state(),
            # Revoked session ids. Stateless tokens stay valid until they expire, so
            # revocation is the part that needs storage - and it must survive a restart,
            # or a signed-out token starts working again.
            "sessions": sessions.export_state(),
            # Encrypted website credentials. Useless without TITAN_CREDENTIAL_KEY, which
            # is why it's safe to store here, but losing it would silently disconnect
            # every client.
            "site_access": site_access.export_state(),
            # Fixes applied to customers' live websites, each with the exact previous
            # value. Losing this loses the only way to undo those changes. `durable` on
            # each record says whether this deployment actually keeps it.
            "site_fix": site_fix.export_state(),
            # Visitor counts are the top of the funnel; a restart that zeroes them would
            # wipe out launch-day traffic.
            "traffic": traffic.export_state(),
            # Transcripts and tool timelines are the replay record; without this, replay
            # would only work until the container recycles.
            "voice": voice_sessions.export_state(),
            # Rebuilding this by re-crawling every client on each restart would be slow
            # and rude to their servers.
            "knowledge": knowledge.export_state(),
            # Provenance is the point of the ledger; without it, values would have no
            # record of where they came from.
            "evidence": evidence.export_state(),
            # Each subscriber's own cockpit ledger, keyed by account.
            "workspaces": workspaces.export_state(),
            # Which Telegram chat belongs to which subscriber. Losing it would answer a
            # linked chat as a stranger's.
            "telegram_links": telegram_links.export_state(),
        }
        # One transaction for every subsystem, so a crash mid-write can't leave a
        # half-written state behind.
        db.connect(STATE_FILE)
        db.put_many(data)
    except Exception:
        pass


def export_json(path: str) -> bool:
    """Write the whole state to a JSON file, for backup or inspection.

    Kept after the move to SQLite: a plain file is easy to read without
    tooling, and it's the escape hatch if the schema ever needs rebuilding.
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

    Older deployments have a JSON file at this exact path. Opening it as SQLite
    would fail and lose every account, so it's detected, imported once, and
    kept as `.json.bak` rather than deleted.
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
        spaces = data.get("workspaces")
        if isinstance(spaces, dict):
            workspaces.import_state(spaces)
        links = data.get("telegram_links")
        if isinstance(links, dict):
            telegram_links.import_state(links)
    except Exception:
        pass
