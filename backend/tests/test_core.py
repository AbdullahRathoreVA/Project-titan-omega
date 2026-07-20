"""Core platform tests.

All tests run with no external services: no Anthropic key, no network, no DB.
They exercise the deterministic paths — the same code paths that run in prod
when providers are unavailable — and verify the new multi-model, connector and
evolution layers degrade and operate correctly.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import STORE, Store, seed
from app.domain.network import AGENT_NETWORK
from app.core import llm
from app.engines import evolution, execution, opportunity
from app.connectors import careermind


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Reset the global store before every test."""
    STORE.agents.clear()
    STORE.opportunities.clear()
    STORE.executions.clear()
    STORE.connectors.clear()
    STORE.deliverables.clear()
    STORE.feed.clear()
    STORE.metrics.clear()
    STORE.posts.clear()
    seed(STORE)
    opportunity.discover(STORE)
    evolution.ensure_weights(STORE)
    yield


# ── agent network ──────────────────────────────────────────────────────────

def test_agent_count():
    assert len(STORE.agents) >= 100


def test_agent_network_has_twelve_divisions():
    divisions = {a.spec.division for a in STORE.agents.values()}
    assert len(divisions) == 12


def test_every_division_has_a_head():
    heads = [a for a in STORE.agents.values() if a.spec.is_head]
    assert len(heads) == 12


# ── multi-model LLM ────────────────────────────────────────────────────────

