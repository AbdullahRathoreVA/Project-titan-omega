"""Telegram Command Center — command Titan from your phone, 100% free.

Uses the official (free) Telegram Bot API via long-polling on the heartbeat, so
it works on HF Spaces with no webhook/public-URL setup. Configure with:

  TELEGRAM_BOT_TOKEN  — from @BotFather (free, 2 minutes)
  TELEGRAM_CHAT_ID    — your chat id; when set, ONLY that chat can command
                        Titan (strongly recommended). Send /start to the bot
                        and the id shows up in the dashboard log.

Commands: /status /revenue /agents /opportunities /report /news /search <q>
/ask <q> /nextpost /approve /help. Unknown text is treated as /ask.
Every command + reply is logged to STORE.telegram_log for the dashboard page.
"""

from __future__ import annotations

import os
from typing import List, Optional

from ..connectors.github import _verify
from ..core import executive, llm, model_router
from ..store import STORE, Store, now
from . import news, opportunity, publisher, research

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 3900  # Telegram hard limit is 4096; leave headroom.


def _token() -> str:
    """Bot token with whitespace stripped — a newline pasted into the HF secret
    otherwise lands inside the request URL and breaks every API call silently."""
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def configured() -> bool:
    return bool(_token())


def send_to_founder(text: str, store: Store = STORE) -> bool:
    """Push a message to Abdullah's own chat (needs TELEGRAM_CHAT_ID). Never raises."""
    token = _token()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat):
        return False
    try:
        _send(token, int(chat), text)
        return True
    except (ValueError, TypeError):
        return False


def _send(token: str, chat_id: int, text: str) -> None:
    try:
        import httpx

        with httpx.Client(timeout=10.0, verify=_verify(), trust_env=True) as c:
            c.post(API.format(token=token, method="sendMessage"),
                   json={"chat_id": chat_id, "text": text[:MAX_LEN]})
    except Exception:
        pass


# --- command handlers -------------------------------------------------------

def _fmt_status(store: Store) -> str:
    s = executive.empire_status(store)
    return (
        f"🏢 TITAN STATUS\n"
        f"Revenue earned: ${s['mrr']:.2f}\n"
        f"Agents active: {s['active_agents']}/{s['total_agents']}\n"
        f"Open opportunities: {s['open_opportunities']}\n"
        f"Actions in flight: {s['actions_in_flight']}\n"
        f"Empire health: {s['health']:.0f}/100"
    )


def _fmt_revenue(store: Store) -> str:
    m = store.metrics
    lines = [
        f"💰 REVENUE — total ${m.get('mrr', 0.0):.2f}",
        f"Upwork: ${m.get('fiverr_revenue', 0.0):.2f} ({int(m.get('fiverr_orders', 0))} orders)",
        f"Career Mind: ${m.get('cm_revenue', 0.0):.2f}",
        f"Kindle: ${m.get('kindle_royalties', 0.0):.2f}",
        f"Other: ${m.get('other_revenue', 0.0):.2f}",
    ]
    recent = list(reversed(store.revenue_entries))[:3]
    if recent:
        lines.append("Recent:")
        lines += [f"• +${e['amount']:.2f} {e['source']} — {e.get('note','')[:40]}" for e in recent]
    return "\n".join(lines)


def _fmt_agents(store: Store) -> str:
    heads = [r for r in store.agents.values() if r.spec.is_head][:8]
    active = sum(1 for a in store.agents.values() if a.status.value == "working")
    lines = [f"🤖 AGENTS — {active}/{len(store.agents)} working"]
    lines += [f"• {r.spec.name}: {r.current_task or r.spec.mission[:50]}" for r in heads]
    return "\n".join(lines)


def _fmt_opps(store: Store) -> str:
    opps = opportunity.ranked(store)[:5]
    if not opps:
        return "No open opportunities — send /report or scan from the dashboard."
    lines = ["🎯 TOP OPPORTUNITIES"]
    lines += [
        f"{i}. {o['title']} (~${o['expected_revenue']:,.0f}, priority {o['priority_score']:.0f})"
        for i, o in enumerate(opps, 1)
    ]
    return "\n".join(lines)


