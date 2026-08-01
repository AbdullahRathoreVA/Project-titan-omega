"""24/7 autonomous client monitoring — the part that runs without anyone asking.

An important distinction, because it decides what is buildable:

The claude-seo plugin's 30+ skills and 20 agents are INSTRUCTIONS. They need an
LLM agent to read and execute them, on demand, in a session. There is no daemon
to install and they cannot run themselves at 3am. What CAN run unattended is
ordinary code — so the plugin's methodology is implemented here as scheduled
Python, and the skills stay available for the deep, one-off audits where a
reasoning model genuinely adds something.

What this does on its own, forever:

  - re-audits every client site on a rota (technical + legal + local)
  - DIFFS against the previous audit and raises what CHANGED, which is the part
    a client actually notices: their developer removed the Impressum, the site
    went down, schema disappeared in a redeploy
  - escalates by severity: a site going offline or losing its imprint is worth
    interrupting someone for; a missing alt tag is not
  - keeps per-client history so the trial period shows a trend, not a snapshot

The diff is the whole point. A monthly report saying "score 67" is noise. A
message saying "your Impressum disappeared yesterday, that is a fine risk" is
why a client keeps paying.
"""

from __future__ import annotations

import time
from typing import Optional

from ..core import clients
from . import client_seo

# How often a single client is re-checked. Deliberately slow: these are real
# sites and we are a guest on them.
DEFAULT_INTERVAL = 6 * 3600          # 6 hours
MAX_HISTORY = 40                     # per client, bounded so state stays small

# What is worth waking someone up for.
ESCALATE = {
    "unreachable": "critical",
    "https": "critical",
    "imprint": "critical",
    "privacy": "critical",
    "cookie_consent": "high",
    "local_business": "high",
    "schema": "high",
}


def _fingerprint(audit: dict) -> dict:
    """The few facts worth comparing between runs."""
    if not audit.get("ok"):
        return {"reachable": False, "error": audit.get("error", "")}
    return {
        "reachable": True,
        "score": audit.get("score", 0),
        "grade": audit.get("grade", ""),
        "failed": sorted(audit.get("failed", [])),
        "legal_critical": (audit.get("counts") or {}).get("legal_critical", 0),
        "local_score": (audit.get("local") or {}).get("score", 0),
        "schema_types": sorted(audit.get("schema_types", [])),
    }


def diff(previous: Optional[dict], current: dict) -> list[dict]:
    """What changed since last time, in words a business owner understands."""
    if not previous:
        return []

    out: list[dict] = []

    # Availability first — nothing else matters if the site is down.
    was, now = previous.get("reachable"), current.get("reachable")
    if was and not now:
        out.append({
            "severity": "critical", "kind": "offline",
            "title": "Your website went offline",
            "detail": f"It was reachable at the last check and now returns "
                      f"{current.get('error', 'no response')}.",
            "action": "Contact your host immediately. Every hour offline is "
                      "lost customers and lost rankings.",
        })
        return out
    if not was and now:
        out.append({
            "severity": "info", "kind": "recovered",
            "title": "Your website is back online",
            "detail": "It is responding again after being unreachable.",
            "action": "No action needed.",
        })

    if not (was and now):
        return out

    # Legal exposure appearing is the single most expensive regression.
    if current["legal_critical"] > previous.get("legal_critical", 0):
        out.append({
            "severity": "critical", "kind": "legal",
            "title": "A legal compliance problem appeared",
            "detail": f"Legal-critical findings went from "
                      f"{previous.get('legal_critical', 0)} to "
                      f"{current['legal_critical']}. This usually means an "
                      f"imprint or privacy page was removed or its link broke.",
            "action": "Fix within days. In Germany a competitor can issue a "
                      "formal warning over this and bill their legal costs.",
        })

    # New failures, ranked by whether they are worth interrupting for.
    new_fail = set(current["failed"]) - set(previous.get("failed", []))
    for f in sorted(new_fail):
        out.append({
            "severity": ESCALATE.get(f, "medium"), "kind": "regression",
            "title": f"'{f}' check started failing",
            "detail": "This passed at the previous check and now does not — "
                      "usually a site update removed it.",
            "action": "Ask whoever maintains the site what changed.",
        })

    fixed = set(previous.get("failed", [])) - set(current["failed"])
    if fixed:
        out.append({
            "severity": "info", "kind": "improved",
            "title": f"{len(fixed)} issue(s) resolved",
            "detail": ", ".join(sorted(fixed)),
            "action": "Nothing needed — worth telling the client.",
        })

    # Score movement, only when meaningful.
    delta = current["score"] - previous.get("score", 0)
    if abs(delta) >= 5:
        out.append({
            "severity": "high" if delta < 0 else "info", "kind": "score",
            "title": f"SEO score {'fell' if delta < 0 else 'rose'} "
                     f"{abs(delta)} points",
            "detail": f"{previous.get('score')} -> {current['score']}.",
            "action": ("Investigate what changed on the site."
                       if delta < 0 else "Good — keep doing it."),
        })

    lost = set(previous.get("schema_types", [])) - set(current["schema_types"])
    if lost:
        out.append({
            "severity": "high", "kind": "schema",
            "title": f"Structured data disappeared: {', '.join(sorted(lost))}",
            "detail": "Schema is how AI search decides what to quote about the "
                      "business. Losing it removes them from AI answers.",
            "action": "Restore the JSON-LD block — usually lost in a redeploy.",
        })

    return out


