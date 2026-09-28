# Customer cockpit — Phase 1: foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A subscriber's account token can read the cockpit API at `/api/me/<path>`, served from their own private `Store`, with the founder's data unreachable.

**Architecture:** `STORE` becomes a proxy over a `ContextVar`; the auth middleware binds a per-account workspace `Store` for `/api/me/*` requests, rewrites the path to the existing `/api/*` handler, and only for allowlisted paths. Workspaces persist inside the existing state file.

**Tech Stack:** FastAPI/Starlette middleware, `contextvars`, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-28-customer-cockpit-design.md`.
- Customer tokens work ONLY under `/api/me`; founder routes keep refusing them.
- The allowlist is the only place a route becomes customer-reachable; unknown paths answer 404.
- Founder environment credentials never act for a customer.
- Every guard gets a test that fails without it (checked by `python -m evaluation.mutation_check`).
- PowerShell 5.1; run tests from `backend/` with `python -m pytest tests/ -q`.
- Commit messages: plain, no attribution lines.

---

### Task 1: `STORE` resolves to the store bound for this request

**Files:**
- Modify: `backend/app/store.py` (the `STORE = Store()` line)
- Test: `backend/tests/test_core.py` (append)

**Interfaces:**
- Produces: `store.founder_store() -> Store`, `store.bind(s: Store) -> contextvars.Token`, `store.unbind(token) -> None`, `store.current() -> Store`, `STORE` (proxy with the full `Store` attribute surface).

- [ ] **Step 1: Write the failing test**

```python
def test_store_proxy_follows_the_bound_workspace():
    import threading
    import contextvars
    from app import store as st

    founder = st.founder_store()
    other = st.Store()
    founder.metrics["canary"] = 1.0
    token = st.bind(other)
    try:
        assert "canary" not in st.STORE.metrics
        st.STORE.metrics["mine"] = 2.0
        st.STORE.next_post = {"x": 1}          # attribute writes go through
        seen = {}
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(
            lambda: seen.update(m=dict(st.STORE.metrics))))
        t.start(); t.join()
        assert seen["m"] == {"mine": 2.0}
    finally:
        st.unbind(token)
    assert st.STORE.metrics.get("canary") == 1.0
    assert "mine" not in founder.metrics and founder.next_post != {"x": 1}
    founder.metrics.pop("canary", None)
```

- [ ] **Step 2: Run it — expect `AttributeError: module 'app.store' has no attribute 'founder_store'`**

- [ ] **Step 3: Implement** — replace `STORE = Store()` with:

```python
_FOUNDER = Store()
_bound: "contextvars.ContextVar[Optional[Store]]" = contextvars.ContextVar(
    "titan_store", default=None)


def founder_store() -> Store:
    return _FOUNDER


def current() -> Store:
    s = _bound.get()
    return s if s is not None else _FOUNDER


def bind(s: Store) -> "contextvars.Token":
    return _bound.set(s)


def unbind(token: "contextvars.Token") -> None:
    _bound.reset(token)


class _StoreProxy:
    """Every module does `from ..store import STORE`. Making that name follow
    the request's workspace keeps ~600 call sites unchanged while a customer
    request can only ever see the Store bound for it."""
    __slots__ = ()

    def __getattr__(self, name):
        return getattr(current(), name)

    def __setattr__(self, name, value):
        setattr(current(), name, value)

    def __repr__(self) -> str:
        return f"<STORE -> {'workspace' if _bound.get() is not None else 'founder'}>"


STORE = _StoreProxy()
```
and add `import contextvars` at the top of `store.py`.

- [ ] **Step 4: Run the new test and the full suite** — expect all pass.
- [ ] **Step 5: Commit** `git commit -m "STORE follows the store bound for the request"`

### Task 2: A private workspace per account

**Files:**
- Create: `backend/app/core/workspaces.py`
- Modify: `backend/app/persistence.py` (`save`/`load` add `"workspaces"`)
- Test: `backend/tests/test_core.py`

**Interfaces:**
- Consumes: `store.Store`, `domain.network.AGENT_NETWORK`.
- Produces: `workspaces.for_account(email) -> Store`, `workspaces.touch(email)`, `workspaces.active(within_s=3600) -> list[tuple[str, Store]]`, `workspaces.export_state() -> dict`, `workspaces.import_state(d) -> None`, `workspaces.reset()`.

- [ ] **Step 1: Failing test**

```python
def test_each_account_gets_its_own_honest_workspace():
    from app.core import workspaces
    from app import store as st
    workspaces.reset()
    a = workspaces.for_account("a@example.com")
    b = workspaces.for_account("b@example.com")
    assert a is workspaces.for_account("a@example.com") and a is not b
    assert a is not st.founder_store()
    assert len(a.agents) == len(st.founder_store().agents or a.agents)
    blob = repr([r.current_task for r in a.agents.values()]) + repr(a.connectors)
    for founder_word in ("Career Mind", "Upwork", "Kindle", "Abdullah"):
        assert founder_word not in blob
    assert all(v == 0.0 for v in a.metrics.values())
    a.revenue_entries.append({"id": "r1", "amount": 5.0})
    state = workspaces.export_state()
    workspaces.reset()
    workspaces.import_state(state)
    assert workspaces.for_account("a@example.com").revenue_entries[0]["amount"] == 5.0
