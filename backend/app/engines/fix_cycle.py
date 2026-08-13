"""The 24/7 half of the fix loop — Titan keeps working with nobody logged in.

`core/site_fix` is the loop: propose → approve → apply → verify → rollback.
This is what drives it continuously, and what it deliberately does NOT do is
the important part.

**It never applies anything.** It re-audits, proposes, and stops. There is no
auto-apply flag in `site_fix` and this must not become one. A model editing a
stranger's live homepage at 3am with nobody watching is the single fastest way
to destroy a customer's business and Titan's reputation together, and "it was
only a title tag" stops being true the first time a page builder stores the
whole page in that field. Approval stays human, and stays named.

**It watches what it already changed.** An applied fix is re-read on a slower
cadence to see whether it is still live. Somebody reverting Titan's change is
normal and fine — the owner is allowed to disagree — so it is recorded as
`drifted` and reported, never re-applied. A tool that quietly puts a change
back after a human removed it is not a tool anybody should give write access
to.

Everything runs through the durable queue rather than on the heartbeat thread,
so a container recycled mid-audit retries instead of silently losing the work.
Each client is enqueued under a dedupe key, so a slow site cannot pile up
duplicate jobs behind itself.
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

# How often a connected site is re-audited. Six hours matches the self-audit
# cadence: frequent enough to catch a regression the day it ships, rare enough
# that Titan is never a meaningful share of a client's traffic.
INTERVAL = float(os.getenv("TITAN_FIX_CYCLE_INTERVAL", str(6 * 3600)))

# Applied fixes are re-checked on a slower cadence — a page does not usually
# change back within the hour, and every check is a request to someone's server.
VERIFY_INTERVAL = float(os.getenv("TITAN_FIX_VERIFY_INTERVAL", str(24 * 3600)))

_last_run = 0.0
_last_verify = 0.0


# ------------------------------------------------------------------ handlers --
def audit_and_propose(payload: dict) -> dict:
    """Re-audit one client's site and record what could be fixed.

    Returns counts only. The proposals themselves live in `site_fix`, and
    nothing here touches the site beyond reading it.
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
        # A site that is down is a finding, not a job failure — retrying it
        # four times with backoff would just be four more requests to a server
        # that is already struggling.
        return {"client_id": cid, "audited": False,
                "error": audit.get("error"), "score": None}

    clients.update_raw(cid, last_audit=audit)
    out = site_fix.propose(cid, audit, business=rec)

    # Only count proposals that are genuinely new. `propose` is called every
    # cycle and would otherwise re-raise the same fix forever.
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
    """Re-read fixes Titan applied, to see whether they are still live.

    Drift is recorded, never corrected. The owner is allowed to change their
    mind, and a tool that silently reinstates its own edit after a human
    removed it has no business holding a credential.
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
    """Heartbeat entry point. Enqueues work; never performs it inline.

    Keeps its own interval so it can ride the existing client-watch tick
    without adding another timer.
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
                    # One open audit per client. A slow site cannot pile up a
                    # queue of duplicates behind itself.
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
    """What the cycle is responsible for, and what it has actually done."""
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
