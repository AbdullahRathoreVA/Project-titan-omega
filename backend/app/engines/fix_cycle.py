"""Runs the site fix loop continuously, with nobody logged in.

`core/site_fix` is the loop itself: propose -> approve -> apply -> verify ->
rollback. This drives it on a schedule, within two limits:

- It never applies anything. It re-audits, proposes, and stops. There's no
  auto-apply flag in `site_fix` and this mustn't become one: an unattended
  model editing a customer's live homepage can do real damage, and "it's only
  a title tag" stops being true when a page builder stores the whole page in
  that field. Approval stays with a named person.
- It watches what it already changed. Applied fixes are re-read on a slower
  cadence. If the owner reverted one, that's their call: it's recorded as
  `drifted` and reported, never re-applied.

Everything runs through the durable queue rather than the heartbeat thread, so
a container recycled mid-audit retries instead of losing the work. Each client
is enqueued under a dedupe key so a slow site can't pile up duplicate jobs.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from ..core import events, queue, site_access, site_fix

# Job kinds. Registered on import of `register_handlers`, which main calls at
# boot alongside the other adapters.
AUDIT_AND_PROPOSE = "site.audit_and_propose"
VERIFY_APPLIED = "site.verify_applied"

# How often a connected site is re-audited. Six hours matches the self-audit:
# often enough to catch a regression the day it ships, rarely enough that
# Titan is never a noticeable share of a client's traffic.
INTERVAL = float(os.getenv("TITAN_FIX_CYCLE_INTERVAL", str(6 * 3600)))

# Applied fixes are re-checked less often - a page rarely changes back within
# the hour, and every check is a request to someone's server.
VERIFY_INTERVAL = float(os.getenv("TITAN_FIX_VERIFY_INTERVAL", str(24 * 3600)))

_last_run = 0.0
_last_verify = 0.0


# ------------------------------------------------------------------ handlers --
def audit_and_propose(payload: dict) -> dict:
    """Re-audit one client's site and record what could be fixed.

    Returns counts only. The proposals live in `site_fix`, and nothing here
    touches the site beyond reading it.
    """
    from ..core import clients
    from . import client_seo

    cid = (payload or {}).get("client_id", "")
    rec = clients.get(cid)
    if not rec:
        return {"client_id": cid, "skipped": "no such client"}
    if cid not in site_access.connected_ids():
        return {"client_id": cid, "skipped": "site no longer connected"}

    website = rec.get("website") or ""
    if not website:
        return {"client_id": cid, "skipped": "no website on the client record"}

    audit = client_seo.audit(
        website,
        business_name=rec.get("business_name", ""),
        city=rec.get("city", ""),
        country=rec.get("country", ""),
        industry=rec.get("industry", ""))
    if not audit.get("ok"):
        # A site that's down is a finding, not a job failure. Retrying it four times
        # with backoff would just send four more requests to a struggling server.
        return {"client_id": cid, "audited": False,
                "error": audit.get("error"), "score": None}

    clients.update_raw(cid, last_audit=audit)
    out = site_fix.propose(cid, audit, business=rec)

    # Only count proposals that are new; `propose` runs every cycle and would
    # otherwise re-raise the same fix forever.
    proposed = out.get("proposed", []) if out.get("ok") else []
    events.emit("SiteFixCycleRan", {
        "client": cid, "score": audit.get("score"),
        "proposed": len(proposed),
        "skipped": len(out.get("skipped", [])),
    }, actor="fix-cycle", severity="info")

    return {
        "client_id": cid,
        "audited": True,
        "score": audit.get("score"),
        "grade": audit.get("grade"),
        "proposed": len(proposed),
        "cannot_fix": len(out.get("skipped", [])),
        "error": None if out.get("ok") else out.get("error"),
    }


def verify_applied(payload: dict) -> dict:
    """Re-read fixes Titan applied to see whether they're still live.

    Drift is recorded, never corrected. The owner is allowed to change their
    mind, and a tool that silently reinstates its own edit shouldn't hold a
    credential.
    """
    cid = (payload or {}).get("client_id", "")
    cred = site_access.credential(cid)
    if not cred:
        return {"client_id": cid, "skipped": "site no longer connected"}

    checked, drifted = 0, []
    for row in site_fix.for_client(cid, status=site_fix.APPLIED):
        fix = site_fix.get(row["id"])
        if not fix:
            continue
        live, err = site_fix._read_field(cred, fix["target"], fix["field"])
        checked += 1
        if err:
            continue
        if live != fix["proposed"]:
            site_fix.mark_drifted(fix["id"], live)
            drifted.append(fix["id"])

    if drifted:
        events.emit("SiteFixDrifted", {"client": cid, "fixes": drifted},
                    actor="fix-cycle", severity="warn")
    return {"client_id": cid, "checked": checked, "drifted": len(drifted),
            "drifted_ids": drifted}


def register_handlers() -> None:
    """Idempotent. Called at boot, before the heartbeat drains anything."""
    queue.register(AUDIT_AND_PROPOSE, audit_and_propose)
    queue.register(VERIFY_APPLIED, verify_applied)


# --------------------------------------------------------------- scheduling --
def cycle(force: bool = False) -> Optional[dict]:
    """Heartbeat entry point. Enqueues work; never does it inline.

    Keeps its own interval so it can ride the existing client-watch tick
    without another timer.
    """
    global _last_run, _last_verify
    try:
        register_handlers()
        now = time.monotonic()
        out = {"enqueued_audits": 0, "enqueued_verifies": 0,
               "connected": len(site_access.connected_ids())}

        if force or now - _last_run >= INTERVAL:
            _last_run = now
            for cid in site_access.connected_ids():
                job = queue.enqueue(
                    AUDIT_AND_PROPOSE, {"client_id": cid},
                    # One open audit per client, so a slow site can't pile up duplicates.
                    dedupe_key=f"{AUDIT_AND_PROPOSE}:{cid}")
                if not job.get("deduped"):
                    out["enqueued_audits"] += 1

        if force or now - _last_verify >= VERIFY_INTERVAL:
            _last_verify = now
            for cid in site_access.connected_ids():
                job = queue.enqueue(
                    VERIFY_APPLIED, {"client_id": cid},
                    dedupe_key=f"{VERIFY_APPLIED}:{cid}", priority=7)
                if not job.get("deduped"):
                    out["enqueued_verifies"] += 1

        return out
    except Exception:
        return None


def status() -> dict:
    """What the cycle is responsible for, and what it has done."""
    connected = site_access.connected_ids()
    summary = site_fix.summary()
    return {
        "connected_sites": len(connected),
        "interval_hours": round(INTERVAL / 3600, 1),
        "verify_interval_hours": round(VERIFY_INTERVAL / 3600, 1),
        "queue": queue.stats(),
        "fixes": summary,
        "applies_automatically": False,
        "note": ("Titan re-audits every connected site on this cadence and "
                 "proposes fixes. It never applies one — approval is human "
                 "and is recorded by name. Fixes already applied are re-read "
                 "and reported as drifted if they are no longer live; they "
                 "are never silently re-applied."),
    }
