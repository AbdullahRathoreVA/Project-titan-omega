"""The Digital Employee Network.

This module is the source of truth for the empire's org chart: the autonomous
divisions and the 100+ specialized agents that staff them. Each division is led
by a C-suite or head agent and contains specialists. The roster is declared as
data and expanded into full :class:`AgentSpec` records at import time so the rest
of the platform (Executive Core, dashboard, APIs) can treat agents uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .enums import AutonomyLevel, Division


@dataclass(frozen=True)
class AgentSpec:
    """The static definition of a digital employee.

    Runtime state (status, current task, live KPI values) lives separately in the
    store; this is the identity and contract of the agent.
    """

    id: str
    name: str
    title: str
    division: Division
    is_head: bool
    autonomy: AutonomyLevel
    mission: str
    kpis: List[str]
    tools: List[str]
    goals: List[str] = field(default_factory=list)


# Default toolbelts by division. Agents inherit their division's tools; heads get
# orchestration tooling on top. These map onto the connectors/engines the agent
# is allowed to reach.
_DIVISION_TOOLS: Dict[Division, List[str]] = {
    Division.EXECUTIVE: ["planner", "forecaster", "resource_allocator", "agent_router"],
    Division.OPERATIONS: ["workflow_engine", "scheduler", "automation_builder"],
    Division.FINANCE: ["ledger", "revenue_model", "pricing_engine", "forecaster"],
    Division.MARKETING: ["content_studio", "campaign_scheduler", "seo_toolkit", "social_publisher"],
    Division.TECHNOLOGY: ["github_connector", "ci_monitor", "infra_scanner"],
    Division.PRODUCT: ["roadmap_planner", "ux_audit", "feature_tracker"],
    Division.REVENUE: ["crm", "outreach_engine", "lead_scorer", "deal_tracker"],
    Division.GROWTH: ["seo_toolkit", "analytics", "experiment_runner", "funnel_mapper"],
    Division.INTELLIGENCE: ["web_research", "trend_radar", "competitor_scanner", "vector_memory"],
    Division.CUSTOMER: ["support_inbox", "sentiment_analyzer", "retention_model"],
    Division.PARTNERSHIPS: ["crm", "outreach_engine", "affiliate_tracker"],
    Division.INNOVATION: ["idea_engine", "market_sizer", "prototype_planner"],
}


# Each entry: (division, head_title, [specialist_titles...]). The head is the
# division's lead agent (typically a C-suite role); specialists report to it.
_ROSTER: List[tuple] = [
    (
        Division.EXECUTIVE,
        "Chief Executive Officer",
        [
            "Chief of Staff",
            "Strategy Director",
            "Resource Allocation Officer",
            "Performance Monitor",
            "Risk & Governance Officer",
            "Board Reporting Analyst",
            "OKR Steward",
            "Decision Auditor",
        ],
    ),
    (
        Division.OPERATIONS,
        "Chief Operating Officer",
        [
            "Process Architect",
            "Automation Engineer",
            "Workflow Optimizer",
            "Task Orchestrator",
            "SLA Monitor",
            "Quality Assurance Lead",
            "Vendor Coordinator",
        ],
    ),
    (
        Division.FINANCE,
        "Chief Financial Officer",
        [
            "Revenue Forecaster",
            "Pricing Strategist",
            "Unit Economics Analyst",
            "Cash Flow Monitor",
            "Budget Allocator",
            "Subscription Analyst",
            "Financial Risk Analyst",
        ],
    ),
    (
        Division.MARKETING,
        "Chief Marketing Officer",
        [
            "Content Strategist",
            "Copywriter",
            "SEO Specialist",
            "Social Media Manager",
            "Email Marketer",
            "Brand Guardian",
            "Campaign Planner",
            "Creative Director",
            "PR & Outreach Lead",
            "Video Script Writer",
            "Ad Creative Tester",
        ],
    ),
    (
        Division.TECHNOLOGY,
        "Chief Technology Officer",
        [
            "Repository Monitor",
            "Code Health Analyst",
            "CI/CD Watcher",
            "Security Auditor",
            "Infrastructure Scout",
            "Reliability Engineer",
            "Tech Debt Analyst",
        ],
    ),
    (
        Division.PRODUCT,
        "Chief Product Officer",
        [
            "Roadmap Planner",
            "UX Analyst",
            "Feature Prioritizer",
            "User Research Lead",
            "Onboarding Optimizer",
            "Product Analytics Lead",
        ],
    ),
    (
        Division.REVENUE,
        "VP of Revenue",
        [
            "Lead Hunter",
            "Outreach Specialist",
            "Sales Closer",
            "Deal Qualifier",
            "Conversion Optimizer",
            "Pipeline Analyst",
            "Pricing Negotiator",
            "Upsell Strategist",
        ],
    ),
    (
        Division.GROWTH,
        "VP of Growth",
        [
            "Growth Hacker",
            "Funnel Analyst",
            "Experiment Designer",
            "Retention Specialist",
            "Acquisition Analyst",
            "Virality Engineer",
            "Landing Page Optimizer",
            "Referral Loop Designer",
            "Activation Specialist",
        ],
    ),
    (
        Division.INTELLIGENCE,
        "Chief Intelligence Officer",
        [
            "Market Researcher",
            "Trend Hunter",
            "Competitor Analyst",
            "Niche Scout",
            "Sentiment Analyst",
            "Signal Aggregator",
            "Forecast Analyst",
            "Knowledge Curator",
        ],
    ),
    (
        Division.CUSTOMER,
        "VP of Customer Success",
        [
            "Support Agent",
            "Churn Predictor",
            "Feedback Synthesizer",
            "Community Manager",
            "Success Coach",
            "Escalation Handler",
        ],
    ),
    (
        Division.PARTNERSHIPS,
        "VP of Business Development",
        [
            "Partnership Scout",
            "Affiliate Manager",
            "Alliance Negotiator",
            "Integration Broker",
            "Channel Developer",
            "Co-Marketing Lead",
            "Reseller Manager",
        ],
    ),
    (
        Division.INNOVATION,
        "Chief Innovation Officer",
        [
            "Idea Generator",
            "Opportunity Scout",
            "Market Sizer",
            "Prototype Planner",
            "Disruption Analyst",
            "R&D Coordinator",
        ],
    ),
]


# Default KPI sets keyed by division — what each division is measured on.
_DIVISION_KPIS: Dict[Division, List[str]] = {
    Division.EXECUTIVE: ["empire_health", "decision_quality", "goal_attainment"],
    Division.OPERATIONS: ["automation_rate", "cycle_time", "sla_compliance"],
    Division.FINANCE: ["mrr", "gross_margin", "forecast_accuracy"],
    Division.MARKETING: ["reach", "engagement_rate", "cac"],
    Division.TECHNOLOGY: ["uptime", "code_health", "deploy_frequency"],
    Division.PRODUCT: ["activation_rate", "feature_adoption", "nps"],
    Division.REVENUE: ["pipeline_value", "win_rate", "new_mrr"],
    Division.GROWTH: ["traffic", "conversion_rate", "retention"],
    Division.INTELLIGENCE: ["opportunities_found", "signal_precision", "coverage"],
    Division.CUSTOMER: ["csat", "churn_rate", "resolution_time"],
    Division.PARTNERSHIPS: ["partners_active", "partner_revenue", "deal_velocity"],
    Division.INNOVATION: ["ideas_validated", "experiments_shipped", "tam_discovered"],
}


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _build_network() -> List[AgentSpec]:
    agents: List[AgentSpec] = []
    for division, head_title, specialists in _ROSTER:
        div_tools = _DIVISION_TOOLS[division]
        kpis = _DIVISION_KPIS[division]

        # Division head — trusted with the highest autonomy and given routing tools.
        head_id = f"{division.value}-head"
        agents.append(
            AgentSpec(
                id=head_id,
                name=head_title,
                title=head_title,
                division=division,
                is_head=True,
                autonomy=AutonomyLevel.AUTONOMOUS
                if division is Division.EXECUTIVE
                else AutonomyLevel.EXECUTE,
                mission=f"Lead the {division.value} division and maximize its KPIs.",
                kpis=kpis,
                tools=div_tools + ["agent_router"],
            )
        )

        for title in specialists:
            agents.append(
                AgentSpec(
                    id=f"{division.value}-{_slug(title)}",
                    name=title,
                    title=title,
                    division=division,
                    is_head=False,
                    autonomy=AutonomyLevel.EXECUTE
                    if division in (Division.MARKETING, Division.GROWTH, Division.INTELLIGENCE)
                    else AutonomyLevel.SUGGEST,
                    mission=f"Own {title.lower()} outcomes for the {division.value} division.",
                    kpis=kpis,
                    tools=div_tools,
                )
            )
    return agents


# The full roster, materialized once at import.
AGENT_NETWORK: List[AgentSpec] = _build_network()
AGENTS_BY_ID: Dict[str, AgentSpec] = {a.id: a for a in AGENT_NETWORK}


def division_summary() -> Dict[str, int]:
    """Count of agents per division — used by the dashboard org map."""
    counts: Dict[str, int] = {}
    for agent in AGENT_NETWORK:
        counts[agent.division.value] = counts.get(agent.division.value, 0) + 1
    return counts
