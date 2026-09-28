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
    assert client.get("/api/me/routing", headers=hdr).status_code == 404
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
    f.telegram_log.append({"time": "2026-09-28T00:00:00+00:00", "from": _CANARY,
                           "chat_id": 1, "command": _CANARY, "reply": _CANARY})
    f.jobs = {"items": [{"id": "job-c", "title": _CANARY, "url": "https://x.test",
                         "why": _CANARY, "score": 1, "applied": False}],
              "live": False, "last_scan": None}
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
        f.telegram_log.clear()
        f.jobs = None


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
    # Lead finding and Job Radar run on the same search key and share the hour.
    assert client.post("/api/me/leads/find", headers=hdr,
                       json={"query": "cafes"}).status_code == 429
    assert client.post("/api/me/jobs/scan", headers=hdr,
                       json={"query": "catering"}).status_code == 429
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

def test_the_dashboard_speaks_for_the_subscriber(customer, monkeypatch):
    """Agent chat, the command bar, the Urdu briefing, Growth Studio and the
    next post were all written about the founder's businesses. From a
    subscriber's cockpit every one of them is about theirs."""
    from app.core import clients, llm
    from app.engines import news, research
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    systems, prompts, searches = [], [], []

    def fake(system="", prompt="", **kw):
        systems.append(system)
        prompts.append(prompt)
        return "Fresh bread, warm smiles. #bakery"

    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(research, "search", lambda q, n=8: searches.append(q) or [
        {"title": "Cafe", "url": "https://cafe.test", "content": "a cafe"}])
    monkeypatch.setattr(news, "fetch_headlines",
                        lambda q, n=8: [{"title": "Flour prices fall", "link": ""}])
    own = _make_client("Own Bakery", owner="cust@example.com")
    clients.update(own, industry="bakery", city="Lahore", website="https://bakery.test")
    try:
        agent_id = next(iter(workspaces.for_account("cust@example.com").agents))
        assert client.post(f"/api/me/agents/{agent_id}/chat", headers=hdr,
                           json={"message": "what are you doing?"}).status_code == 200
        assert client.post("/api/me/command", headers=hdr,
                           json={"text": "grow our sales this week"}).status_code == 200
        gen = client.post("/api/me/intel/generate", headers=hdr,
                          json={"kind": "school_outreach", "topic": ""}).json()
        assert gen["kind"] == "market_analysis"      # the founder-only kind is not offered
        assert client.post("/api/me/intel/news", headers=hdr,
                           json={"topic": ""}).status_code == 200
        assert client.post("/api/me/leads/find", headers=hdr,
                           json={"query": ""}).status_code == 200
        assert searches and all("bakery" in q for q in searches)
        assert any("Own Bakery" in s for s in systems)
        assert any("reporting to the owner" in s for s in systems)
        for text in systems + prompts:
            for word in _FOUNDER_WORDS:
                assert word not in text, (word, text[:120])

        report = client.get("/api/me/voice-report", headers=hdr).json()
        assert report["businesses"] == 1 and "cm_users" not in report
        assert "عبداللہ" not in report["urdu"] and "अब्दुल्लाह" not in report["hindi"]

        feed = [e["message"] for e in workspaces.for_account("cust@example.com").feed]
        assert any(m.startswith("You talked to") for m in feed)
        assert not any("Abdullah" in m for m in feed)
    finally:
        clients.delete_client(own)


def test_the_command_bar_acts_for_the_subscriber(customer, monkeypatch):
    """The command bar posts to /api/agent/act, whose every prompt promoted
    Career Mind and Upwork and whose every reply began "Abdullah". A
    subscriber's drafts are about their business and land in their workspace."""
    from app.core import clients, llm
    from app.engines import autonomous
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    systems = []
    monkeypatch.setattr(llm, "complete", lambda system="", prompt="", **kw:
                        systems.append(system) or "Warm bread, 20% off this Friday!")
    monkeypatch.setattr(autonomous, "growth_cycle", lambda store=None: {"summary": "ok"})
    act = lambda text: client.post("/api/me/agent/act", headers=hdr,  # noqa: E731
                                   json={"instruction": text}).json()

    assert "Add your business" in act("post about our offer")["response"]
    own = _make_client("Own Bakery", owner="cust@example.com")
    clients.update(own, industry="bakery", city="Lahore")
    try:
        replies = [act("post about our weekend offer")["response"],
                   act("scan for opportunities")["response"],
                   act("write a weekly report")["response"],
                   act("email a customer about our catering")["response"],
                   act("what should I focus on?")["response"]]
        ws = workspaces.for_account("cust@example.com")
        assert len(ws.posts) == 1 and not st.founder_store().posts.get(next(iter(ws.posts)))
        assert len(ws.deliverables) == 2               # the report and the outreach
        assert any("Own Bakery" in s for s in systems)
        for text in systems + replies:
            for word in _FOUNDER_WORDS:
                assert word not in text, (word, text[:100])
    finally:
        clients.delete_client(own)


