# The demo and the product

Reported by Abdullah, 2026-08-22, in these words:

> "I made an enterprise account but I cannot open it the way it is shown in the
> demo."

He was right, and it was bigger than a bug.

## What was wrong

There are four surfaces and three separate credential systems:

| Surface | Who | Credential | What it is |
|---|---|---|---|
| `/` (16 tabs) | founder ONLY | `core/auth.py` | Abdullah's own cockpit |
| `/` demo | anyone | guest token | the SAME cockpit, sample figures |
| `/join` | subscriber | `core/billing.py` | a 3-step wizard |
| `/portal` | a business | `core/clients.py` | the customer dashboard |

The public demo button showed a prospect the **founder's** dashboard. A visitor
concluded that was the product, paid for Enterprise, and received `/portal` —
a real product, and a different one.

Nobody was lied to about a number. Every figure in that demo was labelled
`SAMPLE`, and the honesty rules held throughout. **The shape of the product was
misrepresented**, which is the same offence one level up, committed by a
company whose product is checking whether other people's websites tell the
truth.

Reachability was fixed on 2026-08-22 (`clients.issue_session`, and a portal
button on `/join` step 3). That fixed *"a paying customer had nowhere to go"*.
It did not fix *"the demo sells a different product"*.

## What the fix is

`POST /api/demo/portal` mints a portal session against a **demonstration
business** and sends the visitor to `/portal`. The front door offers it first;
the cockpit tour survives as a secondary link labelled as the operator console.

Nothing in it is sample data. The demonstration businesses are the ones
`engines/demo_workspace.py` already seeds — their websites are **Titan's own
pages**, and they are genuinely re-audited every six hours by the same engine
that audits a paying customer's site. The score a visitor sees is that page's
real score. The portal shows a banner saying exactly that, driven by the
server's `is_demo` flag rather than by anything in the URL.

### Why this is safe to expose with no credential

Four independent reasons, in order of how much weight they carry:

1. **The server picks the business.** The caller cannot name one. A caller who
   can name a business is a caller who can name somebody else's, and this
   endpoint is reachable by anyone on the internet with no token at all.
   `demo_workspace.showcase()` filters on `is_demo` and returns `None` rather
   than substituting a real client — an empty demo workspace is a refusal, not
   an opportunity to show a stranger somebody's audit findings.
2. **The route checks again.** It re-tests `is_demo_client()` on whatever
   `showcase()` handed back, rather than trusting a function two modules away
   to have stayed correct.
3. **There is no write surface.** Every `/api/client/*` route reachable with a
   portal token is a GET. `test_the_customer_portal_has_no_write_surface_at_all`
   walks the real route table and **fails open**: add a POST under that prefix
   and the suite goes red, because anonymous visitors now hold portal sessions.
4. **The session expires.** See below.

Both of the first two are mutation-guarded, and getting those guards to bite
took two attempts — see "The two guards that survived".

## Portal sessions now expire

`clients.SESSION_TTL` had been declared since the module was written, with a
reason beside it ("a week; they are business owners, not attackers"), and was
**never compared against anything**. `_sessions` stored `token -> client_id`
with no timestamp, so every portal token stayed valid for the whole life of the
process.

On a free Space that rebuilds every few hours the defect was invisible. On any
container that stays up, every token ever issued was still a live key — and the
dict grew forever.

`_sessions` now stores `token -> (client_id, issued_at)`, `resolve()` enforces
the TTL, and an expired token is **dropped** rather than merely refused, so
public demo traffic cannot grow the dict without bound. One `_mint()` function
creates every token, because two call sites writing into the dict directly is
exactly how the third one gets added without an expiry.

This is the **seventh** instance of the defect shape this repository keeps
finding: defined, reasoned about, documented, and never invoked. The previous
six were `knowledge.backfill()`, `params.apply_stored()`,
`improve.check_active()`, `core/identity.py` entirely, and the two rate-limit
buckets below.

## Two rate-limit buckets were declared and never called

`ratelimit.LIMITS` had six buckets. Two had zero callers:

| Bucket | Comment beside it | Callers |
|---|---|---|
| `demo` | "demo sessions are cheap but not free" | **0** |
| `discover` | "lead discovery burns Tavily quota" | **0** |

Both now have one. `test_every_declared_rate_limit_bucket_has_a_caller` walks
`app/**/*.py` for `ratelimit.check("...")` and fails on any bucket in `LIMITS`
without one. It **fails open**: add a bucket and the test demands a caller.

A bucket with no caller is not a limit, and in the source it reads exactly like
a limit that works.

## The two guards that survived

Worth writing down, because the tests were green and wrong.

`showcase()` has two selection paths: an exact match on the named showcase URL,
then a sorted fallback. The first version of
`test_the_public_demo_can_never_open_a_real_customers_business` only ever
exercised the first path — and the demo record won that on its URL alone,
whether or not the `is_demo` filter was there. Deleting the filter changed
nothing the test could observe. `mutation_check` said `SURVIVED`.

The replacement attacks both paths:

* a real business parked on the showcase URL itself, created first (nothing
  stops a customer entering any URL they like, ours included);
* no business on the showcase URL at all, so selection falls to the sorted
  fallback — where `AAA Real Customer Ltd` beats `[DEMO] ...`, because `[` sorts
  after every capital letter.

The route's second check needed its own test, since it can only fire when
`showcase()` is already wrong: `showcase` is monkeypatched to return a real
client, and the route must refuse with 503 and hand out no token.

**A test that passes for the wrong reason is worse than no test.** It is a red
light wired to a green bulb.

## What was NOT done

The customer portal is a genuine product — audit, top-3 priorities, ready-to-
paste schema, posting week — but it is **not** the sixteen-tab cinematic
dashboard. That dashboard is the founder's console and showing it to a customer
would show them Abdullah's business.

If customers are ever meant to get something of that shape, it is a real build,
not a permission change, and **Abdullah asked to be consulted before it starts.**

Two things found while doing this and deliberately left alone, both worth a
decision rather than a silent fix:

* ~~The portal's Social tab is hardcoded restaurant advice.~~ **Fixed
  immediately afterwards**, because the demo put it on the front door.
  `brand_playbook.coverage(industry)` now says whether the weekly plan applies
  and, when it does not, why — naming the industry and naming what the playbook
  *was* measured for. The weekly plan, highlight names and pillars are
  withheld; cadence, the forbidden list and the benchmarks are not, because
  those were measured across all seven luxury profiles rather than derived for
  food. `GET /api/client/social` turned out to be the **eighth** zero-caller in
  this codebase: it existed, was registered, was served, and the page hardcoded
  its own copy of the answer instead.
* `/api/client/seo` runs a **live crawl on every call**, so each demo visit
  costs one request to Titan's own site. Bounded by the `demo` bucket now
  (30/hour per caller), and worth watching if the demo ever gets traffic.
