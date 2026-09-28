# Every customer gets their own cockpit

Asked for by Abdullah on 2026-09-28, in these words (translated): *"every user
who signs up must have the same dashboard as mine — Tap to initialise Titan,
the autonomous agents, the voice, everything — each person their own. And the
demo too: not the portal, not 'tour the operator console, sample figures'."*

Approved: **option 1** — one cockpit for everyone, each user reading only their
own data — **all sixteen tabs**, built in phases, reported when complete.

## What exists today

| Surface | Who | Credential | Data |
|---|---|---|---|
| `/` cockpit, 16 tabs | founder only | `Authorization: Bearer` (core/auth.py) | the global `STORE` |
| `/` demo | anyone | guest token | `demo_data.guest_payload` samples, GET only |
| `/join` | subscriber | `X-Account-Token` (core/billing.py) | their account + businesses |
| `/portal` | one business | `X-Client-Token` (core/clients.py) | one business |

Every cockpit tab reads the single global `Store` (`app/store.py`). About 600
references to `STORE` exist across ~45 backend files. Engines are already
written against a `Store` object and the heartbeat already passes one in
(`executive.heartbeat(STORE)`, `publisher.run_due(STORE)`), so the machinery is
per-instance even though only one instance exists.

## The design in one paragraph

Each subscriber gets a **workspace**: their own `Store` instance, seeded for
them, persisted under their account. The cockpit is served to them at
**`/api/me/<path>`**, which the auth middleware authenticates with their account
token, checks against an explicit **allowlist** of cockpit paths, binds their
workspace as the current store for that request, and forwards to the existing
`/api/<path>` handler. `STORE` becomes a thin proxy that resolves to the bound
workspace, or to the founder store when nothing is bound. The frontend is the
same `CommandCenter`; for a customer session its API client prefixes `/me` and
sends the account token. The public demo becomes a **read-only demo workspace**
through the same door, so the demo *is* the customer product.

## Security model — the part that must not be wrong

1. **A customer token only works under `/api/me`.** `auth_guard` already
   refuses anything but the founder token on `/api/*`; that stays.
2. **Under `/api/me`, only allowlisted paths exist.** `cockpit_scope.ALLOWED` is
   a list of (method, path-pattern). Anything else answers 404 for a customer.
   The allowlist is the only place a route becomes customer-reachable.
3. **The store is bound in exactly one place** — the middleware — before any
   handler runs, and unbound at the end. `STORE` resolves to the bound store.
4. **Founder credentials never act for a customer.** Integrations that use
   environment credentials (Telegram bot token, GitHub token, social publishing,
   Make.com, the webhook secret) check `cockpit_scope.is_customer()` and either
   use the customer's own connected credential or answer "connect yours first".
   They never fall back to the founder's.
5. **Threads carry the binding.** Work a customer request starts on a thread
   runs inside `contextvars.copy_context()`, so it writes to their workspace,
   not the founder's. `asyncio.to_thread` and Starlette's threadpool already
   copy context; raw `threading.Thread` call sites reachable from allowlisted
   routes are wrapped.
6. **Tests that fail open.**
   * *Canary test*: plant unique strings in every field of the founder store,
     call every allowlisted route as a customer, fail if any canary appears.
   * *Allowlist test*: every `/api/me/*` path not on the allowlist answers 404
     for a customer; a new founder route is unreachable by default.
   * *Reverse test*: a customer's writes never appear in the founder store.
   * *Credential test*: with founder integration credentials set, customer
     actions never call out with them.
   * Each guard is mutation-checked (`evaluation/mutation_check.py`).

## Per-tab meaning for a customer

| Tab | Customer sees | Notes |
|---|---|---|
| Universe | their own divisions, agents, posts, KPIs | agents' tasks come from their real workspace (their businesses, leads, audits); with nothing yet, agents say what they are waiting for |
| Dashboard | their KPIs, feed, opportunities, next post | |
| Mission | their progress, XP and milestones | |
| Clients | their businesses (billing.owned_clients) | reuses existing account routes |
| SEO | audits of their businesses | metered |
| Executive | their executive report and decisions | |
| Customers | their won customers (CRM leads marked won) | never Titan's own customer list |
| Voice | their voice sessions | TTS metered |
| Graph / AI City | visualisations of their workspace | |
| War Room | debates on their topics | LLM, metered |
| Telegram | their own bot, if they connect one | founder's bot never used |
| Job Radar | their own job searches | search API metered |
| Finance | their own revenue and expense ledger | |
| CRM | their own leads | |
| APIs | the public API catalogue and live free data | not sensitive |

## Plans and costs

Every tab is visible on every plan. Anything that spends money (model calls,
web search, text-to-speech) goes through the existing `core/quota.py`, which
`bill_to` binds from the account token, so a customer's usage counts against
their plan's `ai_calls_per_month` and a reached limit returns the existing
"limit reached, here is what the next plan gives" answer.

## Liveliness

The founder cockpit is kept alive by the 5-second heartbeat. Workspaces are
ticked by the same heartbeat, but only those used in the last hour, and only
the cheap simulation step (`executive.heartbeat`). Nothing that spends money
runs for a customer unless they ask for it.

## Persistence

Each workspace's durable parts (metrics, revenue, expenses, leads, decisions,
posts, next post, settings) are saved under `workspace:<email>` in the existing
database, on the same schedule and through the same backup as the founder
store, and restored lazily on first use after a restart.

## The front door and the demo

* Signing in with a subscriber account on `/` opens **the cockpit**, not
  `/join`. The session kind (`/api/session`) gains `customer`.
* "See the product" opens the cockpit on the **demo workspace** — a real
  workspace owned by Titan, seeded with the demonstration businesses that
  `demo_workspace` already audits every six hours. Read-only (GET only), no
  "operator console", "internal view" or "sample figures" wording, and a small
  banner saying it is a demonstration account.
* `/join` stays the signup wizard, and after it the customer lands in their
  cockpit. `/portal` stays for their own clients (a business owner an agency
  gives access to).

## Phases

1. **Foundation**: workspace store, `STORE` proxy, `/api/me` + allowlist in
   `auth_guard`, context-safe threads, persistence, heartbeat ticking, the
   four fail-open tests.
2. **Front door**: customer sign-in opens the cockpit, API client prefix,
   session kind, tab set, header with their name and plan.
3. **Core tabs**: Universe, Dashboard, Mission, Clients, SEO, CRM, Voice.
4. **Money and people**: Finance, Customers, Executive.
5. **Thinking tabs**: War Room, Graph, AI City, APIs.
6. **Integrations**: Telegram (their own bot), Job Radar (their searches),
   social channels (their own connections).
7. **Demo**: demo workspace through `/api/me`, front-door wording, retire the
   founder-cockpit guest demo.

Each phase ships with its tests green, the mutation check clean, and is
verified in a browser against a local isolated server before deploying.

## Not in scope

* Moving billing onto organisations (Abdullah is doing that himself).
* Letting several people share one workspace (organisations, later).
* Changing the founder cockpit's look or behaviour.
