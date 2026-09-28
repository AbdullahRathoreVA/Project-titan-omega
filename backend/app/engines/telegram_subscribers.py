"""Telegram messages from subscribers, before the founder's handler sees them.

Titan's bot answers two kinds of chat: the founder's, from his data, and a
subscriber's linked chat, from their workspace (core/telegram_links.py). Both
ways a message arrives - the Cloudflare relay (/api/telegram/handle) and
direct polling (telegram_bot.poll_once, where Telegram is reachable) - call
`handle` first, so a subscriber's chat can never fall through to the
founder's handler and his data.

Every answer here is deterministic: a chat cannot spend a subscriber's AI
answers.
"""

from __future__ import annotations

from typing import Optional

from ..core import ratelimit, telegram_links
from ..store import now

HELP = (
    "Your Titan workspace on Telegram:\n"
    "/status - businesses, leads, sales and plan\n"
    "/revenue - your latest logged sales\n"
    "/leads - your pipeline\n"
    "/decision - your latest War Room plan\n"
    "/unlink - disconnect this chat"
)


def handle(chat_id, text: str, sender: str = "") -> Optional[str]:
    """The reply for a link attempt or a linked subscriber's chat, or None
    when the message is not theirs and the founder's handler should run."""
    chat = str(chat_id)
    parts = (text or "").strip().split()

    # "/start <code>" from the t.me link in their cockpit, or "/link <code>"
    # typed by hand. Attempts are limited per chat, so codes cannot be guessed.
    if (len(parts) == 2 and parts[1].isdigit()
            and parts[0].lower().split("@")[0] in ("/start", "/link")):
        limited = ratelimit.check("login", f"telegram:{chat}")
        if not limited["allowed"]:
            return "Too many tries. Wait a few minutes, then use a fresh code from your cockpit."
        email = telegram_links.redeem(chat, parts[1])
        if not email:
            return ("That code is not valid or has expired. Open the Telegram tab in "
                    "your Titan cockpit for a new one.")
        reply = "✅ Linked to your Titan workspace.\n\n" + HELP
        _log(email, chat, sender, "/start", reply)
        _save()
        return reply

    email = telegram_links.account_for(chat)
    if not email:
        return None
    reply = _answer(email, text)
    _log(email, chat, sender, text, reply)
    return reply


def _save() -> None:
    """A link must survive a restart the moment it is made."""
    from .. import persistence
    persistence.save()


def _log(email: str, chat: str, sender: str, command: str, reply: str) -> None:
    telegram_links.log(email, {"time": now().isoformat(), "from": sender or "?",
                               "chat_id": chat, "command": (command or "")[:120],
                               "reply": reply[:300]})


def _answer(email: str, text: str) -> str:
    """A linked subscriber's command, from their own workspace."""
    from ..core import billing, clients, crm, workspaces
    from ..store import founder_store

    cmd = ((text or "").strip().split() or [""])[0].lower().split("@")[0]
    ws = workspaces.for_account(email)
    if cmd == "/unlink":
        telegram_links.unlink(email)
        _save()
        return "This chat is no longer linked to your Titan workspace."
    if cmd == "/status":
        acct = billing.public(email)
        n = len([c for c in billing.owned_clients(email) if clients.get(c)])
        k = len(crm.visible_to(founder_store().leads, email))
        calls = (acct.get("limits") or {}).get("ai_calls_per_month")
        used = (acct.get("usage") or {}).get("ai_calls", 0)
        return (f"Plan: {acct.get('plan_name', 'Free')}\n"
                f"Businesses: {n}\nLeads: {k}\n"
                f"Sales logged: ${float(ws.metrics.get('mrr', 0) or 0):,.2f}\n"
                f"AI answers this month: {used}"
                + ("" if calls in (None, -1) else f" of {calls}"))
    if cmd == "/revenue":
        rows = ws.revenue_entries[-3:]
        if not rows:
            return "No sales logged yet. Log them in the Finance tab or on your dashboard."
        lines = [f"+${float(r.get('amount', 0)):,.2f} {r.get('source', '')} "
                 f"{r.get('note', '')}".strip() for r in reversed(rows)]
        return (f"Total logged: ${float(ws.metrics.get('mrr', 0) or 0):,.2f}\n"
                + "\n".join(lines))
    if cmd == "/leads":
        leads = crm.visible_to(founder_store().leads, email)
        if not leads:
            return "Your CRM is empty. Add leads in the CRM tab."
        counts: dict[str, int] = {}
        for lead in leads:
            status = lead.get("status", "new")
            counts[status] = counts.get(status, 0) + 1
        return "Your pipeline: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    if cmd == "/decision":
        if not ws.decisions:
            return "No War Room plan yet. Run a debate in the War Room tab."
        last = ws.decisions[-1]
        return f"Goal: {last.get('goal', '')}\n\n{str(last.get('decision', ''))[:1500]}"
    return HELP
