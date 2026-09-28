"""Cost-aware model routing: the cheapest provider that still meets the bar.

Every model call goes through `llm.complete()`, so routing lives there. The
provider chain comes from which API keys are set and is ordered by measured
health; this adds what the task is and what it costs.

Measured vs declared, kept apart:

  MEASURED  Per-provider success rate and latency, from `core/routing.py`.
            Published per-token prices, from `core/model_catalog.py` (which
            reads OpenRouter's live `/models`).
  DECLARED  Which tier a provider is trusted for. There's no per-model
            quality benchmark, so this is configuration with a conservative
            default, overridable per provider.

`explain()` labels every factor as measured or declared.

Cost is estimated, never reported as actual. None of the provider paths return
token usage through `llm.complete`, so Titan can only estimate from the prompt
and the published price. Every figure is `estimated_cost_usd`, and
`actual_cost_usd` is None with a reason.

A missing price isn't a free price. A provider the catalogue doesn't know gets
None, which sorts last on cost, not first.

Routing never touches permissions. Choosing a provider isn't choosing whether
an action is allowed; approval gates, tool permissions and tenant checks live
elsewhere, and a test parses this module's AST to make sure it can't reach
them. High-risk tasks also have a floor: they can't be moved to a provider
trusted only for FAST work because it's cheaper.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

FAST, STANDARD, PREMIUM = "fast", "standard", "premium"
TIER_ORDER = (FAST, STANDARD, PREMIUM)

# Declared, not measured. Conservative defaults: each provider is trusted for
# the tier it can plausibly serve, and each can be overridden with an env var
# (TITAN_TIER_GROQ=premium, etc).
_DEFAULT_TIERS = {
    "claude": PREMIUM,
    "openai": PREMIUM,
    "groq": STANDARD,
    "gemini": STANDARD,
    # OpenRouter's free catalogue is whatever is free today, so it's trusted for
    # the cheap end only until something measures otherwise.
    "hermes": FAST,
}

# Rough on purpose: ~4 characters per token is close enough for English prose,
# and it's only used for estimates.
_CHARS_PER_TOKEN = 4

_lock = threading.RLock()
# task -> provider -> counters. Everything is counted, never sampled.
_stats: dict[str, dict[str, dict]] = {}
_decisions: list[dict] = []
MAX_DECISIONS = 200


@dataclass(frozen=True)
class Task:
    """The smallest metadata that changes a routing decision.

    Four fields: every extra one is something else a caller has to get right,
    and none would change what gets chosen.
    """
    name: str                              # telemetry key, e.g. "voice_answer"
    tier: str = STANDARD
    high_risk: bool = False                # never downgraded below STANDARD
    max_cost_usd: Optional[float] = None   # refuse a call estimated above this

    def floor(self) -> str:
        """The lowest tier this task may be served by."""
        if self.high_risk and TIER_ORDER.index(self.tier) < TIER_ORDER.index(STANDARD):
            return STANDARD
        return self.tier


# Named profiles, so a call site declares what it is instead of repeating a
# policy. Anything not listed is STANDARD, which is the old behaviour, so an
# untagged call site is unchanged.
PROFILES: dict[str, "Task"] = {}


def _profile(name: str, tier: str = STANDARD, *, high_risk: bool = False,
             max_cost_usd: Optional[float] = None) -> "Task":
    task = Task(name=name, tier=tier, high_risk=high_risk,
                max_cost_usd=max_cost_usd)
    PROFILES[name] = task
    return task


def provider_tier(provider: str) -> str:
    """DECLARED tier for a provider. Env override wins."""
    override = os.getenv(f"TITAN_TIER_{provider.upper()}", "").strip().lower()
    if override in TIER_ORDER:
        return override
    return _DEFAULT_TIERS.get(provider, FAST)


def _model_id(provider: str) -> Optional[str]:
    from . import llm
    return {
        "claude": os.getenv("TITAN_MODEL", "claude-opus-4-8"),
        "groq": os.getenv("TITAN_GROQ_MODEL", "openai/gpt-oss-120b"),
        "openai": os.getenv("TITAN_OPENAI_MODEL", "gpt-4o-mini"),
        # These resolve a model at call time from a live catalogue, so there's no
        # fixed id to price. Unknown, not guessed.
        "gemini": None,
        "hermes": None,
    }.get(provider, getattr(llm, "MODEL", None))


def estimated_cost(provider: str, prompt_chars: int,
                   max_tokens: int) -> Optional[float]:
    """Published price x estimated tokens, or None when either is unknown."""
    from . import model_catalog

    model_id = _model_id(provider)
    if not model_id:
        return None
    prompt_tokens = max(1, int(prompt_chars / _CHARS_PER_TOKEN))
    try:
        out = model_catalog.estimate_cost(
            model_id, prompt_tokens=prompt_tokens,
            completion_tokens=int(max_tokens))
    except Exception:
        return None
    # `measured` is the catalogue's flag for a real published price; it's False for
    # an unknown model, a missing price, or no token counts. Using `usd` without it
    # would read None as free.
    if not isinstance(out, dict) or not out.get("measured"):
        return None
    cost = out.get("usd")
    # A negative cost means the "priced dynamically" sentinel was read as a price.
    # Unknown, never negative.
    if not isinstance(cost, (int, float)) or cost < 0:
        return None
    return float(cost)


def _reliability(provider: str) -> Optional[float]:
    """MEASURED success rate, or None below the evidence threshold."""
    from . import routing
    try:
        rows = (routing.report() or {}).get("providers") or []
    except Exception:
        return None
    for row in rows:
        if row.get("provider") != provider:
            continue
        # `routable` is routing.py's "enough evidence to rank on" flag
        # (calls >= MIN_CALLS). Below it there's no rate to report.
        if not row.get("routable"):
            return None
        # routing.report() publishes success_rate as a PERCENTAGE (0-100).
        rate = row.get("success_rate")
        if not isinstance(rate, (int, float)):
            return None
        return round(float(rate) / 100.0, 3)
    return None


def eligible(task: Task, chain: list) -> list:
    """Providers allowed to serve this task, in the caller's order."""
    floor_idx = TIER_ORDER.index(task.floor())
    return [p for p in chain
            if TIER_ORDER.index(provider_tier(p)) >= floor_idx]


