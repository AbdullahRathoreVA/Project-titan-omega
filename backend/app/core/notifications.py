"""Things that are actually true right now and worth acting on.

The brief lists the notifications it wants: trial ending, integration failed,
payment failed, audit completed, security warning, onboarding incomplete. Every
one of those is easy to emit and most of them are, today, unknowable — Titan
has no customers, no processor and no per-account trial state. Emitting them
anyway would produce a notification centre full of things that never happened,
which is the fastest way to teach somebody to ignore it.

So this derives notifications from state that is **checked at read time**, and
each one carries the source that produced it. There is no notification table
and nothing is queued: a notification here is a *current condition*, so it
disappears when the condition does rather than sitting unread describing
something that has since been fixed.

**What is deliberately NOT emitted, and why:**

* *Trial ending* — `billing` has no per-account ``trial_ends_at``. There is
  nothing to count down. Emitting a guess from signup date plus the plan's
  trial length would notify people about a deadline that does not exist.
* *Payment failed* — no processor is connected, so no payment has ever been
  attempted, so none has failed.

Both reappear on their own the moment the underlying data exists, because they
are computed rather than stored. That is the point of doing it this way.
"""

from __future__ import annotations

import time

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


def _note(key, severity, title, detail, source, action="") -> dict:
    return {"key": key, "severity": severity, "title": title,
            "detail": detail, "source": source, "action": action}


def current() -> dict:
    """Every condition that is true right now, worst first."""
    out: list[dict] = []
    checked: list[str] = []
    failed: list[dict] = []

    # --- the deployment itself -------------------------------------------
    try:
        from . import db
        if not db.stats().get("durable"):
            out.append(_note(
                "storage_not_durable", CRITICAL,
                "Storage does not survive a rebuild",
                "Accounts, organisations, the audit log and every rollback "
                "snapshot are lost the next time this deploys. Titan holds "
                "the only copy of the previous content of pages it has "
                "changed on live websites.",
                "core/db.py",
                "Mount persistent storage at /data, or point "
                "TITAN_STATE_FILE at a real volume."))
        checked.append("storage")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "storage", "error": str(exc)[:120]})

    try:
        from . import appsecret
        state = appsecret.status()
        if not state.get("configured"):
            out.append(_note(
                "secret_missing",
                CRITICAL if state.get("enforced") else WARNING,
                "No deployment secret",
                "Sessions are signed and stored site credentials are "
                "encrypted with a key that is published in this repository.",
                "core/appsecret.py", "Set TITAN_SECRET on the host."))
        checked.append("secret")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "secret", "error": str(exc)[:120]})

    # --- the login cutover ------------------------------------------------
    try:
        from . import identity
        mode = identity.mode()
        if mode["mode"] == "legacy":
            out.append(_note(
                "identity_legacy", WARNING,
                "Sign-in is still the environment gate",
                "One username and one password compared against environment "
                "variables. Organisations and per-person roles cannot be used "
                "until a real founder account exists.",
                "core/identity.py",
                "Set TITAN_FOUNDER_EMAIL, and a TITAN_PASSWORD of at least 12 "
                "characters. The old gate then retires itself."))
        checked.append("identity")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "identity", "error": str(exc)[:120]})

    # --- integrations that are unhealthy rather than merely optional ------
    try:
        from . import integrations
        for row in integrations.all_integrations():
            if row["status"] == integrations.NEEDS_ATTENTION:
                # storage is already reported above, in more detail
                if row["key"] == "storage":
                    continue
                out.append(_note(
                    f"integration_{row['key']}", WARNING,
                    f"{row['name']} needs attention", row["detail"],
                    "core/integrations.py", row.get("configure", "")))
            elif row["status"] == integrations.UNKNOWN:
                out.append(_note(
                    f"integration_{row['key']}", WARNING,
                    f"{row['name']} could not be checked", row["detail"],
                    "core/integrations.py",
                    "This is a fault on Titan's side, not a missing setup."))
        checked.append("integrations")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "integrations", "error": str(exc)[:120]})

    # --- work that failed -------------------------------------------------
    try:
        from . import queue
        # NOTE: the counts are nested under "counts", not top level. Reading
        # stats.get("failed") returns None, which is falsy, so this
        # notification would never have fired and the absence would have
        # looked exactly like "no jobs failed".
        counts = queue.stats().get("counts", {})
        failed_jobs = int(counts.get(queue.FAILED) or 0)
        dead_jobs = int(counts.get(queue.DEAD) or 0)
        if failed_jobs or dead_jobs:
            out.append(_note(
                "jobs_failed", WARNING,
                f"{failed_jobs + dead_jobs} background job(s) did not complete",
                f"{failed_jobs} failed and {dead_jobs} exhausted their "
                "retries. Each one is something that was asked for and did "
                "not happen.",
                "core/queue.py", "Review the failed jobs."))
        checked.append("jobs")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "jobs", "error": str(exc)[:120]})

    # --- selling ----------------------------------------------------------
    try:
        from . import billing
        if not billing.processor_configured():
            out.append(_note(
                "no_processor", WARNING,
                "Nothing can be sold",
                "No payment processor is configured, so no subscription can "
                "be completed and revenue reads as not measured rather than "
                "as zero.",
                "core/billing.py",
                "Set the processor's API keys. See docs/PAYMENTS.md."))
        checked.append("billing")
    except Exception as exc:                                   # noqa: BLE001
        failed.append({"check": "billing", "error": str(exc)[:120]})

    out.sort(key=lambda n: _ORDER.get(n["severity"], 3))
    return {
        "notifications": out,
        "counts": {
            CRITICAL: sum(1 for n in out if n["severity"] == CRITICAL),
            WARNING: sum(1 for n in out if n["severity"] == WARNING),
            INFO: sum(1 for n in out if n["severity"] == INFO),
        },
        "checked": checked,
        # A check that could not run is NOT an absence of a problem.
        "checks_failed": failed,
        "not_emitted": [
            {"key": "trial_ending",
             "why": "billing has no per-account trial_ends_at, so there is no "
                    "deadline to count down to. A guess from signup date plus "
                    "the plan's trial length would notify people about a date "
                    "that does not exist."},
            {"key": "payment_failed",
             "why": "no processor is connected, so no payment has ever been "
                    "attempted and none has failed."},
        ],
        "generated_at": time.time(),
    }
