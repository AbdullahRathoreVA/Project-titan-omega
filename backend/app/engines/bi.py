"""Business intelligence and forecasting.

Spec Part 4C: reports with "Charts, Key Insights, Supporting Data,
Recommendations, Action Items, Historical Comparisons", forecasting "where
sufficient historical data exists", forecasts that "include uncertainty ranges
and assumptions" — and, twice over, "Never fabricate numbers. Never invent
analytics. Never fake benchmarks."

Those two requirements are in tension, and this module resolves it in the only
defensible direction: **it refuses to forecast rather than invent one.**

That refusal is the feature, not a limitation. Titan currently has one client
and no revenue. A forecasting engine that answers "€4,200 next month" from two
data points is not a forecast, it is a number with a chart behind it, and a
founder who plans against it makes real decisions on fiction. Every projection
here states its method, its sample size, its uncertainty band, and the specific
thing that would make it trustworthy.

The forecast is ordinary least-squares on daily totals with a prediction
interval — deliberately simple. Anything fancier would imply a precision the
data does not have, and would be harder to explain to a client reading the
report.
"""

from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..store import STORE

# Below this many distinct days with data, no projection is produced at all.
MIN_POINTS_FOR_TREND = 5
# Below this, a trend is reported but explicitly labelled provisional.
CONFIDENT_POINTS = 14

PERIODS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}


def _ts(row: dict) -> Optional[float]:
    """Epoch seconds for a ledger row, whatever shape its timestamp is in."""
    raw = row.get("created_at") or row.get("ts") or row.get("updated_at")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    if isinstance(raw, datetime):
        return raw.timestamp()
    return None


def _within(rows: list, days: int) -> list:
    cutoff = time.time() - days * 86400
    out = []
    for r in rows:
        t = _ts(r)
        if t is None or t >= cutoff:
            out.append(r)
    return out


def _daily_totals(rows: list, days: int) -> dict:
    """{date -> summed amount} over the window. Days with nothing are absent,
    not zero: a day with no entry is missing data, not a measured zero, and
    treating it as zero would fabricate a downward trend."""
    out: dict[str, float] = {}
    cutoff = time.time() - days * 86400
    for r in rows:
        t = _ts(r)
        if t is None or t < cutoff:
            continue
        day = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        out[day] = out.get(day, 0.0) + float(r.get("amount", 0) or 0)
    return dict(sorted(out.items()))


