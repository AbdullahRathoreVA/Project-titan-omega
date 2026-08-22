"""HTTP API for the command center.

All routes are mounted under ``/api``. Responses use the pydantic schemas in
:mod:`domain.schemas` so the Next.js dashboard has a stable contract.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import (APIRouter, Header, HTTPException, Query, Request,
                     Response)
from pydantic import BaseModel, Field

from .. import persistence
from ..core import auth, clients, executive, learning, llm
from ..domain.enums import Horizon
from ..domain.schemas import (
    AgentView,
    CommandRequest,
    CommandResponse,
    Connector,
    Deliverable,
    DivisionView,
    EmpireStatus,
    ExecutionAction,
    FeedEvent,
    Forecast,
    Opportunity,
    ScheduledPost,
    StrategicPlan,
)
from ..engines import (brand_playbook, client_content, client_report,
                       client_watch, compliance,
                       client_seo, discovery,
                       deliverables, evolution, execution,
                       opportunity, publisher)
from ..store import STORE, AgentRuntime, now
from .actions import UPWORK_PROFILE_URL

router = APIRouter(prefix="/api")


# --- auth -----------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/auth", tags=["auth"])
def auth_status() -> dict:
    from ..core import identity
    return {
        "required": auth.require_auth(),
        "demo": auth.using_demo_credentials(),
        "guest": auth.guest_mode(),
        # Public "View demo" button on the login screen.
        "guest_available": auth.guest_enabled(),
        # Which login is in force. `identity` means real accounts with roles;
        # `legacy` means the single environment gate is still answering. This
        # endpoint is public, so identity.mode() deliberately carries no
        # address — publishing the one account that can administer the system
        # would hand a passer-by the first half of the credentials.
        "identity": identity.mode(),
    }


@router.get("/session", tags=["auth"])
def session(request: Request) -> dict:
    """What KIND of session is this token? The front end must not guess from
    browser storage — a demo token restored in a new tab would otherwise be
    presented as the founder while still being served sample data."""
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return {"founder": auth.valid_token(tok), "guest": auth.valid_guest_token(tok)}


@router.post("/demo/enter", tags=["auth"])
def enter_demo() -> dict:
    """Start a public, read-only demo session — no login required.

    Returns a guest token that unlocks GET-only access. Every endpoint holding
    real business data is served demo-safe sample content instead, and any
    write is refused, so a visitor can explore the whole system without ever
    seeing the founder's private data or changing anything.
    """
    if not auth.guest_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    return {"token": auth.make_guest_token(), "guest": True}


@router.post("/login", tags=["auth"])
def login(req: LoginRequest, request: Request) -> dict:
    from ..core import ratelimit
    # The founder's door had no rate limit at all, while the customer door a
    # few hundred lines below has had one since the day it was written. Keyed
    # on the caller rather than on what was typed, so nobody can lock the
    # founder out of his own site by hammering his address.
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    token = auth.login(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    # The identifier Titan actually authenticated, not the one that was typed.
    # Real accounts normalise the address, so echoing the input back would show
    # a capitalisation that is not what is stored.
    return {"token": token,
            "username": auth.founder_from_token(token) or req.username}


# --- serialization helpers ------------------------------------------------

def _agent_view(rt: AgentRuntime) -> AgentView:
    s = rt.spec
    return AgentView(
        id=s.id,
        name=s.name,
        title=s.title,
        division=s.division,
        is_head=s.is_head,
        autonomy=s.autonomy,
        status=rt.status,
        mission=s.mission,
        current_task=rt.current_task,
        progress=rt.progress,
        goals=s.goals,
        kpis=s.kpis,
        tools=s.tools,
        tasks_completed=rt.tasks_completed,
        success_rate=rt.success_rate,
        impact_score=rt.impact_score,
        last_active=rt.last_active,
    )


# --- empire / executive ---------------------------------------------------

@router.get("/status", response_model=EmpireStatus, tags=["executive"])
def get_status() -> EmpireStatus:
    return EmpireStatus(**executive.empire_status(STORE))


@router.get("/divisions", response_model=List[DivisionView], tags=["executive"])
def get_divisions() -> List[DivisionView]:
    return [DivisionView(**d) for d in executive.division_health(STORE)]


@router.get("/plan/{horizon}", response_model=StrategicPlan, tags=["executive"])
def get_plan(horizon: Horizon) -> StrategicPlan:
    return StrategicPlan(**executive.generate_plan(horizon, STORE))


@router.get("/forecast/{metric}", response_model=Forecast, tags=["executive"])
def get_forecast(
    metric: str,
    horizon: Horizon = Query(default=Horizon.MONTHLY),
) -> Forecast:
    try:
        return Forecast(**executive.forecast(metric, horizon, STORE))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric}")


@router.post("/command", response_model=CommandResponse, tags=["executive"])
def post_command(req: CommandRequest) -> CommandResponse:
    return CommandResponse(**executive.route_command(req.text, STORE))


# --- agents ---------------------------------------------------------------

@router.get("/agents", response_model=List[AgentView], tags=["agents"])
def list_agents(
    division: Optional[str] = Query(default=None),
    heads_only: bool = Query(default=False),
) -> List[AgentView]:
    out = []
    for rt in STORE.agents.values():
        if division and rt.spec.division.value != division:
            continue
        if heads_only and not rt.spec.is_head:
            continue
        out.append(_agent_view(rt))
    return out


@router.get("/agents/{agent_id}", response_model=AgentView, tags=["agents"])
def get_agent(agent_id: str) -> AgentView:
    rt = STORE.agents.get(agent_id)
    if rt is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_view(rt)


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/agents/{agent_id}/chat", tags=["agents"])
def agent_chat(agent_id: str, req: AgentChatRequest) -> dict:
    """Talk directly to one agent — it replies in character, using its own role,
    mission, and current task as context."""
    rt = STORE.agents.get(agent_id)
    if rt is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    s = rt.spec
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    reply = llm.complete(
        system=(
            f"You are {s.name}, the {s.title} in the {s.division.value} division of "
            "Abdullah's autonomous company, Titan Omega. Speak in character as this "
            f"agent. Your mission: {s.mission}. Right now you are working on: "
            f"{rt.current_task or 'advancing your division objectives'}. Address the "
            "founder as 'Abdullah'. Be concrete and specific about what YOU (this role) "
            f"are doing or will do. Keep it 2-4 sentences. Reply in {lang_name}."
        ),
        prompt=req.message,
        max_tokens=400,
    ) or (
        f"Abdullah, {s.name} here. I'm on it — {rt.current_task or 'advancing my objectives'}. "
        "Set an LLM key (Groq/Hermes, free) to unlock my full conversational replies."
    )

    STORE.emit(s.id, "command", f'Abdullah talked to {s.name}: "{req.message[:60]}"', "info")
    return {"agent_id": s.id, "name": s.name, "reply": reply}


# --- opportunities --------------------------------------------------------

@router.get("/opportunities", response_model=List[Opportunity], tags=["opportunities"])
def list_opportunities() -> List[Opportunity]:
    return [Opportunity(**o) for o in opportunity.ranked(STORE)]


@router.post("/opportunities/scan", response_model=List[Opportunity], tags=["opportunities"])
def scan_opportunities() -> List[Opportunity]:
    STORE.opportunities.clear()
    opportunity.discover(STORE)
    return [Opportunity(**o) for o in opportunity.ranked(STORE)]


# --- executions -----------------------------------------------------------

@router.get("/executions", response_model=List[ExecutionAction], tags=["execution"])
def list_executions() -> List[ExecutionAction]:
    actions = sorted(
        STORE.executions.values(), key=lambda a: a["created_at"], reverse=True
    )
    return [ExecutionAction(**a) for a in actions]


@router.get("/decisions", tags=["executive"])
def list_decisions(limit: int = 20) -> List[dict]:
    """Council decision history (memory timeline), newest first."""
    return list(reversed(STORE.decisions[-max(1, min(limit, 50)):]))


@router.post("/executions/from-opportunity/{opportunity_id}",
             response_model=ExecutionAction, tags=["execution"])
def execute_opportunity(opportunity_id: str) -> ExecutionAction:
    opp = STORE.opportunities.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    first_step = opp["execution_plan"][0] if opp["execution_plan"] else opp["title"]
    try:
        action = execution.propose(
            title=opp["title"],
            description=first_step,
            agent_id=opp["source_agent"],
            opportunity_id=opportunity_id,
            store=STORE,
        )
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ExecutionAction(**action)


@router.post("/executions/{action_id}/approve", response_model=ExecutionAction, tags=["execution"])
def approve_execution(action_id: str) -> ExecutionAction:
    return _transition(execution.approve, action_id)


@router.post("/executions/{action_id}/complete", response_model=ExecutionAction, tags=["execution"])
def complete_execution(action_id: str, result: str = Query(default="Done.")) -> ExecutionAction:
    return _transition(lambda aid, store: execution.complete(aid, result, store), action_id)


@router.post("/executions/{action_id}/revert", response_model=ExecutionAction, tags=["execution"])
def revert_execution(action_id: str) -> ExecutionAction:
    return _transition(execution.revert, action_id)


def _transition(fn, action_id: str) -> ExecutionAction:
    try:
        return ExecutionAction(**fn(action_id, STORE))
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- connectors -----------------------------------------------------------

@router.get("/connectors", response_model=List[Connector], tags=["connectors"])
def list_connectors() -> List[Connector]:
    return [Connector(**c) for c in STORE.connectors.values()]


@router.post("/connectors/refresh", response_model=List[Connector], tags=["connectors"])
def refresh_connectors() -> List[Connector]:
    from ..connectors import careermind, github
    github.refresh(STORE)
    careermind.refresh(STORE)
    return [Connector(**c) for c in STORE.connectors.values()]


# --- deliverables ---------------------------------------------------------

class DraftRequest(BaseModel):
    kind: str = Field(default="growth_strategy", description="e.g. outreach_email, seo_plan, growth_strategy")
    brief: str = Field(..., min_length=1)
    agent_id: str = "executive-head"


@router.get("/deliverables", response_model=List[Deliverable], tags=["deliverables"])
def list_deliverables() -> List[Deliverable]:
    return [Deliverable(**d) for d in deliverables.listing(STORE)]


@router.post("/deliverables/draft", response_model=Deliverable, tags=["deliverables"])
def draft_deliverable(req: DraftRequest) -> Deliverable:
    return Deliverable(**deliverables.generate(req.kind, req.brief, req.agent_id, store=STORE))


@router.post("/deliverables/from-opportunity/{opportunity_id}",
             response_model=Deliverable, tags=["deliverables"])
def deliverable_from_opportunity(opportunity_id: str) -> Deliverable:
    if opportunity_id not in STORE.opportunities:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return Deliverable(**deliverables.from_opportunity(opportunity_id, STORE))


@router.post("/report/weekly", response_model=Deliverable, tags=["deliverables"])
def weekly_report() -> Deliverable:
    plan = executive.generate_plan(Horizon.WEEKLY, STORE)
    status = executive.empire_status(STORE)
    brief = (
        f"Weekly empire report for Abdullah. MRR ${status['mrr']:,.0f}, "
        f"traffic {status['traffic']:,}, "
        f"{status['active_agents']}/{status['total_agents']} agents active, "
        f"{status['open_opportunities']} open opportunities. Top objectives: "
        + "; ".join(i["title"] for i in plan["items"])
    )
    return Deliverable(
        **deliverables.generate("business_report", brief, "executive-board-reporting-analyst", store=STORE)
    )


# --- publishing -----------------------------------------------------------

class SchedulePostRequest(BaseModel):
    content: str = Field(..., min_length=1)
    channels: List[str] = Field(default_factory=lambda: ["linkedin"])
    image_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None


@router.get("/posts", response_model=List[ScheduledPost], tags=["publishing"])
def list_posts() -> List[ScheduledPost]:
    return [ScheduledPost(**p) for p in publisher.listing(STORE)]


@router.post("/posts", response_model=ScheduledPost, tags=["publishing"])
def schedule_post(req: SchedulePostRequest) -> ScheduledPost:
    return ScheduledPost(
        **publisher.schedule(req.content, req.channels, req.image_url, req.scheduled_at, store=STORE)
    )


@router.post("/posts/{post_id}/publish", response_model=ScheduledPost, tags=["publishing"])
def publish_post(post_id: str) -> ScheduledPost:
    if post_id not in STORE.posts:
        raise HTTPException(status_code=404, detail="Post not found")
    return ScheduledPost(**publisher.publish(post_id, STORE))


# --- live feed ------------------------------------------------------------

@router.get("/feed", response_model=List[FeedEvent], tags=["feed"])
def get_feed(limit: int = Query(default=50, ge=1, le=200)) -> List[FeedEvent]:
    return [FeedEvent(**e) for e in STORE.recent_feed(limit)]


# --- real metrics webhook (Make.com / Zapier push real data here) ----------

def _verify_webhook(secret: Optional[str]) -> None:
    """Reject requests when TITAN_WEBHOOK_SECRET is set and header doesn't match.

    Used ONLY on the external metric-push endpoints that Make.com / Zapier call.
    In-dashboard buttons (revenue log, inbox reply) do NOT use this — they are
    same-origin and gated by the normal login token when auth is enabled.
    """
    expected = os.getenv("TITAN_WEBHOOK_SECRET")
    if expected and secret != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Webhook-Secret header")


class MetricUpdate(BaseModel):
    key: str
    value: float
    source: str = Field(default="webhook")


class BulkMetricUpdate(BaseModel):
    metrics: Dict[str, float]
    source: str = Field(default="webhook")


@router.get("/metrics", tags=["metrics"])
def get_metrics() -> dict:
    """Return all current empire metrics."""
    return {"metrics": dict(STORE.metrics), "source": "live"}


@router.post("/metrics/update", tags=["metrics"])
def update_metric(
    update: MetricUpdate,
    x_webhook_secret: Optional[str] = Header(default=None),
) -> dict:
    """Push a single real metric (e.g. from Make.com)."""
    _verify_webhook(x_webhook_secret)
    STORE.metrics[update.key] = update.value
    STORE.emit("webhook", "metric", f"{update.key} updated to {update.value} via {update.source}", "success")
    persistence.save(STORE)
    return {"updated": update.key, "value": update.value, "source": update.source}


@router.post("/metrics/bulk", tags=["metrics"])
def bulk_update_metrics(
    update: BulkMetricUpdate,
    x_webhook_secret: Optional[str] = Header(default=None),
) -> dict:
    """Push multiple real metrics at once (e.g. from Make.com hourly job)."""
    _verify_webhook(x_webhook_secret)
    STORE.metrics.update(update.metrics)
    keys = list(update.metrics.keys())
    STORE.emit(
        "webhook", "metric",
        f"{len(keys)} metrics updated from {update.source}: {', '.join(keys)}",
        "success",
    )
    persistence.save(STORE)
    return {"updated": keys, "count": len(keys), "source": update.source}


# --- REAL revenue ledger (Upwork orders, Career Mind sales, Kindle, etc.) ---

_SOURCE_KEY = {
    "fiverr": "fiverr_revenue",
    "career_mind": "cm_revenue",
    "careermind": "cm_revenue",
    "kindle": "kindle_royalties",
}


def _source_key(source: str) -> str:
    return _SOURCE_KEY.get((source or "other").lower(), "other_revenue")


class RevenueLog(BaseModel):
    amount: float = Field(..., gt=0, description="Amount earned in USD for this order/sale")
    source: str = Field(default="fiverr", description="fiverr | career_mind | kindle | other")
    note: str = Field(default="", description="Optional note, e.g. 'AI resume gig - first order'")


@router.get("/revenue", tags=["revenue"])
def get_revenue() -> dict:
    """Total real revenue earned + per-source breakdown."""
    m = STORE.metrics
    return {
        "total": float(m.get("mrr", 0.0)),
        "by_source": {
            "fiverr": float(m.get("fiverr_revenue", 0.0)),
            "career_mind": float(m.get("cm_revenue", 0.0)),
            "kindle": float(m.get("kindle_royalties", 0.0)),
            "other": float(m.get("other_revenue", 0.0)),
        },
        "fiverr_orders": int(m.get("fiverr_orders", 0)),
    }


@router.get("/revenue/entries", tags=["revenue"])
def revenue_entries() -> list:
    """Full order history, newest first — shows where every dollar came from."""
    return list(reversed(STORE.revenue_entries))


@router.post("/revenue/log", tags=["revenue"])
def log_revenue(entry: RevenueLog) -> dict:
    """Record a REAL earned order/sale. Appends a dated ledger entry and bumps
    the running total so the dashboard shows the truth.
    """
    m = STORE.metrics
    source = (entry.source or "other").lower()
    key = _source_key(source)

    m[key] = float(m.get(key, 0.0)) + entry.amount
    m["mrr"] = float(m.get("mrr", 0.0)) + entry.amount  # running total earned
    if source == "fiverr":
        m["fiverr_orders"] = float(m.get("fiverr_orders", 0)) + 1

    record = {
        "id": STORE.new_id("rev"),
        "amount": float(entry.amount),
        "source": source,
        "note": entry.note or "",
        "created_at": now().isoformat(),
    }
    STORE.revenue_entries.append(record)

    label = entry.note or f"{source} order"
    STORE.emit(
        "revenue-tracker", "revenue",
        f"💰 REAL ORDER: +${entry.amount:.2f} from {source} — {label}. "
        f"Total earned now ${m['mrr']:.2f}. Abdullah, the empire is EARNING!",
        "success",
    )
    persistence.save(STORE)
    return {"entry": record, "total": m["mrr"], "source_total": m[key]}


@router.delete("/revenue/entry/{entry_id}", tags=["revenue"])
def cancel_revenue(entry_id: str) -> dict:
    """Cancel / remove a logged order and decrement the running totals."""
    idx = next(
        (i for i, e in enumerate(STORE.revenue_entries) if e.get("id") == entry_id),
        None,
    )
    if idx is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    rec = STORE.revenue_entries.pop(idx)
    m = STORE.metrics
    source = rec.get("source", "other")
    key = _source_key(source)
    amount = float(rec.get("amount", 0.0))

    m[key] = max(0.0, float(m.get(key, 0.0)) - amount)
    m["mrr"] = max(0.0, float(m.get("mrr", 0.0)) - amount)
    if source == "fiverr":
        m["fiverr_orders"] = max(0.0, float(m.get("fiverr_orders", 0)) - 1)

    STORE.emit(
        "revenue-tracker", "revenue",
        f"Order cancelled: -${amount:.2f} ({source}). New total ${m['mrr']:.2f}.",
        "warn",
    )
    persistence.save(STORE)
    return {"cancelled": entry_id, "total": m["mrr"]}


# --- inbox auto-reply drafting (for Make.com DM automation) -----------------

class InboxMessage(BaseModel):
    message: str = Field(..., min_length=1, description="The incoming DM / message text")
    platform: str = Field(default="fiverr", description="fiverr | linkedin | instagram | email")
    lang: str = Field(default="en", description="'en' or 'ur'")
    sender: str = Field(default="", description="Optional sender name")


@router.post("/inbox/auto-reply", tags=["system"])
def inbox_auto_reply(msg: InboxMessage) -> dict:
    """Draft a professional, sales-savvy reply to an incoming DM."""
    is_urdu = msg.lang == "ur"
    lang_name = "Urdu (اردو)" if is_urdu else "English"
    upwork_link = os.getenv("UPWORK_PROFILE_URL", UPWORK_PROFILE_URL)
    cm_link = os.getenv("CAREERMIND_URL", "https://careermind2026-career-mind.hf.space")

    reply = llm.complete(
        system=(
            "You are Abdullah's professional sales assistant replying to a potential "
            f"client on {msg.platform}. Reply ONLY in {lang_name}. Be warm, fast, and "
            "close the sale. Abdullah sells AI services on Upwork and runs Career Mind AI "
            f"(a student career platform at {cm_link}). Upwork profile: {upwork_link}. "
            "Keep it 2-4 sentences, friendly, and end with a clear call to action. "
            "Never invent prices — invite them to share their requirements."
        ),
        prompt=f"Incoming message from {msg.sender or 'a prospect'}: {msg.message}",
        max_tokens=400,
    )

    if not reply:
        if is_urdu:
            reply = (
                "اسلام و علیکم! پیغام کا شکریہ۔ جی ہاں، میں آپ کی پوری مدد کر سکتا ہوں۔ "
                "براہ کرم اپنی ضرورت بتائیں تاکہ میں بہترین آفر دے سکوں۔"
            )
        else:
            reply = (
                "Hi, thanks so much for reaching out! Yes, I can absolutely help with that. "
                "Could you share a few details about what you need? I'll get you a tailored "
                "offer right away — fast delivery and 100% satisfaction guaranteed."
            )

    STORE.emit(
        "inbox-responder", "command",
        f"Drafted auto-reply for {msg.platform} DM from {msg.sender or 'prospect'}.",
        "info",
    )
    return {"reply": reply, "platform": msg.platform, "lang": msg.lang}


# --- Growth Studio: market analysis + outreach generators ------------------

_INTEL_PROMPTS = {
    "market_analysis": (
        "You are a sharp market analyst for Abdullah's AI businesses (Career Mind AI "
        "— a student career-guidance platform — and his Upwork AI service gigs). "
        "Produce a concise, actionable market analysis: current demand, the best target "
        "segments, a competitor angle, simple pricing ideas, and 3 ZERO-COST growth moves "
        "to execute THIS WEEK. Use clear headings and short bullets."
    ),
    "school_outreach": (
        "Write a short, warm cold email to a school or university administrator selling "
        "Career Mind AI — a free-trial AI career-guidance platform for students. Give a "
        "subject line, a 4-6 sentence body, and a clear call to action to book a 10-minute "
        "demo. Professional and genuine, no hype."
    ),
    "business_outreach": (
        "Write a short cold email / DM to a small business owner offering Abdullah's AI "
        "services from his Upwork gigs (custom chatbots, automation, AI content). Give a "
        "subject line, a 4-6 sentence body focused on concrete value, and a clear CTA. "
        "No hype, no fake promises."
    ),
    "jobseeker_outreach": (
        "Write a genuinely helpful community post aimed at people struggling to find a job. "
        "Introduce Career Mind AI (free career guidance) and Abdullah's affordable Upwork "
        "resume / LinkedIn services. Helpful tone, NOT spammy. Then list 5 specific places "
        "(subreddits, Facebook groups, Discords) where it is appropriate to share it."
    ),
    "customer_reply": (
        "Draft a warm, professional customer-care reply that resolves the issue and keeps "
        "the customer happy. If details are missing, ask one or two clarifying questions."
    ),
    "youtube_ideas": (
        "Suggest 8 specific YouTube video / Short ideas Abdullah can make for FREE to promote "
        "Career Mind AI and his Upwork AI gigs — each with a punchy title and a one-line hook. "
        "Then give 5 YouTube search queries he can use to study what is trending in this niche."
    ),
}


class IntelRequest(BaseModel):
    kind: str = Field(default="market_analysis")
    topic: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/intel/generate", tags=["system"])
def intel_generate(req: IntelRequest) -> dict:
    """Generate market analysis or outreach copy on demand via the free LLM."""
    base = _INTEL_PROMPTS.get(req.kind, _INTEL_PROMPTS["market_analysis"])
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    content = llm.complete(
        system=base + f" Write the entire output in {lang_name}.",
        prompt=req.topic
        or "Use Abdullah's businesses: Career Mind AI (student career platform) and Upwork AI gigs.",
        max_tokens=900,
    )

    if not content:
        content = (
            "AI generation is in free fallback mode. Set GROQ_API_KEY in your Space secrets "
            "(free, no card) and click again to get a full, tailored result here."
        )

    STORE.emit(
        "intelligence-studio", "discovery",
        f"Generated {req.kind.replace('_', ' ')} for Abdullah.", "success",
    )
    return {"kind": req.kind, "content": content}


# --- helpers for voice + assistant ----------------------------------------

def _empire_context() -> dict:
    """Gather the live numbers both the voice report and assistant rely on."""
    s = executive.empire_status(STORE)
    cm = STORE.connectors.get("careermind-main", {}).get("metrics", {})
    fiverr = next(
        (c["metrics"] for c in STORE.connectors.values()
         if c.get("name") == "Upwork Gig Network"),
        {},
    )
    return {
        "mrr": s.get("mrr", 0),
        "traffic": s.get("traffic", 0),
        "active_agents": s.get("active_agents", 0),
        "total_agents": s.get("total_agents", 102),
        "open_opportunities": s.get("open_opportunities", 0),
        "health": s.get("health", 0),
        "cm_users": int(cm.get("total_users", 0)),
        "cm_active": int(cm.get("active_users", 0)),
        "cm_signups": int(cm.get("signups", 0)),
        "fiverr_orders": int(STORE.metrics.get("fiverr_orders", fiverr.get("orders", 0))),
        "fiverr_impressions": int(fiverr.get("impressions", 0)),
    }


# --- voice report (Urdu text + Hindi/Devanagari for TTS) -------------------

@router.get("/voice-report", tags=["system"])
def voice_report() -> dict:
    """Returns the briefing in Urdu (for display) and Hindi/Devanagari (for the
    browser TTS engine, since Urdu voices are rarely installed but Hindi ones
    pronounce the same words correctly)."""
    c = _empire_context()

    if c["mrr"] == 0:
        earn_ur = "ابھی تک کوئی آمدنی شروع نہیں ہوئی، لیکن ایجنٹس پہلا آرڈر لانے پر کام کر رہے ہیں۔"
        earn_hi = "अभी तक कोई आमदनी शुरू नहीं हुई, लेकिन एजेंट्स पहला ऑर्डर लाने पर काम कर रहे हैं।"
    else:
        earn_ur = f"اب تک آپ نے کل {c['mrr']:.0f} ڈالر کمائے ہیں۔ مبارک ہو عبداللہ!"
        earn_hi = f"अब तक आपने कुल {c['mrr']:.0f} डॉलर कमाए हैं। मुबारक हो अब्दुल्लाह!"

    if c["cm_users"] > 0 or c["cm_active"] > 0:
        cm_ur = f"آپ کے کیئرئیر مائنڈ پر اس وقت {c['cm_users']} یوزرز ہیں، جن میں سے {c['cm_active']} فعال ہیں۔ "
        cm_hi = f"आपके करियर माइंड पर इस वक्त {c['cm_users']} यूज़र्स हैं, जिनमें से {c['cm_active']} फ़आल हैं। "
    else:
        cm_ur = "آپ کے کیئرئیر مائنڈ پر ابھی نئے یوزرز کا انتظار ہے، مارکیٹنگ ایجنٹس اس پر کام کر رہے ہیں۔ "
        cm_hi = "आपके करियर माइंड पर अभी नए यूज़र्स का इंतज़ार है, मार्केटिंग एजेंट्स इस पर काम कर रहे हैं। "

    urdu_text = (
        f"اسلام و علیکم عبداللہ! یہ رہی آپ کی تازہ ترین رپورٹ۔ "
        f"{cm_ur}{earn_ur} "
        f"اس وقت آپ کے {c['active_agents']} ڈیجیٹل ملازمین کام کر رہے ہیں، کل {c['total_agents']} میں سے۔ "
        f"{c['open_opportunities']} نئے کاروباری مواقع دستیاب ہیں۔ عبداللہ، آگے بڑھتے رہیں!"
    )
    hindi_text = (
        f"अस्सलाम वालेकुम अब्दुल्लाह! ये रही आपकी ताज़ा तरीन रिपोर्ट। "
        f"{cm_hi}{earn_hi} "
        f"इस वक्त आपके {c['active_agents']} डिजिटल मुलाज़िमीन काम कर रहे हैं, कुल {c['total_agents']} में से। "
        f"{c['open_opportunities']} नए कारोबारी मौके मौजूद हैं। अब्दुल्लाह, आगे बढ़ते रहिए!"
    )
    return {"urdu": urdu_text, "hindi": hindi_text, **c}


# --- Ask Titan assistant (voice/text, ~12 languages) -----------------------

# Universal voice: the LLM is natively multilingual; the browser supplies the
# TTS voice per language. Urdu keeps its special trick (### + Devanagari) since
# Urdu voices are rarely installed but Hindi ones read the same words aloud.
ASSISTANT_LANGS = {
    "en": "English",
    "ur": "Urdu (اردو)",
    "hi": "Hindi (हिन्दी)",
    "ar": "Arabic (العربية)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "zh": "Chinese (中文)",
    "ja": "Japanese (日本語)",
    "tr": "Turkish (Türkçe)",
    "pt": "Portuguese (Português)",
    "ru": "Russian (Русский)",
}


class AssistantRequest(BaseModel):
    question: str = Field(..., min_length=1)
    lang: str = Field(default="en", description="en/ur/hi/ar/es/fr/de/zh/ja/tr/pt/ru")


@router.post("/assistant", tags=["system"])
def assistant(req: AssistantRequest) -> dict:
    """Answer Abdullah's question in his chosen language. Returns 'answer'
    (display) and 'spoken' (Devanagari for Urdu so the Hindi voice reads it;
    identical to 'answer' for every other language)."""
    c = _empire_context()
    lang = req.lang if req.lang in ASSISTANT_LANGS else "en"
    is_urdu = lang == "ur"

    context = (
        f"Live empire state — "
        f"Total revenue earned: ${c['mrr']:.0f}. "
        f"Career Mind AI: {c['cm_users']} total users, {c['cm_active']} active, {c['cm_signups']} new signups. "
        f"Upwork: {c['fiverr_orders']} orders, {c['fiverr_impressions']} impressions. "
        f"{c['active_agents']} of {c['total_agents']} AI agents active. "
        f"{c['open_opportunities']} open opportunities. Empire health {c['health']:.0f}%."
    )

    if is_urdu:
        # The old prompt said "write the SAME reply in Hindi (Devanagari)",
        # which asked the model to TRANSLATE into Hindi. It obliged: Hindi
        # vocabulary and Hindi register, which a Hindi voice then read as
        # Hindi. Urdu speakers heard Hindi because it WAS Hindi.
        #
        # What is actually wanted is a transliteration: the same Urdu
        # sentence, letter for letter, written in Devanagari purely so a
        # Hindi TTS voice pronounces it. Urdu and Hindi share phonetics; they
        # do not share vocabulary at this register.
        instructions = (
            "Reply in Urdu using Arabic script. Then output a line containing "
            "exactly '###'. After it, TRANSLITERATE that same Urdu sentence "
            "into Devanagari script — keep the Urdu words exactly as they are "
            "and only change the script, so an Urdu speaker hears Urdu. "
            "Do NOT translate into Hindi and do NOT substitute Hindi "
            "vocabulary. The '###' line is mandatory."
        )
    else:
        instructions = f"Answer ONLY in {ASSISTANT_LANGS[lang]}."

    raw = llm.complete(
        system=(
            "You are Titan, the AI chief-of-staff for Abdullah's autonomous business "
            "empire (Career Mind AI student platform + Upwork AI gigs). "
            f"Always address the founder simply as 'Abdullah'. {instructions} "
            "Be concise (2-4 sentences), concrete, and motivating. Use the live data below "
            "when relevant.\n\n" + context
        ),
        prompt=req.question,
        max_tokens=600,
    )

    answer = raw or ""
    spoken = raw or ""
    if raw and is_urdu:
        if "###" in raw:
            parts = raw.split("###", 1)
            answer = parts[0].strip()
            spoken = parts[1].strip()
        else:
            # The model dropped the separator — common, and it used to mean
            # the Devanagari half was shown to the reader. An Urdu speaker
            # then sees Hindi script, which is the single most visible way
            # this feature was broken.
            answer, spoken = _split_urdu_scripts(raw)
        # Belt and braces: whatever happened above, the DISPLAYED answer must
        # never contain Devanagari, and the SPOKEN line must never be empty.
        answer = _strip_devanagari(answer) or _strip_devanagari(raw)
        spoken = spoken.strip() or answer

    if not raw:
        if is_urdu:
            answer = (
                f"عبداللہ، اس وقت آپ نے کل {c['mrr']:.0f} ڈالر کمائے ہیں اور "
                f"{c['active_agents']} ایجنٹس کام کر رہے ہیں۔"
            )
            spoken = (
                f"अब्दुल्लाह, इस वक्त आपने कुल {c['mrr']:.0f} डॉलर कमाए हैं और "
                f"{c['active_agents']} एजेंट्स काम कर रहे हैं।"
            )
        else:
            answer = (
                f"Abdullah, you've earned ${c['mrr']:.0f} so far and "
                f"{c['active_agents']} agents are working. Set GROQ_API_KEY in your Space "
                f"secrets to unlock full conversational AI answers (free, no card)."
            )
            spoken = answer

    STORE.emit("titan-assistant", "command", f'Abdullah asked: "{req.question[:80]}"', "info")
    return {"answer": answer, "spoken": spoken, "lang": lang}


# --- Urdu script handling -------------------------------------------------
# Urdu is written in Arabic script; Hindi in Devanagari. They share phonetics,
# which is why a Hindi TTS voice can read transliterated Urdu convincingly —
# and also why the two kept getting mixed up here, with Devanagari reaching
# the screen. These keep the two apart explicitly instead of trusting the
# model to emit a separator.

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text or ""))


def has_arabic_script(text: str) -> bool:
    return bool(_ARABIC.search(text or ""))


def _strip_devanagari(text: str) -> str:
    """Drop any line containing Devanagari. Line-wise rather than
    character-wise: removing individual glyphs would leave shredded words."""
    kept = [ln for ln in (text or "").splitlines() if not has_devanagari(ln)]
    return "\n".join(kept).strip()


def _split_urdu_scripts(raw: str) -> tuple[str, str]:
    """Separate an Urdu reply from its Devanagari transliteration by script,
    for when the model forgets the '###' separator.

    Returns (displayed_urdu, spoken_devanagari). If there is no Devanagari at
    all the Urdu is used for both — a Hindi voice reading Arabic script is
    poor, but silence would be worse and inventing a transliteration here
    would be guessing at pronunciation.
    """
    urdu_lines, deva_lines = [], []
    for ln in (raw or "").splitlines():
        if has_devanagari(ln):
            deva_lines.append(ln)
        elif ln.strip():
            urdu_lines.append(ln)
    urdu = "\n".join(urdu_lines).strip()
    deva = "\n".join(deva_lines).strip()
    return (urdu or raw.strip()), (deva or urdu or raw.strip())


# --- intelligence status --------------------------------------------------

@router.get("/intelligence", tags=["system"])
def intelligence_status() -> dict:
    p = llm.provider()
    return {
        "claude_connected": p == "claude",
        "model": llm.active_model(),
        "mode": p if p != "free" else "free",
        "provider": p,
    }


# --- self-evolution -------------------------------------------------------

@router.get("/tools", tags=["system"])
def tools_registry() -> dict:
    """Every external capability, its licence, and whether it can actually run.

    Spec Part 2 Layer 4 + Part 8. The point of this endpoint is that the answer
    to "can Titan crawl / call / message yet?" is a fact on a screen rather than
    a guess: `not_configured` names the missing variable, `licence_blocked`
    cannot be fixed by writing code.
    """
    from ..core import tools as tool_layer
    return tool_layer.registry_report()


@router.post("/tools/{name}/invoke", tags=["system"])
def tools_invoke(name: str, payload: dict | None = None) -> dict:
    """Run one tool through the common interface. Never raises."""
    from ..core import tools as tool_layer
    tool = tool_layer.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No such tool: {name}")
    return tool.invoke(**(payload or {})).as_dict()


@router.get("/economics", tags=["system"])
def ai_economics() -> dict:
    """Cost and reliability per task and per provider, from counted calls.

    Every cost here is ESTIMATED — no provider returns token usage through
    `llm.complete()`, so actual spend is reported as null rather than as an
    estimate wearing a different label.
    """
    from ..core import model_router
    return model_router.economics()


@router.get("/approvals", tags=["system"])
def approvals_pending() -> dict:
    """Everything waiting on a human, across every surface.

    Read-only by design. Approving happens on each item's own endpoint, which
    enforces rules this list does not know — a site fix whose page changed
    since it was proposed is refused there, and an improvement that measured
    worse is refused there. A central approve-all would delete those checks.
    """
    from ..core import approvals
    return approvals.pending(STORE)


# --- self-improvement -----------------------------------------------------
# Abdullah IS the approval step, so these have to exist for the loop to close.
# Everything here is founder-only: `approve` changes how a live product
# behaves, and there is no version of that a demo visitor should reach.

class ProposalRequest(BaseModel):
    param: str
    value: float
    reason: str
    evidence: dict | None = None


class ApprovalRequest(BaseModel):
    # Not optional and not defaulted. An approval without a name is not an
    # audit trail, and a default like "founder" would be a name nobody typed.
    approver: str
    why: str = ""


def _improve_call(fn, *args, **kwargs) -> dict:
    """ValueError from the engine is a 400 with its own message.

    Those messages are the product — "this measured WORSE", "Titan does not
    deploy its own changes" — so they are surfaced rather than flattened into
    a generic error.
    """
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/improve", tags=["system"])
def improve_report() -> dict:
    from ..core import improve
    return improve.report()


@router.get("/improve/params", tags=["system"])
def improve_params() -> dict:
    """What Titan may change about itself, and the evidence for each default."""
    from ..core import params
    return params.status()


@router.get("/improve/observe", tags=["system"])
def improve_observe() -> dict:
    from ..core import improve
    return improve.observe()


@router.post("/improve/propose", tags=["system"])
def improve_propose(req: ProposalRequest) -> dict:
    from ..core import improve
    return _improve_call(improve.propose, req.param, req.value,
                         reason=req.reason, evidence=req.evidence)


@router.post("/improve/{proposal_id}/evaluate", tags=["system"])
def improve_evaluate(proposal_id: str) -> dict:
    """Run the benchmark. Changes nothing that is running."""
    from ..core import improve
    return _improve_call(improve.evaluate, proposal_id)


@router.post("/improve/{proposal_id}/approve", tags=["system"])
def improve_approve(proposal_id: str, req: ApprovalRequest) -> dict:
    from ..core import improve
    return _improve_call(improve.approve, proposal_id, req.approver)


@router.post("/improve/{proposal_id}/reject", tags=["system"])
def improve_reject(proposal_id: str, req: ApprovalRequest) -> dict:
    from ..core import improve
    return _improve_call(improve.reject, proposal_id, req.approver, req.why)


@router.post("/improve/{proposal_id}/activate", tags=["system"])
def improve_activate(proposal_id: str) -> dict:
    """Apply an already-APPROVED proposal. Refuses anything else."""
    from ..core import improve
    return _improve_call(improve.activate, proposal_id)


@router.post("/improve/{proposal_id}/rollback", tags=["system"])
def improve_rollback(proposal_id: str, req: ApprovalRequest) -> dict:
    from ..core import improve
    return _improve_call(improve.rollback, proposal_id,
                         why=req.why or f"Rolled back by {req.approver}.")


class PlanRequest(BaseModel):
    goal: str = Field(..., min_length=1)


@router.post("/plan", tags=["executive"])
def make_plan(req: PlanRequest) -> dict:
    """State what would be done, and what it would cost, before doing it.

    Spec Part 2. This deliberately does NOT execute — /api/agent/act does that.
    Separating them is the point: a plan can be read, priced and refused first,
    and a plan with a blocked step says so instead of failing halfway through.
    """
    from ..core import planner
    return planner.plan(req.goal).as_dict()


# --- subscriptions and signup (spec Part 5B) --------------------------------

class SignupIn(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=8)
    plan: str = Field(default="free")


class OnboardIn(BaseModel):
    business_name: str = Field(..., min_length=1)
    website: str = Field(default="")
    industry: str = Field(default="")
    instagram: str = Field(default="")
    city: str = Field(default="")
    country: str = Field(default="")
    run_audit: bool = Field(default=True)


@router.post("/account/onboard", tags=["billing"])
def account_onboard(req: OnboardIn, request: Request,
                    x_account_token: Optional[str] = Header(None)) -> dict:
    """A subscriber adds their business and gets their first audit immediately.

    This is the conversion path. Everything before it is a promise; this is the
    first moment the product does something for the person who signed up, and
    the audit is what makes the value obvious rather than described.

    The plan's business limit is enforced here, and a refusal names the limit
    and the tier that lifts it rather than failing blankly.
    """
    from ..core import analytics, billing, evidence
    from ..engines import client_seo as _cs

    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")

    # Onboarding fetches a URL the caller supplies. Unmetered, that makes Titan
    # a request amplifier aimed at somebody else's server. Keyed on the
    # account, since the caller is authenticated here.
    from ..core import ratelimit
    limited = ratelimit.check("onboard", email)
    if not limited["allowed"]:
        raise HTTPException(status_code=429, detail=limited)

    verdict = billing.can_add_client(email)
    if not verdict["allowed"]:
        # 402 rather than 403: this is not forbidden, it is a plan ceiling.
        raise HTTPException(status_code=402, detail=verdict)

    # A subscriber's own business gets no separate portal login — they already
    # authenticate as the account holder. A random credential is stored so the
    # shared client record shape stays valid without creating a usable second
    # login nobody was told about.
    import secrets as _secrets
    try:
        rec = clients.create_client(
            business_name=req.business_name.strip(),
            username=f"acct-{_secrets.token_hex(6)}",
            password=_secrets.token_urlsafe(24),
            website=req.website.strip(),
            instagram=req.instagram.strip(),
            industry=req.industry.strip(),
            city=req.city.strip(),
            country=req.country.strip() or "Pakistan",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    billing.attach_client(email, rec["id"])
    analytics.record(email, analytics.ADDED_BUSINESS,
                     business=rec["business_name"],
                     industry=rec.get("industry", ""),
                     country=rec.get("country", ""))

    audit = None
    if req.run_audit and req.website.strip():
        quota = billing.consume(email, "audits")
        if not quota["allowed"]:
            audit = {"skipped": True, **quota}
        else:
            audit = _cs.audit(rec["website"],
                              business_name=rec["business_name"],
                              city=rec.get("city", ""),
                              country=rec.get("country", ""),
                              industry=rec.get("industry", ""))
            clients.bump(rec["id"], "seo_audits")
            analytics.record(email, analytics.RAN_AUDIT,
                             website=rec["website"], ok=bool(audit.get("ok")),
                             findings=len(audit.get("findings", [])))
            if audit.get("ok"):
                clients.bump(rec["id"], "issues_found",
                             len(audit.get("findings", [])))
                clients.update_raw(rec["id"], last_audit=audit)
                # The crawl already happened — file what it observed.
                try:
                    page, _e, _s = _cs._fetch(rec["website"])
                    if page:
                        evidence.observe_from_page(rec["id"], page)
                        # ...and keep the readable text, so the voice agent can
                        # answer questions about this business from its own
                        # site instead of guessing. The fetch is already paid
                        # for; throwing the text away was the waste.
                        from ..core import knowledge
                        knowledge.ingest(rec["id"], page, rec["website"])
                except Exception:
                    pass

    persistence.save(STORE)
    return {
        "client": clients.public(rec["id"]),
        "audit": audit,
        "account": billing.public(email),
        "next": ("Download the PDF report, or open the SEO view to work "
                 "through the findings."),
        "report_url": f"/api/account/clients/{rec['id']}/report.pdf",
    }


class SiteConnectIn(BaseModel):
    provider: str = Field(default="wordpress")
    site_url: str = Field(..., min_length=8)
    username: str = Field(..., min_length=1)
    application_password: str = Field(..., min_length=8)


@router.get("/account/site/guide", tags=["billing"])
def site_setup_guide(provider: str = Query(default="wordpress")) -> dict:
    """How a non-technical owner produces the credential Titan needs.

    Public: someone deciding whether to sign up should be able to see exactly
    what will be asked of them before they hand over anything.
    """
    from ..core import site_access
    return site_access.setup_guide(provider)


@router.post("/account/clients/{cid}/site", tags=["billing"])
def connect_site(cid: str, req: SiteConnectIn,
                 x_account_token: Optional[str] = Header(None)) -> dict:
    """Give Titan write access to a business's own website.

    The credential is verified against the live site before anything is
    stored, encrypted at rest, and never returned by any endpoint. Ownership
    is checked first — a token for one subscriber must never connect another
    subscriber's site.
    """
    from ..core import site_access
    _owned(cid, x_account_token)

    out = site_access.connect(cid, req.provider, req.site_url, req.username,
                              req.application_password)
    if not out["ok"]:
        raise HTTPException(status_code=400, detail=out["error"])
    persistence.save(STORE)
    return out


@router.get("/account/clients/{cid}/site", tags=["billing"])
def site_status(cid: str, x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_access
    _owned(cid, x_account_token)
    return site_access.status(cid)


@router.delete("/account/clients/{cid}/site", tags=["billing"])
def disconnect_site(cid: str,
                    x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_access
    _owned(cid, x_account_token)
    out = site_access.disconnect(cid)
    persistence.save(STORE)
    return out


# ---------------------------------------------------------------- site fixes --
# Titan changing a page on somebody else's live website. Every endpoint here
# checks TWO things: that the caller owns the business, and that the fix
# belongs to that business. Checking only the first would let a valid
# subscriber apply a fix belonging to another subscriber's site by guessing an
# id, which is a worse leak than any read endpoint in this file.

class ApproveIn(BaseModel):
    approver: str = Field(..., min_length=1,
                          description="Who is approving. Recorded on the fix.")
    reason: str = Field(default="")


def _owned(cid: str, token: Optional[str]) -> str:
    """The single ownership gate. See core/tenancy.py for why it lives there.

    Also binds the tenant to the logging context, so every log line for the
    rest of the request carries it and a cross-tenant incident is
    reconstructable.
    """
    from ..core import tenancy
    try:
        return tenancy.require_owner(cid, token or "")
    except tenancy.NotOwned:
        # The SAME 404 as "no such client" — two different answers would tell
        # a prober which client ids exist.
        raise HTTPException(status_code=404, detail="Not found")


def _owned_fix(cid: str, fix_id: str, token: Optional[str]) -> dict:
    from ..core import site_fix
    _owned(cid, token)
    fix = site_fix.get(fix_id)
    # Same 404 for "no such fix" and "not yours" — distinguishing them tells a
    # prober which ids exist.
    if not fix or fix["client_id"] != cid:
        raise HTTPException(status_code=404, detail="Not found")
    return fix


@router.post("/account/clients/{cid}/fixes/propose", tags=["billing"])
def propose_fixes(cid: str,
                  x_account_token: Optional[str] = Header(None)) -> dict:
    """Turn the latest audit's findings into concrete, appliable changes.

    Nothing is changed on the site by this call. It reads the connected
    WordPress site to find the real page behind the audited URL and records
    what it would write — plus, explicitly, every finding it cannot fix and
    why.
    """
    from ..core import site_fix
    _owned(cid, x_account_token)
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    audit = rec.get("last_audit") or {}
    if not audit:
        raise HTTPException(status_code=400, detail=(
            "This business has not been audited yet, so there are no findings "
            "to turn into fixes. Run the audit first."))
    out = site_fix.propose(cid, audit, business=rec)
    if not out["ok"]:
        raise HTTPException(status_code=400, detail=out["error"])
    persistence.save(STORE)
    return out


@router.get("/account/clients/{cid}/fixes", tags=["billing"])
def list_fixes(cid: str, status: str = Query(default=""),
               x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_fix
    _owned(cid, x_account_token)
    return {"fixes": site_fix.for_client(cid, status),
            "summary": site_fix.summary(cid)}


@router.get("/account/clients/{cid}/fixes/{fix_id}", tags=["billing"])
def fix_detail(cid: str, fix_id: str,
               x_account_token: Optional[str] = Header(None)) -> dict:
    """The full before/after text, so a human can read what they are approving."""
    return _owned_fix(cid, fix_id, x_account_token)


@router.post("/account/clients/{cid}/fixes/{fix_id}/approve", tags=["billing"])
def approve_fix(cid: str, fix_id: str, req: ApproveIn,
                x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_fix
    _owned_fix(cid, fix_id, x_account_token)
    out = site_fix.approve(fix_id, req.approver)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out["error"])
    persistence.save(STORE)
    return out


@router.post("/account/clients/{cid}/fixes/{fix_id}/reject", tags=["billing"])
def reject_fix(cid: str, fix_id: str, req: ApproveIn,
               x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_fix
    _owned_fix(cid, fix_id, x_account_token)
    out = site_fix.reject(fix_id, req.approver, req.reason)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out["error"])
    persistence.save(STORE)
    return out


@router.post("/account/clients/{cid}/fixes/{fix_id}/apply", tags=["billing"])
def apply_fix(cid: str, fix_id: str,
              x_account_token: Optional[str] = Header(None)) -> dict:
    """Write the approved change to the live site, then read it back.

    A 409 here means the change did NOT go live — either the page moved on
    since it was proposed, or the site accepted the write and discarded it.
    The body carries what the site actually says now.
    """
    from ..core import site_fix
    _owned_fix(cid, fix_id, x_account_token)
    out = site_fix.apply(fix_id)
    persistence.save(STORE)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out["error"])
    return out


@router.post("/account/clients/{cid}/fixes/{fix_id}/rollback", tags=["billing"])
def rollback_fix(cid: str, fix_id: str,
                 x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import site_fix
    _owned_fix(cid, fix_id, x_account_token)
    out = site_fix.rollback(fix_id)
    persistence.save(STORE)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out["error"])
    return out


@router.get("/account/clients", tags=["billing"])
def account_clients(x_account_token: Optional[str] = Header(None)) -> dict:
    """The businesses THIS subscriber owns. Never anyone else's."""
    from ..core import billing
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    rows = [clients.public(cid) for cid in billing.owned_clients(email)]
    return {"clients": [r for r in rows if r],
            "limit": billing.can_add_client(email)}