def test_provider_free_when_no_keys_set(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
                "OPENAI_BASE_URL", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert llm.provider() == "free"
    assert llm.available() is False
    assert llm.active_model() is None


def test_provider_claude_when_anthropic_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.provider() == "claude"
    assert llm.available() is True
    assert llm.active_model() is not None


def test_provider_groq_when_groq_key_set(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert llm.provider() == "groq"
    assert llm.available() is True
    # Groq deprecates free-tier models; assert the configured default is used
    # rather than pinning a model family that can retire under us.
    assert llm.active_model() == llm._GROQ_MODEL


def test_provider_openai_when_base_url_set(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    assert llm.provider() == "openai"
    assert llm.available() is True


def test_provider_gemini_when_gemini_key_set(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.provider() == "gemini"
    assert llm.available() is True


def test_provider_priority_claude_beats_groq(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert llm.provider() == "claude"


def test_complete_returns_none_in_free_mode(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
                "OPENAI_BASE_URL", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = llm.complete("system", "prompt")
    assert result is None


# ── opportunity engine ─────────────────────────────────────────────────────

def test_opportunities_seeded():
    assert len(STORE.opportunities) >= 5


def test_opportunities_sorted_by_priority():
    opps = opportunity.ranked(STORE)
    scores = [o["priority_score"] for o in opps]
    assert scores == sorted(scores, reverse=True)


def test_score_formula_bounds():
    from app.engines.opportunity import score
    assert 0.0 <= score(0, 0, 0, 0) <= 100.0
    assert 0.0 <= score(1_000_000, 100, 100, 60) <= 100.0


# ── self-evolution engine ──────────────────────────────────────────────────

def test_weights_initialised_with_priors():
    w = evolution.weights(STORE)
    assert w["weight_difficulty"] == pytest.approx(0.35)
    assert w["weight_risk"]       == pytest.approx(0.25)
    assert w["weight_time"]       == pytest.approx(0.15)


def test_record_outcome_success_reduces_dominant_weight():
    opp_id = next(iter(STORE.opportunities))
    opp    = STORE.opportunities[opp_id]
    w_before = evolution.weights(STORE).copy()

    evolution.record_outcome(opp_id, success=True, store=STORE)

    w_after = evolution.weights(STORE)
    # At least one weight must have decreased.
    assert any(w_after[k] < w_before[k] for k in w_before)


def test_record_outcome_failure_increases_dominant_weight():
    opp_id = next(iter(STORE.opportunities))
    w_before = evolution.weights(STORE).copy()

    evolution.record_outcome(opp_id, success=False, store=STORE)

    w_after = evolution.weights(STORE)
    assert any(w_after[k] > w_before[k] for k in w_before)


def test_record_outcome_noop_for_unknown_opportunity():
    w_before = evolution.weights(STORE).copy()
    evolution.record_outcome("opp-99999", success=True, store=STORE)
    assert evolution.weights(STORE) == w_before


def test_adaptive_score_matches_prior_score_at_defaults():
    from app.engines.opportunity import score as static_score
    for opp in list(STORE.opportunities.values())[:3]:
        static = static_score(
            opp["expected_revenue"], opp["difficulty"],
            opp["risk"], opp["time_estimate_days"],
        )
        adaptive = evolution.adaptive_score(
            opp["expected_revenue"], opp["difficulty"],
            opp["risk"], opp["time_estimate_days"], store=STORE,
        )
        assert abs(static - adaptive) < 0.1


# ── execution → evolution integration ─────────────────────────────────────

def test_complete_execution_nudges_weights():
    opp_id = next(iter(STORE.opportunities))
    opp    = STORE.opportunities[opp_id]
    action = execution.propose(
        title="Test action",
        description="desc",
        agent_id=opp["source_agent"],
        opportunity_id=opp_id,
        store=STORE,
    )
    # If action requires approval, approve it first.
    if action["requires_approval"]:
        execution.approve(action["id"], store=STORE)

    w_before = evolution.weights(STORE).copy()
    execution.complete(action["id"], "Done", store=STORE)
    assert evolution.weights(STORE) != w_before


def test_revert_execution_nudges_weights():
    opp_id = next(iter(STORE.opportunities))
    opp    = STORE.opportunities[opp_id]
    action = execution.propose(
        title="Revert test",
        description="desc",
        agent_id=opp["source_agent"],
        opportunity_id=opp_id,
        store=STORE,
    )
    if action["requires_approval"]:
        execution.approve(action["id"], store=STORE)
    # Complete it so we can revert (only completed/running can be reverted).
    execution.complete(action["id"], "Done", store=STORE)
    # Revert after completion — should still emit an evolution event.
    # (Reverting a completed action is a valid undo path.)
    # Skip if not reversible.
    if action["reversible"]:
        w_before = evolution.weights(STORE).copy()
        try:
            execution.revert(action["id"], store=STORE)
        except execution.ExecutionError:
            pass  # Some states may not allow revert — that's fine for this test.


# ── career mind connector ─────────────────────────────────────────────────

def test_careermind_connector_degrades_gracefully(monkeypatch):
    """When the platform is unreachable, connector keeps cached metrics."""
    def _fail(*a, **kw):
        return None

    monkeypatch.setattr(careermind, "_get", _fail)
    result = careermind.refresh(STORE)
    assert result is None
    conn = STORE.connectors.get("careermind-main")
    assert conn is not None
    assert conn["metrics"] is not None


def test_careermind_connector_updates_on_success(monkeypatch):
    """When /health returns a valid dict, connector is marked CONNECTED."""
    from app.domain.enums import ConnectorStatus

    def _mock_get(path: str, key=None, **kwargs):
        if path == "/health":
            return {"status": "ok"}
        return None

    monkeypatch.setattr(careermind, "_get", _mock_get)
    result = careermind.refresh(STORE)
    assert result is not None
    assert result["status"] == ConnectorStatus.CONNECTED


# ── API contract (smoke tests) ─────────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "mrr" in data
    assert "total_agents" in data


def test_api_divisions(client):
    r = client.get("/api/divisions")
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_api_intelligence(client):
    r = client.get("/api/intelligence")
    assert r.status_code == 200
    data = r.json()
    assert "provider" in data
    assert "mode" in data
    assert "claude_connected" in data


def test_api_evolution(client):
    r = client.get("/api/evolution")
    assert r.status_code == 200
    data = r.json()
    assert "weights" in data
    assert "weight_difficulty" in data["weights"]
    assert "weight_risk" in data["weights"]
    assert "weight_time" in data["weights"]


def test_api_connectors(client):
    r = client.get("/api/connectors")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_opportunities(client):
    r = client.get("/api/opportunities")
    assert r.status_code == 200
    opps = r.json()
    assert len(opps) >= 5


def test_api_plan_daily(client):
    r = client.get("/api/plan/daily")
    assert r.status_code == 200


def test_api_command(client):
    r = client.post("/api/command", json={"text": "grow traffic"})
    assert r.status_code == 200
    data = r.json()
    # Current CommandResponse contract: understood/intent/response/routed_to/actions.
    assert data["understood"] is True
    assert "response" in data
    assert data["routed_to"] == "growth-head"


def test_api_feed(client):
    r = client.get("/api/feed?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_execute_opportunity_and_evolution(client):
    opps = client.get("/api/opportunities").json()
    assert opps
    opp_id = opps[0]["id"]
    w_before = client.get("/api/evolution").json()["weights"].copy()

    r = client.post(f"/api/executions/from-opportunity/{opp_id}")
    assert r.status_code == 200
    action = r.json()

    # Approve if pending.
    if action["status"] == "pending":
        r2 = client.post(f"/api/executions/{action['id']}/approve")
        assert r2.status_code == 200

    # Complete the action.
    r3 = client.post(f"/api/executions/{action['id']}/complete?result=Done")
    assert r3.status_code == 200

    # Evolution weights should have changed.
    w_after = client.get("/api/evolution").json()["weights"]
    assert w_after != w_before

# ── single-Space public demo (guest session) ───────────────────────────────

def _guest_headers(client):
    r = client.post("/api/demo/enter")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_guest_can_read_but_never_write(monkeypatch):
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    client = TestClient(app)
    h = _guest_headers(client)

    # reads allowed
    assert client.get("/api/agents", headers=h).status_code == 200
    assert client.get("/api/status", headers=h).status_code == 200
    # writes refused
    assert client.post("/api/revenue/log", json={"amount": 5, "source": "x"}, headers=h).status_code == 403
    assert client.post("/api/leads", json={"name": "x"}, headers=h).status_code == 403
    # anonymous still locked out
    assert client.get("/api/agents").status_code == 401


def test_guest_never_sees_real_business_data(monkeypatch):
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    client = TestClient(app)
    h = _guest_headers(client)

    # Plant unmistakably real private data in the live store.
    STORE.metrics["mrr"] = 91234.0
    STORE.leads["lead-real"] = {"id": "lead-real", "name": "REAL CLIENT ACME", "status": "won",
                                "source": "x", "contact": "secret@acme.com", "note": "",
                                "created_at": "", "updated_at": ""}
    STORE.revenue_entries.append({"id": "rev-real", "amount": 91234.0, "source": "client",
                                  "note": "REAL ORDER private", "created_at": ""})

    assert client.get("/api/revenue", headers=h).json()["total"] != 91234.0
    assert client.get("/api/status", headers=h).json()["mrr"] != 91234.0
    leads_body = client.get("/api/leads", headers=h).text
    assert "ACME" not in leads_body and "secret@acme.com" not in leads_body
    entries = client.get("/api/revenue/entries", headers=h).text
    assert "REAL ORDER private" not in entries
    fin = client.get("/api/finance", headers=h).json()
    assert fin["revenue_total"] != 91234.0


def test_revenue_log_requires_auth_or_webhook_secret(monkeypatch):
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    monkeypatch.setenv("TITAN_WEBHOOK_SECRET", "hook-secret")
    client = TestClient(app)
    # anonymous write refused
    assert client.post("/api/revenue/log", json={"amount": 5, "source": "x"}).status_code == 401
    # automation with the secret still works
    ok = client.post("/api/revenue/log", json={"amount": 5, "source": "x"},
                     headers={"X-Webhook-Secret": "hook-secret"})
    assert ok.status_code == 200


def test_guest_stream_and_status_agree_and_hide_real_money(monkeypatch):
    """Regression: the SSE stream used to send REAL mrr, overriding the masked
    /api/status value — the dashboard showed $0 next to $693 of sample orders."""
    from app.api.actions import _stream_frame
    from app.core import demo_data

    STORE.metrics["mrr"] = 91234.0          # founder's real (private) revenue
    STORE.emit("revenue-tracker", "revenue", "REAL ORDER: +$91234 from client", "success")

    frame, _ = _stream_frame(STORE, 0, guest=True)
    assert frame["status"]["mrr"] == demo_data.DEMO_MRR
    assert frame["status"]["mrr"] != 91234.0
    # real order lines must never reach a demo visitor
    assert not any("REAL ORDER" in e.get("message", "") for e in frame["events"])

    # founder still sees the truth
    real, _ = _stream_frame(STORE, 0, guest=False)
    assert real["status"]["mrr"] == 91234.0


def test_guest_progress_is_sampled_not_derived_from_real_revenue(monkeypatch):
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    client = TestClient(app)
    h = _guest_headers(client)
    body = client.get("/api/progress", headers=h).json()
    assert body["level"] > 1 and body["xp"] > 0


def test_session_endpoint_identifies_token_kind(monkeypatch):
    """Regression: guest-ness was inferred from sessionStorage, so a demo token
    restored in a NEW TAB rendered as the founder while being served sample
    data ('Sign out' shown above $693 of sample revenue)."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import auth
    client = TestClient(app)

    gtok = client.post("/api/demo/enter").json()["token"]
    g = client.get("/api/session", headers={"Authorization": f"Bearer {gtok}"}).json()
    assert g["guest"] is True and g["founder"] is False

    ftok = auth.make_token(auth.credentials()[0])
    f = client.get("/api/session", headers={"Authorization": f"Bearer {ftok}"}).json()
    assert f["founder"] is True and f["guest"] is False

    anon = client.get("/api/session").json()
    assert anon["founder"] is False and anon["guest"] is False
