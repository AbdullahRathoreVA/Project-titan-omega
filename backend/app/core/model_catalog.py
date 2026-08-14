"""Model metadata from OpenRouter — the honest route out of `cost: null`.

Every cost figure in Titan is `null`, correctly, because nothing has ever
measured one. That is defensible but it is not free: a founder cannot see what
the product costs to run, and a plan cannot be priced against a cost nobody
knows.

OpenRouter publishes a `/api/v1/models` endpoint carrying, per model, the
context length, the modalities, and **the per-token price**. That is the
missing input. With it, a token count from a real completion becomes a real
cost, arrived at by multiplying two measured numbers rather than by guessing.

Deliberate decisions:

**No SDK.** OpenRouter ships an official Apache-2.0 Python SDK, and adding it
would be a new dependency for HTTP calls Titan already makes with `httpx`. The
research artifact (`repository_research/openrouter.md`) records this as ADAPT,
not ADOPT, for exactly that reason.

**The catalogue is a cache, not a source of truth about Titan.** It says what a
model costs per token. It does not say what Titan spent. `estimate_cost()`
returns `None` — never `0.0` — when the model is unknown, when the price is
absent, or when no token count was actually reported by the provider. An
estimate is labelled an estimate everywhere it surfaces.

**It degrades to nothing.** No key, no network, stale cache: every function
returns empty or `None` and says why. Nothing in Titan depends on this being
reachable, and no request path blocks on it.

**Free models are marked.** OpenRouter's catalogue includes genuinely free
models (`:free` suffix, zero price). Titan runs on no budget, so "which
capable models cost nothing" is a first-class question this answers from data
rather than from a hardcoded list that rots.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Model metadata changes on the order of days. Six hours keeps it fresh without
# making Titan a nuisance to a free endpoint.
TTL = float(os.getenv("TITAN_MODEL_CATALOG_TTL", str(6 * 3600)))
TIMEOUT = 20.0

_lock = threading.RLock()
_models: dict[str, dict] = {}
_fetched_at: Optional[float] = None
_error: str = ""


def _parse(rows: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        pricing = row.get("pricing") or {}

        def _price(key: str) -> Optional[float]:
            """Price per token as a float, or None. Never 0.0 by accident.

            Three distinct facts that a naive float() collapses into one:

            * OpenRouter returns prices as STRINGS ("0.0000007").
            * A genuinely free model returns "0" — a measured zero.
            * A MISSING field means the price is unknown, which is not free.

            And one sentinel, found by running this against the live endpoint
            rather than a fixture: the router models (`openrouter/auto`,
            `openrouter/fusion`, …) publish **"-1"**, meaning "priced
            dynamically, we cannot tell you in advance". Taken literally that
            made them sort as the cheapest models available and would have
            produced a NEGATIVE cost on the founder's screen. A negative cost
            is worse than a null one: null is honest about not knowing, and
            -$0.0004 is a confident lie. Any negative price is unknown.
            """
            raw = pricing.get(key)
            if raw is None or raw == "":
                return None
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None
            return None if value < 0 else value

        arch = row.get("architecture") or {}
        prompt_price = _price("prompt")
        completion_price = _price("completion")
        out[row["id"]] = {
            "id": row["id"],
            "name": row.get("name") or row["id"],
            "context_length": row.get("context_length"),
            "prompt_price_per_token": prompt_price,
            "completion_price_per_token": completion_price,
            # True only when BOTH prices are known AND both are zero. Unknown
            # pricing is not free, it is unknown.
            "is_free": (prompt_price == 0.0 and completion_price == 0.0
                        if prompt_price is not None
                        and completion_price is not None else None),
            "input_modalities": arch.get("input_modalities") or [],
            "output_modalities": arch.get("output_modalities") or [],
            "supports_vision": "image" in (arch.get("input_modalities") or []),
        }
    return out


def refresh(force: bool = False) -> dict:
    """Fetch the catalogue. Never raises, never blocks a request path."""
    global _fetched_at, _error
    with _lock:
        fresh = (_fetched_at is not None
                 and time.time() - _fetched_at < TTL and _models)
        if fresh and not force:
            return {"ok": True, "cached": True, "models": len(_models)}

    try:
        import httpx
        from . import obs

        headers = {"Accept": "application/json"}
        key = os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with obs.timed("model_catalog.refresh"):
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.get(CATALOG_URL, headers=headers)
        if r.status_code >= 400:
            with _lock:
                _error = f"OpenRouter replied {r.status_code}."
            return {"ok": False, "error": _error, "models": len(_models)}
        rows = (r.json() or {}).get("data") or []
        parsed = _parse(rows)
        if not parsed:
            with _lock:
                _error = "The catalogue response contained no models."
            return {"ok": False, "error": _error, "models": len(_models)}
        with _lock:
            _models.clear()
            _models.update(parsed)
            _fetched_at = time.time()
            _error = ""
        return {"ok": True, "cached": False, "models": len(parsed)}
    except Exception as e:
        with _lock:
            _error = f"Could not reach the catalogue ({type(e).__name__})."
        return {"ok": False, "error": _error, "models": len(_models)}


def get(model_id: str) -> Optional[dict]:
    with _lock:
        return dict(_models[model_id]) if model_id in _models else None


def estimate_cost(model_id: str, *, prompt_tokens: Optional[int] = None,
                  completion_tokens: Optional[int] = None) -> dict:
    """Cost of one call, or `None` with the reason. NEVER 0.0 as a stand-in.

    Two measured numbers multiplied together is a measurement. Either one
    missing makes the answer unknown, and unknown is `None` — a `0.00` on a
    founder's screen reads as "this was free", which is a different and false
    claim.
    """
    model = get(model_id)
    if model is None:
        return {"usd": None, "measured": False,
                "reason": (f"{model_id} is not in the catalogue, so its price "
                           f"is unknown. Run refresh(), or the model is not "
                           f"served by OpenRouter.")}
    if prompt_tokens is None and completion_tokens is None:
        return {"usd": None, "measured": False,
                "reason": ("No token counts were reported for this call, so "
                           "there is nothing to price.")}
    p_rate = model["prompt_price_per_token"]
    c_rate = model["completion_price_per_token"]
    if p_rate is None or c_rate is None:
        return {"usd": None, "measured": False,
                "reason": f"The catalogue carries no price for {model_id}."}

    total = (p_rate * (prompt_tokens or 0)) + (c_rate * (completion_tokens or 0))
    return {
        "usd": round(total, 8),
        "measured": True,
        "model": model_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reason": ("Measured token counts multiplied by the published "
                   "per-token price. This is the provider's list price, not a "
                   "billed invoice — the invoice remains the only authority on "
                   "what was actually charged."),
    }


def free_models(*, min_context: int = 0, vision: bool = False) -> list[dict]:
    """Capable models that cost nothing, from the catalogue rather than a list.

    Titan runs on no budget, so this is a first-class question. A hardcoded
    list of free models rots within weeks; this is answered from data.
    """
    with _lock:
        rows = list(_models.values())
    out = [m for m in rows
           if m["is_free"] is True
           and (m["context_length"] or 0) >= min_context
           and (m["supports_vision"] if vision else True)]
    return sorted(out, key=lambda m: -(m["context_length"] or 0))


def candidates(*, needs_vision: bool = False, min_context: int = 0,
               max_cost_per_1k: Optional[float] = None) -> list[dict]:
    """Models meeting a capability requirement, cheapest first.

    Capability comes from the catalogue, not from a name. Selecting a model by
    popularity is how a router ends up sending a vision task to a text-only
    model and reporting the refusal as a failure.
    """
    with _lock:
        rows = list(_models.values())
    out = []
    for m in rows:
        if needs_vision and not m["supports_vision"]:
            continue
        if (m["context_length"] or 0) < min_context:
            continue
        rate = m["completion_price_per_token"]
        if max_cost_per_1k is not None:
            if rate is None or rate * 1000 > max_cost_per_1k:
                continue
        out.append(m)
    # Unknown price sorts last: it is not free, it is unpriced.
    return sorted(out, key=lambda m: (
        m["completion_price_per_token"] is None,
        m["completion_price_per_token"] or 0.0))


def status() -> dict:
    """What the catalogue knows, and how stale it is. Never a claim of fresh."""
    with _lock:
        count = len(_models)
        fetched = _fetched_at
        err = _error
        free = sum(1 for m in _models.values() if m["is_free"] is True)
        priced = sum(1 for m in _models.values()
                     if m["completion_price_per_token"] is not None)
    return {
        "models": count,
        "free_models": free,
        "priced_models": priced,
        # None, not 0 — "never fetched" is not "fetched a moment ago".
        "age_seconds": round(time.time() - fetched, 1) if fetched else None,
        "fetched": fetched is not None,
        "ttl_seconds": TTL,
        "error": err or None,
        "source": CATALOG_URL,
        "note": ("Per-token list prices published by OpenRouter, used to turn "
                 "measured token counts into a measured cost. It is the "
                 "provider's list price, not an invoice. Titan reports cost as "
                 "null wherever tokens were not actually counted."),
    }


def reset() -> None:
    """Test seam."""
    global _fetched_at, _error
    with _lock:
        _models.clear()
        _fetched_at = None
        _error = ""
