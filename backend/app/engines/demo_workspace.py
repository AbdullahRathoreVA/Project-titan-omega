"""A demo workspace so the 24/7 engines have real work — without faking users.

Titan already runs continuously: the heartbeat drives the self-audit, the
client watch, the news watch and the growth cycle every few seconds. With no
clients on the books, all of that spins against an empty list. The dashboard
looks idle because it *is* idle, not because it is broken.

This seeds a small workspace so those engines do genuine work, and it is built
around one rule:

**A demo account must never be counted as a real one.**

The founder analytics screen exists to answer "is anybody actually using
this?". Seeding fake signups to make it look busy would destroy the only
instrument that can answer that question — and it is the exact failure this
codebase keeps guarding against. So every record here carries ``is_demo`` and
the funnel filters them out. A demo client is visible on the operational
screens, where it is useful, and invisible in the numbers, where it would lie.

**The sites audited are Titan's own.** Re-crawling a stranger's server every
few hours to keep a demo looking lively is rude, and doing it to a business
that never asked would be worse coming from a company selling compliance.
Titan's own landing pages are real, substantive, publicly served pages that
exercise the whole pipeline — crawl, audit, knowledge index — and belong to
Abdullah. ``example.com`` is included deliberately as the low-scoring
contrast: it is IANA-reserved for exactly this use.
"""

from __future__ import annotations

import os
import threading
import time

from ..core import clients, knowledge
from . import client_seo

SITE = os.getenv("TITAN_SITE_URL", "https://titanomega-ai.com").rstrip("/")

# Kept deliberately small. Each entry is a real crawl on every cycle.
DEMO_CLIENTS = (
    ("[DEMO] Titan Omega — compliance guide", f"{SITE}/compliance/de",
     "software", "Berlin", "Germany"),
    ("[DEMO] Titan Omega — wholesale SEO", f"{SITE}/seo/wholesale",
     "wholesale", "Sialkot", "Pakistan"),
    ("[DEMO] Example Trading Co", "https://example.com",
     "wholesale", "", "United States"),
)

# Six hours, matching the self-audit. Fast enough that the screens are never
# stale, slow enough that nothing is being hammered.
INTERVAL = float(os.getenv("TITAN_DEMO_INTERVAL", str(6 * 3600)))

_lock = threading.RLock()
_last_run = 0.0
_last: dict = {}


def enabled() -> bool:
    """On by default. TITAN_DEMO_WORKSPACE=0 turns it off entirely — the right
    move once real clients arrive and the screens have their own content."""
    return os.getenv("TITAN_DEMO_WORKSPACE", "1") != "0"


def is_demo_client(rec: dict) -> bool:
    return bool(rec.get("is_demo")) or str(rec.get("business_name", "")).startswith("[DEMO]")


def ensure() -> dict:
    """Create the demo clients if absent. Idempotent — safe on every boot."""
    if not enabled():
        return {"enabled": False, "created": 0, "existing": 0}
    created, existing = 0, 0
    for name, website, industry, city, country in DEMO_CLIENTS:
        match = next((c for c in clients.all_clients()
                      if c.get("website") == website), None)
        if match:
            existing += 1
            if not match.get("is_demo"):
                clients.update_raw(match["id"], is_demo=True)
            continue
        try:
            import secrets as _secrets
            rec = clients.create_client(
                business_name=name,
                username=f"demo-{_secrets.token_hex(4)}",
                password=_secrets.token_urlsafe(24),
                website=website, industry=industry, city=city, country=country)
            clients.update_raw(rec["id"], is_demo=True)
            created += 1
        except ValueError:
            existing += 1
    return {"enabled": True, "created": created, "existing": existing}


def cycle(force: bool = False) -> dict | None:
    """Audit each demo site and refresh its knowledge index.

    Returns None when it is not yet due, so the heartbeat can call it every
    few seconds without doing anything.
    """
    global _last_run
    if not enabled():
        return None
    if not force and time.monotonic() - _last_run < INTERVAL:
        return None
    _last_run = time.monotonic()

    ensure()
    audited, indexed, failed = 0, 0, []
    for rec in clients.all_clients():
        if not is_demo_client(rec) or not rec.get("website"):
            continue
        try:
            result = client_seo.audit(
                rec["website"], business_name=rec.get("business_name", ""),
                city=rec.get("city", ""), country=rec.get("country", ""),
                industry=rec.get("industry", ""))
            clients.bump(rec["id"], "seo_audits")
            if result.get("ok"):
                clients.update_raw(rec["id"], last_audit=result)
                clients.bump(rec["id"], "issues_found",
                             len(result.get("findings", [])))
                audited += 1
                # The crawl is already paid for — keep the text so the voice
                # agent has something to retrieve from.
                page, _err, _status = client_seo._fetch(rec["website"])
                if page and knowledge.ingest(rec["id"], page,
                                             rec["website"]).get("ok"):
                    indexed += 1
            else:
                failed.append({"site": rec["website"],
                               "error": str(result.get("error", ""))[:120]})
        except Exception as exc:
            failed.append({"site": rec.get("website", ""),
                           "error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    snapshot = {"ran_at": time.time(), "audited": audited, "indexed": indexed,
                "failed": failed, "sites": len(DEMO_CLIENTS)}
    with _lock:
        _last.clear()
        _last.update(snapshot)
    return snapshot


def status() -> dict:
    with _lock:
        last = dict(_last)
    return {
        "enabled": enabled(),
        "sites": [{"name": n, "website": w} for n, w, *_ in DEMO_CLIENTS],
        "interval_hours": round(INTERVAL / 3600, 1),
        "last_run": last or None,
        "note": ("Demo records carry is_demo and are excluded from the signup "
                 "funnel and revenue figures — they exist to give the 24/7 "
                 "engines real work, not to make the numbers look busy. Set "
                 "TITAN_DEMO_WORKSPACE=0 once real clients arrive."),
    }