```

- [ ] **Step 2: Run — expect ImportError.**
- [ ] **Step 3: Implement `core/workspaces.py`** — seeding every agent from `AGENT_NETWORK` as `AgentStatus.IDLE` with `current_task="Waiting for your first business — add one in Clients"`, zero `tasks_completed`/`success_rate`/`impact_score`, metrics `{"mrr","traffic","pipeline_value","customers","conversion_rate"}` at `0.0`, no connectors, one welcome feed event; durable fields exported: `metrics, revenue_entries, expenses, leads, decisions, posts, next_post`.
- [ ] **Step 4: Wire persistence** — in `persistence.save` add `"workspaces": workspaces.export_state()`, in `load` call `workspaces.import_state(data.get("workspaces") or {})`.
- [ ] **Step 5: Tests pass; commit** `"A private workspace per account, saved with the rest of the state"`.

### Task 3: `/api/me` — the customer door, allowlisted

**Files:**
- Create: `backend/app/core/cockpit_scope.py`
- Modify: `backend/app/main.py` (`auth_guard`, `bill_to`)
- Test: `backend/tests/test_core.py`

**Interfaces:**
- Produces: `cockpit_scope.ALLOWED: tuple[tuple[str, str], ...]` (method, regex on the inner `/api/...` path); `cockpit_scope.allowed(method, inner_path) -> bool`; `cockpit_scope.is_customer() -> bool`; `cockpit_scope.customer_email() -> str`.

Phase-1 allowlist (GET only): `/api/status`, `/api/divisions`, `/api/agents`, `/api/opportunities`, `/api/feed`, `/api/deliverables`, `/api/executions`, `/api/decisions`, `/api/posts`, `/api/progress`, `/api/performance`, `/api/finance`, `/api/leads`, `/api/revenue/entries`, `/api/next-post`. Every later phase adds its routes here only after its isolation test passes.

- [ ] **Step 1: Failing tests** — (a) a customer token on `/api/me/status` returns 200 with their workspace figures; (b) the same token on `/api/status` returns 401; (c) `/api/me/telegram/status` (not allowlisted) returns 404; (d) no token on `/api/me/status` returns 401; (e) a founder token on `/api/me/status` returns 401.
- [ ] **Step 2: Implement** — in `auth_guard`, before the founder check:

```python
if path == "/api/me" or path.startswith("/api/me/"):
    from .core import billing as _billing, cockpit_scope, workspaces
    from . import store as _store
    tok = (request.headers.get("x-account-token", "")
           or request.headers.get("authorization", "").removeprefix("Bearer ")).strip()
    email = _billing.resolve(tok) if tok else None
    if not email:
        return JSONResponse({"detail": "Sign in first"}, status_code=401)
    inner = "/api" + path[len("/api/me"):]
    if not cockpit_scope.allowed(request.method, inner):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    request.scope["path"] = inner
    request.scope["raw_path"] = inner.encode()
    token = _store.bind(workspaces.for_account(email))
    ptok = cockpit_scope.bind_customer(email)
    try:
        workspaces.touch(email)
        return await call_next(request)
    finally:
        cockpit_scope.unbind_customer(ptok)
        _store.unbind(token)
```
and in `bill_to` also read the Bearer token when the path starts with `/api/me`.
- [ ] **Step 3: Tests pass; commit** `"Customers read the cockpit API at /api/me, from their own workspace"`.

### Task 4: The fail-open isolation tests

**Files:** Test only: `backend/tests/test_core.py`

- [ ] **Canary test** — put a unique string into every text field of the founder store (a feed event, a lead, a revenue note, a decision, a post, an opportunity, an agent task) and `999999.0` into every metric; call every GET in `cockpit_scope.ALLOWED` as a customer through `/api/me`; assert no canary string and no `999999` appears in any body.
- [ ] **Allowlist test** — walk `app.routes`; every `/api/*` GET route not in `ALLOWED` answers 404 under `/api/me` for a customer.
- [ ] **Reverse test** — a customer POST that writes (added in later phases; in phase 1, write directly through a bound `STORE`) never changes the founder store.
- [ ] **Run the mutation check** and add the new guards to `evaluation/mutation_check.py`: removing the `allowed()` check, removing `_store.bind`, and making the proxy ignore the binding must each be CAUGHT.
- [ ] **Commit** `"Tests that fail if a customer can ever see founder data"`.

### Task 5: Workspaces stay alive and are saved

**Files:** Modify: `backend/app/main.py` (`_heartbeat_loop`)

- [ ] **Failing test** — `workspaces.active()` returns a workspace touched within the hour and not one touched two hours ago.
- [ ] **Implement** — in `_heartbeat_loop`, after `executive.heartbeat(STORE)`, add
  `for _email, ws in workspaces.active(): executive.heartbeat(ws)`; nothing that spends money runs here.
- [ ] **Commit** `"Active workspaces tick with the heartbeat"`.

### Task 6: Verify and ship

- [ ] Full suite green; mutation check clean.
- [ ] Isolated local server: sign up a local test account, call `/api/me/status` and `/api/me/agents` with its token, confirm workspace figures and no founder data; confirm `/api/status` still serves the founder.
- [ ] Push; confirm the Space rebuilds and the founder cockpit on titanomega-ai.com is unchanged.
