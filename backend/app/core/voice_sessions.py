"""Voice agent sessions - the data the Voice Agents screen is drawn from.

Every visual state on that screen must map to a real backend event and every
metric to real data. The screen can only show "thinking" if the server
recorded the agent entering that state, and a latency only if a clock was
read.

So this is the source of truth: a session store, a validated state machine, a
turn-by-turn transcript, a tool-call timeline with an approval gate, and
metrics derived only from recorded timestamps.

- The state machine refuses invalid transitions. `speaking -> thinking` is
  allowed, `ended -> speaking` isn't, so the dashboard can never show a state
  the agent wasn't in. Rejections name the allowed moves.
- Latency is measured, never estimated. `thinking_ms` is the wall time spent
  in `thinking`. A session that never passed through `thinking` has latency
  None, not 0 (which would read as instant).
- Cost is None unless a provider reported one. The voice stack (STT, LLM,
  TTS, telephony) bills per minute or character, and none of it is currently
  paid for, so $0.00 would suggest a measured zero. See `docs/VOICE_OS.md`
  for what each tier would cost.
- Sensitive tool calls wait for human approval. Booking, paying, emailing and
  deleting are `requires_approval`: recorded as `pending` and not markable as
  executed without an explicit approval. The store enforces this rather than
  relying on convention.

Transcripts are personal data. `/api/voice` is in
`demo_data._SENSITIVE_PREFIXES`, so public demo visitors are refused.

Every session has an owner. `account` is "" for the founder and the
subscriber's email for sessions started from their own cockpit (/api/me).
Reads return only the caller's sessions, and someone else's session looks
exactly like one that doesn't exist, so ids can't be probed.
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

# A real conversation loops listening -> thinking -> speaking, and the caller
# can interrupt mid-sentence. Escalation is nearly terminal: a person has the
# call, so the agent may only end afterwards.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    IDLE:        (LISTENING, THINKING, SPEAKING, ESCALATED, ENDED),
    LISTENING:   (THINKING, SPEAKING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    # thinking -> idle happens when a text-only answer finishes without speaking
    # (e.g. the chat client with voice output switched off).
    THINKING:    (SPEAKING, LISTENING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    SPEAKING:    (LISTENING, THINKING, INTERRUPTED, ESCALATED, ENDED, IDLE),
    # An interrupted turn that simply stops settles back to idle.
    INTERRUPTED: (LISTENING, THINKING, SPEAKING, ESCALATED, ENDED, IDLE),
    ESCALATED:   (ENDED,),
    ENDED:       (),
}

CHANNELS = ("web", "browser", "phone", "whatsapp", "telegram", "email", "internal")

# Actions that touch money, a calendar, or another person. Recorded as pending
# and never executable without explicit approval.
SENSITIVE_TOOLS = frozenset({
    "book_appointment", "cancel_appointment", "send_email", "send_whatsapp",
    "send_sms", "place_call", "transfer_call", "charge_card", "refund",
    "create_invoice", "delete_record", "update_crm_stage", "publish_post",
})

MAX_SESSIONS = 400          # bounded: small container
MAX_TURNS = 300             # per session
# So one subscriber can't fill the store and push everyone else's history out.
MAX_PER_ACCOUNT = 60

FOUNDER = ""                # the owner of every session started at /api

_lock = threading.RLock()
_sessions: dict[str, dict] = {}
_seq = 0


class TransitionError(ValueError):
    """An illegal state change. Named so the API can answer 409, not 500."""


def _now() -> float:
    return time.time()


def _owned(sid: str, account: str) -> dict:
    """The session, if `account` owns it. Call with the lock held."""
    s = _sessions.get(sid)
    if not s or s.get("account", FOUNDER) != account:
        raise KeyError(sid)
    return s


def _mine(account: str) -> list[dict]:
    return [s for s in _sessions.values()
            if s.get("account", FOUNDER) == account]


def start(channel: str = "web", agent: str = "titan-voice",
          language: str = "en", caller: str = "",
          account: str = FOUNDER) -> dict:
    """Open a session. Returns the public record."""
    global _seq
    # Raised rather than returned, like the channel check below: this function
    # already raises on refusal, and a caller that gets a session back should be
    # able to assume it can speak.
    from . import flags
    flags.require("voice")
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
            # Free text the operator supplied (a number, an email, a handle). Never
            # derived or enriched - this isn't a tracking system.
            "caller": str(caller or "")[:120],
            "account": account,
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
        if account != FOUNDER:
            own = sorted(_mine(account), key=lambda r: r["started_at"])
            for stale in own[:max(0, len(own) - MAX_PER_ACCOUNT)]:
                del _sessions[stale["id"]]
        if len(_sessions) > MAX_SESSIONS:
            for stale in sorted(_sessions, key=lambda k: _sessions[k]["started_at"])[
                    :len(_sessions) - MAX_SESSIONS]:
                del _sessions[stale]
    events.emit("VoiceSessionStarted",
                {"session": sid, "channel": channel, "agent": agent},
                actor="voice")
    return public(sid)


def set_state(sid: str, state: str, reason: str = "",
              account: str = FOUNDER) -> dict:
    """Move the session. Refuses transitions the machine doesn't define."""
    state = (state or "").lower()
    if state not in STATES:
        raise ValueError(f"Unknown state: {state}. One of {list(STATES)}.")
    with _lock:
        s = _owned(sid, account)
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
        # Measured, not estimated: the clock is read on the way out of thinking, so a
        # session that never thought reports no latency at all.
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
             confidence: Optional[float] = None,
             account: str = FOUNDER) -> dict:
    """Append one transcript turn.

    `confidence` is whatever the recogniser reported, or None. Titan never
    supplies its own - a self-assigned score isn't evidence (same rule as the
    evidence ledger).
    """
    role = (role or "").lower()
    if role not in ("user", "agent", "human"):
        raise ValueError("role must be user, agent or human")
    with _lock:
        s = _owned(sid, account)
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
        # The recogniser decides what language was actually spoken.
        if language and role == "user":
            s["language"] = language
        count = len(s["turns"])
    events.emit("VoiceTurn", {"session": sid, "role": role, "turns": count},
                actor="voice")
    return turn


