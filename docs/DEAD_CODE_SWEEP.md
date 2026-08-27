# Finding the ninth on purpose

Nine capabilities have shipped in this repository tested, documented, exposed —
and called by nothing. The first eight were all found **by accident**:

| # | What | What it meant in production |
|---|---|---|
| 1 | `knowledge.backfill()` | the semantic ranker was dead code; lowering the cosine threshold "changed nothing" because nothing ran |
| 2 | `params.apply_stored()` | approved parameter changes did not survive a boot |
| 3 | `improve.check_active()` | auto-rollback on regression was true of the function and false of the deployment |
| 4 | `core/identity.py` | an entire module — the login — shipped, tested, and unreachable |
| 5 | `clients.SESSION_TTL` | portal tokens never expired |
| 6 | `ratelimit.LIMITS["demo"]` | a limit that limited nothing |
| 7 | `ratelimit.LIMITS["discover"]` | same, spending someone else's API quota |
| 8 | `GET /api/client/social` | served, while the page hardcoded its own copy of the answer |

Every one read, in the source, exactly like working code. The tests passed. The
docstrings were accurate about what the function *did*. Nothing invoked it.

Finding the tenth by luck is not a strategy.

## The tool

`backend/evaluation/dead_code.py` walks the AST of `app/**` and reports every
public module-level function with no reference anywhere in the application.

```bash
python -m evaluation.dead_code
python -m evaluation.dead_code --json
```

It counts four kinds of reference, because a detector that cries wolf trains
people to skim its output:

* a literal call — `mod.fn()` or `fn()`
* an attribute access — `mod.fn` handed somewhere as a value
* **a bare name read** — `queue.register(AUDIT_AND_PROPOSE, audit_and_propose)`
* a string literal matching the name — a registry keyed by name is a real caller

The third one was missing from the first version, which duly reported
`fix_cycle.audit_and_propose` as dead when it is handed to `queue.register()`
one line below its own definition. Two false positives out of thirty-eight was
already enough to make the output feel like noise. Fixed before the tool was
trusted for anything.

`reset()` is exempt with a reason rather than silently: its caller *is* the test
suite, because module-level state has to be resettable between tests.

## What it found immediately: the ninth, and the worst

**`core/flags.py` — an entire feature-flag system that nothing consulted.**

It has five flags, a five-layer resolver (user > org > environment > plan >
default), an `explain()` that names which layer decided, stored overrides, a
database migration, and three founder endpoints. `is_enabled()` had **zero
callers**. The only mention of it anywhere outside its own module was in its own
docstring.

So an operator could open the flags screen, set `site_fix` to disabled, watch it
read "off" — and Titan would carry on proposing and applying edits to a
stranger's live WordPress site.

That is not decoration. It is worse than having no switch at all:

> A kill switch that does not kill is worse than no kill switch. No kill switch
> at least tells you to go and pull the plug yourself.

Somebody would have believed they had stopped it.

## The fix, in two halves

**1. Honesty, first, because it cannot be got wrong later.** Every `Flag` now
declares `enforced_at` — where it is actually consulted. `explain()` publishes
`enforced: false` and a note for any flag nothing reads:

> No code consults this flag yet, so turning it off changes nothing. Shown
> rather than hidden: a switch you believe works is worse than one you know
> does not.

Three of the five are still unenforced and now say so on the screen that offers
the switch.

**2. The two highest-risk capabilities are genuinely gated.** `site_fix` (edits
somebody else's live website) and `voice` (speaks to a business's callers) —
the two you would reach for in an incident.

`flags.require()` raises `FlagDisabled`; `flags.is_enabled()` returns a bool.
The enforcement in each place honours the contract of the function it guards:

* `site_fix.propose()` and `site_fix.apply()` **return** their error shape,
  because `propose`'s own docstring promises "Never raises" and callers depend
  on it. A kill switch that turns a safe refusal into a 500 has traded one
  incident for another.
* `voice_sessions.start()` **raises**, matching the channel check directly below
  it. A caller holding a session object has every right to assume it can speak.

`apply()` is gated separately from `propose()` on purpose: a fix proposed while
the feature was on must not still be appliable after somebody switches it off,
because that is precisely the moment they are trying to stop the writing.

## Three tests keep this from happening again

* **`test_switching_off_site_fix_actually_stops_it`** — asserts the *writing*
  stops, not that the flag reads false. Paired with
  `test_site_fix_still_works_when_the_flag_is_on`, because a gate that refuses
  everything is not a feature flag.
* **`test_every_flag_claiming_enforcement_has_a_real_call_site`** — `enforced_at`
  is a claim in a dataclass. This checks it against the source. A flag that
  *says* it is enforced and is not is worse than one that admits it, because the
  first is believed.
* **`test_no_new_uncalled_capability_appears_without_being_noticed`** — a
  ratchet, not a ban. The current list is written down with a reason for each
  entry. Adding a public function with no caller now requires wiring it up,
  deleting it, or admitting it in writing. It also fails in the other direction:
  a name that gets wired up must leave the list, so the list stays a record
  rather than folklore.

The first thing the ratchet caught was **my own dead code**: `brand_playbook.covers()`,
written earlier the same day, with `coverage()` doing the actual work. Deleted
rather than grandfathered — a list that accepts new entries on the day they are
written is not a ratchet.

## What is on the list, and what it means

Nineteen entries, each read and classified by hand. Three are worth calling out
as **real product gaps** rather than harmless leftovers:

* `billing.sign_out()` — a subscriber cannot sign out.
* `clients.set_password()` and `identity.set_password()` — **nobody can change
  a password.** Not the founder, not a subscriber, not a business.

Those are not fixed here. They are written down so the next person does not have
to find them by accident either.
