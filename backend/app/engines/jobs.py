"""Job Radar — finds real remote jobs/gigs, scores fit, drafts proposals.

Compliant by design: it NEVER auto-applies (platform bots get accounts banned).
It hunts listings on the live web (Tavily), scores each for Abdullah's real
skills, and drafts a tailored proposal — he clicks apply himself. Applied
status is tracked so the dashboard shows the pipeline.
"""

from __future__ import annotations

from typing import List, Optional

from ..core import llm, model_router
from ..store import STORE, Store, now
from . import research

# Abdullah's REAL, verifiable profile — used for scoring + proposals. No lies.
PROFILE = (
    "Muhammad Abdullah Rathore — AI Integration & Automation Developer "
    "(Pakistan, remote). Shipped products: Career Mind AI (live student "
    "career-guidance platform: FastAPI + Next.js + multi-LLM, deployed on "
    "Hugging Face Spaces), Project Titan Omega (autonomous business dashboard: "
    "FastAPI, Next.js, react-three-fiber 3D, SSE realtime, Telegram bot, "
    "multi-provider LLM layer), and an AI Job-Search Toolkit digital product "
    "sold on Upwork. Skills: Python/FastAPI, SQLAlchemy, Streamlit, "
    "Next.js/React/TypeScript/Tailwind, LLM APIs (Anthropic/Groq/OpenRouter), "
    "local LLMs with Ollama, OCR/document-processing pipelines, workflow "
    "automation (n8n, Make.com), Docker deploys, Git/GitHub. Builds fast with "
    "AI pair-programming tools. English + Urdu."
)

_DEFAULT_QUERIES = [
    "remote AI developer OR automation freelance job posting hiring apply 2026",
    "remote junior full stack Python Next.js contract job listing apply",
]


def _parse_scored(raw: str) -> List[dict]:
    """Parse 'SCORE|TITLE|URL|WHY' lines robustly; skip anything malformed."""
    out: List[dict] = []
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        try:
            score = max(0, min(100, int(float(parts[0]))))
        except ValueError:
            continue
        if not parts[2].startswith("http"):
            continue
        out.append({"score": score, "title": parts[1][:120], "url": parts[2], "why": parts[3][:220]})
    return out


def scan(query: str = "", store: Store = STORE) -> dict:
    """One live hunt. Returns and stores {items, live, last_scan}."""
    queries = [query.strip()] if query.strip() else _DEFAULT_QUERIES
    results: List[dict] = []
    seen = set()
    for q in queries:
        for r in research.search(q, 6):
            if r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)

    live = bool(results)
    items: List[dict] = []
    if results:
        src = "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in results)
        raw = llm.complete(
            system=(
                "You are a job-hunting analyst. From the live results, pick the listings "
                "that are REAL jobs/gigs Abdullah could win, score each 0-100 for fit, and "
                "output ONE LINE PER JOB in exactly this format (no other text):\n"
                "SCORE|TITLE|URL|WHY IT FITS\n"
                f"His profile: {PROFILE}"
            ),
            prompt=src,
            max_tokens=700,
        )
        items = _parse_scored(raw or "")
        if not items:  # LLM down or unparseable — keep the raw finds, unscored
            items = [{"score": None, "title": r["title"][:120], "url": r["url"],
                      "why": r["content"][:200]} for r in results[:8]]

    for it in items:
        it["id"] = store.new_id("job")
        it["applied"] = False
        it["found_at"] = now().isoformat()

    prev = (store.jobs or {}).get("items", [])
    kept = [p for p in prev if p.get("applied")]  # keep the applied history
    store.jobs = {"items": items + kept, "live": live, "last_scan": now().isoformat()}
    store.emit("job-radar", "discovery",
               f"Job Radar: found {len(items)} openings ({'live web' if live else 'no live search'}).",
               "success" if items else "warn")
    return store.jobs


def state(store: Store = STORE) -> dict:
    return store.jobs or {"items": [], "live": False, "last_scan": None}


def mark_applied(job_id: str, store: Store = STORE) -> Optional[dict]:
    for it in (store.jobs or {}).get("items", []):
        if it.get("id") == job_id:
            it["applied"] = not it.get("applied", False)
            if it["applied"]:
                store.emit("job-radar", "activity", f"Applied: {it['title'][:60]}", "success")
            return it
    return None


def proposal(title: str, url: str, why: str = "", store: Store = STORE) -> str:
    """Draft a tailored, truthful proposal/cover letter for one listing."""
    text = llm.complete(
        task=model_router.JOB_PROPOSAL,
        system=(
            "Write a short, specific proposal/cover letter (120-180 words) for the job "
            "below, from Abdullah. Rules: 100% truthful to his profile, mention ONE "
            "relevant shipped product with its live link, address the job's actual need "
            "in the first sentence, end with a low-friction call to action. No hype, no "
            f"fake experience, no buzzwords. Profile: {PROFILE}"
        ),
        prompt=f"Job: {title}\nURL: {url}\nWhy it fits: {why}",
        max_tokens=350,
    )
    return text or (
        "AI drafting is unreachable right now (check /api/llm/health). "
        "Retry in a minute."
    )