def record_tool(sid: str, name: str, args_summary: str = "",
                account: str = FOUNDER) -> dict:
    """Log a tool call. Sensitive ones land as `pending` and stay there."""
    with _lock:
        s = _owned(sid, account)
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


def approve_tool(sid: str, call_id: str, approver: str,
                 account: str = FOUNDER) -> dict:
    """A person authorises a sensitive call. Without this it can't complete."""
    if not approver:
        raise ValueError("An approver is required — that is the whole point.")
    with _lock:
        call = _find_tool(sid, call_id, account)
        if call["status"] not in ("pending",):
            raise ValueError(f"That call is {call['status']}, not pending.")
        call["status"] = "running"
        call["approved_by"] = str(approver)[:80]
        out = dict(call)
    events.emit("VoiceToolApproved",
                {"session": sid, "tool": call["name"], "by": approver},
                actor="voice")
    return out


def finish_tool(sid: str, call_id: str, ok: bool, error: str = "",
                account: str = FOUNDER) -> dict:
    """Close a tool call. A sensitive call still pending can't be finished,
    or an unapproved action could be reported as done.
    """
    with _lock:
        call = _find_tool(sid, call_id, account)
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


def escalate(sid: str, reason: str, to: str = "human",
             account: str = FOUNDER) -> dict:
    """Hand the conversation to a person, and say why."""
    with _lock:
        s = _owned(sid, account)
        s["escalation"] = {"reason": str(reason or "")[:300], "to": to,
                           "at": _now()}
    return set_state(sid, ESCALATED, reason=reason, account=account)


