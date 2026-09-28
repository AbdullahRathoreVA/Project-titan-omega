"""Executive metrics, each saying whether it was actually measured.

A metric that can't be measured reads "Not measured" rather than being
invented, so each one returns a shape instead of a bare number:

    {"value": 41.0, "measured": true,  "source": "...",  "note": "..."}
    {"value": null, "measured": false, "reason": "Billing is not connected."}

`value` is None whenever `measured` is false; there's no zero stand-in. With
no payment processor connected, an MRR of 0.0 would claim nobody paid, when
really nobody could pay and nothing was measured.

What's measurable today:

* Customer counts, plan distribution and signup-to-paying conversion, from
  durable account state, so correct for every account ever created.
* Not MRR or ARR while no payment processor is configured. Once one is,
  0.0 becomes a real measurement.
* Not trial customers. `billing` has a trial length per plan but no trial
  state per account (no `trial_ends_at`), so "who's in a trial now" can't be
  answered, and the reason names the missing field.
* Churn depends on `subscription_events`, which only records from when it was
  added. It reads "not measured" until there's history and at least one paid
  subscription to churn from.

Demo records and granted seats never count as customers.
`analytics.accounts_snapshot()` already excludes both, and this reads from it
rather than keeping a second opinion about who counts.
"""

from __future__ import annotations

import time
from typing import Any, Optional

DAY = 86400.0


def measured(value: Any, source: str, note: str = "") -> dict:
    return {"value": value, "measured": True, "source": source, "note": note}


def not_measured(reason: str, source: str = "") -> dict:
    """`value` is None, never 0. A zero is a measurement."""
    return {"value": None, "measured": False, "source": source,
            "reason": reason}


def _snapshot() -> dict:
    from . import analytics
    return analytics.accounts_snapshot()


# ------------------------------------------------------------- customers --
def customers(snap: Optional[dict] = None) -> dict:
    """Counts from durable account state, so correct for every account ever
    created, not only those seen since the activity log started.
    """
    snap = snap or _snapshot()
    accounts = snap["accounts"]
    now = time.time()
    total = len(accounts)
    active_7d = sum(1 for a in accounts
                    if a.get("last_seen_at")
                    and now - a["last_seen_at"] <= 7 * DAY)
    dormant = sum(1 for a in accounts
                  if not a.get("last_seen_at")
                  or now - a["last_seen_at"] > 30 * DAY)
    return {
        "total": measured(total, "billing accounts"),
        "paying": measured(snap["paying"], "billing accounts",
                           "Excludes granted seats and demo records."),
        "granted": measured(snap["granted_paid_plans"], "billing accounts",
                            "On a paid plan, never charged."),
        "active_last_7_days": measured(active_7d, "activity log"),
        "dormant_30_days": measured(dormant, "activity log"),
    }


def plan_distribution(snap: Optional[dict] = None) -> dict:
    snap = snap or _snapshot()
    return measured(snap["by_plan"], "billing accounts")


# ---------------------------------------------------------------- money --
def _billing_connected() -> tuple:
    from . import billing
    try:
        return bool(billing.processor_configured()), billing.processor_name()
    except Exception:
        return False, "none"


def mrr(snap: Optional[dict] = None) -> dict:
    """Committed monthly recurring revenue.

    Unmeasured, not zero, while no processor is connected: nobody could have
    paid, and "$0 revenue" would read as a business result rather than a
    missing integration.
    """
    connected, name = _billing_connected()
    if not connected:
        return not_measured(
            "Billing is not connected, so no payment has ever been possible "
            "and revenue has not been measured. Configure a payment processor "
            "to make this a real number.", "billing")
    snap = snap or _snapshot()
    return measured(round(float(snap["committed_usd"]), 2), f"billing ({name})",
                    "Sum of list prices of active paid plans, excluding "
                    "granted seats.")


def arr(snap: Optional[dict] = None) -> dict:
    """Twelve times MRR, and unmeasured for as long as MRR is.

    Deriving a number from an unmeasured one mustn't make it look measured.
    """
    base = mrr(snap)
    if not base["measured"]:
        return not_measured(base["reason"], base.get("source", "billing"))
    return measured(round(base["value"] * 12, 2), base["source"],
                    "MRR x 12. Not a forecast.")


def granted_list_value(snap: Optional[dict] = None) -> dict:
    """What the granted seats would be worth. Kept separate from MRR so pilot
    accounts are never mistaken for revenue.
    """
    snap = snap or _snapshot()
    return measured(round(float(snap["granted_list_value_usd"]), 2),
                    "billing accounts",
                    "List value of seats handed out. Never charged, never "
                    "counted as revenue.")


