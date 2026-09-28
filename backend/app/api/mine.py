"""A subscriber's own businesses, for the cockpit's Clients and SEO tabs.

Same response shapes as the founder's /api/admin/* routes, so the same
screens can render them, limited to the caller's businesses. Only reachable
through /api/me/mine/*; called any other way there is no subscriber bound
and every route returns 404.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import persistence
from ..core import billing, clients, cockpit_scope, ratelimit
from ..store import STORE
from .router import (OnboardIn, business_report_pdf, client_schema,
                     onboard_business, run_client_audit)

router = APIRouter(prefix="/api/mine")


def _me() -> str:
    email = cockpit_scope.customer_email()
    if not email:
        raise HTTPException(status_code=404, detail="Not found")
    return email


def _owned(cid: str) -> str:
    """The caller's email if they own this business, else 404.

    Same 404 as a missing business, so ids can't be probed.
    """
    email = _me()
    if cid not in billing.owned_clients(email) or not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    return email


def _mine() -> set:
    return set(billing.owned_clients(_me()))


@router.get("/clients", tags=["cockpit"])
def my_clients() -> dict:
    email = _me()
    return {**clients.admin_overview(only=set(billing.owned_clients(email))),
            "limit": billing.can_add_client(email)}


@router.post("/clients", tags=["cockpit"])
def add_my_client(req: OnboardIn) -> dict:
    return onboard_business(_me(), req)


@router.get("/clients/{cid}", tags=["cockpit"])
def my_client(cid: str) -> dict:
    _owned(cid)
    return clients.public(cid)


@router.delete("/clients/{cid}", tags=["cockpit"])
def remove_my_client(cid: str) -> dict:
    email = _owned(cid)
    clients.delete_client(cid)
    billing.detach_client(email, cid)
    persistence.save(STORE)
    return {"ok": True}


@router.post("/clients/{cid}/seo", tags=["cockpit"])
def audit_my_client(cid: str) -> dict:
    """A re-audit spends one audit from the plan, as onboarding does."""
    email = _owned(cid)
    verdict = billing.consume(email, "audits")
    if not verdict["allowed"]:
        raise HTTPException(status_code=402, detail=verdict)
    return run_client_audit(cid)


@router.get("/clients/{cid}/seo/schema", tags=["cockpit"])
def my_client_schema(cid: str) -> dict:
    _owned(cid)
    return client_schema(cid)


@router.get("/clients/{cid}/report.pdf", tags=["cockpit"])
def my_client_report(cid: str):
    return business_report_pdf(cid, _owned(cid))


@router.get("/watch", tags=["cockpit"])
def my_watch() -> dict:
    from ..engines import client_watch
    return client_watch.summary(only=_mine())


@router.post("/clients/{cid}/watch", tags=["cockpit"])
def watch_my_client_now(cid: str) -> dict:
    """A check is a live crawl of their site, so it shares onboarding's limit."""
    from ..engines import client_watch
    email = _owned(cid)
    limited = ratelimit.check("onboard", email)
    if not limited["allowed"]:
        raise HTTPException(status_code=429, detail=limited)
    r = client_watch.check_client(cid)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "failed"))
    persistence.save(STORE)
    return r


@router.get("/seo-overview", tags=["cockpit"])
def my_seo_overview() -> dict:
    """SEO panel for the Executive tab, limited to the caller's businesses.

    `titan` is None here: Titan's own score is only shown to the founder.
    """
    from .router import SEO_OVERVIEW_NOTE, seo_rows
    rows, scored = seo_rows(only=_mine())
    return {
        "titan": None,
        "clients": rows,
        "client_average": round(sum(scored) / len(scored), 1) if scored else None,
        "unaudited": sum(1 for r in rows if not r["audited"]),
        "note": SEO_OVERVIEW_NOTE,
    }


@router.get("/discovery", tags=["cockpit"])
def my_discovery(live: bool = Query(False)) -> dict:
    """Sellable work across the caller's businesses, from their stored audits.

    `live` is ignored - re-crawling every site isn't something a GET should do.
    """
    from ..engines import discovery
    only = _mine()
    cache = {}
    for c in clients.all_clients():
        if c["id"] in only and c.get("last_audit"):
            cache[c["id"]] = c["last_audit"]
    return discovery.report(cache, live=False, only=only)