def test_a_subscribers_post_never_goes_through_the_founders_webhook(customer, monkeypatch):
    """The publishing webhook posts to the founder's own accounts."""
    import httpx
    from app.core import clients, llm
    from app.engines import publisher
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    monkeypatch.setattr(publisher, "_webhook_url", lambda: "https://hook.founder.test")

    class NoNetwork:
        def __init__(self, *a, **k):
            raise AssertionError("a subscriber's post reached the founder's webhook")

    monkeypatch.setattr(httpx, "Client", NoNetwork)
    monkeypatch.setattr(llm, "complete", lambda **kw: "Fresh bread daily #bakery")

    # No business yet: a placeholder, which cannot be approved into the queue.
    draft = client.get("/api/me/next-post", headers=hdr).json()
    assert draft["unavailable"] == "no_business"
    assert client.post("/api/me/next-post/approve", headers=hdr).status_code == 409

    own = _make_client("Own Bakery", owner="cust@example.com")
    clients.update(own, industry="bakery", website="https://bakery.test")
    try:
        draft = client.get("/api/me/next-post", headers=hdr).json()   # rebuilt for it
        assert "Fresh bread" in draft["caption"] and "https://bakery.test" in draft["caption"]
        assert draft["publish"]["ready"] is False
        assert "does not post to your accounts" in draft["publish"]["reason"]
        approved = client.post("/api/me/next-post/approve", headers=hdr).json()
        assert approved["sent"] is False
        post_id = approved["scheduled_id"]
        assert post_id in workspaces.for_account("cust@example.com").posts
        assert post_id not in st.founder_store().posts
        out = client.post(f"/api/me/posts/{post_id}/publish", headers=hdr).json()
        assert out["status"] == "queued"
        assert all("yourself" in r["detail"] for r in out["results"])
    finally:
        clients.delete_client(own)


def test_the_founders_figures_and_ai_are_no_longer_public(customer, monkeypatch):
    """/api/voice-report and /api/assistant were open 'because the Space URL
    is private'. It is not, and anyone could read his live figures and spend
    his AI quota. With auth on, both need his token now."""
    import secrets
    client, token, _ = customer
    monkeypatch.setenv("TITAN_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TITAN_SECRET", secrets.token_urlsafe(48))
    assert client.get("/api/voice-report").status_code == 401
    assert client.post("/api/assistant", json={"question": "hi"}).status_code == 401
    # A subscriber still has their own, through their own door. (A new secret
    # means a new sign-in: tokens are signed with it.)
    from app.core import billing
    token = billing.authenticate("cust@example.com", "password123")
    assert client.get("/api/me/voice-report",
                      headers={"X-Account-Token": token}).status_code == 200


