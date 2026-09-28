"""Per-client news watch, on the heartbeat.

Uses Google News RSS: no key, no quota, no cost. (GNews, Currents and
MarketAux all need a key and cap the free tier; GNews is wired as an
optional extra for sentiment tagging.)

Three watches per client:

  brand       Is anyone talking about this business? The most time-critical.
  industry    What happened in their trade today that they could post about?
  local       Industry news in their city - what converts for a local business.

Nothing is posted. This produces post angles; a person approves and sends
them.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from ..core import events
from . import news

# Every three hours: day-old news isn't worth posting about, and each client
# costs three cheap RSS requests per cycle.
INTERVAL = 3 * 3600
# Per cycle, so a large portfolio doesn't stall the heartbeat.
MAX_CLIENTS_PER_CYCLE = 4
MAX_STORED = 12

_lock = threading.RLock()
_watch: dict[str, dict] = {}       # client_id -> {items, checked_at}
_cursor = 0


def _queries(rec: dict) -> list:
    """(kind, query) pairs. Empty fields are skipped - searching for an empty
    string returns everything.
    """
    name = (rec.get("business_name") or "").strip()
    industry = (rec.get("industry") or "").strip()
    city = (rec.get("city") or "").strip()
    out = []
    if name:
        out.append(("brand", f'"{name}"'))
    if industry:
        out.append(("industry", industry))
    if industry and city:
        out.append(("local", f"{industry} {city}"))
    return out


def _angle(kind: str, title: str, business: str) -> str:
    """Why this headline matters to this business, in one line.

    Template-based so it works without an LLM, and so it never gets the client's
    own trade wrong.
    """
    if kind == "brand":
        return (f"Direct mention of {business}. Read it before the client does "
                f"— a bad one is time-critical and a good one is a post.")
    if kind == "local":
        return ("Local trade news. Posting about something happening in their "
                "own city is the angle most likely to be seen by a buyer there.")
    return ("Industry development. A short post taking a position on this "
            "shows expertise without needing anything new to announce.")


def check_client(client_id: str, rec: Optional[dict] = None) -> dict:
    """Run the three watches for one client. Never raises."""
    from ..core import clients

    rec = rec or clients.get(client_id) or {}
    if not rec:
        return {"ok": False, "error": "Client not found"}

    business = rec.get("business_name", "")
    seen: set = set()
    items: list = []
    for kind, query in _queries(rec):
        try:
            for h in news.fetch_headlines(query, limit=4):
                title = (h.get("title") or "").strip()
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                items.append({
                    "kind": kind,
                    "title": title[:220],
                    "url": h.get("link") or h.get("url") or "",
                    "source": h.get("source") or "",
                    "published": h.get("published") or "",
                    "angle": _angle(kind, title, business),
                })
        except Exception:
            continue          # one failed query shouldn't lose the others

    # Brand mentions first - they're the time-critical ones.
    order = {"brand": 0, "local": 1, "industry": 2}
    items.sort(key=lambda i: order.get(i["kind"], 9))
    items = items[:MAX_STORED]

    snapshot = {"ok": True, "client_id": client_id, "business": business,
                "checked_at": time.time(), "items": items,
                "brand_mentions": sum(1 for i in items if i["kind"] == "brand")}
    with _lock:
        _watch[client_id] = snapshot

    if snapshot["brand_mentions"]:
        events.emit(events.KNOWLEDGE_INDEXED, {
            "client": business, "brand_mentions": snapshot["brand_mentions"],
        }, actor="news-watch", severity="warn")
    return snapshot


def cycle() -> int:
    """Heartbeat entry point. Round-robin, so every client gets reached."""
    global _cursor
    from ..core import clients

    rows = [c for c in clients.all_clients() if c.get("business_name")]
    if not rows:
        return 0

    now = time.time()
    due = []
    with _lock:
        for c in rows:
            last = (_watch.get(c["id"]) or {}).get("checked_at", 0)
            if now - last >= INTERVAL:
                due.append(c)
    if not due:
        return 0

    # Round-robin rather than always starting at the top, or clients past
    # MAX_CLIENTS_PER_CYCLE would never be checked.
    _cursor = _cursor % len(due)
    batch = (due + due)[_cursor:_cursor + MAX_CLIENTS_PER_CYCLE]
    _cursor = (_cursor + len(batch)) % max(1, len(due))

    done = 0
    for c in batch:
        try:
            check_client(c["id"], c)
            done += 1
        except Exception:
            continue
    return done


def summary() -> dict:
    with _lock:
        rows = [dict(v) for v in _watch.values()]
    rows.sort(key=lambda r: -r.get("checked_at", 0))
    total_brand = sum(r.get("brand_mentions", 0) for r in rows)
    return {
        "clients_watched": len(rows),
        "brand_mentions": total_brand,
        "interval_hours": round(INTERVAL / 3600, 1),
        "recent": rows[:8],
        "source": "Google News RSS — no API key, no quota, no bill.",
        "note": ("Nothing here is posted automatically. These are angles; a "
                 "human approves and sends. An auto-posted mistake, or a "
                 "platform ban, ends the service a client is paying for."),
    }


def for_client(client_id: str) -> dict:
    with _lock:
        return dict(_watch.get(client_id) or {"ok": False,
                                              "error": "Not checked yet"})


def reset() -> None:
    with _lock:
        _watch.clear()
