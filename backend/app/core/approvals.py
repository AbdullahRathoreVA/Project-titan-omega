"""One place to see everything waiting for a human decision.

Brief §24. The gates already existed and were already enforced — a site fix
needs a named approver and refuses a stale proposal, an improvement proposal
refuses anything unmeasured or measured worse, a voice tool call is 403 without
an approver, a social post queues as a draft and cannot auto-send. What did not
exist was anywhere to SEE all of that at once, so the safety was real and
invisible. An operator who cannot find the queue does not work the queue.

**This module never approves anything.** It is a read-only aggregator, and that
is a security property, not a limitation. Each surface's own `approve()` carries
rules this list does not know: `site_fix.approve` refuses a proposal whose page
changed since it was proposed, `improve.approve` refuses a regression. A
central "approve everything" that shortcut those would quietly delete the very
checks this screen exists to advertise. So the list points at the endpoint that
WILL approve each item and stops there. There is a test asserting this module
cannot approve, in the same spirit as the one asserting outreach cannot send.

Sources are enumerated defensively. A surface that fails to report is listed as
an ERROR with its reason — never silently omitted, because a queue that hides
its own gaps is worse than no queue.
"""

from __future__ import annotations

import time
from typing import Any

# Risk is the operator's triage signal, so it describes the BLAST RADIUS if the
# action is wrong, not how likely it is to be wrong.
CLIENT_SITE = "writes to a client's live website"
OWN_BEHAVIOUR = "changes how Titan itself behaves"
LIVE_CALL = "acts during a live phone call"
PUBLIC = "publishes publicly under your name"


def _age(ts: Any) -> float | None:
    """Seconds since `ts`, or None when there is no usable timestamp.

    None, not 0. A missing timestamp is unknown age, and "0 seconds old" would
    be a number nobody measured."""
    try:
        return round(max(0.0, time.time() - float(ts)), 1)
    except (TypeError, ValueError):
        return None


def _site_fixes() -> list[dict]:
    from . import site_fix
    out = []
    for fix in site_fix.awaiting_approval():
        out.append({
            "surface": "site_fix",
            "id": fix["id"],
            "title": fix.get("title") or fix.get("kind") or "site fix",
            "risk": CLIENT_SITE,
            "detail": {
                "client_id": fix.get("client_id"),
                "kind": fix.get("kind"),
                "field": fix.get("field"),
                "link": (fix.get("target") or {}).get("link"),
                "why": fix.get("why"),
                "current": fix.get("current"),
                "proposed": fix.get("proposed"),
                # Titan's OWN audit weight. Never a traffic prediction —
                # site_fix is explicit that it cannot measure a ranking change.
                "audit_weight": fix.get("audit_weight"),
            },
            "created_at": fix.get("created_at"),
            "age_seconds": _age(fix.get("created_at")),
            "approve_with": f"POST /api/account/clients/{fix.get('client_id')}"
                            f"/fixes/{fix['id']}/approve",
            "needs_approver_name": True,
        })
    return out


def _improvements() -> list[dict]:
    from . import improve
    out = []
    for row in improve.listing(status=improve.EVALUATED):
        # A measured regression is never offered for approval — approve()
        # refuses it — so listing it here would be an invitation to a dead end.
        if row.get("regression"):
            continue
        out.append({
            "surface": "improve",
            "id": row["id"],
            "title": f"{row['param']} → {row['proposed_value']}",
            "risk": OWN_BEHAVIOUR,
            "detail": {
                "param": row["param"],
                "from": row.get("baseline_value"),
                "to": row.get("proposed_value"),
                "metric": row.get("metric"),
                "before": row.get("before_metric"),
                "after": row.get("after_metric"),
                "reason": row.get("reason"),
            },
            "created_at": row.get("created_at"),
            "age_seconds": _age(row.get("created_at")),
            "approve_with": f"POST /api/improve/{row['id']}/approve",
            "needs_approver_name": True,
        })
    return out


def _voice_tool_calls() -> list[dict]:
    from . import voice_sessions
    out = []
    for call in voice_sessions.awaiting_approval():
        out.append({
            "surface": "voice",
            "id": f"{call['session_id']}:{call['call_id']}",
            "title": f"{call['name']} during a live {call.get('channel') or 'call'}",
            "risk": LIVE_CALL,
            "detail": {
                "session": call["session_id"],
                "tool": call["name"],
                "args": call["args_summary"],
                "caller": call.get("caller"),
            },
            "created_at": call["started_at"],
            "age_seconds": _age(call["started_at"]),
            "approve_with": f"POST /api/voice/sessions/{call['session_id']}"
                            f"/tool/{call['call_id']}/approve",
            "needs_approver_name": True,
        })
    return out


def _posts(store) -> list[dict]:
    """Drafts queued for publication. Titan never auto-posts; there is a test."""
    out = []
    for post in list(getattr(store, "posts", []) or []):
        data = post if isinstance(post, dict) else getattr(post, "__dict__", {})
        if str(data.get("status")) not in ("scheduled", "queued"):
            continue
        content = str(data.get("content") or "")
        out.append({
            "surface": "publishing",
            "id": str(data.get("id")),
            "title": (content[:70] + "…") if len(content) > 70 else content,
            "risk": PUBLIC,
            "detail": {
                "channels": data.get("channels"),
                "status": data.get("status"),
            },
            "created_at": data.get("created_at"),
            "age_seconds": _age(data.get("created_at")),
            "approve_with": f"POST /api/posts/{data.get('id')}/publish",
            "needs_approver_name": False,
        })
    return out


_SOURCES = (
    ("site_fix", _site_fixes),
    ("improve", _improvements),
    ("voice", _voice_tool_calls),
)


def pending(store=None) -> dict:
    """Everything waiting, newest risk first. Never approves, never mutates."""
    items: list[dict] = []
    errors: list[dict] = []

    for name, fn in _SOURCES:
        try:
            items.extend(fn())
        except Exception as exc:
            # Listed, not swallowed. A surface that cannot report its queue is
            # itself something the operator needs to know about.
            errors.append({"surface": name,
                           "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    if store is not None:
        try:
            items.extend(_posts(store))
        except Exception as exc:
            errors.append({"surface": "publishing",
                           "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    # Oldest first: the thing that has been waiting longest is the thing most
    # likely to be forgotten. Items with no timestamp sort last rather than
    # being treated as infinitely old.
    items.sort(key=lambda i: (i.get("age_seconds") is None,
                              -(i.get("age_seconds") or 0.0)))

    by_surface: dict[str, int] = {}
    for item in items:
        by_surface[item["surface"]] = by_surface.get(item["surface"], 0) + 1

    ages = [i["age_seconds"] for i in items if i.get("age_seconds") is not None]
    return {
        "items": items,
        "count": len(items),
        "by_surface": by_surface,
        # None until something is actually waiting — not 0.
        "oldest_seconds": max(ages) if ages else None,
        "errors": errors,
        "note": ("Read-only. Approving happens on each item's own endpoint, "
                 "which enforces the rules this list does not know — a site "
                 "fix whose page changed since it was proposed is refused, and "
                 "an improvement that measured worse is refused. Nothing here "
                 "can approve anything."),
    }