def decide(task: Task, chain: list, *, prompt_chars: int = 0,
           max_tokens: int = 1500) -> dict:
    """Choose an order of providers to try. Deterministic and explainable.

    Never asks a model which model to use - that would cost more than it
    saves. Everything here is a dict lookup and a sort.
    """
    allowed = eligible(task, chain)
    dropped = [p for p in chain if p not in allowed]

    rows = []
    for provider in allowed:
        cost = estimated_cost(provider, prompt_chars, max_tokens)
        rows.append({
            "provider": provider,
            "tier": provider_tier(provider),
            "estimated_cost_usd": cost,
            "reliability": _reliability(provider),
            "position": chain.index(provider),
        })

    # The whole policy in one comparison. FAST work is a cost decision, so price
    # leads. Anything above FAST is a reliability decision first, because a cheap
    # answer that fails costs a retry on top of the original call. Unknown cost
    # sorts last: it isn't free, it's unmeasured.
    cost_first = task.floor() == FAST

    def key(r):
        cost = r["estimated_cost_usd"]
        cost_key = (cost is None, cost if cost is not None else 0.0)
        rel = r["reliability"]
        # Unknown reliability sits between measured-good and measured-bad
        # rather than winning or losing outright.
        rel_key = (0 if rel is None else -rel, r["position"])
        return (cost_key, rel_key) if cost_first else (rel_key, cost_key)

    rows.sort(key=key)

    # A task with a cost ceiling refuses providers estimated above it. An unknown
    # estimate isn't let through either - the caller asked for a guarantee this
    # can't give.
    over_budget = []
    if task.max_cost_usd is not None:
        keep = []
        for r in rows:
            cost = r["estimated_cost_usd"]
            if cost is None or cost > task.max_cost_usd:
                over_budget.append(r["provider"])
            else:
                keep.append(r)
        rows = keep

    order = [r["provider"] for r in rows]
    decision = {
        "task": task.name,
        "tier": task.floor(),
        "high_risk": task.high_risk,
        "order": order,
        "selected": order[0] if order else None,
        "candidates": rows,
        "dropped_below_tier": dropped,
        "dropped_over_budget": over_budget,
        "policy": "cost-first" if cost_first else "reliability-first",
        # Stated every time so nobody mistakes an estimate for a bill.
        "estimated_cost_usd": rows[0]["estimated_cost_usd"] if rows else None,
        "actual_cost_usd": None,
        "actual_cost_note": (
            "No provider returns token usage through llm.complete(), so the "
            "actual cost of a call is not measured. This figure is an estimate "
            "from the prompt size and the published price."),
        "decided_at": time.time(),
    }
    return decision


