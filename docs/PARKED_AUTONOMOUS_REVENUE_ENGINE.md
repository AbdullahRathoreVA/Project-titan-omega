# PARKED — "Autonomous Revenue Engine" brief

Abdullah wrote a 52-section brief (2026-08-15) to turn Titan into an autonomous
business operating system. **He asked for it to be parked, not executed.** This
file exists so the brief is not lost and so the next session does not start it
by accident.

## Why it is parked

**Titan cannot take a payment.** Every section below multiplies a revenue of
$0, and 52 × $0 is $0. The brief's own §48 puts revenue infrastructure at P1,
and the only thing standing between Titan and its first sale is four Paddle
environment variables — blocked on Abdullah, not on code.

**A large part of the brief is already built.** It reads as if written without
the repository in front of it. See the status map below.

**A large part of the rest cannot be built honestly yet.** ROI attribution
(§9), churn prediction (§19), CAC-based channel ranking (§16), the
experimentation engine (§32) and agent economics (§12) all require real
customer data. With zero customers, building them means shipping dashboards
full of numbers nobody measured — which is precisely what the brief's own §49
forbids and what this codebase's spine rule forbids. **Building them now would
force the fabrication the brief exists to prevent.**

## Un-park trigger

Work this brief when **both** are true:

1. Paddle is configured and at least one payment has succeeded.
2. At least one paying customer has enough activity to produce real numbers.

Until then, the highest-value action is not in this document.

## Status map — the brief's 52 sections against the repository

`DONE` shipped and tested · `PARTIAL` real but incomplete · `NEEDS CUSTOMERS`
cannot be built truthfully yet · `OPEN` not started

