"""Multi-model intelligence layer for the Executive Core.

Provider priority (first configured wins; override with TITAN_PROVIDER):
  1. Claude (ANTHROPIC_API_KEY)
  2. Groq   (GROQ_API_KEY)                      — free, fast (Llama 3.3 70B)
  3. Hermes (OPENROUTER_API_KEY / HERMES_API_KEY) — free via OpenRouter
  4. OpenAI-compatible (OPENAI_API_KEY / OPENAI_BASE_URL)
  5. Gemini (GEMINI_API_KEY)
  6. Free fallback                              — deterministic, no key needed

All providers share the same ``complete(system, prompt)`` seam. Returns the
generated text, or ``None`` to fall back to deterministic logic. Never raises.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

_CLAUDE_MODEL = os.getenv("TITAN_MODEL",        "claude-opus-4-8")
_GROQ_MODEL   = os.getenv("TITAN_GROQ_MODEL",   "openai/gpt-oss-120b")
# Display label only — actual model is picked live from the free catalog.
_HERMES_MODEL = os.getenv("TITAN_HERMES_MODEL", "auto (openrouter free catalog)")
_OPENAI_MODEL = os.getenv("TITAN_OPENAI_MODEL",  "gpt-4o-mini")
# Display label only — the actual Gemini model is discovered from Google's live
# catalog (they retire model ids periodically, e.g. gemini-1.5-flash in 2026).
_GEMINI_MODEL = os.getenv("TITAN_GEMINI_MODEL", "auto (google catalog)")

MODEL: Optional[str] = _CLAUDE_MODEL

_VALID = ("claude", "groq", "hermes", "openai", "gemini")


def provider() -> str:
    """Active LLM provider. TITAN_PROVIDER forces one; else first key wins."""
    forced = os.getenv("TITAN_PROVIDER", "").strip().lower()
    if forced in _VALID:
        return forced
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY"):
        return "hermes"
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "free"


def active_model() -> Optional[str]:
    return {
        "claude": _CLAUDE_MODEL,
        "groq":   _GROQ_MODEL,
        "hermes": _HERMES_MODEL,
        "openai": _OPENAI_MODEL,
        "gemini": _GEMINI_MODEL,
    }.get(provider())


def available() -> bool:
    return provider() != "free"


# ── lazy, cached provider clients ────────────────────────────────────

@lru_cache(maxsize=1)
def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(max_retries=1, timeout=25.0)


@lru_cache(maxsize=1)
def _groq_client():
    from groq import Groq
    return Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=1, timeout=20.0)


@lru_cache(maxsize=1)
def _hermes_client():
    import openai
    return openai.OpenAI(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=(os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY") or "missing").strip(),
        timeout=25.0,
        max_retries=1,
    )


@lru_cache(maxsize=1)
def _openai_client():
    import openai
    kwargs: dict = {}
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key  = os.getenv("OPENAI_API_KEY", "ollama").strip()
    if base_url:
        kwargs["base_url"] = base_url
    kwargs["api_key"] = api_key
    kwargs.setdefault("timeout", 25.0)
    kwargs.setdefault("max_retries", 1)
    return openai.OpenAI(**kwargs)


# ── per-provider completion functions ──────────────────────────────
# These RAISE on error; complete() catches, records the reason, and falls back
# to the next configured provider. That way one provider deprecating a model
# (e.g. Groq retiring llama-3.3-70b) can't silently kill every agent.

def _complete_claude(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    resp = _anthropic_client().messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        return None
    return "".join(b.text for b in resp.content if b.type == "text").strip() or None


def _complete_groq(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    # Direct httpx call to Groq's OpenAI-compatible endpoint — the SDK's client
    # hit connection errors from the HF container; plain HTTP/1.1 via httpx is
    # the most compatible path. If Groq's edge blocks the host network entirely,
    # this still fails and the chain moves on to Gemini.
    import httpx

    payload = {
        "model": _GROQ_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if _GROQ_MODEL.startswith("openai/gpt-oss"):
        # gpt-oss is a reasoning model: hidden reasoning consumes completion
        # tokens BEFORE any visible text, so a tiny budget (the health probe's
        # max_tokens=10) yields content="" — keep effort low and floor the cap.
        payload["reasoning_effort"] = "low"
        payload["max_tokens"] = max(max_tokens, 256)
    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        # .strip() everywhere a key is used: a newline pasted into an HF secret
        # becomes an illegal HTTP header and kills the provider silently.
        headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '').strip()}"},
        json=payload,
        timeout=20.0,
        trust_env=True,
    )
    resp.raise_for_status()
    return (resp.json()["choices"][0]["message"]["content"] or "").strip() or None


# OpenRouter's free models churn constantly (rate limits, delistings), so we
# discover what's ACTUALLY available from the live catalog instead of pinning
# ids that go stale. Preferred families first; static list only as last resort.
_PREFERRED_FREE = (
    "openai/gpt-oss-120b",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen3-next-80b",
    "nvidia/nemotron-3-super",
    "openai/gpt-oss-20b",
)
_STATIC_FALLBACKS = [
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]
_free_models_cache: tuple = (0.0, [])  # (fetched_at_monotonic, [model ids])


def _free_models() -> list:
    """Currently-listed :free OpenRouter models, preferred families first.
    Cached ~1h; falls back to a small static list if the catalog is unreachable."""
    global _free_models_cache
    import time as _time

    ts, cached = _free_models_cache
    if cached and _time.monotonic() - ts < 3600:
        return cached
    try:
        import httpx

        with httpx.Client(timeout=10.0, trust_env=True) as c:
            resp = c.get("https://openrouter.ai/api/v1/models")
        ids = [m["id"] for m in resp.json().get("data", []) if m["id"].endswith(":free")]
        ranked = [i for pref in _PREFERRED_FREE for i in ids if i.startswith(pref)]
        rest = [i for i in ids if i not in ranked]
        models = (ranked + rest) or _STATIC_FALLBACKS
        _free_models_cache = (_time.monotonic(), models)
        return models
    except Exception:
        return cached or _STATIC_FALLBACKS


def _complete_hermes(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    forced = os.getenv("TITAN_HERMES_MODEL", "").strip()
    candidates = ([forced] if forced else []) + _free_models()
    last_exc: Optional[Exception] = None
    for model in candidates[:5]:  # cap attempts — fail fast, fall through
        try:
            resp = _hermes_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            )
            # OpenRouter surfaces provider errors as a 200 with choices=None —
            # subscripting that raised TypeError and looked like a code crash.
            choices = getattr(resp, "choices", None)
            if not choices or choices[0].message is None:
                last_exc = RuntimeError(f"{model}: provider returned no choices")
                continue
            text = (choices[0].message.content or "").strip()
            if text:
                return text
        except Exception as exc:  # rate-limited/retired — try the next one
            last_exc = exc
            # The free-models-per-DAY cap is account-wide on OpenRouter: once
            # it's hit, every free model 429s — stop burning time on the rest.
            if "free-models-per-day" in str(exc):
                break
    if last_exc is not None:
        raise last_exc
    return None


def _complete_openai(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    resp = _openai_client().chat.completions.create(
        model=_OPENAI_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip() or None


_gemini_model_cache: Optional[str] = None


def _gemini_model_id() -> str:
    """Pick a live Gemini model from Google's catalog (cached for the process).
    Google retires ids (gemini-1.5-flash died in 2026), so never pin blindly."""
    global _gemini_model_cache
    forced = os.getenv("TITAN_GEMINI_MODEL", "").strip()
    if forced:
        return forced
    if _gemini_model_cache:
        return _gemini_model_cache
    try:
        import google.generativeai as genai

        genai.configure(api_key=os.getenv("GEMINI_API_KEY", "").strip())
        ids = [
            m.name.split("/")[-1]
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]
        for pref in ("gemini-2.5-flash", "gemini-2.0-flash", "flash"):
            for mid in ids:
                if pref in mid and "preview" not in mid and "thinking" not in mid and "lite" not in mid:
                    _gemini_model_cache = mid
                    return mid
        if ids:
            _gemini_model_cache = ids[0]
            return ids[0]
    except Exception:
        pass
    return "gemini-2.5-flash"


def _complete_gemini(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", "").strip())
    model = genai.GenerativeModel(model_name=_gemini_model_id(), system_instruction=system)
    resp = model.generate_content(prompt, generation_config={"max_output_tokens": max_tokens})
    return (resp.text or "").strip() or None


_DISPATCH = {
    "claude": _complete_claude,
    "groq":   _complete_groq,
    "hermes": _complete_hermes,
    "openai": _complete_openai,
    "gemini": _complete_gemini,
}

_LAST_ERROR: Optional[str] = None


def _provider_chain() -> list:
    """Every configured provider, in failover order.

    TITAN_PROVIDER moves that provider to the FRONT — it no longer disables the
    rest. A pinned provider that breaks (rate limit, dead key, retired model)
    must never silence the agents when other working keys exist.
    """
    # Order = free-tier daily quota: Groq (thousands/day) > Gemini (hundreds)
    # > OpenRouter free (~50/day without credits).
    chain = []
    if os.getenv("ANTHROPIC_API_KEY"):
        chain.append("claude")
    if os.getenv("GROQ_API_KEY"):
        chain.append("groq")
    if os.getenv("GEMINI_API_KEY"):
        chain.append("gemini")
    if os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY"):
        chain.append("hermes")
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"):
        chain.append("openai")

    forced = os.getenv("TITAN_PROVIDER", "").strip().lower()
    if forced in _VALID:
        return [forced] + [p for p in chain if p != forced]
    return chain


def providers_configured() -> list:
    return _provider_chain()


def last_error() -> Optional[str]:
    return _LAST_ERROR


def complete(system: str, prompt: str, max_tokens: int = 1500) -> Optional[str]:
    """Ask the LLM for a completion, trying each configured provider in turn.

    Returns the text, or None if every provider fails (never raises). The reason
    for the last failure is recorded in ``last_error()`` for diagnostics.
    """
    global _LAST_ERROR
    chain = _provider_chain()
    if not chain:
        _LAST_ERROR = "no LLM provider configured"
        return None

    # Spec Part 6: route on measured performance, not on an assumption about
    # free-tier quotas. Providers with too little evidence keep their configured
    # position, and none is ever dropped — see routing.order().
    import time as _time

    from . import routing

    chain = routing.order(chain)

    errors = []
    for prov in chain:
        fn = _DISPATCH.get(prov)
        if fn is None:
            continue
        started = _time.monotonic()
        try:
            text = fn(system, prompt, max_tokens)
            elapsed = int((_time.monotonic() - started) * 1000)
            if text:
                routing.record(prov, ok=True, latency_ms=elapsed)
                _LAST_ERROR = None
                return text
            # An empty response is a failure of this provider, not a success:
            # counting it as OK would keep a silently-broken provider ranked
            # first forever.
            routing.record(prov, ok=False, latency_ms=elapsed,
                           error="empty response")
            errors.append(f"{prov}: empty response")
        except Exception as exc:
            elapsed = int((_time.monotonic() - started) * 1000)
            reason = f"{type(exc).__name__}: {str(exc)[:200]}"
            routing.record(prov, ok=False, latency_ms=elapsed, error=reason)
            errors.append(f"{prov}: {reason}")

    _LAST_ERROR = " | ".join(errors) if errors else "all providers returned empty"
    return None