@router.get("/account/clients/{cid}/report.pdf", tags=["billing"])
def account_report(cid: str, x_account_token: Optional[str] = Header(None)):
    """The PDF a subscriber can hand to their own client.

    Ownership is checked against the account's own list — a valid token for one
    subscriber must never fetch another subscriber's report.
    """
    email = _owned(cid, x_account_token)
    from ..core import analytics
    analytics.record(email, analytics.DOWNLOADED_REPORT, client_id=cid)
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    seo = client_seo.audit(rec.get("website", ""),
                           business_name=rec.get("business_name", ""),
                           city=rec.get("city", ""),
                           country=rec.get("country", ""),
                           industry=rec.get("industry", ""))
    pdf = client_report.build(clients.public(cid), seo, social=_social_pack(rec))
    fname = (rec.get("business_name", "report").lower()
             .replace(" ", "-")[:40] + "-report.pdf")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/self-seo", tags=["billing"])
def self_seo_report() -> dict:
    """Titan's own audit score, from the engine it sells.

    Deliberately PUBLIC. It is the strongest trust signal available and it
    costs nothing: anyone can claim their SEO tool is good, but a score
    produced by the same code the customer is buying can be checked by the
    reader in seconds. Published as measured — if Titan's own site regresses,
    this number falls in public.
    """
    from ..engines import self_seo
    return self_seo.report()


