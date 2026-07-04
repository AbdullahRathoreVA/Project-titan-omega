"""Autonomous Growth Engine API — live research, marketing war room, SEO co-pilot.

Mounted alongside the main router. These are dashboard-facing (auth-gated like
the rest); the 24/7 research itself runs server-side on the heartbeat.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..engines import autonomous
from ..store import STORE

router = APIRouter(prefix="/api")


@router.get("/growth/intel", tags=["growth"])
def growth_intel() -> dict:
    """Latest autonomous research (opportunities, competitors, keywords, summary)."""
    return autonomous.state(STORE)


@router.post("/growth/scan", tags=["growth"])
def growth_scan() -> dict:
    """Run a full research cycle right now (also runs automatically 24/7)."""
    return autonomous.growth_cycle(STORE)


class DebateRequest(BaseModel):
    topic: str = Field(default="")


@router.post("/warroom/debate", tags=["growth"])
def warroom_debate(req: DebateRequest) -> dict:
    """The marketing team argues, the head decides, and returns an action plan."""
    return autonomous.marketing_debate(req.topic, STORE)


class SeoRequest(BaseModel):
    keyword: str = Field(default="")


@router.post("/seo/report", tags=["growth"])
def seo_report(req: SeoRequest) -> dict:
    """Live ranking landscape + a prioritised, zero-cost action list to climb."""
    return autonomous.seo_report(req.keyword, STORE)


class RepurposeRequest(BaseModel):
    idea: str = Field(..., min_length=3)
    lang: str = Field(default="en")


@router.post("/content/repurpose", tags=["growth"])
def content_repurpose(req: RepurposeRequest) -> dict:
    """One idea → blog + LinkedIn + X thread + IG caption + email + Shorts
    script. The pack is also saved to Deliverables."""
    from ..engines import repurpose

    return repurpose.repurpose(req.idea, req.lang, STORE)


# --- gamification + performance (REAL events only, no fake progress) --------

_MILESTONES = [
    ("First real order logged", lambda s: len(s.revenue_entries) > 0),
    ("First $100 earned", lambda s: float(s.metrics.get("mrr", 0)) >= 100),
    ("First lead won", lambda s: any(l.get("status") == "won" for l in s.leads.values())),
    ("10 posts scheduled", lambda s: len(s.posts) >= 10),
    ("First job application", lambda s: any(i.get("applied") for i in (s.jobs or {}).get("items", []))),
    ("Telegram connected", lambda s: len(s.telegram_log) > 0),
    ("First council decision", lambda s: len(s.decisions) > 0),
]


def _counters(s) -> dict:
    return {
        "posts_scheduled": len(s.posts),
        "posts_published": sum(1 for p in s.posts.values() if p.get("status") == "published"),
        "deliverables": len(s.deliverables),
        "jobs_found": len((s.jobs or {}).get("items", [])),
        "jobs_applied": sum(1 for i in (s.jobs or {}).get("items", []) if i.get("applied")),
        "leads_total": len(s.leads),
        "leads_won": sum(1 for l in s.leads.values() if l.get("status") == "won"),
        "telegram_commands": len(s.telegram_log),
        "council_decisions": len(s.decisions),
    }


@router.get("/progress", tags=["growth"])
def progress() -> dict:
    """XP and level computed ONLY from real events — revenue, wins, real work."""
    s = STORE
    c = _counters(s)
    leads_contacted = sum(
        1 for l in s.leads.values() if l.get("status") in ("contacted", "replied", "won")
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
    """Automation output counters + an ESTIMATED time-saved figure (labelled
    estimate — ~30min/deliverable, 15min/post, 20min/proposal-application,
    2min/telegram command)."""
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
    """Open a REAL pull request to a repo (default: Career Mind) with an AI-drafted
    improvement to one file. You review and merge — nothing is auto-merged."""
    from ..engines import devops

    return devops.open_improvement_pr(req.owner, req.repo, req.instruction, req.path, STORE)
