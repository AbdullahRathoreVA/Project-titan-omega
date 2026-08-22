"""One screen that answers "what is actually connected, and what does it cost".

Titan grew a ``configured()`` or ``status()`` function per subsystem — payments,
telephony, the renderer, the embedding model, the credential vault, the
deployment secret. Each is correct and each lives somewhere different, so the
only way to answer "is this deployment ready" was to know all of them.

This aggregates them. It does not reimplement any of them: every entry calls
the module that already owns the question. Two rules follow from that:

* **Nothing is reported connected without calling the real check.** No entry is
  hardcoded true, and no entry infers connectedness from the presence of an
  environment variable when the owning module has an opinion.
* **A check that raises is `unknown`, never `disconnected`.** They lead to
  different actions — one is "go and connect it", the other is "something is
  broken on our side" — and a red cross for both sends people to fix the wrong
  thing.

Every entry also says what it **costs**, because the brief asks the customer to
always know whether something is free, included, paid, or needs an account
somewhere else. Getting that wrong is how somebody enables a feature and
receives a bill.
"""

from __future__ import annotations

import os
import time

CONNECTED = "connected"
NOT_CONFIGURED = "not_configured"
NEEDS_ATTENTION = "needs_attention"
UNKNOWN = "unknown"

FREE = "free"
INCLUDED = "included"
PAID = "paid"
EXTERNAL = "requires external account"


def _entry(key, name, category, status, detail, unlocks, cost, configure="",
           extra=None) -> dict:
    rec = {
        "key": key, "name": name, "category": category, "status": status,
        "detail": detail, "unlocks": unlocks, "cost": cost,
        "configure": configure,
    }
    if extra:
        rec.update(extra)
    return rec


def _safe(fn, *args, **kwargs):
    """Call a status function, or report why it could not be called."""
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:                                   # noqa: BLE001
        return None, str(exc)[:160]


def _payments() -> dict:
    from . import billing
    value, err = _safe(billing.processor_configured)
    if err is not None:
        return _entry("payments", "Payments", "billing", UNKNOWN,
                      f"The billing module could not be read: {err}",
                      "Taking money at all.", EXTERNAL)
    if value:
        name, _ = _safe(billing.processor_name)
        return _entry("payments", "Payments", "billing", CONNECTED,
                      f"Processor configured: {name}.",
                      "Subscriptions, trials that can convert, real MRR.",
                      EXTERNAL)
    missing, _ = _safe(billing.missing_for_paddle)
    return _entry(
        "payments", "Payments", "billing", NOT_CONFIGURED,
        "No payment processor is configured, so nothing can be sold and "
        "revenue is reported as not measured rather than as $0.",
        "Subscriptions, trials that can convert, real MRR.", EXTERNAL,
        configure=("Set " + ", ".join(missing) if missing
                   else "Set the processor's API keys."),
        extra={"missing": missing or []})


def _deployment_secret() -> dict:
    from . import appsecret
    value, err = _safe(appsecret.status)
    if err is not None or not isinstance(value, dict):
        return _entry("secret", "Deployment secret", "platform", UNKNOWN,
                      f"Could not be read: {err}", "Signing sessions and "
                      "encrypting stored site credentials.", FREE)
    if value.get("configured"):
        return _entry("secret", "Deployment secret", "platform", CONNECTED,
                      "TITAN_SECRET is set and is not a published default.",
                      "Sessions and the credential vault.", FREE)
    status = NEEDS_ATTENTION if value.get("enforced") else NOT_CONFIGURED
    return _entry(
        "secret", "Deployment secret", "platform", status,
        ("Set to a value published in this repository."
         if value.get("using_published_default")
         else "TITAN_SECRET is not set."),
        "Sessions and the credential vault.", FREE,
        configure="Set TITAN_SECRET to a long random string on the host.")


def _storage() -> dict:
    from . import db
    value, err = _safe(db.stats)
    if err is not None or not isinstance(value, dict):
        return _entry("storage", "Durable storage", "platform", UNKNOWN,
                      f"Could not be read: {err}",
                      "Accounts, organisations and rollback snapshots "
                      "surviving a rebuild.", PAID)
    if value.get("durable"):
        return _entry("storage", "Durable storage", "platform", CONNECTED,
                      "State is on a persistent mount.",
                      "Accounts and rollback snapshots surviving a rebuild.",
                      PAID)
    return _entry(
        "storage", "Durable storage", "platform", NEEDS_ATTENTION,
        "State is NOT on a persistent mount. Accounts, organisations, the "
        "audit log and every rollback snapshot are lost on the next rebuild.",
        "Anything that has to outlive a deploy.", PAID,
        configure="Mount persistent storage at /data, or point "
                  "TITAN_STATE_FILE at a real volume.")


