"""Action-taking endpoints — the agents actually DO things, not just talk.

Mounted alongside the main router so the core contract stays untouched:
  * POST /api/agent/act     — perform a real in-app action.
  * POST /api/intel/news    — live headlines + market analysis.
  * POST /api/leads/find    — live web search → concrete leads (Tavily).
  * GET  /api/content/daily — fresh caption + free AI image URL for auto-posting.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core import llm
from ..engines import deliverables, news, opportunity, publisher, research
from ..store import STORE

router = APIRouter(prefix="/api")


# --- live news + market analysis ------------------------------------------

class NewsRequest(BaseModel):
    topic: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/intel/news", tags=["system"])
def intel_news(req: NewsRequest) -> dict:
    """Live headlines + AI market analysis tuned to Abdullah's businesses."""
    query = req.topic or (
        "AI career tools OR freelancing OR Fiverr gig economy OR ed-tech students jobs"
    )
    heads = news.fetch_headlines(query, 8)
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    if heads:
        head_text = "\n".join(f"- {h['title']}" for h in heads)
        analysis = llm.complete(
            system=(
                "You are a market analyst for Abdullah's Career Mind AI (a student "
                "career-guidance platform) and his Fiverr AI service gigs. From today's "
                "real headlines, extract what matters for HIS marketing and earning, then "
                f"give 3 concrete, zero-cost moves to capitalize THIS WEEK. Write in {lang_name}."
            ),
            prompt="Today's headlines:\n" + head_text,
            max_tokens=700,
        )
        content = (
            "📰 LATEST HEADLINES (live)\n"
            + head_text
            + "\n\n📈 ANALYSIS & MOVES\n"
            + (analysis or "(Set GROQ_API_KEY or Hermes to unlock AI analysis — free.)")
        )
    else:
        content = (
            "Couldn't fetch live news right now (network blocked or rate-limited). "
            "Try again in a moment."
        )

    STORE.emit(
        "intelligence-studio", "discovery",
        f"Pulled {len(heads)} live headlines for market analysis.", "success",
    )
    return {"kind": "latest_news", "content": content, "headlines": heads}


# --- live lead finder (Tavily web search) ----------------------------------

class LeadRequest(BaseModel):
    query: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/leads/find", tags=["system"])
def find_leads(req: LeadRequest) -> dict:
    """Search the live web for real leads, then format them into an action list."""
    query = req.query or (
        "universities and colleges career services departments contact, "
        "and small businesses that need AI chatbots or automation"
    )
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"
    results = research.search(query, 8)

    if results:
        src = "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in results)
        content = llm.complete(
            system=(
                "You are Abdullah's lead-generation analyst. From these LIVE web results, "
                "extract concrete leads (organisations / people / places) he can reach to "
                "sell Career Mind AI (student career platform) or his Fiverr AI gigs. For "
                "each lead give: name, why they're a fit, where/how to contact, and a 1-line "
                f"opening message. Be specific and practical. Write in {lang_name}."
            ),
            prompt="Live web results:\n" + src,
            max_tokens=900,
        )
        content = (content or "") + "\n\n— Sources —\n" + "\n".join(
            f"• {r['url']}" for r in results
        )
        live = True
    else:
        content = llm.complete(
            system=(
                "You are Abdullah's lead-generation analyst. Give a concrete, practical list "
                "of WHERE to find buyers for Career Mind AI and his Fiverr AI gigs — specific "
                "communities, directories, search queries, and outreach angles. "
                f"Write in {lang_name}."
            ),
            prompt=req.query or "Find buyers for an AI career platform + Fiverr AI services.",
            max_tokens=700,
        ) or (
            "Add a free TAVILY_API_KEY (tavily.com) in your Space to unlock LIVE lead search. "
            "For now: target university career-services pages, student Facebook groups, and "
            "r/jobs / r/resumes on Reddit."
        )
        live = False

    STORE.emit(
        "revenue-head", "discovery",
        f"Lead search ({'live' if live else 'offline'}): {query[:60]}", "success",
    )
    return {"kind": "leads", "content": content, "live": live}


# --- daily auto-content (caption + free AI image) for posting --------------

_IMG_STYLES = [
    "professional marketing poster, bold modern design, vibrant gradient, ultra high quality, 4k, clean, eye-catching advertising creative",
    "sleek corporate flat illustration, blue and purple palette, minimal, premium, crisp, high detail",
    "modern social media ad creative, dynamic composition, bright and inspiring, professional studio look",
    "premium tech brand visual, smooth gradient background, sharp, polished, marketing campaign quality",
]


def _pollinations(prompt: str) -> str:
    return (
        "https://image.pollinations.ai/prompt/"
        + quote(prompt)
        + "?width=1080&height=1080&nologo=true&model=flux&enhance=true"
    )