def explain(decision: dict) -> str:
    """One sentence a human can check, labelling measured vs declared."""
    if not decision.get("selected"):
        return ("No provider was eligible: "
                f"{decision.get('dropped_below_tier') or 'none configured'} "
                f"below the {decision.get('tier')} floor, "
                f"{decision.get('dropped_over_budget') or 'none'} over budget.")
    top = decision["candidates"][0]
    cost = top["estimated_cost_usd"]
    rel = top["reliability"]
    return (
        f"{top['provider']} for {decision['task']}: trusted for "
        f"{top['tier']} (declared), "
        + (f"measured success {rel:.0%}" if rel is not None
           else "no measured success rate yet")
        + ", "
        + (f"estimated ${cost:.6f}" if cost is not None
           else "price not published for this model")
        + f"; policy {decision['policy']}."
    )


def record(task: str, provider: str, *, ok: bool, latency_ms: int,
           estimated_cost_usd: Optional[float] = None,
           fallback: bool = False) -> None:
    """Count what happened. Counted, never sampled."""
    with _lock:
        by_provider = _stats.setdefault(task, {})
        row = by_provider.setdefault(provider, {
            "calls": 0, "ok": 0, "failed": 0, "fallbacks": 0,
            "latency_ms_total": 0, "estimated_cost_usd": 0.0,
            "priced_calls": 0,
        })
        row["calls"] += 1
        row["ok" if ok else "failed"] += 1
        if fallback:
            row["fallbacks"] += 1
        row["latency_ms_total"] += max(0, int(latency_ms))
        if estimated_cost_usd is not None:
            row["estimated_cost_usd"] += float(estimated_cost_usd)
            row["priced_calls"] += 1


def note_decision(decision: dict) -> None:
    """Keep the last few decisions so the dashboard can show real ones."""
    with _lock:
        _decisions.append({
            "task": decision.get("task"),
            "selected": decision.get("selected"),
            "tier": decision.get("tier"),
            "policy": decision.get("policy"),
            "estimated_cost_usd": decision.get("estimated_cost_usd"),
            "reason": explain(decision),
            "at": decision.get("decided_at"),
        })
        del _decisions[:-MAX_DECISIONS]


def _summarise(row: dict) -> dict:
    calls = row["calls"]
    return {
        "calls": calls,
        "ok": row["ok"],
        "failed": row["failed"],
        "fallbacks": row["fallbacks"],
        # None until something happened; a 0% success rate on zero calls says nothing.
        "success_rate": round(row["ok"] / calls, 3) if calls else None,
        "avg_latency_ms": round(row["latency_ms_total"] / calls, 1) if calls else None,
        # Sums only the calls whose price was known, and says how many that was, so an
        # unpriced provider doesn't look free.
        "estimated_cost_usd": (round(row["estimated_cost_usd"], 6)
                               if row["priced_calls"] else None),
        "priced_calls": row["priced_calls"],
        "unpriced_calls": calls - row["priced_calls"],
    }


