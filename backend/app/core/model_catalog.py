"""Model metadata from OpenRouter, used to turn token counts into costs.

OpenRouter's `/api/v1/models` lists each model's context length, modalities
and per-token price. Multiplied by a token count from a real completion, that
gives a real cost instead of `cost: null`.

- No SDK: OpenRouter has an official Python SDK, but it would be a new
  dependency for HTTP calls Titan already makes with `httpx`.
- The catalogue says what a model costs per token, not what Titan spent.
  `estimate_cost()` returns None, never 0.0, when the model or price is
  unknown or the provider reported no token count. Estimates are labelled as
  estimates wherever they appear.
- It degrades to nothing: with no key, no network or a stale cache, functions
  return empty or None and say why. No request path depends on it.
- Free models (`:free` suffix, zero price) are marked, so "which capable
  models cost nothing" is answered from data rather than a hand-kept list.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Model metadata changes over days. Six hours keeps it fresh without hammering
# a free endpoint.
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

            * OpenRouter returns prices as strings ("0.0000007").
            * A free model returns "0", a measured zero.
            * A missing field means the price is unknown, which isn't free.
            * Router models (`openrouter/auto`, `openrouter/fusion`, ...) publish "-1",
              meaning priced dynamically. Taken literally they'd sort as cheapest and
              produce a negative cost, so any negative price counts as unknown.
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
            # True only when both prices are known and both are zero. Unknown pricing
            # isn't free.
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
    """Cost of one call, or None with the reason. Never 0.0 as a stand-in.

    Two measured numbers multiplied together is a measurement. If either is
    missing the answer is unknown, and a 0.00 on screen would read as "free".
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

    A hand-kept list of free models goes stale within weeks.
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

    Capability comes from the catalogue, not the name, so a vision task never
    gets routed to a text-only model.
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
    # Unknown price sorts last: it isn't free, it's unpriced.
    return sorted(out, key=lambda m: (
        m["completion_price_per_token"] is None,
        m["completion_price_per_token"] or 0.0))


def status() -> dict:
    """What the catalogue knows, and how old it is."""
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
        # None, not 0: "never fetched" isn't "fetched a moment ago".
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