def _find_tool(sid: str, call_id: str, account: str) -> dict:
    s = _owned(sid, account)
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
        # None, never 0: a session that never entered `thinking` has no latency, and
        # 0 would read as instant.
        "avg_thinking_ms": round(s["thinking_ms"] / spans, 1) if spans else None,
        "cost_usd": s["cost_usd"],
        "error": s["error"],
    }


def public(sid: str) -> dict:
    with _lock:
        s = _sessions.get(sid)
        return _public_locked(s) if s else {}


def awaiting_approval(account: str = FOUNDER) -> list[dict]:
    """Every sensitive tool call sitting in `pending`, oldest first.

    `live()` reports `tools` as a count, which suits the 3D screen but not an
    approval queue. This returns the calls themselves, without the transcript.
    """
    out = []
    with _lock:
        for s in _mine(account):
            for call in s["tools"]:
                if call["status"] != "pending":
                    continue
                out.append({
                    "session_id": s["id"],
                    "call_id": call["id"],
                    "name": call["name"],
                    "args_summary": call["args_summary"],
                    "started_at": call["started_at"],
                    "channel": s["channel"],
                    "caller": s["caller"],
                })
    return sorted(out, key=lambda c: c["started_at"])


def transcript(sid: str, account: str = FOUNDER) -> dict:
    """Full replay payload: turns, tools and the state timeline."""
    with _lock:
        try:
            s = _owned(sid, account)
        except KeyError:
            return {}
        return {
            **_public_locked(s),
            "turns_detail": [dict(t) for t in s["turns"]],
            "tools_detail": [dict(c) for c in s["tools"]],
            "state_history": [dict(h) for h in s["history"]],
        }


def live(account: str = FOUNDER) -> dict:
    """What's happening right now - the payload the 3D screen renders.

    Every field is counted from stored sessions; nothing is sampled, smoothed
    or made up.
    """
    with _lock:
        rows = [_public_locked(s) for s in _mine(account)]
    return summarise(rows)


def summarise(rows: list) -> dict:
    """Turn session rows into the live payload.

    Split out of `live()` so the public demo renders the same shape from sample
    rows. A hand-written copy would drift: a new field here would show as
    `undefined` in the demo.
    """
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

    # Plain-language "what's happening now" - the line a non-engineer actually
    # reads.
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
        # Nobody measures this yet.
        "cost_usd": None,
        "cost_note": ("No voice provider is billing yet, so there is no cost to "
                      "report. This is null rather than 0.00 because 0.00 would "
                      "claim a measurement that was never taken."),
        "channels_supported": list(CHANNELS),
    }


def demo_rows() -> list:
    """Sample sessions for the public demo, in `_public_locked` shape.

    `/api/voice` is blocked for guests, so without this the demo couldn't show
    Voice at all. Everything here is obviously sample data for a fictional
    shop - no real caller number, transcript or client - and it goes through
    the real `summarise()`, so it can't drift from the live shape.
    """
    now = _now()
    return [
        {"id": "demo-1", "channel": "phone", "agent": "titan-voice",
         "language": "en", "caller": "+00 000 0000 (sample)",
         "state": LISTENING, "started_at": now - 42, "ended_at": None,
         "duration_s": 42.0, "turns": 6, "tools": 1,
         "pending_approvals": 1, "escalated": False, "escalation": None,
         "avg_thinking_ms": 610.0, "cost_usd": None, "error": None},
        {"id": "demo-2", "channel": "web", "agent": "titan-voice",
         "language": "ur", "caller": "web visitor (sample)",
         "state": ENDED, "started_at": now - 900, "ended_at": now - 780,
         "duration_s": 120.0, "turns": 11, "tools": 2,
         "pending_approvals": 0, "escalated": False, "escalation": None,
         "avg_thinking_ms": 540.0, "cost_usd": None, "error": None},
    ]


def history(limit: int = 50, account: str = FOUNDER) -> list[dict]:
    with _lock:
        rows = [_public_locked(s) for s in _mine(account)]
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
