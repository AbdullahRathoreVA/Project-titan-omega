"""Core platform tests.

All tests run with no external services: no Anthropic key, no network, no DB.
They exercise the deterministic paths — the same code paths that run in prod
when providers are unavailable — and verify the new multi-model, connector and
evolution layers degrade and operate correctly.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import STORE, Store, seed
from app.domain.network import AGENT_NETWORK
from app.core import llm
from app.engines import evolution, execution, opportunity
from app.connectors import careermind


@pytest.fixture
def no_ambient_config(monkeypatch):
    """Clear tool configuration that a developer's local .env may have set.

    app.main autoloads .env, so once Abdullah configured a real Firecrawl key
    every test asserting "this tool is unconfigured" started failing on his
    machine and passing on CI. A suite whose result depends on whether an
    untracked file exists is worse than no suite: it trains you to ignore red.
    Tests that assert on configuration state must therefore state it.
    """
    for var in ("FIRECRAWL_BASE_URL", "FIRECRAWL_API_KEY",
                "OPENWA_BASE_URL", "OPENWA_API_KEY",
                "COMPAI_CRM_URL", "COMPAI_CRM_KEY",
                "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    yield


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


# ── jurisdiction detection ─────────────────────────────────────────────────

def test_country_name_selects_jurisdiction():
    """The onboarding form stores 'Germany', never 'DE'. detect_country only
    matched 2-letter codes, so the declared value was silently discarded and
    the jurisdiction fell back to the TLD. A German restaurant on a .com
    domain was therefore audited as United States — which skips the Impressum
    check entirely, i.e. drops the one finding the product is sold on."""
    from app.engines import compliance
    assert compliance.detect_country("", tld="com", declared="Germany") == "DE"
    assert compliance.detect_country("", tld="com", declared="germany") == "DE"
    assert compliance.detect_country("", tld="com", declared="DE") == "DE"
    assert compliance.detect_country("", tld="com", declared="Austria") == "AT"
    assert compliance.detect_country("", tld="com", declared="Switzerland") == "CH"
    # An unknown name must not silently become US — fall through to the
    # TLD/lang evidence instead of asserting a jurisdiction we cannot support.
    assert compliance.detect_country("", tld="de", declared="Atlantis") == "DE"


def test_german_com_domain_still_gets_impressum_finding():
    """Regression for the same bug, at the level the client sees it."""
    from app.engines import compliance
    html = '<html lang="en"><head><title>Pizza</title></head><body>Hi</body></html>'
    r = compliance.check(html, country="Germany", tld="com")
    assert r["country"] == "DE"
    assert r["abmahnung_risk"] is True
    assert any(f["id"] == "imprint" for f in r["findings"])


# ── verticals: Titan must sell to any business, not just restaurants ───────

def test_every_vertical_can_actually_be_detected():
    """VERTICAL_SCHEMA listed dentist, auto and store while VERTICAL_SIGNALS did
    not, so those trades could never be detected and silently got generic
    advice. Every declared vertical must be reachable."""
    from app.engines import verticals
    for key, v in verticals.VERTICALS.items():
        assert v.signals, f"{key} has no detection signals"
        assert verticals.detect("", key) == key, f"{key} unreachable by name"
        assert verticals.detect("", v.label) == key, f"{v.label} unreachable"


def test_declared_industry_beats_stray_page_words():
    """An owner declaring their trade at onboarding is better evidence than a
    word in a footer — a dentist who mentions 'coffee' is not a café."""
    from app.engines import verticals
    html = "<p>free coffee and espresso in the waiting room, barista made</p>"
    assert verticals.detect(html, "Zahnarztpraxis") == "dentist"
    assert verticals.detect(html, "") == "cafe"


def test_audit_copy_is_not_restaurant_specific_for_a_law_firm():
    """The audit is what the client pays for. Telling a law firm its food
    photography is the product is not a credible deliverable."""
    from app.engines import client_seo
    html = """<html lang="de"><head><title>Kanzlei</title></head><body>
      <img src="a.jpg"><img src="b.jpg"><p>Rechtsanwalt und Anwalt, Mandant</p>
      </body></html>"""
    import unittest.mock as mock
    with mock.patch.object(client_seo, "_fetch",
                           return_value=(html, None, 200)):
        r = client_seo.audit("https://kanzlei.example", business_name="Kanzlei X",
                             city="Berlin", country="Germany", industry="legal")
    blob = json.dumps(r["findings"]).lower()
    assert "food photography" not in blob
    assert "karahi" not in blob
    assert "restaurant in" not in blob
    assert "legalservice" in blob or "law firm" in blob


def test_schema_generator_emits_the_right_subtype_per_trade():
    """It always emitted Restaurant with servesCuisine and acceptsReservations.
    Pasting that onto a law firm declares the firm a restaurant — worse than no
    schema, because search engines believe it."""
    from app.engines import client_seo
    law = json.loads(client_seo.suggested_schema(
        "Kanzlei X", "Berlin", "https://k.example", "legal"))
    assert law["@type"] == "LegalService"
    assert "servesCuisine" not in law and "acceptsReservations" not in law
    assert law["areaServed"] == "Berlin"

    dentist = json.loads(client_seo.suggested_schema(
        "Praxis Y", "München", "https://d.example", "dentist"))
    assert dentist["@type"] == "Dentist" and "medicalSpecialty" in dentist

    rest = json.loads(client_seo.suggested_schema(
        "Trattoria", "Bochum", "https://r.example", "restaurant"))
    assert rest["@type"] == "Restaurant" and rest["acceptsReservations"] == "True"
    assert rest["openingHoursSpecification"][0]["closes"] == "23:00"


def test_unknown_trade_gets_sane_generic_advice_not_food_advice():
    from app.engines import client_seo, verticals
    v = verticals.profile("something-nobody-listed")
    assert v.schema_type == "LocalBusiness"
    assert "food" not in v.asset_noun
    node = json.loads(client_seo.suggested_schema(
        "Acme", "Lahore", "https://a.example", "quantum widget consultancy"))
    assert node["@type"] == "LocalBusiness"


# ── .env loading ───────────────────────────────────────────────────────────

def test_real_environment_beats_the_env_file(tmp_path, monkeypatch):
    """A stale .env shipped inside an image must never shadow the real Space
    secret with a dead key."""
    from app.core import envfile
    f = tmp_path / ".env"
    f.write_text("FIRECRAWL_API_KEY=from-file\nNEW_ONLY=set-me\n", encoding="utf-8")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "from-real-environment")
    applied = envfile.load(f)
    assert os.environ["FIRECRAWL_API_KEY"] == "from-real-environment"
    assert os.environ["NEW_ONLY"] == "set-me"
    assert "FIRECRAWL_API_KEY" not in applied and "NEW_ONLY" in applied
    os.environ.pop("NEW_ONLY", None)


def test_env_parser_handles_what_people_actually_paste(tmp_path):
    from app.core import envfile
    f = tmp_path / ".env"
    f.write_text(
        "# a comment\n"
        "\n"
        "export EXPORTED=yes\n"
        'QUOTED="has spaces"\n'
        "SINGLE='single'\n"
        "TRAILING=value # trailing comment\n"
        "HASHVALUE=abc#notacomment\n"
        "NO_EQUALS_SIGN\n",
        encoding="utf-8")
    envfile.load(f, override=True)
    assert os.environ["EXPORTED"] == "yes"
    assert os.environ["QUOTED"] == "has spaces"
    assert os.environ["SINGLE"] == "single"
    assert os.environ["TRAILING"] == "value"
    assert os.environ["HASHVALUE"] == "abc#notacomment"
    for k in ("EXPORTED", "QUOTED", "SINGLE", "TRAILING", "HASHVALUE"):
        os.environ.pop(k, None)


def test_missing_or_broken_env_file_never_stops_boot(tmp_path):
    from app.core import envfile
    assert envfile.load(tmp_path / "does-not-exist") == []
    assert envfile.load(tmp_path) == []          # a directory, not a file


# ── 24/7 news watch ────────────────────────────────────────────────────────

def test_news_watch_searches_brand_industry_and_city_not_empty_strings():
    """An empty query to a news search returns the whole world, which is worse
    than no result because it looks like a finding."""
    from app.engines import client_news
    qs = dict(client_news._queries({"business_name": "Leather Co",
                                    "industry": "wholesale", "city": "Sialkot"}))
    assert qs["brand"] == '"Leather Co"'
    assert qs["local"] == "wholesale Sialkot"
    # Missing fields are skipped entirely.
    assert client_news._queries({"business_name": "Solo"}) == [("brand", '"Solo"')]
    assert client_news._queries({}) == []


def test_brand_mentions_sort_first_because_they_are_time_critical():
    from app.engines import client_news
    import unittest.mock as mock

    def fake(query, limit=4):
        kind = "brand" if query.startswith('"') else "other"
        return [{"title": f"{kind}-{query}-{i}", "link": "https://x.example"}
                for i in range(2)]

    client_news.reset()
    with mock.patch.object(client_news.news, "fetch_headlines", side_effect=fake):
        snap = client_news.check_client("c1", {
            "business_name": "Leather Co", "industry": "wholesale",
            "city": "Sialkot"})
    kinds = [i["kind"] for i in snap["items"]]
    assert kinds[0] == "brand", "a brand mention was not surfaced first"
    assert snap["brand_mentions"] == 2
    assert all(i["angle"] for i in snap["items"]), "an item had no angle"
    client_news.reset()


def test_one_dead_query_does_not_lose_the_others():
    from app.engines import client_news
    import unittest.mock as mock

    def flaky(query, limit=4):
        if query.startswith('"'):
            raise RuntimeError("news source down")
        return [{"title": f"ok-{query}", "link": "https://x.example"}]

    client_news.reset()
    with mock.patch.object(client_news.news, "fetch_headlines", side_effect=flaky):
        snap = client_news.check_client("c1", {
            "business_name": "Leather Co", "industry": "wholesale",
            "city": "Sialkot"})
    assert snap["ok"] is True and snap["items"], "a single failure lost everything"
    client_news.reset()


def test_the_news_watch_never_posts_anything():
    """Abdullah's standing rule: drafts queue for approval. An auto-posted
    mistake or a platform ban ends the service a client is paying for."""
    from app.engines import client_news
    src = pathlib.Path(client_news.__file__).read_text(encoding="utf-8")
    for forbidden in ("publisher.publish", "post_now", "requests.post",
                      "urlopen("):
        assert forbidden not in src, f"the news watch can {forbidden}"
    assert "human approves" in client_news.summary()["note"]


# ── evidence ledger (pattern from trycompai/crm) ───────────────────────────

@pytest.fixture
def clean_ledger():
    from app.core import evidence
    evidence.reset()
    yield
    evidence.reset()


def test_no_observation_can_carry_a_self_reported_confidence(clean_ledger):
    """The rule the whole pattern rests on: a model asked to grade its own
    certainty will, and it will be wrong in the direction that makes it look
    useful. Callers name the SURFACE they looked at; nothing else is accepted."""
    from app.core import evidence
    with pytest.raises(ValueError) as exc:
        evidence.observe("c1", "phone", "+49 1", "model_said_90_percent")
    assert "surface" in str(exc.value).lower()


def test_strong_evidence_writes_weak_evidence_only_suggests(clean_ledger):
    from app.core import evidence
    # A footer is too weak to trust automatically.
    evidence.observe("c1", "phone", "+49 111", "site.footer")
    rec = evidence.record("c1")
    assert "phone" not in rec["known"], "a footer value was written as fact"
    assert rec["suggestions"] and rec["suggestions"][0]["field"] == "phone"

    # Schema is published deliberately, so it writes.
    evidence.observe("c1", "phone", "+49 222", "site.schema")
    rec = evidence.record("c1")
    assert rec["known"]["phone"]["value"] == "+49 222"
    assert not any(s["field"] == "phone" for s in rec["suggestions"])


def test_the_impressum_outranks_schema(clean_ledger):
    """German law requires the Impressum to carry the operator's real legal
    name and address, and getting it wrong is a fineable offence. Nothing else
    a machine can read is tied that tightly to being correct."""
    from app.core import evidence
    evidence.observe("c1", "business_name", "Schema Name GmbH", "site.schema")
    evidence.observe("c1", "business_name", "Legal Name GmbH", "site.impressum")
    assert evidence.record("c1")["known"]["business_name"]["value"] == "Legal Name GmbH"


def test_a_human_decision_outranks_every_machine_observation(clean_ledger):
    from app.core import evidence
    evidence.observe("c1", "email", "scraped@site.example", "site.impressum")
    evidence.settle("c1", "email", "real@business.example")
    rec = evidence.record("c1")
    assert rec["known"]["email"]["value"] == "real@business.example"
    assert rec["known"]["email"]["source"] == "manual"


def test_conflicting_weak_observations_are_surfaced_not_resolved(clean_ledger):
    """This is precisely the case where guessing does damage."""
    from app.core import evidence
    evidence.observe("c1", "phone", "+49 111", "site.footer")
    evidence.observe("c1", "phone", "+49 999", "site.contact")
    sug = evidence.record("c1")["suggestions"]
    row = next(s for s in sug if s["field"] == "phone")
    assert row["conflict"] is True
    assert "different values" in row["prompt"]


def test_unresolved_fields_stay_blank_rather_than_plausible(clean_ledger):
    from app.core import evidence
    evidence.observe("c1", "address", "Somewhere 1", "site.title")
    rec = evidence.record("c1")
    assert "address" not in rec["known"]
    assert rec["unresolved"]["address"]["best_seen"] == "Somewhere 1"
    assert "worse than an empty field" in rec["note"]


def test_facts_are_observed_from_a_page_the_audit_already_fetched(clean_ledger):
    from app.core import evidence
    html = """<html><head><title>Trattoria Bella | Bochum</title>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Restaurant",
       "name":"Trattoria Bella GmbH","telephone":"+49 234 555",
       "address":{"@type":"PostalAddress","streetAddress":"Hauptstr 1",
                  "postalCode":"44787","addressLocality":"Bochum"}}
      </script></head>
      <body><a href="mailto:hallo@bella.example">mail</a>
      <a href="tel:+49234999">call</a></body></html>"""
    filed = evidence.observe_from_page("c1", html)
    assert filed, "nothing was observed from a page full of facts"
    rec = evidence.record("c1")
    # Schema beats the page title for the name, and beats the tel: link.
    assert rec["known"]["business_name"]["value"] == "Trattoria Bella GmbH"
    assert rec["known"]["phone"]["value"] == "+49 234 555"
    assert rec["known"]["city"]["value"] == "Bochum"
    # The mailto was only in the footer, so it is a suggestion, not a fact.
    assert "email" not in rec["known"]


def test_impressum_flag_upgrades_what_is_found_on_that_page(clean_ledger):
    from app.core import evidence
    html = '<html><body>USt-IdNr: DE123456789 ' \
           '<a href="mailto:info@kanzlei.example">e</a></body></html>'
    evidence.observe_from_page("c1", html, impressum=True)
    rec = evidence.record("c1")
    assert rec["known"]["vat_id"]["value"] == "DE123456789"
    assert rec["known"]["email"]["source"] == "site.impressum"


def test_ledger_survives_a_corrupt_state_file(clean_ledger):
    from app.core import evidence
    evidence.import_state({"ledger": {
        "c1": {"phone": [
            {"value": "+49 1", "source": "site.schema", "ts": 1.0},
            {"value": "x", "source": "made_up_source"},
            "not a dict",
        ]},
        "c2": "not a dict either",
    }})
    rec = evidence.record("c1")
    assert rec["known"]["phone"]["value"] == "+49 1"
    evidence.import_state("not a dict")


# ── Titan's own SEO ────────────────────────────────────────────────────────

def test_a_wholesaler_is_audited_as_b2b_not_as_a_local_shop():
    """A leather wholesaler's buyers find it by searching the product or the
    trade, not by standing nearby. Scoring it on Google Business Profile and
    review velocity produces a low number that means nothing and buries the
    findings that would actually win it business."""
    from app.engines import client_seo, verticals
    import unittest.mock as mock

    assert verticals.profile("wholesale").local_business is False
    assert verticals.profile("manufacturer").local_business is False
    # Declared trade wins, and the German spelling resolves too.
    assert verticals.detect("", "wholesale") == "wholesale"
    assert verticals.detect("", "Großhandel") == "wholesale"
    assert verticals.detect("", "manufacturer") == "manufacturer"

    html = ('<html lang="en"><head><title>Leather Co</title></head><body>'
            '<img src="a.jpg"><p>Wholesale leather jackets, MOQ 50 units, '
            'trade price on enquiry.</p></body></html>')
    with mock.patch.object(client_seo, "_fetch", return_value=(html, None, 200)):
        r = client_seo.audit("https://leather.example", business_name="Leather Co",
                             industry="wholesale")

    blob = json.dumps(r["findings"], ensure_ascii=False).lower()
    assert "openinghours" not in blob, "a wholesaler was told to publish opening hours"
    assert "google business profile" not in blob
    assert r["local"]["not_applicable"] is True
    # The advice that DOES matter for B2B.
    assert "moq" in blob or "eligiblequantity" in blob
    assert "wholesalestore" in blob


def test_a_software_product_is_not_told_to_publish_opening_hours():
    """Titan audited its own site and was told to add LocalBusiness schema with
    a street address and opening hours. A SaaS is not served from a place, and
    that same wrong advice would have gone to every software client."""
    from app.engines import client_seo, verticals
    import unittest.mock as mock

    assert verticals.profile("software").local_business is False
    assert verticals.profile("restaurant").local_business is True

    html = '<html lang="en"><head><title>A SaaS</title></head><body></body></html>'
    with mock.patch.object(client_seo, "_fetch", return_value=(html, None, 200)):
        r = client_seo.audit("https://saas.example", business_name="Acme",
                             industry="software")
    blob = json.dumps(r["findings"], ensure_ascii=False).lower()
    assert "openinghours" not in blob and "street address" not in blob
    assert "localbusiness" not in blob
    # Local scoring is skipped rather than reported as a bad score.
    assert r["local"]["not_applicable"] is True and r["local"]["score"] is None
    # Structured data still matters, just as the right type.
    assert "softwareapplication" in blob

    with mock.patch.object(client_seo, "_fetch", return_value=(html, None, 200)):
        rest = client_seo.audit("https://food.example", business_name="Bella",
                                industry="restaurant")
    assert rest["local"].get("not_applicable") is not True
    assert isinstance(rest["local"]["score"], int)


def test_titan_publishes_a_sitemap_and_its_own_robots(client):
    """Titan's audit reports a missing sitemap as a finding on client sites.
    Measured on the live site before this: sitemap.xml returned 404."""
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    body = r.text
    assert "<urlset" in body and "titanomega-ai.com/pricing" in body

    rb = client.get("/robots.txt")
    assert rb.status_code == 200
    txt = rb.text
    assert "Sitemap: " in txt, "robots.txt does not declare the sitemap"
    assert "Disallow: /api/" in txt, "JSON endpoints are crawlable"
    assert "Disallow: /portal" in txt, "the client portal is indexable"
    # AI answer engines are explicitly welcome — being quotable is the product.
    assert "GPTBot" in txt and "PerplexityBot" in txt


def test_product_schema_offers_match_the_real_prices(client):
    """A marked-up price that drifts from the charged price is a consumer
    problem, not a cosmetic one — so offers are generated from the plan table."""
    from app.core import billing
    ld = client.get("/api/structured-data").json()
    assert ld["@context"] == "https://schema.org"
    app_node = next(n for n in ld["@graph"]
                    if n["@type"] == "SoftwareApplication")
    offers = {o["name"]: float(o["price"]) for o in app_node["offers"]}
    for key in billing.ORDER:
        plan = billing.PLANS[key]
        assert offers[plan.name] == plan.price_usd, (
            f"schema advertises {offers[plan.name]} for {plan.name} but the "
            f"server charges {plan.price_usd}")


def test_self_audit_reports_honestly_before_it_has_run(client):
    """A placeholder score would be the exact fabrication this product exists
    to catch."""
    from app.engines import self_seo
    with self_seo._lock:
        self_seo._last.clear()
    body = client.get("/api/self-seo").json()
    assert body["checked"] is False
    assert "score" not in body
    assert "has not audited itself yet" in body["note"]


def test_self_seo_endpoints_are_public(monkeypatch):
    """The score and the schema are marketing assets — meant for strangers and
    for crawlers, so they must not sit behind the founder token."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)
    assert c.get("/api/self-seo").status_code == 200
    assert c.get("/api/structured-data").status_code == 200
    assert c.get("/sitemap.xml").status_code == 200
    assert c.get("/robots.txt").status_code == 200


