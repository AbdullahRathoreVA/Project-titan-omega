"""How far through setup an account is, detected from its actual data.

- A step is done because the thing it describes exists, not because a wizard
  was clicked through.
- A check that can't run returns None (unknown), not False.
- Unknown steps are left out of the denominator, so an account isn't scored
  down for a failure on our side.

The score is completed / checkable, and the payload says how many steps
were unknown.
"""

from __future__ import annotations

import time
from typing import Optional

# (key, label, why it matters, optional)
# Optional steps are shown but not counted in the score.
STEPS = (
    ("account", "Account created", "You are here.", False),
    ("business", "Business added",
     "Titan needs to know which business it is working for.", False),
    ("website", "Website set",
     "Every audit, fix and report is anchored to a real URL.", False),
    ("audit", "First audit run",
     "The audit is what produces findings to act on.", False),
    ("site_connected", "Website connected",
     "A scoped credential lets Titan apply approved fixes, not just report "
     "them.", False),
    ("report", "Report downloaded",
     "The PDF is the thing most people share internally.", True),
)


def _unknown(reason: str) -> dict:
    return {"done": None, "source": "unavailable", "reason": reason}


def _done(done: bool, source: str) -> dict:
    return {"done": bool(done), "source": source, "reason": ""}


def for_account(email: str) -> dict:
    """Detected setup state for one subscriber.

    Reads through analytics.accounts_snapshot() so this and the customers screen
    agree on which businesses an account has (the snapshot already drops stale
    client ids and demo records).
    """
    from . import analytics

    try:
        snap = analytics.accounts_snapshot()
    except Exception as exc:
        return {"email": email, "steps": [], "score_pct": None,
                "measured": False,
                "reason": f"Account state could not be read: {exc}"}

    row = next((a for a in snap["accounts"] if a["email"] == email), None)
    if row is None:
        return {"email": email, "steps": [], "score_pct": None,
                "measured": False, "reason": "No such account."}

    checks: dict[str, dict] = {"account": _done(True, "billing account")}

    businesses = row.get("businesses", [])
    checks["business"] = _done(bool(businesses), "billing account")
    checks["website"] = _done(
        any(b.get("website") for b in businesses), "client registry")
    checks["audit"] = _done(
        int(row.get("usage", {}).get("audits", 0)) > 0, "usage counters")
    checks["report"] = _done(
        bool(row.get("actions", {}).get(analytics.DOWNLOADED_REPORT)),
        "activity log")

    # The one check that can fail on our side, so it can return "unknown".
    try:
        from . import site_access
        connected = any(
            site_access.status(b["id"]).get("connected") for b in businesses)
        checks["site_connected"] = _done(connected, "credential vault")
    except Exception as exc:
        checks["site_connected"] = _unknown(
            f"The credential vault could not be read: {str(exc)[:120]}")

    steps, done_n, checkable, unknown_n = [], 0, 0, 0
    for key, label, why, optional in STEPS:
        state = checks.get(key, _unknown("No detector for this step."))
        steps.append({"key": key, "label": label, "why": why,
                      "optional": optional, **state})
        if optional:
            continue
        if state["done"] is None:
            unknown_n += 1
            continue
        checkable += 1
        if state["done"]:
            done_n += 1

    return {
        "email": email,
        "steps": steps,
        # completed / checkable - an unknown step isn't counted against the account.
        "score_pct": round(100.0 * done_n / checkable, 1) if checkable else None,
        "completed": done_n,
        "checkable": checkable,
        "unknown": unknown_n,
        "measured": checkable > 0,
        "next_actions": [
            {"key": s["key"], "label": s["label"], "why": s["why"]}
            for s in steps if s["done"] is False and not s["optional"]
        ],
        "generated_at": time.time(),
    }


def summary() -> dict:
    """Across all accounts. Averages only over accounts that could be scored and
    says how many couldn't.
    """
    from . import analytics
    try:
        snap = analytics.accounts_snapshot()
    except Exception as exc:
        return {"accounts": 0, "average_pct": None, "measured": False,
                "reason": f"Account state could not be read: {exc}"}

    scores = []
    unscored = 0
    for row in snap["accounts"]:
        rec = for_account(row["email"])
        if rec.get("score_pct") is None:
            unscored += 1
        else:
            scores.append(rec["score_pct"])

    if not scores:
        return {
            "accounts": len(snap["accounts"]), "average_pct": None,
            "measured": False, "unscored": unscored,
            "reason": ("No account could be scored yet. With no accounts, an "
                       "average completion of 0% would describe nobody."),
        }
    return {
        "accounts": len(snap["accounts"]),
        "average_pct": round(sum(scores) / len(scores), 1),
        "measured": True,
        "scored": len(scores),
        "unscored": unscored,
    }
