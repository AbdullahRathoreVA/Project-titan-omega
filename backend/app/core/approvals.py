"""Everything waiting for a human decision, in one list.

Each gate is enforced where it lives: a site fix needs a named approver and
refuses a stale proposal, an improvement refuses anything unmeasured or
worse, a voice tool call needs an approver, a social post can only be queued.
This collects them so the queue is visible in one place.

Read-only by design. Each surface's approve() has rules this list doesn't
know (site_fix refuses a proposal whose page has changed, improve refuses a
regression), so the list only points at the endpoint that approves each item.
A test checks that this module can't approve anything.

A surface that fails to report is listed as an error with the reason rather
than silently left out.
"""

from __future__ import annotations

import time
from typing import Any

# Risk describes the blast radius if the action is wrong, not how likely it
# is to be wrong.
CLIENT_SITE = "writes to a client's live website"
OWN_BEHAVIOUR = "changes how Titan itself behaves"
LIVE_CALL = "acts during a live phone call"
PUBLIC = "publishes publicly under your name"


def _age(ts: Any) -> float | None:
    """Seconds since `ts`, or None when there's no usable timestamp (unknown age,
    not zero).
    """
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
                # Titan's own audit weight - not a traffic prediction.
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
        # approve() refuses a measured regression, so don't list it.
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
    """Drafts queued for publication. Titan never posts on its own (there's a test)."""
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
    """Everything waiting, oldest first. Never approves or changes anything."""
    items: list[dict] = []
    errors: list[dict] = []

    for name, fn in _SOURCES:
        try:
            items.extend(fn())
        except Exception as exc:
            # Listed rather than swallowed: a surface that can't report is worth knowing about.
            errors.append({"surface": name,
                           "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    if store is not None:
        try:
            items.extend(_posts(store))
        except Exception as exc:
            errors.append({"surface": "publishing",
                           "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    # Oldest first - the longest wait is the likeliest to be forgotten. Items
    # without a timestamp go last.
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
        # None until something is waiting.
        "oldest_seconds": max(ages) if ages else None,
        "errors": errors,
        "note": ("Read-only. Approving happens on each item's own endpoint, "
                 "which enforces the rules this list does not know — a site "
                 "fix whose page changed since it was proposed is refused, and "
                 "an improvement that measured worse is refused. Nothing here "
                 "can approve anything."),
    }
