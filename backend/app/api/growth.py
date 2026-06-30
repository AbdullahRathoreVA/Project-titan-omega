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
