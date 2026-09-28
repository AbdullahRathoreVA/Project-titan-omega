"""Who a request is billed to, and whether they may spend.

Every plan declares `ai_calls_per_month` (Free 50, Individual 500, Business
3000, Enterprise unlimited). Metering happens in one place, `llm.complete()`,
so no model call can skip it. This module connects "who is calling" to "what
they may spend", so core/llm.py doesn't need to know about billing.

Not metered, because there's no subscriber to bill:

  * the founder's own console
  * the heartbeat engines (self-audit, demo workspace, fix cycle, news watch)
  * the public demo

Guessing an account for those would either put usage on someone's bill or
refuse Titan's own background work when a stranger's plan ran out.
"""

from __future__ import annotations

import contextvars
from typing import Optional

# The billing account this request belongs to, if any. Bound once by the
# middleware in main.py rather than in every route that resolves a token.
_account: contextvars.ContextVar[str] = contextvars.ContextVar(
    "titan_billing_account", default="")

AI_CALLS = "ai_calls"


def bind(email: str = "") -> None:
    """Set who the current request is billed to. Empty means nobody."""
    _account.set((email or "").strip().lower())


def current() -> str:
    """The billing account for this request, or "" when there is none."""
    return _account.get()


def reset() -> None:
    """Test seam."""
    _account.set("")


def spend(kind: str = AI_CALLS, cost: int = 1) -> dict:
    """Charge one unit to whoever this request belongs to.

    Returns a verdict:
      {"metered": False, ...}            nobody is bound; not charged, allowed
      {"metered": True, "allowed": True} charged
      {"metered": True, "allowed": False, "reason": ...} over the plan limit

    `metered` is separate from `allowed` because "we didn't charge anyone" and
    "they were within their limit" are different facts.
    """
    email = current()
    if not email:
        return {"metered": False, "allowed": True,
                "reason": "no billing account is bound to this request"}
    try:
        from . import billing
        verdict = billing.consume(email, kind, cost)
    except Exception as exc:                                   # noqa: BLE001
        # A billing failure shouldn't take down the founder's dashboard, so it's
        # allowed but reported as unmetered, with the reason.
        return {"metered": False, "allowed": True,
                "reason": f"quota check failed: {type(exc).__name__}"}
    return {"metered": True, "allowed": bool(verdict.get("allowed")),
            "reason": verdict.get("reason", ""), "account": email}


def no_answer_note(founder_text: str) -> str:
    """What to say when llm.complete() came back empty.

    The founder's screens say which key to set. A subscriber can't set keys,
    so they get the actual reason: their plan's AI calls are used up (and what
    to do about it), or the AI couldn't be reached.
    """
    email = current()
    if not email:
        return founder_text
    try:
        from . import billing
        verdict = billing.check_quota(email, AI_CALLS, 1)
    except Exception:                                          # noqa: BLE001
        verdict = {"allowed": True}
    if not verdict.get("allowed", True):
        parts = [verdict.get("reason")
                 or "This month's AI answers on your plan are used up."]
        if verdict.get("resets_in_days") is not None:
            parts.append(f"It resets in {verdict['resets_in_days']:g} days.")
        if verdict.get("upgrade_gives"):
            parts.append(verdict["upgrade_gives"])
        return " ".join(parts)
    return "The AI could not be reached just now. Please try again in a moment."


def status() -> dict:
    """What this request would be charged to. Diagnostics only."""
    email = current()
    if not email:
        return {"bound": False, "account": None,
                "note": ("Nothing is charged for this request. Founder work, "
                         "heartbeat engines and the public demo are not a "
                         "subscriber's usage.")}
    try:
        from . import billing
        acct = billing.public(email)
    except Exception:
        return {"bound": True, "account": email, "usage": None,
                "note": "The account is bound but its usage could not be read."}
    return {"bound": True, "account": email,
            "usage": acct.get("usage"), "limits": acct.get("limits")}
