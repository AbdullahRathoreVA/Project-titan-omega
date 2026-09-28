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
    assert client.post("/api/me/revenue/log", headers=hdr,
                       json={"amount": 1, "source": "x"}).status_code == 404
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
    for rt in f.agents.values():
        rt.current_task = f"{_CANARY} task"


def test_no_customer_route_ever_shows_founder_data(customer):
    """The one that matters. Fails OPEN: every route on the allowlist is
    called, including ones added later, and any founder canary in any body
    fails the suite."""
    from app.core import cockpit_scope
    client, token, _ = customer
    _plant_founder_canaries()
    hdr = {"X-Account-Token": token}
    try:
        for method, pattern in cockpit_scope.ALLOWED:
            if method != "GET":
                continue
            path = "/api/me" + pattern[len("/api"):].replace(r"(?P<id>[^/]+)", "x")
            r = client.get(path, headers=hdr)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            for word in _FOUNDER_WORDS:
                assert word not in r.text, f"{path} leaked {word!r}"
    finally:
        f = st.founder_store()
        f.agents.clear(); f.opportunities.clear(); f.feed.clear()
        f.metrics.clear(); f.revenue_entries.clear(); f.expenses.clear()
        f.leads.clear(); f.decisions.clear()


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


def test_unbound_code_still_sees_the_founder_store():
    # The heartbeat, persistence and every founder request run unbound.
    assert st.current() is st.founder_store()
    st.STORE.metrics["probe"] = 3.0
    assert st.founder_store().metrics.pop("probe") == 3.0
