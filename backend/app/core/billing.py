"""Subscription plans, usage limits and signup.

Spec Part 5B: a genuinely useful free tier, clear upgrade paths, plans with
"feature comparison, usage limits, storage limits, AI usage quotas", and
explicitly: "Avoid dark patterns or deceptive UX."

The model is the one Abdullah described — free usage first, conversion second.
Two rules follow from Part 5B and are enforced in code rather than trusted to
copywriting:

1. **The free tier must be genuinely useful.** Free includes a real audit with
   the legal findings, because the legal check is the thing that proves Titan
   is worth paying for. Crippling it to force upgrades would be the dark
   pattern the spec forbids and would sell nothing.

2. **A limit that is reached is never a silent failure.** Exceeding a quota
   returns which limit, what it is, when it resets and what the next tier gives
   — never a bare error, and never a quiet truncation of results.

Processor: PayPal, on Abdullah's instruction. Deliberately behind the same
`Processor` seam as everything else in this codebase, so switching to Dodo or
Stripe later is one adapter, not a rewrite — the tier logic, the quotas and the
signup flow do not know or care who takes the money.

Nothing here charges anyone. Creating a subscription returns an approval URL
that the CUSTOMER must open and confirm themselves; Titan never handles a card
number and never completes a payment on a user's behalf.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import events

# ------------------------------------------------------------------ plans --
# Prices in USD. Chosen against what comparable SEO/agency tools charge, and
# deliberately low: a Pakistan-based solo founder competing on price with
# incumbents is a real advantage, and an empty paid tier earns nothing.


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_usd: float
    clients: int              # businesses manageable at once
    audits_per_month: int
    ai_calls_per_month: int
    keeps_history_days: int
    features: tuple
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "price_usd": self.price_usd,
            "limits": {
                "clients": self.clients,
                "audits_per_month": self.audits_per_month,
                "ai_calls_per_month": self.ai_calls_per_month,
                "history_days": self.keeps_history_days,
            },
            "features": list(self.features),
            "note": self.note,
        }


PLANS: dict[str, Plan] = {
    "free": Plan(
        "free", "Free", 0.0,
        clients=1, audits_per_month=5, ai_calls_per_month=50,
        keeps_history_days=30,
        features=(
            "Full SEO audit — technical, local and legal",
            "Legal compliance check for all 9 jurisdictions",
            "Ready-to-paste schema markup",
            "1 business",
        ),
        note="Includes the legal findings in full. That check is the thing "
             "worth paying for — hiding it would sell nothing."),
    "student": Plan(
        "student", "Student", 4.0,
        clients=3, audits_per_month=30, ai_calls_per_month=500,
        keeps_history_days=180,
        features=(
            "Everything in Free",
            "3 businesses",
            "PDF reports you can hand to a client",
            "Content drafts in the market language",
        ),
        note="Requires a valid student email or proof of enrolment."),
    "individual": Plan(
        "individual", "Individual", 19.0,
        clients=10, audits_per_month=200, ai_calls_per_month=3000,
        keeps_history_days=365,
        features=(
            "Everything in Student",
            "10 businesses",
            "24/7 monitoring with regression alerts",
            "Lead funnel and CRM",
            "Priority model routing",
        )),
    "enterprise": Plan(
        "enterprise", "Enterprise", 99.0,
        clients=-1, audits_per_month=-1, ai_calls_per_month=-1,
        keeps_history_days=-1,
        features=(
            "Everything in Individual",
            "Unlimited businesses",
            "Unlimited audits and AI usage",
            "Full history retention",
            "Custom branding on reports",
            "API access",
        ),
        note="-1 means no enforced limit."),
}

ORDER = ("free", "student", "individual", "enterprise")


def plans() -> dict:
    return {
        "plans": [PLANS[k].as_dict() for k in ORDER],
        "currency": "USD",
        "processor": processor_name(),
        "note": ("Free is usable on its own, not a demo. Limits are enforced "
                 "server-side and every rejection names the limit, the reset "
                 "time and what the next tier allows."),
    }


# --------------------------------------------------------------- accounts --
_lock = threading.RLock()
_accounts: dict[str, dict] = {}      # email -> record
_sessions: dict[str, str] = {}       # token -> email


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                               200_000).hex()


def _period_start() -> float:
    """Quotas reset on a rolling 30-day window from signup, not on the 1st of
    the month — otherwise someone signing up on the 30th gets one day of usage
    for a full month's price."""
    return time.time()


def signup(email: str, password: str, plan: str = "free") -> dict:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("A valid email address is required.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")

    with _lock:
        if email in _accounts:
            raise ValueError("An account with that email already exists.")
        salt = secrets.token_hex(16)
        _accounts[email] = {
            "email": email,
            "_salt": salt,
            "_pwhash": _hash(password, salt),
            "plan": plan,
            "created_at": time.time(),
            "period_start": _period_start(),
            "usage": {"audits": 0, "ai_calls": 0},
            "subscription_id": "",
            "status": "active" if plan == "free" else "pending_payment",
        }
    events.emit("SubscriptionChanged", {"email": email, "plan": plan,
                                        "status": _accounts[email]["status"]},
                actor="billing")
    return public(email)


def authenticate(email: str, password: str) -> Optional[str]:
    email = (email or "").strip().lower()
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            return None
        if not hmac.compare_digest(_hash(password, acct["_salt"]),
                                   acct["_pwhash"]):
            return None
        token = secrets.token_urlsafe(32)
        _sessions[token] = email
        return token


def resolve(token: str) -> Optional[str]:
    return _sessions.get(token or "")