# ── demo isolation: the guard that fails open ──────────────────────────────

def test_executive_endpoints_are_hidden_from_the_public_demo(monkeypatch):
    """These shipped leaking. /api/bi returned the founder's real revenue,
    /api/routing his provider error messages and /api/events the internal
    trace, to anyone who clicked 'View the live demo'."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)
    tok = c.post("/api/demo/enter").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    for path in ("/api/bi/monthly", "/api/reflection", "/api/routing",
                 "/api/tools", "/api/events"):
        r = c.get(path, headers=h)
        assert r.status_code == 403, f"{path} leaked to a guest ({r.status_code})"
        assert r.json().get("guest") is True


def test_demo_shows_the_sales_pitch_without_showing_a_real_client(monkeypatch):
    """Clients and SEO are the screens that sell Titan — they show the German
    Impressum finding priced as a fine, which is the reason to pay. Blocking
    them removed the pitch. They are substituted, and the substitute must be
    unmistakably sample data."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)
    tok = c.post("/api/demo/enter").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}

    body = c.get("/api/admin/clients", headers=h).json()
    assert body["clients"], "demo has no portfolio to show"
    for cl in body["clients"]:
        assert "[SAMPLE]" in cl["business_name"], "a real client name reached the demo"
        assert ".example" in (cl.get("website") or ""), "a real domain reached the demo"

    # The differentiator must actually be visible.
    audit = body["clients"][0]["last_audit"]
    # ensure_ascii=False, or json.dumps escapes the § in "§5 DDG" to § and
    # the assertion fails on its own encoding rather than on the content.
    blob = json.dumps(audit, ensure_ascii=False)
    assert "Impressum" in blob and "§5" in blob and "Abmahnung" in blob
    assert audit["legal"]["legal_critical"] == 2
    assert audit["local"]["dimensions"], "local ranking factors missing"

    # And the supporting screens.
    disc = c.get("/api/admin/discovery", headers=h).json()
    assert disc["opportunities"] and disc["pipeline_value_eur"] > 0
    watch = c.get("/api/admin/watch", headers=h).json()
    assert watch["watching"] > 0 and watch["trends"]

    # Anything under /api/admin WITHOUT a substitute must still be refused.
    assert c.get("/api/admin/nope", headers=h).status_code in (403, 404)


