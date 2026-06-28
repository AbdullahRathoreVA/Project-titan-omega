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
_GROQ_MODEL   = os.getenv("TITAN_GROQ_MODEL",   "llama-3.3-70b-versatile")
_HERMES_MODEL = os.getenv("TITAN_HERMES_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")
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
    return anthropic.Anthropic()


@lru_cache(maxsize=1)
def _groq_client():
    from groq import Groq
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


@lru_cache(maxsize=1)
def _hermes_client():
    import openai
    return openai.OpenAI(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY") or "missing",
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
    return openai.OpenAI(**kwargs)


# ── per-provider completion functions ──────────────────────────────

def _complete_claude(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    try:
        resp = _anthropic_client().messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception:
        return None


def _complete_groq(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    try:
        resp = _groq_client().chat.completions.create(
            model=_GROQ_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None


def _complete_hermes(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    try:
        resp = _hermes_client().chat.completions.create(
            model=_HERMES_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None


def _complete_openai(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    try:
        resp = _openai_client().chat.completions.create(
            model=_OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None


def _complete_gemini(system: str, prompt: str, max_tokens: int) -> Optional[str]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel(model_name=_GEMINI_MODEL, system_instruction=system)
        resp = model.generate_content(prompt, generation_config={"max_output_tokens": max_tokens})
        text = (resp.text or "").strip()
        return text or None
    except Exception:
        return None


_DISPATCH = {
    "claude": _complete_claude,
    "groq":   _complete_groq,
    "hermes": _complete_hermes,
    "openai": _complete_openai,
    "gemini": _complete_gemini,
}


def complete(system: str, prompt: str, max_tokens: int = 1500) -> Optional[str]:
    """Ask the active LLM for a completion. None on any failure (never raises)."""
    fn = _DISPATCH.get(provider())
    if fn is None:
        return None
    return fn(system, prompt, max_tokens)
