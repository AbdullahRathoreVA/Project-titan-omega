"""HTTP API for the command center.

All routes are mounted under ``/api``. Responses use the pydantic schemas in
:mod:`domain.schemas` so the Next.js dashboard has a stable contract.
"""

from __future__ import annotations

import os
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
    return {
        "required": auth.require_auth(),
        "demo": auth.using_demo_credentials(),
        "guest": auth.guest_mode(),
        # Public "View demo" button on the login screen.
        "guest_available": auth.guest_enabled(),
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
def login(req: LoginRequest) -> dict:
    if not auth.check_login(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": auth.make_token(req.username), "username": req.username}


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
        instructions = (
            "Reply in Urdu (Arabic script). Then output a line containing exactly '###' "
            "and after it write the SAME reply in Hindi (Devanagari script) for text-to-speech."
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
    if raw and is_urdu and "###" in raw:
        parts = raw.split("###", 1)
        answer = parts[0].strip()
        spoken = parts[1].strip()

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
def signup(req: SignupIn) -> dict:
    from ..core import billing
    try:
        account = billing.signup(req.email, req.password, req.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persistence.save(STORE)
    return account


@router.post("/account/login", tags=["billing"])
def account_login(req: SignupIn) -> dict:
    from ..core import billing
    token = billing.authenticate(req.email, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Wrong email or password")
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
    try:
        return billing.checkout(email, plan_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