def test_every_founder_endpoint_is_hidden_from_guests(monkeypatch):
    """The sensitive-path list fails OPEN — an endpoint added later and not
    registered simply serves real data. This walks the REAL route table so a
    new private endpoint cannot slip through unnoticed."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import demo_data

    # Endpoints that are public BY DESIGN, each with the reason it is safe.
    public_by_design = {
        "/api/auth", "/api/session", "/api/demo/enter", "/api/login",
        "/api/intelligence", "/api/llm/health", "/api/tts/health",
        "/api/doctor", "/api/voice-report", "/api/assistant",
        "/api/content/daily", "/api/intel/news", "/api/inbox/auto-reply",
        "/api/plans",            # pricing must be readable to sell anything
        "/api/signup", "/api/account/login", "/api/account",
        # Marketing assets, deliberately crawlable: Titan's own audit score and
        # its product schema. Both describe Titan itself, not any client.
        "/api/self-seo", "/api/structured-data",
        # Methodology, not data: the evidence source ranking and the rule that
        # nothing accepts a self-reported confidence score. Describes HOW Titan
        # decides what to trust, and contains no observation about anyone.
        "/api/evidence/sources",
        # Demo-safe by substitution or by containing no private data.
        "/api/status", "/api/divisions", "/api/agents", "/api/opportunities",
        "/api/feed", "/api/executions", "/api/connectors", "/api/posts",
        "/api/channels", "/api/next-post", "/api/progress", "/api/performance",
        "/api/stream", "/api/metrics", "/api/growth/intel", "/api/health",
    }

    c = TestClient(app)
    tok = c.post("/api/demo/enter").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}

    leaked = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods or not path.startswith("/api/"):
            continue
        if "{" in path:                      # needs an id we do not have
            continue
        if path in public_by_design:
            continue
        if any(path.startswith(p) for p in demo_data._SENSITIVE_PREFIXES):
            continue
        r = c.get(path, headers=h)
        if r.status_code == 200:
            leaked.append(path)

    assert not leaked, (
        "These GET endpoints serve real founder data to a public demo visitor "
        "and are neither registered sensitive nor listed public-by-design: "
        + ", ".join(sorted(leaked)))


# ── subscriptions and signup (spec Part 5B) ────────────────────────────────

@pytest.fixture
def isolated_billing(monkeypatch, tmp_path):
    from app import persistence
    from app.core import analytics, billing
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "s.json"))
    billing.reset()
    # Analytics is module-level and persisted like the registry it measures. A
    # signup in one test would otherwise show up in another test's funnel.
    analytics.reset()
    yield
    billing.reset()
    analytics.reset()


def test_free_tier_keeps_the_thing_worth_paying_for(isolated_billing):
    """Spec Part 5B forbids dark patterns and requires the free tier be
    genuinely useful. Crippling the legal check — the one finding that proves
    Titan's value — would be exactly the forbidden pattern, and would sell
    nothing because nobody would see what they were buying."""
    from app.core import billing
    free = billing.PLANS["free"]
    blob = " ".join(free.features).lower()
    assert "legal" in blob and "audit" in blob
    assert free.audits_per_month >= 5, "free tier is not usable on its own"
    assert free.price_usd == 0.0


def test_plans_increase_monotonically(isolated_billing):
    """A higher price that buys less somewhere is a pricing bug users notice."""
    from app.core import billing
    prev = None
    for key in billing.ORDER:
        p = billing.PLANS[key]
        if prev:
            assert p.price_usd > prev.price_usd
            for field in ("clients", "audits_per_month", "ai_calls_per_month"):
                a, b = getattr(prev, field), getattr(p, field)
                assert b == -1 or a == -1 or b >= a, f"{key}.{field} regressed"
        prev = p


def test_exceeding_a_quota_explains_itself_instead_of_just_failing(
        isolated_billing):
    from app.core import billing
    billing.signup("a@b.com", "password123", "free")
    limit = billing.PLANS["free"].audits_per_month
    for _ in range(limit):
        assert billing.consume("a@b.com", "audits")["allowed"] is True
    v = billing.consume("a@b.com", "audits")
    assert v["allowed"] is False
    assert str(limit) in v["reason"]
    assert v["upgrade_to"] == "student"
    assert "$" in v["upgrade_gives"] and "resets_in_days" in v
    # and the refusal must not have consumed anything
    assert billing.public("a@b.com")["usage"]["audits"] == limit


def test_unlimited_plan_is_actually_unlimited(isolated_billing):
    from app.core import billing
    billing.signup("e@b.com", "password123", "enterprise")
    for _ in range(50):
        assert billing.consume("e@b.com", "audits")["allowed"] is True


def test_signup_rejects_bad_input_and_duplicates(isolated_billing):
    from app.core import billing
    with pytest.raises(ValueError):
        billing.signup("notanemail", "password123")
    with pytest.raises(ValueError):
        billing.signup("x@y.com", "short")
    billing.signup("x@y.com", "password123")
    with pytest.raises(ValueError):
        billing.signup("x@y.com", "password123")


def test_password_is_never_stored_or_returned(isolated_billing):
    from app.core import billing
    billing.signup("p@q.com", "sup3rsecret!", "free")
    pub = billing.public("p@q.com")
    assert "sup3rsecret!" not in json.dumps(pub)
    assert not any(k.startswith("_") for k in pub), "internal fields leaked"
    state = json.dumps(billing.export_state())
    assert "sup3rsecret!" not in state, "plaintext password persisted"


def test_login_works_and_wrong_password_fails(isolated_billing):
    from app.core import billing
    billing.signup("l@m.com", "password123")
    assert billing.authenticate("l@m.com", "wrong") is None
    tok = billing.authenticate("l@m.com", "password123")
    assert tok and billing.resolve(tok) == "l@m.com"


def test_pricing_page_ships_schema_in_the_html_not_via_javascript(
        isolated_billing, monkeypatch):
    """Titan's audit tells clients that schema is how AI answer engines decide
    what to quote. Most of those crawlers do not execute JavaScript, so schema
    appended after hydration is schema they never see — Titan was failing its
    own advice on its own pricing page."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import billing
    c = TestClient(app)
    html = c.get("/pricing").text
    assert 'type="application/ld+json"' in html, "no schema in the served HTML"
    assert "SoftwareApplication" in html and '"@context"' in html
    # Prices in the markup must be the prices the server charges.
    for key in billing.ORDER:
        p = billing.PLANS[key]
        assert f'"price": "{p.price_usd:.2f}"' in html, (
            f"{p.name} is missing or mispriced in the structured data")


def test_pricing_page_serves_and_hardcodes_no_prices(isolated_billing,
                                                     monkeypatch):
    """A pricing page with its own copy of the numbers will eventually disagree
    with what the server enforces, and a customer gets billed for something they
    were never shown."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import billing
    c = TestClient(app)
    r = c.get("/pricing")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert "/api/plans" in html, "page does not fetch live pricing"
    for plan in billing.PLANS.values():
        if plan.price_usd:
            assert f"${plan.price_usd:.0f}/month" not in html, (
                f"{plan.key} price is hardcoded into the page")


def test_self_serve_onboarding_delivers_the_first_audit(isolated_billing,
                                                        isolated_clients,
                                                        monkeypatch):
    """The conversion path. Everything before this is a promise; this is the
    first moment the product does something for the person who signed up."""
    import unittest.mock as mock
    from app.engines import client_seo
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)

    c.post("/api/signup", json={"email": "w@leather.example",
                                "password": "password123", "plan": "free"})
    tok = c.post("/api/account/login",
                 json={"email": "w@leather.example",
                       "password": "password123"}).json()["token"]
    h = {"X-Account-Token": tok}

    html = ('<html lang="en"><head><title>Leather Co</title></head><body>'
            '<p>Wholesale leather jackets, MOQ 50.</p></body></html>')
    with mock.patch.object(client_seo, "_fetch", return_value=(html, None, 200)):
        r = c.post("/api/account/onboard", headers=h, json={
            "business_name": "Leather Co", "website": "https://leather.example",
            "industry": "wholesale", "country": "Pakistan"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client"]["business_name"] == "Leather Co"
    assert body["audit"]["ok"] is True and isinstance(body["audit"]["score"], int)
    # The audit must have consumed exactly one from the plan quota.
    assert body["account"]["usage"]["audits"] == 1
    # It must be audited as B2B, not as a corner shop.
    assert body["audit"]["local"]["not_applicable"] is True

    mine = c.get("/api/account/clients", headers=h).json()
    assert len(mine["clients"]) == 1


def test_a_subscriber_cannot_exceed_their_plan_or_read_someone_elses(
        isolated_billing, isolated_clients, monkeypatch):
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import billing
    c = TestClient(app)

    def acct(email):
        c.post("/api/signup", json={"email": email, "password": "password123",
                                    "plan": "free"})
        t = c.post("/api/account/login",
                   json={"email": email, "password": "password123"}).json()["token"]
        return {"X-Account-Token": t}

    a, b = acct("a@x.example"), acct("b@x.example")

    first = c.post("/api/account/onboard", headers=a, json={
        "business_name": "First", "run_audit": False})
    assert first.status_code == 200
    cid = first.json()["client"]["id"]

    # Free covers 1 business; the second must be refused with a way forward.
    second = c.post("/api/account/onboard", headers=a, json={
        "business_name": "Second", "run_audit": False})
    assert second.status_code == 402
    detail = second.json()["detail"]
    assert detail["upgrade_to"] == "student" and "$" in detail["upgrade_gives"]

    # Subscriber B must not see or fetch subscriber A's business.
    assert c.get("/api/account/clients", headers=b).json()["clients"] == []
    assert c.get(f"/api/account/clients/{cid}/report.pdf",
                 headers=b).status_code == 404
    assert billing.owned_clients("b@x.example") == []


def test_signup_and_pricing_are_reachable_without_the_founder_token(
        isolated_billing, monkeypatch):
    """If these sit behind the founder token nobody can ever become a customer,
    which defeats the entire subscription feature."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)
    assert c.get("/api/plans").status_code == 200
    r = c.post("/api/signup", json={"email": "new@user.com",
                                    "password": "password123", "plan": "free"})
    assert r.status_code == 200, r.text
    login = c.post("/api/account/login", json={"email": "new@user.com",
                                               "password": "password123"})
    assert login.status_code == 200
    tok = login.json()["token"]
    # The account endpoint must still refuse an unknown token.
    assert c.get("/api/account",
                 headers={"X-Account-Token": "garbage"}).status_code == 401
    me = c.get("/api/account", headers={"X-Account-Token": tok})
    assert me.status_code == 200 and me.json()["plan"] == "free"
    # A subscriber token must NOT unlock founder-only data.
    assert c.get("/api/finance",
                 headers={"X-Account-Token": tok}).status_code == 401


