"""Customer cockpit: every subscriber reads their own workspace.

See docs/superpowers/specs/2026-09-28-customer-cockpit-design.md. The tests
that matter most here are the isolation ones: a customer must never see the
founder's data, and must never write into it.
"""

from __future__ import annotations

import contextvars
import os
import threading

os.environ.setdefault("TITAN_HEARTBEAT_ENABLED", "0")

import pytest  # noqa: E402

from app import store as st  # noqa: E402


def test_store_proxy_follows_the_bound_workspace():
    founder = st.founder_store()
    other = st.Store()
    founder.metrics["canary"] = 1.0
    token = st.bind(other)
    try:
        assert "canary" not in st.STORE.metrics
        st.STORE.metrics["mine"] = 2.0
        st.STORE.next_post = {"x": 1}          # attribute writes go through too
        seen = {}
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(
            lambda: seen.update(m=dict(st.STORE.metrics))))
        t.start()
        t.join()
        assert seen["m"] == {"mine": 2.0}
    finally:
        st.unbind(token)
    assert st.STORE.metrics.get("canary") == 1.0
    assert "mine" not in founder.metrics and founder.next_post != {"x": 1}
    founder.metrics.pop("canary", None)


@pytest.fixture
def clean_workspaces():
    from app.core import workspaces
    workspaces.reset()
    yield workspaces
    workspaces.reset()


def test_each_account_gets_its_own_honest_workspace(clean_workspaces):
    workspaces = clean_workspaces
    a = workspaces.for_account("a@example.com")
    b = workspaces.for_account("b@example.com")
    assert a is workspaces.for_account("a@example.com") and a is not b
    assert a is not st.founder_store()
    assert len(a.agents) > 0
    blob = repr([r.current_task for r in a.agents.values()]) + repr(a.connectors)
    for founder_word in ("Career Mind", "Upwork", "Kindle", "Abdullah"):
        assert founder_word not in blob
    assert a.metrics and all(v == 0.0 for v in a.metrics.values())
    assert not a.connectors and not a.revenue_entries


def test_a_workspace_survives_a_restart(clean_workspaces):
    workspaces = clean_workspaces
    a = workspaces.for_account("a@example.com")
    a.revenue_entries.append({"id": "r1", "amount": 5.0, "source": "x"})
    a.metrics["mrr"] = 5.0
    state = workspaces.export_state()
    workspaces.reset()
    workspaces.import_state(state)
    again = workspaces.for_account("a@example.com")
    assert again.revenue_entries[0]["amount"] == 5.0
    assert again.metrics["mrr"] == 5.0


def test_a_subscribers_research_and_content_survive_a_restart(clean_workspaces):
    """The founder's heartbeat re-runs his research; nothing re-runs a
    subscriber's, and their content packs exist nowhere else. The saved state
    goes through JSON (db.put_many uses default=str), so dates come back as
    text and must still load."""
    import json
    from app.domain.schemas import Deliverable
    workspaces = clean_workspaces
    ws = workspaces.for_account("a@example.com")
    ws.intel = {"summary": "bakery brief", "keywords": ["bakery lahore"]}
    for i in range(55):
        ws.deliverables[f"deliv-{i}"] = {
            "id": f"deliv-{i}", "title": f"Pack {i}", "kind": "growth_strategy",
            "agent_id": "marketing-head", "agent_name": "Content Studio",
            "opportunity_id": None, "content": "x", "source": "ai",
            "created_at": st.now()}
    state = json.loads(json.dumps(workspaces.export_state(), default=str))
    workspaces.reset()
    workspaces.import_state(state)
    again = workspaces.for_account("a@example.com")
    assert again.intel["summary"] == "bakery brief"
    assert len(again.deliverables) == 50                 # the newest 50
    assert "deliv-54" in again.deliverables and "deliv-0" not in again.deliverables
    Deliverable(**again.deliverables["deliv-54"])        # still a valid record


def test_saving_inside_a_customer_request_saves_the_founder_not_the_customer(
        clean_workspaces, monkeypatch, tmp_path):
    """Routes call persistence.save(STORE). Bound to a customer, STORE is
    their workspace - saving it as the top-level state would overwrite the
    founder's revenue and leads with a stranger's."""
    from app import persistence
    from app.core import db
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "s.db"))
    founder = st.founder_store()
    founder.metrics["founder_only"] = 42.0
    ws = clean_workspaces.for_account("c@example.com")
    ws.metrics["customer_only"] = 7.0
    token = st.bind(ws)
    try:
        persistence.save(st.STORE)
    finally:
        st.unbind(token)
    saved = db.all_state()
    assert saved["metrics"].get("founder_only") == 42.0
    assert "customer_only" not in saved["metrics"]
    assert saved["workspaces"]["c@example.com"]["metrics"]["customer_only"] == 7.0
    founder.metrics.pop("founder_only", None)


