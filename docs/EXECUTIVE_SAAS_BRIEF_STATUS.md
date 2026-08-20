# "World-class SaaS / Executive Control Center" brief — status map

Abdullah sent a 61-section brief (2026-08-20) to turn Titan Omega into a
polished multi-tenant SaaS with an Executive control centre, an RBAC model, a
subscription and trial engine, progressive onboarding and an integration hub.

This file is the audit the brief's §1 asks for, and the honest answer to its
§61 ("do not stop after writing a plan"): **§2/§34/§35 — the authentication and
authorisation spine — was implemented this session**, and everything else is
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
3. **zashmart.com** must pass the `Authorization` header through.
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
| 2 | The wider role set | The brief asks for Executive / Administrator / Manager / Team Member / Customer. Today the closed set is `founder` / `member`. The set is deliberately closed and refuses unknown values, so widening it is a considered change, not a typo. |
| 3–4 | Executive user management + create-customer flow | Needs organisations first. |
| 5–8 | Progressive signup, onboarding, website detection, WordPress connect | Detection half exists **[H]**; the guided flow does not. |
| 12–14 | Tiered trial engine (10/7/5 days), trial anti-abuse, Executive trial control | Blocked behind billing being real. |
| 15 | Customer 360 | Needs organisations. |
| 26 | Integration health centre | |
| 38–42 | Global search, notifications, transactional email, quick actions, support mode | |
| 35 | **Tenant-isolation tests that actually attack** | The next thing worth doing. Abdullah's own ordered list puts it third; the brief's §35 asks for the same. |

## 5. Cannot be built honestly yet

§16 (MRR, ARR, churn, conversion, plan distribution) and §20 (usage-based
upgrade prompts) need real customers. With zero customers these become
dashboards of numbers nobody measured — which the brief's own §47 forbids, and
which is the one rule this codebase is built on.

**The correct display for all of them today is "Not measured".**

---

## What to do next, in order

1. Set `TITAN_FOUNDER_EMAIL` (+ a `TITAN_PASSWORD` of 12+ characters) on the
   Space. That completes the cutover and retires the environment gate.
2. **Organisations** on top of identity, then provision a customer through the
   generic flow — no customer-specific code path.
3. **Tenant-isolation tests that attack**: tenant A reading, modifying and
   deleting tenant B, with mutation guards on the authorisation boundaries.
4. Paddle. Everything monetary is downstream of it.
