"""Growth API: live research, the marketing war room and the SEO co-pilot.

Dashboard-facing routes, behind the usual auth. The scheduled research runs
on the heartbeat.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..engines import autonomous
from ..store import STORE

router = APIRouter(prefix="/api")


def limit_subscriber() -> None:
    """Rate-limit a subscriber's War Room runs.

    Each run uses the platform's search key and several AI calls, so it gets an
    hourly limit like lead discovery. The founder's own runs aren't limited.
    """
    from ..core import cockpit_scope, ratelimit
    email = cockpit_scope.customer_email()
    if email:
        verdict = ratelimit.check("warroom", email)
        if not verdict["allowed"]:
            raise HTTPException(status_code=429, detail=verdict)


@router.get("/growth/intel", tags=["growth"])
def growth_intel() -> dict:
    """Latest autonomous research (opportunities, competitors, keywords, summary)."""
    return autonomous.state(STORE)


@router.post("/growth/scan", tags=["growth"])
def growth_scan() -> dict:
    """Run a research cycle now (it also runs on the heartbeat)."""
    limit_subscriber()
    return autonomous.growth_cycle(STORE)


class DebateRequest(BaseModel):
    topic: str = Field(default="")


@router.post("/warroom/debate", tags=["growth"])
def warroom_debate(req: DebateRequest) -> dict:
    """The marketing team pitches, the head decides and returns an action plan."""
    limit_subscriber()
    return autonomous.marketing_debate(req.topic, STORE)


class SeoRequest(BaseModel):
    keyword: str = Field(default="")


@router.post("/seo/report", tags=["growth"])
def seo_report(req: SeoRequest) -> dict:
    """Current ranking landscape for a keyword, plus a prioritised zero-cost
    action list.
    """
    limit_subscriber()
    return autonomous.seo_report(req.keyword, STORE)


class RepurposeRequest(BaseModel):
    idea: str = Field(..., min_length=3)
    lang: str = Field(default="en")


@router.post("/content/repurpose", tags=["growth"])
def content_repurpose(req: RepurposeRequest) -> dict:
    """One idea -> blog, LinkedIn post, X thread, IG caption, email and Shorts
    script. The pack is also saved to Deliverables.
    """
    from ..engines import repurpose
    limit_subscriber()

    return repurpose.repurpose(req.idea, req.lang, STORE)


# --- gamification and performance (counted from real events) --------------

def _my_leads() -> list:
    """The caller's own leads from the shared, owner-tagged table.

    Counting the whole table would put every subscriber's leads into the
    founder's XP.
    """
    from ..core import cockpit_scope, crm
    from ..store import founder_store
    return crm.visible_to(founder_store().leads,
                          cockpit_scope.customer_email() or crm.FOUNDER)


_MILESTONES = [
    ("First real order logged", lambda s: len(s.revenue_entries) > 0),
    ("First $100 earned", lambda s: float(s.metrics.get("mrr", 0)) >= 100),
    ("First lead won", lambda s: any(l.get("status") == "won" for l in _my_leads())),
    ("10 posts scheduled", lambda s: len(s.posts) >= 10),
    ("First job application", lambda s: any(i.get("applied") for i in (s.jobs or {}).get("items", []))),
    ("Telegram connected", lambda s: len(s.telegram_log) > 0),
    ("First council decision", lambda s: len(s.decisions) > 0),
]


def _counters(s) -> dict:
    leads = _my_leads()
    return {
        "posts_scheduled": len(s.posts),
        "posts_published": sum(1 for p in s.posts.values() if p.get("status") == "published"),
        "deliverables": len(s.deliverables),
        "jobs_found": len((s.jobs or {}).get("items", [])),
        "jobs_applied": sum(1 for i in (s.jobs or {}).get("items", []) if i.get("applied")),
        "leads_total": len(leads),
        "leads_won": sum(1 for l in leads if l.get("status") == "won"),
        "telegram_commands": len(s.telegram_log),
        "council_decisions": len(s.decisions),
    }


@router.get("/progress", tags=["growth"])
def progress() -> dict:
    """XP and level, computed only from real events: revenue, wins, work done."""
    s = STORE
    c = _counters(s)
    leads_contacted = sum(
        1 for l in _my_leads() if l.get("status") in ("contacted", "replied", "won")
    )
    xp = int(
        float(s.metrics.get("mrr", 0)) * 10
        + c["leads_won"] * 50
        + leads_contacted * 5
        + c["posts_scheduled"] * 10
        + c["deliverables"] * 5
        + c["jobs_applied"] * 15
        + c["telegram_commands"] * 2
        + len(s.expenses)
    )
    level = 1
    while xp >= (level ** 2) * 100:
        level += 1
    return {
        "xp": xp,
        "level": level,
        "level_floor": ((level - 1) ** 2) * 100,
        "next_level_xp": (level ** 2) * 100,
        "milestones": [{"label": label, "done": bool(check(s))} for label, check in _MILESTONES],
    }


@router.get("/performance", tags=["growth"])
def performance() -> dict:
    """Automation output counters plus an estimated time saved.

    The estimate assumes ~30 min per deliverable, 15 per post, 20 per job
    application and 2 per Telegram command, and is labelled as an estimate.
    """
    c = _counters(STORE)
    minutes = (
        c["deliverables"] * 30
        + c["posts_scheduled"] * 15
        + c["jobs_applied"] * 20
        + c["telegram_commands"] * 2
    )
    return {
        **c,
        "research_last_run": (STORE.intel or {}).get("last_run"),
        "time_saved_minutes_estimate": minutes,
    }


class PrRequest(BaseModel):
    instruction: str = Field(
        default="Improve this file to be clearer, more compelling, and SEO-friendly "
        "for students searching for AI career help — without inventing fake stats."
    )
    owner: str = Field(default="AbdullahRathoreVA")
    repo: str = Field(default="career-mind")
    path: str = Field(default="README.md")


@router.post("/devops/pr", tags=["growth"])
def devops_pr(req: PrRequest) -> dict:
    """Open a pull request with an AI-drafted improvement to one file (Career
    Mind by default). Nothing is merged automatically.
    """
    from ..engines import devops

    return devops.open_improvement_pr(req.owner, req.repo, req.instruction, req.path, STORE)
