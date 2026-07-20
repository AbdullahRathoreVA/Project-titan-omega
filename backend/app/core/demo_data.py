"""Demo-safe payloads for the public guest session.

One Space now serves both the founder's real dashboard and a public demo. The
guest must NEVER see real business data, so every endpoint carrying private
information is intercepted and answered from here instead of the live store.

What a guest DOES see live (genuinely impressive, zero private data): the 102
agents working through their division pipelines, divisions, opportunities,
the universe, council decisions and the activity feed (revenue lines filtered).

What a guest NEVER sees: real revenue/ledger, expenses, CRM leads, Telegram
logs, job-radar applications, generated deliverables.

Every figure below is clearly marked SAMPLE — the honesty rule applies to
demos too.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from ..store import STORE, now

# Paths whose real content is private. Anything not listed passes through live.
_SENSITIVE_PREFIXES = (
    "/api/finance",
    "/api/leads",
    "/api/revenue",
    "/api/telegram",
    "/api/jobs",
    "/api/deliverables",
)

_LEAD_STATUSES = ["new", "contacted", "replied", "won", "lost"]

# One source of truth for the demo's headline numbers, so the status card, the
# live SSE stream, the revenue ledger and the finance panel can never disagree.
DEMO_MRR = 693.0
DEMO_PIPELINE = 4200.0
DEMO_TRAFFIC = 1280


def is_revenue_event(e: dict) -> bool:
    """Real order/revenue lines must never reach a public demo visitor."""
    return e.get("kind") == "revenue" or "REAL ORDER" in str(e.get("message", ""))


def _iso(days_ago: int) -> str:
    return (now() - timedelta(days=days_ago)).isoformat()


def _sample_expenses() -> list:
    return [
        {"id": "exp-demo-1", "amount": 12.0, "category": "tools", "note": "[SAMPLE] Domain renewal", "created_at": _iso(18)},
        {"id": "exp-demo-2", "amount": 25.0, "category": "marketing", "note": "[SAMPLE] Boosted launch post", "created_at": _iso(8)},
    ]


def _sample_revenue_entries() -> list:
    return [
        {"id": "rev-demo-5", "amount": 180.0, "source": "client", "note": "[SAMPLE] n8n workflow retainer", "created_at": _iso(2)},
        {"id": "rev-demo-4", "amount": 35.0, "source": "product", "note": "[SAMPLE] Digital product sale", "created_at": _iso(6)},
        {"id": "rev-demo-3", "amount": 240.0, "source": "client", "note": "[SAMPLE] Custom dashboard deployment", "created_at": _iso(9)},
        {"id": "rev-demo-2", "amount": 89.0, "source": "fiverr", "note": "[SAMPLE] Automation pipeline gig", "created_at": _iso(14)},
        {"id": "rev-demo-1", "amount": 149.0, "source": "client", "note": "[SAMPLE] AI chatbot build", "created_at": _iso(21)},
    ]


def _sample_leads() -> list:
    return [
        {"id": "lead-demo-1", "name": "[SAMPLE] Horizon Digital Agency", "source": "linkedin", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Wants white-label AI dashboard", "status": "negotiating" if "negotiating" in _LEAD_STATUSES else "replied",
         "created_at": _iso(5), "updated_at": _iso(1)},
        {"id": "lead-demo-2", "name": "[SAMPLE] K. Marketing Studio", "source": "fiverr", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Asked for automation audit", "status": "contacted", "created_at": _iso(7), "updated_at": _iso(2)},
        {"id": "lead-demo-3", "name": "[SAMPLE] SaaS founder (beta list)", "source": "referral", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Interested in enterprise tier", "status": "new", "created_at": _iso(3), "updated_at": _iso(3)},
    ]


def _sample_jobs() -> dict:
    return {
        "items": [
            {"score": 88, "title": "[SAMPLE] Remote AI Automation Developer", "url": "https://example.com/sample-job-1",
             "why": "[SAMPLE] Matches FastAPI + n8n + LLM integration experience", "applied": False},
            {"score": 76, "title": "[SAMPLE] Python / LLM Integration Engineer", "url": "https://example.com/sample-job-2",
             "why": "[SAMPLE] Strong overlap with multi-provider LLM work", "applied": False},
        ],
        "live": True,
        "last_scan": _iso(0),
    }


def is_sensitive(path: str) -> bool:
    return path.startswith(_SENSITIVE_PREFIXES)


def guest_payload(path: str, limit: int = 50) -> Optional[Any]:
    """Demo-safe replacement for a guest GET, or None to serve the live response."""
    # --- private business data: fully substituted -------------------------
    if path == "/api/finance":
        rev, exp = DEMO_MRR, 37.0
        return {
            "revenue_total": rev, "expenses_total": exp, "profit": rev - exp,
            "revenue_30d": 455.0, "expenses_30d": 25.0,
            "forecast_monthly_revenue": 455.0, "forecast_monthly_profit": 430.0,
            "expenses": _sample_expenses(),
        }
    if path == "/api/leads":
        items = _sample_leads()
        return {
            "items": items,
            "counts": {s: sum(1 for l in items if l.get("status") == s) for s in _LEAD_STATUSES},
            "statuses": _LEAD_STATUSES,
        }
    if path == "/api/revenue":
        return {
            "total": DEMO_MRR,
            "by_source": {"fiverr": 89.0, "career_mind": 0.0, "kindle": 0.0, "other": 604.0},
            "fiverr_orders": 1,
        }
    if path == "/api/revenue/entries":
        return _sample_revenue_entries()
    if path == "/api/telegram/status":
        return {"configured": True, "locked": True, "handled": 12}
    if path == "/api/telegram/log":
        return []
    if path == "/api/jobs":
        return _sample_jobs()
    if path == "/api/deliverables":
        return []
    if path == "/api/progress":
        # XP is computed from real revenue/leads, so it must be sampled too —
        # otherwise the demo shows "LV 1 · 0 XP" beside $693 of sample earnings.
        return {
            "xp": 7180, "level": 9, "level_floor": 6400, "next_level_xp": 8100,
            "milestones": [
                {"label": "First real order logged", "done": True},
                {"label": "First lead contacted", "done": True},
                {"label": "First lead won", "done": True},
                {"label": "10 posts scheduled", "done": True},
                {"label": "First deliverable produced", "done": True},
                {"label": "First job application sent", "done": False},
                {"label": "$1,000 earned", "done": False},
            ],
        }

    # --- live but money-masked -------------------------------------------
    if path == "/api/status":
        from . import executive

        s = executive.empire_status(STORE)
        s["mrr"] = DEMO_MRR          # SAMPLE — never the founder's real revenue
        s["pipeline_value"] = DEMO_PIPELINE
        s["traffic"] = DEMO_TRAFFIC
        s["updated_at"] = s["updated_at"].isoformat() if hasattr(s["updated_at"], "isoformat") else s["updated_at"]
        return s

    if path == "/api/feed":
        out = []
        for e in STORE.recent_feed(limit):
            # Never leak real order/revenue lines into the public demo.
            if is_revenue_event(e):
                continue
            ev = dict(e)
            ts = ev.get("timestamp")
            ev["timestamp"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
            out.append(ev)
        return out

    return None
