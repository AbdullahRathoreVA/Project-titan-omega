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
#   TITAN_TRIAL_DAYS_STUDENT / _INDIVIDUAL / _ENTERPRISE / _AGENCY
#
# Abdullah set these on 2026-09-28, replacing the earlier year-long student
# trial: 3 days on Student, 7 on Individual, a month (30 days) on Enterprise,
# and none on Agency, whose price pays for his own time from day one.
#
# They are env-driven because a trial length is a pricing experiment, and a
# pricing experiment that needs a redeploy never gets run. The Paddle price
# carries its own trial; the two must be changed together.
_DEFAULT_TRIAL_DAYS = {"free": 0, "student": 3, "individual": 7,
                       "enterprise": 30, "agency": 0}


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
        "student", "Student", 5.0,
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
        "individual", "Individual", 10.0,
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
        "enterprise", "Enterprise", 20.0,
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
    # Enterprise already has no enforced limit, so Agency cannot be sold on a
    # bigger number. Everything it adds is either built (the client's logo on
    # their portal and reports: clients.logo_url, client_report.py) or
    # Abdullah's own time, which he chose to promise on 2026-09-28. Adding a
    # line here that neither the code nor he delivers is a false advert, and
    # Paddle's review compares the site against what is sold.
    "agency": Plan(
        "agency", "Agency", 50.0,
        clients=-1, audits_per_month=-1, ai_calls_per_month=-1,
        keeps_history_days=-1,
        features=(
            "Everything in Enterprise",
            "Each client's own logo on their portal and PDF reports",
            "Priority support: a reply within 24 hours",
            "Done-for-you setup of your first 5 businesses",
            "A 30-minute strategy call every month",
        ),
        note="Includes the founder's own time: setup, support and a monthly "
             "call."),
}

ORDER = ("free", "student", "individual", "enterprise", "agency")


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
    """Create an account. ALWAYS on Free.

    `plan` is only what the person chose on the way in, kept as
    `requested_plan` so the pricing funnel can be measured. It used to become
    the account's plan, with status "pending_payment" - and every limit read
    the plan and ignored the status, so picking Agency on /join and closing
    the checkout kept unlimited Agency for nothing. A paid plan is set only by
    a confirmed payment (apply_paddle_event -> set_plan) or a founder grant.
    """
    # The check here used to be `"@" not in email or len(email) < 5`, which
    # accepted `xx@xx` and `@@@@@` as customers. That is not a cosmetic
    # problem: the signup funnel is the only instrument that answers "is
    # anybody actually using this?", and it was counting junk. Nothing could
    # ever be sent to those accounts either, so a receipt or a trial-ending
    # notice was undeliverable before it was written.
    from . import emailaddr
    email = emailaddr.normalise(email)
    problem = emailaddr.reason_invalid(email)
    if problem:
        raise ValueError(problem)
    # Deliverability is a SEPARATE question, off by default, and it fails open
    # — see core/emailaddr.py. Unknown never becomes invalid, because a
    # nameserver blinking must not cost a customer.
    posted = emailaddr.deliverable(email)
    if posted.get("deliverable") is False:
        raise ValueError(
            f"Mail cannot be delivered to {email.partition('@')[2]} — "
            f"{posted.get('reason')}. Please use an address you can receive "
            f"mail at.")
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
            # Always False, and never set to True by anything here. Only a
            # delivered message proves a mailbox exists, and sending needs a
            # provider Titan does not have. An unsent address reported as
            # verified is the same lie as an unmeasured number.
            "email_verified": False,
            "_salt": salt,
            "_pwhash": _hash(password, salt),
            "plan": "free",
            "requested_plan": plan,
            "created_at": time.time(),
            "period_start": _period_start(),
            "usage": {"audits": 0, "ai_calls": 0},
            "subscription_id": "",
            "status": "active",
            # Businesses this subscriber has onboarded. The plan's `clients`
            # limit is enforced against the length of this list, so a Free
            # account cannot quietly manage ten businesses.
            "client_ids": [],
        }
    # from_plan is NULL for the first row of an account's life. That is what
    # makes a signup distinguishable from an upgrade later, and without it
    # trial-to-paid conversion could not be reconstructed from history at all.
    record_change(email, None, "free", status=_accounts[email]["status"],
                  reason="signup" if plan == "free" else f"signup:wants={plan}")
    events.emit("SubscriptionChanged", {"email": email, "plan": "free",
                                        "requested_plan": plan,
                                        "status": _accounts[email]["status"]},
                actor="billing")
    return public(email)


