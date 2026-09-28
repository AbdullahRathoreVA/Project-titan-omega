"""Who is this request billed to, and may they spend?

Every plan has declared `ai_calls_per_month` since billing was written — Free
50, Individual 500, Business 3000, Enterprise unlimited — and
`billing.check_quota` has always known how to check it. Across **36 call sites**
that reach a language model, **not one metered the account**.
`billing.consume` was called exactly once in the whole application, for audits.

So a free signup could burn an unbounded amount of Groq, Gemini and OpenRouter
quota, and the plan table said otherwise on the pricing page. That is the
fourteenth instance of this repository's dominant defect shape, and the first
that costs money rather than truth.

The metering lives in ONE place — `llm.complete()` — for the same reason: a
limit applied at thirty-six call sites is a limit missing from the
thirty-seventh. This module is the seam between "who is calling" and "what may
they spend", so `core/llm.py` never has to know what billing is.

WHO IS NOT METERED, AND WHY

An unbound request is not charged to anybody and is never refused:

  * the founder's own console — Abdullah is not a subscriber of his own product
  * the heartbeat engines — self-audit, demo workspace, fix cycle, news watch
  * the public demo

Guessing an account for those would either invent usage on somebody's bill or
refuse Titan's own background work when a stranger's plan ran out. Both are
worse than not metering them, and neither is a number anybody measured.
"""

from __future__ import annotations

import contextvars
from typing import Optional

# The billing account this request belongs to, if any. Bound once, by the
# middleware in main.py, rather than at every route that resolves a token —
# same reasoning as metering in llm.complete() rather than at 36 call sites.
_account: contextvars.ContextVar[str] = contextvars.ContextVar(
    "titan_billing_account", default="")

AI_CALLS = "ai_calls"


def bind(email: str = "") -> None:
    """Say who the current request is billed to. Empty means nobody."""
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

    `metered` is reported separately from `allowed` on purpose. "We did not
    charge anyone" and "they were within their limit" are different facts, and
    a caller that cannot tell them apart will eventually report unmetered work
    as free work.
    """
    email = current()
    if not email:
        return {"metered": False, "allowed": True,
                "reason": "no billing account is bound to this request"}
    try:
        from . import billing
        verdict = billing.consume(email, kind, cost)
    except Exception as exc:                                   # noqa: BLE001
        # A billing failure must not silently become a free call. It also must
        # not take down the founder's dashboard, so it is reported as unknown
        # and allowed — and it says which, so nobody reads this as "free".
        return {"metered": False, "allowed": True,
                "reason": f"quota check failed: {type(exc).__name__}"}
    return {"metered": True, "allowed": bool(verdict.get("allowed")),
            "reason": verdict.get("reason", ""), "account": email}


def no_answer_note(founder_text: str) -> str:
    """What to say when llm.complete() came back empty.

    The founder's screens tell him which key to set. A subscriber cannot set
    keys, so they get the real reason instead: their plan's AI calls are used
    up (and what to do about it), or the AI could not be reached.
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