@router.get("/structured-data", tags=["billing"])
def structured_data() -> dict:
    """JSON-LD for the product, offers generated from the real plan table so a
    marked-up price can never drift from the price actually charged."""
    from ..engines import self_seo
    return self_seo.structured_data()


@router.get("/plans", tags=["billing"])
def list_plans() -> dict:
    """Public pricing. Free is a usable product, not a demo."""
    from ..core import billing
    return billing.plans()


@router.post("/signup", tags=["billing"])
def signup(req: SignupIn, request: Request) -> dict:
    from ..core import analytics, billing, ratelimit
    verdict = ratelimit.check("signup", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        # 429 with the reason and a retry time, not a bare refusal — the same
        # rule the plan quotas follow.
        raise HTTPException(status_code=429, detail=verdict)
    try:
        account = billing.signup(req.email, req.password, req.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    analytics.record(req.email, analytics.SIGNED_UP, plan=req.plan)
    persistence.save(STORE)
    return account


@router.post("/account/login", tags=["billing"])
def account_login(req: SignupIn, request: Request) -> dict:
    from ..core import billing, ratelimit
    # Slows credential stuffing. Keyed on the caller, not the email, so an
    # attacker cannot lock a real customer out of their own account.
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    token = billing.authenticate(req.email, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    # Coming back after signup is the difference between interest and use. It
    # has no durable trace anywhere else, so it is recorded here or not at all.
    from ..core import analytics
    analytics.record(req.email, analytics.SIGNED_IN)
    return {"token": token, "account": billing.public(req.email)}


@router.get("/account", tags=["billing"])
def account_me(x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import billing
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return billing.public(email)


@router.post("/checkout/{plan_key}", tags=["billing"])
def checkout(plan_key: str,
             x_account_token: Optional[str] = Header(None)) -> dict:
    """Where the CUSTOMER goes to approve a subscription.

    Titan never handles a card number and never completes a payment on anyone's
    behalf — this returns an approval target the customer opens themselves.
    """
    from ..core import billing
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    from ..core import analytics
    analytics.record(email, analytics.OPENED_CHECKOUT, plan=plan_key)
    try:
        return billing.checkout(email, plan_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- founder analytics ------------------------------------------------------
# Founder-only by construction: `/api/founder` is registered in
# demo_data._SENSITIVE_PREFIXES, so a guest token is refused outright by the
# middleware rather than served a sample. Subscriber tokens never reach here —
# they authenticate with X-Account-Token, which this route does not accept.

@router.get("/founder/analytics", tags=["executive"])
def founder_analytics(days: int = Query(default=30, ge=1, le=365),
                      recent: int = Query(default=40, ge=1, le=200)) -> dict:
    """Who signed up, what they are on, and what they actually did with it."""
    from ..core import analytics
    return analytics.report(days=days, recent=recent)


@router.get("/founder/accounts", tags=["executive"])
def founder_list_accounts() -> dict:
    """Every customer, with the plan and status the founder acts on.

    `POST /api/founder/accounts` has worked for a long time with nothing to
    show what it created — the first Enterprise seat on this platform was
    granted from a browser console. This is the read side.

    It serves the SAME rows as the funnel (`analytics.accounts_snapshot`)
    rather than re-deriving them, so the customers screen and the funnel cannot
    disagree about what plan somebody is on.

    Founder-only by construction: `/api/founder` is registered in
    `demo_data._SENSITIVE_PREFIXES`, so a demo visitor is refused outright
    rather than served a sample. Every row is a real person's email address.
    """
    from ..core import analytics, billing

    snap = analytics.accounts_snapshot()
    return {
        "accounts": snap["accounts"],
        "counts": {
            "total": len(snap["accounts"]),
            "paying": snap["paying"],
            "granted_paid_plans": snap["granted_paid_plans"],
            "by_plan": snap["by_plan"],
            "by_status": snap["by_status"],
        },
        # Read from the catalogue billing actually enforces, so the form cannot
        # offer a plan the POST would refuse.
        "plans": [{"key": k, "name": billing.PLANS[k].name,
                   "price_usd": billing.PLANS[k].price_usd}
                  for k in billing.ORDER],
        "processor": billing.processor_name(),
        "billable": billing.configured(),
        # These accounts are only as durable as the state file. Saying so on the
        # screen that creates them is the difference between a customer list and
        # a customer list that quietly disappears on the next rebuild.
        "storage_warning": analytics.storage_warning(),
    }


class GrantIn(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(default="", min_length=0)
    plan: str = Field(default="enterprise")
    note: str = Field(default="")


@router.post("/founder/accounts", tags=["executive"])
def founder_create_account(req: GrantIn) -> dict:
    """Create a subscriber and put them on any plan, bypassing payment.

    This is how a free Enterprise seat is given to a pilot customer, a friend
    or a case study — the thing that gets a product its first real users while
    checkout is still unfinished.

    Founder-only by construction: /api/founder is registered sensitive, so a
    guest is refused outright and a subscriber's own X-Account-Token is not
    accepted here at all.
    """
    from ..core import analytics, billing

    if req.plan not in billing.PLANS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown plan. One of {list(billing.PLANS)}.")

    # A generated password is stronger than one typed in a hurry, and it means
    # a seat can be granted without inventing a credential for someone else.
    import secrets as _secrets
    password = req.password or _secrets.token_urlsafe(12)
    if len(password) < 8:
        raise HTTPException(status_code=400,
                            detail="Password must be at least 8 characters.")

    created = True
    try:
        billing.signup(req.email, password, "free")
        analytics.record(req.email, analytics.SIGNED_UP, plan=req.plan,
                         granted=True)
    except ValueError as e:
        if "already exists" not in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        created = False       # existing account: change their plan instead

    account = billing.set_plan(req.email, req.plan,
                               subscription_id=f"granted:{req.note[:60]}"
                               if req.note else "granted",
                               status="active")
    analytics.record(req.email, analytics.CHANGED_PLAN, plan=req.plan,
                     granted=True)
    persistence.save(STORE)
    return {
        "account": account,
        "created": created,
        # Shown ONCE. It is stored only as a PBKDF2 hash, so nobody — not even
        # Abdullah — can read it back later.
        "password": password if created else None,
        "note": ("Give this password to the user now; it is stored only as a "
                 "hash and cannot be shown again. They sign in at /join."
                 if created else
                 "Account already existed — the plan was changed and the "
                 "existing password is unchanged."),
        "billed": False,
        "warning": ("This grant bypasses payment entirely. It counts as a "
                    "paying account in the funnel only if the plan is paid "
                    "AND active, so a pile of free grants will make MRR look "
                    "real when nothing was charged. The subscription id "
                    "records it as granted."),
    }


@router.post("/founder/accounts/{email}/plan", tags=["executive"])
def founder_set_plan(email: str, req: GrantIn) -> dict:
    """Move an existing subscriber to another plan."""
    from ..core import analytics, billing
    if req.plan not in billing.PLANS:
        raise HTTPException(status_code=400, detail="Unknown plan.")
    try:
        account = billing.set_plan(email, req.plan, status="active")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    analytics.record(email, analytics.CHANGED_PLAN, plan=req.plan, granted=True)
    persistence.save(STORE)
    return {"account": account, "billed": False}


@router.get("/founder/demo-workspace", tags=["executive"])
def founder_demo_workspace() -> dict:
    """What the 24/7 engines are practising on, and when they last ran."""
    from ..engines import demo_workspace
    return demo_workspace.status()


@router.post("/founder/demo-workspace/run", tags=["executive"])
def founder_demo_workspace_run() -> dict:
    """Force a cycle now instead of waiting for the interval."""
    from ..engines import demo_workspace
    return demo_workspace.cycle(force=True) or {"skipped": True,
                                                "reason": "Demo workspace is disabled."}


@router.get("/apis", tags=["system"])
def api_catalogue(q: str = Query(default=""),
                  category: str = Query(default=""),
                  auth: str = Query(default=""),
                  no_credential: bool = Query(default=False),
                  https_only: bool = Query(default=False),
                  limit: int = Query(default=25, ge=1, le=100)) -> dict:
    """Search the external-API catalogue. Metadata only — no calls are made.

    Public by design: it is a directory of publicly listed APIs and contains
    no customer data. Paginated because the catalogue is 1,675 entries and
    shipping all of them to a phone would be the performance bug the brief
    warns about.
    """
    from ..core import api_registry
    return api_registry.search(q, category=category, auth=auth,
                               no_credential=no_credential,
                               https_only=https_only, limit=limit)


@router.get("/apis/stats", tags=["system"])
def api_catalogue_stats() -> dict:
    """The integration audit: how many are catalogued vs actually integrated."""
    from ..core import api_registry
    return {"stats": api_registry.stats(),
            "categories": api_registry.categories()}


@router.get("/apis/integrated", tags=["system"])
def api_integrated() -> dict:
    """What Titan can genuinely CALL, versus what it has merely catalogued.

    The dashboard reads this to show the honest number. It is 4 capabilities
    against 3 providers, beside 1,675 catalogued entries with 0 adapters.
    """
    from ..core import api_adapters, api_registry
    return {"integrated": api_adapters.integrated(),
            "catalogued": api_registry.stats()["total"],
            "adapters_written": api_registry.stats()["adapters_written"]}


@router.get("/apis/live/rates", tags=["system"])
def api_live_rates(base: str = Query(default="USD"),
                   symbols: str = Query(default="PKR,EUR,GBP")) -> dict:
    """Live exchange rates through the hardened runtime, with fallback."""
    from ..core import api_adapters
    wanted = [s.strip() for s in symbols.split(",") if s.strip()][:12]
    return api_adapters.exchange_rates(base, wanted)


@router.get("/apis/live/weather", tags=["system"])
def api_live_weather(place: str = Query(..., min_length=2)) -> dict:
    """Geocode a place name then fetch its weather — two providers, one call."""
    from ..core import api_adapters
    return api_adapters.weather_for_place(place)


@router.get("/apis/capability", tags=["system"])
def api_capability(intent: str = Query(..., min_length=2),
                   limit: int = Query(default=5, ge=1, le=25)) -> dict:
    """Map an intent ("current exchange rate") onto candidate providers.

    Returns candidates ranked by catalogue facts — credential needed, HTTPS,
    CORS — not by a quality score nobody measured. Candidates are not
    connections; see the note on the response.
    """
    from ..core import api_registry
    return api_registry.for_capability(intent, limit=limit)


@router.get("/founder/models", tags=["executive"])
def founder_models(free_only: bool = Query(default=False),
                   vision: bool = Query(default=False),
                   min_context: int = Query(default=0, ge=0),
                   limit: int = Query(default=40, ge=1, le=200)) -> dict:
    """Model capability and per-token price, from OpenRouter's live catalogue.

    This is what makes a cost figure possible at all: measured token counts
    times a published price. Cost stays null wherever tokens were not counted.
    """
    from ..core import model_catalog
    model_catalog.refresh()
    rows = (model_catalog.free_models(min_context=min_context, vision=vision)
            if free_only else
            model_catalog.candidates(needs_vision=vision,
                                     min_context=min_context))
    return {"status": model_catalog.status(), "models": rows[:limit]}


@router.post("/founder/models/refresh", tags=["executive"])
def founder_models_refresh() -> dict:
    from ..core import model_catalog
    return model_catalog.refresh(force=True)


@router.get("/founder/logs", tags=["executive"])
def founder_logs(limit: int = Query(default=100, ge=1, le=300),
                 level: str = Query(default=""),
                 event: str = Query(default="")) -> dict:
    """Recent structured log lines, for when no log shipper is attached.

    Under /api/founder because log lines carry paths, statuses and tenant ids.
    Credentials and emails are redacted before a line is ever written — see
    core/obs.py.
    """
    from ..core import obs
    return {"stats": obs.stats(),
            "lines": obs.recent(limit=limit, level=level, event=event)}


@router.get("/founder/backups", tags=["executive"])
def founder_backups() -> dict:
    """What backup protection actually exists, and whether it was verified."""
    from ..core import backup
    return {"status": backup.status(), "backups": backup.listing()}


@router.post("/founder/backups", tags=["executive"])
def founder_backup_create(note: str = Query(default="")) -> dict:
    """Take a snapshot now. It is verified by restoring it before it counts."""
    from ..core import backup
    out = backup.create(note=note)
    if not out["ok"]:
        raise HTTPException(status_code=500, detail=out["error"])
    return out


@router.post("/founder/backups/verify", tags=["executive"])
def founder_backup_verify(file: str = Query(...)) -> dict:
    """Open a backup and prove it is a working database with rows in it."""
    from ..core import backup
    return backup.verify(file)


@router.get("/founder/rendering", tags=["executive"])
def founder_rendering() -> dict:
    """Whether Titan can see JavaScript-built pages, stated plainly.

    A large share of small-business sites are client-rendered. Without a
    browser renderer Titan detects them and says its findings are unreliable
    rather than publishing a confident score on an empty shell.
    """
    from ..core import render
    return render.status()


@router.get("/founder/fix-cycle", tags=["executive"])
def founder_fix_cycle() -> dict:
    """What the 24/7 fix loop is responsible for, and what it has actually done.

    Under /api/founder because it names the client ids Titan holds keys to.
    """
    from ..engines import fix_cycle
    return fix_cycle.status()


@router.post("/founder/fix-cycle/run", tags=["executive"])
def founder_fix_cycle_run() -> dict:
    """Enqueue a re-audit of every connected site now.

    This enqueues; it does not apply. Nothing in the cycle can change a
    customer's site without a named human approval.
    """
    from ..engines import fix_cycle
    return fix_cycle.cycle(force=True) or {"skipped": True,
                                           "reason": "The cycle errored."}


@router.get("/founder/queue", tags=["executive"])
def founder_queue(limit: int = Query(default=50, ge=1, le=200),
                  kind: str = Query(default=""),
                  status: str = Query(default="")) -> dict:
    """The durable work queue — what is pending, what ran, and how long it took."""
    from ..core import queue
    return {"stats": queue.stats(),
            "jobs": queue.recent(limit=limit, kind=kind, status=status)}


@router.post("/founder/queue/drain", tags=["executive"])
def founder_queue_drain(limit: int = Query(default=5, ge=1, le=50)) -> dict:
    """Run pending jobs now instead of waiting for the heartbeat."""
    from ..core import queue
    return queue.drain(limit=limit, worker="founder")


@router.get("/founder/traffic", tags=["executive"])
def founder_traffic(days: int = Query(default=30, ge=1, le=90)) -> dict:
    """How many people opened the site, measured in-process — no analytics
    vendor, no cookie, no consent banner, and no IP address stored."""
    from ..core import traffic
    return traffic.report(days=days)


@router.get("/founder/seo-overview", tags=["executive"])
def founder_seo_overview() -> dict:
    """Titan's own SEO score beside every client site it manages.

    Abdullah asked to see these together, and they belong together: Titan
    audits itself with the same engine it sells, so its own score is the one
    number a prospect can check. A client scoring above the platform selling
    them SEO is a thing he needs to find out from this screen, not from them.
    """
    from ..engines import self_seo

    own = self_seo.report()
    from .. engines import demo_workspace as _demo

    rows = []
    for rec in clients.all_clients():
        cid = rec.get("id", "")
        audit = rec.get("last_audit") or {}
        is_demo = _demo.is_demo_client(rec)
        rows.append({
            "id": cid,
            "business_name": rec.get("business_name", ""),
            "website": rec.get("website", ""),
            "country": rec.get("country", ""),
            "industry": rec.get("industry", ""),
            # None, never 0 — a site that has not been audited has no score,
            # and a 0 next to a real 58 reads as "audited, and terrible".
            "score": audit.get("score"),
            "grade": audit.get("grade"),
            "findings": len(audit.get("findings", []) or []),
            "audited": bool(audit),
            "is_demo": is_demo,
        })

    # The client average is a claim about Abdullah's book of business. Demo
    # sites are Titan's own pages and would flatter it.
    scored = [r["score"] for r in rows
              if isinstance(r.get("score"), (int, float)) and not r["is_demo"]]
    rows.sort(key=lambda r: (r["score"] is None, r["score"] or 0))
    import time as _t
    checked_at = own.get("checked_at")
    interval_h = own.get("interval_hours", 6.0)
    return {
        "titan": {
            "checked": own.get("checked", False),
            "url": own.get("url", ""),
            "score": own.get("score"),
            "grade": own.get("grade"),
            "open_findings": own.get("open_findings", []),
            # The full picture, not just the headline. "94/A" without the list
            # of what passed is a number to be trusted rather than checked.
            "passed": own.get("passed", []),
            "failed": own.get("failed", []),
            "counts": own.get("counts", {}),
            "checked_at": checked_at,
            "minutes_ago": (round((_t.time() - checked_at) / 60, 1)
                            if checked_at else None),
            "next_check_in_minutes": (
                max(0, round(interval_h * 60 - (_t.time() - checked_at) / 60, 1))
                if checked_at else None),
            "interval_hours": interval_h,
            # An audit that failed to run is not a passing audit.
            "error": own.get("error"),
            "note": own.get("note", ""),
        },
        "clients": rows,
        "client_average": round(sum(scored) / len(scored), 1) if scored else None,
        "unaudited": sum(1 for r in rows if not r["audited"]),
        "note": ("Client scores come from the last stored audit, not a fresh "
                 "crawl — opening this screen must not fire a request at every "
                 "client's website. Sites never audited show no score rather "
                 "than a zero."),
    }


@router.get("/reflection", tags=["executive"])
def reflection_report(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """What Titan learned from finishing things, and what it changed as a result.

    Spec Part 2. The calibration_factor is the load-bearing number: it is
    applied to every subsequent plan's runtime estimate, which is what makes
    this a feedback loop rather than a log.
    """
    from ..core import reflection
    return reflection.report(limit=limit)


class ReflectIn(BaseModel):
    goal: str = Field(..., min_length=1)
    achieved: bool
    predicted_seconds: float = 0.0
    actual_seconds: float = 0.0
    confidence: float = 0.5
    tool_failures: List[str] = Field(default_factory=list)
    notes: str = ""


@router.post("/reflection", tags=["executive"])
def reflection_record(req: ReflectIn) -> dict:
    from ..core import reflection
    return reflection.record(
        goal=req.goal, achieved=req.achieved,
        predicted_seconds=req.predicted_seconds,
        actual_seconds=req.actual_seconds, confidence=req.confidence,
        tool_failures=req.tool_failures, notes=req.notes)


@router.get("/bi/{period}", tags=["executive"])
def bi_report(period: str) -> dict:
    """Period report built only from what is actually in the ledger.

    Spec Part 4C. Where there is not enough history to project, the forecast
    reports `available: false` with the reason instead of a number — a
    projection invented from two data points is worse than none, because it
    gets planned against.
    """
    from ..engines import bi as bi_engine
    if period not in bi_engine.PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"period must be one of {sorted(bi_engine.PERIODS)}")
    return bi_engine.report(period)


@router.get("/routing", tags=["system"])
def routing_report() -> dict:
    """Measured per-provider performance and the order it produces.

    Spec Part 6. The order shown is the one the next completion will actually
    use, so a provider sitting last is visibly last rather than quietly slow.
    """
    from ..core import llm as llm_mod
    from ..core import routing as routing_mod
    chain = llm_mod.providers_configured()
    return {**routing_mod.report(),
            "configured_chain": chain,
            "effective_order": routing_mod.order(chain)}


@router.get("/events", tags=["system"])
def event_trace(limit: int = Query(default=50, ge=1, le=500),
                event: str = Query(default="")) -> dict:
    """Structured event trace — the machine-readable twin of /api/feed."""
    from ..core import events as bus
    return {"events": bus.trace(limit=limit, event=event), **bus.stats()}


@router.get("/evolution", tags=["system"])
def evolution_status() -> dict:
    w = evolution.weights(STORE)
    return {
        "weights": w,
        "description": {
            "weight_difficulty": "Penalty applied to high-difficulty opportunities",
            "weight_risk": "Penalty applied to high-risk opportunities",
            "weight_time": "Penalty applied to long time-to-value estimates",
        },
        "total_outcomes": sum(
            1 for a in STORE.executions.values()
            if a["status"].value in ("completed", "reverted", "failed")
            and a.get("opportunity_id")
        ),
    }


# ---------------------------------------------------------------- learning ---
# Titan adapting its ranking to what Abdullah actually pursues, rather than
# ranking identically forever. See core/learning.py for the honesty rules.

class LearnIn(BaseModel):
    text: str = Field(..., description="Opportunity title + rationale")
    pursued: bool = Field(..., description="True if he acted on it")


@router.get("/learning", tags=["system"])
def learning_stats() -> dict:
    """What the model has learned, with cross-validated accuracy."""
    return learning.stats()


@router.post("/learning/record", tags=["system"])
def learning_record(payload: LearnIn) -> dict:
    """Log one real decision so the ranking improves."""
    learning.record(payload.text, payload.pursued)
    return {"ok": True, "stats": learning.stats()}


@router.post("/learning/opportunity/{opportunity_id}", tags=["system"])
def learning_from_opportunity(opportunity_id: str, pursued: bool = Query(...)) -> dict:
    """Teach from a stored opportunity by id — what the dashboard calls."""
    opp = STORE.opportunities.get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    learning.record(f"{opp.get('title','')} {opp.get('rationale','')}", pursued)
    return {"ok": True, "stats": learning.stats()}


@router.post("/learning/bootstrap", tags=["system"])
def learning_bootstrap() -> dict:
    """Teach the ranker from the LLM chain so it works without waiting for clicks.

    Judges the currently-known opportunities against Abdullah's real situation
    (solo, no capital, needs revenue in weeks) and learns from those verdicts.
    His own execute/dismiss decisions still override this later.
    """
    items = [
        (f"{o.get('title','')} {o.get('rationale','') or o.get('description','')}",
         float(o.get("formula_score") or o.get("priority_score") or 0.0))
        for o in STORE.opportunities.values()
    ]
    if not items:
        opportunity.discover(STORE)
        items = [
            (f"{o.get('title','')} {o.get('rationale','') or o.get('description','')}",
             float(o.get("formula_score") or o.get("priority_score") or 0.0))
            for o in STORE.opportunities.values()
        ]
    result = learning.teach_from_llm(items)
    # Re-score everything now that the model knows something.
    opportunity.discover(STORE)
    persistence.save(STORE)
    return result


# ============================================================ CLIENT PORTAL ==
# Multi-tenant: each business gets its own login and sees only its own data.
# Isolation fails closed - an unknown token resolves to nothing, never to
# everything.

class ClientCreateIn(BaseModel):
    business_name: str
    username: str
    password: str
    website: str = ""
    instagram: str = ""
    industry: str = ""
    city: str = ""
    country: str = "Pakistan"
    logo_url: str = ""
    brand_voice: str = ""
    trial_days: int = 60
    notes: str = ""


class ClientLoginIn(BaseModel):
    username: str
    password: str


def _client_from_header(x_client_token: Optional[str]) -> str:
    cid = clients.resolve(x_client_token or "")
    if not cid:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return cid


# ---- admin (Abdullah only) -------------------------------------------------
@router.post("/admin/clients", tags=["clients"])
def admin_create_client(payload: ClientCreateIn) -> dict:
    try:
        rec = clients.create_client(**payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persistence.save(STORE)
    return rec


@router.get("/admin/clients", tags=["clients"])
def admin_list_clients() -> dict:
    return clients.admin_overview()


@router.get("/admin/clients/{cid}", tags=["clients"])
def admin_get_client(cid: str) -> dict:
    rec = clients.public(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    return rec


@router.post("/admin/clients/{cid}/extend", tags=["clients"])
def admin_extend_trial(cid: str, days: int = Query(30)) -> dict:
    rec = clients.extend_trial(cid, days)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    persistence.save(STORE)
    return rec


@router.delete("/admin/clients/{cid}", tags=["clients"])
def admin_delete_client(cid: str) -> dict:
    if not clients.delete_client(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    persistence.save(STORE)
    return {"ok": True}


@router.post("/admin/clients/{cid}/seo", tags=["clients"])
def admin_run_client_seo(cid: str) -> dict:
    """Run the SEO audit for a client and log it against their account."""
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    result = client_seo.audit(rec.get("website", ""),
                              business_name=rec.get("business_name", ""),
                              city=rec.get("city", ""),
                              country=rec.get("country", ""),
                              industry=rec.get("industry", ""))
    # The crawl already happened. File what it OBSERVED about the business,
    # tagged with the surface it was seen on, so the CRM record carries its own
    # provenance instead of a value nobody can trace. Never fatal to the audit.
    try:
        from ..core import evidence
        from ..engines import client_seo as _cs
        page, _err, _st = _cs._fetch(result.get("url") or rec.get("website", ""))
        if page:
            evidence.observe_from_page(cid, page)
        # The Impressum is a separate page and is the strongest source there is
        # for the operator's legal name, address and VAT id.
        if result.get("ok"):
            base = (result.get("url") or "").rstrip("/")
            for path in ("/impressum", "/imprint"):
                imp, _e, st = _cs._fetch(base + path)
                if imp and st == 200:
                    evidence.observe_from_page(cid, imp, impressum=True)
                    break
    except Exception:
        pass

    clients.bump(cid, "seo_audits")
    if result.get("ok"):
        clients.bump(cid, "issues_found", len(result.get("findings", [])))
        # Keep the last result so discovery can aggregate across clients
        # without re-crawling every site on every request.
        clients.update_raw(cid, last_audit=result)
        clients.log_activity(
            cid, "seo",
            f"SEO audit: {result['score']}/100 ({result['grade']}), "
            f"{len(result['findings'])} issues found")
    else:
        clients.log_activity(cid, "seo",
                             f"SEO audit failed: {result.get('error')}")
    persistence.save(STORE)
    return result


@router.get("/admin/clients/{cid}/seo/schema", tags=["clients"])
def admin_client_schema(cid: str) -> dict:
    """The ready-to-paste JSON-LD block, admin side.

    The client portal already had this at /client/seo/schema, but that is
    behind a client token — so the SEO view in the dashboard, where the work
    actually gets done, could not show the single highest-value fix.
    """
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"json_ld": client_seo.suggested_schema(
        rec.get("business_name", ""), rec.get("city", ""),
        rec.get("website", ""), rec.get("industry", ""),
        country_code=compliance.code_for(rec.get("country", "")) or "DE")}


# ---- client-facing ---------------------------------------------------------
@router.post("/client/login", tags=["clients"])
def client_login(payload: ClientLoginIn) -> dict:
    token = clients.authenticate(payload.username, payload.password)
    if not token:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    cid = clients.resolve(token)
    persistence.save(STORE)
    return {"token": token, "client": clients.public(cid)}


@router.get("/client/me", tags=["clients"])
def client_me(x_client_token: Optional[str] = Header(None)) -> dict:
    return clients.public(_client_from_header(x_client_token))


@router.get("/client/seo", tags=["clients"])
def client_seo_report(x_client_token: Optional[str] = Header(None)) -> dict:
    cid = _client_from_header(x_client_token)
    rec = clients.get(cid) or {}
    return client_seo.audit(rec.get("website", ""),
                            business_name=rec.get("business_name", ""),
                            city=rec.get("city", ""),
                            country=rec.get("country", ""),
                              industry=rec.get("industry", ""))


@router.get("/client/seo/schema", tags=["clients"])
def client_seo_schema(x_client_token: Optional[str] = Header(None)) -> dict:
    """The ready-to-paste JSON-LD block — usually the single biggest win."""
    cid = _client_from_header(x_client_token)
    rec = clients.get(cid) or {}
    return {"json_ld": client_seo.suggested_schema(
        rec.get("business_name", ""), rec.get("city", ""),
        rec.get("website", ""), rec.get("industry", ""))}


# ---- client report + social plan -------------------------------------------

def _social_pack(rec: dict) -> dict:
    """Localised social plan for a client, from the measured brand playbook."""
    lang = {"Germany": "de", "Austria": "de", "Switzerland": "de",
            "Italy": "it", "France": "fr"}.get(rec.get("country", ""), "en")
    return {
        "week": brand_playbook.weekly_plan(
            rec.get("business_name", ""), rec.get("industry", "Restaurant"),
            rec.get("city", ""), lang),
        "highlights": brand_playbook.highlights_plan(
            rec.get("industry", ""), lang),
        "pillars": brand_playbook.PILLARS,
        "cadence": brand_playbook.CADENCE,
        "avoid": brand_playbook.FORBIDDEN,
        "benchmarks": brand_playbook.BENCHMARKS,
    }


@router.get("/client/social", tags=["clients"])
def client_social(x_client_token: Optional[str] = Header(None)) -> dict:
    cid = _client_from_header(x_client_token)
    return _social_pack(clients.get(cid) or {})


@router.get("/client/report.pdf", tags=["clients"])
def client_report_pdf(x_client_token: Optional[str] = Header(None)):
    """The PDF the client downloads — the thing that justifies the fee."""
    cid = _client_from_header(x_client_token)
    rec = clients.get(cid) or {}
    seo = client_seo.audit(rec.get("website", ""),
                           business_name=rec.get("business_name", ""),
                           city=rec.get("city", ""),
                           country=rec.get("country", ""),
                              industry=rec.get("industry", ""))
    pdf = client_report.build(clients.public(cid), seo, social=_social_pack(rec))
    clients.log_activity(cid, "report", "Website & visibility report generated")
    persistence.save(STORE)
    fname = (rec.get("business_name", "report").lower()
             .replace(" ", "-")[:40] + "-report.pdf")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/admin/clients/{cid}/report.pdf", tags=["clients"])
def admin_report_pdf(cid: str):
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    seo = client_seo.audit(rec.get("website", ""),
                           business_name=rec.get("business_name", ""),
                           city=rec.get("city", ""),
                           country=rec.get("country", ""),
                              industry=rec.get("industry", ""))
    pdf = client_report.build(clients.public(cid), seo, social=_social_pack(rec))
    fname = (rec.get("business_name", "report").lower()
             .replace(" ", "-")[:40] + "-report.pdf")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/client/content", tags=["clients"])
def client_content_week(dishes: str = Query(""), lang: str = Query("en"),
                        x_client_token: Optional[str] = Header(None)) -> dict:
    """A week of captions in English, each with a market-language twin."""
    cid = _client_from_header(x_client_token)
    out = client_content.week_of_posts(
        clients.public(cid), lang=lang,
        dishes=[d.strip() for d in dishes.split(",") if d.strip()])
    clients.bump(cid, "posts_drafted", len(out.get("posts", [])))
    clients.log_activity(cid, "content",
                         f"{len(out.get('posts', []))} captions drafted")
    persistence.save(STORE)
    return out


@router.post("/admin/clients/{cid}/content", tags=["clients"])
def admin_client_content(cid: str, dishes: str = Query(""),
                         lang: str = Query("en")) -> dict:
    if not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    out = client_content.week_of_posts(
        clients.public(cid), lang=lang,
        dishes=[d.strip() for d in dishes.split(",") if d.strip()])
    clients.bump(cid, "posts_drafted", len(out.get("posts", [])))
    persistence.save(STORE)
    return out


# ---- discovery: opportunities and risks found in real client data ----------

@router.get("/admin/discovery", tags=["clients"])
def admin_discovery(live: bool = Query(False)) -> dict:
    """Sellable offers derived from recurring findings, plus portfolio risks.

    live=true re-audits every client website (slow). Default reads the last
    stored audit result per client.
    """
    cache = {}
    if not live:
        for c in clients.all_clients():
            last = c.get("last_audit")
            if last:
                cache[c["id"]] = last
    return discovery.report(cache, live=live)


@router.get("/admin/news", tags=["clients"])
def news_watch() -> dict:
    """What the 24/7 news watch has found across every client."""
    from ..engines import client_news
    return client_news.summary()


@router.post("/admin/clients/{cid}/news", tags=["clients"])
def news_for_client(cid: str) -> dict:
    """Force a news check for one client now."""
    from ..engines import client_news
    if not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    return client_news.check_client(cid)


@router.get("/admin/clients/{cid}/evidence", tags=["clients"])
def client_evidence(cid: str) -> dict:
    """What Titan believes about this business, and why it believes it.

    Every field carries the surface it was observed on. Fields with only weak
    evidence stay BLANK and appear as a suggestion for a human to settle — a
    confidently wrong fact about a client is worse than an empty one, because
    nobody can tell it is wrong.
    """
    from ..core import evidence
    if not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    return evidence.record(cid)


class SettleIn(BaseModel):
    field: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


@router.post("/admin/clients/{cid}/evidence/settle", tags=["clients"])
def settle_evidence(cid: str, req: SettleIn) -> dict:
    """A human decides a contested field. Recorded as manual, which outranks
    every machine observation from then on."""
    from ..core import evidence
    if not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    evidence.settle(cid, req.field, req.value)
    persistence.save(STORE)
    return evidence.record(cid)


@router.get("/evidence/sources", tags=["clients"])
def evidence_sources() -> dict:
    """The source ranking, and the rule that nothing accepts a self-reported
    confidence score."""
    from ..core import evidence
    return evidence.sources()


@router.get("/admin/watch", tags=["clients"])
def admin_watch() -> dict:
    """Autonomous monitoring status: what changed on client sites, unprompted."""
    return client_watch.summary()


@router.post("/admin/clients/{cid}/watch", tags=["clients"])
def admin_watch_now(cid: str) -> dict:
    """Force an immediate check for one client."""
    r = client_watch.check_client(cid)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error", "failed"))
    persistence.save(STORE)
    return r


# --- organisations ---------------------------------------------------------
# Several people, one account, different privileges. See core/orgs.py.
#
# Every route here carries its OWN credential — an identity session, resolved
# through core/identity.py — which is why /api/org is in main._OPEN_PREFIXES
# alongside /api/client/ and /api/account. Open at the middleware, guarded at
# the endpoint, exactly as those are.
#
# A legacy environment-gate token does NOT work here, and that is correct
# rather than an oversight: those sessions belong to a configured username, not
# to a person, and there is no person for a membership row to point at. Set
# TITAN_FOUNDER_EMAIL and the founder gets a real account like everybody else.
#
# The adversarial route walk in the test suite attacks every route under this
# prefix with a non-member's token and fails on anything that answers 200, so a
# new endpoint that forgets its check is a failing test rather than a leak.

class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberAddIn(BaseModel):
    email: str
    role: str = "member"


class MemberRoleIn(BaseModel):
    role: str


class OrgStatusIn(BaseModel):
    status: str


def _identity_user(token: Optional[str]) -> dict:
    """Who is calling, as a person. 401 if nobody."""
    from ..core import identity
    user = identity.resolve((token or "").removeprefix("Bearer ").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


def _org_role(org_id: str, token: Optional[str], minimum: str) -> tuple:
    """The single gate for organisations, mirroring _owned for businesses.

    Returns (user, role). Every refusal — not signed in aside — is the SAME
    404, because "no such organisation" and "not yours" being distinguishable
    tells a prober which ids are real.
    """
    from ..core import orgs
    user = _identity_user(token)
    try:
        role = orgs.require_member(org_id, user["id"], minimum)
    except orgs.NotAMember:
        raise HTTPException(status_code=404, detail="Not found")
    return user, role


@router.post("/org", tags=["orgs"])
def create_org(req: OrgCreateIn, request: Request,
               authorization: Optional[str] = Header(None)) -> dict:
    """Start an organisation. The caller becomes its first owner."""
    from ..core import orgs, ratelimit
    user = _identity_user(authorization)
    # Keyed on the person, not the address: this endpoint is authenticated, so
    # the account is the thing worth limiting, and an office behind one IP must
    # not throttle each other.
    verdict = ratelimit.check("org", user["id"])
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    from ..core import audit
    try:
        org = orgs.create(req.name, user["id"], created_by=user["email"])
    except orgs.OrgError as e:
        audit.record(user["email"], "org.create", "org", "", audit.REFUSED,
                     name=req.name, reason=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(user["email"], "org.create", "org", org["id"],
                 name=org["name"])
    return org


@router.get("/org", tags=["orgs"])
def my_orgs(authorization: Optional[str] = Header(None)) -> dict:
    """Only the organisations this person belongs to. Never a global list."""
    from ..core import orgs
    user = _identity_user(authorization)
    return {"organisations": orgs.orgs_for(user["id"])}


@router.get("/org/{org_id}", tags=["orgs"])
def org_detail(org_id: str,
               authorization: Optional[str] = Header(None)) -> dict:
    from ..core import orgs
    user, role = _org_role(org_id, authorization, orgs.VIEWER)
    org = orgs.get(org_id)
    org["your_role"] = role
    return org


@router.get("/org/{org_id}/members", tags=["orgs"])
def org_members(org_id: str,
                authorization: Optional[str] = Header(None)) -> dict:
    from ..core import orgs
    user, role = _org_role(org_id, authorization, orgs.VIEWER)
    return {"members": orgs.members(org_id), "your_role": role}


@router.post("/org/{org_id}/members", tags=["orgs"])
def org_add_member(org_id: str, req: MemberAddIn,
                   authorization: Optional[str] = Header(None)) -> dict:
    """Give somebody access. Administrator and above."""
    from ..core import identity, orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    person = identity.get(req.email)
    if not person:
        # Not the same 404 as the org gate: the caller is a proven
        # administrator of this organisation, so telling them the address has
        # no account is help, not disclosure.
        raise HTTPException(status_code=400,
                            detail="That address has no Titan account yet.")
    from ..core import audit
    try:
        added = orgs.add_member(org_id, person["id"], req.role)
    except orgs.OrgError as e:
        audit.record(user["email"], "org.member.add", "org", org_id,
                     audit.REFUSED, member=person["email"], role=req.role,
                     reason=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(user["email"], "org.member.add", "org", org_id,
                 member=person["email"], role=req.role)
    return added


@router.patch("/org/{org_id}/members/{user_id}", tags=["orgs"])
def org_set_member_role(org_id: str, user_id: str, req: MemberRoleIn,
                        authorization: Optional[str] = Header(None)) -> dict:
    from ..core import orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    from ..core import audit
    try:
        changed = orgs.set_member_role(org_id, user_id, req.role)
    except orgs.OrgError as e:
        # A refused attempt is recorded too. Six refusals to demote the last
        # owner is the signal; keeping only successes throws away the half
        # worth looking at.
        audit.record(user["email"], "org.member.role", "org", org_id,
                     audit.REFUSED, member_id=user_id, role=req.role,
                     reason=str(e))
        raise HTTPException(status_code=409, detail=str(e))
    if not changed:
        raise HTTPException(status_code=404, detail="Not found")
    audit.record(user["email"], "org.member.role", "org", org_id,
                 member_id=user_id, role=req.role)
    return {"org_id": org_id, "user_id": user_id, "role": req.role}


@router.delete("/org/{org_id}/members/{user_id}", tags=["orgs"])
def org_remove_member(org_id: str, user_id: str,
                      authorization: Optional[str] = Header(None)) -> dict:
    from ..core import orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    from ..core import audit
    try:
        removed = orgs.remove_member(org_id, user_id)
    except orgs.OrgError as e:
        audit.record(user["email"], "org.member.remove", "org", org_id,
                     audit.REFUSED, member_id=user_id, reason=str(e))
        raise HTTPException(status_code=409, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail="Not found")
    audit.record(user["email"], "org.member.remove", "org", org_id,
                 member_id=user_id)
    return {"removed": True, "org_id": org_id, "user_id": user_id}


@router.patch("/org/{org_id}", tags=["orgs"])
def org_set_status(org_id: str, req: OrgStatusIn,
                   authorization: Optional[str] = Header(None)) -> dict:
    """Suspend or reactivate. Owners only — a suspended organisation refuses
    everybody, including its own administrators, so it is not an admin action."""
    from ..core import orgs
    user, role = _org_role(org_id, authorization, orgs.OWNER)
    from ..core import audit
    try:
        if not orgs.set_status(org_id, req.status):
            raise HTTPException(status_code=404, detail="Not found")
    except orgs.OrgError as e:
        audit.record(user["email"], "org.status", "org", org_id,
                     audit.REFUSED, status=req.status, reason=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(user["email"], "org.status", "org", org_id,
                 status=req.status)
    return orgs.get(org_id)


@router.get("/org/{org_id}/audit", tags=["orgs"])
def org_audit(org_id: str, limit: int = 50,
              authorization: Optional[str] = Header(None)) -> dict:
    """What has been done to this organisation, newest first.

    Administrator and above: an audit trail names who did what, and that is
    exactly the thing a plain member should not be able to read about their
    colleagues. `stats.durable` says whether any of it survives the next
    rebuild - on the current free tier it does not, and a compliance record you
    wrongly believe is kept is worse than none at all.
    """
    from ..core import audit, orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    return {"entries": audit.recent(limit=limit, target_id=org_id),
            "stats": audit.stats()}


@router.get("/founder/metrics", tags=["founder"])
def founder_metrics(days: int = 30) -> dict:
    """Executive metrics, every one carrying whether it was measured.

    Behind the founder token, and `/api/founder` is already in
    `demo_data._SENSITIVE_PREFIXES`, so a demo visitor is refused rather than
    shown a substituted version - there is no demo-safe edition of revenue.

    Read `metrics.measured` before `metrics.value` on every field. A `value` of
    null means nothing was measured, and is deliberately NOT zero: with no
    payment processor connected, $0 MRR would read as a business result when
    the truth is that nobody could have paid.
    """
    from ..core import metrics
    return metrics.report(days=days)


# --- feature flags, integrations and onboarding ----------------------------

class FlagOverrideIn(BaseModel):
    scope: str
    scope_id: str
    enabled: bool


@router.get("/founder/flags", tags=["founder"])
def founder_flags(plan: str = "", user_id: str = "",
                  org_id: str = "") -> dict:
    """Every flag as it resolves, and WHY.

    `decided_by` is the field that matters. "It is off for this customer" is
    not something anybody can act on; "the plan layer said no" is.
    """
    from ..core import flags
    return {"flags": flags.all_flags(user_id=user_id, org_id=org_id,
                                     plan=plan),
            "overrides": flags.overrides()}


@router.post("/founder/flags/{key}", tags=["founder"])
def founder_set_flag(key: str, req: FlagOverrideIn) -> dict:
    from ..core import audit, flags
    try:
        out = flags.set_override(key, req.scope, req.scope_id, req.enabled,
                                 set_by="founder")
    except flags.FlagError as e:
        audit.record("founder", "flag.set", "flag", key, audit.REFUSED,
                     scope=req.scope, reason=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    audit.record("founder", "flag.set", "flag", key, scope=req.scope,
                 scope_id=req.scope_id, enabled=req.enabled)
    return out


@router.delete("/founder/flags/{key}", tags=["founder"])
def founder_clear_flag(key: str, scope: str, scope_id: str) -> dict:
    from ..core import audit, flags
    try:
        cleared = flags.clear_override(key, scope, scope_id)
    except flags.FlagError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cleared:
        raise HTTPException(status_code=404, detail="No such override")
    audit.record("founder", "flag.clear", "flag", key, scope=scope,
                 scope_id=scope_id)
    return {"cleared": True, "key": key}


@router.get("/founder/integrations", tags=["founder"])
def founder_integrations() -> dict:
    """What is actually connected, what it unlocks, and what it costs.

    Every row is answered by the module that owns the question. A check that
    raises reads `unknown`, never `not_configured` - "go and connect it" and
    "something is broken on our side" are different actions.
    """
    from ..core import integrations
    return integrations.summary()


@router.get("/founder/onboarding", tags=["founder"])
def founder_onboarding() -> dict:
    """Setup completion across every account, averaged only over the accounts
    that could actually be scored."""
    from ..core import onboarding
    return onboarding.summary()


@router.get("/account/onboarding", tags=["billing"])
def account_onboarding(x_account_token: Optional[str] = Header(None)) -> dict:
    """The caller's OWN setup score. Scoped by the token, so there is no id to
    manipulate and nothing to walk sideways into."""
    from ..core import billing, onboarding
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    return onboarding.for_account(email)


@router.get("/founder/search", tags=["founder"])
def founder_search(q: str = "", limit: int = 20) -> dict:
    """Find a customer from anything you can remember about them.

    Searches ACROSS tenants by design, which is what makes it useful to the
    operator and exactly what makes it unsafe for a customer. It lives under
    `/api/founder`, already in `demo_data._SENSITIVE_PREFIXES`. A per-tenant
    search would need its own function with an org filter, not a parameter on
    this one - a boolean deciding whether to leak every tenant is one wrong
    default away from doing it.
    """
    from ..core import search
    return search.search(q, limit=limit)


@router.get("/founder/notifications", tags=["founder"])
def founder_notifications() -> dict:
    """Conditions that are true right now, worst first.

    Nothing is stored, so a notification disappears when the condition does.
    Read `not_emitted` too: it lists what Titan deliberately does NOT notify
    about yet and names the missing data, rather than inventing an alert.
    """
    from ..core import notifications
    return notifications.current()