def authenticate(email: str, password: str) -> Optional[str]:
    email = (email or "").strip().lower()
    with _lock:
        acct = _accounts.get(email)
        if not acct or acct.get("is_demo"):
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


def set_password(email: str, current: str, new: str) -> dict:
    """Change a subscriber's password. Requires the CURRENT one.

    Requiring it is not politeness. Without it a stolen session token becomes a
    permanent account takeover: the thief changes the password, and the owner
    is locked out of their own billing.

    Every other session for this account ends. That is the entire reason a
    person changes a password, and one that leaves the thief signed in has
    done nothing.
    """
    email = (email or "").strip().lower()
    if len(new or "") < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            return {"ok": False, "error": "No such account."}
        if not hmac.compare_digest(_hash(current, acct["_salt"]),
                                   acct["_pwhash"]):
            # Deliberately the same wording the login uses. "Your current
            # password is wrong" and "no such account" must not be
            # distinguishable to somebody holding a token and guessing.
            return {"ok": False, "error": "Wrong email or password"}
        salt = secrets.token_hex(16)
        acct["_salt"] = salt
        acct["_pwhash"] = _hash(new, salt)
        acct["password_changed_at"] = time.time()

    from . import sessions
    sessions.invalidate_all(email, kind="account")
    return {"ok": True, "signed_out_everywhere": True}


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
            "email_verified": bool(acct.get("email_verified", False)),
            "plan": acct["plan"],
            "plan_name": plan.name,
            "requested_plan": acct.get("requested_plan", acct["plan"]),
            # The public demo's cockpit says so, and offers a real signup.
            "demo": bool(acct.get("is_demo")),
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


# The public demo's account. `.invalid` is reserved (RFC 2606): nothing can be
# mailed to it and nobody can sign up as it. It has no password, so nobody can
# sign in as it either - only /api/demo/cockpit issues its sessions, and
# main.auth_guard refuses every write it attempts, on every door.
DEMO_ACCOUNT = "demo@titan-omega.invalid"


def ensure_demo_account() -> str:
    """Create the demo account if it is missing. It is kept out of every
    founder figure (analytics.accounts_snapshot skips it) and records no
    signup, because nobody signed up."""
    with _lock:
        if DEMO_ACCOUNT not in _accounts:
            _accounts[DEMO_ACCOUNT] = {
                "email": DEMO_ACCOUNT, "email_verified": False, "is_demo": True,
                "_salt": "", "_pwhash": "",            # matches no password
                "plan": "free", "requested_plan": "free",
                "created_at": time.time(), "period_start": _period_start(),
                "usage": {"audits": 0, "ai_calls": 0}, "subscription_id": "",
                "status": "active", "client_ids": [],
            }
    return DEMO_ACCOUNT


def is_demo(email: str) -> bool:
    return bool(email) and email == DEMO_ACCOUNT


def owned_clients(email: str) -> list:
    if is_demo(email):
        # Titan's own demonstration businesses - its own pages, audited for
        # real - and never anyone else's.
        from ..engines import demo_workspace
        return demo_workspace.business_ids()
    with _lock:
        acct = _accounts.get(email)
        return list(acct.get("client_ids", [])) if acct else []


def plan_for_client(client_id: str) -> str:
    """The plan name of the subscriber who owns this business, or "".

    The client portal showed every business a 60-day countdown meant for
    businesses the founder onboards by hand, so a subscriber's own business
    read "59 days left in trial" - a clock that ends nothing, on an account
    whose access actually comes from its plan.
    """
    with _lock:
        for acct in _accounts.values():
            if client_id and client_id in acct.get("client_ids", []):
                return PLANS[acct["plan"]].name
    return ""


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


