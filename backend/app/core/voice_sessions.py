"""Voice agent sessions — the record every dial on the Voice Agents screen reads.

The brief for the 3D dashboard is explicit: *every visual state must map to a
real backend event, every metric must come from actual data, no placeholder
logic pretending to be live.* That constraint is why this module exists before
any of the visuals do. A dashboard cannot honestly animate "thinking" unless
something server-side actually recorded the agent entering that state, and a
latency figure cannot be shown unless a clock was actually read.

So this is the source of truth: a session store, a validated state machine, a
turn-by-turn transcript, a tool-call timeline with an approval gate, and
metrics derived only from timestamps that were genuinely taken.

Design decisions worth knowing:

**The state machine refuses invalid transitions.** `speaking → thinking` is
allowed; `ended → speaking` is not. A store that accepts any transition would
let the dashboard display a state the agent was never in, which is the same
class of lie as a fabricated metric. Rejections name the legal moves.

**Latency is measured, never estimated.** `thinking_ms` is the wall time
between entering `thinking` and leaving it. If a session never passed through
`thinking`, latency is `None` — not `0`, which would read as "instant".

**Cost is `None` unless a provider actually reported one.** Every voice stack
worth using (STT, LLM, TTS, telephony) bills per minute or per character, and
Titan currently runs none of them for money. Displaying `$0.00` would imply a
measured zero. See `docs/VOICE_OS.md` for what each tier would actually cost.

**Sensitive tool calls block on human approval.** Booking, paying, emailing and
deleting are `requires_approval`; they are recorded as `pending` and cannot be
marked executed without an explicit approval. This is Abdullah's standing rule
— nothing reaches a real person or a real account without him — expressed as a
state the store enforces rather than a convention someone has to remember.

Transcripts are personal data. `/api/voice` is registered in
`demo_data._SENSITIVE_PREFIXES` so a public demo visitor is refused outright.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import events

# ------------------------------------------------------------------ states --
IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"
INTERRUPTED = "interrupted"
ESCALATED = "escalated"
ENDED = "ended"

STATES = (IDLE, LISTENING, THINKING, SPEAKING, INTERRUPTED, ESCALATED, ENDED)

# A real barge-in conversation loops listening → thinking → speaking, and the
# caller can interrupt mid-sentence. Escalation is terminal-ish: a human has
# the call, so the agent may only end afterwards.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    IDLE:        (LISTENING, THINKING, SPEAKING, ESCALATED, ENDED),
    LISTENING:   (THINKING, SPEAKING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    # thinking → idle is real: a text-only answer concludes the thought
    # without ever speaking. Found by wiring the actual chat client, which
    # 409'd whenever voice output was switched off.
    THINKING:    (SPEAKING, LISTENING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    SPEAKING:    (LISTENING, THINKING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    # An interrupted turn that simply stops settles back to idle.
    INTERRUPTED: (LISTENING, THINKING, SPEAKING, ESCALATED, ENDED, IDLE),
    ESCALATED:   (ENDED,),
    ENDED:       (),
}

CHANNELS = ("web", "browser", "phone", "whatsapp", "telegram", "email", "internal")

# Actions that touch money, a calendar, or another human. Recorded as pending
# and never executable without an explicit approval.
SENSITIVE_TOOLS = frozenset({
    "book_appointment", "cancel_appointment", "send_email", "send_whatsapp",
    "send_sms", "place_call", "transfer_call", "charge_card", "refund",
    "create_invoice", "delete_record", "update_crm_stage", "publish_post",
})

MAX_SESSIONS = 400          # bounded: free-tier container
MAX_TURNS = 300             # per session

_lock = threading.RLock()
_sessions: dict[str, dict] = {}
_seq = 0


class TransitionError(ValueError):
    """An illegal state change. Named so the API can answer 409, not 500."""


def _now() -> float:
    return time.time()


def start(channel: str = "web", agent: str = "titan-voice",
          language: str = "en", caller: str = "") -> dict:
    """Open a session. Returns the public record."""
    global _seq
    channel = (channel or "web").lower()
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel: {channel}. One of {list(CHANNELS)}.")
    with _lock:
        _seq += 1
        sid = f"vs-{_seq:06d}"
        _sessions[sid] = {
            "id": sid,
            "channel": channel,
            "agent": agent or "titan-voice",
            "language": language or "en",
            # Free text the operator supplied (a number, an email, a handle).
            # Never derived, never enriched — this is not a tracking system.
            "caller": str(caller or "")[:120],
            "state": IDLE,
            "started_at": _now(),
            "ended_at": None,
            "state_changed_at": _now(),
            "history": [{"state": IDLE, "at": _now()}],
            "turns": [],
            "tools": [],
            "escalation": None,
            # Accumulated wall time actually spent thinking, in ms.
            "thinking_ms": 0.0,
            "thinking_spans": 0,
            "cost_usd": None,          # only set if a provider reports one
            "error": None,
        }
        if len(_sessions) > MAX_SESSIONS:
            for stale in sorted(_sessions, key=lambda k: _sessions[k]["started_at"])[
                    :len(_sessions) - MAX_SESSIONS]:
                del _sessions[stale]
    events.emit("VoiceSessionStarted",
                {"session": sid, "channel": channel, "agent": agent},
                actor="voice")
    return public(sid)


def set_state(sid: str, state: str, reason: str = "") -> dict:
    """Move the session. Refuses transitions the machine does not define."""
    state = (state or "").lower()
    if state not in STATES:
        raise ValueError(f"Unknown state: {state}. One of {list(STATES)}.")
    with _lock:
        s = _sessions.get(sid)
        if not s:
            raise KeyError(sid)
        current = s["state"]
        if state == current:
            return _public_locked(s)
        allowed = TRANSITIONS.get(current, ())
        if state not in allowed:
            raise TransitionError(
                f"{current} → {state} is not a legal transition. "
                f"From {current} you may go to: "
                f"{', '.join(allowed) if allowed else 'nowhere — the session has ended'}.")

        now = _now()
        # Measured, not estimated: the clock is read on the way out of
        # thinking, so a session that never thought reports no latency at all.
        if current == THINKING:
            s["thinking_ms"] += (now - s["state_changed_at"]) * 1000.0
            s["thinking_spans"] += 1

        s["state"] = state
        s["state_changed_at"] = now
        s["history"].append({"state": state, "at": now, "reason": reason[:160]})
        if state == ENDED:
            s["ended_at"] = now
        out = _public_locked(s)

    events.emit("VoiceStateChanged",
                {"session": sid, "from": current, "to": state, "reason": reason},
                actor="voice",
                severity="warn" if state in (ESCALATED, INTERRUPTED) else "info")
    return out


def add_turn(sid: str, role: str, text: str, language: str = "",
             confidence: Optional[float] = None) -> dict:
    """Append one transcript turn.

    `confidence` is whatever the recogniser reported, or None. Titan never
    supplies a confidence of its own — a self-assigned score is not evidence,
    which is the same rule the evidence ledger already enforces.
    """
    role = (role or "").lower()
    if role not in ("user", "agent", "human"):
        raise ValueError("role must be user, agent or human")
    with _lock:
        s = _sessions.get(sid)
        if not s:
            raise KeyError(sid)
        turn = {
            "role": role,
            "text": str(text or "")[:4000],
            "at": _now(),
            "language": language or s["language"],
            "confidence": (float(confidence)
                           if isinstance(confidence, (int, float)) else None),
        }
        s["turns"].append(turn)
        if len(s["turns"]) > MAX_TURNS:
            del s["turns"][:len(s["turns"]) - MAX_TURNS]
        # The recogniser is the authority on what language was actually spoken.
        if language and role == "user":
            s["language"] = language
        count = len(s["turns"])
    events.emit("VoiceTurn", {"session": sid, "role": role, "turns": count},
                actor="voice")
    return turn


def record_tool(sid: str, name: str, args_summary: str = "") -> dict:
    """Log a tool call. Sensitive ones land as `pending` and stay there."""
    with _lock:
        s = _sessions.get(sid)
        if not s:
            raise KeyError(sid)
        needs = name in SENSITIVE_TOOLS
        call = {
            "id": f"{sid}-t{len(s['tools']) + 1}",
            "name": name,
            "args_summary": str(args_summary or "")[:300],
            "requires_approval": needs,
            "status": "pending" if needs else "running",
            "started_at": _now(),
            "ended_at": None,
            "ok": None,
            "error": None,
            "approved_by": None,
        }
        s["tools"].append(call)
    events.emit("VoiceToolInvoked",
                {"session": sid, "tool": name, "requires_approval": needs},
                actor="voice", severity="warn" if needs else "info")
    return dict(call)


def approve_tool(sid: str, call_id: str, approver: str) -> dict:
    """A human authorises a sensitive call. Without this it cannot complete."""
    if not approver:
        raise ValueError("An approver is required — that is the whole point.")
    with _lock:
        call = _find_tool(sid, call_id)
        if call["status"] not in ("pending",):
            raise ValueError(f"That call is {call['status']}, not pending.")
        call["status"] = "running"
        call["approved_by"] = str(approver)[:80]
        out = dict(call)
    events.emit("VoiceToolApproved",
                {"session": sid, "tool": call["name"], "by": approver},
                actor="voice")
    return out


def finish_tool(sid: str, call_id: str, ok: bool, error: str = "") -> dict:
    """Close a tool call. A sensitive call still pending cannot be finished —
    that would let an unapproved action be reported as done."""
    with _lock:
        call = _find_tool(sid, call_id)
        if call["requires_approval"] and call["approved_by"] is None:
            raise ValueError(
                f"{call['name']} needs approval before it can be executed. "
                f"Approve it first — this gate is the reason it exists.")
        call["status"] = "done" if ok else "failed"
        call["ok"] = bool(ok)
        call["error"] = str(error or "")[:300]
        call["ended_at"] = _now()
        out = dict(call)
    events.emit("VoiceToolFinished",
                {"session": sid, "tool": call["name"], "ok": bool(ok)},
                actor="voice", severity="info" if ok else "warn")
    return out


def escalate(sid: str, reason: str, to: str = "human") -> dict:
    """Hand the conversation to a person, and say why."""
    with _lock:
        s = _sessions.get(sid)
        if not s:
            raise KeyError(sid)
        s["escalation"] = {"reason": str(reason or "")[:300], "to": to,
                           "at": _now()}
    return set_state(sid, ESCALATED, reason=reason)


def _find_tool(sid: str, call_id: str) -> dict:
    s = _sessions.get(sid)
    if not s:
        raise KeyError(sid)
    for c in s["tools"]:
        if c["id"] == call_id:
            return c
    raise KeyError(call_id)


# ----------------------------------------------------------------- reading --
def _public_locked(s: dict) -> dict:
    dur = (s["ended_at"] or _now()) - s["started_at"]
    spans = s["thinking_spans"]
    return {
        "id": s["id"],
        "channel": s["channel"],
        "agent": s["agent"],
        "language": s["language"],
        "caller": s["caller"],
        "state": s["state"],
        "started_at": s["started_at"],
        "ended_at": s["ended_at"],
        "duration_s": round(dur, 2),
        "turns": len(s["turns"]),
        "tools": len(s["tools"]),
        "pending_approvals": sum(1 for c in s["tools"] if c["status"] == "pending"),
        "escalated": s["state"] == ESCALATED or s["escalation"] is not None,
        "escalation": s["escalation"],
        # None, never 0: a session that never entered `thinking` has no
        # latency to report, and a 0 there would read as instantaneous.
        "avg_thinking_ms": round(s["thinking_ms"] / spans, 1) if spans else None,
        "cost_usd": s["cost_usd"],
        "error": s["error"],
    }


def public(sid: str) -> dict:
    with _lock:
        s = _sessions.get(sid)
        return _public_locked(s) if s else {}


def transcript(sid: str) -> dict:
    """Full replay payload: turns, tools and the state timeline."""
    with _lock:
        s = _sessions.get(sid)
        if not s:
            return {}
        return {
            **_public_locked(s),
            "turns_detail": [dict(t) for t in s["turns"]],
            "tools_detail": [dict(c) for c in s["tools"]],
            "state_history": [dict(h) for h in s["history"]],
        }


def live() -> dict:
    """What is happening right now — the payload the 3D screen renders.

    Every field here is counted from stored sessions. Nothing is sampled,
    smoothed or invented.
    """
    with _lock:
        rows = [_public_locked(s) for s in _sessions.values()]

    active = [r for r in rows if r["state"] != ENDED]
    by_state = {st: sum(1 for r in rows if r["state"] == st) for st in STATES}
    by_channel: dict[str, int] = {}
    for r in active:
        by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + 1

    latencies = [r["avg_thinking_ms"] for r in rows
                 if isinstance(r["avg_thinking_ms"], (int, float))]
    latencies.sort()

    pending = sum(r["pending_approvals"] for r in rows)
    escalated = [r for r in rows if r["escalated"]]

    # Plain-language "what is happening now". The brief asked for it, and it
    # is the line a non-engineer actually reads.
    if not rows:
        summary = "No voice sessions yet. Nothing is running."
    elif not active:
        summary = f"Nothing live. {len(rows)} session{'s' if len(rows) != 1 else ''} finished."
    else:
        bits = [f"{len(active)} live session{'s' if len(active) != 1 else ''}"]
        speaking = by_state.get(SPEAKING, 0)
        listening = by_state.get(LISTENING, 0)
        if speaking:
            bits.append(f"{speaking} speaking")
        if listening:
            bits.append(f"{listening} listening")
        if pending:
            bits.append(f"{pending} waiting for your approval")
        if escalated:
            bits.append(f"{len(escalated)} escalated to a human")
        summary = " · ".join(bits) + "."

    return {
        "summary": summary,
        "active": sorted(active, key=lambda r: -r["started_at"]),
        "active_count": len(active),
        "total_sessions": len(rows),
        "by_state": {k: v for k, v in by_state.items() if v},
        "by_channel": by_channel,
        "pending_approvals": pending,
        "escalated": len(escalated),
        "median_thinking_ms": (latencies[len(latencies) // 2]
                               if latencies else None),
        "measured_latency_sessions": len(latencies),
        # Honest about the one number nobody is measuring yet.
        "cost_usd": None,
        "cost_note": ("No voice provider is billing yet, so there is no cost to "
                      "report. This is null rather than 0.00 because 0.00 would "
                      "claim a measurement that was never taken."),
        "channels_supported": list(CHANNELS),
    }


def history(limit: int = 50) -> list[dict]:
    with _lock:
        rows = [_public_locked(s) for s in _sessions.values()]
    rows.sort(key=lambda r: -r["started_at"])
    return rows[:limit]


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"seq": _seq, "sessions": {k: dict(v) for k, v in _sessions.items()}}


def import_state(data: dict) -> None:
    global _seq
    if not isinstance(data, dict):
        return
    rows = data.get("sessions")
    if not isinstance(rows, dict):
        return
    with _lock:
        _sessions.clear()
        for sid, s in list(rows.items())[-MAX_SESSIONS:]:
            if isinstance(s, dict) and s.get("state") in STATES:
                s.setdefault("turns", [])
                s.setdefault("tools", [])
                s.setdefault("history", [])
                s.setdefault("thinking_ms", 0.0)
                s.setdefault("thinking_spans", 0)
                s.setdefault("escalation", None)
                s.setdefault("cost_usd", None)
                s.setdefault("error", None)
                _sessions[sid] = s
        try:
            _seq = max(int(data.get("seq", 0)), len(_sessions))
        except Exception:
            _seq = len(_sessions)


def reset() -> None:
    """Test seam."""
    global _seq
    with _lock:
        _sessions.clear()
        _seq = 0