@pytest.fixture
def customer(clean_workspaces, monkeypatch, tmp_path):
    """A signed-in subscriber and a TestClient, with isolated state."""
    from fastapi.testclient import TestClient
    from app import persistence
    from app.core import billing, ratelimit
    from app.main import app
    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / "s.db"))
    billing.reset()
    ratelimit.reset()
    billing.signup("cust@example.com", "password123")
    token = billing.authenticate("cust@example.com", "password123")
    with TestClient(app) as client:
        yield client, token, clean_workspaces
    billing.reset()


def test_a_customer_reads_their_own_workspace_at_api_me(customer):
    client, token, workspaces = customer
    workspaces.for_account("cust@example.com").metrics["mrr"] = 12.5
    st.founder_store().metrics["mrr"] = 999.0
    r = client.get("/api/me/status", headers={"X-Account-Token": token})
    assert r.status_code == 200 and r.json()["mrr"] == 12.5
    # Bearer works too - the cockpit's API client sends that.
    r = client.get("/api/me/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["mrr"] == 12.5
    st.founder_store().metrics["mrr"] = 0.0


def test_api_me_refuses_everything_it_should(customer, monkeypatch):
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    assert client.get("/api/me/status").status_code == 401
    assert client.get("/api/me/status",
                      headers={"X-Account-Token": "nonsense"}).status_code == 401
    # Not on the allowlist: a founder route stays unreachable.
    assert client.get("/api/me/telegram/status", headers=hdr).status_code == 404
    assert client.get("/api/me/admin/clients", headers=hdr).status_code == 404
    assert client.post("/api/me/connectors/refresh", headers=hdr).status_code == 404
    # With founder auth on, the customer's token opens no founder route.
    import secrets
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", secrets.token_urlsafe(48))
    assert client.get("/api/status", headers={
        "Authorization": f"Bearer {token}"}).status_code == 401


_CANARY = "CANARY-7f3a"
_FOUNDER_WORDS = ("Career Mind", "Upwork", "Kindle", "Abdullah", _CANARY, "999999")


def _plant_founder_canaries():
    """Fill the founder Store with data no customer may ever see: the real
    founder seed (it names his businesses) plus explicit canaries."""
    from app.store import seed
    from app.engines import opportunity
    f = st.founder_store()
    seed(f)
    opportunity.discover(f)
    for k in list(f.metrics):
        f.metrics[k] = 999999.0
    f.emit("executive-core", "system", f"{_CANARY} feed", "info")
    f.revenue_entries.append({"id": "rev-c", "amount": 999999.0, "source": _CANARY,
                              "note": _CANARY, "created_at": "2026-09-28T00:00:00+00:00"})
    f.expenses.append({"id": "exp-c", "amount": 999999.0, "category": "other",
                       "note": _CANARY, "created_at": "2026-09-28T00:00:00+00:00"})
    f.leads["lead-c"] = {"id": "lead-c", "name": _CANARY, "status": "new",
                         "source": _CANARY, "contact": _CANARY, "note": _CANARY,
                         "updated_at": "2026-09-28T00:00:00+00:00"}
    f.decisions.append({"topic": _CANARY, "decision": _CANARY})
    f.intel = {"opportunities": [], "competitors": [], "keywords": [_CANARY],
               "headlines": [], "summary": f"{_CANARY} intel", "live": False,
               "last_run": None}
    for rt in f.agents.values():
        rt.current_task = f"{_CANARY} task"


def test_no_customer_route_ever_shows_founder_data(customer, monkeypatch):
    """The one that matters. Fails OPEN: every route on the allowlist is
    called, including ones added later, and any founder canary in any body
    fails the suite."""
    from app.core import api_adapters, clients, cockpit_scope, voice_sessions as vs
    client, token, _ = customer
    # The two live public-data routes would otherwise call out to the internet.
    monkeypatch.setattr(api_adapters, "exchange_rates", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(api_adapters, "weather_for_place", lambda *a, **k: {"ok": True})
    _plant_founder_canaries()
    founders_business = _make_client(f"{_CANARY} Founder Business")
    own = _make_client("Own Business", owner="cust@example.com")
    founders_call = vs.start("phone", caller=f"{_CANARY} caller")["id"]
    vs.add_turn(founders_call, "user", f"{_CANARY} said this")
    vs.record_tool(founders_call, "send_email", _CANARY)
    own_call = vs.start("web", account="cust@example.com")["id"]
    hdr = {"X-Account-Token": token}
    try:
        for method, pattern in cockpit_scope.ALLOWED:
            if method != "GET":
                continue
            # Path parameters are filled with the customer's OWN ids, so every
            # route really runs; a leak would have to come from elsewhere.
            own_id = (own_call if "/voice/" in pattern
                      else "monthly" if "/bi/" in pattern else own)
            path = "/api/me" + (pattern[len("/api"):]
                                .replace("[^/]+", own_id).replace("\\.", "."))
            if path.endswith("/live/weather"):
                path += "?place=Lahore"
            r = client.get(path, headers=hdr)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            body = r.content.decode("latin-1")
            for word in _FOUNDER_WORDS:
                assert word not in body, f"{path} leaked {word!r}"
    finally:
        vs.reset()
        clients.delete_client(founders_business)
        clients.delete_client(own)
        f = st.founder_store()
        f.agents.clear(); f.opportunities.clear(); f.feed.clear()
        f.metrics.clear(); f.revenue_entries.clear(); f.expenses.clear()
        f.leads.clear(); f.decisions.clear()
        f.intel = None


def test_every_route_not_on_the_allowlist_is_closed_to_customers(customer):
    """Walks the real route table, so a route added tomorrow is closed to
    customers by default rather than by somebody remembering."""
    from fastapi.routing import APIRoute
    from app.core import cockpit_scope
    from app.main import app
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path.startswith("/api/me"):
            continue
        inner = route.path.replace("{", "").replace("}", "")
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if cockpit_scope.allowed(method, inner):
                continue
            r = client.request(method, "/api/me" + inner[len("/api"):], headers=hdr)
            assert r.status_code == 404, (method, route.path, r.status_code)
            checked += 1
    assert checked > 100    # the walk really walked


def test_a_customers_crm_is_theirs_alone(customer):
    """One owner-tagged leads table for everyone, as /api/account/leads has
    always used. The owner comes from the session, never the request."""
    from app.core import crm
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    founder = st.founder_store()
    founder.leads["lead-f"] = crm.new_lead(lead_id="lead-f", account=crm.FOUNDER,
                                           name="Founder Prospect")
    try:
        made = client.post("/api/me/leads", headers=hdr,
                           json={"name": "Customer Prospect", "source": "manual"})
        assert made.status_code == 200 and made.json()["account"] == "cust@example.com"
        lid = made.json()["id"]
        mine = client.get("/api/me/leads", headers=hdr).json()
        assert [l["name"] for l in mine["items"]] == ["Customer Prospect"]
        # Same record through the account API, and absent from the founder's.
        acct = client.get("/api/account/leads", headers=hdr).json()
        assert [l["id"] for l in acct["items"]] == [lid]
        assert "Customer Prospect" not in client.get("/api/leads").text
        # The founder's lead is out of reach, with the same 404 as a missing one.
        assert client.post("/api/me/leads/lead-f/status", headers=hdr,
                           json={"status": "won"}).status_code == 404
        assert client.delete("/api/me/leads/lead-f", headers=hdr).status_code == 404
        assert founder.leads["lead-f"]["status"] == "new"
        # Their own lead moves and goes.
        assert client.post(f"/api/me/leads/{lid}/status", headers=hdr,
                           json={"status": "contacted"}).json()["status"] == "contacted"
        assert client.delete(f"/api/me/leads/{lid}", headers=hdr).status_code == 200
        assert lid not in founder.leads
    finally:
        founder.leads.pop("lead-f", None)


def _make_client(name, owner=None):
    from app.core import billing, clients
    import secrets
    rec = clients.create_client(business_name=name,
                                username=f"u-{secrets.token_hex(4)}",
                                password=secrets.token_urlsafe(12), website="",
                                industry="retail", city="", country="Pakistan")
    if owner:
        billing.attach_client(owner, rec["id"])
    return rec["id"]


def test_a_customers_businesses_are_theirs_alone(customer):
    """Clients and SEO tabs, in the shapes the founder's screens render, but
    only ever the subscriber's own businesses."""
    from app.core import clients
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    theirs = _make_client("Customer Leather Co", owner="cust@example.com")
    founders = _make_client("Founder Client GmbH")
    try:
        ov = client.get("/api/me/mine/clients", headers=hdr)
        assert ov.status_code == 200
        names = [c["business_name"] for c in ov.json()["clients"]]
        assert names == ["Customer Leather Co"]
        assert "limit" in ov.json()
        assert client.get(f"/api/me/mine/clients/{theirs}", headers=hdr).status_code == 200
        assert client.get(f"/api/me/mine/clients/{theirs}/seo/schema",
                          headers=hdr).status_code == 200
        watch = client.get("/api/me/mine/watch", headers=hdr).json()
        assert "Founder Client GmbH" not in str(watch)
        disc = client.get("/api/me/mine/discovery", headers=hdr).json()
        assert "Founder Client GmbH" not in str(disc)
        # Another business: every route answers as if it did not exist.
        for method, path in (("GET", f"/api/me/mine/clients/{founders}"),
                             ("POST", f"/api/me/mine/clients/{founders}/seo"),
                             ("GET", f"/api/me/mine/clients/{founders}/seo/schema"),
                             ("POST", f"/api/me/mine/clients/{founders}/watch"),
                             ("GET", f"/api/me/mine/clients/{founders}/report.pdf"),
                             ("DELETE", f"/api/me/mine/clients/{founders}")):
            assert client.request(method, path, headers=hdr).status_code == 404, path
        assert clients.get(founders)
        # Not through /api/me, there is no subscriber: nothing is served.
        assert client.get("/api/mine/clients").status_code == 404
        # Their own business can be removed, and leaves their account too.
        assert client.delete(f"/api/me/mine/clients/{theirs}", headers=hdr).status_code == 200
        assert client.get("/api/me/mine/clients", headers=hdr).json()["clients"] == []
    finally:
        for cid in (theirs, founders):
            clients.delete_client(cid)


def test_a_cockpit_re_audit_spends_the_plans_audits(customer):
    from app.core import billing, clients
    client, token, _ = customer
    own = _make_client("Audit Co", owner="cust@example.com")
    try:
        allowed = billing.PLANS["free"].audits_per_month
        for _ in range(allowed):
            assert client.post(f"/api/me/mine/clients/{own}/seo",
                               headers={"X-Account-Token": token}).status_code == 200
        over = client.post(f"/api/me/mine/clients/{own}/seo",
                           headers={"X-Account-Token": token})
        assert over.status_code == 402 and over.json()["detail"]["upgrade_to"]
    finally:
        clients.delete_client(own)


def test_the_pdf_report_downloads_from_join_and_from_the_cockpit(customer):
    """Both doors share one PDF builder. A helper name clash once replaced it
    with the portal's route of the same name; nothing covered /join's
    download, so it would have broken silently."""
    from app.core import clients
    client, token, _ = customer
    own = _make_client("Report Co", owner="cust@example.com")
    try:
        for path in (f"/api/account/clients/{own}/report.pdf",
                     f"/api/me/mine/clients/{own}/report.pdf"):
            r = client.get(path, headers={"X-Account-Token": token})
            assert r.status_code == 200, path
            assert r.headers["content-type"] == "application/pdf"
            assert r.content.startswith(b"%PDF")
    finally:
        clients.delete_client(own)


def test_adding_a_business_from_the_cockpit_is_the_same_onboarding(customer):
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    r = client.post("/api/me/mine/clients", headers=hdr,
                    json={"business_name": "New Shop", "website": "",
                          "industry": "retail", "country": "Pakistan"})
    assert r.status_code == 200 and r.json()["client"]["business_name"] == "New Shop"
    # Free allows one business; the second is the plan ceiling, not an error.
    r2 = client.post("/api/me/mine/clients", headers=hdr,
                     json={"business_name": "Second Shop", "website": ""})
    assert r2.status_code == 402
    from app.core import clients
    clients.delete_client(r.json()["client"]["id"])


def test_voice_sessions_belong_to_whoever_started_them(customer, monkeypatch):
    """Transcripts are the most personal data Titan holds. A subscriber sees
    and acts on their own sessions only, and the founder does not see theirs."""
    from app.core import approvals, voice_sessions as vs
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    founders = vs.start("web", "titan-voice", "en", "founder caller")["id"]
    try:
        mine = client.post("/api/me/voice/sessions", headers=hdr,
                           json={"channel": "web"}).json()["id"]
        client.post(f"/api/me/voice/sessions/{mine}/turn", headers=hdr,
                    json={"role": "user", "text": "customer words"})
        call = client.post(f"/api/me/voice/sessions/{mine}/tool", headers=hdr,
                           json={"name": "send_email"}).json()
        listed = [s["id"] for s in client.get("/api/me/voice/sessions",
                                              headers=hdr).json()["sessions"]]
        assert listed == [mine]
        assert client.get("/api/me/voice/live", headers=hdr).json()["total_sessions"] == 1
        assert "customer words" in client.get(f"/api/me/voice/sessions/{mine}",
                                              headers=hdr).text
        # The founder's session does not exist, as far as they can tell.
        assert client.get(f"/api/me/voice/sessions/{founders}", headers=hdr).status_code == 404
        assert client.post(f"/api/me/voice/sessions/{founders}/end",
                           headers=hdr).status_code == 404
        # ...and the founder's screens and approval queue do not show theirs.
        assert mine not in client.get("/api/voice/sessions").text
        assert client.get(f"/api/voice/sessions/{mine}").status_code == 404
        queue = [i["detail"]["session"] for i in approvals.pending()["items"]
                 if i["surface"] == "voice"]
        assert mine not in queue
        assert [c["session_id"] for c in vs.awaiting_approval(
            account="cust@example.com")] == [mine]
        # They approve as themselves, whatever name the request carries.
        ok = client.post(f"/api/me/voice/sessions/{mine}/tool/{call['id']}/approve",
                         headers=hdr, json={"approver": "someone else"})
        assert ok.status_code == 200
        assert ok.json()["approved_by"] == "cust@example.com"
        # Keyed providers are the founder's, so none is ready for them.
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-value")
        monkeypatch.setenv("LIVEKIT_API_KEY", "test-value")
        monkeypatch.setenv("LIVEKIT_API_SECRET", "test-value")
        assert client.get("/api/voice/capabilities").json()["premium_tts"]["ready"]
        caps = client.get("/api/me/voice/capabilities", headers=hdr).json()
        assert not caps["livekit"]["ready"] and not caps["premium_tts"]["ready"]
        assert caps["tool_registry"] == []
        assert "Abdullah" not in caps["telephony"]["note"]
    finally:
        vs.reset()


def test_one_subscriber_cannot_push_everyone_elses_calls_out():
    from app.core import voice_sessions as vs
    vs.reset()
    try:
        founders = vs.start("web")["id"]
        for _ in range(vs.MAX_PER_ACCOUNT + 5):
            vs.start("web", account="busy@example.com")
        assert len(vs.history(400, account="busy@example.com")) == vs.MAX_PER_ACCOUNT
        assert vs.transcript(founders)["id"] == founders
    finally:
        vs.reset()


def test_the_approvals_queue_points_at_the_route_that_approves(customer):
    """It linked to /tools/<id>/approve, which does not exist; the route is
    /tool/<id>/approve. Following the link must actually approve."""
    from app.core import approvals, voice_sessions as vs
    client, _, _ = customer
    vs.reset()
    try:
        sid = vs.start("web")["id"]
        vs.record_tool(sid, "send_email")
        item = next(i for i in approvals.pending()["items"] if i["surface"] == "voice")
        method, path = item["approve_with"].split(" ", 1)
        r = client.request(method, path, json={"approver": "abdullah"})
        assert r.status_code == 200 and r.json()["approved_by"] == "abdullah"
    finally:
        vs.reset()


def test_ask_titan_answers_a_subscriber_from_their_own_data(customer, monkeypatch):
    """The founder's assistant is briefed with his empire figures and calls him
    by name. A subscriber's is briefed with their own businesses only."""
    from app.core import llm
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    _plant_founder_canaries()
    own = _make_client("Own Bakery", owner="cust@example.com")
    seen = {}

    def fake_complete(system="", prompt="", **kw):
        seen["system"] = system
        return "Your bakery site needs a meta description."

    try:
        monkeypatch.setattr(llm, "complete", fake_complete)
        r = client.post("/api/me/assistant", headers=hdr,
                        json={"question": "How is my site?", "lang": "en"})
        assert r.status_code == 200
        assert r.json()["answer"] == "Your bakery site needs a meta description."
        assert "Own Bakery" in seen["system"]
        for word in _FOUNDER_WORDS:
            assert word not in seen["system"], word
        # With no AI answer, the fallback is theirs too - in both scripts.
        monkeypatch.setattr(llm, "complete", lambda **kw: None)
        for lang in ("en", "ur"):
            body = client.post("/api/me/assistant", headers=hdr,
                               json={"question": "hi", "lang": lang}).text
            for word in _FOUNDER_WORDS:
                assert word not in body, (lang, word)
        assert "1 business" in client.post(
            "/api/me/assistant", headers=hdr,
            json={"question": "hi", "lang": "en"}).json()["answer"]
        # Their question lands in their own feed, not the founder's.
        feed = [e["message"] for e in workspaces.for_account("cust@example.com").feed]
        assert any("You asked" in m for m in feed)
        assert not any("You asked" in e["message"] for e in st.founder_store().feed)
    finally:
        from app.core import clients
        clients.delete_client(own)
        f = st.founder_store()
        f.agents.clear(); f.opportunities.clear(); f.feed.clear()
        f.metrics.clear(); f.revenue_entries.clear(); f.expenses.clear()
        f.leads.clear(); f.decisions.clear()


def test_a_subscribers_money_is_their_own(customer):
    """Expenses and sales logged in the cockpit land in their workspace
    ledger. The founder's ledger never moves, and neither side can delete
    the other's entries."""
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    founder = st.founder_store()
    founder.expenses.append({"id": "exp-founder", "amount": 3.0, "category": "tools",
                             "note": "founder", "created_at": "2026-09-28T00:00:00+00:00"})
    before_mrr = float(founder.metrics.get("mrr", 0.0))
    try:
        exp = client.post("/api/me/finance/expense", headers=hdr,
                          json={"amount": 12.0, "category": "ads", "note": "flyers"}).json()
        sale = client.post("/api/me/revenue/log", headers=hdr,
                           json={"amount": 40.0, "source": "sales", "note": "first cake"}).json()
        ws = workspaces.for_account("cust@example.com")
        assert [e["id"] for e in ws.expenses] == [exp["id"]]
        assert ws.metrics["mrr"] == 40.0 and sale["total"] == 40.0
        assert float(founder.metrics.get("mrr", 0.0)) == before_mrr
        assert [e["id"] for e in founder.expenses] == ["exp-founder"]
        fin = client.get("/api/me/finance", headers=hdr).json()
        assert fin["revenue_total"] == 40.0 and fin["expenses_total"] == 12.0
        # The cheer in their feed is theirs, not the founder's.
        assert any("Your business is earning" in e["message"] for e in ws.feed)
        assert not any("Abdullah" in e["message"] for e in ws.feed)
        # The founder's expense id does not exist in their ledger.
        assert client.delete("/api/me/finance/expense/exp-founder",
                             headers=hdr).status_code == 404
        assert client.delete(f"/api/me/revenue/entry/{sale['entry']['id']}",
                             headers=hdr).status_code == 200
        assert client.delete(f"/api/me/finance/expense/{exp['id']}",
                             headers=hdr).status_code == 200
        assert ws.metrics["mrr"] == 0.0 and not ws.expenses
    finally:
        founder.expenses[:] = [e for e in founder.expenses if e["id"] != "exp-founder"]


def test_the_executive_report_names_only_the_callers_businesses(customer):
    """engines/bi.py listed every client on the platform ("Never audited: ...")
    and counted every account's leads. A subscriber's report is theirs."""
    from app.core import clients, crm
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    founders_business = _make_client(f"{_CANARY} Founder Business")
    own = _make_client("Own Bakery", owner="cust@example.com")
    leads = st.founder_store().leads
    leads["lead-f"] = {"id": "lead-f", "name": _CANARY, "status": "won",
                       "stage_reached": 3, "account": crm.FOUNDER}
    leads["lead-c2"] = {"id": "lead-c2", "name": "Cust lead", "status": "new",
                       "account": "cust@example.com"}
    try:
        mine = client.get("/api/me/bi/monthly", headers=hdr)
        assert mine.status_code == 200
        body = mine.text
        assert "Own Bakery" in body and _CANARY not in body
        assert "Abdullah" not in body
        assert "1 in, 0 won" in body
        founders = client.get("/api/bi/monthly").text
        assert "1 in, 1 won" in founders          # the founder's own lead only
        seo = client.get("/api/me/mine/seo-overview", headers=hdr).json()
        assert [c["business_name"] for c in seo["clients"]] == ["Own Bakery"]
        assert seo["titan"] is None and seo["unaudited"] == 1
        assert _CANARY in client.get("/api/founder/seo-overview").text
    finally:
        leads.pop("lead-f", None)
        leads.pop("lead-c2", None)
        clients.delete_client(founders_business)
        clients.delete_client(own)


def test_the_war_room_works_for_the_subscribers_own_business(customer, monkeypatch):
    """The War Room's prompts named the founder's businesses and every debate
    went to his Telegram. A subscriber's researches, debates and writes for
    their own business, and nothing of theirs reaches the founder."""
    from app.core import clients, llm
    from app.engines import news, research, telegram_bot
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    systems, searches, pushed = [], [], []
    monkeypatch.setattr(llm, "complete", lambda system="", prompt="", **kw:
                        systems.append(system) or "CONFIDENCE: 60%")
    monkeypatch.setattr(research, "search", lambda q, n=8: searches.append(q) or [])
    monkeypatch.setattr(news, "fetch_headlines", lambda q, n=8: [])
    monkeypatch.setattr(telegram_bot, "send_to_founder",
                        lambda *a, **k: pushed.append(a) or True)
    founder = st.founder_store()
    before = (founder.intel, len(founder.decisions), len(founder.deliverables))

    # No business yet: nothing to research, and nothing is spent finding that out.
    intel = client.post("/api/me/growth/scan", headers=hdr).json()
    assert "Add your business" in intel["summary"]
    assert systems == [] and searches == []

    own = _make_client("Own Bakery", owner="cust@example.com")
    clients.update(own, industry="bakery", city="Lahore")
    try:
        assert client.post("/api/me/growth/scan", headers=hdr).status_code == 200
        assert client.post("/api/me/warroom/debate", headers=hdr,
                           json={"topic": ""}).status_code == 200
        seo = client.post("/api/me/seo/report", headers=hdr, json={"keyword": ""}).json()
        assert seo["keyword"] == "bakery Lahore"
        assert client.post("/api/me/content/repurpose", headers=hdr,
                           json={"idea": "fresh bread every morning"}).status_code == 200
        assert searches and all("bakery" in q for q in searches)
        assert any("Own Bakery" in s for s in systems)
        for s in systems:
            for word in _FOUNDER_WORDS:
                assert word not in s, (word, s[:120])
        assert pushed == []                       # the founder's phone stays quiet
        ws = workspaces.for_account("cust@example.com")
        assert ws.intel and len(ws.decisions) == 1 and len(ws.deliverables) == 1
        assert "Own Bakery" in ws.decisions[0]["goal"]
        assert (founder.intel, len(founder.decisions),
                len(founder.deliverables)) == before

        # The founder's own War Room is exactly what it was.
        systems.clear()
        client.post("/api/warroom/debate", json={"topic": "founder goal"})
        assert len(pushed) == 1 and any("Abdullah" in s for s in systems)
    finally:
        founder.decisions[:] = founder.decisions[:before[1]]
        founder.pending_decision = None
        clients.delete_client(own)


def test_a_subscribers_war_room_is_rate_limited(customer, monkeypatch):
    """Each click is web searches on the platform's key plus AI calls."""
    from app.core import ratelimit
    from app.engines import autonomous
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    monkeypatch.setattr(ratelimit, "ENABLED", True)
    monkeypatch.setattr(autonomous, "growth_cycle", lambda store=None: {"ok": True})
    codes = [client.post("/api/me/growth/scan", headers=hdr).status_code
             for _ in range(ratelimit.LIMITS["warroom"][0] + 1)]
    assert codes[:-1] == [200] * (len(codes) - 1) and codes[-1] == 429
    assert client.post("/api/growth/scan").status_code == 200   # founder: unlimited



def test_a_subscriber_is_never_told_to_set_an_api_key(customer, monkeypatch):
    """With no AI answer the founder's screens say which key to set. A
    subscriber cannot set keys, so they hear the real reason instead - and
    what to do about it when it is their plan's limit."""
    from app.core import billing, llm
    from app.engines import news, research
    client, token, _ = customer
    hdr = {"X-Account-Token": token}
    monkeypatch.setattr(llm, "complete", lambda **kw: None)
    monkeypatch.setattr(research, "search", lambda q, n=8: [])
    monkeypatch.setattr(news, "fetch_headlines", lambda q, n=8: [])
    down = client.post("/api/me/seo/report", headers=hdr,
                       json={"keyword": "bakery"}).json()["report"]
    assert "could not be reached" in down and "KEY" not in down
    billing._accounts["cust@example.com"]["usage"]["ai_calls"] = 10 ** 6
    pack = client.post("/api/me/content/repurpose", headers=hdr,
                       json={"idea": "fresh bread daily"}).json()
    for text in pack.values():
        assert "KEY" not in text and "llm/health" not in text
    assert "limit reached" in pack["blog"] and "resets in" in pack["blog"]
    # The founder is still told which key to set.
    founder = client.post("/api/seo/report", json={"keyword": "x"}).json()["report"]
    assert "GROQ_API_KEY" in founder

_FRONTEND = __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend"

# Which /api routes each customer-visible tab reads. A tab may be added to
# CUSTOMER_TABS in CommandCenter.tsx only when all of its routes are on
# cockpit_scope.ALLOWED - otherwise the customer gets a panel of 404s.
TAB_ROUTES = {
    "universe": ["/api/status", "/api/divisions", "/api/agents", "/api/posts",
                 "/api/progress"],
    "dashboard": ["/api/status", "/api/divisions", "/api/agents",
                  "/api/opportunities", "/api/feed", "/api/deliverables",
                  "/api/revenue/entries"],
    "mission": ["/api/status", "/api/agents", "/api/opportunities",
                "/api/executions", "/api/decisions", "/api/feed"],
    "clients": ["/api/mine/clients", "/api/mine/discovery"],
    "seo": ["/api/mine/clients", "/api/mine/watch", "/api/mine/clients/x",
            "/api/mine/clients/x/seo/schema"],
    "crm": ["/api/leads"],
    "voice": ["/api/voice/live", "/api/voice/capabilities",
              "/api/voice/sessions", "/api/voice/sessions/x"],
    "finance": ["/api/finance", "/api/performance"],
    "customers": ["/api/leads"],
    "executive": ["/api/bi/monthly", "/api/mine/seo-overview"],
    "graph": ["/api/divisions", "/api/agents"],
    "city": ["/api/divisions", "/api/agents"],
    "warroom": ["/api/growth/intel"],
    "apis": ["/api/apis/integrated", "/api/apis", "/api/apis/live/rates",
             "/api/apis/live/weather"],
}


def _customer_tabs() -> set:
    import re
    src = (_FRONTEND / "components" / "CommandCenter.tsx").read_text(encoding="utf-8")
    m = re.search(r"CUSTOMER_TABS = new Set<string>\(\[([^\]]*)\]\)", src)
    assert m, "CUSTOMER_TABS not found in CommandCenter.tsx"
    return set(re.findall(r'"([a-z]+)"', m.group(1)))


def test_every_tab_a_customer_sees_reads_only_open_routes():
    from app.core import cockpit_scope
    tabs = _customer_tabs()
    assert tabs, "no customer tabs at all"
    for tab in tabs:
        assert tab in TAB_ROUTES, f"{tab} has no route list in TAB_ROUTES"
        for route in TAB_ROUTES[tab]:
            assert cockpit_scope.allowed("GET", route), f"{tab} needs {route}"


def test_a_customer_is_never_shown_the_founder_sample_data():
    """The API client falls back to MOCK (founder sample figures) when a call
    fails. For a subscriber every fallback must be empty instead, and the
    founder's live stream must stay off."""
    import re
    api = (_FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    uses = re.findall(r"get<[^>]+>\([^)]*MOCK\.\w+", api)
    assert uses, "expected the founder cockpit to still use MOCK fallbacks"
    for call in uses:
        assert "fb(" in call or "fb<" in call, f"MOCK reaches customers: {call}"
    assert 'isCustomer() ? "/api/me" : "/api"' in api
    cc = (_FRONTEND / "components" / "CommandCenter.tsx").read_text(encoding="utf-8")
    assert "useTitanStream(!customer)" in cc
    # The founder's own feeds are never requested from a subscriber's cockpit;
    # the next-post one would draft a post with their AI calls.
    for feed in ("none<Connector[]>([]) : api.connectors()",
                 "none<IntelligenceStatus | null>(null) : api.intelligence()",
                 "none({ channels: [] as ChannelTile[] }) : api.channels()",
                 "none<NextPostType | null>(null) : api.nextPost()"):
        assert f"customer ? {feed}" in cc, feed
    assert ".filter(([v]) => !customer || CUSTOMER_TABS.has(v))" in cc


def test_the_voice_screens_use_the_subscribers_own_door():
    """Voice Agents, the session recorder and Ask Titan all used hard-coded
    /api paths, which in a subscriber's cockpit would record their calls under
    the founder and brief their assistant with his figures."""
    comp = _FRONTEND / "components"
    assert "`${apiBase()}/voice${path}`" in (comp / "VoiceAgents.tsx").read_text(encoding="utf-8")
    assert "`${apiBase()}/voice${path}`" in (
        _FRONTEND / "lib" / "voiceSession.ts").read_text(encoding="utf-8")
    ask = (comp / "AskTitan.tsx").read_text(encoding="utf-8")
    assert "`${apiBase()}/assistant`" in ask
    # The premium voice runs on the founder's ElevenLabs key.
    assert 'lang === "en" && !customer' in ask
    # A reload or a closed tab ends the session instead of leaving it "live".
    assert 'window.addEventListener("pagehide", leave);' in ask
    rec = (_FRONTEND / "lib" / "voiceSession.ts").read_text(encoding="utf-8")
    # The first `thinking` waits for the session to open instead of vanishing.
    assert rec.count("if (!(await this.opened())) return;") == 3


def test_the_money_screens_show_a_subscriber_only_their_own():
    """Customers, Executive and the revenue ledger each have a founder version
    built on his business. A subscriber's cockpit must render theirs."""
    comp = _FRONTEND / "components"
    cc = (comp / "CommandCenter.tsx").read_text(encoding="utf-8")
    assert '(customer ? <MyCustomers onOpenCrm={() => setView("crm")} /> : <Customers />)' in cc
    ex = (comp / "ExecutiveCommand.tsx").read_text(encoding="utf-8")
    assert "{!customer && <ExecutiveOperations />}" in ex
    for founder_only in ('customer ? none<Analytics>() : api<Analytics>("/founder/analytics")',
                         'customer ? none<Traffic>() : api<Traffic>("/founder/traffic")',
                         'customer ? none<RoutingReport>() : api<RoutingReport>("/routing")'):
        assert founder_only in ex, founder_only
    assert 'customer ? "/mine/seo-overview" : "/founder/seo-overview"' in ex
    rev = (comp / "RevenueTracker.tsx").read_text(encoding="utf-8")
    assert "const sources = customer ? CUSTOMER_SOURCES : SOURCES;" in rev


def test_the_war_room_screen_keeps_the_founders_repo_tools_to_himself():
    """The auto-PR panel opens pull requests on Titan's own repository."""
    wr = (_FRONTEND / "components" / "WarRoomView.tsx").read_text(
        encoding="utf-8").replace("\r\n", "\n")
    assert "{/* Auto-PR to Career Mind */}\n      {!customer && (" in wr
    assert 'customer ? "live web: off" : "live web: add TAVILY_API_KEY"' in wr


def test_unbound_code_still_sees_the_founder_store():
    # The heartbeat, persistence and every founder request run unbound.
    assert st.current() is st.founder_store()
    st.STORE.metrics["probe"] = 3.0
    assert st.founder_store().metrics.pop("probe") == 3.0