@router.get("/content/daily", tags=["system"])
def content_daily(
    topic: str = Query(default=""),
    lang: str = Query(default="en"),
    target: str = Query(default="auto", description="career_mind | fiverr | auto"),
) -> dict:
    """Fresh caption + a FREE high-quality AI image for the daily post."""
    cm = os.getenv("CAREERMIND_URL", "https://careermind2026-career-mind.hf.space")
    fiverr = os.getenv("FIVERR_GIG_URL", "").strip()
    lang_name = "Urdu (اردو)" if lang == "ur" else "English"

    t = (target or "auto").lower()
    if t == "auto":
        t = "fiverr" if (fiverr and len(STORE.feed) % 2 == 0) else "career_mind"

    if t == "fiverr" and fiverr:
        link = fiverr
        pitch = (
            "Abdullah's Fiverr AI services: custom AI chatbots, business automation, "
            "AI content writing, and resume/LinkedIn optimisation. Affordable, fast delivery."
        )
        img_subject = (
            "freelance AI services advertisement, chatbots and automation, a confident "
            "professional at a laptop, digital marketing"
        )
    else:
        t = "career_mind"
        link = cm
        pitch = (
            "Career Mind AI — a FREE AI career-guidance platform for students: instant "
            "resume feedback, career matching, and interview prep."
        )
        img_subject = (
            "student career success, a happy graduate getting hired, education and AI, "
            "bright and hopeful"
        )

    caption = llm.complete(
        system=(
            "Write ONE scroll-stopping social media caption (max 200 characters) that "
            "attracts buyers. Open with a hook, give one clear benefit, end with a call to "
            "action. Add 3-5 relevant hashtags. Do NOT include any URL (it is appended "
            f"separately). Write in {lang_name}. Output ONLY the caption."
        ),
        prompt=(topic + ". " if topic else "") + "Promote: " + pitch,
        max_tokens=160,
    ) or (
        "🚀 Land your dream job with AI — free career guidance for students! Try it today. "
        "#AI #careers #jobs #resume #students"
    )

    style = _IMG_STYLES[len(STORE.feed) % len(_IMG_STYLES)]
    img_prompt = ((topic + ", ") if topic else "") + img_subject + ", " + style
    image_url = _pollinations(img_prompt)

    caption_with_link = f"{caption}\n\n👉 {link}"
    STORE.emit(
        "content-studio", "activity",
        f"Generated daily {t.replace('_', ' ')} post (caption + image).", "success",
    )
    return {
        "target": t,
        "caption": caption_with_link,
        "image_prompt": img_prompt,
        "image_url": image_url,
        "link": link,
    }


# --- action-taking command --------------------------------------------------

class ActRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


def _resp(intent: str, response: str, routed_to=None, actions=None) -> dict:
    return {
        "understood": True,
        "intent": intent,
        "response": response,
        "routed_to": routed_to,
        "actions": actions or [],
    }


@router.post("/agent/act", tags=["system"])
def agent_act(req: ActRequest) -> dict:
    """Interpret an instruction and perform a real in-app action."""
    text = req.instruction.strip()
    low = text.lower()

    if any(k in low for k in ["post", "tweet", "linkedin", "instagram", "pinterest", "social", "share", "caption"]):
        content = llm.complete(
            system=(
                "Write ONE punchy social media post (max 280 chars) promoting Abdullah's "
                "Career Mind AI (free AI career guidance for students) or his Fiverr AI gigs, "
                "based on the instruction. Include a clear call to action. Output only the post."
            ),
            prompt=text,
            max_tokens=160,
        ) or "🚀 Career Mind AI — free AI career guidance for students. Try it now! #AI #careers"
        post = publisher.schedule(content, ["linkedin"], None, None, store=STORE)
        return _resp(
            "publish",
            f'Done Boss — drafted & scheduled a post: "{content[:140]}". It publishes on the next '
            "cycle. Connect Make.com to push it live to your real socials.",
            "marketing-head",
            ["scheduled_post:" + str(post.get("id", ""))],
        )

    if any(k in low for k in ["scan", "opportunit", "find revenue", "find new", "leads", "prospect"]):
        STORE.opportunities.clear()
        opportunity.discover(STORE)
        n = len(STORE.opportunities)
        return _resp(
            "intelligence",
            f"Scanned the market — surfaced {n} fresh opportunities. Check the Opportunity Radar.",
            "intelligence-head",
            ["scanned_opportunities"],
        )

    if any(k in low for k in ["report", "summary", "weekly"]):
        deliverables.generate("business_report", text, "executive-board-reporting-analyst", store=STORE)
        return _resp(
            "report",
            "Generated your report — open the Deliverables panel to read it.",
            "executive-board-reporting-analyst",
            ["created_deliverable"],
        )

    if any(k in low for k in ["email", "outreach", "school", "university", "college", "business", "customer", "reply", "sell", "contact"]):
        if any(k in low for k in ["school", "university", "college"]):
            brief = "Cold email to a school/university administrator selling Career Mind AI (free-trial student career platform)."
        elif any(k in low for k in ["customer", "reply", "care", "support"]):
            brief = "Warm, professional customer-care reply that resolves the issue."
        elif any(k in low for k in ["business", "sell", "contact"]):
            brief = "Cold email to a small business owner offering Abdullah's Fiverr AI services (chatbots, automation, content)."
        else:
            brief = "Helpful community message for job-seekers introducing Career Mind AI + Abdullah's Fiverr resume services."
        content = llm.complete(
            system="You are Abdullah's sales/outreach writer. Draft specific, professional, ready-to-send copy.",
            prompt=brief + "\n\nContext from Abdullah: " + text,
            max_tokens=600,
        ) or "Draft unavailable — set an LLM key (Groq/Hermes, free)."
        deliverables.generate("outreach_email", brief + "\n\n" + content, "revenue-head", store=STORE)
        return _resp(
            "outreach",
            "Drafted the outreach and saved it to Deliverables. ⚠️ To actually SEND it to real people, "
            "connect your Gmail via Make.com — auto-emailing strangers without that is spam and risks a ban.",
            "revenue-head",
            ["created_deliverable"],
        )

    ans = llm.complete(
        system=(
            "You are Titan, Abdullah's AI chief of staff. Address him as 'Abdullah Boss'. "
            "Be concise and actionable. If he wants an action, tell him you can post, scan "
            "opportunities, generate reports, or draft outreach."
        ),
        prompt=text,
        max_tokens=400,
    ) or (
        "Boss, I can post to socials, scan opportunities, generate reports, or draft outreach. "
        "Tell me which and I'll do it."
    )
    return _resp("answer", ans, "executive-core", [])
