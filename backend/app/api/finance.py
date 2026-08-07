"""Financial Center + CRM-lite APIs.

Finance: real expense ledger next to the real revenue ledger; profit is simply
revenue - expenses, and the forecast is an honest run-rate projection from the
last 30 days (labelled as such — no invented growth curves).

CRM-lite: a leads pipeline (new → contacted → replied → won/lost) so outreach
from the lead-finder / Job Radar has somewhere real to live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import persistence
from ..store import STORE, now

router = APIRouter(prefix="/api")

LEAD_STATUSES = ["new", "contacted", "replied", "won", "lost"]

# The ordered progress path. "lost" is a terminal outcome, not a stage — a lead
# can be lost from anywhere, so it never appears here.
LEAD_STAGES = ["new", "contacted", "replied", "won"]


def _stage_reached(lead: dict) -> int:
    """Furthest stage index this lead ever reached.

    Stored on the lead from now on. Derived for leads created before the field
    existed: their current status is the best evidence available. A legacy lead
    already marked 'lost' genuinely cannot be placed — nothing recorded how far
    it got — so it counts only at 'new' rather than inventing a stage for it.
    """
    stored = lead.get("stage_reached")
    if isinstance(stored, int):
        return max(0, min(stored, len(LEAD_STAGES) - 1))
    status = lead.get("status", "new")
    return LEAD_STAGES.index(status) if status in LEAD_STAGES else 0


def _funnel(items: list) -> dict:
    """How many leads ever reached each stage, newest stage last.

    Deliberately NOT built from `counts`: counts say where leads are sitting
    right now, so a lead that reached 'won' has already left 'contacted' and a
    counts-based chart shows conversion increasing down the funnel.
    """
    top = len(items)
    rows = []
    for i, stage in enumerate(LEAD_STAGES):
        reached = sum(1 for l in items if _stage_reached(l) >= i)
        rows.append({
            "stage": stage,
            "reached": reached,
            "pct": round(100.0 * reached / top, 1) if top else 0.0,
        })
    # Drop-off is only meaningful between adjacent stages.
    for i, row in enumerate(rows):
        row["dropped"] = (rows[i - 1]["reached"] - row["reached"]) if i else 0
    won = rows[-1]["reached"] if rows else 0
    return {
        "funnel": rows,
        "lost": sum(1 for l in items if l.get("status") == "lost"),
        "conversion_pct": round(100.0 * won / top, 1) if top else 0.0,
    }


# --- Financial Center --------------------------------------------------------

def _recent_total(entries: list, days: int) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0.0
    for e in entries:
        try:
            ts = datetime.fromisoformat(str(e.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            total += float(e.get("amount", 0.0))
    return total


@router.get("/finance", tags=["finance"])
def finance_state() -> dict:
    revenue_total = float(STORE.metrics.get("mrr", 0.0))
    expenses_total = sum(float(e.get("amount", 0.0)) for e in STORE.expenses)
    rev_30 = _recent_total(STORE.revenue_entries, 30)
    exp_30 = _recent_total(STORE.expenses, 30)
    return {
        "revenue_total": revenue_total,
        "expenses_total": expenses_total,
        "profit": revenue_total - expenses_total,
        "revenue_30d": rev_30,
        "expenses_30d": exp_30,
        # Honest run-rate: last-30-days pace projected forward one month.
        "forecast_monthly_revenue": rev_30,
        "forecast_monthly_profit": rev_30 - exp_30,
        "expenses": list(reversed(STORE.expenses))[:100],
    }


class ExpenseLog(BaseModel):
    amount: float = Field(..., gt=0)
    category: str = Field(default="other", description="tools | ads | fees | other")
    note: str = Field(default="")


@router.post("/finance/expense", tags=["finance"])
def log_expense(entry: ExpenseLog) -> dict:
    record = {
        "id": STORE.new_id("exp"),
        "amount": float(entry.amount),
        "category": (entry.category or "other").lower(),
        "note": entry.note or "",
        "created_at": now().isoformat(),
    }
    STORE.expenses.append(record)
    STORE.emit("finance-head", "metric",
               f"Expense logged: -${entry.amount:.2f} ({record['category']}) {entry.note[:40]}",
               "warn")
    persistence.save(STORE)
    return record


@router.delete("/finance/expense/{expense_id}", tags=["finance"])
def delete_expense(expense_id: str) -> dict:
    idx = next((i for i, e in enumerate(STORE.expenses) if e.get("id") == expense_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    rec = STORE.expenses.pop(idx)
    persistence.save(STORE)
    return {"deleted": expense_id, "amount": rec.get("amount", 0.0)}


# --- CRM-lite ---------------------------------------------------------------

@router.get("/leads", tags=["crm"])
def list_leads() -> dict:
    items = sorted(STORE.leads.values(), key=lambda l: l.get("updated_at", ""), reverse=True)
    counts = {s: sum(1 for l in items if l.get("status") == s) for s in LEAD_STATUSES}
    return {"items": items, "counts": counts, "statuses": LEAD_STATUSES,
            "stages": LEAD_STAGES, **_funnel(items)}


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1)
    source: str = Field(default="manual", description="e.g. fiverr | linkedin | school | jobradar")
    contact: str = Field(default="", description="email / profile URL / phone")
    note: str = Field(default="")


@router.post("/leads", tags=["crm"])
def create_lead(req: LeadCreate) -> dict:
    lead = {
        "id": STORE.new_id("lead"),
        "name": req.name.strip()[:80],
        "source": (req.source or "manual").lower()[:30],
        "contact": req.contact.strip()[:200],
        "note": req.note.strip()[:300],
        "status": "new",
        "stage_reached": 0,
        "created_at": now().isoformat(),
        "updated_at": now().isoformat(),
    }
    STORE.leads[lead["id"]] = lead
    STORE.emit("revenue-head", "discovery", f"New lead: {lead['name']} ({lead['source']})", "info")
    persistence.save(STORE)
    return lead


class LeadStatus(BaseModel):
    status: str = Field(...)


@router.post("/leads/{lead_id}/status", tags=["crm"])
def set_lead_status(lead_id: str, req: LeadStatus) -> dict:
    lead = STORE.leads.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    status = req.status.lower()
    if status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {LEAD_STATUSES}")
    # Record the high-water mark BEFORE overwriting status, and never lower it:
    # marking a lead lost must not erase how far it got, and correcting a
    # mis-click (won → contacted) must not un-count stages it genuinely reached.
    if status in LEAD_STAGES:
        lead["stage_reached"] = max(_stage_reached(lead), LEAD_STAGES.index(status))
    else:
        lead["stage_reached"] = _stage_reached(lead)
    lead["status"] = status
    lead["updated_at"] = now().isoformat()
    if status == "won":
        STORE.emit("revenue-head", "revenue", f"🏆 Lead WON: {lead['name']} — log the order in the Revenue Ledger!", "success")
    persistence.save(STORE)
    return lead


class LeadResearch(BaseModel):
    lang: str = Field(default="en")


@router.post("/leads/{lead_id}/research", tags=["crm"])
def research_lead(lead_id: str, req: LeadResearch | None = None) -> dict:
    """Audit this lead's own website, then draft outreach from what was found.

    This is the pitch Titan can make that a generic outreach tool cannot: it
    had to crawl the site to say anything, so every claim is checkable. If
    there is no website, or the site cannot be read, it says so and writes
    nothing — outreach citing a problem the recipient does not have loses the
    deal on the first reply.

    Returns a DRAFT. Nothing is sent to anyone.
    """
    from ..engines import outreach

    lead = STORE.leads.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lang = (req.lang if req else "en") or "en"
    res = outreach.research(lead)
    msg = outreach.draft(lead, res, lang)

    # File it on the lead so the research is not lost when the tab closes.
    lead["research"] = res
    lead["draft"] = msg
    lead["updated_at"] = now().isoformat()
    STORE.emit("revenue-head", "discovery",
               (f"Researched {lead['name']}: "
                + (f"scored {res['score']}/100, {res['total_findings']} findings"
                   if res.get("ok") else "no site to audit")),
               "info" if res.get("ok") else "warn")
    persistence.save(STORE)
    return {"lead_id": lead_id, "research": res, "draft": msg}


@router.delete("/leads/{lead_id}", tags=["crm"])
def delete_lead(lead_id: str) -> dict:
    if lead_id not in STORE.leads:
        raise HTTPException(status_code=404, detail="Lead not found")
    del STORE.leads[lead_id]
    persistence.save(STORE)
    return {"deleted": lead_id}
