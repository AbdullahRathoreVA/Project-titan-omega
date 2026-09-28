"""Pydantic models for the API.

Static agent identity (domain/network.py) is merged with live runtime state
so the dashboard gets everything it needs in one shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .enums import (
    AgentStatus,
    AutonomyLevel,
    ConnectorKind,
    ConnectorStatus,
    Division,
    ExecutionStatus,
    Horizon,
    OpportunityStatus,
)


class AgentView(BaseModel):
    id: str
    name: str
    title: str
    division: Division
    is_head: bool
    autonomy: AutonomyLevel
    status: AgentStatus
    mission: str
    current_task: Optional[str] = None
    progress: float = 0.0
    goals: List[str] = Field(default_factory=list)
    kpis: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    tasks_completed: int = 0
    success_rate: float = 0.0
    impact_score: float = 0.0
    last_active: Optional[datetime] = None


class DivisionView(BaseModel):
    division: Division
    head: str
    agent_count: int
    active_agents: int
    health: float
    kpis: List[str]


class Opportunity(BaseModel):
    id: str
    title: str
    description: str
    source_agent: str
    category: str
    status: OpportunityStatus = OpportunityStatus.DISCOVERED
    expected_revenue: float = 0.0          # projected $ impact
    difficulty: float = 0.0                # 0-100, higher = harder
    risk: float = 0.0                      # 0-100, higher = riskier
    time_estimate_days: float = 0.0
    priority_score: float = 0.0            # composite, after learned re-rank
    # Score before the learned re-rank, plus a plain-language reason, so the
    # ranking can be checked rather than taken on trust.
    formula_score: Optional[float] = None
    rank_reason: Optional[str] = None
    execution_plan: List[str] = Field(default_factory=list)
    discovered_at: datetime


class ExecutionAction(BaseModel):
    id: str
    title: str
    description: str
    agent_id: str
    division: Division
    autonomy: AutonomyLevel
    status: ExecutionStatus
    reversible: bool = True
    requires_approval: bool = False
    opportunity_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    logs: List[str] = Field(default_factory=list)
    result: Optional[str] = None


class Connector(BaseModel):
    id: str
    name: str
    kind: ConnectorKind
    status: ConnectorStatus
    url: Optional[str] = None
    discovered_at: datetime
    last_sync: Optional[datetime] = None
    metrics: Dict[str, float] = Field(default_factory=dict)


class Deliverable(BaseModel):
    id: str
    title: str
    kind: str
    agent_id: str
    agent_name: str
    opportunity_id: Optional[str] = None
    content: str
    source: str  # "ai" (LLM-generated) | "template" (no key configured)
    created_at: datetime


class ScheduledPost(BaseModel):
    id: str
    content: str
    channels: List[str]
    image_url: Optional[str] = None
    agent_id: str
    scheduled_at: datetime
    status: str  # scheduled | queued | published | failed
    results: List[dict] = Field(default_factory=list)
    created_at: datetime


class FeedEvent(BaseModel):
    id: str
    timestamp: datetime
    actor: str            # agent id or "executive-core"
    kind: str             # e.g. "decision", "execution", "discovery", "alert"
    message: str
    severity: str = "info"  # info | success | warn | critical


class PlanItem(BaseModel):
    title: str
    division: Division
    owner_agent: str
    rationale: str
    target_metric: str
    priority: int


class StrategicPlan(BaseModel):
    horizon: Horizon
    generated_at: datetime
    headline: str
    items: List[PlanItem]


class Forecast(BaseModel):
    metric: str
    horizon: Horizon
    current: float
    projected: float
    confidence: float
    drivers: List[str] = Field(default_factory=list)


class EmpireStatus(BaseModel):
    """The single snapshot the command center renders on load."""

    health: float
    total_agents: int
    active_agents: int
    divisions: int
    open_opportunities: int
    pipeline_value: float
    actions_in_flight: int
    mrr: float
    traffic: int
    updated_at: datetime


class CommandRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Natural-language command")


class CommandResponse(BaseModel):
    understood: bool
    intent: str
    response: str
    routed_to: Optional[str] = None
    actions: List[str] = Field(default_factory=list)