def detach_client(email: str, client_id: str) -> None:
    """The subscriber removed this business, so it stops counting against
    their plan's business limit."""
    with _lock:
        acct = _accounts.get(email)
        if acct is not None and client_id in acct.get("client_ids", []):
            acct["client_ids"].remove(client_id)


def set_plan(email: str, plan: str, subscription_id: str = "",
             status: str = "active") -> dict:
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    with _lock:
        acct = _accounts.get(email)
        if not acct:
            raise ValueError("No such account.")
        was = acct.get("plan")
        acct.update(plan=plan, subscription_id=subscription_id, status=status)
    # Durable, append-only, and BEFORE the in-memory event: churn and
    # trial-to-paid conversion are properties of how an account changed, not of
    # what it is now. This call is the difference between those numbers being
    # measurable later and being invented.
    record_change(email, was, plan, status=status,
                  subscription_id=subscription_id)
    events.emit("SubscriptionChanged",
                {"email": email, "plan": plan, "status": status},
                actor="billing")
    return public(email)


# ------------------------------------------------- subscription history --
def _history_conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def record_change(email: str, from_plan, to_plan: str, *, status: str = "active",
                  subscription_id: str = "", reason: str = "") -> None:
    """Append one row. Never raises: failing to record history must not be the
    thing that stops somebody's plan from changing."""
    import uuid as _uuid
    try:
        granted = 1 if str(subscription_id or "").startswith("granted") else 0
        conn = _history_conn()
        with _lock, conn:
            conn.execute(
                "INSERT INTO subscription_events (id, ts, email, from_plan,"
                " to_plan, status, granted, reason) VALUES (?,?,?,?,?,?,?,?)",
                ("sub_" + _uuid.uuid4().hex[:16], time.time(), email,
                 from_plan, to_plan, status, granted, reason or ""))
    except Exception:
        pass


