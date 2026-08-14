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


# Trial lengths, per plan, overridable without a deploy:
#   TITAN_TRIAL_DAYS_STUDENT / _INDIVIDUAL / _ENTERPRISE
#
# Abdullah set these: 10 days on Enterprise, 7 on Individual, and a full YEAR
# on Student. The year is deliberate and matches what the market does — Cursor
# gives verified students a free year, and a student evaluating a business SEO
# tool has no client website to audit in five days, so a short student trial
# tests nothing and converts nobody.
#
# They are env-driven because a trial length is a pricing experiment, and a
# pricing experiment that needs a redeploy never gets run.
_DEFAULT_TRIAL_DAYS = {"free": 0, "student": 365, "individual": 7,
                       "enterprise": 10}


def trial_days(plan_key: str) -> int:
    """How long this plan's trial runs. Never negative, never invented."""
    import os
    default = _DEFAULT_TRIAL_DAYS.get(plan_key, 0)
    raw = os.getenv(f"TITAN_TRIAL_DAYS_{plan_key.upper()}", "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


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
        days = trial_days(self.key)
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
            "trial_days": days,
            # A trial with no processor behind it is not a trial, it is a
            # free account that stops working. Say which one this is rather
            # than advertising a conversion that cannot happen.
            "trial_billable": bool(days) and processor_configured(),
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
            # Businesses this subscriber has onboarded. The plan's `clients`
            # limit is enforced against the length of this list, so a Free
            # account cannot quietly manage ten businesses.
            "client_ids": [],
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
    # A signed token rather than a dict entry. The dict meant every paying
    # customer was silently signed out by a restart, which on a free-tier host
    # happens often. Verification is stateless, so a restart no longer touches
    # anyone's session.
    from . import sessions
    return sessions.issue(email, kind="account", ttl=sessions.ACCOUNT_TTL)


def resolve(token: str) -> Optional[str]:
    from . import sessions
    email = sessions.subject(token or "", kind="account")
    if not email:
        return None
    # A valid signature is not enough: the account must still exist. Deleting
    # someone must actually revoke their access.
    with _lock:
        return email if email in _accounts else None


def sign_out(token: str) -> bool:
    from . import sessions
    return sessions.revoke(token)


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


def owned_clients(email: str) -> list:
    with _lock:
        acct = _accounts.get(email)
        return list(acct.get("client_ids", [])) if acct else []


def all_emails() -> list:
    """Every registered subscriber. For tenancy lookups, never for display.

    Deliberately an accessor rather than letting callers reach into
    `_accounts`: the ownership rule has one home (`core/tenancy.py`) and this
    is the only door it needs.
    """
    with _lock:
        return list(_accounts)


def can_add_client(email: str) -> dict:
    """Is this subscriber allowed another business? Never a bare boolean —
    a refusal has to say what to do about it."""
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            return {"allowed": False, "reason": "No such account."}
        plan = PLANS[acct["plan"]]
        used = len(acct.get("client_ids", []))
    if plan.clients == -1 or used < plan.clients:
        return {"allowed": True, "used": used, "limit": plan.clients}

    nxt = None
    for k in ORDER[ORDER.index(acct["plan"]) + 1:]:
        if PLANS[k].clients == -1 or PLANS[k].clients > plan.clients:
            nxt = PLANS[k]
            break
    return {
        "allowed": False,
        "reason": (f"The {plan.name} plan covers {plan.clients} business"
                   f"{'es' if plan.clients != 1 else ''}, and you have "
                   f"{used}."),
        "upgrade_to": nxt.key if nxt else None,
        "upgrade_gives": (
            f"{nxt.name} covers "
            f"{'unlimited businesses' if nxt.clients == -1 else str(nxt.clients) + ' businesses'}"
            f" for ${nxt.price_usd:.0f}/month." if nxt else
            "You are already on the highest plan."),
    }


def attach_client(email: str, client_id: str) -> None:
    with _lock:
        acct = _accounts.get(email)
        if acct is not None and client_id not in acct.setdefault("client_ids", []):
            acct["client_ids"].append(client_id)


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
# Two adapters behind one seam.
#
# PayPal is Abdullah's stated preference and stays supported. It also cannot
# RECEIVE money in Pakistan, which means a PayPal-only build can never be paid
# — the plan table, the quotas and the signup flow are all finished and the
# product still earns nothing.
#
# Dodo Payments is the researched alternative: a Merchant of Record that
# handles US sales tax and EU VAT and pays out to Payoneer and Wise, both of
# which work in Pakistan. Fees ~4% + $0.40. Preferred here purely because it
# is the one that can actually complete a sale from where he lives.
#
# Neither is required. With neither configured, signup and the free tier work
# and the refusal names exactly what is missing.


def _dodo_key() -> str:
    return os.getenv("DODO_PAYMENTS_API_KEY", "").strip()


def dodo_configured() -> bool:
    return bool(_dodo_key())


def paypal_configured() -> bool:
    return bool(os.getenv("PAYPAL_CLIENT_ID", "").strip()
                and os.getenv("PAYPAL_CLIENT_SECRET", "").strip())


def paddle_price_id(plan_key: str) -> str:
    return os.getenv(f"PADDLE_PRICE_ID_{plan_key.upper()}", "").strip()


def paddle_configured() -> bool:
    """Paddle is the researched processor for a Pakistan seller — and until
    now nothing in this module looked for it.

    It was named in the help text as the recommended option and checked
    against Paddle's own unsupported-suppliers list on 2026-08-08, but there
    was no detector: `configured()` tested Dodo and PayPal only. Setting
    PADDLE_API_KEY would have left the product still reporting "no processor"
    and still refusing every sale, with nothing on screen explaining why.

    Requires the API key AND at least one price id — a key with no price to
    sell against cannot complete a checkout, and reporting "configured" on the
    key alone would move the failure to the customer's card screen.
    """
    if not os.getenv("PADDLE_API_KEY", "").strip():
        return False
    return any(paddle_price_id(k) for k in ORDER if k != "free")


def processor_name() -> str:
    # Paddle first: it is the only one of the three verified to onboard a
    # Pakistan-based seller, so if it is configured it is the intended one.
    if paddle_configured():
        return "paddle"
    if dodo_configured():
        return "dodo"
    if os.getenv("PAYPAL_CLIENT_ID", "").strip():
        return "paypal"
    return "none"


def configured() -> bool:
    return paddle_configured() or dodo_configured() or paypal_configured()


def processor_configured() -> bool:
    """Alias used by the plan table. A trial is only real if a card can be
    charged at the end of it."""
    return configured()


def missing_for_paddle() -> list[str]:
    """Exactly which environment variables are still absent. Names them rather
    than saying 'not configured', so the fix is a copy-paste."""
    missing = []
    if not os.getenv("PADDLE_API_KEY", "").strip():
        missing.append("PADDLE_API_KEY")
    for key in ORDER:
        if key == "free":
            continue
        if not paddle_price_id(key):
            missing.append(f"PADDLE_PRICE_ID_{key.upper()}")
    return missing


def _dodo_product_id(plan_key: str) -> str:
    return os.getenv(f"DODO_PRODUCT_ID_{plan_key.upper()}", "").strip()


def _dodo_checkout(email: str, plan_key: str, plan: Plan) -> dict:
    """Create a Dodo checkout session and hand back the URL the CUSTOMER opens.

    Titan never sees a card number. The SDK is imported inside the function on
    purpose: a missing package must degrade to an honest "not configured"
    message, never take the process down at import time the way reportlab once
    did.
    """
    product_id = _dodo_product_id(plan_key)
    if not product_id:
        return {
            "ready": False, "processor": "dodo", "plan": plan_key,
            "price_usd": plan.price_usd,
            "needs": (f"Create a ${plan.price_usd:.0f}/month subscription "
                      f"product in the Dodo dashboard and set "
                      f"DODO_PRODUCT_ID_{plan_key.upper()} to its id "
                      f"(looks like pdt_…)."),
        }
    try:
        from dodopayments import DodoPayments
    except Exception:
        return {
            "ready": False, "processor": "dodo", "plan": plan_key,
            "needs": ("The dodopayments package is not installed in this "
                      "deployment. It is in requirements.txt — the Space "
                      "needs a rebuild."),
        }

    site = os.getenv("TITAN_SITE_URL", "https://titanomega-ai.com").rstrip("/")
    env = os.getenv("DODO_PAYMENTS_ENVIRONMENT", "live_mode").strip() or "live_mode"
    try:
        kwargs = {"bearer_token": _dodo_key(), "environment": env}
        base = os.getenv("DODO_PAYMENTS_BASE_URL", "").strip()
        if base:
            kwargs["base_url"] = base
        client = DodoPayments(**kwargs)
        session = client.checkout_sessions.create(
            product_cart=[{"product_id": product_id, "quantity": 1}],
            customer={"email": email},
            return_url=f"{site}/join?paid=1",
            cancel_url=f"{site}/pricing",
        )
        url = getattr(session, "checkout_url", "") or ""
        if not url:
            raise ValueError("no checkout_url in the response")
        return {
            "ready": True, "processor": "dodo", "plan": plan_key,
            "price_usd": plan.price_usd,
            "checkout_url": url,
            "session_id": getattr(session, "session_id", ""),
            "environment": env,
            "flow": ("Open checkout_url. Dodo takes the payment as Merchant of "
                     "Record and pays out to Payoneer or Wise. Titan never "
                     "sees card details."),
        }
    except Exception as exc:
        # Report the real failure. A checkout that silently returns nothing is
        # indistinguishable from a customer who changed their mind.
        return {
            "ready": False, "processor": "dodo", "plan": plan_key,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "needs": ("Dodo rejected the checkout request. Check "
                      "DODO_PAYMENTS_API_KEY, that DODO_PAYMENTS_ENVIRONMENT "
                      "matches the key (test_mode vs live_mode), and that the "
                      "product id belongs to the same account."),
        }


def checkout(email: str, plan_key: str) -> dict:
    """Return where the CUSTOMER goes to approve a subscription.

    Titan never takes a card number and never completes a payment on anyone's
    behalf — it hands back an approval URL the customer opens themselves. That
    is both the correct integration and the only safe one.
    """
    if plan_key not in PLANS or plan_key == "free":
        raise ValueError("Choose a paid plan.")
    plan = PLANS[plan_key]

    if dodo_configured():
        return _dodo_checkout(email, plan_key, plan)

    if not configured():
        return {
            "ready": False,
            "processor": "none",
            "plan": plan_key,
            "price_usd": plan.price_usd,
            "needs": ("No payment processor is connected, so nothing can be "
                      "sold yet.\n"
                      "• Paddle (checked 2026-08-08: Pakistan is NOT on "
                      "Paddle's unsupported-suppliers list). Merchant of "
                      "Record — it handles sales tax and VAT and pays out via "
                      "Payoneer, which works in Pakistan. ~5% + $0.50. Set "
                      "PADDLE_API_KEY and PADDLE_PRICE_ID_STUDENT / "
                      "_INDIVIDUAL / _ENTERPRISE.\n"
                      "• Dodo Payments: same model, set DODO_PAYMENTS_API_KEY "
                      "and DODO_PRODUCT_ID_*. Confirm it onboards Pakistan "
                      "sellers before relying on it.\n"
                      "• PayPal: PAYPAL_CLIENT_ID / _SECRET / _PLAN_ID_*. "
                      "Works only where PayPal can RECEIVE — not Pakistan.\n"
                      "The account must be in YOUR name. Routing your revenue "
                      "through someone else's account breaks every "
                      "processor's terms, makes it their taxable income, and "
                      "gets funds frozen — see docs/PAYMENTS.md."),
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