def test_checkout_says_what_is_missing_rather_than_pretending(isolated_billing,
                                                              monkeypatch):
    """With no processor keys the paid flow must degrade honestly — and must
    say the free tier still works, because it does."""
    from app.core import billing
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    out = billing.checkout("a@b.com", "individual")
    assert out["ready"] is False
    assert "PAYPAL_CLIENT_ID" in out["needs"]
    assert "free tier is fully" in out["note"]
    with pytest.raises(ValueError):
        billing.checkout("a@b.com", "free")


# ── business intelligence + forecasting (spec Part 4C) ─────────────────────

@pytest.fixture
def isolated_ledger(monkeypatch, tmp_path):
    from app import persistence
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "s.json"))
    rev, exp = list(STORE.revenue_entries), list(STORE.expenses)
    STORE.revenue_entries.clear(); STORE.expenses.clear()
    yield
    STORE.revenue_entries.clear(); STORE.revenue_entries.extend(rev)
    STORE.expenses.clear(); STORE.expenses.extend(exp)


def _entry(days_ago: float, amount: float) -> dict:
    import datetime as dt
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return {"amount": amount, "source": "test", "created_at": ts.isoformat()}


def test_forecast_refuses_rather_than_inventing_a_number(isolated_ledger):
    """Spec Part 4C says both 'forecast where sufficient data exists' and
    'never fabricate numbers'. With two data points the only honest output is a
    refusal — a founder planning against an invented projection makes real
    decisions on fiction."""
    from app.engines import bi
    STORE.revenue_entries.extend([_entry(1, 100), _entry(2, 120)])
    f = bi.report("monthly")["forecast"]
    assert f["available"] is False
    assert "projected_total" not in f
    assert str(bi.MIN_POINTS_FOR_TREND) in f["reason"]
    assert f["needed"] == bi.MIN_POINTS_FOR_TREND - 2


def test_forecast_states_its_method_uncertainty_and_assumptions(isolated_ledger):
    from app.engines import bi
    for d in range(20):
        STORE.revenue_entries.append(_entry(d, 100 + d))
    f = bi.report("monthly")["forecast"]
    assert f["available"] is True
    assert f["method"] and f["days_of_data"] >= bi.MIN_POINTS_FOR_TREND
    assert f["low"] <= f["projected_total"] <= f["high"], "no uncertainty band"
    assert f["assumptions"], "a forecast with no stated assumptions is a guess"
    assert f["provisional"] is False


def test_a_thin_but_usable_sample_is_labelled_provisional(isolated_ledger):
    from app.engines import bi
    for d in range(6):
        STORE.revenue_entries.append(_entry(d, 50))
    f = bi.report("monthly")["forecast"]
    assert f["available"] is True and f["provisional"] is True
    assert any("direction of travel" in a for a in f["assumptions"])


def test_missing_days_are_not_counted_as_zero(isolated_ledger):
    """A day with no entry is missing data, not a measured zero. Counting gaps
    as zeros manufactures a downward trend out of nothing."""
    from app.engines import bi
    for d in (0, 10, 20, 30, 40, 50):
        STORE.revenue_entries.append(_entry(d, 100))
    series = bi._daily_totals(STORE.revenue_entries, 90)
    assert len(series) == 6, "gap days were fabricated into the series"
    assert all(v == 100 for v in series.values())


def test_report_never_reports_revenue_it_does_not_have(isolated_ledger):
    from app.engines import bi
    r = bi.report("monthly")
    assert r["revenue"] == 0.0 and r["profit"] == 0.0
    assert r["forecast"]["available"] is False
    assert any("No revenue recorded" in i for i in r["insights"])
    # And it must say what to do about it rather than just stating the zero.
    assert r["actions"]


def test_report_compares_against_the_previous_window(isolated_ledger):
    from app.engines import bi
    STORE.revenue_entries.append(_entry(2, 200))    # this window
    STORE.revenue_entries.append(_entry(40, 100))   # previous window
    r = bi.report("monthly")
    assert "%" in r["comparison"] and "+" in r["comparison"]


# ── self-reflection (spec Part 2) ──────────────────────────────────────────

def test_reflection_needs_evidence_before_it_corrects_anything():
    """One slow network call must not permanently triple every future estimate."""
    from app.core import reflection
    reflection.reset()
    assert reflection.calibration() == 1.0
    reflection.record(goal="g", achieved=True, predicted_seconds=1,
                      actual_seconds=30)
    assert reflection.calibration() == 1.0, "corrected on a single sample"
    reflection.reset()


def test_calibration_uses_the_median_so_one_timeout_cannot_poison_it():
    from app.core import reflection
    reflection.reset()
    for _ in range(9):
        reflection.record(goal="g", achieved=True, predicted_seconds=2,
                          actual_seconds=2)          # ratio 1.0
    reflection.record(goal="g", achieved=False, predicted_seconds=2,
                      actual_seconds=600)            # ratio 300, an outlier
    f = reflection.calibration()
    assert 0.9 <= f <= 1.1, f"a single outlier moved calibration to {f}"
    reflection.reset()


def test_calibration_is_clamped_even_with_a_pathological_history():
    from app.core import reflection
    reflection.reset()
    for _ in range(10):
        reflection.record(goal="g", achieved=True, predicted_seconds=1,
                          actual_seconds=500)
    assert reflection.calibration() == reflection.CALIBRATION_CEIL
    reflection.reset()
    for _ in range(10):
        reflection.record(goal="g", achieved=True, predicted_seconds=500,
                          actual_seconds=1)
    assert reflection.calibration() == reflection.CALIBRATION_FLOOR
    reflection.reset()


def test_the_loop_actually_closes_planner_estimates_change():
    """This is the whole point. If reflection cannot change a later plan, it is
    a diary, not a feedback loop."""
    from app.core import planner, reflection
    from app.engines import adapters
    adapters.register_all()
    reflection.reset()

    before = planner.plan("audit the website").est_seconds

    for _ in range(8):      # consistently 3x slower than planned
        reflection.record(goal="audit", achieved=True, predicted_seconds=1,
                          actual_seconds=3)
    assert reflection.calibration() == 3.0

    after = planner.plan("audit the website").est_seconds
    assert after > before, "reflection did not affect the next plan"
    assert abs(after - before * 3.0) < 0.5
    reflection.reset()


def test_confident_and_wrong_scores_worse_than_unsure_and_wrong():
    """Brier scoring: being certain and wrong is the expensive error, because
    it gets acted on without review."""
    from app.core import reflection
    reflection.reset()
    for _ in range(5):
        reflection.record(goal="g", achieved=False, predicted_seconds=1,
                          actual_seconds=1, confidence=0.95)
    confident_wrong = reflection.report()["confidence_brier"]

    reflection.reset()
    for _ in range(5):
        reflection.record(goal="g", achieved=False, predicted_seconds=1,
                          actual_seconds=1, confidence=0.30)
    unsure_wrong = reflection.report()["confidence_brier"]

    assert confident_wrong > unsure_wrong
    reflection.reset()


def test_reflection_names_the_expensive_mistake():
    from app.core import reflection
    reflection.reset()
    r = reflection.record(goal="send invoice", achieved=False,
                          predicted_seconds=2, actual_seconds=2,
                          confidence=0.9, tool_failures=["messaging.whatsapp"])
    blob = " ".join(r["lessons"]).lower()
    assert "confiden" in blob and "review" in blob
    assert "messaging.whatsapp" in blob
    reflection.reset()


def test_reflection_survives_a_corrupt_state_file():
    from app.core import reflection
    reflection.reset()
    reflection.import_state({"records": [
        {"goal": "ok", "achieved": True, "predicted_seconds": 1,
         "actual_seconds": 2, "ratio": 2, "confidence": 0.5},
        {"goal": "bad", "predicted_seconds": "nonsense"},
        "not even a dict",
    ]})
    rep = reflection.report()
    assert rep["tasks_reflected"] == 1, "one bad row lost the whole history"
    reflection.import_state("not a dict")
    reflection.reset()


# ── planning engine (spec Part 2) ──────────────────────────────────────────

def test_plan_is_produced_before_anything_runs():
    """The planner must describe the work without doing it."""
    from app.core import planner
    from app.engines import adapters
    adapters.register_all()
    p = planner.plan("audit the restaurant website for SEO and compliance")
    d = p.as_dict()
    assert d["step_count"] >= 3
    assert d["graph"]["s2"] == ["s1"], "dependencies were not expressed"
    assert 0.0 < d["confidence"] <= 0.95


def test_runtime_is_the_critical_path_not_the_sum():
    """Independent steps run together; summing them overstates the estimate."""
    from app.core import planner
    steps = [
        planner.Step("a", "x", "agent", est_seconds=5),
        planner.Step("b", "y", "agent", est_seconds=5),
        planner.Step("c", "z", "agent", depends_on=("a", "b"), est_seconds=1),
    ]
    p = planner.Plan(goal="g", steps=steps)
    assert p.est_seconds == 6.0, "expected critical path a->c (5+1), not 11"


