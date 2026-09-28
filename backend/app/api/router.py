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
from ..core import auth, clients, cockpit_scope, executive, learning, llm
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
        # Which login is active. `identity` means real accounts with roles; `legacy`
        # means the single environment gate is still answering. This endpoint is
        # public, so identity.mode() carries no address.
        "identity": identity.mode(),
    }


@router.get("/session", tags=["auth"])
def session(request: Request) -> dict:
    """What kind of session is this token? The front end mustn't guess from
    browser storage, or a demo token restored in a new tab would be shown as
    the founder while still being served sample data.
    """
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return {"founder": auth.valid_token(tok), "guest": auth.valid_guest_token(tok)}


@router.post("/demo/enter", tags=["auth"])
def enter_demo(request: Request) -> dict:
    """Start a read-only tour of the operator console, no login required.

    This isn't the customer product: it's the founder's cockpit with every
    private figure replaced by sample content, and it's labelled that way.

    Returns a guest token that unlocks GET-only access. Endpoints holding real
    business data serve sample content instead, and any write is refused.
    """
    from ..core import ratelimit
    # Demo sessions are cheap but not free, so they're rate-limited per caller.
    verdict = ratelimit.check("demo", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    if not auth.guest_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    return {"token": auth.make_guest_token(), "guest": True}


@router.post("/demo/cockpit", tags=["auth"])
def enter_cockpit_demo(request: Request) -> dict:
    """Open the subscriber cockpit itself - all sixteen tabs, boot, voice, 3D
    universe - on the public demo account, with no signup.

    This is exactly the cockpit a subscriber signs into, not the founder's
    console and not the portal. It holds Titan's own demonstration businesses
    (its own pages, audited for real) and nothing belonging to anyone else.

    The demo account is read-only on every door (main.auth_guard): a visitor
    can open every screen but can't change or send anything.
    """
    from ..core import billing, ratelimit, sessions
    from ..engines import demo_workspace

    cockpit_limit = ratelimit.check("demo", ratelimit.identity_for(request))
    if not cockpit_limit["allowed"]:
        raise HTTPException(status_code=429, detail=cockpit_limit)
    if not auth.guest_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    if not demo_workspace.business_ids():
        # No demonstration business, no demo. Never a real one in its place.
        raise HTTPException(
            status_code=503,
            detail=("The demonstration workspace is not available. It is "
                    "seeded on boot and disabled by TITAN_DEMO_WORKSPACE=0."))
    email = billing.ensure_demo_account()
    return {"token": sessions.issue(email, kind="account", ttl=2 * 3600),
            "demo": True}


@router.post("/demo/portal", tags=["auth"])
def enter_customer_demo(request: Request) -> dict:
    """Open the customer portal on a demo business, with no signup.

    Nothing here is sample data. The business is one of those seeded by
    engines/demo_workspace.py, whose sites are Titan's own pages and whose
    audits really run every six hours.

    The server chooses the business; the caller can't name one, since this is
    reachable by anyone with no token. demo_workspace.showcase() only returns
    a business carrying is_demo, and returns None rather than a real one.
    """
    from ..core import ratelimit
    from ..engines import demo_workspace

    # Named differently from the one in enter_demo on purpose: both use the same
    # bucket, and each mutation guard needs an anchor that matches in exactly one
    # place.
    portal_limit = ratelimit.check("demo", ratelimit.identity_for(request))
    if not portal_limit["allowed"]:
        raise HTTPException(status_code=429, detail=portal_limit)
    if not auth.guest_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is disabled")

    business = demo_workspace.showcase()
    if not business:
        # Never fall back to a real client. An empty demo workspace is a refusal.
        raise HTTPException(
            status_code=503,
            detail=("The demonstration workspace is not available. It is "
                    "seeded on boot and disabled by TITAN_DEMO_WORKSPACE=0."))

    # Belt and braces: showcase() already filters on is_demo, but this refuses to
    # mint the session if that ever stops being true.
    if not demo_workspace.is_demo_client(business):
        raise HTTPException(status_code=503,
                            detail="Demonstration business is not marked as one.")

    token = clients.issue_session(business["id"])
    if not token:
        raise HTTPException(status_code=503,
                            detail="Demonstration business could not be opened.")
    return {
        "token": token,
        "portal_url": "/portal",
        "demo": True,
        "business_name": business.get("business_name", ""),
        "website": business.get("website", ""),
        "note": ("A real business record audited on Titan's own pages. Read-"
                 "only: every endpoint this session can reach is a GET."),
    }


@router.post("/login", tags=["auth"])
def login(req: LoginRequest, request: Request) -> dict:
    from ..core import ratelimit
    # Rate-limited per caller, not per address typed, so nobody can lock the
    # founder out by hammering the founder's address.
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    token = auth.login(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    # The identifier Titan authenticated, not the one typed: real accounts
    # normalise the address, so echoing the input could show different
    # capitalisation from what's stored.
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
    """Talk directly to one agent. It replies in character, using its own role,
    mission and current task as context.

    In a subscriber's cockpit the agent works for their workspace and their
    businesses, and addresses them directly.
    """
    from ..core import quota
    from ..engines import owner
    rt = STORE.agents.get(agent_id)
    if rt is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    s = rt.spec
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    businesses = owner.subscriber_businesses()
    if businesses is not None:
        company = (f"the Titan Omega workspace that runs {owner.describe(businesses)}"
                   if businesses else "this owner's new Titan Omega workspace")
        address = ("Speak to the owner as 'you', and never mention any other "
                   "person, company or customer.")
    else:
        company = "Abdullah's autonomous company, Titan Omega"
        address = "Address the founder as 'Abdullah'."

    reply = llm.complete(
        system=(
            f"You are {s.name}, the {s.title} in the {s.division.value} division of "
            f"{company}. Speak in character as this "
            f"agent. Your mission: {s.mission}. Right now you are working on: "
            f"{rt.current_task or 'advancing your division objectives'}. {address} "
            "Be concrete and specific about what YOU (this role) "
            f"are doing or will do. Keep it 2-4 sentences. Reply in {lang_name}."
        ),
        prompt=req.message,
        max_tokens=400,
    ) or quota.no_answer_note(
        f"Abdullah, {s.name} here. I'm on it — {rt.current_task or 'advancing my objectives'}. "
        "Set an LLM key (Groq/Hermes, free) to unlock my full conversational replies."
    )

    who = "You" if businesses is not None else "Abdullah"
    STORE.emit(s.id, "command", f'{who} talked to {s.name}: "{req.message[:60]}"', "info")
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
    """Reject requests when TITAN_WEBHOOK_SECRET is set and the header doesn't match.

    Only used on the external metric-push endpoints that Make.com / Zapier
    call. In-dashboard buttons (revenue log, inbox reply) don't use this; they
    are same-origin and use the normal login token when auth is enabled.
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


# --- revenue ledger (Upwork orders, Career Mind sales, Kindle, etc.) -------

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
    """Full order history, newest first."""
    return list(reversed(STORE.revenue_entries))


@router.post("/revenue/log", tags=["revenue"])
def log_revenue(entry: RevenueLog) -> dict:
    """Record a real order or sale. Appends a dated ledger entry and updates the
    running total.
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
    cheer = ("Your business is earning!" if cockpit_scope.is_customer()
             else "Abdullah, the empire is EARNING!")
    STORE.emit(
        "revenue-tracker", "revenue",
        f"💰 REAL ORDER: +${entry.amount:.2f} from {source} — {label}. "
        f"Total earned now ${m['mrr']:.2f}. {cheer}",
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


# The same studio for a subscriber, written about their own business. The
# founder-only kinds (school and job-seeker outreach for Career Mind) aren't
# offered; an unknown kind falls back to market analysis. {desc} is replaced
# with the business description by plain substitution, not str.format(),
# since a business name may contain braces.
_SUBSCRIBER_INTEL = {
    "market_analysis": (
        "You are a sharp market analyst for {desc}. Produce a concise, actionable "
        "market analysis: current demand, the best target customers, a competitor "
        "angle, simple pricing ideas, and 3 ZERO-COST growth moves to execute THIS "
        "WEEK. Use clear headings and short bullets."
    ),
    "business_outreach": (
        "Write a short, warm cold email / DM from {desc} to a potential customer. "
        "Give a subject line, a 4-6 sentence body focused on concrete value, and a "
        "clear CTA. No hype, no fake promises."
    ),
    "customer_reply": _INTEL_PROMPTS["customer_reply"],
    "youtube_ideas": (
        "Suggest 8 specific short-video ideas (YouTube Shorts, Reels, TikTok) the "
        "owner of {desc} can make for FREE to win customers — each with a punchy "
        "title and a one-line hook. Then give 5 search queries to study what is "
        "trending in this niche."
    ),
}


class IntelRequest(BaseModel):
    kind: str = Field(default="market_analysis")
    topic: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/intel/generate", tags=["system"])
def intel_generate(req: IntelRequest) -> dict:
    """Generate market analysis or outreach copy on demand via the LLM."""
    from ..core import quota
    from ..engines import owner
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        desc = owner.describe(businesses) or "a small local business"
        kind = req.kind if req.kind in _SUBSCRIBER_INTEL else "market_analysis"
        base = _SUBSCRIBER_INTEL[kind].replace("{desc}", desc)
        default_topic = f"The business: {desc}."
        for_whom = "you"
    else:
        kind = req.kind
        base = _INTEL_PROMPTS.get(req.kind, _INTEL_PROMPTS["market_analysis"])
        default_topic = ("Use Abdullah's businesses: Career Mind AI (student career "
                         "platform) and Upwork AI gigs.")
        for_whom = "Abdullah"
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    content = llm.complete(
        system=base + f" Write the entire output in {lang_name}.",
        prompt=req.topic or default_topic,
        max_tokens=900,
    )

    if not content:
        content = quota.no_answer_note(
            "AI generation is in free fallback mode. Set GROQ_API_KEY in your Space secrets "
            "(free, no card) and click again to get a full, tailored result here."
        )

    STORE.emit(
        "intelligence-studio", "discovery",
        f"Generated {kind.replace('_', ' ')} for {for_whom}.", "success",
    )
    return {"kind": kind, "content": content}


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
    browser TTS engine - Urdu voices are rarely installed, but Hindi ones
    pronounce the same words correctly).

    A subscriber gets their own briefing from /api/me/voice-report.
    """
    subscriber = cockpit_scope.customer_email()
    if subscriber:
        return _subscriber_voice_report(subscriber)
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


def _subscriber_voice_report(email: str) -> dict:
    """The same spoken briefing about a subscriber's own workspace: their
    businesses, leads, logged sales and agents. No name - the account holds
    an email, not a name, and a guessed name is worse than none.
    """
    from ..core import billing, crm
    from ..store import founder_store

    n = len([cid for cid in billing.owned_clients(email) if clients.get(cid)])
    k = len(crm.visible_to(founder_store().leads, email))
    s = executive.empire_status(STORE)
    mrr = float(s.get("mrr", 0) or 0)
    active, total = s.get("active_agents", 0), s.get("total_agents", 0)

    if mrr == 0:
        earn_ur = "ابھی تک آپ نے کوئی فروخت درج نہیں کی۔ "
        earn_hi = "अभी तक आपने कोई फ़रोख़्त दर्ज नहीं की। "
    else:
        earn_ur = f"اب تک آپ نے کل {mrr:.0f} ڈالر کی فروخت درج کی ہے۔ "
        earn_hi = f"अब तक आपने कुल {mrr:.0f} डॉलर की फ़रोख़्त दर्ज की है। "

    urdu_text = (
        "اسلام و علیکم! یہ رہی آپ کے کاروبار کی تازہ ترین رپورٹ۔ "
        f"Titan پر آپ کے {n} کاروبار ہیں اور آپ کے CRM میں {k} لیڈز ہیں۔ "
        f"{earn_ur}"
        f"اس وقت {active} ڈیجیٹل ملازمین کام کر رہے ہیں، کل {total} میں سے۔ "
        "آگے بڑھتے رہیں!"
    )
    hindi_text = (
        "अस्सलाम वालेकुम! ये रही आपके कारोबार की ताज़ा तरीन रिपोर्ट। "
        f"टाइटन पर आपके {n} कारोबार हैं और आपके सी आर एम में {k} लीड्स हैं। "
        f"{earn_hi}"
        f"इस वक्त {active} डिजिटल मुलाज़िमीन काम कर रहे हैं, कुल {total} में से। "
        "आगे बढ़ते रहिए!"
    )
    return {"urdu": urdu_text, "hindi": hindi_text, "businesses": n, "leads": k,
            "mrr": mrr, "active_agents": active, "total_agents": total}


# --- Ask Titan assistant (voice/text, ~12 languages) -----------------------

# The LLM is multilingual; the browser supplies the TTS voice per language.
# Urdu is special-cased (### + Devanagari) because Urdu voices are rarely
# installed but Hindi ones read the same words aloud.
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
    """Answer the founder's question in the chosen language. Returns 'answer'
    (display) and 'spoken' (Devanagari for Urdu so the Hindi voice reads it;
    the same as 'answer' for every other language).

    From a subscriber's cockpit (/api/me/assistant) it answers about their own
    businesses instead - see _subscriber_brief. The founder's figures below
    never reach a subscriber.
    """
    lang = req.lang if req.lang in ASSISTANT_LANGS else "en"
    is_urdu = lang == "ur"
    subscriber = cockpit_scope.customer_email()

    if subscriber:
        brief = _subscriber_brief(subscriber)
        persona, context = brief["persona"], brief["context"]
    else:
        c = _empire_context()
        persona = (
            "You are Titan, the AI chief-of-staff for Abdullah's autonomous business "
            "empire (Career Mind AI student platform + Upwork AI gigs). "
            "Always address the founder simply as 'Abdullah'.")
        context = (
            f"Live empire state — "
            f"Total revenue earned: ${c['mrr']:.0f}. "
            f"Career Mind AI: {c['cm_users']} total users, {c['cm_active']} active, {c['cm_signups']} new signups. "
            f"Upwork: {c['fiverr_orders']} orders, {c['fiverr_impressions']} impressions. "
            f"{c['active_agents']} of {c['total_agents']} AI agents active. "
            f"{c['open_opportunities']} open opportunities. Empire health {c['health']:.0f}%."
        )

    if is_urdu:
        # Ask for a transliteration, not a translation: the same Urdu sentence,
        # letter for letter, written in Devanagari only so a Hindi TTS voice can
        # pronounce it. Asking for "the same reply in Hindi" gets Hindi vocabulary,
        # which Urdu speakers then hear as Hindi.
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
            f"{persona} {instructions} "
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
            # The model often drops the separator; split by script instead, so the
            # Devanagari half is never shown to the reader.
            answer, spoken = _split_urdu_scripts(raw)
        # Whatever happened above, the displayed answer must never contain
        # Devanagari, and the spoken line must never be empty.
        answer = _strip_devanagari(answer) or _strip_devanagari(raw)
        spoken = spoken.strip() or answer

    if not raw and subscriber:
        answer, spoken = brief["fallback_ur"] if is_urdu else brief["fallback_en"]
    elif not raw:
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

    who = "You" if subscriber else "Abdullah"
    STORE.emit("titan-assistant", "command", f'{who} asked: "{req.question[:80]}"', "info")
    return {"answer": answer, "spoken": spoken, "lang": lang}


def _subscriber_brief(email: str) -> dict:
    """What Ask Titan knows when a subscriber asks: their plan, their own
    businesses and their own leads. Nothing of the founder's or anyone else's -
    the model can't repeat what it was never given.
    """
    from ..core import billing, crm, quota
    from ..store import founder_store

    acct = billing.public(email)
    businesses = [clients.public(cid) for cid in billing.owned_clients(email)]
    businesses = [b for b in businesses if b]
    leads = crm.visible_to(founder_store().leads, email)
    won = sum(1 for lead in leads if lead.get("status") == "won")

    def describe(b: dict) -> str:
        score = (b.get("last_audit") or {}).get("score")
        site = b.get("website") or "no website"
        audit = f"last SEO audit {score}/100" if isinstance(score, (int, float)) \
            else "not audited yet"
        return f"{b.get('business_name') or 'Unnamed'} ({site}, {audit})"

    context = (
        f"This subscriber's account - plan: {acct.get('plan_name', 'Free')}. "
        f"AI answers used this month: {acct.get('usage', {}).get('ai_calls', 0)}. "
        f"Their businesses on Titan ({len(businesses)}): "
        f"{'; '.join(describe(b) for b in businesses) or 'none yet'}. "
        f"Their CRM: {len(leads)} leads, {won} won. "
        f"Revenue they have logged in Titan: ${float(STORE.metrics.get('mrr', 0) or 0):.0f}."
    )
    persona = (
        "You are Titan, the AI assistant inside this subscriber's own Titan Omega "
        "cockpit. Titan audits their websites, finds SEO problems, tracks their "
        "leads and reports on their businesses. Speak to them as 'you'. Never "
        "mention any other person, customer or business - you know only theirs, "
        "and if the data below cannot answer, say what Titan would need.")

    n, k = len(businesses), len(leads)
    en = (f"You have {n} business{'es' if n != 1 else ''} on Titan and "
          f"{k} lead{'s' if k != 1 else ''} in your CRM. ")
    en += quota.no_answer_note("")
    return {
        "persona": persona,
        "context": context,
        "fallback_en": (en, en),
        "fallback_ur": (
            f"Titan پر آپ کے {n} کاروبار ہیں اور آپ کے CRM میں {k} لیڈز ہیں۔",
            f"Titan पर आपके {n} कारोबार हैं और आपके CRM में {k} लीड्स हैं।",
        ),
    }


# --- Urdu script handling -------------------------------------------------
# Urdu is written in Arabic script, Hindi in Devanagari. They share phonetics,
# which is why a Hindi TTS voice can read transliterated Urdu - and why the two
# are easy to mix up. These keep them apart explicitly instead of relying on the
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

    Returns (displayed_urdu, spoken_devanagari). With no Devanagari at all the
    Urdu is used for both: a Hindi voice reading Arabic script is poor, but
    silence is worse, and inventing a transliteration here would be guessing
    at pronunciation.
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

    So "can Titan crawl / call / message yet?" is answered on screen:
    `not_configured` names the missing variable, and `licence_blocked` can't
    be fixed by writing code.
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

    Every cost here is estimated: no provider returns token usage through
    `llm.complete()`, so actual spend is reported as null.
    """
    from ..core import model_router
    return model_router.economics()


@router.get("/approvals", tags=["system"])
def approvals_pending() -> dict:
    """Everything waiting on a person, across every surface.

    Read-only. Approving happens on each item's own endpoint, which enforces
    rules this list doesn't know (a site fix whose page changed is refused
    there, so is an improvement that measured worse). A central approve-all
    would skip those checks.
    """
    from ..core import approvals
    return approvals.pending(STORE)


# --- self-improvement -----------------------------------------------------
# The founder is the approval step. Everything here is founder-only: `approve`
# changes how the live product behaves.

class ProposalRequest(BaseModel):
    param: str
    value: float
    reason: str
    evidence: dict | None = None


class ApprovalRequest(BaseModel):
    # Required, with no default. An approval without a name isn't an audit trail,
    # and a default like "founder" would be a name nobody typed.
    approver: str
    why: str = ""


def _improve_call(fn, *args, **kwargs) -> dict:
    """ValueError from the engine becomes a 400 with its own message.

    Those messages ("this measured worse", "Titan doesn't deploy its own
    changes") are meant for the user, so they're passed through rather than
    replaced with a generic error.
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
    """Apply an already approved proposal. Refuses anything else."""
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
    """Say what would be done, and what it would cost, before doing it.

    Doesn't execute - /api/agent/act does that. Keeping them separate means a
    plan can be read, priced and refused first, and a plan with a blocked step
    says so instead of failing halfway through.
    """
    from ..core import planner
    return planner.plan(req.goal).as_dict()


# --- subscriptions and signup --------------------------------------------

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

    This is the conversion path: the first moment the product does something
    for the person who signed up.

    The plan's business limit is enforced here, and a refusal names the limit
    and the tier that lifts it.
    """
    from ..core import billing

    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    return onboard_business(email, req)


def onboard_business(email: str, req: OnboardIn) -> dict:
    """Add a business to this subscriber and run its first audit. Shared by
    /join (above) and the cockpit's Clients tab (api/mine.py)."""
    from ..core import analytics, billing, evidence
    from ..engines import client_seo as _cs

    # Onboarding fetches a URL the caller supplies; unmetered, Titan would become
    # a request amplifier aimed at someone else's server. Keyed on the account,
    # since the caller is authenticated here.
    from ..core import ratelimit
    limited = ratelimit.check("onboard", email)
    if not limited["allowed"]:
        raise HTTPException(status_code=429, detail=limited)

    verdict = billing.can_add_client(email)
    if not verdict["allowed"]:
        # 402 rather than 403: it isn't forbidden, it's a plan limit.
        raise HTTPException(status_code=402, detail=verdict)

    # A subscriber's own business gets no separate portal login - they already
    # sign in as the account holder. A random credential is stored so the shared
    # client record stays valid without creating a usable second login.
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
                # The crawl already happened - record what it observed.
                try:
                    page, _e, _s = _cs._fetch(rec["website"])
                    if page:
                        evidence.observe_from_page(rec["id"], page)
                        # ...and keep the readable text, so the voice agent can answer
                        # questions about this business from its own site. The page is
                        # already fetched.
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
    """How a non-technical owner creates the credential Titan needs.

    Public: someone deciding whether to sign up should see exactly what will
    be asked of them first.
    """
    from ..core import site_access
    return site_access.setup_guide(provider)


@router.post("/account/clients/{cid}/site", tags=["billing"])
def connect_site(cid: str, req: SiteConnectIn,
                 x_account_token: Optional[str] = Header(None)) -> dict:
    """Give Titan write access to a business's own website.

    The credential is checked against the live site before anything is
    stored, encrypted at rest, and never returned by any endpoint. Ownership
    is checked first, so one subscriber's token can never connect another
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
# Titan changing a page on someone else's live website. Every endpoint checks
# two things: that the caller owns the business, and that the fix belongs to
# that business. Checking only the first would let a subscriber apply another
# subscriber's fix by guessing its id.

class ApproveIn(BaseModel):
    approver: str = Field(..., min_length=1,
                          description="Who is approving. Recorded on the fix.")
    reason: str = Field(default="")


def _owned(cid: str, token: Optional[str]) -> str:
    """The single ownership gate. See core/tenancy.py.

    Also binds the tenant to the logging context, so every log line for the
    rest of the request carries it.
    """
    from ..core import tenancy
    try:
        return tenancy.require_owner(cid, token or "")
    except tenancy.NotOwned:
        # Same 404 as "no such client"; two different answers would tell a prober
        # which client ids exist.
        raise HTTPException(status_code=404, detail="Not found")


def _owned_fix(cid: str, fix_id: str, token: Optional[str]) -> dict:
    from ..core import site_fix
    _owned(cid, token)
    fix = site_fix.get(fix_id)
    # Same 404 for "no such fix" and "not yours", so a prober can't tell which
    # ids exist.
    if not fix or fix["client_id"] != cid:
        raise HTTPException(status_code=404, detail="Not found")
    return fix


@router.post("/account/clients/{cid}/fixes/propose", tags=["billing"])
def propose_fixes(cid: str,
                  x_account_token: Optional[str] = Header(None)) -> dict:
    """Turn the latest audit's findings into concrete, appliable changes.

    Nothing on the site changes. It reads the connected WordPress site to
    find the real page behind the audited URL and records what it would
    write, plus every finding it can't fix and why.
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
    """The full before/after text, so a person can read what they're approving."""
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

    A 409 means the change did not go live - either the page changed since it
    was proposed, or the site accepted the write and discarded it. The body
    carries what the site says now.
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


@router.post("/account/clients/{cid}/portal", tags=["billing"])
def open_client_portal(cid: str,
                       x_account_token: Optional[str] = Header(None)) -> dict:
    """Open the customer portal for a business this subscriber owns.

    A subscriber's own business is created with a deliberately unusable portal
    password, so this is their way in.

    Ownership is checked first, by the same gate as every other client route,
    so one subscriber's token can never open another's business.
    """
    from ..core import audit, clients as registry
    _owned(cid, x_account_token)

    token = registry.issue_session(cid)
    if not token:
        raise HTTPException(status_code=404, detail="Not found")

    from ..core import billing
    audit.record(billing.resolve(x_account_token or "") or "unknown",
                 "portal.open", "client", cid)
    return {"token": token, "portal_url": "/portal",
            "note": ("Store this as `client_token` in sessionStorage and open "
                     "/portal. It is a session, not a password, and it ends "
                     "when the tab does.")}


class PortalPasswordIn(BaseModel):
    password: str = Field(..., min_length=8)


@router.post("/account/clients/{cid}/portal-password", tags=["billing"])
def set_portal_password(cid: str, req: PortalPasswordIn,
                        x_account_token: Optional[str] = Header(None)) -> dict:
    """The owner sets the portal password for one of their businesses.

    Owner-only. The portal password starts as a random unusable string, so the
    owner is the one who sets a real one. A portal session can't change it:
    that session was minted for an owner who already proved ownership, and
    letting it change the credential would turn a link shared once into
    permanent access.

    Every existing portal session for this business ends (clients.set_password
    revokes them).
    """
    email = _owned(cid, x_account_token)
    if not clients.set_password(cid, req.password):
        raise HTTPException(status_code=404, detail="Not found")
    persistence.save(STORE)
    from ..core import audit
    audit.record(email, "client.portal_password_set",
                 target_type="client", target_id=cid)
    return {"ok": True, "signed_out_everywhere": True,
            "note": ("Every open portal session for this business has ended. "
                     "Sign in again with the new password.")}


@router.get("/account/clients", tags=["billing"])
def account_clients(x_account_token: Optional[str] = Header(None)) -> dict:
    """The businesses this subscriber owns. Never anyone else's."""
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

    Ownership is checked against the account's own list, so one subscriber's
    token can never fetch another's report.
    """
    email = _owned(cid, x_account_token)
    return business_report_pdf(cid, email)


def business_report_pdf(cid: str, email: str) -> Response:
    """The PDF report for one business, recorded against the subscriber who
    downloaded it. Callers check ownership first; shared with api/mine.py."""
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

    Public on purpose: a score produced by the same code customers are buying
    can be checked by anyone in seconds. Published as measured - if Titan's own
    site regresses, this number drops in public.
    """
    from ..engines import self_seo
    return self_seo.report()


@router.get("/structured-data", tags=["billing"])
def structured_data() -> dict:
    """JSON-LD for the product, with offers generated from the real plan table so
    a marked-up price can't drift from what's charged.
    """
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
        # 429 with the reason and a retry time, not a bare refusal - same as the plan
        # quotas.
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
    # attacker can't lock a real customer out of their own account.
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)
    token = billing.authenticate(req.email, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    # Coming back after signup is the difference between interest and use, and
    # nothing else records it, so it's recorded here.
    from ..core import analytics
    analytics.record(req.email, analytics.SIGNED_IN)
    return {"token": token, "account": billing.public(req.email)}


class PasswordChangeIn(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


@router.post("/account/password", tags=["billing"])
def account_change_password(req: PasswordChangeIn, request: Request,
                            x_account_token: Optional[str] = Header(None)) -> dict:
    """A subscriber changes their own password.

    The current password is required even though the caller has a valid
    session; otherwise a stolen token would be a permanent takeover (the thief
    changes the password and locks the owner out of their own billing).
    """
    from ..core import billing, ratelimit
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    # Same bucket as the login. This endpoint checks a password, so leaving it
    # unmetered would just move credential stuffing one door along.
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)

    out = billing.set_password(email, req.current_password, req.new_password)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error"))
    persistence.save(STORE)
    # Audited, without the password. audit.py redacts on the way in, so a field
    # named *password* can't reach the table even by mistake, and record() never
    # raises, so a failed audit write can't break the change.
    from ..core import audit
    audit.record(email, "account.password_changed",
                 target_type="account", target_id=email)
    # The caller's own token ended with the rest. Return a fresh one so changing a
    # password isn't also a logout.
    return {"ok": True, "signed_out_everywhere": True,
            "token": billing.authenticate(email, req.new_password)}


def _account_or_401(token) -> str:
    """The subscriber this request belongs to, or 401.

    One helper rather than the same lines at each CRM route, so the tenant
    filter can't go missing from one copy.
    """
    from ..core import billing
    email = billing.resolve(token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    return email


class CustomerLeadIn(BaseModel):
    name: str = Field(..., min_length=1)
    source: str = Field(default="manual")
    contact: str = Field(default="")
    note: str = Field(default="")
    website: str = Field(default="")


class CustomerLeadStatus(BaseModel):
    status: str = Field(...)


@router.get("/account/leads", tags=["crm"])
def customer_leads(x_account_token: Optional[str] = Header(None)) -> dict:
    """This customer's pipeline, and nothing else.

    Everything reads through crm.visible_to(), including the counts: a count
    over the unfiltered table would tell one customer how many leads another
    has.
    """
    from ..core import crm
    email = _account_or_401(x_account_token)
    items = sorted(crm.visible_to(STORE.leads, email),
                   key=lambda l: l.get("updated_at", ""), reverse=True)
    return {
        "items": items,
        "statuses": list(crm.STATUSES),
        "attention": crm.attention(items),
        **crm.stats(items),
    }


@router.post("/account/leads", tags=["crm"])
def customer_create_lead(req: CustomerLeadIn,
                         x_account_token: Optional[str] = Header(None)) -> dict:
    """File a lead against this account.

    The owner comes from the session, never the body; a caller who could name
    the owner could file into, and read from, someone else's pipeline.
    """
    from ..core import crm
    email = _account_or_401(x_account_token)
    lead = crm.new_lead(
        lead_id=STORE.new_id("lead"), account=email,
        name=req.name, source=req.source, contact=req.contact,
        note=req.note, website=req.website,
        created_at=now().isoformat(), updated_at=now().isoformat())
    STORE.leads[lead["id"]] = lead
    persistence.save(STORE)
    return lead


@router.post("/account/leads/{lead_id}/status", tags=["crm"])
def customer_lead_status(lead_id: str, req: CustomerLeadStatus,
                         x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import crm
    email = _account_or_401(x_account_token)
    status = (req.status or "").lower()
    if status not in crm.STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of {list(crm.STATUSES)}")
    try:
        lead = crm.require_owned(STORE.leads, lead_id, email)
    except crm.NotYours:
        # Identical to "no such lead", so other people's ids can't be enumerated.
        raise HTTPException(status_code=404, detail="Lead not found")
    lead["status"] = status
    lead["updated_at"] = now().isoformat()
    persistence.save(STORE)
    return lead


@router.delete("/account/leads/{lead_id}", tags=["crm"])
def customer_delete_lead(lead_id: str,
                         x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import crm
    email = _account_or_401(x_account_token)
    try:
        crm.require_owned(STORE.leads, lead_id, email)
    except crm.NotYours:
        raise HTTPException(status_code=404, detail="Lead not found")
    del STORE.leads[lead_id]
    persistence.save(STORE)
    return {"deleted": lead_id}


@router.get("/account/usage", tags=["billing"])
def account_usage(x_account_token: Optional[str] = Header(None)) -> dict:
    """What this customer has used this month, and what their plan allows.

    A limit nobody can see is just a surprise.

    `billed_to` is what the current request resolved to through the
    middleware. It's reported rather than assumed, because a request that
    binds nobody spends nobody's quota, and "you've used none" is different
    from "we weren't counting".
    """
    from ..core import billing, quota
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    acct = billing.public(email)
    return {
        "account": email,
        "plan": acct.get("plan"),
        "usage": acct.get("usage"),
        "limits": acct.get("limits"),
        "period_start": acct.get("period_start"),
        # Shows the meter is actually pointed at this request.
        "billed_to": quota.current() or None,
        "note": ("A limit of -1 means unlimited. Usage resets at the start of "
                 "each billing period. Work Titan does for itself — the "
                 "heartbeat, the self-audit, the public demo — is charged to "
                 "nobody and is not counted here."),
    }


@router.post("/account/logout", tags=["billing"])
def account_logout(x_account_token: Optional[str] = Header(None)) -> dict:
    """End this session."""
    from ..core import billing
    if not billing.resolve(x_account_token or ""):
        raise HTTPException(status_code=401, detail="Sign in first")
    ended = billing.sign_out(x_account_token or "")
    persistence.save(STORE)
    return {"ok": bool(ended)}


@router.post("/me/password", tags=["auth"])
def founder_change_password(req: PasswordChangeIn, request: Request) -> dict:
    """The founder changes their own password.

    Only available once the login runs on real accounts. Under the environment
    gate there's no stored password to change (the credential is a Space
    variable), and reporting success would be wrong.

    Founder only for now: this path sits behind the middleware in main.py,
    which requires role == founder, so a member with a valid session can't
    reach it. Members will need their own endpoint.
    """
    from ..core import identity, ratelimit
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    user = identity.resolve(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail=("Sign in with a real account first. The environment gate "
                    "has no stored password to change."))
    verdict = ratelimit.check("login", ratelimit.identity_for(request))
    if not verdict["allowed"]:
        raise HTTPException(status_code=429, detail=verdict)

    out = identity.change_password(user["email"], req.current_password,
                                   req.new_password)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error"))
    from ..core import audit
    audit.record(user["email"], "identity.password_changed",
                 target_type="user", target_id=user["email"])
    return {"ok": True, "signed_out_everywhere": True,
            "token": identity.authenticate(user["email"], req.new_password)}


@router.get("/account", tags=["billing"])
def account_me(x_account_token: Optional[str] = Header(None)) -> dict:
    from ..core import billing
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return billing.public(email)


@router.post("/webhooks/billing", tags=["billing"])
async def billing_webhook(request: Request) -> dict:
    """Paddle notifies Titan that a subscription started, renewed, lapsed or
    ended. Unauthenticated by design - Paddle holds no Titan token - so the
    HMAC signature is the authentication, and without a secret nothing is
    accepted.
    """
    import json as _json

    from ..core import billing
    if not os.getenv("PADDLE_WEBHOOK_SECRET", "").strip():
        raise HTTPException(status_code=503, detail=(
            "PADDLE_WEBHOOK_SECRET is not set. Copy the secret key of the "
            "notification destination in Paddle > Developer tools > "
            "Notifications into the Space secrets, then restart."))
    raw = await request.body()
    if not billing.verify_paddle_signature(
            raw, request.headers.get("paddle-signature", "")):
        raise HTTPException(status_code=401, detail="Invalid Paddle-Signature.")
    try:
        event = _json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not JSON.")
    return billing.apply_paddle_event(event if isinstance(event, dict) else {})


@router.post("/checkout/{plan_key}", tags=["billing"])
def checkout(plan_key: str,
             x_account_token: Optional[str] = Header(None)) -> dict:
    """Where the customer goes to approve a subscription.

    Titan never handles a card number or completes a payment on anyone's
    behalf; this returns an approval target the customer opens themselves.
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
# Founder-only: `/api/founder` is in demo_data._SENSITIVE_PREFIXES, so a guest
# token is refused by the middleware rather than served a sample. Subscriber
# tokens never reach here - they use X-Account-Token, which this route doesn't
# accept.

@router.get("/founder/analytics", tags=["executive"])
def founder_analytics(days: int = Query(default=30, ge=1, le=365),
                      recent: int = Query(default=40, ge=1, le=200)) -> dict:
    """Who signed up, what they are on, and what they actually did with it."""
    from ..core import analytics
    return analytics.report(days=days, recent=recent)


@router.get("/founder/accounts", tags=["executive"])
def founder_list_accounts() -> dict:
    """Every customer, with the plan and status the founder acts on.

    The read side of `POST /api/founder/accounts`. It serves the same rows as
    the funnel (`analytics.accounts_snapshot`), so the customers screen and the
    funnel can't disagree about someone's plan.

    Founder-only: `/api/founder` is in `demo_data._SENSITIVE_PREFIXES`, so a
    demo visitor is refused rather than served a sample. Every row is a real
    person's email address.
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
        # Read from the plan catalogue billing enforces, so the form can't offer a
        # plan the POST would refuse.
        "plans": [{"key": k, "name": billing.PLANS[k].name,
                   "price_usd": billing.PLANS[k].price_usd}
                  for k in billing.ORDER],
        "processor": billing.processor_name(),
        "billable": billing.configured(),
        # These accounts are only as durable as the state file, and the screen that
        # creates them should say so.
        "storage_warning": analytics.storage_warning(),
    }


class GrantIn(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(default="", min_length=0)
    plan: str = Field(default="enterprise")
    note: str = Field(default="")
    # Optional business details. Without business_name this behaves as before;
    # with it, the account and the business are created together.
    business_name: str = Field(default="")
    website: str = Field(default="")
    industry: str = Field(default="")
    city: str = Field(default="")
    country: str = Field(default="")


@router.post("/founder/accounts", tags=["executive"])
def founder_create_account(req: GrantIn) -> dict:
    """Create a subscriber on any plan, bypassing payment.

    For giving a free seat to a pilot customer, a friend or a case study.

    Founder-only: /api/founder is registered as sensitive, so a guest is
    refused outright, and a subscriber's X-Account-Token isn't accepted here.
    """
    from ..core import analytics, billing

    if req.plan not in billing.PLANS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown plan. One of {list(billing.PLANS)}.")

    # A generated password is stronger than one typed in a hurry, and nobody has
    # to invent a credential for someone else.
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

    # Step 2 of the create-customer flow, when a business was supplied.
    business = None
    business_error = None
    if req.business_name.strip():
        from ..core import clients as _registry
        import secrets as _s
        try:
            business = _registry.create_client(
                business_name=req.business_name.strip(),
                username=f"{req.email.split('@')[0][:24]}-{_s.token_hex(3)}",
                password=_s.token_urlsafe(16),
                website=req.website.strip(), industry=req.industry.strip(),
                city=req.city.strip(),
                country=req.country.strip() or "Pakistan")
            billing.attach_client(req.email, business["id"])
        except Exception as exc:                               # noqa: BLE001
            # The account already exists at this point. Report the failure rather than
            # roll the account back - the operator has already been shown its password.
            business_error = str(exc)[:200]
        else:
            # `account` was read before the attach; refresh it so the response shows the
            # business that was just attached.
            account = billing.public(req.email)

    # Every sensitive founder action leaves a record. The password isn't passed
    # here (and core/audit.py would redact it by key name anyway).
    from ..core import audit
    audit.record("founder", "customer.create", "account", req.email,
                 plan=req.plan, created=created, granted=True,
                 business=(business or {}).get("id", ""),
                 note=req.note[:120])

    persistence.save(STORE)
    return {
        "account": account,
        "created": created,
        "business": business,
        # Reported, not swallowed: the account exists either way, and an operator
        # who isn't told will assume the business was created.
        "business_error": business_error,
        # Shown once. It's stored only as a PBKDF2 hash, so nobody can read it back
        # later.
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
    """Move an existing subscriber to another plan.

    Nobody pays for a plan set here, so a paid plan becomes a granted seat,
    counted apart from paying customers and kept out of MRR. A customer who
    really pays through the processor keeps their subscription id: renewal and
    cancellation webhooks find the account by it.
    """
    from ..core import analytics, billing
    if req.plan not in billing.PLANS:
        raise HTTPException(status_code=400, detail="Unknown plan.")
    current = billing.subscription_of(email)
    if current is None:
        raise HTTPException(status_code=404, detail="No such account.")
    if current and not current.startswith("granted"):
        subscription = current
    elif req.plan == "free":
        subscription = ""
    else:
        subscription = f"granted:{req.note[:60]}" if req.note else "granted"
    account = billing.set_plan(email, req.plan, subscription_id=subscription,
                               status="active")
    granted = subscription.startswith("granted")
    analytics.record(email, analytics.CHANGED_PLAN, plan=req.plan, granted=granted)
    persistence.save(STORE)
    return {"account": account, "billed": False, "granted": granted}


@router.get("/founder/demo-workspace", tags=["executive"])
def founder_demo_workspace() -> dict:
    """What the background engines are working on, and when they last ran."""
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
    """Search the external-API catalogue. Metadata only - no calls are made.

    Public: it's a directory of publicly listed APIs with no customer data.
    Paginated because the catalogue has 1,675 entries.
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
    """What Titan can actually call, versus what it has catalogued.

    The dashboard uses this to show the real number of integrations next to
    the size of the catalogue.
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

    Candidates are ranked by catalogue facts (credential needed, HTTPS, CORS),
    not by an unmeasured quality score. Candidates aren't connections; see the
    note on the response.
    """
    from ..core import api_registry
    return api_registry.for_capability(intent, limit=limit)


@router.get("/founder/models", tags=["executive"])
def founder_models(free_only: bool = Query(default=False),
                   vision: bool = Query(default=False),
                   min_context: int = Query(default=0, ge=0),
                   limit: int = Query(default=40, ge=1, le=200)) -> dict:
    """Model capability and per-token price, from OpenRouter's live catalogue.

    Measured token counts times a published price is what makes a cost figure
    possible. Cost stays null wherever tokens weren't counted.
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
    Credentials and emails are redacted before a line is written - see
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
    """Take a snapshot now. It's verified by restoring it before it counts."""
    from ..core import backup
    out = backup.create(note=note)
    if not out["ok"]:
        raise HTTPException(status_code=500, detail=out["error"])
    return out


@router.post("/founder/backups/verify", tags=["executive"])
def founder_backup_verify(file: str = Query(...)) -> dict:
    """Open a backup and check it's a working database with rows in it."""
    from ..core import backup
    return backup.verify(file)


@router.get("/founder/rendering", tags=["executive"])
def founder_rendering() -> dict:
    """Whether Titan can see JavaScript-built pages.

    Many small-business sites are client-rendered. Without a browser renderer
    Titan detects them and marks its findings unreliable instead of scoring an
    empty shell.
    """
    from ..core import render
    return render.status()


@router.get("/founder/fix-cycle", tags=["executive"])
def founder_fix_cycle() -> dict:
    """What the 24/7 fix loop is responsible for, and what it has done.

    Under /api/founder because it names the client ids Titan holds keys to.
    """
    from ..engines import fix_cycle
    return fix_cycle.status()


@router.post("/founder/fix-cycle/run", tags=["executive"])
def founder_fix_cycle_run() -> dict:
    """Enqueue a re-audit of every connected site now.

    This only enqueues. Nothing in the cycle can change a customer's site
    without a named person's approval.
    """
    from ..engines import fix_cycle
    return fix_cycle.cycle(force=True) or {"skipped": True,
                                           "reason": "The cycle errored."}


@router.get("/founder/queue", tags=["executive"])
def founder_queue(limit: int = Query(default=50, ge=1, le=200),
                  kind: str = Query(default=""),
                  status: str = Query(default="")) -> dict:
    """The durable work queue: what's pending, what ran, and how long it took."""
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
    """How many people opened the site, measured in-process: no analytics
    vendor, no cookie, no consent banner, no stored IP address.
    """
    from ..core import traffic
    return traffic.report(days=days)


@router.get("/founder/seo-overview", tags=["executive"])
def founder_seo_overview() -> dict:
    """Titan's own SEO score next to every client site it manages.

    Titan audits itself with the same engine it sells, so its score is the one
    number a prospect can check. If a client scores above Titan itself, the
    founder should find out here first.
    """
    from ..engines import self_seo

    own = self_seo.report()
    rows, scored = seo_rows()
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
            # The full picture, not just the headline: "94/A" without the list of what
            # passed can't be checked.
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
            # An audit that failed to run isn't a passing audit.
            "error": own.get("error"),
            "note": own.get("note", ""),
        },
        "clients": rows,
        "client_average": round(sum(scored) / len(scored), 1) if scored else None,
        "unaudited": sum(1 for r in rows if not r["audited"]),
        "note": SEO_OVERVIEW_NOTE,
    }


SEO_OVERVIEW_NOTE = (
    "Client scores come from the last stored audit, not a fresh crawl — "
    "opening this screen must not fire a request at every client's website. "
    "Sites never audited show no score rather than a zero.")


def seo_rows(only=None) -> tuple:
    """One row per business from its last stored audit, worst score first,
    plus the scores that count towards the average. `only` limits it to those
    client ids - a subscriber's Executive tab (api/mine.py) passes theirs.
    """
    from ..engines import demo_workspace as _demo

    rows = []
    for rec in clients.all_clients():
        if only is not None and rec.get("id") not in only:
            continue
        cid = rec.get("id", "")
        audit = rec.get("last_audit") or {}
        is_demo = _demo.is_demo_client(rec)
        rows.append({
            "id": cid,
            "business_name": rec.get("business_name", ""),
            "website": rec.get("website", ""),
            "country": rec.get("country", ""),
            "industry": rec.get("industry", ""),
            # None, never 0: an unaudited site has no score, and a 0 next to a real 58
            # reads as "audited, and terrible".
            "score": audit.get("score"),
            "grade": audit.get("grade"),
            "findings": len(audit.get("findings", []) or []),
            "audited": bool(audit),
            "is_demo": is_demo,
        })

    # The client average describes the founder's real clients. Demo sites are
    # Titan's own pages and would flatter it.
    scored = [r["score"] for r in rows
              if isinstance(r.get("score"), (int, float)) and not r["is_demo"]]
    rows.sort(key=lambda r: (r["score"] is None, r["score"] or 0))
    return rows, scored


@router.get("/reflection", tags=["executive"])
def reflection_report(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """What Titan learned from finishing things, and what it changed as a result.

    The calibration_factor is applied to every later plan's runtime estimate,
    which makes this a feedback loop rather than a log.
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
    """Period report built only from what's in the ledger.

    Where there isn't enough history to project, the forecast reports
    `available: false` with the reason instead of a number; a projection from
    two data points would just get planned against.
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

    The order shown is the one the next completion will use, so a provider in
    last place is visibly last.
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
    """Structured event trace - the machine-readable twin of /api/feed."""
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
# Ranking that adapts to what the founder actually pursues. See
# core/learning.py.

class LearnIn(BaseModel):
    text: str = Field(..., description="Opportunity title + rationale")
    pursued: bool = Field(..., description="True if he acted on it")


@router.get("/learning", tags=["system"])
def learning_stats() -> dict:
    """What the model has learned, with cross-validated accuracy."""
    return learning.stats()


@router.post("/learning/record", tags=["system"])
def learning_record(payload: LearnIn) -> dict:
    """Record one real decision so the ranking improves."""
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

    Judges the known opportunities against the founder's situation (solo, no
    capital, needs revenue in weeks) and learns from those verdicts. Real
    execute/dismiss decisions override this later.
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


# ---- admin (founder only) --------------------------------------------------
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
    return run_client_audit(cid)


def run_client_audit(cid: str) -> dict:
    """Audit one business and file the result. Shared by the founder's route
    and a subscriber's (api/mine.py), which checks ownership and quota first."""
    rec = clients.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    result = client_seo.audit(rec.get("website", ""),
                              business_name=rec.get("business_name", ""),
                              city=rec.get("city", ""),
                              country=rec.get("country", ""),
                              industry=rec.get("industry", ""))
    # The crawl already happened. Record what it observed about the business,
    # tagged with where it was seen, so the CRM record carries its own source.
    # Never fatal to the audit.
    try:
        from ..core import evidence
        from ..engines import client_seo as _cs
        page, _err, _st = _cs._fetch(result.get("url") or rec.get("website", ""))
        if page:
            evidence.observe_from_page(cid, page)
        # The Impressum is a separate page and the strongest source for the
        # operator's legal name, address and VAT id.
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
        # Keep the last result so discovery can aggregate across clients without
        # re-crawling every site on every request.
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

    The client portal has this at /client/seo/schema behind a client token;
    this gives the dashboard's SEO view the same block.
    """
    return client_schema(cid)


def client_schema(cid: str) -> dict:
    """The JSON-LD block for one business. Shared with api/mine.py."""
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
    from ..core import billing
    cid = _client_from_header(x_client_token)
    # The plan name only - never the owning subscriber's email, which a business
    # managed by an agency shouldn't see.
    return {**clients.public(cid), "plan_name": billing.plan_for_client(cid)}


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
    """The ready-to-paste JSON-LD block - usually the single biggest win."""
    cid = _client_from_header(x_client_token)
    rec = clients.get(cid) or {}
    return {"json_ld": client_seo.suggested_schema(
        rec.get("business_name", ""), rec.get("city", ""),
        rec.get("website", ""), rec.get("industry", ""))}


# ---- client report + social plan -------------------------------------------

def _social_pack(rec: dict) -> dict:
    """Localised social plan for a client, from the brand playbook.

    The weekly plan and highlight names come from hospitality research (the
    dish, the kitchen, the room) and are withheld, with the reason, from a
    business the playbook wasn't researched for.

    The cadence, forbidden list and benchmarks aren't withheld: following
    count, post-to-follower ratio and discount-led posting apply to any brand.
    """
    lang = {"Germany": "de", "Austria": "de", "Switzerland": "de",
            "Italy": "it", "France": "fr"}.get(rec.get("country", ""), "en")
    industry = rec.get("industry", "")
    cover = brand_playbook.coverage(industry)
    return {
        "coverage": cover,
        "week": brand_playbook.weekly_plan(
            rec.get("business_name", ""), industry or "Restaurant",
            rec.get("city", ""), lang) if cover["covered"] else [],
        "highlights": (brand_playbook.highlights_plan(industry, lang)
                       if cover["covered"] else []),
        "pillars": brand_playbook.PILLARS if cover["covered"] else [],
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
    """The PDF the client downloads."""
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
    """What the news watch has found across every client."""
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
    """What Titan believes about this business, and why.

    Every field carries where it was observed. Fields with only weak evidence
    stay blank and show up as a suggestion for a person to settle - a
    confidently wrong fact is worse than an empty field.
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
    """A person settles a contested field. Recorded as manual, which outranks
    every machine observation from then on.
    """
    from ..core import evidence
    if not clients.get(cid):
        raise HTTPException(status_code=404, detail="Client not found")
    evidence.settle(cid, req.field, req.value)
    persistence.save(STORE)
    return evidence.record(cid)


@router.get("/evidence/sources", tags=["clients"])
def evidence_sources() -> dict:
    """The source ranking, and the rule that nothing accepts a self-reported
    confidence score.
    """
    from ..core import evidence
    return evidence.sources()


@router.get("/admin/watch", tags=["clients"])
def admin_watch() -> dict:
    """Monitoring status: what changed on client sites."""
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
# Every route here has its own credential - an identity session resolved
# through core/identity.py - which is why /api/org is in main._OPEN_PREFIXES
# next to /api/client/ and /api/account: open at the middleware, guarded at
# the endpoint.
#
# A legacy environment-gate token doesn't work here, by design: those sessions
# belong to a configured username, not a person, so there's nobody for a
# membership row to point at. Set TITAN_FOUNDER_EMAIL and the founder gets a
# real account like everyone else.
#
# The adversarial route walk in the tests calls every route under this prefix
# with a non-member's token and fails on any 200.

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

    Returns (user, role). Every refusal except "not signed in" is the same
    404, so a prober can't tell which organisation ids exist.
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
    # Keyed on the person, not the address: this endpoint is authenticated, and
    # people in one office behind one IP shouldn't throttle each other.
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
    """Give someone access. Administrator and above."""
    from ..core import identity, orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    person = identity.get(req.email)
    if not person:
        # Not the org gate's 404: the caller is a proven administrator here, so
        # telling them the address has no account is help, not disclosure.
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
        # Refused attempts are recorded too; repeated attempts to demote the last
        # owner are exactly the signal worth seeing.
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
    """Suspend or reactivate. Owners only - a suspended organisation refuses
    everyone, including its own administrators.
    """
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

    Administrator and above, since an audit trail says who did what and plain
    members shouldn't read that about colleagues. `stats.durable` says whether
    it survives the next rebuild (on the current free tier it doesn't).
    """
    from ..core import audit, orgs
    user, role = _org_role(org_id, authorization, orgs.ADMIN)
    return {"entries": audit.recent(limit=limit, target_id=org_id),
            "stats": audit.stats()}


@router.get("/founder/metrics", tags=["founder"])
def founder_metrics(days: int = 30) -> dict:
    """Executive metrics, each saying whether it was measured.

    Behind the founder token, and `/api/founder` is in
    `demo_data._SENSITIVE_PREFIXES`, so a demo visitor is refused - there's no
    demo version of revenue.

    Check `metrics.measured` before `metrics.value` on every field. A null
    value means nothing was measured, and isn't zero: with no payment
    processor connected, $0 MRR would look like a business result.
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
    """Every flag as it resolves, and why.

    `decided_by` is the useful field: "the plan layer said no" is actionable,
    "it's off for this customer" isn't.
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
    """What's connected, what it unlocks, and what it costs.

    Each row is answered by the module that owns it. A check that raises reads
    `unknown`, never `not_configured` - "go connect it" and "something's
    broken on our side" are different actions.
    """
    from ..core import integrations
    return integrations.summary()


@router.get("/founder/onboarding", tags=["founder"])
def founder_onboarding() -> dict:
    """Setup completion across every account, averaged only over accounts that
    could be scored.
    """
    from ..core import onboarding
    return onboarding.summary()


@router.get("/account/onboarding", tags=["billing"])
def account_onboarding(x_account_token: Optional[str] = Header(None)) -> dict:
    """The caller's own setup score. Scoped by the token, so there's no id to
    tamper with.
    """
    from ..core import billing, onboarding
    email = billing.resolve(x_account_token or "")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first")
    return onboarding.for_account(email)


@router.get("/founder/search", tags=["founder"])
def founder_search(q: str = "", limit: int = 20) -> dict:
    """Find a customer from anything you remember about them.

    Searches across tenants by design, which is what makes it useful to the
    operator and unsafe for customers. It lives under `/api/founder`, already
    in `demo_data._SENSITIVE_PREFIXES`. A per-tenant search should be its own
    function with an org filter, not a flag on this one.
    """
    from ..core import search
    return search.search(q, limit=limit)


@router.get("/founder/notifications", tags=["founder"])
def founder_notifications() -> dict:
    """Conditions that are true right now, worst first.

    Nothing is stored, so a notification disappears when its condition does.
    `not_emitted` lists what Titan doesn't notify about yet and the missing
    data, instead of inventing an alert.
    """
    from ..core import notifications
    return notifications.current()


@router.get("/founder/customers/{email}", tags=["executive"])
def founder_customer_360(email: str) -> dict:
    """Everything Titan knows about one customer, in one payload.

    Composed from the modules that own each part rather than recomputed, so
    this screen and the customers list can't disagree. A section that can't
    answer is returned as an explicit `unavailable` entry naming the source,
    since a blank panel and a broken one otherwise look the same.
    """
    from ..core import (analytics, audit, billing, identity, onboarding,
                        orgs, site_access)

    snap = analytics.accounts_snapshot()
    account = next((a for a in snap["accounts"] if a["email"] == email), None)
    if account is None:
        raise HTTPException(status_code=404, detail="No such customer")

    unavailable = []

    def _try(name, fn, default):
        try:
            return fn()
        except Exception as exc:                               # noqa: BLE001
            unavailable.append({"section": name, "error": str(exc)[:160]})
            return default

    # Businesses, each with whether Titan holds a credential for it.
    businesses = []
    for biz in account.get("businesses", []):
        state = _try(f"site_access:{biz['id']}",
                     lambda b=biz: site_access.status(b["id"]), None)
        businesses.append({**biz,
                           "connected": (state or {}).get("connected"),
                           "connection": state})

    # The person behind the account, if they have an identity record. Not every
    # billing account does yet.
    person = _try("identity", lambda: identity.get(email), None)
    memberships = (_try("orgs", lambda: orgs.orgs_for(person["id"]), [])
                   if person else [])

    return {
        "account": account,
        "person": person,
        "organisations": memberships,
        "businesses": businesses,
        "subscription_history": _try("subscription_history",
                                     lambda: billing.history(email), []),
        "onboarding": _try("onboarding",
                           lambda: onboarding.for_account(email), None),
        "activity": _try("audit", lambda: audit.recent(limit=25,
                                                       target_id=email), []),
        "unavailable": unavailable,
        "notes": {
            "revenue": ("This account's plan price is NOT revenue unless "
                        "`account.paying` is true. A granted seat shows "
                        "`granted` and was never charged."),
            "identity": ("`person` is null when this billing account has no "
                         "identity record. Billing has not been migrated onto "
                         "organisations yet, so the two are separate."),
        },
    }