def _renderer() -> dict:
    from . import render
    value, err = _safe(render.status)
    if err is not None or not isinstance(value, dict):
        return _entry("renderer", "JavaScript renderer", "audit", UNKNOWN,
                      f"Could not be read: {err}",
                      "Auditing sites that render their content in the "
                      "browser.", PAID)
    configured = bool(value.get("configured") or value.get("enabled")
                      or value.get("url"))
    if configured:
        return _entry("renderer", "JavaScript renderer", "audit", CONNECTED,
                      "A renderer is configured.",
                      "Auditing client-rendered sites.", PAID)
    return _entry(
        "renderer", "JavaScript renderer", "audit", NOT_CONFIGURED,
        "Not configured. Client-rendered sites are DETECTED and reported as "
        "unreliable rather than being audited as if they were empty.",
        "Auditing client-rendered sites.", PAID,
        configure="Deploy services/renderer/ (needs ~1GB RAM), then set "
                  "TITAN_RENDER_URL and TITAN_RENDER_TOKEN.")


def _env_backed(key, name, category, variables, unlocks, cost, note="") -> dict:
    """For integrations whose only real check IS the presence of a variable.

    Kept honest by saying so in the detail: a set variable proves the operator
    intended a connection, not that the far end answers.
    """
    present = [v for v in variables if os.getenv(v, "").strip()]
    if len(present) == len(variables):
        return _entry(key, name, category, CONNECTED,
                      "Configured. Not verified against the remote service — "
                      "a set variable proves intent, not reachability.",
                      unlocks, cost)
    missing = [v for v in variables if v not in present]
    return _entry(key, name, category, NOT_CONFIGURED,
                  note or f"Not configured. Missing: {', '.join(missing)}.",
                  unlocks, cost,
                  configure=f"Set {', '.join(missing)} on the host.",
                  extra={"missing": missing})


def _telegram() -> dict:
    from ..engines import telegram_bot
    value, err = _safe(telegram_bot.configured)
    if err is not None:
        return _entry("telegram", "Telegram control", "comms", UNKNOWN,
                      f"Could not be read: {err}",
                      "Running Titan from a phone.", FREE)
    if value:
        return _entry("telegram", "Telegram control", "comms", CONNECTED,
                      "Bot token configured.", "Running Titan from a phone.",
                      FREE)
    return _entry("telegram", "Telegram control", "comms", NOT_CONFIGURED,
                  "No bot token.", "Running Titan from a phone.", FREE,
                  configure="Set TELEGRAM_BOT_TOKEN.")


def _sites() -> dict:
    """WordPress credentials, counted from the vault rather than assumed."""
    from . import analytics, site_access
    snap, err = _safe(analytics.accounts_snapshot)
    if err is not None:
        return _entry("wordpress", "Website connections", "website", UNKNOWN,
                      f"Account state could not be read: {err}",
                      "Applying approved fixes to a live site.", FREE)
    total = connected = 0
    for account in snap["accounts"]:
        for business in account.get("businesses", []):
            total += 1
            state, serr = _safe(site_access.status, business["id"])
            if serr is None and isinstance(state, dict) and state.get("connected"):
                connected += 1
    if total == 0:
        return _entry(
            "wordpress", "Website connections", "website", NOT_CONFIGURED,
            "No businesses have been added yet, so there is nothing to "
            "connect.", "Applying approved fixes to a live site.", FREE,
            extra={"connected": 0, "total": 0})
    status = CONNECTED if connected else NOT_CONFIGURED
    return _entry(
        "wordpress", "Website connections", "website", status,
        f"{connected} of {total} businesses have a stored credential.",
        "Applying approved fixes to a live site.", FREE,
        configure="Create a WordPress application password and connect it. "
                  "See docs/CONNECTING_A_WORDPRESS_SITE.md.",
        extra={"connected": connected, "total": total})


def all_integrations() -> list:
    """Every integration, each answered by the module that owns it."""
    checks = (
        _payments,
        _deployment_secret,
        _storage,
        _sites,
        _renderer,
        _telegram,
        lambda: _env_backed(
            "publishing", "Social publishing", "marketing",
            ["TITAN_PUBLISH_WEBHOOK"],
            "Queued posts actually reaching a platform.", EXTERNAL,
            note="Not configured. The CONNECT buttons are placeholders and "
                 "there is no OAuth behind them — nothing is posted anywhere."),
    )
    out = []
    for check in checks:
        try:
            out.append(check())
        except Exception as exc:                               # noqa: BLE001
            out.append(_entry("unknown", "Unknown", "platform", UNKNOWN,
                              f"This check itself failed: {str(exc)[:120]}",
                              "", FREE))
    return out


def summary() -> dict:
    rows = all_integrations()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "integrations": rows,
        "counts": counts,
        "connected": counts.get(CONNECTED, 0),
        "total": len(rows),
        # Named so nobody reads "3 of 7 connected" as a health score. Some of
        # these cost money and are deliberately off.
        "note": ("Not a score. Several of these are optional or paid, and "
                 "being unconfigured is a decision rather than a fault."),
        "generated_at": time.time(),
    }