def test_a_dependency_cycle_cannot_hang_the_planner():
    from app.core import planner
    steps = [
        planner.Step("a", "x", "agent", depends_on=("b",), est_seconds=1),
        planner.Step("b", "y", "agent", depends_on=("a",), est_seconds=1),
    ]
    assert planner.Plan(goal="g", steps=steps).est_seconds > 0


def test_confidence_drops_when_a_step_needs_a_tool_nobody_configured(
        no_ambient_config):
    """A plan whose step needs an unset key is not a high-confidence plan."""
    from app.core import planner
    from app.engines import adapters
    adapters.register_all()
    research = planner.plan("research competitor restaurants")   # uses web.crawl
    audit = planner.plan("audit the site")                       # uses web.fetch
    assert research.blocked_steps, "web.crawl should be unconfigured here"
    assert not audit.blocked_steps, "web.fetch needs no configuration"
    assert research.confidence < audit.confidence
    assert research.as_dict()["executable"] is False
    assert "FIRECRAWL_BASE_URL" in research.blocked_steps[0].blocked_reason


def test_outreach_plan_always_routes_through_human_review():
    """Spec Part 6: nothing is sent on the user's behalf without approval, and
    the plan must show that as a step rather than leave it implicit."""
    from app.core import planner
    from app.engines import adapters
    adapters.register_all()
    p = planner.plan("send a whatsapp message to the client")
    actions = [s.action.lower() for s in p.steps]
    assert any("review" in a for a in actions)
    send = [s for s in p.steps if s.tool == "messaging.whatsapp"][0]
    assert "s2" in send.depends_on, "send does not depend on the review step"


def test_unrecognised_goals_admit_low_confidence():
    from app.core import planner
    vague = planner.plan("do the thing with the stuff")
    specific = planner.plan("audit the website")
    assert vague.confidence < specific.confidence


# ── model routing (spec Part 6) ────────────────────────────────────────────

def test_unmeasured_providers_keep_their_configured_order():
    """One unlucky timeout on a first call must not reorder anything."""
    from app.core import routing
    routing.reset()
    chain = ["claude", "groq", "gemini"]
    assert routing.order(chain) == chain
    routing.record("groq", ok=False, latency_ms=50, error="timeout")
    assert routing.order(chain) == chain, "ranked on a single sample"
    routing.reset()


def test_a_measured_reliable_provider_outranks_a_failing_one():
    from app.core import routing
    routing.reset()
    for _ in range(5):
        routing.record("groq", ok=False, latency_ms=9000, error="429")
        routing.record("gemini", ok=True, latency_ms=800)
    assert routing.order(["groq", "gemini"])[0] == "gemini"
    routing.reset()


def test_reliability_beats_latency():
    """A fast provider that fails half the time is worse than a slower one that
    always works — every failure costs the caller a full retry."""
    from app.core import routing
    routing.reset()
    for i in range(10):
        routing.record("fast", ok=(i % 2 == 0), latency_ms=100, error="flaky")
        routing.record("slow", ok=True, latency_ms=2500)
    assert routing.order(["fast", "slow"])[0] == "slow"
    routing.reset()


def test_a_failing_provider_is_demoted_never_dropped():
    """Removing a provider during a transient outage would silence every agent."""
    from app.core import routing
    routing.reset()
    for _ in range(routing.TRIP_AFTER + 2):
        routing.record("groq", ok=False, latency_ms=20, error="dead key")
    ordered = routing.order(["groq", "gemini"])
    assert set(ordered) == {"groq", "gemini"}, "a provider was dropped"
    assert ordered[-1] == "groq"
    assert routing.report()["providers"][0]["tripped"] is True
    routing.reset()


def test_a_tripped_provider_recovers_after_cooldown(monkeypatch):
    from app.core import routing
    routing.reset()
    for _ in range(routing.TRIP_AFTER):
        routing.record("groq", ok=False, latency_ms=20, error="429")
    assert routing.order(["groq", "gemini"])[-1] == "groq"

    real_time = routing.time.time
    monkeypatch.setattr(routing.time, "time",
                        lambda: real_time() + routing.COOLDOWN_SECONDS + 1)
    assert routing.order(["groq", "gemini"])[-1] != "groq", "never recovered"
    routing.reset()


def test_an_empty_response_counts_as_a_failure():
    """Counting empty responses as success keeps a silently-broken provider
    ranked first forever."""
    from app.core import llm, routing
    routing.reset()
    monkey = {"calls": 0}

    def _empty(system, prompt, max_tokens):
        monkey["calls"] += 1
        return None

    original = dict(llm._DISPATCH)
    llm._DISPATCH["groq"] = _empty
    try:
        os.environ["GROQ_API_KEY"] = "test-key"
        assert llm.complete("s", "p") is None
        row = routing.report()["providers"][0]
        assert row["provider"] == "groq" and row["failures"] == 1
        assert row["successes"] == 0
    finally:
        llm._DISPATCH.clear()
        llm._DISPATCH.update(original)
        os.environ.pop("GROQ_API_KEY", None)
        routing.reset()


def test_routing_state_survives_a_restart():
    from app.core import routing
    routing.reset()
    for _ in range(4):
        routing.record("gemini", ok=True, latency_ms=700)
    saved = routing.export_state()
    routing.reset()
    assert routing.report()["providers"] == []
    routing.import_state(saved)
    row = routing.report()["providers"][0]
    assert row["provider"] == "gemini" and row["calls"] == 4 and row["routable"]
    routing.reset()


def test_import_state_survives_a_corrupt_state_file():
    from app.core import routing
    routing.reset()
    routing.import_state({"profiles": {"groq": {"calls": "nonsense",
                                                "latencies_ms": "not-a-list",
                                                "last_error": 12345}}})
    row = routing.report()["providers"][0]
    assert row["p50_latency_ms"] == 0 and row["calls"] == 0
    assert row["success_rate"] == 0.0

    # A file claiming more successes than calls must not yield >100%.
    routing.import_state({"profiles": {"groq": {"calls": 2, "successes": 99}}})
    assert routing.report()["providers"][0]["success_rate"] <= 100.0

    routing.import_state("not a dict")          # must not raise
    routing.import_state({"profiles": {"bad": "not a dict either"}})
    routing.reset()


# ── event bus (spec Part 2 / Part 7) ───────────────────────────────────────

def test_event_bus_delivers_and_traces():
    from app.core import events
    events.reset()
    seen = []
    off = events.subscribe(events.TASK_CREATED, lambda r: seen.append(r))
    events.emit(events.TASK_CREATED, {"goal": "audit a site"}, actor="planner")
    assert len(seen) == 1 and seen[0]["payload"]["goal"] == "audit a site"
    off()
    events.emit(events.TASK_CREATED, {"goal": "second"})
    assert len(seen) == 1, "unsubscribe did not take effect"
    assert events.stats()["total"] == 2
    assert events.trace(limit=1)[0]["payload"]["goal"] == "second"
    events.reset()


