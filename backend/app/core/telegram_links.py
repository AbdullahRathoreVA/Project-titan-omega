"""Subscribers' Telegram chats, linked to Titan's bot with a one-time code.

HF blocks api.telegram.org, so the bot runs through a Cloudflare Worker that
forwards each message to /api/telegram/handle and sends the reply back (see
TELEGRAM_SETUP.md). Subscribers can't run their own bot through that, so they
share Titan's: their cockpit shows a link with a one-time code
(t.me/<bot>?start=<code>), and from then on their chat is answered from their
own workspace.

- A code lasts ten minutes and works once.
- A chat belongs to one account; linking it again moves it.
- The founder's chat (TELEGRAM_CHAT_ID) is never linked to a subscriber.
- Each subscriber's command log is kept here, separate from the founder's.

Titan can't send messages out on its own, so there are no notifications:
subscribers ask (/status, /decision, ...) and get an answer.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Optional

CODE_TTL = 600
MAX_LOG = 50

_lock = threading.RLock()
_links: dict[str, str] = {}                     # chat id -> account email
_codes: dict[str, tuple[str, float]] = {}       # code -> (email, issued at)
_logs: dict[str, list] = {}                     # email -> their command log


def bot_username() -> str:
    """Titan's bot, without the @. Empty until the founder sets it."""
    return os.getenv("TITAN_TELEGRAM_BOT", "").strip().lstrip("@")


def new_code(email: str) -> dict:
    """A fresh one-time code for this account, replacing any earlier one."""
    code = f"{secrets.randbelow(10 ** 8):08d}"
    with _lock:
        for old in [c for c, (e, _) in _codes.items() if e == email]:
            _codes.pop(old, None)
        _codes[code] = (email, time.time())
    bot = bot_username()
    return {"code": code, "expires_in": CODE_TTL,
            "url": f"https://t.me/{bot}?start={code}" if bot else ""}


def redeem(chat_id: str, code: str) -> Optional[str]:
    """Link this chat to the account the code was issued to.

    Returns None for an unknown or expired code, or for the founder's own chat.
    """
    founder_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id or (founder_chat and str(chat_id) == founder_chat):
        return None
    with _lock:
        entry = _codes.pop((code or "").strip(), None)
        if not entry or time.time() - entry[1] > CODE_TTL:
            return None
        email = entry[0]
        for chat in [c for c, e in _links.items() if e == email]:
            _links.pop(chat, None)                 # one chat per account
        _links[str(chat_id)] = email
        return email


def account_for(chat_id: str) -> Optional[str]:
    with _lock:
        return _links.get(str(chat_id))


def is_linked(email: str) -> bool:
    with _lock:
        return email in _links.values()


def unlink(email: str) -> bool:
    with _lock:
        chats = [c for c, e in _links.items() if e == email]
        for chat in chats:
            _links.pop(chat, None)
        return bool(chats)


def log(email: str, entry: dict) -> None:
    with _lock:
        rows = _logs.setdefault(email, [])
        rows.append(entry)
        del rows[:-MAX_LOG]


def history(email: str, limit: int = 50) -> list:
    with _lock:
        return list(reversed(_logs.get(email, [])[-max(1, min(limit, MAX_LOG)):]))


def export_state() -> dict:
    """Links and logs survive a restart; codes don't (they only last ten minutes)."""
    with _lock:
        return {"links": dict(_links), "logs": {e: list(v) for e, v in _logs.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    with _lock:
        links = data.get("links")
        if isinstance(links, dict):
            _links.clear()
            _links.update({str(k): v for k, v in links.items() if isinstance(v, str)})
        logs = data.get("logs")
        if isinstance(logs, dict):
            _logs.clear()
            _logs.update({e: v[-MAX_LOG:] for e, v in logs.items() if isinstance(v, list)})


def reset() -> None:
    """Test seam."""
    with _lock:
        _links.clear()
        _codes.clear()
        _logs.clear()
