"""Demo workspace, so the background engines have real work to do.

The heartbeat drives the self-audit, client watch, news watch and growth
cycle continuously. With no clients they run against an empty list, and the
dashboard looks idle. This seeds a small workspace so those engines do real
work, with one rule: a demo account is never counted as a real one.

Every record carries ``is_demo`` and the funnel filters it out, so demo
clients show up on the operational screens but never in the customer
numbers.

The audited sites are Titan's own landing pages - real, publicly served
pages that exercise the whole pipeline (crawl, audit, knowledge index) -
rather than a stranger's server crawled every few hours without asking.
``example.com`` is included as the low-scoring contrast; IANA reserves it for
this kind of use.
"""

from __future__ import annotations

import os
import threading
import time

from ..core import clients, knowledge
from . import client_seo

SITE = os.getenv("TITAN_SITE_URL", "https://titanomega-ai.com").rstrip("/")

# Kept small: each entry is a real crawl every cycle.
DEMO_CLIENTS = (
    ("[DEMO] Titan Omega — compliance guide", f"{SITE}/compliance/de",
     "software", "Berlin", "Germany"),
    ("[DEMO] Titan Omega — wholesale SEO", f"{SITE}/seo/wholesale",
     "wholesale", "Sialkot", "Pakistan"),
    ("[DEMO] Example Trading Co", "https://example.com",
     "wholesale", "", "United States"),
)

# Six hours, matching the self-audit: the screens are never stale and nothing
# gets hammered.
INTERVAL = float(os.getenv("TITAN_DEMO_INTERVAL", str(6 * 3600)))

_lock = threading.RLock()
_last_run = 0.0
_last: dict = {}


def enabled() -> bool:
    """On by default. TITAN_DEMO_WORKSPACE=0 turns it off entirely, e.g. once
    real clients give the screens their own content.
    """
    return os.getenv("TITAN_DEMO_WORKSPACE", "1") != "0"


def is_demo_client(rec: dict) -> bool:
    return bool(rec.get("is_demo")) or str(rec.get("business_name", "")).startswith("[DEMO]")


def ensure() -> dict:
    """Create the demo clients if absent. Idempotent, so safe on every boot."""
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

    Returns None when it isn't due yet, so the heartbeat can call it every few
    seconds.
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
                # The page is already fetched - keep the text so the voice agent has
                # something to retrieve from.
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


# The business the public demo opens. Chosen here, next to the data, because
# it decides what a stranger sees.
#
# The compliance guide is used because it's the only demo site that
# exercises the legal half of the audit, the finding prospects can't get
# elsewhere. example.com is deliberately not used: it scores badly on purpose
# as the contrast for the operator screens.
SHOWCASE_WEBSITE = f"{SITE}/compliance/de"


def _demo_rows() -> list[dict]:
    """Every business carrying the demo flag, and nothing else.

    This line decides what an anonymous visitor may be shown. It's its own
    function so its mutation guard anchor matches in exactly one place.
    """
    return [c for c in clients.all_clients() if is_demo_client(c)]


def business_ids() -> list:
    """Every demo business, for the public demo cockpit. Seeded on demand like
    showcase(), and never a real client.
    """
    if not enabled():
        return []
    if not _demo_rows():
        try:
            ensure()
        except Exception:
            return []
    return [r["id"] for r in _demo_rows() if is_demo_client(r)]


def showcase() -> dict | None:
    """The demo business a stranger may open, or None.

    Returns None rather than falling back to a real client: the public demo
    must only ever reach a business Titan owns, so an empty demo workspace
    produces a refusal, never a substitution.
    """
    if not enabled():
        return None
    rows = _demo_rows()
    if not rows:
        # Seed on demand. Otherwise, on a fresh boot, the public demo would return 503
        # until the first heartbeat tick. ensure() is idempotent and doesn't crawl
        # anything, so this is free when the records already exist.
        try:
            ensure()
        except Exception:
            # Seeding failed. Fall through to the refusal below rather than let the
            # exception decide what a visitor sees.
            pass
        rows = _demo_rows()
    if not rows:
        return None
    for rec in rows:
        if rec.get("website") == SHOWCASE_WEBSITE:
            return rec
    # The named one is missing (deleted, or SITE changed). Any demo business is
    # still safe to show; a real one never is. Sorted so every visitor sees the
    # same one.
    return sorted(rows, key=lambda r: str(r.get("business_name", "")))[0]


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