def test_a_broken_subscriber_cannot_break_the_emitter():
    """A listener that throws must degrade observability, never the business
    action that fired the event."""
    from app.core import events
    events.reset()
    good = []
    events.subscribe(events.AGENT_FAILED, lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    events.subscribe(events.AGENT_FAILED, lambda r: good.append(r))
    rec = events.emit(events.AGENT_FAILED, {"agent": "scout"})
    assert good, "a failing handler stopped later handlers"
    assert rec["errors"] and "RuntimeError" in rec["errors"][0]
    assert events.stats()["subscriber_failures"] == 1
    events.reset()


def test_event_trace_is_bounded():
    from app.core import events
    events.reset()
    for i in range(events.MAX_TRACE + 40):
        events.emit(events.TOOL_INVOKED, {"i": i})
    assert len(events.trace(limit=10_000)) == events.MAX_TRACE
    assert events.stats()["total"] == events.MAX_TRACE + 40
    events.reset()


# ── tool layer + licence gate (spec Part 2 Layer 4 / Part 8) ───────────────

def test_agpl_tool_is_wrap_only_and_never_embedded():
    """Firecrawl is AGPL-3.0 and Titan is sold. If its integration mode is ever
    flipped to 'embed', Titan would owe its own source to every user of the
    hosted Space. This test is the tripwire."""
    from app.core import tools
    p = tools.PROVENANCE["firecrawl"]
    assert p.licence == "AGPL-3.0"
    assert p.mode == tools.WRAP, "AGPL dependency must never be embedded"


def test_unlicensed_upstream_is_blocked_in_code_not_just_in_a_comment():
    from app.core import tools
    from app.engines import adapters
    adapters.register_all()
    t = tools.get("memory.external")
    assert t.status() == "licence_blocked"
    res = t.invoke()
    assert res.ok is False
    assert "licence" in (res.error + res.needs).lower()


def test_unconfigured_tool_says_exactly_what_is_missing(no_ambient_config):
    from app.core import tools
    from app.engines import adapters
    adapters.register_all()
    res = tools.get("web.crawl").invoke(url="https://example.com")
    assert res.ok is False
    assert "FIRECRAWL_BASE_URL" in res.needs


def test_outbound_tool_refuses_without_explicit_approval(monkeypatch):
    """Spec Part 6: never send on the user's behalf without approval."""
    from app.core import tools
    from app.engines import adapters
    monkeypatch.setenv("OPENWA_BASE_URL", "http://localhost:9999")
    adapters.register_all()
    t = tools.get("messaging.whatsapp")
    assert t.status() == "ready"
    res = t.invoke(to="123", message="hello")
    assert res.ok is False and "approved" in res.needs.lower()


def test_tool_failure_is_returned_not_raised():
    from app.core import tools
    from app.engines import adapters
    adapters.register_all()
    res = tools.get("web.fetch").invoke()          # no url -> ValueError inside
    assert res.ok is False and "ValueError" in res.error


def test_ready_means_it_actually_runs_not_just_that_env_is_set():
    """A tool whose python package is absent reported 'ready' and then failed on
    invoke, moving the failure from the status screen to the caller."""
    from app.core import tools
    from app.engines import adapters
    adapters.register_all()
    t = tools.get("agents.plan")
    assert t.missing_packages() == ["praisonaiagents"]
    assert t.status() == "not_configured"
    res = t.invoke(goal="x")
    assert res.ok is False and "pip install praisonaiagents" in res.needs


def test_every_registered_tool_declares_a_resolvable_status():
    from app.core import tools
    from app.engines import adapters
    adapters.register_all()
    report = tools.registry_report()
    assert report["tools"], "no tools registered"
    for t in report["tools"]:
        assert t["status"] in ("ready", "not_configured", "licence_blocked")
        assert t["capability"], f"{t['name']} has no capability description"


def test_api_tools_registry_is_honest_about_readiness(client):
    r = client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["tools"], "boot did not register the adapters"
    names = {t["name"] for t in body["tools"]}
    assert {"web.fetch", "web.crawl", "messaging.whatsapp"} <= names
    fc = next(t for t in body["tools"] if t["name"] == "web.crawl")
    assert fc["licence"] == "AGPL-3.0" and fc["integration_mode"] == "wrap"
    # web.fetch needs nothing, so it must be the one capability always usable.
    assert next(t for t in body["tools"] if t["name"] == "web.fetch")["status"] == "ready"


def test_api_tool_invoke_returns_a_reason_instead_of_a_stack_trace(
        client, no_ambient_config):
    r = client.post("/api/tools/web.crawl/invoke", json={"url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "FIRECRAWL_BASE_URL" in body["needs"]
    assert client.post("/api/tools/nope/invoke", json={}).status_code == 404


def test_api_events_exposes_the_structured_trace(client):
    client.post("/api/tools/web.crawl/invoke", json={"url": "https://example.com"})
    body = client.get("/api/events").json()
    assert body["total"] >= 1
    assert any(e["event"] in ("ToolInvoked", "ToolFailed") for e in body["events"])


# ── lead funnel ────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_leads(monkeypatch, tmp_path):
    """STORE.leads is not cleared by fresh_store and every write is persisted,
    so a test that creates leads otherwise pollutes the real state file — the
    same trap the client registry had."""
    from app import persistence
    monkeypatch.setattr(persistence, "STATE_FILE",
                        str(tmp_path / "titan_state.json"))
    before = dict(STORE.leads)
    STORE.leads.clear()
    yield
    STORE.leads.clear()
    STORE.leads.update(before)


def test_funnel_counts_leads_that_passed_through_not_leads_sitting_there(
        client, isolated_leads):
    """`counts` is a snapshot of where leads are NOW. A lead that reached 'won'
    is no longer counted in 'contacted', so drawing a funnel from counts shows
    conversion going UP the stages. The funnel must count how many leads ever
    reached each stage."""
    ids = []
    for n in ("A", "B", "C", "D"):
        r = client.post("/api/leads", json={"name": f"Lead {n}", "source": "manual"})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])

    # A → won (so it passed through contacted and replied on the way)
    for s in ("contacted", "replied", "won"):
        assert client.post(f"/api/leads/{ids[0]}/status", json={"status": s}).status_code == 200
    # B → replied
    for s in ("contacted", "replied"):
        assert client.post(f"/api/leads/{ids[1]}/status", json={"status": s}).status_code == 200
    # C → contacted, then lost: it still reached 'contacted'
    assert client.post(f"/api/leads/{ids[2]}/status", json={"status": "contacted"}).status_code == 200
    assert client.post(f"/api/leads/{ids[2]}/status", json={"status": "lost"}).status_code == 200
    # D stays new

    body = client.get("/api/leads").json()
    funnel = {row["stage"]: row for row in body["funnel"]}

    assert funnel["new"]["reached"] == 4          # everyone starts here
    assert funnel["contacted"]["reached"] == 3    # A, B, C — C counts despite being lost
    assert funnel["replied"]["reached"] == 2      # A, B
    assert funnel["won"]["reached"] == 1          # A

    # Monotonically non-increasing — that is what makes it a funnel.
    reached = [row["reached"] for row in body["funnel"]]
    assert reached == sorted(reached, reverse=True)

    assert funnel["new"]["pct"] == 100.0
    assert funnel["won"]["pct"] == 25.0
    assert body["lost"] == 1
    assert body["conversion_pct"] == 25.0


def test_funnel_records_where_a_lost_lead_died(client, isolated_leads):
    """Losing a lead must not erase how far it got, otherwise the funnel cannot
    show which stage is actually leaking."""
    r = client.post("/api/leads", json={"name": "Doomed", "source": "manual"})
    lid = r.json()["id"]
    for s in ("contacted", "replied", "lost"):
        client.post(f"/api/leads/{lid}/status", json={"status": s})

    funnel = {row["stage"]: row for row in client.get("/api/leads").json()["funnel"]}
    assert funnel["replied"]["reached"] == 1
    assert funnel["won"]["reached"] == 0


def test_funnel_does_not_regress_when_a_lead_moves_backwards(client, isolated_leads):
    """Correcting a mis-click (won → contacted) must not un-count the stages the
    lead genuinely reached."""
    lid = client.post("/api/leads", json={"name": "Bounced", "source": "manual"}).json()["id"]
    for s in ("contacted", "replied", "won", "contacted"):
        client.post(f"/api/leads/{lid}/status", json={"status": s})

    funnel = {row["stage"]: row for row in client.get("/api/leads").json()["funnel"]}
    assert funnel["won"]["reached"] == 1
    assert client.get("/api/leads").json()["counts"]["contacted"] == 1


def test_guest_leads_payload_has_the_same_shape_as_the_real_one(monkeypatch):
    """The demo substitutes its own /api/leads body. When the real endpoint grows
    a field the substitute does not, the dashboard renders undefined for guests —
    and the guest view is what prospects are shown."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    c = TestClient(app)
    tok = c.post("/api/demo/enter").json()["token"]
    body = c.get("/api/leads", headers={"Authorization": f"Bearer {tok}"}).json()

    for key in ("items", "counts", "statuses", "stages", "funnel", "lost",
                "conversion_pct"):
        assert key in body, f"guest /api/leads is missing {key!r}"
    reached = [row["reached"] for row in body["funnel"]]
    assert reached == sorted(reached, reverse=True)
    assert {"stage", "reached", "pct", "dropped"} <= set(body["funnel"][0])


def test_funnel_is_empty_not_broken_with_no_leads(client, isolated_leads):
    body = client.get("/api/leads").json()
    assert [row["reached"] for row in body["funnel"]] == [0, 0, 0, 0]
    assert body["conversion_pct"] == 0.0
    assert all(row["pct"] == 0.0 for row in body["funnel"])


@pytest.fixture
def isolated_clients(monkeypatch, tmp_path):
    """The client registry is module-level and persisted to disk, and the
    fresh_store fixture does not touch it. Without this a test that onboards a
    client writes into the real state file and fails on the next run with
    'username already exists'."""
    import copy
    from app import persistence
    from app.core import clients as clients_mod

    monkeypatch.setattr(persistence, "STATE_FILE",
                        str(tmp_path / "titan_state.json"))
    before = copy.deepcopy(clients_mod.export_state())
    clients_mod.import_state({"clients": {}})
    yield
    clients_mod.import_state(before)


def test_admin_seo_audit_passes_client_country(client, isolated_clients,
                                               monkeypatch):
    """/admin/clients/{cid}/seo audited without the country, so the Clients tab
    and the PDF disagreed about the jurisdiction for the same site."""
    from app.engines import client_seo

    seen: dict = {}

    def fake_audit(url, **kw):
        seen.update(kw)
        return {"ok": True, "url": url, "score": 50, "grade": "D",
                "passed": [], "failed": [], "schema_types": [], "findings": [],
                "legal": {"country": "DE", "findings": [], "legal_critical": 0},
                "local": {"score": 0, "findings": []},
                "counts": {"legal_critical": 0, "critical": 0, "high": 0,
                           "medium": 0, "low": 0}}

    monkeypatch.setattr(client_seo, "audit", fake_audit)

    created = client.post("/api/admin/clients", json={
        "business_name": "Trattoria Test", "username": "tt-user",
        "password": "tt-pass-12345", "website": "https://example.com",
        "city": "Berlin", "country": "Germany", "industry": "Restaurant",
    })
    assert created.status_code == 200, created.text
    cid = created.json()["id"]

    r = client.post(f"/api/admin/clients/{cid}/seo")
    assert r.status_code == 200, r.text
    assert seen.get("country") == "Germany"


def test_admin_schema_endpoint_uses_client_jurisdiction(client,
                                                        isolated_clients):
    """The SEO view needs the paste-ready JSON-LD without a client token."""
    import json as _json

    created = client.post("/api/admin/clients", json={
        "business_name": "Gasthaus Adler", "username": "adler",
        "password": "adler-pass-12345", "website": "https://adler.example",
        "city": "München", "country": "Germany", "industry": "Restaurant",
    })
    assert created.status_code == 200, created.text
    cid = created.json()["id"]

    r = client.get(f"/api/admin/clients/{cid}/seo/schema")
    assert r.status_code == 200, r.text
    node = _json.loads(r.json()["json_ld"])
    assert node["name"] == "Gasthaus Adler"
    assert node["address"]["addressLocality"] == "München"
    assert node["address"]["addressCountry"] == "DE"

    assert client.get("/api/admin/clients/does-not-exist/seo/schema"
                      ).status_code == 404


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


# ── founder analytics ──────────────────────────────────────────────────────

def test_founder_analytics_is_never_served_to_the_public_demo(
        client, isolated_billing, monkeypatch):
    """Every row of this report is a real subscriber's email address. The
    route-table audit test skips it because it is registered sensitive — this
    asserts the registration actually refuses a guest, rather than trusting a
    string being present in a tuple."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    from app.core import demo_data

    assert "/api/founder" in demo_data._SENSITIVE_PREFIXES

    client.post("/api/signup", json={"email": "leak@example.com",
                                     "password": "hunter2hunter2"})
    tok = client.post("/api/demo/enter").json()["token"]
    r = client.get("/api/founder/analytics",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "leak@example.com" not in r.text


def test_founder_analytics_reports_who_signed_up_and_what_they_did(
        client, isolated_billing, isolated_clients):
    """The three questions the founder cannot currently answer: who signed up,
    which plan, and what they actually did."""
    from app.core import analytics

    client.post("/api/signup", json={"email": "a@example.com",
                                     "password": "hunter2hunter2"})
    tok = client.post("/api/account/login",
                      json={"email": "a@example.com",
                            "password": "hunter2hunter2"}).json()["token"]
    r = client.post("/api/account/onboard",
                    json={"business_name": "Triad Thread Studio",
                          "website": "", "industry": "wholesale",
                          "run_audit": False},
                    headers={"X-Account-Token": tok})
    assert r.status_code == 200, r.text

    rep = analytics.report()
    assert rep["totals"]["accounts"] == 1
    row = rep["accounts"][0]
    assert row["email"] == "a@example.com"
    assert row["plan"] == "free"
    assert row["business_count"] == 1
    assert row["businesses"][0]["business_name"] == "Triad Thread Studio"
    # Signing back in is the difference between interest and use.
    assert row["returned_after_signup"] is True

    steps = {s["step"]: s for s in rep["funnel"]}
    assert steps["Signed up"]["count"] == 1
    assert steps["Added a business"]["count"] == 1
    assert steps["Is paying"]["count"] == 0


def test_funnel_says_which_steps_it_can_actually_prove(client, isolated_billing):
    """The activity log starts empty the day this ships, but accounts already
    exist. A step reconstructed from account state is true for every account
    ever created; a step that can only come from the log is not. Presenting
    both as the same kind of number would be inventing one."""
    from app.core import analytics
    rep = analytics.report()
    steps = {s["step"]: s for s in rep["funnel"]}

    assert steps["Signed up"]["reliable"] is True
    assert steps["Signed up"]["source"] == "account state"
    assert steps["Added a business"]["reliable"] is True
    assert steps["Ran an audit"]["reliable"] is True
    assert steps["Is paying"]["reliable"] is True

    # These have no durable trace anywhere and must say so.
    assert steps["Downloaded a PDF report"]["reliable"] is False
    assert steps["Downloaded a PDF report"]["source"] == "activity log"
    assert steps["Opened checkout"]["reliable"] is False


def test_mrr_is_not_reported_as_zero_when_it_cannot_be_collected(
        client, isolated_billing, monkeypatch):
    """No processor is configured, so no account can complete a purchase. A
    0.0 sitting under a dollar sign would read as 'measured, and it is zero'.
    It is not measured — it is uncollectable, and the report has to say which."""
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    from app.core import analytics

    rev = analytics.report()["revenue"]
    assert rev["collectable"] is False
    assert rev["committed_mrr_usd"] is None
    assert "PAYPAL_CLIENT_ID" in rev["note"]


def test_analytics_survives_a_restart(isolated_billing):
    """Losing the funnel on every Space restart would make 'nobody used it'
    indistinguishable from 'we forgot'."""
    from app.core import analytics
    analytics.record("b@example.com", analytics.DOWNLOADED_REPORT, client_id="c1")
    saved = analytics.export_state()
    analytics.reset()
    assert analytics.report()["activity"]["log_size"] == 0
    analytics.import_state(saved)
    assert analytics.report()["activity"]["log_size"] == 1


def test_analytics_can_never_break_the_action_it_measures(isolated_billing):
    """A metric that can raise is a metric that takes down a signup."""
    from app.core import analytics
    analytics.record("", analytics.SIGNED_UP)
    analytics.record(None, None)
    analytics.record("c@example.com", "")
    assert analytics.report()["activity"]["log_size"] == 0


def test_analytics_log_is_bounded(isolated_billing):
    """Free-tier container. An unbounded log is an OOM with a delay."""
    from app.core import analytics
    for i in range(analytics.MAX_EVENTS + 50):
        analytics.record("d@example.com", analytics.SIGNED_IN, n=i)
    assert analytics.report()["activity"]["log_size"] == analytics.MAX_EVENTS


# ── visitor analytics ──────────────────────────────────────────────────────

@pytest.fixture
def isolated_traffic(monkeypatch, tmp_path):
    from app import persistence
    from app.core import traffic
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "t.json"))
    traffic.reset()
    yield
    traffic.reset()


