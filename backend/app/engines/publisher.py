"""Publishing pipeline: scheduled posts, delivered through an automation webhook.

Posting through password bots gets accounts banned, so Titan goes through an
approved route instead:

    Titan -> webhook -> Zapier / Make / Buffer -> the platforms

Connect the platforms once inside Zapier, Make or Buffer (their OAuth, never
a password given to Titan), set the automation's catch-hook URL as
TITAN_PUBLISH_WEBHOOK, and Titan sends each scheduled post to it.

Without a webhook, posts wait in a ready-to-publish queue (status "queued")
to be posted by hand.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from ..store import STORE, Store, now

# Channels Titan can target; delivery itself happens in the automation.
KNOWN_CHANNELS = ["linkedin", "facebook", "pinterest", "instagram", "twitter"]


def _webhook_url() -> Optional[str]:
    return os.getenv("TITAN_PUBLISH_WEBHOOK")


def schedule(
    content: str,
    channels: List[str],
    image_url: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
    agent_id: str = "marketing-social-media-manager",
    store: Store = STORE,
) -> dict:
    """Queue a post for one or more channels, optionally at a future time."""
    chans = [c for c in channels if c in KNOWN_CHANNELS] or ["linkedin"]
    post = {
        "id": store.new_id("post"),
        "content": content,
        "channels": chans,
        "image_url": image_url,
        "agent_id": agent_id,
        "scheduled_at": scheduled_at or now(),
        "status": "scheduled",
        "results": [],
        "created_at": now(),
    }
    store.posts[post["id"]] = post
    store.emit(
        agent_id,
        "publish",
        f"Scheduled post to {', '.join(chans)} for {post['scheduled_at'].isoformat()}.",
        "info",
    )
    return post


def publish(post_id: str, store: Store = STORE) -> dict:
    """Send a post to its channels now, via the configured automation webhook."""
    post = store.posts[post_id]  # KeyError handled by caller
    from ..core import cockpit_scope
    # The webhook posts to the founder's own accounts. A subscriber's post never
    # goes through it; it stays queued for them to post themselves.
    customer = cockpit_scope.is_customer()
    url = None if customer else _webhook_url()

    if not url:
        post["status"] = "queued"
        post["results"] = [
            {"channel": c, "status": "ready",
             "detail": ("Copy it and post it yourself - Titan does not post to your accounts."
                        if customer else "Set TITAN_PUBLISH_WEBHOOK to auto-post.")}
            for c in post["channels"]
        ]
        store.emit(
            post["agent_id"], "publish",
            f"Post ready for {', '.join(post['channels'])} (no webhook set — publish manually).",
            "warn",
        )
        return post

    payload = {
        "source": "titan-omega",
        "content": post["content"],
        "channels": post["channels"],
        "image_url": post["image_url"],
        "scheduled_at": post["scheduled_at"].isoformat(),
    }
    try:
        import httpx

        with httpx.Client(timeout=10.0, trust_env=True) as client:
            resp = client.post(url, json=payload)
        ok = 200 <= resp.status_code < 300
        post["status"] = "published" if ok else "failed"
        post["results"] = [
            {"channel": c, "status": "published" if ok else "failed",
             "detail": f"webhook HTTP {resp.status_code}"}
            for c in post["channels"]
        ]
        store.emit(
            post["agent_id"], "publish",
            f"{'Published to' if ok else 'Failed publishing to'} "
            f"{', '.join(post['channels'])} via automation webhook.",
            "success" if ok else "critical",
        )
    except Exception as exc:  # network or automation down: keep it queued
        post["status"] = "queued"
        post["results"] = [{"channel": c, "status": "ready", "detail": str(exc)}
                           for c in post["channels"]]
        store.emit(post["agent_id"], "publish",
                   f"Webhook unreachable; post re-queued for {', '.join(post['channels'])}.",
                   "warn")
    return post


def due(store: Store = STORE) -> List[dict]:
    """Scheduled posts whose time has come and that haven't gone out yet."""
    t = datetime.now(timezone.utc)
    return [
        p for p in store.posts.values()
        if p["status"] == "scheduled" and p["scheduled_at"] <= t
    ]


def run_due(store: Store = STORE) -> int:
    """Publish everything that's due. Called on the heartbeat."""
    count = 0
    for post in due(store):
        publish(post["id"], store)
        count += 1
    return count


def listing(store: Store = STORE) -> List[dict]:
    return sorted(store.posts.values(), key=lambda p: p["scheduled_at"], reverse=True)
