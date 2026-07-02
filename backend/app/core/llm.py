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
_GEMINI_MODEL = os.getenv("TITAN_GEMINI_MODEL",  "gemini-1.5-flash")

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
        api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY") or "missing",
        timeout=25.0,
        max_retries=1,
    )


@lru_cache(maxsize=1)
def _openai_client():
    import openai
    kwargs: dict = {}
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key  = os.getenv("OPENAI_API_KEY", "ollama")
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
    resp = _groq_client().chat.completions.create(
        model=_GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip() or None


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
            text = (resp.choices[0].message.content or "").strip()
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


def _complete_gemini(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(model_name=_GEMINI_MODEL, system_instruction=system)
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
    chain = []
    if os.getenv("ANTHROPIC_API_KEY"):
        chain.append("claude")
    if os.getenv("GROQ_API_KEY"):
        chain.append("groq")
    if os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY"):
        chain.append("hermes")
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"):
        chain.append("openai")
    if os.getenv("GEMINI_API_KEY"):
        chain.append("gemini")

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

    errors = []
    for prov in chain:
        fn = _DISPATCH.get(prov)
        if fn is None:
            continue
        try:
            text = fn(system, prompt, max_tokens)
            if text:
                _LAST_ERROR = None
                return text
            errors.append(f"{prov}: empty response")
        except Exception as exc:
            errors.append(f"{prov}: {type(exc).__name__}: {str(exc)[:200]}")

    _LAST_ERROR = " | ".join(errors) if errors else "all providers returned empty"
    return None