def check_client(cid: str) -> dict:
    """Audit one client and diff against their last result."""
    rec = clients.get(cid)
    if not rec:
        return {"ok": False, "error": "no such client"}

    site = rec.get("website")
    if not site:
        return {"ok": False, "error": "no website on file"}

    audit = client_seo.audit(site,
                             business_name=rec.get("business_name", ""),
                             city=rec.get("city", ""),
                             country=rec.get("country", ""))
    current = _fingerprint(audit)
    history = rec.get("watch_history") or []
    previous = history[-1]["fingerprint"] if history else None
    changes = diff(previous, current)

    history.append({"ts": time.time(), "fingerprint": current})
    if len(history) > MAX_HISTORY:
        del history[:len(history) - MAX_HISTORY]

    clients.update_raw(cid, watch_history=history, last_audit=audit,
                       last_watch=time.time())
    clients.bump(cid, "seo_audits")

    for c in changes:
        if c["severity"] in ("critical", "high"):
            clients.log_activity(cid, "alert", f"{c['title']} — {c['action']}",
                                 {"severity": c["severity"], "kind": c["kind"]})

    return {"ok": True, "client": rec.get("business_name"),
            "score": current.get("score"), "changes": changes,
            "first_run": previous is None}


def due(interval: int = DEFAULT_INTERVAL) -> list[str]:
    """Clients whose next check is due, oldest first."""
    now = time.time()
    rows = []
    for c in clients.all_clients():
        if not c.get("website"):
            continue
        last = c.get("last_watch") or 0
        if now - last >= interval:
            rows.append((last, c["id"]))
    rows.sort()
    return [cid for _, cid in rows]


def cycle(limit: int = 3, interval: int = DEFAULT_INTERVAL) -> dict:
    """One scheduler tick. Kept small so a heartbeat never stalls on network."""
    checked, alerts = [], []
    for cid in due(interval)[:limit]:
        r = check_client(cid)
        if r.get("ok"):
            checked.append(r["client"])
            alerts.extend(
                {**c, "client": r["client"]} for c in r["changes"]
                if c["severity"] in ("critical", "high"))
    return {"checked": checked, "alerts": alerts, "ts": time.time()}


def summary() -> dict:
    """Everything the dashboard needs about ongoing monitoring."""
    rows = clients.all_clients()
    watched = [c for c in rows if c.get("website")]
    alerts = []
    for c in rows:
        for a in (c.get("activity") or [])[-25:]:
            if a.get("kind") == "alert":
                alerts.append({"client": c["business_name"],
                               "message": a.get("message", ""),
                               "ts": a.get("ts"),
                               "severity": (a.get("meta") or {}).get(
                                   "severity", "medium")})
    alerts.sort(key=lambda a: a["ts"] or 0, reverse=True)

    trends = []
    for c in rows:
        h = c.get("watch_history") or []
        if len(h) >= 2:
            first, last = h[0]["fingerprint"], h[-1]["fingerprint"]
            if first.get("reachable") and last.get("reachable"):
                trends.append({
                    "client": c["business_name"],
                    "from": first.get("score"), "to": last.get("score"),
                    "delta": last.get("score", 0) - first.get("score", 0),
                    "checks": len(h),
                })

    return {
        "watching": len(watched),
        "unwatched": len(rows) - len(watched),
        "interval_hours": DEFAULT_INTERVAL // 3600,
        "recent_alerts": alerts[:12],
        "trends": trends,
        "note": ("Monitoring runs on the server heartbeat, with no session "
                 "open and nobody logged in. The value is the DIFF: clients "
                 "notice 'your imprint disappeared yesterday', not 'your score "
                 "is 67'."),
    }
