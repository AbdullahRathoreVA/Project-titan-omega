"""HTTP API for the command center.

All routes are mounted under ``/api``. Responses use the pydantic schemas in
:mod:`domain.schemas` so the Next.js dashboard has a stable contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from pydantic import BaseModel, Field

from ..core import executive, llm
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
from ..engines import deliverables, execution, opportunity, publisher
from ..store import STORE, AgentRuntime

router = APIRouter(prefix="/api")


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


# --- opportunities --------------------------------------------------------

@router.get("/opportunities", response_model=List[Opportunity], tags=["opportunities"])
def list_opportunities() -> List[Opportunity]:
    return [Opportunity(**o) for o in opportunity.ranked(STORE)]


@router.post("/opportunities/scan", response_model=List[Opportunity], tags=["opportunities"])
def scan_opportunities() -> List[Opportunity]:
    """Re-run the Global Opportunity Engine."""
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
    """Re-sync live connectors (GitHub repos) on demand."""
    from ..connectors import github

    github.refresh(STORE)
    return [Connector(**c) for c in STORE.connectors.values()]


# --- deliverables ---------------------------------------------------------

class DraftRequest(BaseModel):
    kind: str = Field(..., description="e.g. outreach_email, seo_plan, growth_strategy")
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


# --- intelligence status --------------------------------------------------

@router.get("/intelligence", tags=["system"])
def intelligence_status() -> dict:
    """Tells the dashboard whether agents are thinking with Claude or in free mode."""
    return {
        "claude_connected": llm.available(),
        "model": llm.MODEL if llm.available() else None,
        "mode": "claude" if llm.available() else "free",
    }
