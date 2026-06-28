"""Action-taking endpoints — the agents actually DO things, not just talk.

Mounted alongside the main router so the core contract stays untouched:
  * POST /api/agent/act   — interpret an instruction and perform a real in-app
                            action (schedule a post, scan opportunities,
                            generate a report, draft outreach).
  * POST /api/intel/news  — pull live headlines and produce market analysis.

Honest boundary: this app cannot send emails or post to your real social
accounts by itself — that requires connecting your Gmail / socials through
Make.com. Until then, 'actions' that touch the outside world are prepared and
queued here for Make.com (or you) to send.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..core import llm
from ..engines import deliverables, news, opportunity, publisher
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

    # 1) Social post — draft + schedule (publishes via Make.com once connected).
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

    # 2) Scan the market for opportunities.
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

    # 3) Generate a report.
    if any(k in low for k in ["report", "summary", "weekly"]):
        deliverables.generate("business_report", text, "executive-board-reporting-analyst", store=STORE)
        return _resp(
            "report",
            "Generated your report — open the Deliverables panel to read it.",
            "executive-board-reporting-analyst",
            ["created_deliverable"],
        )

    # 4) Outreach / customer care — draft + save (sending needs Make.com + Gmail).
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

    # 5) Default — answer as chief of staff.
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