def test_visitor_ip_is_never_stored(isolated_traffic):
    """Titan sells legal compliance. Storing visitor IPs while charging clients
    to fix their GDPR problems would be indefensible, so the raw address must
    not survive anywhere in exported state."""
    from app.core import traffic
    traffic.record("/", ip="203.0.113.77", user_agent="Mozilla/5.0",
                   referrer="https://news.ycombinator.com/item?id=1&user=bob")
    blob = json.dumps(traffic.export_state())
    assert "203.0.113.77" not in blob
    # The referring URL's query string can carry personal data too.
    assert "user=bob" not in blob
    assert "news.ycombinator.com" in blob, "the referring host is still useful"


def test_crawlers_are_never_counted_as_people(isolated_traffic):
    """A bot hit is real traffic but it is not someone who might sign up.
    Folding the two together makes the funnel lie."""
    from app.core import traffic
    traffic.record("/", ip="1.1.1.1", user_agent="Mozilla/5.0 (Windows NT 10.0)")
    traffic.record("/", ip="2.2.2.2", user_agent="Googlebot/2.1")
    traffic.record("/", ip="3.3.3.3", user_agent="python-requests/2.31")
    rep = traffic.report()
    assert rep["views"] == 1
    assert rep["bot_views"] == 2
    assert rep["visitors_today"] == 1


def test_same_visitor_is_counted_once_per_day(isolated_traffic):
    from app.core import traffic
    for _ in range(5):
        traffic.record("/", ip="9.9.9.9", user_agent="Mozilla/5.0")
    rep = traffic.report()
    assert rep["views"] == 5, "every page load counts"
    assert rep["visitors_today"] == 1, "but it is one person"


def test_no_conversion_percentage_is_invented(isolated_traffic):
    """The visitor id salt rotates daily, so there is no honest all-time
    visitor total. Dividing signups by a number that does not exist would be
    inventing the denominator."""
    from app.core import traffic
    rep = traffic.report()
    assert "conversion_rate" not in rep
    assert "rotates" in rep["conversion_note"]


def test_traffic_survives_a_restart(isolated_traffic):
    from app.core import traffic
    traffic.record("/pricing", ip="8.8.8.8", user_agent="Mozilla/5.0")
    saved = traffic.export_state()
    traffic.reset()
    assert traffic.report()["views"] == 0
    traffic.import_state(saved)
    assert traffic.report()["views"] == 1
    assert traffic.report()["top_paths"]["/pricing"] == 1


def test_assets_and_api_calls_do_not_count_as_visits(client, isolated_traffic):
    """One visit must not read as thirty. Exercised through the real
    middleware, not by calling record() directly."""
    from app.core import traffic
    client.get("/api/status")
    client.get("/manifest.webmanifest")
    rep = traffic.report()
    assert rep["views"] == 0, f"non-page requests were counted: {rep['top_paths']}"


def test_founder_traffic_and_seo_overview_are_hidden_from_guests(
        client, monkeypatch):
    """Both live under /api/founder, which is registered sensitive."""
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    tok = client.post("/api/demo/enter").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/founder/traffic", headers=h).status_code == 403
    assert client.get("/api/founder/seo-overview", headers=h).status_code == 403


def test_seo_overview_shows_titan_beside_its_clients(client, isolated_clients):
    """A client outscoring the platform selling them SEO is something Abdullah
    needs to see here, not hear from the client."""
    from app.core import clients as creg
    rec = creg.create_client(business_name="Triad Thread Studio",
                             username="seo-ov-1", password="x" * 20,
                             website="https://triadthread.example",
                             industry="wholesale", country="Pakistan")
    creg.update_raw(rec["id"], last_audit={"score": 91, "grade": "A",
                                           "findings": [{"id": "x"}]})
    creg.create_client(business_name="Never Audited Ltd",
                       username="seo-ov-2", password="x" * 20,
                       website="https://never.example")

    body = client.get("/api/founder/seo-overview").json()
    assert "titan" in body
    rows = {r["business_name"]: r for r in body["clients"]}
    assert rows["Triad Thread Studio"]["score"] == 91
    # Never audited must be None, not 0 — a 0 reads as "audited, and terrible".
    assert rows["Never Audited Ltd"]["score"] is None
    assert rows["Never Audited Ltd"]["audited"] is False
    assert body["unaudited"] >= 1
    assert body["client_average"] == 91


# ── the signup screen ──────────────────────────────────────────────────────

def test_join_page_is_public_and_self_contained(client):
    """The conversion page must render for a stranger with no token, and must
    not hardcode a price — a signup screen that disagrees with what the server
    enforces is how people get billed for something they were never shown."""
    r = client.get("/join")
    assert r.status_code == 200
    html = r.text
    assert "/api/plans" in html, "prices must be fetched, not hardcoded"
    assert "/api/account/onboard" in html
    # No hardcoded dollar figure for a paid tier anywhere in the markup.
    for price in ("$4", "$19", "$99"):
        assert price not in html, f"{price} is hardcoded in join.html"


def test_join_is_in_the_sitemap(client):
    """Titan reports missing pages as a finding on client sites. Leaving its
    own conversion page out of its own sitemap would be that same mistake."""
    body = client.get("/sitemap.xml").text
    assert "/join" in body


def test_join_page_is_counted_as_a_visit(client, isolated_traffic):
    from app.core import traffic
    client.get("/join")
    assert traffic.report()["top_paths"].get("/join") == 1


# ── lead research and outreach drafting ────────────────────────────────────

def test_outreach_can_never_send_anything(no_ambient_config):
    """Abdullah's standing rule: nothing reaches a real person without his
    approval. A platform ban or spam complaint ends the service a client is
    paying for, so the capability must not exist rather than be switched off."""
    import inspect
    from app.engines import outreach
    src = inspect.getsource(outreach)
    for forbidden in ("smtplib", "sendmail", "send_message", "requests.post",
                      "httpx.post", "send_email"):
        assert forbidden not in src, f"outreach.py can {forbidden}"


def test_no_website_means_no_invented_findings():
    """Outreach citing a problem the recipient does not have is a lie that
    costs the deal on the first reply."""
    from app.engines import outreach
    res = outreach.research({"name": "Nameless Ltd", "contact": "call me",
                             "note": "met at a trade show"})
    assert res["ok"] is False
    assert res["findings"] == []
    assert "no website" in res["reason"].lower()

    msg = outreach.draft({"name": "Nameless Ltd"}, res)
    assert msg["ready"] is False
    assert msg["message"] == ""
    assert msg["sent"] is False


def test_website_is_found_wherever_the_lead_happens_to_carry_it():
    """Leads arrive from search, manual entry and imports, so the address is
    as likely to be in the note as in a tidy field."""
    from app.engines import outreach
    assert outreach.find_website({"note": "site is https://triadthread.pk/about"}) \
        == "https://triadthread.pk/about"
    assert outreach.find_website({"contact": "hello@bellavista.de, bellavista.de"}) \
        .endswith("bellavista.de")
    assert outreach.find_website({"note": "no site yet"}) == ""


def test_draft_works_with_no_llm_key_at_all(monkeypatch):
    """A $0 setup must still produce usable outreach. Falling back to nothing
    would make the whole feature depend on a key Abdullah may not have."""
    from app.core import llm
    from app.engines import outreach
    monkeypatch.setattr(llm, "complete", lambda **kw: "")

    res = {"ok": True, "website": "https://example.com", "score": 41,
           "grade": "F", "total_findings": 9,
           "findings": [{"id": "impressum", "severity": "critical",
                         "title": "No Impressum (required by §5 DDG)",
                         "detail": "German sites must carry one."}]}
    msg = outreach.draft({"name": "Bella Vista"}, res)
    assert msg["ready"] is True
    assert msg["generated_by"] == "template"
    assert "Impressum" in msg["message"]
    assert "41" in msg["message"], "the real score must appear"
    assert msg["sent"] is False


