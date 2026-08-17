"""Content Repurposing Factory — one idea in, a week of content out.

Single LLM call with hard delimiters, parsed robustly; the pack is also saved
to Deliverables so nothing generated is ever lost. Honest degradation: with no
LLM available the caller gets an explanatory note, never a crash.
"""

from __future__ import annotations

import re
from typing import Dict

from ..core import llm, model_router
from ..store import STORE, Store, now

SECTIONS = ["BLOG", "LINKEDIN", "XTHREAD", "INSTAGRAM", "EMAIL", "SHORTS"]

_PROMPT = (
    "You are the content team for Abdullah's businesses (Career Mind AI — a free "
    "AI career-guidance platform for students — and his Upwork AI services). "
    "From the single idea below, produce SIX pieces of ready-to-publish content. "
    "Output EXACTLY this structure, each section starting with its delimiter line:\n"
    "===BLOG===\n(a 350-500 word blog post with a strong title on the first line)\n"
    "===LINKEDIN===\n(a LinkedIn post, hook first line, 80-150 words, 3 hashtags)\n"
    "===XTHREAD===\n(an X thread: 5 numbered tweets, each under 260 chars)\n"
    "===INSTAGRAM===\n(an Instagram caption, casual human voice, max 150 words, 5 hashtags)\n"
    "===EMAIL===\n(a newsletter email: subject line first, then 100-150 word body, one CTA)\n"
    "===SHORTS===\n(a 30-second YouTube Shorts / Reel script: HOOK, 3 beats, CTA — with timing)\n"
    "Rules: sound like a real person, no corporate fluff, no invented statistics, "
    "no URLs (added later)."
)


def repurpose(idea: str, lang: str = "en", store: Store = STORE) -> Dict[str, str]:
    lang_name = "Urdu (اردو)" if lang == "ur" else "English"
    raw = llm.complete(
        task=model_router.REPURPOSE,
        system=_PROMPT + f" Write everything in {lang_name}.",
        prompt=f"The idea: {idea.strip()}",
        max_tokens=1900,
    )

    if not raw:
        note = "AI generation unreachable right now — check /api/llm/health and retry."
        return {s.lower(): note for s in SECTIONS}

    parts = re.split(r"===\s*(BLOG|LINKEDIN|XTHREAD|INSTAGRAM|EMAIL|SHORTS)\s*===", raw)
    out: Dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].lower()] = parts[i + 1].strip()
    for s in SECTIONS:  # anything the model skipped gets an honest placeholder
        out.setdefault(s.lower(), "(not generated — hit Repurpose again)")

    # If the delimiters were ignored entirely, keep the full text in the blog slot.
    if all(v.startswith("(not generated") for v in out.values()):
        out["blog"] = raw.strip()

    # Save the whole pack to Deliverables (same record shape as the engine).
    record = {
        "id": store.new_id("deliv"),
        "title": f"Content Pack: {idea.strip()[:60]}",
        "kind": "growth_strategy",  # existing kind keeps the API schema stable
        "agent_id": "marketing-head",
        "agent_name": "Content Studio",
        "opportunity_id": None,
        "content": "\n\n".join(f"## {k.upper()}\n\n{v}" for k, v in out.items()),
        "source": "ai",
        "created_at": now(),
    }
    store.deliverables[record["id"]] = record
    store.emit("content-studio", "activity",
               f"Repurposed one idea into {len(SECTIONS)} content pieces.", "success")
    return out