@pytest.fixture
def telegram(customer, monkeypatch):
    """Titan's bot switched on, the founder's chat locked to 999."""
    from app.core import telegram_links
    telegram_links.reset()
    monkeypatch.setenv("TITAN_TELEGRAM_BOT", "TitanTestBot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.delenv("TITAN_WEBHOOK_SECRET", raising=False)
    yield customer
    telegram_links.reset()


def _say(client, chat, text):
    return client.post("/api/telegram/handle",
                       json={"text": text, "chat_id": chat, "sender": "S"}).json()["reply"]


def test_a_subscribers_telegram_is_linked_by_a_one_time_code(telegram):
    """Titan cannot reach Telegram from its Space, so a subscriber uses Titan's
    own bot through the same relay: a one-time code links their chat, and from
    then on it is answered from their workspace only."""
    from app.core import telegram_links
    client, token, workspaces = telegram
    hdr = {"X-Account-Token": token}
    status = client.get("/api/me/telegram/status", headers=hdr).json()
    assert status == {"configured": True, "locked": True, "bot": "TitanTestBot",
                      "linked": False, "handled": 0}
    code = client.post("/api/me/telegram/link-code", headers=hdr).json()
    assert code["url"] == f"https://t.me/TitanTestBot?start={code['code']}"

    founders_log = len(st.founder_store().telegram_log)
    assert "Linked" in _say(client, "555", f"/start {code['code']}")
    assert client.get("/api/me/telegram/status", headers=hdr).json()["linked"]
    assert "not valid" in _say(client, "556", f"/start {code['code']}")   # used once

    workspaces.for_account("cust@example.com").metrics["mrr"] = 40.0
    reply = _say(client, "555", "/status")
    assert "Plan:" in reply and "$40.00" in reply
    for word in _FOUNDER_WORDS:
        assert word not in reply
    assert len(st.founder_store().telegram_log) == founders_log   # never his log
    assert len(client.get("/api/me/telegram/log", headers=hdr).json()) == 2

    # The founder's own chat is never linked to a subscriber.
    again = client.post("/api/me/telegram/link-code", headers=hdr).json()["code"]
    assert "not valid" in _say(client, "999", f"/start {again}")
    assert telegram_links.account_for("999") is None
    # A stranger's chat is refused, as before.
    assert "linked Titan accounts only" in _say(client, "777", "/status")

    # The link survives a restart, and unlinking ends it.
    state = telegram_links.export_state()
    telegram_links.reset()
    telegram_links.import_state(state)
    assert telegram_links.account_for("555") == "cust@example.com"
    assert client.delete("/api/me/telegram/link", headers=hdr).json()["unlinked"]
    assert "linked Titan accounts only" in _say(client, "555", "/status")


def test_a_telegram_code_expires_and_cannot_be_guessed(telegram, monkeypatch):
    from app.core import ratelimit, telegram_links
    client, token, _ = telegram
    hdr = {"X-Account-Token": token}
    code = client.post("/api/me/telegram/link-code", headers=hdr).json()["code"]
    monkeypatch.setattr(telegram_links, "CODE_TTL", -1)
    assert "not valid" in _say(client, "555", f"/start {code}")
    monkeypatch.setattr(ratelimit, "ENABLED", True)
    ratelimit.reset()
    replies = [_say(client, "555", f"/start {n:08d}") for n in range(13)]
    assert "Too many tries" in replies[-1]


def test_telegram_waits_until_titans_bot_is_named(customer, monkeypatch):
    client, token, _ = customer
    monkeypatch.delenv("TITAN_TELEGRAM_BOT", raising=False)
    hdr = {"X-Account-Token": token}
    assert client.get("/api/me/telegram/status", headers=hdr).json()["configured"] is False
    assert client.post("/api/me/telegram/link-code", headers=hdr).status_code == 409


def test_polling_never_answers_a_subscribers_chat_with_the_founders_data(
        telegram, monkeypatch):
    """Where Telegram is reachable the bot polls instead of using the relay.
    That path must route a linked chat to the subscriber too."""
    import httpx
    from app.core import telegram_links
    from app.engines import telegram_bot
    client, token, _ = telegram
    code = client.post("/api/me/telegram/link-code",
                       headers={"X-Account-Token": token}).json()["code"]
    telegram_links.redeem("555", code)

    class Resp:
        status_code = 200

        def json(self):
            return {"result": [{"update_id": 1, "message": {
                "chat": {"id": 555}, "text": "/status", "from": {"first_name": "S"}}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return Resp()

    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(telegram_bot, "_send", lambda tok, chat, text: sent.append(text))
    founder = st.founder_store()
    before = (founder.telegram_offset, len(founder.telegram_log))
    try:
        telegram_bot.poll_once(founder)
        assert sent and sent[0].startswith("Plan:")
        assert len(founder.telegram_log) == before[1]
    finally:
        founder.telegram_offset = before[0]


def test_job_radar_works_from_the_subscribers_own_profile(customer, monkeypatch):
    """Job Radar scored and wrote proposals from the founder's CV. A
    subscriber's works from the profile they write, and never his."""
    from app.core import llm
    from app.engines import jobs, research
    client, token, workspaces = customer
    hdr = {"X-Account-Token": token}
    systems, searches = [], []

    def fake(system="", prompt="", **kw):
        systems.append(system)
        return "80|Office catering contract|https://tender.test/1|Fits a bakery"

    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(research, "search", lambda q, n=8: searches.append(q) or [
        {"title": "Catering contract", "url": "https://tender.test/1", "content": "bread"}])

    # No profile yet: nothing is searched and nothing is spent.
    out = client.post("/api/me/jobs/scan", headers=hdr, json={"query": ""}).json()
    assert "Tell Titan what you offer" in out["note"] and searches == []

    profile = "Artisan bakery in Lahore: bread, cakes and office catering."
    assert client.post("/api/me/jobs/profile", headers=hdr,
                       json={"profile": profile}).json()["profile"] == profile
    found = client.post("/api/me/jobs/scan", headers=hdr, json={"query": ""}).json()
    assert found["items"][0]["title"] == "Office catering contract"
    assert found["profile"] == profile                    # kept across a scan
    assert searches and "bakery" in searches[0].lower()
    proposal = client.post("/api/me/jobs/proposal", headers=hdr,
                           json={"title": "Office catering contract"}).json()["proposal"]
    assert proposal
    assert all(profile in s for s in systems)
    for s in systems:
        assert jobs.PROFILE not in s
        for word in _FOUNDER_WORDS:
            assert word not in s, word
    # The founder's own radar is untouched and still his.
    assert not (st.founder_store().jobs or {}).get("profile")
    assert workspaces.export_state()["cust@example.com"]["jobs"]["profile"] == profile


def test_the_demo_is_the_subscriber_cockpit_and_changes_nothing(customer, monkeypatch):
    """Abdullah: the demo must be the cockpit a customer gets - not the
    operator console with sample figures, and not a portal. So it is that
    cockpit, on a demo account that holds Titan's own demonstration businesses
    and can read everything and change nothing, on either door."""
    from app.core import analytics, billing, cockpit_scope, llm
    from app.engines import demo_workspace
    client, _, _ = customer
    _plant_founder_canaries()
    try:
        opened = client.post("/api/demo/cockpit")
        assert opened.status_code == 200 and opened.json()["demo"] is True
        hdr = {"X-Account-Token": opened.json()["token"]}
        bearer = {"Authorization": f"Bearer {opened.json()['token']}"}

        # It is the whole cockpit, reading only the demo account's own data.
        for method, pattern in cockpit_scope.ALLOWED:
            if method != "GET" or "[^/]+" in pattern:
                continue
            path = "/api/me" + pattern[len("/api"):]
            if path.endswith("/live/weather"):
                continue                        # needs a place; public data anyway
            r = client.get(path, headers=hdr)
            assert r.status_code == 200, (path, r.status_code)
            for word in _FOUNDER_WORDS:
                assert word not in r.content.decode("latin-1"), (path, word)
        shown = client.get("/api/me/mine/clients", headers=hdr).json()["clients"]
        assert shown and {c["id"] for c in shown} == set(demo_workspace.business_ids())
        assert client.get("/api/account", headers=hdr).json()["demo"] is True

        # Every write is refused, on /api/me and on the /api/account door.
        writes = [("POST", "/api/me/leads", {"name": "x"}),
                  ("POST", "/api/me/assistant", {"question": "hi"}),
                  ("POST", "/api/me/mine/clients", {"business_name": "x"}),
                  ("POST", "/api/me/finance/expense", {"amount": 1}),
                  ("DELETE", "/api/me/leads/x", None),
                  ("POST", "/api/account/onboard", {"business_name": "x"})]
        for method, path, body in writes:
            for h in (hdr, bearer):
                r = client.request(method, path, headers=h, json=body)
                assert r.status_code == 403 and r.json()["demo"] is True, (path, r.status_code)

        # No AI is spent on a visitor, and nobody can sign in as the demo.
        monkeypatch.setattr(llm, "complete", lambda **kw: (_ for _ in ()).throw(
            AssertionError("the demo spent an AI call")))
        assert client.get("/api/me/next-post", headers=hdr).json()["unavailable"] == "demo"
        assert billing.authenticate(billing.DEMO_ACCOUNT, "") is None
        # And it is nobody in the founder's figures.
        assert all(a["email"] != billing.DEMO_ACCOUNT
                   for a in analytics.accounts_snapshot()["accounts"])
    finally:
        f = st.founder_store()
        f.agents.clear(); f.opportunities.clear(); f.feed.clear()
        f.metrics.clear(); f.revenue_entries.clear(); f.expenses.clear()
        f.leads.clear(); f.decisions.clear()
        f.intel = None
        f.telegram_log.clear()
        f.jobs = None


def test_the_demo_is_refused_rather_than_shown_a_real_client(customer, monkeypatch):
    client, _, _ = customer
    monkeypatch.setenv("TITAN_DEMO_WORKSPACE", "0")
    assert client.post("/api/demo/cockpit").status_code == 503
    monkeypatch.setenv("TITAN_DEMO_ENABLED", "0")
    assert client.post("/api/demo/cockpit").status_code == 404


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
    "telegram": ["/api/telegram/status", "/api/telegram/log"],
    "jobs": ["/api/jobs"],
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
                 "none({ channels: [] as ChannelTile[] }) : api.channels()"):
        assert f"customer ? {feed}" in cc, feed
    # Their next post is drafted only once they have a business to promote.
    assert ("customer && !hasBusinessRef.current ? none<NextPostType | null>(null)"
            " : api.nextPost()") in cc
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


def test_the_dashboard_never_names_the_founder_to_a_subscriber():
    """The Urdu button carried his name, the command bar suggested posting
    about Career Mind and the CRM offered "School/Uni" as a lead source."""
    comp = _FRONTEND / "components"
    read = lambda name: (comp / name).read_text(encoding="utf-8")  # noqa: E731
    assert "(customer ? CUSTOMER_SUGGESTIONS : SUGGESTIONS)" in read("CommandBar.tsx")
    assert "(customer ? CUSTOMER_SOURCES : FOUNDER_SOURCES)" in read("CrmLite.tsx")
    urdu = read("UrduVoiceAssistant.tsx")
    assert 'isCustomer() ? "\U0001f399 اردو رپورٹ"' in urdu
    assert "`${apiBase()}/voice-report`" in urdu


# Client methods a subscriber's cockpit never calls: the founder's own feeds
# and engines, and the sign-in / demo calls made before anyone is a customer.
# Everything else in lib/api.ts must reach a route open at /api/me - otherwise
# a button in their cockpit fails with a 404 nobody can explain. That is how
# the command bar (it posts to /agent/act, not /command) was nearly shipped
# broken.
_FOUNDER_ONLY_CLIENT = {
    "authStatus", "sessionKind", "enterDemo",        # before sign-in
    "connectors", "channels", "intelligence",        # his feeds (never requested)
    "refreshConnectors", "scanOpportunities",         # his engines (buttons hidden)
    "weeklyReport", "executeOpportunity", "openPr",
}


def _client_routes() -> dict:
    import re
    src = (_FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    heads = [(m.start(), m.group(1)) for m in
             re.finditer(r"^  (?:async\s+)?(\w+)\s*[:(]", src, re.M)]
    verbs = {"get": "GET", "getRoot": "GET", "post": "POST", "del": "DELETE"}
    out: dict = {}
    for m in re.finditer(r"\b(getRoot|get|post|del)\s*<[^()]*?>\(\s*[`\"]([^`\"]+)", src):
        name = [n for pos, n in heads if pos < m.start()][-1]
        path = "/api" + re.sub(r"\$\{[^}]+\}", "x", m.group(2).split("?")[0])
        out.setdefault(name, []).append((verbs[m.group(1)], path))
    return out


def test_every_client_call_a_subscriber_can_make_is_open_to_them():
    from app.core import cockpit_scope
    routes = _client_routes()
    assert "command" in routes and len(routes) > 40      # the parser really parsed
    closed = [f"{name}: {method} {path}"
              for name, calls in routes.items() if name not in _FOUNDER_ONLY_CLIENT
              for method, path in calls if not cockpit_scope.allowed(method, path)]
    assert not closed, "closed to subscribers: " + "; ".join(closed)


def test_the_demo_on_the_front_door_is_the_cockpit():
    """The sign-in page offered "tour the operator console (our internal view,
    sample figures)" and a client portal. The demo is now the cockpit itself."""
    login = (_FRONTEND / "components" / "Login.tsx").read_text(encoding="utf-8")
    assert "Try the cockpit — no signup" in login
    assert "operator console" not in login and "/api/demo/portal" not in login
    client = (_FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    # The demo token is kept out of /join, so a visitor signs up as themselves.
    assert "setCustomerToken(data.token, false)" in client
    # A refused demo write is announced from every client write path.
    assert client.count("noticeDemoRefusal(res);") >= 3


def test_unbound_code_still_sees_the_founder_store():
    # The heartbeat, persistence and every founder request run unbound.
    assert st.current() is st.founder_store()
    st.STORE.metrics["probe"] = 3.0
    assert st.founder_store().metrics.pop("probe") == 3.0