def public(email: str) -> dict:
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            return {}
        plan = PLANS[acct["plan"]]
        used = acct["usage"]
        return {
            "email": acct["email"],
            "plan": acct["plan"],
            "plan_name": plan.name,
            "status": acct["status"],
            "usage": dict(used),
            "limits": plan.as_dict()["limits"],
            "period_resets_in_days": max(
                0, round(30 - (time.time() - acct["period_start"]) / 86400, 1)),
        }


def _roll_period(acct: dict) -> None:
    if time.time() - acct["period_start"] >= 30 * 86400:
        acct["period_start"] = time.time()
        acct["usage"] = {"audits": 0, "ai_calls": 0}


def check_quota(email: str, kind: str, cost: int = 1) -> dict:
    """Is this action allowed? Returns a verdict, never raises, never silently
    truncates. A refusal always says what to do about it."""
    field_map = {"audits": "audits_per_month", "ai_calls": "ai_calls_per_month"}
    if kind not in field_map:
        return {"allowed": True, "reason": ""}

    with _lock:
        acct = _accounts.get(email)
        if not acct:
            return {"allowed": False, "reason": "No such account.",
                    "upgrade_to": None}
        _roll_period(acct)
        plan = PLANS[acct["plan"]]
        limit = getattr(plan, field_map[kind])
        used = acct["usage"].get(kind, 0)
        if limit == -1 or used + cost <= limit:
            return {"allowed": True, "reason": "", "used": used, "limit": limit}

        nxt = None
        for k in ORDER[ORDER.index(acct["plan"]) + 1:]:
            if getattr(PLANS[k], field_map[kind]) in (-1,) or \
               getattr(PLANS[k], field_map[kind]) > limit:
                nxt = PLANS[k]
                break
        resets = max(0, round(30 - (time.time() - acct["period_start"]) / 86400, 1))
        return {
            "allowed": False,
            "reason": (f"{kind.replace('_', ' ')} limit reached: {used}/{limit} "
                       f"on the {plan.name} plan."),
            "resets_in_days": resets,
            "upgrade_to": nxt.key if nxt else None,
            "upgrade_gives": (
                f"{nxt.name} allows "
                f"{'unlimited' if getattr(nxt, field_map[kind]) == -1 else getattr(nxt, field_map[kind])} "
                f"per month for ${nxt.price_usd:.0f}." if nxt else
                "You are already on the highest plan — contact support."),
        }


def consume(email: str, kind: str, cost: int = 1) -> dict:
    verdict = check_quota(email, kind, cost)
    if verdict["allowed"]:
        with _lock:
            acct = _accounts.get(email)
            if acct:
                acct["usage"][kind] = acct["usage"].get(kind, 0) + cost
    return verdict


def set_plan(email: str, plan: str, subscription_id: str = "",
             status: str = "active") -> dict:
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            raise ValueError("No such account.")
        acct.update(plan=plan, subscription_id=subscription_id, status=status)
    events.emit("SubscriptionChanged",
                {"email": email, "plan": plan, "status": status},
                actor="billing")
    return public(email)


# -------------------------------------------------------------- processor --
def processor_name() -> str:
    return "paypal" if os.getenv("PAYPAL_CLIENT_ID", "").strip() else "none"


def configured() -> bool:
    return bool(os.getenv("PAYPAL_CLIENT_ID", "").strip()
                and os.getenv("PAYPAL_CLIENT_SECRET", "").strip())


def checkout(email: str, plan_key: str) -> dict:
    """Return where the CUSTOMER goes to approve a subscription.

    Titan never takes a card number and never completes a payment on anyone's
    behalf — it hands back an approval URL the customer opens themselves. That
    is both the correct integration and the only safe one.
    """
    if plan_key not in PLANS or plan_key == "free":
        raise ValueError("Choose a paid plan.")
    plan = PLANS[plan_key]
    if not configured():
        return {
            "ready": False,
            "plan": plan_key,
            "price_usd": plan.price_usd,
            "needs": ("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET as Space "
                      "secrets, and create a subscription Plan ID in the "
                      "PayPal dashboard for each paid tier "
                      "(PAYPAL_PLAN_ID_STUDENT, _INDIVIDUAL, _ENTERPRISE)."),
            "note": ("Until then signup works and the free tier is fully "
                     "usable — only paid upgrades are unavailable."),
        }
    plan_id = os.getenv(f"PAYPAL_PLAN_ID_{plan_key.upper()}", "").strip()
    if not plan_id:
        return {"ready": False, "plan": plan_key,
                "needs": f"Set PAYPAL_PLAN_ID_{plan_key.upper()}."}
    base = ("https://api-m.paypal.com" if os.getenv("PAYPAL_LIVE", "").strip()
            else "https://api-m.sandbox.paypal.com")
    return {
        "ready": True,
        "plan": plan_key,
        "price_usd": plan.price_usd,
        "paypal_plan_id": plan_id,
        "api_base": base,
        "flow": ("The dashboard renders PayPal's own subscription button with "
                 "this plan id. The customer approves inside PayPal; Titan is "
                 "told the result by webhook and never sees card details."),
    }


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"accounts": {k: dict(v) for k, v in _accounts.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("accounts")
    if not isinstance(rows, dict):
        return
    with _lock:
        _accounts.clear()
        for email, acct in rows.items():
            if isinstance(acct, dict) and "_pwhash" in acct:
                acct.setdefault("usage", {"audits": 0, "ai_calls": 0})
                acct.setdefault("period_start", time.time())
                acct.setdefault("status", "active")
                acct.setdefault("plan", "free")
                if acct["plan"] not in PLANS:
                    acct["plan"] = "free"
                _accounts[email] = acct


def reset() -> None:
    """Test seam."""
    with _lock:
        _accounts.clear()
        _sessions.clear()
