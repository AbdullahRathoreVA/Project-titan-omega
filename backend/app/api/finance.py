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
    return {"items": items, "counts": counts, "statuses": LEAD_STATUSES}


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
    lead["status"] = status
    lead["updated_at"] = now().isoformat()
    if status == "won":
        STORE.emit("revenue-head", "revenue", f"🏆 Lead WON: {lead['name']} — log the order in the Revenue Ledger!", "success")
    persistence.save(STORE)
    return lead


@router.delete("/leads/{lead_id}", tags=["crm"])
def delete_lead(lead_id: str) -> dict:
    if lead_id not in STORE.leads:
        raise HTTPException(status_code=404, detail="Lead not found")
    del STORE.leads[lead_id]
    persistence.save(STORE)
    return {"deleted": lead_id}