# ----------------------------------------------------------- conversion --
def conversion(snap: Optional[dict] = None) -> dict:
    """Signed up -> paying, over every account ever created.

    Cumulative, not a cohort rate: an account that signed up yesterday hasn't
    had a chance to convert, so this understates a growing business and
    overstates a shrinking one.
    """
    snap = snap or _snapshot()
    total = len(snap["accounts"])
    if total == 0:
        return not_measured(
            "No accounts exist yet, so there is no conversion to measure.",
            "billing accounts")
    paying = snap["paying"]
    return measured(round(100.0 * paying / total, 1), "billing accounts",
                    f"{paying} of {total} accounts. Cumulative, not a cohort "
                    "rate.")


def trial_customers() -> dict:
    """Not measurable; the reason names the missing field.

    `billing.trial_days()` belongs to a plan. There's no per-account trial
    state (no `trial_ends_at`), and guessing from the signup date and trial
    length would give a number that looks right and isn't.
    """
    return not_measured(
        "Trials are configured per plan but not tracked per account: a "
        "billing record has no trial_ends_at. Nothing currently distinguishes "
        "an account inside a trial from one that never started it.",
        "billing")


# ---------------------------------------------------------------- churn --
def churn(days: int = 30) -> dict:
    """Paid subscriptions that fell back to free, or were cancelled, in the
    window, as a share of the paid subscriptions that could have churned.

    Unmeasurable in two cases, both reported:

    1. `subscription_events` only records from when it was added; earlier
       plan changes overwrote the plan in place.
    2. A churn rate over zero paid subscriptions is a division by nothing.
    """
    from . import billing

    window = max(1, int(days)) * DAY
    cutoff = time.time() - window
    rows = billing.history(limit=1000)
    if not rows:
        return not_measured(
            "No subscription history has been recorded yet. Plan changes are "
            "durable from now on, so this becomes measurable once one occurs.",
            "subscription_events")

    paid_plans = {k for k, p in billing.PLANS.items() if p.price_usd > 0}
    in_window = [r for r in rows if r["ts"] >= cutoff]

    # Anyone who held a paid plan during the window could churn out of it. Granted
    # seats are excluded: losing a seat nobody paid for isn't revenue churn.
    at_risk = {r["email"] for r in in_window
               if r["to_plan"] in paid_plans and not r["granted"]}
    at_risk |= {r["email"] for r in in_window
                if (r["from_plan"] or "") in paid_plans and not r["granted"]}
    if not at_risk:
        return not_measured(
            f"No paid subscription existed in the last {int(days)} days, so "
            "there was nothing to churn. Zero percent churn on zero customers "
            "would not mean anything.", "subscription_events")

    lost = {r["email"] for r in in_window
            if (r["from_plan"] or "") in paid_plans
            and (r["to_plan"] not in paid_plans or r["status"] != "active")
            and not r["granted"]}
    return measured(round(100.0 * len(lost) / len(at_risk), 1),
                    "subscription_events",
                    f"{len(lost)} of {len(at_risk)} paid subscriptions in the "
                    f"last {int(days)} days.")


# --------------------------------------------------------------- report --
def report(days: int = 30) -> dict:
    """Everything above in one payload, plus whether any of it survives.

    On the current free tier the account store is wiped by a rebuild, so
    `durable` says whether these counts outlive the next deploy.
    """
    snap = _snapshot()
    durable = False
    try:
        from . import db
        durable = bool(db.stats().get("durable"))
    except Exception:
        durable = False

    metrics = {
        "customers": customers(snap),
        "plan_distribution": plan_distribution(snap),
        "mrr_usd": mrr(snap),
        "arr_usd": arr(snap),
        "granted_list_value_usd": granted_list_value(snap),
        "conversion_pct": conversion(snap),
        "trial_customers": trial_customers(),
        "churn_pct": churn(days),
    }

    flat = []
    for name, m in metrics.items():
        if isinstance(m, dict) and "measured" in m:
            flat.append((name, m["measured"]))
        elif isinstance(m, dict):
            flat.extend((f"{name}.{k}", v.get("measured", False))
                        for k, v in m.items() if isinstance(v, dict))

    return {
        "metrics": metrics,
        "window_days": int(days),
        "durable": durable,
        # Headline: how much of this dashboard is measured.
        "measured_count": sum(1 for _, ok in flat if ok),
        "unmeasured_count": sum(1 for _, ok in flat if not ok),
        "generated_at": time.time(),
    }
