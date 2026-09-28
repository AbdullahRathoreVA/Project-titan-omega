"""Opportunity engine: surfaces growth opportunities (niches, products, markets,
revenue streams, partnerships, automations) and scores them on one rubric.

Priority is a simple, inspectable composite: expected revenue discounted by
difficulty, risk and time to value.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from ..core import learning
from ..domain.enums import OpportunityStatus
from ..store import STORE, Store, now

# Candidate opportunities to "discover". In production these would come from
# live research; here they are a seed pool the engine scores and ranks.
_CANDIDATES = [
    {
        "title": "Career Mind AI: add resume-to-interview funnel",
        "description": "Users drop off after resume generation. Add a guided "
        "interview-prep flow to lift activation and retention.",
        "source_agent": "product-onboarding-optimizer",
        "category": "product",
        "expected_revenue": 36000,
        "difficulty": 45,
        "risk": 25,
        "time_estimate_days": 21,
        "execution_plan": [
            "Instrument funnel drop-off after resume export",
            "Design interview-prep flow (Product + UX agents)",
            "Ship behind a feature flag to 10% of users",
            "Measure activation lift, then roll out",
        ],
    },
    {
        "title": "Upwork: target underpriced 'AI resume' keyword cluster",
        "description": "High-impression, low-competition keywords identified with "
        "weak top-3 gigs. Re-optimize gig titles and tags to rank.",
        "source_agent": "intelligence-niche-scout",
        "category": "seo",
        "expected_revenue": 14000,
        "difficulty": 25,
        "risk": 15,
        "time_estimate_days": 7,
        "execution_plan": [
            "Pull keyword cluster with impression/competition scores",
            "Rewrite gig titles + tags (SEO + Copywriter agents)",
            "Refresh thumbnails and first 3 lines of description",
            "Track ranking + click-through for 14 days",
        ],
    },
    {
        "title": "Launch affiliate program for Career Mind AI",
        "description": "Recruit creators in the career-coaching niche to drive "
        "referral signups on revenue share.",
        "source_agent": "partnerships-affiliate-manager",
        "category": "partnership",
        "expected_revenue": 52000,
        "difficulty": 60,
        "risk": 35,
        "time_estimate_days": 30,
        "execution_plan": [
            "Define commission tiers (Finance agent)",
            "Build affiliate tracking + dashboards",
            "Source 50 candidate creators (Partnership Scout)",
            "Run onboarding sequence and measure CAC",
        ],
    },
    {
        "title": "Automate weekly investor/founder report",
        "description": "Replace manual reporting with an auto-generated empire "
        "digest covering revenue, traffic and agent performance.",
        "source_agent": "executive-board-reporting-analyst",
        "category": "automation",
        "expected_revenue": 8000,
        "difficulty": 20,
        "risk": 10,
        "time_estimate_days": 5,
        "execution_plan": [
            "Aggregate KPIs across connectors",
            "Draft narrative with Executive Core",
            "Schedule weekly delivery",
        ],
    },
    {
        "title": "New niche: AI-assisted LinkedIn profile optimization",
        "description": "Adjacent market with high intent and low tooling. Reuse "
        "Career Mind AI's resume engine for LinkedIn profiles.",
        "source_agent": "innovation-opportunity-scout",
        "category": "new_market",
        "expected_revenue": 88000,
        "difficulty": 70,
        "risk": 50,
        "time_estimate_days": 45,
        "execution_plan": [
            "Size the TAM (Market Sizer agent)",
            "Validate demand with a landing page test",
            "Adapt resume engine for LinkedIn schema",
            "Soft-launch to existing user base",
        ],
    },
    {
        "title": "Introduce annual pricing tier with discount",
        "description": "Improve cash flow and retention by offering a discounted "
        "annual plan to monthly subscribers.",
        "source_agent": "finance-pricing-strategist",
        "category": "pricing",
        "expected_revenue": 41000,
        "difficulty": 30,
        "risk": 20,
        "time_estimate_days": 10,
        "execution_plan": [
            "Model annual-vs-monthly LTV (Unit Economics Analyst)",
            "Set discount that protects margin",
            "Add tier to checkout",
            "Email monthly subscribers with upgrade offer",
        ],
    },
]


def score(expected_revenue: float, difficulty: float, risk: float, time_days: float) -> float:
    """Composite priority score in [0, 100].

    Reward is normalised against a $100k reference and discounted by difficulty,
    risk and time to value. The weights are explicit so they can be inspected and
    tuned (engines/evolution.py).
    """

    reward = min(expected_revenue / 100_000, 1.0)          # 0..1
    difficulty_penalty = (difficulty / 100) * 0.35
    risk_penalty = (risk / 100) * 0.25
    time_penalty = min(time_days / 60, 1.0) * 0.15

    raw = reward - difficulty_penalty - risk_penalty - time_penalty
    # Map roughly [-0.75, 1.0] -> [0, 100]
    return round(max(0.0, min(1.0, (raw + 0.75) / 1.75)) * 100, 1)


def discover(store: Store = STORE) -> List[dict]:
    """Materialize and score the candidate opportunities into the store."""

    created: List[dict] = []
    for cand in _CANDIDATES:
        oid = store.new_id("opp")
        formula = score(
            cand["expected_revenue"],
            cand["difficulty"],
            cand["risk"],
            cand["time_estimate_days"],
        )
        # Learned re-rank: the formula is fixed, but which kinds of opportunity get
        # pursued is learned. Until there are enough decisions this returns the
        # formula score unchanged and says so.
        text = f"{cand.get('title', '')} {cand.get('rationale', '')}"
        priority, why = learning.rerank(text, formula)

        opp = {
            "id": oid,
            **cand,
            "status": OpportunityStatus.SCORED,
            "priority_score": priority,
            "formula_score": formula,
            "rank_reason": why,
            "discovered_at": now(),
        }
        store.opportunities[oid] = opp
        created.append(opp)

    store.emit(
        "intelligence-head",
        "discovery",
        f"Opportunity Engine surfaced {len(created)} scored opportunities.",
        "success",
    )
    return created


def ranked(store: Store = STORE) -> List[dict]:
    """All opportunities, highest priority first."""
    return sorted(
        store.opportunities.values(),
        key=lambda o: o["priority_score"],
        reverse=True,
    )