def history(email: str = "", limit: int = 200) -> list:
    """Newest first. The only reader; there is deliberately no edit or delete."""
    limit = max(1, min(int(limit or 200), 1000))
    try:
        if email:
            rows = _history_conn().execute(
                "SELECT * FROM subscription_events WHERE email=?"
                " ORDER BY ts DESC LIMIT ?", (email, limit)).fetchall()
        else:
            rows = _history_conn().execute(
                "SELECT * FROM subscription_events ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
    except Exception:
        return []
    return [{"id": r["id"], "ts": r["ts"], "email": r["email"],
             "from_plan": r["from_plan"], "to_plan": r["to_plan"],
             "status": r["status"], "granted": bool(r["granted"]),
             "reason": r["reason"]} for r in rows]


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


def paddle_client_token() -> str:
    """The token the BROWSER uses to open Paddle's checkout.

    A different credential from PADDLE_API_KEY, and deliberately so: Paddle
    publishes client-side tokens as safe for frontend code, while the API key
    is server-side only. Checked against Paddle's overlay-checkout
    documentation, not from memory.
    """
    return os.getenv("PADDLE_CLIENT_TOKEN", "").strip()


def paddle_environment() -> str:
    """"sandbox" or "production". Sandbox unless PADDLE_LIVE is set, because a
    deployment that defaults to live is one typo away from taking a real card
    during a test."""
    return "production" if os.getenv("PADDLE_LIVE", "").strip() else "sandbox"


def paddle_checkout_ready() -> bool:
    """Can a CUSTOMER actually complete a Paddle checkout?

    Separate from paddle_configured() on purpose. That one answers "is the
    server set up", and it is what processor_name() and the money metrics read.
    This one adds the client-side token, without which the browser cannot open
    the overlay at all — so a deployment can be server-configured and still
    unable to sell, and the two must not report the same thing.
    """
    return bool(paddle_configured() and paddle_client_token())


# ------------------------------------------------------ Paddle webhook --
# The checkout told customers "Titan is told the result by webhook" and
# docs/PAYMENTS.md said to point Paddle at POST /api/webhooks/billing. Neither
# existed: set_plan() had no caller except the founder's manual grant, so a
# customer who paid stayed on Free. This is the missing half.
WEBHOOK_TOLERANCE_S = 300        # a captured request cannot be replayed later
_WEBHOOK_STATE = "billing.paddle_webhook"
_ACTIVE = ("active", "trialing", "past_due")   # past_due: Paddle is retrying
_ENDED = ("canceled", "paused")


def verify_paddle_signature(raw: bytes, header: str,
                            now: Optional[float] = None) -> bool:
    """Paddle-Signature is `ts=<unix>;h1=<hex>`: an HMAC-SHA256 of
    "<ts>:<raw body>" keyed with the notification destination's secret.
    Fails closed — no secret, no header or a stale timestamp is a refusal."""
    secret = os.getenv("PADDLE_WEBHOOK_SECRET", "").strip()
    fields = [p.partition("=") for p in (header or "").split(";")]
    ts = next((v.strip() for k, _, v in fields if k.strip() == "ts"), "")
    sigs = [v.strip() for k, _, v in fields if k.strip() == "h1"]
    if not (secret and ts.isdigit() and sigs):
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > WEBHOOK_TOLERANCE_S:
        return False
    expected = hmac.new(secret.encode(), ts.encode() + b":" + raw,
                        hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def _plan_for_price(price_id: str) -> str:
    return next((k for k in ORDER if k != "free" and price_id
                 and paddle_price_id(k) == price_id), "")


def apply_paddle_event(event: dict) -> dict:
    """Turn one VERIFIED subscription notification into a plan change.

    The plan comes from the price id in Paddle's signed payload, never from
    custom data a browser supplied. Duplicates and out-of-order deliveries,
    both normal for webhooks, are ignored rather than re-applied.
    """
    from . import db, emailaddr

    kind = event.get("event_type") or ""
    data = event.get("data") or {}
    if not kind.startswith("subscription."):
        return {"ok": True, "ignored": f"{kind or 'event'} changes no plan"}

    state = db.get(_WEBHOOK_STATE, {}) or {}
    seen, last = state.get("seen", []), state.get("last", {})
    event_id, sub_id = event.get("event_id", ""), data.get("id", "")
    occurred = event.get("occurred_at", "")
    if event_id and event_id in seen:
        return {"ok": True, "duplicate": event_id}
    if occurred and occurred <= last.get(sub_id, ""):
        return {"ok": True, "ignored": "older than an event already applied"}

    email = emailaddr.normalise((data.get("custom_data") or {}).get("titan_email", ""))
    items = data.get("items") or [{}]
    plan = _plan_for_price(((items[0] or {}).get("price") or {}).get("id", ""))
    status = data.get("status", "")
    problem = ("no Titan account on this subscription" if email not in _accounts
               else "unknown price id" if status in _ACTIVE and not plan
               else "" if status in _ACTIVE + _ENDED
               else f"unhandled status {status!r}")
    if problem:
        # Somebody may have paid. Never silent: the founder resolves it by hand.
        events.emit("PaymentUnmatched", {"subscription_id": sub_id,
                                         "event": kind, "why": problem},
                    actor="billing", severity="warn")
        return {"ok": True, "unmatched": problem, "subscription_id": sub_id}

    account = set_plan(email, plan if status in _ACTIVE else "free",
                       subscription_id=sub_id, status=status)
    state["seen"] = (seen + [event_id])[-500:] if event_id else seen
    state["last"] = {**last, sub_id: occurred or last.get(sub_id, "")}
    db.put(_WEBHOOK_STATE, state)
    return {"ok": True, "applied": kind, "plan": account.get("plan"),
            "status": status}


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


def can_take_payment() -> bool:
    """Can a CUSTOMER actually complete a purchase right now?

    Distinct from configured(), which answers "is a processor set up on the
    server". For Paddle those came apart the moment the checkout was wired:
    the API key and a price id make the server ready, and the browser still
    cannot open the overlay without PADDLE_CLIENT_TOKEN.

    Reporting the two as one is how a pricing page comes to advertise a trial
    that converts while no sale can complete.
    """
    if paddle_configured():
        return paddle_checkout_ready()
    return dodo_configured() or paypal_configured()


def processor_configured() -> bool:
    """Alias used by the plan table. A trial is only real if a card can be
    charged at the end of it — so this asks whether one CAN be, not whether a
    key is present. It used to call configured(), and with a Paddle API key
    but no client token that advertised a conversion nobody could complete."""
    return can_take_payment()


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
    # The browser cannot open Paddle's overlay without this, so leaving it out
    # of the list would report "nothing missing" on a deployment that still
    # cannot take a payment. It is listed last because the others are the ones
    # that make the server ready.
    if not paddle_client_token():
        missing.append("PADDLE_CLIENT_TOKEN")
    return missing


def _paddle_checkout(email: str, plan_key: str, plan: Plan) -> dict:
    """What the browser needs to open Paddle's own checkout.

    Titan never takes a card number and never completes a payment on anyone's
    behalf. This hands back the price id and the CLIENT-SIDE token, and the
    customer approves inside Paddle's overlay.

    PADDLE_API_KEY is never included. It is a server-side credential, this
    payload is read by a browser, and there is a test asserting it never
    appears here.
    """
    price_id = paddle_price_id(plan_key)
    if not price_id:
        return {
            "ready": False, "processor": "paddle", "plan": plan_key,
            "price_usd": plan.price_usd,
            "needs": (f"Set PADDLE_PRICE_ID_{plan_key.upper()} to the Paddle "
                      f"price id for the {plan.name} plan."),
        }
    token = paddle_client_token()
    if not token:
        return {
            "ready": False, "processor": "paddle", "plan": plan_key,
            "price_usd": plan.price_usd,
            "needs": ("Set PADDLE_CLIENT_TOKEN. The API key configures the "
                      "server; the browser opens Paddle's checkout with a "
                      "separate CLIENT-SIDE token, which Paddle publishes as "
                      "safe for frontend code. Find it in Paddle under "
                      "Developer tools > Authentication. Without it the "
                      "checkout overlay cannot be initialised, so nothing can "
                      "be sold even though the server is otherwise ready."),
        }
    return {
        "ready": True,
        "processor": "paddle",
        "plan": plan_key,
        "price_usd": plan.price_usd,
        "price_id": price_id,
        # Safe to publish, by Paddle's own documentation. The API key is NOT
        # here and must never be.
        "client_token": token,
        "environment": paddle_environment(),
        "customer_email": email,
        # Rides the checkout into the transaction and the subscription, which
        # is how the webhook knows WHICH Titan account paid: Paddle's own
        # subscription events carry a customer id, not an email.
        "custom_data": {"titan_email": email},
        "flow": ("The page loads Paddle.js, calls Paddle.Initialize with "
                 "client_token, and opens Paddle.Checkout.open with this "
                 "price_id. The customer approves inside Paddle. Titan never "
                 "sees card details and is told the result by webhook."),
    }


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

    # Paddle FIRST. It is the only processor verified to onboard a Pakistan
    # seller, processor_name() already prefers it, and until now checkout()
    # skipped it entirely and fell through to PayPal's environment variable —
    # so setting the Paddle keys produced "Set PAYPAL_PLAN_ID_INDIVIDUAL."
    if paddle_configured():
        return _paddle_checkout(email, plan_key, plan)

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
                      "_INDIVIDUAL / _ENTERPRISE / _AGENCY.\n"
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
                # Accounts created before signup stopped granting paid plans:
                # a paid plan that was never paid for drops to Free. A payment
                # always arrives as set_plan with a real status, never this.
                if acct.get("status") == "pending_payment":
                    acct.setdefault("requested_plan", acct["plan"])
                    acct["plan"], acct["status"] = "free", "active"
                _accounts[email] = acct


def reset() -> None:
    """Test seam."""
    with _lock:
        _accounts.clear()
        _sessions.clear()
