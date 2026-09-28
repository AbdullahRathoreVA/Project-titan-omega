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

From a subscriber's cockpit (/api/me) all three work on the subscriber's own
businesses instead of the founder's (see engines/owner.py), and a debate is
never pushed to the founder's Telegram.
"""

from __future__ import annotations

from typing import Dict, List

from ..core import llm, model_router, quota
from ..store import STORE, Store, now
from . import news, owner, research


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


def _sources(opp: List[dict], comp: List[dict], heads: List[dict]) -> str:
    src_parts = []
    if opp:
        src_parts.append("EARNING / OPPORTUNITY RESULTS:\n" + "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in opp))
    if comp:
        src_parts.append("COMPETITOR / NICHE RESULTS:\n" + "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in comp))
    if heads:
        src_parts.append("TODAY'S HEADLINES:\n" + "\n".join(f"- {h['title']}" for h in heads))
    return "\n\n".join(src_parts) or "No live web results (add TAVILY_API_KEY for live search)."


def _save_intel(store: Store, opp, comp, heads, summary, kw_raw, live, label) -> dict:
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
        f"{label}: {len(intel['opportunities'])} opportunities, "
        f"{len(intel['competitors'])} competitor signals, {len(keywords)} keywords.",
        "success",
    )
    return intel


def growth_cycle(store: Store = STORE) -> dict:
    """One full research pass. Safe to call repeatedly (heartbeat or on demand)."""
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        return _subscriber_growth_cycle(businesses, store)
    opp = research.search(
        "freelance Upwork projects hiring AI chatbot automation resume writing remote, "
        "and paid contests or grants for student edtech founders",
        6,
    )
    comp = research.search(
        "AI career guidance platform for students competitors, "
        "and high-demand Upwork AI gig niches and keywords 2026",
        6,
    )
    heads = news.fetch_headlines("AI careers OR freelancing OR edtech students jobs", 6)
    live = bool(opp or comp)
    src = _sources(opp, comp, heads)

    summary = llm.complete(
        system=(
            "You are Abdullah's autonomous Growth Operator. From the live research below, "
            "write a tight brief: the 3 best money-making moves to act on THIS WEEK "
            "(freelance/Upwork/Career Mind), who the real competitors are and their weak "
            "spot, and the single highest-leverage zero-cost action right now. Short bullets."
        ),
        prompt=src,
        max_tokens=700,
    ) or (
        "Autonomous engine is in free fallback. Add GROQ_API_KEY (free) for full AI "
        "synthesis and TAVILY_API_KEY (free) for live web search."
    )

    kw_raw = llm.complete(
        task=model_router.KEYWORDS,
        system=(
            "List 8 specific, high-intent SEO keywords Abdullah should target for Career "
            "Mind AI (student career platform) and his Upwork AI gigs. Output ONLY a "
            "comma-separated list, no numbering."
        ),
        prompt=src if live else "AI career guidance for students; affordable AI freelance services",
        max_tokens=120,
    )
    return _save_intel(store, opp, comp, heads, summary, kw_raw, live,
                       "Autonomous growth cycle")


def _subscriber_growth_cycle(businesses: list, store: Store) -> dict:
    """The same research pass, about the subscriber's own market.

    With no business on file there is nothing to research, so it says so and
    spends none of their AI calls or the platform's search quota."""
    if not businesses:
        intel = {**_empty(), "last_run": now().isoformat(), "summary": (
            "Add your business in the Clients tab first. The War Room "
            "researches your market, and it has nothing to research yet.")}
        store.intel = intel
        return intel

    main = businesses[0]
    trade = main.get("industry") or main.get("business_name") or "local business"
    place = " ".join(x for x in (main.get("city"), main.get("country")) if x)
    desc = owner.describe(businesses)

    opp = research.search(f"{trade} {place} customer demand and marketing opportunities", 6)
    comp = research.search(f"best {trade} {place} competitors and reviews", 6)
    heads = news.fetch_headlines(f"{trade} {place}".strip(), 6)
    live = bool(opp or comp)
    src = _sources(opp, comp, heads)

    summary = llm.complete(
        system=(
            f"You are the growth operator for {desc}. From the live research "
            "below, write a tight brief for the owner: the 3 best moves to win "
            "customers THIS WEEK, who the real competitors are and their weak "
            "spot, and the single highest-leverage zero-cost action right now. "
            "Short bullets."
        ),
        prompt=src,
        max_tokens=700,
    ) or quota.no_answer_note("")
    kw_raw = llm.complete(
        task=model_router.KEYWORDS,
        system=(
            f"List 8 specific, high-intent SEO keywords people search when they "
            f"are looking for {desc}. Output ONLY a comma-separated list, no numbering."
        ),
        prompt=src if live else f"{trade} {place}".strip(),
        max_tokens=120,
    )
    return _save_intel(store, opp, comp, heads, summary, kw_raw, live,
                       f"Growth research for {main.get('business_name') or 'your business'}")


# --- marketing war room (debate -> decide -> execute) ----------------------

_TEAM = [
    ("Aisha — Brand Strategist", "bold brand-building, storytelling, long-term positioning"),
    ("Bilal — Performance Marketer", "fast ROI, scrappy organic + cheap paid growth, data-driven"),
    ("Sara — Content & SEO Lead", "viral content, SEO, social reach, community building"),
]


