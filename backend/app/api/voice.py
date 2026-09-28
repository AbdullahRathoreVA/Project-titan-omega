"""Voice agent API: sessions, transcripts, tool timeline, approvals, replay.

Every endpoint reads or writes the store in `core/voice_sessions.py`, which is
the only source the 3D Voice Agents screen renders from, so nothing on it is
decorative.

The whole prefix is in `demo_data._SENSITIVE_PREFIXES`: transcripts are the
most personal data Titan holds and there's no demo-safe version.

Subscribers reach the session routes through /api/me/voice/*. Every route
passes `_owner()` down, so they only see and act on their own sessions; the
founder's /api/voice only sees the founder's.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import persistence
from ..core import cockpit_scope
from ..core import voice_sessions as vs
from ..store import STORE

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _owner() -> str:
    return cockpit_scope.customer_email() or vs.FOUNDER


class StartIn(BaseModel):
    channel: str = Field(default="web")
    agent: str = Field(default="titan-voice")
    language: str = Field(default="en")
    caller: str = Field(default="")


class StateIn(BaseModel):
    state: str
    reason: str = Field(default="")


class TurnIn(BaseModel):
    role: str
    text: str
    language: str = Field(default="")
    confidence: Optional[float] = None


class ToolIn(BaseModel):
    name: str
    args_summary: str = Field(default="")


class ApproveIn(BaseModel):
    approver: str


class FinishIn(BaseModel):
    ok: bool
    error: str = Field(default="")


class EscalateIn(BaseModel):
    reason: str
    to: str = Field(default="human")


@router.get("/live")
def live() -> dict:
    """What's happening right now. The 3D screen polls this."""
    return vs.live(account=_owner())


@router.get("/sessions")
def sessions(limit: int = Query(default=50, ge=1, le=400)) -> dict:
    return {"sessions": vs.history(limit, account=_owner()), "states": list(vs.STATES),
            "channels": list(vs.CHANNELS)}


@router.get("/sessions/{sid}")
def session_detail(sid: str) -> dict:
    """Full replay: every turn, every tool call, the whole state timeline."""
    data = vs.transcript(sid, account=_owner())
    if not data:
        raise HTTPException(status_code=404, detail="No such session")
    return data


@router.post("/sessions")
def start_session(req: StartIn) -> dict:
    try:
        out = vs.start(req.channel, req.agent, req.language, req.caller,
                       account=_owner())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persistence.save(STORE)
    return out