| § | Topic | Status | Where / why |
|---|---|---|---|
| 4 | Real system, no fake activity | DONE | The codebase's spine rule. Cost is null not 0.00; unaudited sites read "not audited". |
| 5 | Lead discovery + intelligence | PARTIAL | `engines/discovery.py`, `engines/prospecting.py`, `core/clients.py`. Scoring exists; evidence attached via `core/evidence.py`. |
| 6 | Autonomous sales pipeline | PARTIAL | CRM + outreach drafting exist. **Outreach has no send capability at all**, asserted by a source-inspection test. That is deliberate. |
| 7 | Offer engine | PARTIAL | `engines/verticals.py` + audit findings drive the recommendation. Not a general engine. |
| 8 | Monetization tiers | DONE | `core/billing.py`, 4 plans, $0/$4/$19/$99. **Processor unconfigured.** |
| 9 | Customer ROI engine | NEEDS CUSTOMERS | Attribution with no customers is invented attribution. |
| 10 | Self-improving agent system | DONE | `core/improve.py` + `core/params.py`, shipped 2026-08-15. observe → propose → measure isolated → named human approves → activate → auto-rollback. Never self-deploys. |
| 11 | Agent evaluation | PARTIAL | `evaluation/retrieval_benchmark.py`, `evaluation/mutation_check.py` (57 guards), `core/verify.py`, `core/reflection.py` calibration + Brier. |
| 12 | Agent economics | PARTIAL | `core/model_catalog.py` measures real token cost from OpenRouter's published prices. Revenue-influenced half NEEDS CUSTOMERS. |
| 13 | Model router | PARTIAL | `core/routing.py` exists. Cost-aware routing by difficulty is not complete. |
| 14 | Opportunity discovery | PARTIAL | `engines/opportunity.py`. |
| 15 | Product factory | OPEN | Deliberately not started. Kill criteria matter more than the pipeline. |
| 16 | Distribution engine | PARTIAL | 25 landing pages with schema, sitemap, self-audit. CAC ranking NEEDS CUSTOMERS. |
| 17 | Free tool / lead magnet | DONE | `/join` runs a real free audit and produces a PDF. |
| 18 | Viral / referral loop | OPEN | Needs the free tool to have users first. |
| 19 | Retention engine | NEEDS CUSTOMERS | Churn signals with no customers are noise. |
| 20 | Expansion revenue | NEEDS CUSTOMERS | Same. |
| 21 | Executive dashboard | PARTIAL | `ExecutiveCommand.tsx`, founder analytics, visitor analytics, funnel steps labelled BY SOURCE. |
| 22 | Real-time agent activity | DONE | SSE stream from real backend events, `core/events.py`. |
| 23 | Command centre | PARTIAL | `AskTitan`, `CommandBar` answer from real system state. |
| 24 | Approval centre | PARTIAL | Approval gates exist and are enforced per-surface (`site_fix` needs a named approver, `improve.approve` too, voice sessions 403 without one, publishing queues drafts). **Not centralised into one screen** — that is a real gap. |
| 25 | Security | DONE | SSRF guard, prompt-injection boundary (`core/untrusted.py`), signed expiring revocable sessions, rate limiting, credential vault, structural redaction, `POST`-only-with-no-body egress. |
| 26 | Multi-tenancy | DONE | `core/tenancy.py` is the one gate; an adversarial test walks the REAL route table with another subscriber's token and **fails open** on unregistered endpoints. |
| 27 | Integration architecture | DONE | `core/tools.py` — one interface, licence containment, status/`not_configured`/`licence_blocked`, health. |
| 28 | Observability | DONE | `core/obs.py` — JSON logs, request id on every response including 401s, credential redaction, email hashing. |
| 29 | Failure recovery | PARTIAL | Queue backoff + attempt caps + leases; `api_runtime` classifies failures and has a breaker that 401/429 must not trip. Alternative-model fallback OPEN. |
| 30 | Cost control | PARTIAL | Per-host politeness lock, size caps, timeouts, breaker, queue concurrency. Token budgets OPEN. |
| 31 | Self-monitoring | PARTIAL | `/health`, `db.stats()`, queue stats, `durable: false` reported honestly. |
| 32 | Experimentation engine | NEEDS CUSTOMERS | An experiment with no traffic has no result. |
| 33 | Market intelligence | PARTIAL | `engines/news.py`, `engines/research.py`, `core/api_registry.py` (1,675 providers, honest METADATA_ONLY). |
| 34 | Moat | OPEN as strategy | The honest current moat is the measurement discipline and the audit accuracy, not the agents. |
| 35–36 | Dashboard UX + mobile | DONE this session | Mobile IA fixed: revenue moved y=1064 → y=241 at 375×812; tab strip no longer overflows the page at 1280. |
| 37 | Scenario model | OPEN | Worth doing — but as a document, not a feature. |
| 38 | Revenue simulator | OPEN | Only safe if §39 holds absolutely. |
| 39 | REAL vs PROJECTED separation | DONE | Already the codebase's central rule. |
| 40 | Autonomous CEO layer | OPEN | Recommends, never acts. Cheap to add once there is data worth reviewing. |
| 41 | Prioritisation engine | PARTIAL | `core/planner.py` + `engines/evolution.py` adaptive scoring. |
| 42 | Low-cost engineering | DONE | Whole product runs on free tiers; stdlib-first; no SDK where a URL will do. |
| 43–44 | Don't break Titan / test everything | DONE | 417 tests, 57 mutation guards all CAUGHT, full suite + mutation check before every push. |
| 45 | Performance | PARTIAL | Suite went 6h27m → ~45s by fixing a real production bug. One test still takes ~10.8s on a real network path — uninvestigated. |
| 46 | Token efficiency | — | Working practice, not a repo feature. |

## What is genuinely missing and worth doing, in order

Once un-parked:

1. **Centralised approval screen (§24).** The gates exist and are enforced; there is no single place to see everything waiting. Cheap, real, and it makes the existing safety visible.
2. **Cost-aware model routing (§13).** `model_catalog` already measures real cost; routing by difficulty is the missing half. Directly reduces operating cost.
3. **Alternative-model fallback in recovery (§29).** The classification already exists.
4. **Scenario model (§37) as a document**, with every assumption explicit — not a dashboard widget.
5. Everything marked NEEDS CUSTOMERS, in whatever order the first customers make relevant.

## What must not be built from this brief

- Anything that displays a number nobody measured, however good the dashboard looks.
- Unrestricted self-modification. `improve.py` deliberately cannot change source code, and `activate()` refuses anything a named human has not approved.
- Auto-send outreach or auto-post social. Both are refused by tests today.
