# Cost-aware model routing

`core/model_router.py`. One module, wired into `llm.complete()` — the single
place all ~25 model call sites in Titan go through.

## What is measured and what is declared

Kept apart on purpose. Reading a declared policy as a measurement is how a
router starts lying.

| | Source | Status |
|---|---|---|
| Per-provider success rate, latency | `core/routing.py` | **MEASURED** |
| Published per-token price | `core/model_catalog.py` (OpenRouter `/models`) | **MEASURED** |
| Which tier a provider is trusted for | `_DEFAULT_TIERS` + env override | **DECLARED** |

Titan has no per-model quality benchmark, so any "this model is smarter"
ranking would be invented. Tier is therefore configuration, and `explain()`
labels every factor with which of the two it is.

## Cost is estimated, never claimed as actual

**No provider returns token usage through `llm.complete()`.** So Titan cannot
know what a call actually cost. It estimates from the prompt it sent (~4 chars
per token) and the published price.

- `estimated_cost_usd` — a real number, clearly labelled.
- `actual_cost_usd` — **always `null`**, with the reason attached.

Capturing real usage means threading it back out of all five `_complete_*`
functions. That is the next step and is **not done**.

## A missing price is not a free price

A model the catalogue does not know gets `None`, and `None` sorts **last** on
cost. The `-1` "priced dynamically" sentinel already taught this repo that an
unknown price read as a number yields a negative cost.

`estimate_cost` is trusted only when its own `measured: True` flag is set — a
number arriving with `measured: False` is a fallback guess, not a price.

## Task metadata

Four fields. Every extra one is something a caller has to get right.

```python
Task(name="voice_answer", tier=STANDARD, high_risk=False, max_cost_usd=None)
```

- `name` — telemetry key
- `tier` — `fast` | `standard` | `premium`
- `high_risk` — floor-limited to at least `standard`, whatever the tier says
- `max_cost_usd` — refuse a provider estimated above this; **an unknown
  estimate is also refused**, because the caller asked for a ceiling this
  module cannot guarantee

Passing no task at all means `STANDARD`, which is exactly the old behaviour —
that default is what let 25 existing call sites stay untouched.

## The policy, in one comparison

- **FAST** work is a cost decision: price leads.
- **Anything above FAST** is a reliability decision: measured success leads,
  because a cheap answer that fails costs a retry *and* the original call.
- Unknown reliability sits between measured-good and measured-bad rather than
  winning or losing outright.
- No eligible provider is a **refusal**, never a silent downgrade.

Routing is deterministic (a test runs the same decision six times) and never
calls a model to decide which model to call — it is dict lookups and a sort.

## Security

Choosing a provider is not choosing whether an action is allowed. Approval
gates, tool permissions and tenant checks live elsewhere and are unreachable
from here — a test parses the module's AST and fails on any attribute access
named `approve`, `require_owner`, `publish`, `activate`, `apply` or `invoke`.

A high-risk task cannot be dropped to a provider trusted only for FAST work
merely because that provider is cheaper. Mutation-guarded.

## Configuration

```bash
TITAN_TIER_CLAUDE=premium      # override any provider's declared tier
TITAN_TIER_GROQ=standard
TITAN_AI_DAILY_BUDGET_USD=5    # unset means NO budget, not a budget of zero
```

Defaults: claude/openai `premium`, groq/gemini `standard`, hermes `fast`
(OpenRouter's free catalogue rotates, so it is trusted for the cheap end only
until something measures otherwise).

A malformed budget value is reported as *no budget configured*, never silently
treated as a limit.

## Telemetry

`GET /api/economics` (founder-only). Per task and per provider: calls, ok,
failed, fallbacks, success rate, average latency, estimated cost, and
**priced vs unpriced call counts kept separate** so an unpriced provider never
looks free. Plus the last 25 routing decisions with their one-line reason.

`success_rate` and `avg_latency_ms` are `None` until something has happened —
a 0% success rate on zero calls is a claim about a provider nobody tried.

## Adding a model

1. Add the provider to `llm._provider_chain()` and `_DISPATCH`.
2. Add its model id to `model_router._model_id()` so it can be priced. A
   provider that resolves its model at call time (gemini, hermes) has no fixed
   id and stays unpriced — that is correct, not a gap to paper over.
3. Give it a tier in `_DEFAULT_TIERS`, or leave it to default to `fast`.

## Testing routing

```bash
python -m pytest tests -q -k "router or routed or cheapest_eligible or high_risk_task"
python -m evaluation.mutation_check --only "router:"
```
