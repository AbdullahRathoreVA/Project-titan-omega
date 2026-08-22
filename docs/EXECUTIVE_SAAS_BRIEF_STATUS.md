# "World-class SaaS / Executive Control Center" brief — status map

Abdullah sent a 61-section brief (2026-08-20) to turn Titan Omega into a
polished multi-tenant SaaS with an Executive control centre, an RBAC model, a
subscription and trial engine, progressive onboarding and an integration hub.

This file is the audit the brief's §1 asks for, and the honest answer to its
§61 ("do not stop after writing a plan"): **§2, §12, §33, §34, §35, §43 and §48
were implemented this session** — the authentication and authorisation spine,
organisations, the audit log, and the trial display — and everything else is
classified below rather than half-built.

It is the companion to [`PARKED_AUTONOMOUS_REVENUE_ENGINE.md`](PARKED_AUTONOMOUS_REVENUE_ENGINE.md),
which maps the earlier 52-section brief. **The two briefs overlap heavily.**
That one was parked by Abdullah himself, and the reasoning still holds for the
overlapping parts.

## Provenance — how much to trust each row

| Mark | Meaning |
|---|---|
| **[V]** | Read and verified in the repository during this session |
| **[H]** | Taken from `CONTINUE_HERE.md`, which records work verified live in production. Not re-verified here. |
| **[P]** | Taken from the parked-brief status map. Not re-verified here. |

Nothing below is asserted from memory of what the code "probably" does. Where a
row would need a claim neither verified nor recorded, it says so.

---

## 1. Built this session (2026-08-20)

