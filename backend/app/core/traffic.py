"""Who opened the website — visitor analytics with no third party and no cost.

Abdullah asked to see "how many ppl have opened my website" beside signups and
subscriptions. Google Analytics would answer that, but it means a third-party
script, a consent banner under GDPR (his market is the EU, and his own audit
already flagged Titan for a missing privacy policy), and one more account to
manage. This measures it in-process instead: no script, no cookie, no vendor,
no bill.

**Privacy is the design constraint, not a footnote.** A raw IP address is
personal data under GDPR, and Titan sells legal compliance — storing visitor
IPs while charging clients to fix their compliance would be indefensible. So:

- The IP is never stored. It is hashed with the user agent and a salt that
  **changes every day**, which makes the resulting id useless for linking a
  person across days. That is a deliberate accuracy trade: unique visitors is
  a per-day figure only, and the report says so rather than summing daily
  uniques into a bigger, wronger number.
- Referrers are reduced to a **host** before storage. The full URL of the page
  someone came from can itself carry personal data in its query string.
- Only HTML page loads are counted. Counting asset and API requests would turn
  one visit into thirty and make every number on the screen meaningless.

Obvious crawlers are counted **separately**, never folded into human traffic.
A bot hit is real traffic but it is not a person who might sign up, and mixing
the two is how a dashboard starts lying about its funnel.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from typing import Optional

# 90 days of daily buckets is a few KB. The per-day visitor sets are the only
# thing that can grow, and they are capped.
MAX_DAYS = 90
MAX_VISITORS_PER_DAY = 20_000

# Substrings that identify a non-human client. Deliberately conservative — a
# false positive here silently deletes a real visitor from the funnel.
BOT_MARKERS = (
    "bot", "crawler", "spider", "slurp", "curl", "wget", "python-requests",
    "httpx", "headlesschrome", "lighthouse", "pingdom", "uptimerobot",
    "facebookexternalhit", "gptbot", "claudebot", "perplexitybot",
)

_lock = threading.RLock()
_days: dict[str, dict] = {}
_salt_day = ""
_salt = ""


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _daily_salt(day: str) -> str:
    """A salt that rotates daily. Yesterday's ids cannot be recomputed, so the
    stored hashes cannot be used to follow anyone over time — by construction,
    not by promise."""
    global _salt_day, _salt
    with _lock:
        if _salt_day != day:
            _salt_day = day
            _salt = os.getenv("TITAN_SECRET", "") + secrets.token_hex(16)
        return _salt


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in BOT_MARKERS)


def _bucket(day: str) -> dict:
    b = _days.get(day)
    if b is None:
        b = {"views": 0, "bot_views": 0, "visitors": [], "paths": {},
             "referrers": {}}
        _days[day] = b
        if len(_days) > MAX_DAYS:
            for stale in sorted(_days)[:len(_days) - MAX_DAYS]:
                del _days[stale]
    return b


def record(path: str, ip: str = "", user_agent: str = "",
           referrer: str = "") -> None:
    """Count one page load. Never raises — a counter must never be able to
    take down the page it is counting."""
    try:
        day = _today()
        with _lock:
            b = _bucket(day)
            if is_bot(user_agent):
                b["bot_views"] += 1
                return
            b["views"] += 1
            b["paths"][path] = b["paths"].get(path, 0) + 1

            vid = hashlib.sha256(
                (_daily_salt(day) + (ip or "") + (user_agent or "")).encode()
            ).hexdigest()[:16]
            if vid not in b["visitors"] and len(b["visitors"]) < MAX_VISITORS_PER_DAY:
                b["visitors"].append(vid)

            host = _referrer_host(referrer)
            if host:
                b["referrers"][host] = b["referrers"].get(host, 0) + 1
    except Exception:
        pass


def _referrer_host(referrer: str) -> str:
    """Host only. A full referring URL can carry personal data in its query."""
    ref = (referrer or "").strip()
    if not ref:
        return ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(ref).hostname or "").lower()
    except Exception:
        return ""
    if not host:
        return ""
    own = os.getenv("TITAN_SITE_HOST", "titanomega-ai.com")
    if host == own or host.endswith("." + own) or host in ("localhost", "127.0.0.1"):
        return ""            # internal navigation is not a referral
    return host[:80]


def report(days: int = 30) -> dict:
    """Traffic, and honestly what it can and cannot tell you."""
    from . import billing

    today = _today()
    with _lock:
        wanted = sorted(_days)[-max(1, days):]
        series = [{"day": d,
                   "views": _days[d]["views"],
                   "visitors": len(_days[d]["visitors"]),
                   "bot_views": _days[d]["bot_views"]}
                  for d in wanted]
        paths: dict[str, int] = {}
        referrers: dict[str, int] = {}
        for d in wanted:
            for k, v in _days[d]["paths"].items():
                paths[k] = paths.get(k, 0) + v
            for k, v in _days[d]["referrers"].items():
                referrers[k] = referrers.get(k, 0) + v
        today_visitors = len(_days.get(today, {}).get("visitors", []))

    views = sum(r["views"] for r in series)
    bot_views = sum(r["bot_views"] for r in series)
    busiest = max((r["visitors"] for r in series), default=0)

    with billing._lock:                                   # noqa: SLF001
        signups = len(billing._accounts)                  # noqa: SLF001

    return {
        "window_days": days,
        "days_measured": len(series),
        "views": views,
        "bot_views": bot_views,
        "visitors_today": today_visitors,
        "busiest_day_visitors": busiest,
        "series": series,
        "top_paths": dict(sorted(paths.items(), key=lambda kv: -kv[1])[:12]),
        "top_referrers": dict(sorted(referrers.items(),
                                     key=lambda kv: -kv[1])[:12]),
        "signups_total": signups,
        # Deliberately NOT a visitors→signups percentage. Unique visitors is a
        # per-day figure (the id salt rotates daily), so there is no honest
        # total to divide by. Publishing a conversion rate here would be
        # inventing the denominator.
        "conversion_note": (
            "Unique visitors is per-day only — the visitor id is salted with a "
            "salt that rotates every 24h, so the same person on two days "
            "cannot be recognised as one. That is intentional (no cross-day "
            "tracking, no cookie, no consent banner), and it means there is no "
            "honest all-time visitor total to divide signups by. Compare the "
            "daily visitor line against the signup dates instead."),
        "note": (
            "Counted in-process: no Google Analytics, no third-party script, "
            "no cookie, no cost. IP addresses are never stored — only a daily "
            "rotating hash. Only HTML page loads count; assets and API calls "
            "do not. Crawler hits are listed separately and never mixed into "
            "human traffic."),
    }


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"days": {d: {"views": b["views"], "bot_views": b["bot_views"],
                             "visitors": list(b["visitors"]),
                             "paths": dict(b["paths"]),
                             "referrers": dict(b["referrers"])}
                         for d, b in _days.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("days")
    if not isinstance(rows, dict):
        return
    with _lock:
        _days.clear()
        for day, b in sorted(rows.items())[-MAX_DAYS:]:
            if not isinstance(b, dict):
                continue
            _days[day] = {
                "views": int(b.get("views", 0)),
                "bot_views": int(b.get("bot_views", 0)),
                "visitors": list(b.get("visitors", []))[:MAX_VISITORS_PER_DAY],
                "paths": dict(b.get("paths", {})),
                "referrers": dict(b.get("referrers", {})),
            }


def reset() -> None:
    """Test seam."""
    global _salt_day
    with _lock:
        _days.clear()
        _salt_day = ""
