"""Executive metrics, every one of which says whether it was measured.

The brief asks for MRR, ARR, churn, conversion, trial counts and plan
distribution, and then says — twice — that a metric which cannot be measured
must read "Not measured" rather than being invented. Those two requirements
are in tension only if you try to return a number for everything, so this
module returns a *shape* instead of a number:

    {"value": 41.0, "measured": true,  "source": "...",  "note": "..."}
    {"value": null, "measured": false, "reason": "Billing is not connected."}

**`value` is `None` whenever `measured` is false. There is no third state and
no zero.** That distinction is the whole point: with no payment processor
connected, MRR of `0.0` is a claim that nobody paid, and the truth is that
nobody *could* pay and nothing was measured. A dashboard that cannot tell those
apart will be believed anyway.

What is genuinely measurable today, and what is not
---------------------------------------------------
* **Measurable** — customer counts, plan distribution and signup-to-paying
  conversion. These come from durable account state, so they are correct for
  every account ever created.
* **Not measurable: MRR and ARR**, because no payment processor is configured.
  The moment one is, they become measurable — and `0.0` will then be a real
  measurement.
* **Not measurable: trial customers.** `billing` has a per-*plan* trial length
  and no per-*account* trial state at all — no `trial_ends_at` on the record.
  So "who is currently in a trial" is not a question the data can answer, and
  the reason names the exact missing field rather than shrugging.
* **Churn** depends on `subscription_events`, which only began recording when
  it shipped. Before that, plan changes overwrote the plan in place and were
  gone. So churn reads "not measured" until there is history AND at least one
  paid subscription to churn *from* — a churn rate computed over zero paid
  accounts is a division by nothing dressed up as a percentage.

Nothing here counts a demo record or a granted seat as a customer.
`analytics.accounts_snapshot()` already excludes both, and this reads from it
rather than growing a second, subtly different opinion about who counts.
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
    created — not only those seen since the activity log started."""
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

    Unmeasured while no processor is connected — not zero. Nobody could have
    paid, so nothing was measured, and `$0 revenue` would read as a business
    result rather than a missing integration.
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
    """Twelve times MRR, and unmeasured for exactly as long as MRR is.

    Deriving a number from an unmeasured one and presenting it as measured is
    how a null becomes a zero two function calls away from where it started.
    """
    base = mrr(snap)
    if not base["measured"]:
        return not_measured(base["reason"], base.get("source", "billing"))
    return measured(round(base["value"] * 12, 2), base["source"],
                    "MRR x 12. Not a forecast.")


def granted_list_value(snap: Optional[dict] = None) -> dict:
    """What the granted seats WOULD be worth. Deliberately separate from MRR
    so a pile of pilot accounts can never be mistaken for revenue."""
    snap = snap or _snapshot()
    return measured(round(float(snap["granted_list_value_usd"]), 2),
                    "billing accounts",
                    "List value of seats handed out. Never charged, never "
                    "counted as revenue.")


# ----------------------------------------------------------- conversion --
def conversion(snap: Optional[dict] = None) -> dict:
    """Signed up -> paying, over every account ever created.

    Cumulative, not a cohort rate, and it says so: an account that signed up
    yesterday has not had the chance to convert, so this understates a growing
    business and overstates a shrinking one.
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
    """Not measurable, and the reason names the missing field.

    `billing.trial_days()` is a property of a PLAN. There is no per-account
    trial state — no `trial_ends_at` on the record — so "who is in a trial
    right now" is not a question this data can answer. Guessing it from the
    signup date and the plan's trial length would produce a number that looks
    right and is not.
    """
    return not_measured(
        "Trials are configured per plan but not tracked per account: a "
        "billing record has no trial_ends_at. Nothing currently distinguishes "
        "an account inside a trial from one that never started it.",
        "billing")


# ---------------------------------------------------------------- churn --
def churn(days: int = 30) -> dict:
    """Paid subscriptions that fell back to free, or were cancelled, in the
    window — as a share of the paid subscriptions that existed to lose.

    Two ways this is legitimately unmeasurable, and both are reported rather
    than smoothed over:

    1. `subscription_events` only began recording when it shipped. Plan changes
       before that overwrote the plan in place and are gone.
    2. A churn rate over zero paid subscriptions is a division by nothing.
       Zero percent churn on zero customers is not good news.
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

    # Anyone who held a paid plan at any point in the window is at risk of
    # churning out of it. Granted seats are excluded: losing a seat nobody paid
    # for is not revenue churn.
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

    `durable` is not decoration. On the current free tier the account store is
    wiped by a rebuild, so a customer count is true until the next deploy and
    then silently becomes true about a different, emptier world.
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
        # A single honest headline: how much of this dashboard is real.
        "measured_count": sum(1 for _, ok in flat if ok),
        "unmeasured_count": sum(1 for _, ok in flat if not ok),
        "generated_at": time.time(),
    }
