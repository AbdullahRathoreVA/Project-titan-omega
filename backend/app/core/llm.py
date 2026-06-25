"""Claude intelligence layer for the Executive Core.

This is the seam where real model reasoning plugs into the platform. When an
``ANTHROPIC_API_KEY`` is present, agents think with Claude (``claude-opus-4-8``);
when it is absent, every call returns ``None`` and the caller falls back to the
deterministic rule-based logic — so the whole system still runs, free, with no
keys and no network.

Nothing else in the platform imports the Anthropic SDK directly: callers go
through :func:`complete`, which never raises (a model/network error degrades to
the fallback path just like a missing key).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

# Default to the most capable model. Override with TITAN_MODEL if desired.
MODEL = os.getenv("TITAN_MODEL", "claude-opus-4-8")


def available() -> bool:
    """True when a key is configured, i.e. agents can think with Claude."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=1)
def _client():
    # Imported lazily so the platform runs even when `anthropic` isn't installed.
    import anthropic

    return anthropic.Anthropic()


def complete(system: str, prompt: str, max_tokens: int = 1500) -> Optional[str]:
    """Ask Claude for a completion. Returns the text, or ``None`` to fall back.

    Uses adaptive thinking (the recommended mode for Opus 4.8) so the model
    decides how much to reason per request. Any failure — no key, network error,
    rate limit, refusal — returns ``None`` rather than raising, so a caller can
    always proceed with its deterministic path.
    """

    if not available():
        return None
    try:
        resp = _client().messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        # Refusals (and any non-normal stop) shouldn't be treated as content.
        if resp.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception:
        return None
