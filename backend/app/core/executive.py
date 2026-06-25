"""Executive Intelligence Core — the AI CEO.

This is the brain that sits above the Digital Employee Network. It understands the
empire's state, allocates priorities, generates daily/weekly/monthly plans,
forecasts revenue and traffic, and routes natural-language commands to the right
division and agent.

The reasoning here is deterministic and rule-based so the foundation runs with no
external model dependency. The architecture is built so a Claude/Gemini/OpenAI
planner can be dropped in behind :func:`generate_plan` and :func:`route_command`
without changing callers (see README → "Wiring real models").
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from ..domain.enums import (
    AgentStatus,
    Division,
    Horizon,
    OpportunityStatus,
)
from ..domain.network import AGENTS_BY_ID, division_summary
from ..engines import opportunity
from ..store import STORE, Store, now


# --- Empire snapshot ------------------------------------------------------

def empire_status(store: Store = STORE) -> dict:
    agents = store.agents.values()
    active = sum(1 for a in agents if a.status is AgentStatus.WORKING)
    health = _empire_health(store)
    open_opps = sum(
        1
        for o in store.opportunities.values()
        if o["status"] not in (OpportunityStatus.REALIZED, OpportunityStatus.DISMISSED)
    )
    in_flight = sum(
        1
        for a in store.executions.values()
        if a["status"].value in ("running", "pending")
    )
    return {
        "health": health,
        "total_agents": len(store.agents),
        "active_agents": active,
        "divisions": len(division_summary()),
        "open_opportunities": open_opps,
        "pipeline_value": store.metrics.get("pipeline_value", 0.0),
        "actions_in_flight": in_flight,
        "mrr": store.metrics.get("mrr", 0.0),
        "traffic": int(store.metrics.get("traffic", 0.0)),
        "updated_at": now(),
    }


def _empire_health(store: Store) -> float:
    """A single 0-100 health index blending agent success and impact."""
    agents = list(store.agents.values())
    if not agents:
        return 0.0
    avg_success = sum(a.success_rate for a in agents) / len(agents)
    avg_impact = sum(a.impact_score for a in agents) / len(agents)
    blocked = sum(1 for a in agents if a.status is AgentStatus.BLOCKED)
    penalty = (blocked / len(agents)) * 15
    health = (avg_success * 100) * 0.5 + avg_impact * 0.5 - penalty
    return round(max(0.0, min(100.0, health)), 1)


def division_health(store: Store = STORE) -> List[dict]:
    out: List[dict] = []
    by_div: Dict[Division, list] = {}
    for runtime in store.agents.values():
        by_div.setdefault(runtime.spec.division, []).append(runtime)

    for division, runtimes in by_div.items():
        head = next((r for r in runtimes if r.spec.is_head), runtimes[0])
        active = sum(1 for r in runtimes if r.status is AgentStatus.WORKING)
        avg_impact = sum(r.impact_score for r in runtimes) / len(runtimes)
        out.append(
            {
                "division": division,
                "head": head.spec.name,
                "agent_count": len(runtimes),
                "active_agents": active,
                "health": round(avg_impact, 1),
                "kpis": head.spec.kpis,
            }
        )
    return sorted(out, key=lambda d: d["division"].value)


# --- Strategic planning ---------------------------------------------------

_HORIZON_HEADLINES = {
    Horizon.DAILY: "Today's highest-impact moves",
    Horizon.WEEKLY: "This week's growth agenda",
    Horizon.MONTHLY: "This month's empire-level objectives",
}


def generate_plan(horizon: Horizon, store: Store = STORE) -> dict:
    """Build a prioritized action plan for the given horizon.

    Strategy: take the top-ranked opportunities and translate each into a plan
    item owned by the agent that surfaced it (or its division head), ordered by
    priority. The number of items scales with the horizon.
    """

    opps = opportunity.ranked(store)
    limit = {Horizon.DAILY: 3, Horizon.WEEKLY: 5, Horizon.MONTHLY: 8}[horizon]

    items: List[dict] = []
    for rank, opp in enumerate(opps[:limit], start=1):
        owner = AGENTS_BY_ID.get(opp["source_agent"])
        owner_id = owner.id if owner else f"{opp.get('category', 'executive')}-head"
        division = owner.division if owner else Division.EXECUTIVE
        items.append(
            {
                "title": opp["title"],
                "division": division,
                "owner_agent": owner_id,
                "rationale": (
                    f"Priority {opp['priority_score']:.0f}/100 · "
                    f"~${opp['expected_revenue']:,.0f} expected · "
                    f"risk {opp['risk']:.0f} · {opp['time_estimate_days']:.0f}d"
                ),
                "target_metric": _category_metric(opp.get("category", "")),
                "priority": rank,
            }
        )

    store.emit(
        "executive-core",
        "decision",
        f"Generated {horizon.value} plan with {len(items)} prioritized objectives.",
        "success",
    )
    return {
        "horizon": horizon,
        "generated_at": now(),
        "headline": _HORIZON_HEADLINES[horizon],
        "items": items,
    }


def _category_metric(category: str) -> str:
    return {
        "product": "activation_rate",
        "seo": "traffic",
        "partnership": "partner_revenue",
        "automation": "automation_rate",
        "new_market": "tam_discovered",
        "pricing": "mrr",
    }.get(category, "empire_health")


# --- Forecasting ----------------------------------------------------------

_GROWTH_ASSUMPTIONS = {
    # metric: (monthly_growth_rate, confidence, drivers)
    "mrr": (0.18, 0.82, ["annual tier launch", "affiliate program", "conversion lift"]),
    "traffic": (0.22, 0.76, ["SEO keyword cluster", "content cadence", "referral loop"]),
    "pipeline_value": (0.15, 0.7, ["lead hunter throughput", "outreach automation"]),
    "customers": (0.16, 0.78, ["activation funnel", "retention program"]),
}


def forecast(metric: str, horizon: Horizon, store: Store = STORE) -> dict:
    current = store.metrics.get(metric)
    if current is None:
        raise KeyError(metric)
    rate, confidence, drivers = _GROWTH_ASSUMPTIONS.get(
        metric, (0.1, 0.6, ["baseline momentum"])
    )
    periods = {Horizon.DAILY: 1 / 30, Horizon.WEEKLY: 0.25, Horizon.MONTHLY: 1.0}[horizon]
    projected = current * ((1 + rate) ** periods)
    # Confidence decays with longer horizons.
    horizon_conf = confidence * {Horizon.DAILY: 1.0, Horizon.WEEKLY: 0.95, Horizon.MONTHLY: 0.85}[horizon]
    return {
        "metric": metric,
        "horizon": horizon,
        "current": round(current, 2),
        "projected": round(projected, 2),
        "confidence": round(horizon_conf, 2),
        "drivers": drivers,
    }


# --- Natural-language command routing -------------------------------------

# Intent keyword → (division, canned action verbs). The command center sends
# free text; the Core classifies intent and routes to a division head.
_INTENT_MAP = [
    (("revenue", "sales", "mrr", "money", "pipeline", "deal"), Division.REVENUE, "revenue"),
    (("seo", "traffic", "rank", "keyword", "growth", "funnel"), Division.GROWTH, "growth"),
    (("content", "marketing", "campaign", "social", "brand", "copy", "email"), Division.MARKETING, "marketing"),
    (("product", "feature", "roadmap", "ux", "onboarding"), Division.PRODUCT, "product"),
    (("competitor", "research", "trend", "market", "niche", "intel"), Division.INTELLIGENCE, "intelligence"),
    (("price", "pricing", "finance", "forecast", "budget", "margin"), Division.FINANCE, "finance"),
    (("support", "customer", "churn", "retention", "success"), Division.CUSTOMER, "customer"),
    (("partner", "affiliate", "alliance", "integration"), Division.PARTNERSHIPS, "partnerships"),
    (("repo", "code", "deploy", "ci", "security", "infra"), Division.TECHNOLOGY, "technology"),
    (("idea", "innovate", "opportunity", "new business"), Division.INNOVATION, "innovation"),
]


def route_command(text: str, store: Store = STORE) -> dict:
    """Classify a natural-language command and route it to a division head."""

    lowered = text.lower()
    matched: Optional[Division] = None
    intent = "general"
    for keywords, division, name in _INTENT_MAP:
        if any(k in lowered for k in keywords):
            matched = division
            intent = name
            break

    if matched is None:
        # Default to the Executive Core for strategy-level asks.
        store.emit("executive-core", "command", f'Command received: "{text}"', "info")
        return {
            "understood": True,
            "intent": "strategy",
            "response": (
                "Routed to the Executive Intelligence Core. I'll fold this into the "
                "next planning cycle and assign it to the right division."
            ),
            "routed_to": "executive-head",
            "actions": ["queued_for_planning"],
        }

    head_id = f"{matched.value}-head"
    head = AGENTS_BY_ID.get(head_id)
    head_name = head.name if head else matched.value
    store.emit(head_id, "command", f'{head_name} tasked: "{text}"', "info")
    return {
        "understood": True,
        "intent": intent,
        "response": (
            f"Understood. Tasking the {matched.value} division (lead: {head_name}). "
            f"The team will draft an execution plan and report progress to the feed."
        ),
        "routed_to": head_id,
        "actions": [f"dispatched_to:{head_id}"],
    }


# --- Heartbeat ------------------------------------------------------------

def heartbeat(store: Store = STORE) -> None:
    """One tick of autonomous life: rotate agent focus and emit a signal.

    Called by the background loop so the live feed and agent activity keep moving
    even with no operator input — the empire works 24/7.
    """

    rng = store._rng
    runtimes = list(store.agents.values())
    if not runtimes:
        return
    runtime = rng.choice(runtimes)
    runtime.last_active = now()
    if runtime.status is AgentStatus.IDLE and rng.random() < 0.6:
        runtime.status = AgentStatus.WORKING

    store.emit(
        runtime.spec.id,
        "activity",
        f"{runtime.spec.name}: {runtime.current_task or 'advancing objectives'}.",
        "info",
    )
