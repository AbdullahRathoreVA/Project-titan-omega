"""How far through setup an account actually is, measured from real state.

The brief asks for a completion score and "a prioritised list of the next best
actions". Both are easy to fake and the fake version is worse than nothing: a
progress bar that moves because somebody clicked "skip" teaches a customer that
the number means nothing.

So every step here is **detected**, never remembered:

* No step is marked done because a wizard was completed. It is marked done
  because the thing it describes is present in the data.
* A check that cannot run answers ``None`` — *unknown* — not ``False``. Those
  are different: "we looked and it is not connected" and "we could not look"
  lead to different next actions, and collapsing them into a red cross sends
  people to fix something that may not be broken.
* Unknown steps are excluded from the denominator. Scoring an account down for
  a check that failed on Titan's side would be blaming the customer for our
  outage.

The score is therefore *completed / checkable*, and the payload says how many
were unknown so the number can be read honestly.
"""

from __future__ import annotations

import time
from typing import Optional

# (key, label, why it matters, optional)
# `optional` steps are shown and are NOT counted in the score — an account can
# be fully set up without them.
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

    Reads through `analytics.accounts_snapshot()` so this and the customers
    screen cannot disagree about which businesses an account really has — that
    snapshot already drops stale client ids and seeded demo records.
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

    # The one check that can genuinely fail on Titan's side, so it is the one
    # that has to be able to say "unknown".
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
        # completed / CHECKABLE. An unknown is not a failure, and counting it
        # as one would score the customer down for our outage.
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
    """Across every account. Averages only over accounts that could be scored,
    and says how many could not."""
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