| § | Topic | What landed |
|---|---|---|
| 2 | RBAC / Executive-only access | **[V]** The login now runs on `core/identity.py` — real accounts, hashed passwords, a closed role set. `auth.valid_token()` (the check every founder endpoint's middleware makes) resolves the account and requires `role == founder`, so a valid member session cannot open the Executive dashboard. |
| 34 | Brute-force protection | **[V]** `POST /api/login` had **no rate limit at all**, while `POST /api/account/login` beside it has had one since it was written. Now on the same `login` bucket (12 per 15 min), keyed on the caller so nobody can lock Abdullah out of his own site. |
| 34 | Authentication hardening | **[V]** The plaintext `TITAN_USERNAME`/`TITAN_PASSWORD` comparison is now **unreachable the moment a founder account exists** — it retires itself, with no second deploy and no flag to remember. |
| 34 | Secret exposure | **[V]** `/api/auth` is a public endpoint. It now reports *which* login is in force but deliberately carries **no address** — publishing the one account that administers the system would hand a passer-by half the credentials. There is a test. |
| 48 | Error handling | **[V]** `hmac.compare_digest` raises `TypeError` on non-ASCII `str`, so a username with an accent in it returned **500** from `/api/login`. Now a clean 401. |
| 2 | The wider role set | **[V]** `core/orgs.py`. Ranked roles — `viewer < member < manager < admin < owner` — compared in one place by `require_member(org, user, minimum)`. The brief's *Executive* maps to `identity.FOUNDER`, who administers the whole SaaS rather than one organisation; that is a different axis and stays one. |
| 35 | Multi-tenant isolation, attacked | **[V]** Two adversarial route walks now, both fail-open: one over `/api/account` (11 routes) and a new one over `/api/org`. Both attack with a caller who legitimately owns something else — the case that finds real bugs. Found and fixed a boundary that was real code with **no test behind it**: deleting `fix["client_id"] != cid` left 478 tests green. |
| 33 | Audit log | **[V]** `core/audit.py`, migration 6. Append-only — there is no update or delete function, not a guarded one. Secrets are redacted **on the way in**, because a value that reaches the table is already on the disk and in every backup. Refused actions are recorded too. Says `durable: false` out loud. |
| 12 | Tiered trials | **[V]** Already existed and is better than the brief asks: `billing._DEFAULT_TRIAL_DAYS` is one central config, overridable per plan by environment variable **without a deploy**, and `as_dict()` publishes `trial_billable` so the product never advertises a conversion that cannot happen. |
| 43 | "Free for X days" on the pricing page | **[V]** The API published `trial_days` and the page never displayed it. Now rendered from `/api/plans`, with a test that **fails if a number is typed into the JSX** — the brief's own rule that marketing copy must not be a second source of truth. |
| 16/17 | Executive metrics, built honestly | **[V]** `core/metrics.py`. MRR, ARR, churn, conversion, trial counts, plan distribution — every one returns `{value, measured, reason}` and **`value` is `null`, never `0`, whenever `measured` is false**. With no processor connected, MRR reads "Billing is not connected", not `$0`. `GET /api/founder/metrics`. |
| 16 | Churn made measurable at all | **[V]** Migration 7, `subscription_events`. `set_plan()` overwrote the plan in place and emitted an in-memory event, so churn and trial-to-paid conversion were not "hard to compute" — they were **unmeasurable by construction**, and any figure shown would have been invented. Now recorded append-only. |
| 45 | Feature flags | **[V]** `core/flags.py`, migration 8. Five layers — user, org, environment, plan, default — and `explain()` returns **which one decided**. "It is off for this customer" is not actionable; "the plan layer said no" is. An unknown key raises rather than reading as off. |
| 21 | Onboarding score | **[V]** `core/onboarding.py`. Every step is **detected**, never remembered — nothing is done because a wizard was completed. A check that cannot run answers *unknown*, is excluded from the denominator, and is not turned into a to-do: scoring an account down for our outage blames the customer for it. |
| 26 | Integration health centre | **[V]** `core/integrations.py`. Aggregates the `status()`/`configured()` functions each subsystem already owns rather than reimplementing them. A check that raises reads `unknown`, never `not_configured`. Every row states its **cost**, so nobody enables a feature and receives a bill. |
| 38 | Global search | **[V]** `core/search.py`. Organisations, people, businesses, accounts — and **domains matched on host**, so `https://www.x.com/path` and `x.com` find the same business. Every hit says what it matched on. Founder-scoped by design, and the module says why a per-tenant version needs its own function rather than a boolean. |
| 39 | Notification centre | **[V]** `core/notifications.py`. Conditions checked at read time, so one disappears when it is fixed rather than sitting unread. Critically, it publishes `not_emitted` — *trial ending* and *payment failed* are deliberately absent, each naming the missing data, instead of being faked. |
| 31 | Self-improvement actually running | **[V]** `improve.check_active()` — the auto-rollback that re-measures every ACTIVE change and reverts regressions — was tested, mutation-guarded, and **called by nothing in production**. Now on the heartbeat. Third instance of this exact defect shape, after `knowledge.backfill()` and `params.apply_stored()`. |

### Two defects found in passing and fixed

* **`core/identity.py` had zero callers.** It was shipped, tested, and dead —
  exactly the `knowledge.backfill()` trap `CONTINUE_HERE.md` §9 warns about
  ("grep for CALLERS, not just definitions"). It is now on the login path.
* **A mutation guard that only half worked.** `if role not in ROLES:` appeared
  twice in `identity.py`; the mutation tool replaces the **first** match, so
  removing the check only ever disarmed `create()` and `set_role()` was never
  tested against its own guard being gone. Both now go through one
  `_require_role()`, so one anchor covers both call sites.

---

## 2. Already built — do NOT rebuild

| § | Topic | Where |
|---|---|---|
| 24 | Human approval system | **[H]** `core/approvals.py`; `site_fix` has no auto-apply flag by design |
| 25 | API key vault | **[H]** `core/site_access.py`, encrypted through `core/appsecret.py` |
| 27 | Website audit centre | **[H]** `engines/client_seo.py`, real measurements, "not audited" when absent |
| 30 | Provider abstraction | **[H]** `core/model_router.py`, `core/api_adapters.py` |
| 31 | "Make Titan better" | **[H]** `core/improve.py` + `core/params.py` — observe → propose → measure → named human approves → activate → auto-rollback |
| 32 | System health | **[H]** `core/obs.py`, durable queue stats, `db.stats()` reporting `durable: false` honestly |
| 35 | Multi-tenancy | **[V]** `core/tenancy.py` exists; **[H]** tenant gate shipped. See §4 below for what is still missing. |
| 45/46 | Usage limits | **[H]** plan quotas in `core/billing.py` |
| 47 | Never fake data | **[H]** The spine rule of the codebase. Cost is `null` not `0.00`; a granted seat is not revenue. |
| 51 | Observability | **[H]** `core/obs.py`, structured request logs with request ids |

---

## 3. Blocked on Abdullah — not on engineering

These are unchanged from `CONTINUE_HERE.md` §4. **Do not build around them.**

1. **`TITAN_FOUNDER_EMAIL` on the Space.** This is now the single variable that
   completes the authentication cutover. Until it is set, Titan keeps using the
   environment gate and says so on `/api/auth`.
2. **Paddle keys** — `PADDLE_API_KEY` + `PADDLE_PRICE_ID_{...}`. Nothing can be
   sold, so §11/§12/§17/§18/§19/§43 all multiply zero.
3. ~~zashmart.com must pass the `Authorization` header through.~~
   **RE-MEASURED 2026-08-20: gone.** Hostinger is already passing it. All
   that is missing is a WordPress **Application Password** created by the
   site owner — not a hosting login. See
   [`CONNECTING_A_WORDPRESS_SITE.md`](CONNECTING_A_WORDPRESS_SITE.md).
4. **A host for `services/renderer/`** (~1GB RAM).
5. **HF persistent storage** — without it the identity table, and every account
   in it, is wiped on each rebuild. The founder row re-seeds from the
   environment; customer accounts would not.
6. **`TITAN_STREET` / `TITAN_LOCALITY` / `TITAN_COUNTRY`.**

---

## 4. Real work, genuinely not started

Honest list. None of this is stubbed or faked anywhere in the product.

| § | Topic | Note |
|---|---|---|
| 3–4 | Executive user management + create-customer flow | Organisations now exist underneath it; the Executive-facing screens do not. |
| 5–8 | Progressive signup, onboarding, website detection, WordPress connect | Detection half exists **[H]**; the guided flow does not. |
| 13–14 | Trial anti-abuse, Executive trial control | The trial *engine* (§12) already existed and the pricing page now displays it (§43). These two need billing to be real. |
| 15 | Customer 360 | Organisations exist now; the screen does not. Its Usage and Activity panels need billing on organisations first. |
| 26 | Integration health centre | |
| 38–42 | Global search, notifications, transactional email, quick actions, support mode | |
| 3 | Billing migrated onto organisations | Deliberately not done. The subscriber path is the one that takes money; moving it in the same change that introduces the table underneath is how a paying customer loses access. |

## 5. Built, and honest about what it cannot yet see

§16 was previously listed here as "cannot be built honestly". That was half
right. The *engine* can be built now; what cannot be invented is the data.

`core/metrics.py` computes MRR, ARR, churn, conversion, trial counts and plan
distribution today, and each one carries whether it was measured. With zero
customers and no processor:

| Metric | Today | Why |
|---|---|---|
| customers, plan distribution | **measured** | durable account state |
| conversion | **measured** once one account exists | account state |
| MRR / ARR | **not measured** | no processor — nobody *could* pay, so `$0` would be a claim |
| churn | **not measured** | no paid subscription has existed to be lost |
| trial customers | **not measured** | `billing` has no per-account `trial_ends_at` at all |

Every "not measured" carries a reason that names what is missing, so it is
actionable rather than a shrug. The moment Paddle is configured, MRR becomes a
real number — and `0.0` then genuinely means nobody paid.

§20 (usage-based upgrade prompts) still needs real usage.

---

## What to do next, in order

1. Set `TITAN_FOUNDER_EMAIL` (+ a `TITAN_PASSWORD` of 12+ characters) on the
   Space. That completes the cutover and retires the environment gate.
2. ~~Organisations~~ and ~~tenant-isolation tests that attack~~ — **both done
   2026-08-20.** Next on that thread: migrate billing onto organisations, then
   provision a customer through the generic flow with no customer-specific
   code path.
3. A WordPress **Application Password** for zashmart.com. The header blocker
   was re-measured and is gone — see `CONNECTING_A_WORDPRESS_SITE.md`.
4. Paddle. Everything monetary is downstream of it.
