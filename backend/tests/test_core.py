"""Tests for the Executive Core, engines and API.

These run against a freshly seeded store so they're deterministic and require no
external services.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import executive, llm
from app.domain.enums import AutonomyLevel, Horizon
from app.domain.network import AGENT_NETWORK, division_summary
from app.engines import deliverables, execution, opportunity
from app.main import app
from app.store import STORE, seed


@pytest.fixture(autouse=True)
def fresh_store():
    seed(STORE)
    STORE.opportunities.clear()
    STORE.executions.clear()
    opportunity.discover(STORE)
    yield


# --- network --------------------------------------------------------------

def test_network_has_over_100_agents():
    assert len(AGENT_NETWORK) > 100


def test_every_division_has_exactly_one_head():
    heads = [a for a in AGENT_NETWORK if a.is_head]
    divisions = division_summary()
    assert len(heads) == len(divisions)
    # Head ids are unique per division.
    assert len({h.division for h in heads}) == len(heads)


def test_executive_head_is_fully_autonomous():
    ceo = next(a for a in AGENT_NETWORK if a.id == "executive-head")
    assert ceo.autonomy is AutonomyLevel.AUTONOMOUS


# --- opportunity engine ---------------------------------------------------

def test_scoring_rewards_high_revenue_low_risk():
    easy = opportunity.score(expected_revenue=90000, difficulty=10, risk=10, time_days=5)
    hard = opportunity.score(expected_revenue=90000, difficulty=90, risk=90, time_days=60)
    assert easy > hard
    assert 0 <= hard <= 100 and 0 <= easy <= 100


def test_opportunities_are_ranked_descending():
    ranked = opportunity.ranked(STORE)
    scores = [o["priority_score"] for o in ranked]
    assert scores == sorted(scores, reverse=True)


# --- execution layer ------------------------------------------------------

def test_suggest_agent_action_requires_approval():
    # A finance specialist has SUGGEST autonomy.
    action = execution.propose(
        title="Test action",
        description="...",
        agent_id="finance-pricing-strategist",
        store=STORE,
    )
    assert action["requires_approval"] is True
    assert action["status"].value == "pending"


def test_execute_agent_runs_immediately():
    action = execution.propose(
        title="Auto action",
        description="...",
        agent_id="marketing-head",  # EXECUTE autonomy
        store=STORE,
    )
    assert action["requires_approval"] is False
    assert action["status"].value == "running"


def test_full_lifecycle_and_audit_log():
    action = execution.propose("X", "...", "marketing-head", store=STORE)
    done = execution.complete(action["id"], "shipped", store=STORE)
    assert done["status"].value == "completed"
    assert any("Completed" in line for line in done["logs"])


def test_only_reversible_actions_revert():
    action = execution.propose("X", "...", "marketing-head", reversible=False, store=STORE)
    with pytest.raises(execution.ExecutionError):
        execution.revert(action["id"], store=STORE)


# --- executive core -------------------------------------------------------

def test_command_routing_classifies_intent():
    res = executive.route_command("boost our SEO traffic and keyword rankings", STORE)
    assert res["intent"] == "growth"
    assert res["routed_to"] == "growth-head"


def test_plan_scales_with_horizon():
    daily = executive.generate_plan(Horizon.DAILY, STORE)
    monthly = executive.generate_plan(Horizon.MONTHLY, STORE)
    assert len(daily["items"]) <= len(monthly["items"])


def test_forecast_projects_growth():
    f = executive.forecast("mrr", Horizon.MONTHLY, STORE)
    assert f["projected"] > f["current"]
    assert 0 < f["confidence"] <= 1


# --- API smoke ------------------------------------------------------------

def test_api_status_and_agents():
    client = TestClient(app)
    with client:
        assert client.get("/health").json()["status"] == "online"
        status = client.get("/api/status").json()
        assert status["total_agents"] > 100
        agents = client.get("/api/agents?heads_only=true").json()
        assert len(agents) == len(division_summary())


def test_api_command_endpoint():
    client = TestClient(app)
    with client:
        res = client.post("/api/command", json={"text": "find new revenue opportunities"})
        assert res.status_code == 200
        assert res.json()["understood"] is True


# --- deliverables (fallback / template mode) ------------------------------

def test_deliverable_from_opportunity_produces_artifact():
    top = opportunity.ranked(STORE)[0]
    d = deliverables.from_opportunity(top["id"], STORE)
    assert d["content"].strip()                      # a real artifact exists
    assert d["opportunity_id"] == top["id"]
    # Without a key configured, generation falls back to a template.
    if not llm.available():
        assert d["source"] == "template"


def test_draft_deliverable_defaults_unknown_kind():
    d = deliverables.generate("not_a_real_kind", "Launch a referral program", store=STORE)
    assert d["kind"] == "business_report"
    assert d["content"].strip()


def test_intelligence_endpoint_reports_mode():
    client = TestClient(app)
    with client:
        body = client.get("/api/intelligence").json()
        assert body["mode"] in ("claude", "free")
        assert body["claude_connected"] is llm.available()


def test_llm_complete_is_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.available() is False
    assert llm.complete("system", "prompt") is None