@router.post("/sessions/{sid}/state")
def change_state(sid: str, req: StateIn) -> dict:
    try:
        return vs.set_state(sid, req.state, req.reason, account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session")
    except vs.TransitionError as e:
        # 409, not 400: the request is well-formed, but the session isn't in a state
        # where this move is allowed.
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{sid}/turn")
def add_turn(sid: str, req: TurnIn) -> dict:
    try:
        return vs.add_turn(sid, req.role, req.text, req.language,
                           req.confidence, account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{sid}/tool")
def record_tool(sid: str, req: ToolIn) -> dict:
    """Log a tool call. Sensitive names come back `pending` — see
    voice_sessions.SENSITIVE_TOOLS for which and why."""
    try:
        return vs.record_tool(sid, req.name, req.args_summary,
                              account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session")


@router.post("/sessions/{sid}/tool/{call_id}/approve")
def approve(sid: str, call_id: str, req: ApproveIn) -> dict:
    # A subscriber approves as themselves. The name in the body is only trusted
    # from the founder.
    owner = _owner()
    approver = owner or req.approver
    try:
        out = vs.approve_tool(sid, call_id, approver, account=owner)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session or call")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persistence.save(STORE)
    return out


@router.post("/sessions/{sid}/tool/{call_id}/finish")
def finish(sid: str, call_id: str, req: FinishIn) -> dict:
    try:
        return vs.finish_tool(sid, call_id, req.ok, req.error,
                              account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session or call")
    except ValueError as e:
        # An unapproved sensitive call can't be reported as executed.
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/sessions/{sid}/escalate")
def escalate(sid: str, req: EscalateIn) -> dict:
    try:
        out = vs.escalate(sid, req.reason, req.to, account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session")
    except vs.TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    persistence.save(STORE)
    return out


@router.post("/sessions/{sid}/end")
def end_session(sid: str) -> dict:
    try:
        out = vs.set_state(sid, vs.ENDED, "closed", account=_owner())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such session")
    except vs.TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    persistence.save(STORE)
    return out


class KnowledgeAsk(BaseModel):
    client_id: str
    question: str = Field(..., min_length=2)
    lang: str = Field(default="en")


@router.post("/knowledge/ask")
def knowledge_ask(req: KnowledgeAsk) -> dict:
    """Answer a caller's question from that business's own website.

    Every answer comes from pages Titan actually crawled and carries the URL it
    came from. When the site doesn't cover the question it says so - an
    invented opening time sends a customer to a closed door.
    """
    from ..core import knowledge
    return knowledge.answer(req.client_id, req.question, req.lang)


@router.get("/knowledge/{client_id}")
def knowledge_stats(client_id: str) -> dict:
    """What Titan knows about this business, and from which pages."""
    from ..core import knowledge
    return knowledge.stats(client_id)


@router.post("/knowledge/backfill")
def knowledge_backfill(client_id: str = "") -> dict:
    """Embed passages indexed before the model finished downloading.

    The first pages are usually indexed while the ~130 MB model is still
    downloading; without this a client would stay keyword-only until its next
    audit.
    """
    from ..core import knowledge
    return knowledge.backfill(client_id)


@router.get("/retrieval")
def retrieval_status() -> dict:
    """Which ranking is running right now, and why.

    Semantic search is an upgrade, not a dependency. This reports when it's
    still downloading or couldn't start, so the dashboard doesn't claim a
    capability the container doesn't have.
    """
    from ..core import embeddings
    return embeddings.status()


@router.get("/capabilities")
def capabilities() -> dict:
    """What the voice layer can do on this deployment right now.

    Reports configuration, not intent: listing "phone" as a channel with no
    telephony credentials would be a false claim.
    """
    import os
    from ..core import tools as tool_layer

    # A subscriber's cockpit never uses the founder's keys, so for them every
    # keyed provider is reported as not ready.
    customer = cockpit_scope.is_customer()

    def has(*names: str) -> bool:
        return not customer and all(os.getenv(n, "").strip() for n in names)

    reg = {}
    try:
        if not customer:
            reg = tool_layer.registry_report()
    except Exception:
        pass

    return {
        "browser_speech": {
            "ready": True,
            "cost": "free",
            "note": ("Web Speech API in the visitor's own browser. Speech in "
                     "and out at no cost, no key, no server. Chrome and Edge "
                     "support the microphone; Firefox does not."),
        },
        "livekit": {
            "ready": has("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"),
            "cost": "free tier, then per connection-minute",
            "note": ("Apache-2.0, already registered as a tool adapter. It "
                     "carries audio — it does NOT do speech-to-text or "
                     "text-to-speech, so it is transport, not a voice stack."),
        },
        "premium_tts": {
            "ready": has("ELEVENLABS_API_KEY"),
            "cost": "free character cap, then paid",
            "note": "ElevenLabs. Optional adapter; browser speech is the default.",
        },
        "telephony": {
            "ready": False,
            "cost": "paid, per minute",
            "note": ("Phone calls are not available on your plan yet."
                     if customer else
                     "No telephony provider is configured. Real phone calls "
                     "require an account in Abdullah's name with ID "
                     "verification — there is no free path to placing a call."),
        },
        "tool_registry": reg.get("tools", []) if isinstance(reg, dict) else [],
        "channels": list(vs.CHANNELS),
        "note": ("Reported from configuration, not from a wish list. A channel "
                 "marked not-ready cannot be used until its credential exists."),
    }
