"""Autonomous Growth Engine — real 24/7 research + a marketing "war room".

Three honest capabilities, all degrade gracefully (never raise, never fake):

* ``growth_cycle`` — live web + news research for earning opportunities,
  competitors, and SEO keywords, synthesised by the LLM. Runs on the heartbeat.
* ``marketing_debate`` — a team of marketing agents each pitch, then a head
  picks/combines and gives an executable plan. Real LLM multi-agent.
* ``seo_report`` — analyses the live ranking landscape for a keyword and returns
  a prioritised action list. Honest: it never promises a guaranteed #1.

With no ``TAVILY_API_KEY`` the web search returns [] and we fall back to an LLM
brainstorm; with no LLM key the text falls back to a clear "set a key" note.
"""

from __future__ import annotations

from typing import Dict, List

from ..core import llm
from ..store import STORE, Store, now
from . import news, research


def _empty() -> dict:
    return {
        "opportunities": [],
        "competitors": [],
        "keywords": [],
        "headlines": [],
        "summary": "",
        "live": False,
        "last_run": None,
    }


def state(store: Store = STORE) -> dict:
    """Latest research, or an empty shell so the dashboard always has shape."""
    return store.intel or _empty()


def _rows(results: List[dict]) -> List[dict]:
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in results
        if r.get("title")
    ]