def _fmt_report(store: Store) -> str:
    s = executive.empire_status(store)
    brief = llm.complete(
        task=model_router.FORMAT_REPORT,
        system=(
            "You are Titan, Abdullah's AI chief of staff. Write a compact weekly report "
            "for Telegram (max 12 short lines): earnings, agent activity, top 3 focus "
            "moves for this week. Address him simply as 'Abdullah'. Plain text, no markdown."
        ),
        prompt=(
            f"Revenue ${s['mrr']:.2f}; {s['active_agents']}/{s['total_agents']} agents active; "
            f"{s['open_opportunities']} open opportunities; health {s['health']:.0f}."
        ),
        max_tokens=400,
    )
    return brief or _fmt_status(store)


def _fmt_news(arg: str) -> str:
    heads = news.fetch_headlines(arg or "AI careers OR freelancing OR edtech", 5)
    if not heads:
        return "Couldn't fetch news right now — try again in a minute."
    return "📰 LATEST\n" + "\n".join(f"• {h['title']}" for h in heads)


def _fmt_search(arg: str) -> str:
    if not arg:
        return "Usage: /search <what to find>"
    results = research.search(arg, 5)
    if not results:
        return "No live results (is TAVILY_API_KEY set?). Try again."
    return "🔎 RESULTS\n" + "\n\n".join(f"• {r['title']}\n{r['url']}" for r in results)


def _fmt_ask(arg: str, store: Store) -> str:
    if not arg:
        return "Usage: /ask <your question>"
    s = executive.empire_status(store)
    ans = llm.complete(
        task=model_router.FORMAT_ANSWER,
        system=(
            "You are Titan, Abdullah's AI chief of staff, replying on Telegram. Address "
            "him simply as 'Abdullah'. Be concise (max 8 lines), concrete, plain text. "
            f"Live data: revenue ${s['mrr']:.2f}, {s['active_agents']}/{s['total_agents']} "
            f"agents active, {s['open_opportunities']} opportunities."
        ),
        prompt=arg,
        max_tokens=400,
    )
    return ans or "The AI brain is unreachable right now (check /api/llm/health)."


def _fmt_nextpost(store: Store) -> str:
    from ..api.actions import _build_next_post

    if not store.next_post:
        store.next_post = _build_next_post("", "en", "auto", store)
    p = store.next_post
    return (
        f"🖼 NEXT POST ({p['target']})\n\n{p['caption']}\n\nImage: {p['image_url']}\n\n"
        "Send /approve to schedule it."
    )


def _fmt_decision(store: Store) -> str:
    d = store.pending_decision
    if not d:
        return "No war-room decision waiting. Run a debate from the dashboard (War Room tab)."
    return (
        f"⚔️ PENDING DECISION\nGoal: {d['goal']}\n\n{d['decision']}\n\n"
        "Send /approveplan to lock it in as this week's plan."
    )


def _fmt_approveplan(store: Store) -> str:
    d = store.pending_decision
    if not d:
        return "Nothing to approve — run a war-room debate first."
    from . import deliverables

    deliverables.generate(
        "growth_strategy",
        f"APPROVED war-room plan for: {d['goal']}\n\n{d['decision']}",
        "marketing-head",
        store=store,
    )
    store.pending_decision = None
    store.emit("marketing-head", "decision",
               "✅ Founder approved the war-room plan via Telegram — saved to Deliverables.",
               "success")
    return "✅ Approved. The plan is saved in Deliverables and the marketing team is on it."


def _fmt_approve(store: Store) -> str:
    from ..api.actions import _build_next_post

    post = store.next_post or _build_next_post("", "en", "auto", store)
    scheduled = publisher.schedule(
        post["caption"], post.get("channels", ["linkedin"]), post.get("image_url"), None, store=store
    )
    store.next_post = _build_next_post("", "en", "auto", store)
    return f"✅ Post scheduled to {', '.join(scheduled['channels'])}. A fresh draft is ready — /nextpost to see it."