def economics() -> dict:
    """Cost and reliability by task and by provider. Real counts only."""
    with _lock:
        tasks = {t: {p: _summarise(r) for p, r in provs.items()}
                 for t, provs in _stats.items()}
        recent = list(_decisions[-25:])

    by_provider: dict[str, dict] = {}
    for provs in _stats.values():
        for provider, row in provs.items():
            acc = by_provider.setdefault(provider, {
                "calls": 0, "ok": 0, "failed": 0, "fallbacks": 0,
                "latency_ms_total": 0, "estimated_cost_usd": 0.0,
                "priced_calls": 0})
            for key in acc:
                acc[key] += row[key]
    by_provider = {p: _summarise(r) for p, r in by_provider.items()}

    total_calls = sum(r["calls"] for r in by_provider.values())
    priced = sum(r["priced_calls"] for r in by_provider.values())
    spend = sum(r["estimated_cost_usd"] or 0.0 for r in by_provider.values())

    return {
        "by_task": tasks,
        "by_provider": by_provider,
        "recent_decisions": recent,
        "total_calls": total_calls,
        "estimated_spend_usd": round(spend, 6) if priced else None,
        "priced_calls": priced,
        "unpriced_calls": total_calls - priced,
        "actual_spend_usd": None,
        "budget": budget_status(),
        "note": ("Costs are ESTIMATED from prompt size and published prices. "
                 "No provider returns token usage through llm.complete(), so "
                 "actual spend is not measured and is reported as null rather "
                 "than as an estimate wearing a different label. Calls whose "
                 "model has no published price are counted separately instead "
                 "of being treated as free."),
    }


def budget_status() -> dict:
    """The configured ceiling, or None if there isn't one."""
    raw = os.getenv("TITAN_AI_DAILY_BUDGET_USD", "").strip()
    if not raw:
        return {"configured": False, "limit_usd": None,
                "note": "No AI budget is configured, so none is enforced."}
    try:
        limit = float(raw)
    except ValueError:
        return {"configured": False, "limit_usd": None,
                "note": f"TITAN_AI_DAILY_BUDGET_USD={raw!r} is not a number, "
                        f"so no budget is enforced."}
    return {"configured": True, "limit_usd": limit,
            "note": "Enforced against ESTIMATED spend, which is the only "
                    "figure available; it is not a billing guarantee."}


def reset() -> None:
    with _lock:
        _stats.clear()
        del _decisions[:]


# --- the declared profiles --------------------------------------------------
# Tagged only where the tier differs from STANDARD. An untagged call site is
# STANDARD by design and behaves as before, so this could roll out without
# touching every caller.

# Cheap, frequent, simple transformations where a premium model adds nothing.
# This is where most of the savings come from.
KEYWORDS = _profile("keywords", FAST)
CAPTION = _profile("caption", FAST)
FORMAT_REPORT = _profile("format_report", FAST)
FORMAT_ANSWER = _profile("format_answer", FAST)
SCORE_LEADS = _profile("score_leads", FAST)
REPURPOSE = _profile("repurpose", FAST)

# Normal agent work. Explicit rather than defaulted, so the intent is clear.
OUTREACH_DRAFT = _profile("outreach_draft", STANDARD)
JOB_PROPOSAL = _profile("job_proposal", STANDARD)

# Spoken to a client's own callers. The verification layer already rejects
# invented figures here; high_risk stops the router from moving it to the cheap
# tier to save a fraction of a cent. A wrong closing time sends a customer to a
# locked door.
VOICE_ANSWER = _profile("voice_answer", STANDARD, high_risk=True)

# The founder's business intelligence and the client-facing SEO report. Both
# get read and acted on, so they get the strongest configured model.
EXECUTIVE = _profile("executive_command", PREMIUM)
SEO_REPORT = _profile("seo_report", PREMIUM)