def growth_cycle(store: Store = STORE) -> dict:
    """One full research pass. Safe to call repeatedly (heartbeat or on demand)."""
    opp = research.search(
        "freelance Upwork projects hiring AI chatbot automation resume writing remote, "
        "and paid contests or grants for student edtech founders",
        6,
    )
    comp = research.search(
        "AI career guidance platform for students competitors, "
        "and high-demand Fiverr AI gig niches and keywords 2026",
        6,
    )
    heads = news.fetch_headlines("AI careers OR freelancing OR edtech students jobs", 6)
    live = bool(opp or comp)

    src_parts = []
    if opp:
        src_parts.append("EARNING / OPPORTUNITY RESULTS:\n" + "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in opp))
    if comp:
        src_parts.append("COMPETITOR / NICHE RESULTS:\n" + "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in comp))
    if heads:
        src_parts.append("TODAY'S HEADLINES:\n" + "\n".join(f"- {h['title']}" for h in heads))
    src = "\n\n".join(src_parts) or "No live web results (add TAVILY_API_KEY for live search)."

    summary = llm.complete(
        system=(
            "You are Abdullah's autonomous Growth Operator. From the live research below, "
            "write a tight brief: the 3 best money-making moves to act on THIS WEEK "
            "(freelance/Fiverr/Career Mind), who the real competitors are and their weak "
            "spot, and the single highest-leverage zero-cost action right now. Short bullets."
        ),
        prompt=src,
        max_tokens=700,
    ) or (
        "Autonomous engine is in free fallback. Add GROQ_API_KEY (free) for full AI "
        "synthesis and TAVILY_API_KEY (free) for live web search."
    )

    kw_raw = llm.complete(
        system=(
            "List 8 specific, high-intent SEO keywords Abdullah should target for Career "
            "Mind AI (student career platform) and his Fiverr AI gigs. Output ONLY a "
            "comma-separated list, no numbering."
        ),
        prompt=src if live else "AI career guidance for students; affordable AI freelance services",
        max_tokens=120,
    )
    keywords = [k.strip() for k in (kw_raw or "").replace("\n", ",").split(",") if k.strip()][:8]

    intel = {
        "opportunities": _rows(opp),
        "competitors": _rows(comp),
        "keywords": keywords,
        "headlines": [{"title": h["title"], "link": h.get("link", "")} for h in heads],
        "summary": summary,
        "live": live,
        "last_run": now().isoformat(),
    }
    store.intel = intel
    store.emit(
        "growth-autonomous", "discovery",
        f"Autonomous growth cycle: {len(intel['opportunities'])} opportunities, "
        f"{len(intel['competitors'])} competitor signals, {len(keywords)} keywords.",
        "success",
    )
    return intel


# --- marketing war room (debate -> decide -> execute) ----------------------

_TEAM = [
    ("Aisha — Brand Strategist", "bold brand-building, storytelling, long-term positioning"),
    ("Bilal — Performance Marketer", "fast ROI, scrappy organic + cheap paid growth, data-driven"),
    ("Sara — Content & SEO Lead", "viral content, SEO, social reach, community building"),
]


def marketing_debate(topic: str = "", store: Store = STORE) -> dict:
    """The marketing team argues; the head decides and gives an action plan."""
    goal = topic.strip() or (
        "Grow Career Mind AI signups and Fiverr orders with a $0 budget this week."
    )

    proposals: List[Dict[str, str]] = []
    for name, style in _TEAM:
        pitch = llm.complete(
            system=(
                f"You are {name}, a marketing expert ({style}) on Abdullah's team. The "
                f"goal: {goal}. Give ONE concrete, zero-cost proposal in 2-3 sentences. "
                "Be specific and bold — you're competing with teammates to win the plan."
            ),
            prompt=goal,
            max_tokens=220,
        ) or f"{name}: (set a free LLM key like GROQ_API_KEY to hear my pitch.)"
        proposals.append({"name": name, "proposal": pitch})

    debate = "\n".join(f"{p['name']}: {p['proposal']}" for p in proposals)
    decision = llm.complete(
        system=(
            "You are the Head of Marketing. Your team pitched competing ideas (below). "
            "Pick the strongest one or combine the best parts, say WHY in 2 sentences, "
            "then give a concrete 3-step action plan to execute it this week for free."
        ),
        prompt="Team pitches:\n" + debate + f"\n\nGoal: {goal}",
        max_tokens=450,
    ) or "Decision pending — add a free LLM key (GROQ_API_KEY) to run the war room."

    store.emit(
        "marketing-head", "decision",
        "Marketing war room debated and locked this week's growth play.", "success",
    )

    # Push the decision to Abdullah's phone for approval (no-op without Telegram).
    store.pending_decision = {"goal": goal, "decision": decision, "time": now().isoformat()}
    try:
        from . import telegram_bot

        telegram_bot.send_to_founder(
            "⚔️ WAR ROOM DECISION — approval needed\n\n"
            f"Goal: {goal}\n\n{decision[:2800]}\n\n"
            "Reply /approveplan to lock it in, or /decision to re-read it.",
            store,
        )
    except Exception:
        pass

    return {"goal": goal, "proposals": proposals, "decision": decision}


# --- SEO co-pilot ----------------------------------------------------------

def seo_report(keyword: str = "", store: Store = STORE) -> dict:
    """Analyse the live ranking landscape for a keyword + an action list to climb."""
    kw = keyword.strip() or "AI career guidance for students"
    results = research.search(f"{kw} top ranking websites and who ranks for it", 8)
    live = bool(results)
    src = "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in results) or (
        "(No live results — add TAVILY_API_KEY for a live ranking scan.)"
    )

    report = llm.complete(
        system=(
            f"You are an SEO strategist. For the keyword '{kw}', use the live results to: "
            "(1) identify who currently ranks and why, (2) find concrete content/keyword "
            "gaps, (3) give Abdullah (Career Mind AI student platform + Fiverr AI gigs) a "
            "prioritised, zero-cost action list to climb toward page one. Be specific and "
            "practical. Be honest: never promise a guaranteed #1 ranking."
        ),
        prompt="Live ranking results:\n" + src,
        max_tokens=800,
    ) or "Add a free LLM key (GROQ_API_KEY) for the full SEO analysis."

    store.emit("seo-strategist", "discovery", f"SEO report generated for '{kw}'.", "success")
    return {
        "keyword": kw,
        "live": live,
        "competitors": [{"title": r["title"], "url": r["url"]} for r in results],
        "report": report,
    }
