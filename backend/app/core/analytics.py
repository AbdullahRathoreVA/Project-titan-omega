"""Founder-only product analytics: who signed up, what they bought, what they did.

This answers three questions Abdullah cannot currently answer about his own
product: **who signed up**, **which plan they are on**, and **how they are
actually using it**. Revenue is $0 and there are no paying customers, so the
instrument that shows where people stop is worth more than another feature.

Three rules this module is built around, all of them learned the hard way in
this codebase:

1. **Derive from state before trusting the log.** The activity log starts empty
   the day this ships, but accounts already exist. Every funnel step that can be
   reconstructed from the billing record (signed up, added a business, ran an
   audit, is paying) IS reconstructed from it, so the first screen is not
   misleadingly empty. Only steps with no durable trace — opening checkout,
   downloading a PDF, signing back in — come from the log alone, and those are
   labelled as log-only so a zero is never read as "nobody did this".

2. **Never invent a number.** No payment processor is configured, so no account
   can complete a purchase. MRR is therefore reported as uncollectable with the
   reason, not as ``0.0`` sitting next to a currency symbol — a zero implies
   measurement, and this is not measured.

3. **This is personal data.** Every row here is a real person's email address.
   The route that serves it is registered in ``demo_data._SENSITIVE_PREFIXES``
   and covered by ``test_every_founder_endpoint_is_hidden_from_guests``, which
   walks the real route table. Deleting that registration leaks subscriber
   emails to anyone clicking "View the live demo".
"""

from __future__ import annotations

import threading
import time
from typing import Optional

# Bounded: this runs in a free-tier container alongside everything else. At
# ~200 bytes a row this is well under a megabyte, and the derived funnel does
# not depend on the log being complete.
MAX_EVENTS = 2000

DAY = 86400.0

# Actions worth recording. Unknown actions are still accepted — refusing them
# would make this module a bottleneck on every new endpoint — but they are
# listed separately in the report so an undocumented action is visible rather
# than silently folded into the totals.
SIGNED_UP = "signed_up"
SIGNED_IN = "signed_in"
ADDED_BUSINESS = "added_business"
RAN_AUDIT = "ran_audit"
DOWNLOADED_REPORT = "downloaded_report"
OPENED_CHECKOUT = "opened_checkout"
CHANGED_PLAN = "changed_plan"

KNOWN_ACTIONS = frozenset({
    SIGNED_UP, SIGNED_IN, ADDED_BUSINESS, RAN_AUDIT,
    DOWNLOADED_REPORT, OPENED_CHECKOUT, CHANGED_PLAN,
})

_lock = threading.RLock()
_events: list[dict] = []


def record(email: str, action: str, **meta) -> None:
    """File one thing a subscriber did. Never raises — analytics must never be
    able to break the action it is measuring."""
    try:
        email = (email or "").strip().lower()
        if not email or not action:
            return
        with _lock:
            _events.append({
                "ts": time.time(),
                "email": email,
                "action": action,
                "meta": {k: v for k, v in meta.items() if v not in (None, "")},
            })
            if len(_events) > MAX_EVENTS:
                del _events[:len(_events) - MAX_EVENTS]
    except Exception:
        pass


def _by_email() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with _lock:
        rows = list(_events)
    for e in rows:
        rec = out.setdefault(e["email"], {"actions": {}, "first": e["ts"],
                                          "last": e["ts"], "total": 0})
        rec["actions"][e["action"]] = rec["actions"].get(e["action"], 0) + 1
        rec["total"] += 1
        rec["first"] = min(rec["first"], e["ts"])
        rec["last"] = max(rec["last"], e["ts"])
    return out


def _storage_warning() -> Optional[str]:
    """A number the founder acts on must say whether it survives a restart."""
    try:
        from .. import persistence
        path = persistence.STATE_FILE
    except Exception:
        return "State file location could not be determined."
    if path.startswith("/data"):
        return None
    return (f"History is stored at {path}, which is not a persistent mount. "
            f"Signups survive restarts and sleep-wake, but a fresh Space "
            f"rebuild wipes them. Mount HF persistent storage at /data (paid) "
            f"or point TITAN_STATE_FILE at a real volume to keep this history.")


def _is_granted(acct: dict) -> bool:
    """Was this seat handed out by the founder, or bought?

    ``POST /api/founder/accounts`` records a grant by writing ``granted`` (or
    ``granted:<note>``) into ``subscription_id``, and its own response warns
    that a pile of grants would make MRR look real. **Nothing ever read that
    flag back.** A granted Enterprise seat was active on a paid plan, so it
    counted as a paying customer in the funnel and added its list price to
    committed MRR. Provisioning a single pilot customer would have made this
    dashboard report revenue that nobody was ever charged.
    """
    return str(acct.get("subscription_id", "")).startswith("granted")