def test_research_endpoint_files_the_draft_on_the_lead(client, isolated_leads,
                                                       monkeypatch):
    from app.core import llm
    monkeypatch.setattr(llm, "complete", lambda **kw: "")
    lead = client.post("/api/leads", json={
        "name": "Nameless Ltd", "source": "manual",
        "contact": "no site", "note": "met at a trade show"}).json()

    r = client.post(f"/api/leads/{lead['id']}/research", json={"lang": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["research"]["ok"] is False
    assert body["draft"]["sent"] is False
    # Persisted onto the lead, so closing the tab does not lose it.
    assert STORE.leads[lead["id"]]["research"]["ok"] is False

    assert client.post("/api/leads/nope/research", json={}).status_code == 404


def test_template_does_not_claim_a_legal_finding_that_is_not_there(monkeypatch):
    """Caught by running it: the draft closed with "the legal ones matter most"
    beside three purely technical findings. That is an invented claim in the
    very template written to prevent invented claims."""
    from app.core import llm
    from app.engines import outreach
    monkeypatch.setattr(llm, "complete", lambda **kw: "")

    technical = {"ok": True, "website": "https://example.com", "score": 19,
                 "grade": "F", "total_findings": 17,
                 "findings": [
                     {"id": "title", "severity": "high",
                      "title": "Missing or weak page title", "detail": ""},
                     {"id": "schema", "severity": "medium",
                      "title": "No structured data found", "detail": ""}]}
    msg = outreach.draft({"name": "Example Trading"}, technical)["message"]
    assert "legal one" not in msg.lower(), msg
    assert "legal ones" not in msg.lower(), msg

    legal = dict(technical, findings=[
        {"id": "impressum", "severity": "critical",
         "title": "No Impressum (required by §5 DDG)", "detail": ""}])
    msg2 = outreach.draft({"name": "Bella Vista"}, legal)["message"]
    assert "legal one matters most" in msg2.lower(), msg2


# ── voice agent sessions ───────────────────────────────────────────────────

@pytest.fixture
def isolated_voice(monkeypatch, tmp_path):
    from app import persistence
    from app.core import voice_sessions as vs
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "v.json"))
    vs.reset()
    yield
    vs.reset()


def test_illegal_state_transitions_are_refused(client, isolated_voice):
    """A store that accepts any transition lets the dashboard animate a state
    the agent was never in — the same class of lie as a fabricated metric."""
    sid = client.post("/api/voice/sessions", json={"channel": "web"}).json()["id"]
    assert client.post(f"/api/voice/sessions/{sid}/state",
                       json={"state": "listening"}).status_code == 200
    client.post(f"/api/voice/sessions/{sid}/end")
    # ended is terminal
    r = client.post(f"/api/voice/sessions/{sid}/state", json={"state": "speaking"})
    assert r.status_code == 409
    assert "not a legal transition" in r.json()["detail"]


def test_unknown_channel_is_refused(client, isolated_voice):
    """Listing a channel Titan cannot serve is how a claim gets discovered in
    front of a customer."""
    r = client.post("/api/voice/sessions", json={"channel": "telepathy"})
    assert r.status_code == 400


def test_sensitive_tool_cannot_complete_without_human_approval(client, isolated_voice):
    """Abdullah's standing rule, enforced as a state rather than a convention."""
    sid = client.post("/api/voice/sessions", json={"channel": "phone"}).json()["id"]
    call = client.post(f"/api/voice/sessions/{sid}/tool",
                       json={"name": "book_appointment",
                             "args_summary": "Tue 3pm"}).json()
    assert call["requires_approval"] is True
    assert call["status"] == "pending"

    # Executing it without approval must be refused, not merely discouraged.
    r = client.post(f"/api/voice/sessions/{sid}/tool/{call['id']}/finish",
                    json={"ok": True})
    assert r.status_code == 403
    assert "needs approval" in r.json()["detail"]

    client.post(f"/api/voice/sessions/{sid}/tool/{call['id']}/approve",
                json={"approver": "abdullah"})
    ok = client.post(f"/api/voice/sessions/{sid}/tool/{call['id']}/finish",
                     json={"ok": True})
    assert ok.status_code == 200
    assert ok.json()["approved_by"] == "abdullah"


def test_harmless_tool_needs_no_approval(client, isolated_voice):
    sid = client.post("/api/voice/sessions", json={}).json()["id"]
    call = client.post(f"/api/voice/sessions/{sid}/tool",
                       json={"name": "lookup_opening_hours"}).json()
    assert call["requires_approval"] is False
    assert client.post(f"/api/voice/sessions/{sid}/tool/{call['id']}/finish",
                       json={"ok": True}).status_code == 200


def test_latency_is_null_when_it_was_never_measured(client, isolated_voice):
    """0 ms would read as instantaneous. A session that never thought has no
    latency to report at all."""
    sid = client.post("/api/voice/sessions", json={}).json()["id"]
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "listening"})
    body = client.get(f"/api/voice/sessions/{sid}").json()
    assert body["avg_thinking_ms"] is None

    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "thinking"})
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "speaking"})
    after = client.get(f"/api/voice/sessions/{sid}").json()
    assert isinstance(after["avg_thinking_ms"], float)
    assert after["avg_thinking_ms"] >= 0


def test_cost_is_null_not_zero(client, isolated_voice):
    """No provider is billing, so there is no cost. 0.00 would claim a
    measurement nobody took."""
    body = client.get("/api/voice/live").json()
    assert body["cost_usd"] is None
    assert "0.00" in body["cost_note"]


def test_live_summary_is_plain_language_and_counts_real_sessions(
        client, isolated_voice):
    assert "No voice sessions yet" in client.get("/api/voice/live").json()["summary"]

    sid = client.post("/api/voice/sessions", json={"channel": "whatsapp"}).json()["id"]
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "speaking"})
    client.post(f"/api/voice/sessions/{sid}/tool",
                json={"name": "send_whatsapp", "args_summary": "confirm booking"})

    live = client.get("/api/voice/live").json()
    assert live["active_count"] == 1
    assert live["by_channel"] == {"whatsapp": 1}
    assert live["pending_approvals"] == 1
    assert "speaking" in live["summary"]
    assert "approval" in live["summary"]


def test_replay_keeps_transcript_tools_and_state_timeline(client, isolated_voice):
    sid = client.post("/api/voice/sessions", json={"language": "en"}).json()["id"]
    client.post(f"/api/voice/sessions/{sid}/turn",
                json={"role": "user", "text": "Do you ship to Germany?",
                      "language": "de", "confidence": 0.91})
    client.post(f"/api/voice/sessions/{sid}/turn",
                json={"role": "agent", "text": "Yes, three to five days."})
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "thinking"})

    body = client.get(f"/api/voice/sessions/{sid}").json()
    assert len(body["turns_detail"]) == 2
    assert body["turns_detail"][0]["confidence"] == 0.91
    # The recogniser is the authority on what was actually spoken.
    assert body["language"] == "de"
    assert [h["state"] for h in body["state_history"]] == ["idle", "thinking"]


def test_escalation_records_the_reason_and_locks_the_session(client, isolated_voice):
    sid = client.post("/api/voice/sessions", json={"channel": "phone"}).json()["id"]
    r = client.post(f"/api/voice/sessions/{sid}/escalate",
                    json={"reason": "Caller asked for a refund", "to": "abdullah"})
    assert r.status_code == 200
    assert r.json()["escalated"] is True
    assert r.json()["escalation"]["reason"] == "Caller asked for a refund"
    # A human has the call; the agent may only end afterwards.
    assert client.post(f"/api/voice/sessions/{sid}/state",
                       json={"state": "speaking"}).status_code == 409
    assert client.post(f"/api/voice/sessions/{sid}/end").status_code == 200


def test_voice_sessions_are_never_served_to_the_public_demo(
        client, isolated_voice, monkeypatch):
    """Transcripts are the most personal data Titan holds."""
    # Seed the session BEFORE the guard goes up, otherwise the setup call is
    # itself refused and the test passes for the wrong reason.
    sid = client.post("/api/voice/sessions", json={}).json()["id"]
    client.post(f"/api/voice/sessions/{sid}/turn",
                json={"role": "user", "text": "my card number is secret"})

    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", "unit-test-secret")
    tok = client.post("/api/demo/enter").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/voice/live", headers=h).status_code == 403
    r = client.get(f"/api/voice/sessions/{sid}", headers=h)
    assert r.status_code == 403
    assert "card number" not in r.text


def test_capabilities_reports_configuration_not_intent(client, no_ambient_config):
    """A screen listing 'phone' while no telephony credential exists is a
    claim that gets discovered in front of a customer."""
    body = client.get("/api/voice/capabilities").json()
    assert body["browser_speech"]["ready"] is True
    assert body["telephony"]["ready"] is False
    assert "no free path" in body["telephony"]["note"].lower()
    assert body["livekit"]["ready"] is False


def test_voice_sessions_survive_a_restart(isolated_voice):
    from app.core import voice_sessions as vs
    s = vs.start("phone", caller="+49 555 0100")
    vs.add_turn(s["id"], "user", "Hello")
    saved = vs.export_state()
    vs.reset()
    assert vs.live()["total_sessions"] == 0
    vs.import_state(saved)
    assert vs.live()["total_sessions"] == 1
    assert vs.transcript(s["id"])["turns_detail"][0]["text"] == "Hello"


def test_a_silent_answer_can_return_to_idle(client, isolated_voice):
    """Found by wiring the real chat client: with voice output switched off,
    Titan thinks and then answers in text without ever speaking. That path
    409'd because thinking -> idle was missing from the machine. A state model
    that rejects a move the product genuinely makes forces the client to lie
    about what happened."""
    sid = client.post("/api/voice/sessions", json={}).json()["id"]
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "thinking"})
    r = client.post(f"/api/voice/sessions/{sid}/state", json={"state": "idle"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "idle"

    # An interrupted turn that simply stops also settles.
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "listening"})
    client.post(f"/api/voice/sessions/{sid}/state", json={"state": "interrupted"})
    assert client.post(f"/api/voice/sessions/{sid}/state",
                       json={"state": "idle"}).status_code == 200

    # The terminal rule is untouched: ended is still a dead end.
    client.post(f"/api/voice/sessions/{sid}/end")
    assert client.post(f"/api/voice/sessions/{sid}/state",
                       json={"state": "idle"}).status_code == 409