def marketing_debate(topic: str = "", store: Store = STORE) -> dict:
    """The marketing team argues; the head decides and gives an action plan."""
    businesses = owner.subscriber_businesses()
    subscriber = businesses is not None
    if subscriber:
        desc = owner.describe(businesses) if businesses else "a small business"
        first = businesses[0].get("business_name") if businesses else "your business"
        goal = topic.strip() or (
            f"Win more customers for {first} with a $0 budget this week.")
        team, council = f"the marketing team for {desc}", f"the executive council for {desc}"
    else:
        goal = topic.strip() or (
            "Grow Career Mind AI signups and Upwork orders with a $0 budget this week."
        )
        team, council = "Abdullah's team", "Abdullah's executive council"

    proposals: List[Dict[str, str]] = []
    for name, style in _TEAM:
        pitch = llm.complete(
            system=(
                f"You are {name}, a marketing expert ({style}) on {team}. The "
                f"goal: {goal}. Give ONE concrete, zero-cost proposal in 2-3 sentences. "
                "Be specific and bold — you're competing with teammates to win the plan."
            ),
            prompt=goal,
            max_tokens=220,
        ) or quota.no_answer_note(
            f"{name}: (set a free LLM key like GROQ_API_KEY to hear my pitch.)")
        proposals.append({"name": name, "proposal": pitch})

    debate = "\n".join(f"{p['name']}: {p['proposal']}" for p in proposals)

    # Council critiques: finance and risk challenge the pitches before the call.
    critiques = []
    for name, role in (
        ("Yusuf — CFO", "evaluate the pitches for cost, cash-flow impact, and feasibility on a $0 budget"),
        ("Zara — Risk Officer", "identify the biggest risks in the pitches (platform bans, wasted effort, reputation) and how to avoid them"),
    ):
        note = llm.complete(
            system=(
                f"You are {name} on {council}. In 2-3 blunt, specific "
                f"sentences, {role}. Challenge weak thinking — don't rubber-stamp."
            ),
            prompt=f"Goal: {goal}\n\nTeam pitches:\n{debate}",
            max_tokens=200,
        ) or "(critique unavailable — LLM unreachable)"
        critiques.append({"name": name, "note": note})

    critique_text = "\n".join(f"{c['name']}: {c['note']}" for c in critiques)
    decision = llm.complete(
        system=(
            "You are the Head of Marketing. Your team pitched competing ideas and the "
            "CFO + Risk Officer critiqued them (all below). Pick the strongest idea or "
            "combine the best parts, say WHY in 2 sentences, address the critiques, then "
            "give a concrete 3-step action plan to execute this week for free. END with "
            "one line in exactly this format: CONFIDENCE: NN% (your honest confidence)."
        ),
        prompt=f"Team pitches:\n{debate}\n\nCouncil critiques:\n{critique_text}\n\nGoal: {goal}",
        max_tokens=500,
    ) or quota.no_answer_note(
        "Decision pending — add a free LLM key (GROQ_API_KEY) to run the war room.")

    import re as _re

    m = _re.search(r"CONFIDENCE[:\s]+(\d{1,3})", decision)
    confidence = max(0, min(100, int(m.group(1)))) if m else 70

    # Decision history (persisted) — every council call is auditable later.
    store.decisions.append({
        "goal": goal,
        "decision": decision,
        "confidence": confidence,
        "time": now().isoformat(),
    })
    if len(store.decisions) > 50:
        store.decisions = store.decisions[-50:]
    try:
        from .. import persistence

        persistence.save(store)
    except Exception:
        pass

    store.emit(
        "marketing-head", "decision",
        "Marketing war room debated and locked this week's growth play.", "success",
    )

    # Push the decision to Abdullah's phone for approval (no-op without
    # Telegram). Never a subscriber's: their plan is theirs, not his to approve.
    if not subscriber:
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

    return {
        "goal": goal,
        "proposals": proposals,
        "critiques": critiques,
        "decision": decision,
        "confidence": confidence,
    }


# --- SEO co-pilot ----------------------------------------------------------

def seo_report(keyword: str = "", store: Store = STORE) -> dict:
    """Analyse the live ranking landscape for a keyword + an action list to climb."""
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        main = businesses[0] if businesses else {}
        kw = keyword.strip() or " ".join(
            x for x in (main.get("industry"), main.get("city")) if x
        ) or main.get("business_name", "")
        if not kw:
            return {"keyword": "", "live": False, "competitors": [], "report": (
                "Type a keyword, or add your business in the Clients tab so "
                "Titan can pick one for you.")}
        for_whom = (f"the owner of {owner.describe(businesses)}" if businesses
                    else "a small business owner")
    else:
        kw = keyword.strip() or "AI career guidance for students"
        for_whom = "Abdullah (Career Mind AI student platform + Upwork AI gigs)"
    results = research.search(f"{kw} top ranking websites and who ranks for it", 8)
    live = bool(results)
    src = "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in results) or (
        "(No live results — add TAVILY_API_KEY for a live ranking scan.)"
    )

    report = llm.complete(
        task=model_router.SEO_REPORT,
        system=(
            f"You are an SEO strategist. For the keyword '{kw}', use the live results to: "
            "(1) identify who currently ranks and why, (2) find concrete content/keyword "
            f"gaps, (3) give {for_whom} a "
            "prioritised, zero-cost action list to climb toward page one. Be specific and "
            "practical. Be honest: never promise a guaranteed #1 ranking."
        ),
        prompt="Live ranking results:\n" + src,
        max_tokens=800,
    ) or quota.no_answer_note("Add a free LLM key (GROQ_API_KEY) for the full SEO analysis.")

    store.emit("seo-strategist", "discovery", f"SEO report generated for '{kw}'.", "success")
    return {
        "keyword": kw,
        "live": live,
        "competitors": [{"title": r["title"], "url": r["url"]} for r in results],
        "report": report,
    }