def forecast(series: dict, horizon_days: int = 30) -> dict:
    """Least-squares projection with a prediction interval, or an honest refusal.

    Returns `available: False` and the reason whenever the data cannot support
    a projection. Callers must render the reason, not a zero.
    """
    points = sorted(series.items())
    n = len(points)
    if n < MIN_POINTS_FOR_TREND:
        return {
            "available": False,
            "reason": (
                f"Only {n} day(s) of data. A projection needs at least "
                f"{MIN_POINTS_FOR_TREND} to distinguish a trend from noise."),
            "needed": MIN_POINTS_FOR_TREND - n,
            "method": None,
        }

    xs = list(range(n))
    ys = [v for _, v in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return {"available": False, "reason": "All observations fall on one day.",
                "method": None}

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    intercept = mean_y - slope * mean_x

    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    # Standard error of the residuals; needs n>2 for a meaningful estimate.
    se = (math.sqrt(sum(r * r for r in residuals) / (n - 2)) if n > 2 else 0.0)

    projected_daily = intercept + slope * (n + horizon_days / 2.0)
    projected_total = max(0.0, projected_daily * horizon_days)
    # ~95% band. Widened by sqrt(horizon) because uncertainty compounds the
    # further out the projection runs.
    band = 1.96 * se * math.sqrt(horizon_days)

    return {
        "available": True,
        "method": "ordinary least squares on daily totals",
        "days_of_data": n,
        "horizon_days": horizon_days,
        "projected_total": round(projected_total, 2),
        "low": round(max(0.0, projected_total - band), 2),
        "high": round(projected_total + band, 2),
        "direction": "rising" if slope > 0 else "falling" if slope < 0 else "flat",
        "provisional": n < CONFIDENT_POINTS,
        "assumptions": [
            "The next period behaves like the observed one — no new client, no "
            "campaign, no seasonality.",
            f"Days with no entries are excluded rather than counted as zero, so "
            f"the trend is not dragged down by gaps.",
            ("Fewer than "
             f"{CONFIDENT_POINTS} days of data: treat this as a direction of "
             "travel, not a number to plan against.")
            if n < CONFIDENT_POINTS else
            "Sample is large enough for the interval to be meaningful.",
        ],
    }


def _insights(rev_rows: list, exp_rows: list, days: int) -> tuple:
    """(insights, actions) — each tied to a number that is actually present.

    Served to a subscriber's Executive tab too (/api/me/bi), so the client
    list and the lead funnel are the caller's own. Both used to read the whole
    platform: every business on file named in "Never audited", and every
    account's leads counted in the founder's funnel.
    """
    from ..core import cockpit_scope
    subscriber = cockpit_scope.customer_email()
    insights: list[str] = []
    actions: list[str] = []

    revenue = sum(float(r.get("amount", 0) or 0) for r in rev_rows)
    expenses = sum(float(e.get("amount", 0) or 0) for e in exp_rows)

    if revenue == 0:
        insights.append(
            f"No revenue recorded in the last {days} days. Every other number "
            f"in this report is activity, not income.")
        actions.append(
            "Log each sale in Finance as it happens — this report only counts "
            "what is recorded."
            if subscriber else
            "The bottleneck is checkout, not capability: nothing here converts "
            "until a payment link exists.")
    else:
        insights.append(f"Revenue over {days} days: {revenue:,.2f}.")
        if expenses > revenue:
            insights.append(
                f"Spending ({expenses:,.2f}) exceeds income ({revenue:,.2f}) "
                f"over the same window.")
            actions.append("Cut or defer the largest recurring cost.")

    # Clients and their audit coverage — real counts, no estimation.
    try:
        from ..core import clients as client_registry
        rows = client_registry.all_clients()
        if subscriber:
            from ..core import billing
            own = set(billing.owned_clients(subscriber))
            rows = [c for c in rows if c["id"] in own]
        if rows:
            unaudited = [c["business_name"] for c in rows
                         if not (c.get("metrics") or {}).get("seo_audits")]
            insights.append(f"{len(rows)} business(es) on Titan." if subscriber
                            else f"{len(rows)} client(s) on file.")
            if unaudited:
                actions.append(
                    "Never audited: " + ", ".join(unaudited[:5]) +
                    (". Run the first audit from the SEO tab." if subscriber
                     else ". An unaudited client has been sold nothing yet."))
        elif subscriber:
            insights.append("No business added yet.")
            actions.append(
                "Add your business in the Clients tab — its first audit takes "
                "about 90 seconds.")
        else:
            insights.append("No clients onboarded.")
            actions.append(
                "Onboarding is roughly 90 seconds and produces the PDF that "
                "justifies the fee — it is the shortest path to revenue.")
    except Exception:
        pass

    # Lead funnel — reuse the real funnel, never recompute it differently here.
    try:
        from ..api.finance import _funnel, _leads, _owner
        from ..core import crm
        f = _funnel(crm.visible_to(_leads(), _owner()))
        if f["funnel"][0]["reached"]:
            insights.append(
                f"Lead funnel: {f['funnel'][0]['reached']} in, "
                f"{f['funnel'][-1]['reached']} won "
                f"({f['conversion_pct']}% end to end).")
            worst = max(f["funnel"][1:], key=lambda r: r["dropped"], default=None)
            if worst and worst["dropped"] > 0:
                actions.append(
                    f"Biggest leak is at '{worst['stage']}' "
                    f"({worst['dropped']} lost there).")
    except Exception:
        pass

    return insights, actions


def report(period: str = "monthly") -> dict:
    """A period report built only from what has actually been recorded."""
    days = PERIODS.get(period, 30)
    rev_rows = _within(STORE.revenue_entries, days)
    exp_rows = _within(STORE.expenses, days)

    revenue = sum(float(r.get("amount", 0) or 0) for r in rev_rows)
    expenses = sum(float(e.get("amount", 0) or 0) for e in exp_rows)

    # Historical comparison against the immediately preceding window.
    prev_rev_rows = [r for r in STORE.revenue_entries
                     if (t := _ts(r)) is not None
                     and time.time() - 2 * days * 86400 <= t < time.time() - days * 86400]
    prev_revenue = sum(float(r.get("amount", 0) or 0) for r in prev_rev_rows)
    if prev_revenue:
        change_pct = round(100.0 * (revenue - prev_revenue) / prev_revenue, 1)
        comparison = f"{change_pct:+.1f}% versus the previous {days} days."
    elif revenue:
        comparison = "No revenue in the previous period to compare against."
    else:
        comparison = "No revenue in either period."

    series = _daily_totals(STORE.revenue_entries, max(days, 90))
    insights, actions = _insights(rev_rows, exp_rows, days)

    return {
        "period": period,
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revenue": round(revenue, 2),
        "expenses": round(expenses, 2),
        "profit": round(revenue - expenses, 2),
        "comparison": comparison,
        "chart": {"daily_revenue": series},
        "insights": insights,
        "actions": actions,
        "forecast": forecast(series, horizon_days=days),
        "note": ("Every figure is read from the ledger. Where there is not "
                 "enough data to project, this report says so instead of "
                 "showing a number."),
    }