_HELP = (
    "🤖 TITAN COMMANDS\n"
    "/status — empire snapshot\n"
    "/revenue — earnings breakdown\n"
    "/agents — who's working on what\n"
    "/opportunities — top ranked opportunities\n"
    "/report — weekly report\n"
    "/news [topic] — live headlines\n"
    "/search <query> — live web search\n"
    "/ask <question> — ask Titan anything\n"
    "/nextpost — preview the next social post\n"
    "/approve — schedule the next post\n"
    "/decision — pending war-room decision\n"
    "/approveplan — approve that decision\n"
    "Plain text = /ask."
)


def _handle(text: str, store: Store) -> str:
    t = (text or "").strip()
    low = t.lower()
    cmd, _, arg = t.partition(" ")
    cmd = cmd.lower().split("@")[0]  # strip @botname suffix in groups
    arg = arg.strip()

    if cmd in ("/start", "/help"):
        return _HELP
    if cmd == "/status":
        return _fmt_status(store)
    if cmd == "/revenue":
        return _fmt_revenue(store)
    if cmd == "/agents":
        return _fmt_agents(store)
    if cmd in ("/opportunities", "/opps"):
        return _fmt_opps(store)
    if cmd in ("/report", "/weekly_report"):
        return _fmt_report(store)
    if cmd == "/news":
        return _fmt_news(arg)
    if cmd in ("/search", "/research"):
        return _fmt_search(arg)
    if cmd == "/ask":
        return _fmt_ask(arg, store)
    if cmd == "/nextpost":
        return _fmt_nextpost(store)
    if cmd == "/approve":
        return _fmt_approve(store)
    if cmd == "/decision":
        return _fmt_decision(store)
    if cmd == "/approveplan":
        return _fmt_approveplan(store)
    if low.startswith("/"):
        return "Unknown command.\n\n" + _HELP
    return _fmt_ask(t, store)


# --- polling loop (called from the heartbeat) --------------------------------

def poll_once(store: Store = STORE) -> int:
    """Fetch and answer pending Telegram messages. Returns handled count."""
    token = _token()
    if not token:
        return 0

    try:
        import httpx

        with httpx.Client(timeout=12.0, verify=_verify(), trust_env=True) as c:
            resp = c.get(
                API.format(token=token, method="getUpdates"),
                params={"offset": store.telegram_offset + 1, "timeout": 0, "limit": 5},
            )
        if resp.status_code != 200:
            return 0
        updates = resp.json().get("result", [])
    except Exception:
        return 0

    allowed = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    handled = 0
    for u in updates:
        store.telegram_offset = max(store.telegram_offset, int(u.get("update_id", 0)))
        msg = u.get("message") or u.get("edited_message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        text = msg.get("text") or ""
        sender = (msg.get("from") or {}).get("first_name", "?")
        if chat_id is None or not text:
            continue

        # A subscriber's link attempt or linked chat never reaches the
        # founder's handler below - it is answered from their own workspace.
        from . import telegram_subscribers
        theirs = telegram_subscribers.handle(chat_id, text, sender)
        if theirs is not None:
            _send(token, chat_id, theirs)
            handled += 1
            continue

        if allowed and str(chat_id) != allowed:
            _send(token, chat_id, "⛔ This bot answers linked Titan accounts only. If you "
                                  "have one, open the Telegram tab in your Titan cockpit "
                                  "to link this chat.")
            store.telegram_log.append({
                "time": now().isoformat(), "from": sender, "chat_id": chat_id,
                "command": text[:120], "reply": "(blocked — not the allowed chat id)",
            })
            continue

        try:
            reply = _handle(text, store)
        except Exception as exc:
            reply = f"Something went wrong handling that: {type(exc).__name__}"
        _send(token, chat_id, reply)
        handled += 1

        store.telegram_log.append({
            "time": now().isoformat(), "from": sender, "chat_id": chat_id,
            "command": text[:120], "reply": reply[:300],
        })
        store.emit("telegram-center", "command", f"Telegram: {sender} → {text[:60]}", "info")

    if len(store.telegram_log) > 200:
        store.telegram_log = store.telegram_log[-200:]
    return handled


def status(store: Store = STORE) -> dict:
    return {
        "configured": configured(),
        "locked": bool(os.getenv("TELEGRAM_CHAT_ID", "").strip()),
        "handled": len(store.telegram_log),
    }
