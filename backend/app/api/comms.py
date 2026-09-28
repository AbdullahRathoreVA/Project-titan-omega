"""Communication + job-hunt APIs: Telegram Command Center and Job Radar.

A subscriber reaches both through /api/me. Their Telegram is Titan's own bot,
linked to their chat by a one-time code (core/telegram_links.py) and answered
from their workspace; their Job Radar works from the profile they write.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..core import cockpit_scope, ratelimit, telegram_links
from ..engines import jobs, telegram_bot, telegram_subscribers
from ..store import STORE, now

router = APIRouter(prefix="/api")


# --- Telegram Command Center -------------------------------------------------

@router.get("/telegram/status", tags=["comms"])
def telegram_status() -> dict:
    email = cockpit_scope.customer_email()
    if email:
        bot = telegram_links.bot_username()
        return {"configured": bool(bot), "locked": True, "bot": bot,
                "linked": telegram_links.is_linked(email),
                "handled": len(telegram_links.history(email))}
    return telegram_bot.status(STORE)


@router.get("/telegram/log", tags=["comms"])
def telegram_log(limit: int = 50) -> list:
    email = cockpit_scope.customer_email()
    if email:
        return telegram_links.history(email, limit)
    return list(reversed(STORE.telegram_log[-max(1, min(limit, 200)):]))


def _me() -> str:
    email = cockpit_scope.customer_email()
    if not email:
        raise HTTPException(status_code=404, detail="Not found")
    return email


@router.post("/telegram/link-code", tags=["comms"])
def telegram_link_code() -> dict:
    """A one-time code, and the t.me link that sends it to Titan's bot."""
    email = _me()
    if not telegram_links.bot_username():
        raise HTTPException(status_code=409, detail=(
            "Telegram is not switched on for Titan yet."))
    limited = ratelimit.check("login", f"telegram-code:{email}")
    if not limited["allowed"]:
        raise HTTPException(status_code=429, detail=limited)
    return telegram_links.new_code(email)


@router.delete("/telegram/link", tags=["comms"])
def telegram_unlink() -> dict:
    return {"unlinked": telegram_links.unlink(_me())}


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

    # A subscriber's link attempt or linked chat is answered from their own
    # workspace, and logged there - never in the founder's log.
    theirs = telegram_subscribers.handle(req.chat_id, req.text, req.sender)
    if theirs is not None:
        return {"reply": theirs}

    allowed = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if allowed and str(req.chat_id) != allowed:
        reply = ("⛔ This bot answers linked Titan accounts only. If you have one, "
                 "open the Telegram tab in your Titan cockpit to link this chat.")
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
    if cockpit_scope.is_customer():
        # A live web search on the platform's key, like the War Room.
        from .growth import limit_subscriber
        limit_subscriber()
    return jobs.scan(req.query, STORE)


class ProfileRequest(BaseModel):
    profile: str = Field(default="", max_length=1000)


@router.post("/jobs/profile", tags=["jobs"])
def jobs_profile(req: ProfileRequest) -> dict:
    """A subscriber says what they offer. The founder's profile is his CV in
    engines/jobs.py and is not edited here."""
    _me()
    from .. import persistence
    out = jobs.set_profile(req.profile, STORE)
    persistence.save(STORE)
    return out


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
