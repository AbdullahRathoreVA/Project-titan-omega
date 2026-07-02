"""Communication + job-hunt APIs: Telegram Command Center and Job Radar."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..engines import jobs, telegram_bot
from ..store import STORE

router = APIRouter(prefix="/api")


# --- Telegram Command Center -------------------------------------------------

@router.get("/telegram/status", tags=["comms"])
def telegram_status() -> dict:
    return telegram_bot.status(STORE)


@router.get("/telegram/log", tags=["comms"])
def telegram_log(limit: int = 50) -> list:
    return list(reversed(STORE.telegram_log[-max(1, min(limit, 200)):]))


# --- Job Radar -----------------------------------------------------------------

@router.get("/jobs", tags=["jobs"])
def jobs_state() -> dict:
    return jobs.state(STORE)


class JobScanRequest(BaseModel):
    query: str = Field(default="")


@router.post("/jobs/scan", tags=["jobs"])
def jobs_scan(req: JobScanRequest) -> dict:
    return jobs.scan(req.query, STORE)


class ProposalRequest(BaseModel):
    title: str = Field(..., min_length=1)
    url: str = Field(default="")
    why: str = Field(default="")


@router.post("/jobs/proposal", tags=["jobs"])
def jobs_proposal(req: ProposalRequest) -> dict:
    return {"proposal": jobs.proposal(req.title, req.url, req.why, STORE)}


@router.post("/jobs/{job_id}/applied", tags=["jobs"])
def jobs_applied(job_id: str) -> dict:
    item = jobs.mark_applied(job_id, STORE)
    if item is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return item
