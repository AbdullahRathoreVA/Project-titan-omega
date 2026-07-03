"""Communication + job-hunt APIs: Telegram Command Center and Job Radar."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..engines import jobs, telegram_bot
from ..store import STORE, now

router = APIRouter(prefix="/api")


# --- Telegram Command Center -------------------------------------------------

@router.get("/telegram/status", tags=["comms"])
def telegram_status() -> dict:
    return telegram_bot.status(STORE)


@router.get("/telegram/log", tags=["comms"])
def telegram_log(limit: int = 50) -> list:
    return list(reversed(STORE.telegram_log[-max(1, min(limit, 200)):]))


class TelegramHandleRequest(BaseModel):
    text: str = Field(..., min_length=1)
    chat_id: str = Field(default="")
    sender: str = Field(default="")


@router.post("/telegram/handle", tags=["comms"])
def telegram_handle(
    req: TelegramHandleRequest,
    x_webhook_secret: Optional[str] = Header(default=None),
) -> dict:
    """Relay entrypoint: HF's network blocks outbound calls to api.telegram.org,
    so a tiny Cloudflare Worker (see TELEGRAM_SETUP.md) receives the Telegram
    webhook, calls this endpoint for the reply, and sends it back to Telegram.
    Secured with the existing TITAN_WEBHOOK_SECRET header."""
    expected = os.getenv("TITAN_WEBHOOK_SECRET", "").strip()
    if expected and x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Webhook-Secret header")

    allowed = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if allowed and str(req.chat_id) != allowed:
        reply = "⛔ This Titan instance is locked to its founder."
    else:
        try:
            reply = telegram_bot._handle(req.text, STORE)
        except Exception as exc:
            reply = f"Something went wrong handling that: {type(exc).__name__}"

    STORE.telegram_log.append({
        "time": now().isoformat(),
        "from": req.sender or "?",
        "chat_id": req.chat_id,
        "command": req.text[:120],
        "reply": reply[:300],
    })
    if len(STORE.telegram_log) > 200:
        STORE.telegram_log = STORE.telegram_log[-200:]
    STORE.emit("telegram-center", "command", f"Telegram: {req.sender or '?'} → {req.text[:60]}", "info")
    return {"reply": reply}


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
