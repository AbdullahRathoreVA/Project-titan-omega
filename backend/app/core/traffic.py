"""Website visitor analytics with no third party and no cost.

Google Analytics would mean a third-party script, a GDPR consent banner (the
market is the EU) and another account. This counts visits in-process instead:
no script, no cookie, no vendor, no bill.

Privacy shapes the design. A raw IP address is personal data under GDPR, and
Titan sells compliance, so:

- The IP is never stored. It's hashed with the user agent and a salt that
  changes every day, so ids can't link a person across days. The trade-off:
  unique visitors is a per-day figure only, and the report doesn't sum daily
  uniques into a bigger, wrong number.
- Referrers are reduced to a host before storage, since the full URL can
  carry personal data in its query string.
- Only HTML page loads are counted; counting asset and API requests would
  turn one visit into thirty.

Obvious crawlers are counted separately from human traffic, since a bot
isn't a potential signup.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import time
from typing import Optional

# 90 days of daily buckets is a few KB. The per-day visitor sets are the only
# thing that can grow, and they're capped.
MAX_DAYS = 90
MAX_VISITORS_PER_DAY = 20_000

# Substrings that identify a non-human client. Conservative, because a false
# positive silently removes a real visitor from the funnel.
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
    """A salt that rotates daily. Yesterday's ids can't be recomputed, so stored
    hashes can't be used to follow anyone over time.
    """
    global _salt_day, _salt
    with _lock:
        if _salt_day != day:
            _salt_day = day
            # Through core/appsecret.py like every other reader, so a test can assert
            # that only one module reads TITAN_SECRET from the environment. The random
            # half already carries the entropy.
            from . import appsecret
            _salt = appsecret.value() + secrets.token_hex(16)
        return _salt


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in BOT_MARKERS)


_MOBILE = re.compile(r"iphone|android.*mobile|windows phone|ipod", re.I)
_TABLET = re.compile(r"ipad|android(?!.*mobile)|tablet", re.I)
# Order matters: an iPhone announces itself as "like Mac OS X", so iOS has to
# be tested before macOS or every iPhone is filed as a Mac.
_OS = (("Windows", re.compile(r"windows nt", re.I)),
       ("iOS", re.compile(r"iphone|ipad|ipod", re.I)),
       ("Android", re.compile(r"android", re.I)),
       ("macOS", re.compile(r"mac os x|macintosh", re.I)),
       ("Linux", re.compile(r"linux|x11", re.I)))
# Order matters: Edge and Chrome both claim "Chrome", Chrome claims "Safari".
_BROWSER = (("Edge", re.compile(r"edg[ea]?/", re.I)),
            ("Opera", re.compile(r"opr/|opera", re.I)),
            ("Samsung", re.compile(r"samsungbrowser", re.I)),
            ("Firefox", re.compile(r"firefox/", re.I)),
            ("Chrome", re.compile(r"chrome/|crios/", re.I)),
            ("Safari", re.compile(r"safari/", re.I)))


def device_of(user_agent: str) -> dict:
    """Device class, OS and browser from the user agent.

    Deliberately coarse: "Android phone, Chrome" describes a category, not a
    person. Anything finer would be fingerprinting.
    """
    ua = user_agent or ""
    kind = ("mobile" if _MOBILE.search(ua) else
            "tablet" if _TABLET.search(ua) else
            "desktop" if ua else "unknown")
    os_name = next((n for n, rx in _OS if rx.search(ua)), "unknown")
    browser = next((n for n, rx in _BROWSER if rx.search(ua)), "unknown")
    return {"kind": kind, "os": os_name, "browser": browser}


def _bucket(day: str) -> dict:
    b = _days.get(day)
    if b is None:
        b = {"views": 0, "bot_views": 0, "visitors": [], "paths": {},
             "referrers": {}, "devices": {}, "os": {}, "browsers": {},
             "countries": {}, "hours": {}}
        _days[day] = b
        if len(_days) > MAX_DAYS:
            for stale in sorted(_days)[:len(_days) - MAX_DAYS]:
                del _days[stale]
    return b


def record(path: str, ip: str = "", user_agent: str = "",
           referrer: str = "", country: str = "") -> None:
    """Count one page load. Never raises - a counter mustn't be able to take
    down the page it's counting.
    """
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

            d = device_of(user_agent)
            for key, val in (("devices", d["kind"]), ("os", d["os"]),
                             ("browsers", d["browser"])):
                b[key][val] = b[key].get(val, 0) + 1

            # Country only, from Cloudflare's CF-IPCountry header, so no IP database
            # and no stored IP. City-level location would need the address itself; a
            # country is a market, a city plus a device is a person.
            cc = (country or "").strip().upper()[:2]
            if cc and cc.isalpha():
                b["countries"][cc] = b["countries"].get(cc, 0) + 1

            # Hour of day in UTC, for "when do people actually open it".
            hour = time.strftime("%H", time.gmtime())
            b["hours"][hour] = b["hours"].get(hour, 0) + 1
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
    """Traffic, and what it can and can't tell you."""
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
        rolled: dict[str, dict[str, int]] = {
            "devices": {}, "os": {}, "browsers": {}, "countries": {}, "hours": {}}
        for d in wanted:
            for k, v in _days[d]["paths"].items():
                paths[k] = paths.get(k, 0) + v
            for k, v in _days[d]["referrers"].items():
                referrers[k] = referrers.get(k, 0) + v
            for group in rolled:
                for k, v in _days[d].get(group, {}).items():
                    rolled[group][k] = rolled[group].get(k, 0) + v
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
        "devices": dict(sorted(rolled["devices"].items(), key=lambda kv: -kv[1])),
        "operating_systems": dict(sorted(rolled["os"].items(), key=lambda kv: -kv[1])),
        "browsers": dict(sorted(rolled["browsers"].items(), key=lambda kv: -kv[1])),
        "countries": dict(sorted(rolled["countries"].items(),
                                 key=lambda kv: -kv[1])[:20]),
        "busiest_hours_utc": dict(sorted(rolled["hours"].items())),
        "signups_total": signups,
        # Stated explicitly: this was asked for and can't be provided.
        "not_collected": {
            "phone_number": ("A website visit carries no phone number. "
                             "Nothing in a browser exposes one, and no "
                             "analytics product can supply it. The only way "
                             "to get a phone number is for someone to type "
                             "it into a form."),
            "street_or_city": ("Country only. City-level location needs the "
                               "IP address itself, which Titan does not "
                               "store — a city plus a device fingerprint "
                               "identifies a person."),
            "identity": ("Visitors are counted, never identified. The visitor "
                         "id is a hash with a salt that rotates every 24h."),
        },
        # Not a visitors-to-signups percentage. Unique visitors is a per-day figure
        # (the salt rotates daily), so there's no total to divide by.
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
                             "referrers": dict(b["referrers"]),
                             "devices": dict(b.get("devices", {})),
                             "os": dict(b.get("os", {})),
                             "browsers": dict(b.get("browsers", {})),
                             "countries": dict(b.get("countries", {})),
                             "hours": dict(b.get("hours", {}))}
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
                # Absent in state files written before device/country tracking.
                "devices": dict(b.get("devices", {})),
                "os": dict(b.get("os", {})),
                "browsers": dict(b.get("browsers", {})),
                "countries": dict(b.get("countries", {})),
                "hours": dict(b.get("hours", {})),
            }


def reset() -> None:
    """Test seam."""
    global _salt_day
    with _lock:
        _days.clear()
        _salt_day = ""