def accounts_snapshot() -> dict:
    """Every account as one row, plus the counts derived from those rows.

    Extracted from ``report()`` so the customers screen and the funnel cannot
    disagree about what plan somebody is on: there is exactly one place in the
    codebase that shapes an account row.
    """
    from . import billing, clients as client_registry
    from ..engines import demo_workspace as _demo

    now = time.time()
    logged = _by_email()

    accounts: list[dict] = []
    by_plan: dict[str, int] = {}
    by_status: dict[str, int] = {}
    paying = 0
    granted_paid_plans = 0
    committed_usd = 0.0
    granted_usd = 0.0

    with billing._lock:                       # noqa: SLF001 — same package
        raw = {k: dict(v) for k, v in billing._accounts.items()}   # noqa: SLF001

    for email, acct in raw.items():
        plan_key = acct.get("plan", "free")
        plan = billing.PLANS.get(plan_key)
        status = acct.get("status", "active")
        created = float(acct.get("created_at", now))
        usage = dict(acct.get("usage", {}))
        cids = list(acct.get("client_ids", []))
        log = logged.get(email, {})

        # Businesses actually still present in the registry. A stale id in the
        # account is not a business the person can use, and a seeded demo site
        # is not a business at all — counting either would make the funnel
        # describe something other than real usage.
        live_clients = []
        for cid in cids:
            row = client_registry.public(cid)
            if row and not _demo.is_demo_client(row):
                live_clients.append({
                    "id": cid,
                    "business_name": row.get("business_name", ""),
                    "website": row.get("website", ""),
                    "industry": row.get("industry", ""),
                    "country": row.get("country", ""),
                })

        by_plan[plan_key] = by_plan.get(plan_key, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        is_granted = _is_granted(acct)
        on_paid_plan = plan_key != "free" and status == "active"
        # A granted seat is active on a paid plan and has paid nothing. Folding
        # it into `paying` is precisely the invented number this codebase exists
        # to avoid, so it is counted on its own and kept out of revenue.
        is_paying = on_paid_plan and not is_granted
        if is_paying:
            paying += 1
            committed_usd += plan.price_usd if plan else 0.0
        elif on_paid_plan:
            granted_paid_plans += 1
            granted_usd += plan.price_usd if plan else 0.0

        last_seen = log.get("last")
        accounts.append({
            "email": email,
            "plan": plan_key,
            "plan_name": plan.name if plan else plan_key,
            "price_usd": plan.price_usd if plan else 0.0,
            "status": status,
            "paying": is_paying,
            # Its own column on the customers screen: the founder has to be
            # able to tell a pilot seat from a customer at a glance.
            "granted": is_granted,
            "grant_note": (str(acct.get("subscription_id", "")).partition(":")[2]
                           if is_granted else ""),
            "signed_up_at": created,
            "days_since_signup": round((now - created) / DAY, 1),
            "usage": usage,
            "limits": plan.as_dict()["limits"] if plan else {},
            "businesses": live_clients,
            "business_count": len(live_clients),
            "actions": log.get("actions", {}),
            "action_total": log.get("total", 0),
            "last_seen_at": last_seen,
            "days_since_seen": (round((now - last_seen) / DAY, 1)
                                if last_seen else None),
            # An account that signed up and never came back is the single most
            # actionable row on this screen.
            "returned_after_signup": bool(log.get("actions", {}).get(SIGNED_IN)),
        })

    accounts.sort(key=lambda a: a["signed_up_at"], reverse=True)
    return {
        "accounts": accounts,
        "by_plan": dict(sorted(by_plan.items(), key=lambda kv: -kv[1])),
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "paying": paying,
        "granted_paid_plans": granted_paid_plans,
        "committed_usd": round(committed_usd, 2),
        "granted_list_value_usd": round(granted_usd, 2),
    }


def storage_warning() -> Optional[str]:
    """Public reader. The customers screen has to be able to say out loud
    whether the accounts it is listing survive a rebuild."""
    return _storage_warning()


def report(days: int = 30, recent: int = 40) -> dict:
    """Everything the founder needs to see about real usage, in one payload."""
    from . import billing

    now = time.time()
    window = max(1, days) * DAY

    snap = accounts_snapshot()
    accounts = snap["accounts"]
    by_plan = snap["by_plan"]
    by_status = snap["by_status"]
    paying = snap["paying"]
    committed_usd = snap["committed_usd"]
    total = len(accounts)

    # ---------------------------------------------------------------- funnel --
    # `derived` steps are reconstructed from durable account state and are
    # correct for every account ever created. `log_only` steps depend on the
    # activity log, which began the day this shipped — a zero there means "not
    # observed since analytics started", NOT "never happened".
    def _count(pred) -> int:
        return sum(1 for a in accounts if pred(a))

    def _logged(action: str) -> int:
        return sum(1 for a in accounts if a["actions"].get(action))

    steps = [
        ("Signed up", total, True),
        ("Came back at least once", _logged(SIGNED_IN), False),
        ("Added a business", _count(lambda a: a["business_count"] > 0), True),
        ("Ran an audit", _count(lambda a: a["usage"].get("audits", 0) > 0), True),
        ("Downloaded a PDF report", _logged(DOWNLOADED_REPORT), False),
        ("Opened checkout", _logged(OPENED_CHECKOUT), False),
        ("Is paying", paying, True),
    ]
    funnel = []
    prev = None
    for name, count, derived in steps:
        funnel.append({
            "step": name,
            "count": count,
            "pct_of_signups": round(100.0 * count / total, 1) if total else 0.0,
            "dropped_from_previous": (max(0, prev - count)
                                      if prev is not None else None),
            "source": "account state" if derived else "activity log",
            "reliable": derived,
        })
        prev = count

    # ------------------------------------------------------------ engagement --
    active = _count(lambda a: a["last_seen_at"] and
                    now - a["last_seen_at"] <= 7 * DAY)
    in_window = _count(lambda a: now - a["signed_up_at"] <= window)
    dormant = _count(lambda a: not a["last_seen_at"] or
                     now - a["last_seen_at"] > 30 * DAY)

    with _lock:
        tail = list(_events)[-recent:][::-1]
        action_totals: dict[str, int] = {}
        undocumented: set[str] = set()
        for e in _events:
            action_totals[e["action"]] = action_totals.get(e["action"], 0) + 1
            if e["action"] not in KNOWN_ACTIONS:
                undocumented.add(e["action"])
        log_started = _events[0]["ts"] if _events else None
        log_size = len(_events)

    # ---------------------------------------------------------------- money --
    processor_ready = billing.configured()
    revenue = {
        "collectable": processor_ready,
        "paying_accounts": paying,
        "committed_mrr_usd": round(committed_usd, 2) if processor_ready else None,
        # Seats handed out by the founder, kept BESIDE mrr rather than inside
        # it. The list value of a free seat is what that plan would have cost,
        # not money anybody was charged.
        "granted_paid_seats": snap["granted_paid_plans"],
        "granted_list_value_usd": snap["granted_list_value_usd"],
        "granted_note": (
            "Granted seats are excluded from paying accounts and from MRR. "
            "Their list value is what those plans would cost, not revenue."),
        "note": (
            "Sum of list prices for accounts marked active on a paid plan. "
            "This is what they agreed to pay, not what has cleared."
            if processor_ready else
            "No payment processor is configured (PAYPAL_CLIENT_ID / "
            "PAYPAL_CLIENT_SECRET are unset), so no account can complete a "
            "purchase and every signup stays on Free. MRR is not reported as "
            "0 because it is not measured — it is uncollectable."),
    }

    return {
        "generated_at": now,
        "window_days": days,
        "totals": {
            "accounts": total,
            "signed_up_in_window": in_window,
            "paying": paying,
            "granted_paid_plans": snap["granted_paid_plans"],
            "active_7d": active,
            "dormant_30d": dormant,
            "by_plan": dict(sorted(by_plan.items(), key=lambda kv: -kv[1])),
            "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        },
        "revenue": revenue,
        "funnel": funnel,
        "accounts": accounts,
        "activity": {
            "recent": tail,
            "totals": dict(sorted(action_totals.items(), key=lambda kv: -kv[1])),
            "undocumented_actions": sorted(undocumented),
            "log_started_at": log_started,
            "log_capacity": MAX_EVENTS,
            "log_size": log_size,
        },
        "storage_warning": _storage_warning(),
        "note": (
            "Funnel steps sourced from 'account state' are correct for every "
            "account ever created. Steps sourced from 'activity log' only "
            "count what happened after analytics shipped, so a zero there "
            "means not-observed, not never-happened."),
    }


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"events": list(_events)}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("events")
    if not isinstance(rows, list):
        return
    with _lock:
        _events.clear()
        for e in rows[-MAX_EVENTS:]:
            if isinstance(e, dict) and e.get("email") and e.get("action"):
                e.setdefault("ts", time.time())
                e.setdefault("meta", {})
                _events.append(e)


def reset() -> None:
    """Test seam."""
    with _lock:
        _events.clear()
