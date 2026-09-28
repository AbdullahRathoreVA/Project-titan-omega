"""Endpoints where the agents take actions rather than just talk.

Mounted alongside the main router:
  * POST /api/agent/act     - perform a real in-app action.
  * POST /api/intel/news    - live headlines + market analysis.
  * POST /api/leads/find    - live web search -> concrete leads (Tavily).
  * GET  /api/content/daily - fresh caption + free AI image URL for auto-posting.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core import auth, demo_data, executive, llm, model_router, quota
from ..engines import deliverables, news, opportunity, owner, publisher, research
from ..store import STORE, Store, now

router = APIRouter(prefix="/api")

# The founder's Upwork profile. Override with the UPWORK_PROFILE_URL env var.
UPWORK_PROFILE_URL = "https://www.upwork.com/freelancers/~01afb00378bd38d964?mp_source=share"


# --- live news + market analysis ------------------------------------------

class NewsRequest(BaseModel):
    topic: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/intel/news", tags=["system"])
def intel_news(req: NewsRequest) -> dict:
    """Live headlines + AI market analysis for the founder's businesses, or for
    the subscriber's when called from their cockpit.
    """
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        main = businesses[0] if businesses else {}
        query = req.topic or " ".join(
            x for x in (main.get("industry"), main.get("city"), main.get("country")) if x
        ) or "small business marketing"
        analyst = (
            f"You are a market analyst for {owner.describe(businesses) or 'a small business'}. "
            "From today's real headlines, extract what matters for this business's "
            "marketing and sales, then give 3 concrete, zero-cost moves to capitalize "
            "THIS WEEK.")
    else:
        query = req.topic or (
            "AI career tools OR freelancing OR Upwork gig economy OR ed-tech students jobs"
        )
        analyst = (
            "You are a market analyst for Abdullah's Career Mind AI (a student "
            "career-guidance platform) and his Upwork AI service gigs. From today's "
            "real headlines, extract what matters for HIS marketing and earning, then "
            "give 3 concrete, zero-cost moves to capitalize THIS WEEK.")
    heads = news.fetch_headlines(query, 8)
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"

    if heads:
        head_text = "\n".join(f"- {h['title']}" for h in heads)
        analysis = llm.complete(
            system=f"{analyst} Write in {lang_name}.",
            prompt="Today's headlines:\n" + head_text,
            max_tokens=700,
        )
        content = (
            "📰 LATEST HEADLINES (live)\n"
            + head_text
            + "\n\n📈 ANALYSIS & MOVES\n"
            + (analysis or quota.no_answer_note(
                "(Set GROQ_API_KEY or Hermes to unlock AI analysis — free.)"))
        )
    else:
        content = (
            "Couldn't fetch live news right now (network blocked or rate-limited). "
            "Try again in a moment."
        )

    STORE.emit(
        "intelligence-studio", "discovery",
        f"Pulled {len(heads)} live headlines for market analysis.", "success",
    )
    return {"kind": "latest_news", "content": content, "headlines": heads}


# --- live lead finder (Tavily web search) ----------------------------------

class LeadRequest(BaseModel):
    query: str = Field(default="")
    lang: str = Field(default="en", description="'en' or 'ur'")


@router.post("/leads/find", tags=["system"])
def find_leads(req: LeadRequest) -> dict:
    """Search the live web for real leads, then format them into an action list.

    From a subscriber's cockpit the leads are customers for their own business,
    and each search counts against the War Room's hourly limit, since it uses
    the platform's search key.
    """
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        from .growth import limit_subscriber
        main = businesses[0] if businesses else {}
        trade = main.get("industry") or main.get("business_name") or ""
        place = " ".join(x for x in (main.get("city"), main.get("country")) if x)
        if not (req.query or trade):
            return {"kind": "leads", "live": False, "content": (
                "Add your business in the Clients tab, or type who you are "
                "looking for, and Titan searches for them.")}
        limit_subscriber()
        where = f" in {place}" if place else ""
        query = req.query or f"businesses and organisations{where} that buy from a {trade}"
        desc = owner.describe(businesses) or "a small business"
        analyst = (f"You are the lead-generation analyst for {desc}. From these LIVE web "
                   "results, extract concrete leads (organisations / people / places) the "
                   "owner can reach to win as customers.")
        offline = (f"You are the lead-generation analyst for {desc}. Give a concrete, "
                   "practical list of WHERE to find customers for this business — specific "
                   "communities, directories, search queries, and outreach angles.")
        offline_prompt = req.query or f"Find customers for {desc}."
    else:
        query = req.query or (
            "universities and colleges career services departments contact, "
            "and small businesses that need AI chatbots or automation"
        )
        analyst = (
            "You are Abdullah's lead-generation analyst. From these LIVE web results, "
            "extract concrete leads (organisations / people / places) he can reach to "
            "sell Career Mind AI (student career platform) or his Upwork AI gigs.")
        offline = (
            "You are Abdullah's lead-generation analyst. Give a concrete, practical list "
            "of WHERE to find buyers for Career Mind AI and his Upwork AI gigs — specific "
            "communities, directories, search queries, and outreach angles.")
        offline_prompt = req.query or "Find buyers for an AI career platform + Upwork AI services."
    lang_name = "Urdu (اردو)" if req.lang == "ur" else "English"
    results = research.search(query, 8)

    if results:
        src = "\n".join(f"- {r['title']} | {r['url']}\n  {r['content']}" for r in results)
        content = llm.complete(
            task=model_router.SCORE_LEADS,
            system=(
                f"{analyst} For "
                "each lead give: name, why they're a fit, where/how to contact, and a 1-line "
                f"opening message. Be specific and practical. Write in {lang_name}."
            ),
            prompt="Live web results:\n" + src,
            max_tokens=900,
        )
        content = (content or quota.no_answer_note("")) + "\n\n— Sources —\n" + "\n".join(
            f"• {r['url']}" for r in results
        )
        live = True
    else:
        content = llm.complete(
            system=f"{offline} Write in {lang_name}.",
            prompt=offline_prompt,
            max_tokens=700,
        ) or quota.no_answer_note(
            "Add a free TAVILY_API_KEY (tavily.com) in your Space to unlock LIVE lead search. "
            "For now: target university career-services pages, student Facebook groups, and "
            "r/jobs / r/resumes on Reddit."
        )
        live = False

    STORE.emit(
        "revenue-head", "discovery",
        f"Lead search ({'live' if live else 'offline'}): {query[:60]}", "success",
    )
    return {"kind": "leads", "content": content, "live": live}


# --- daily auto-content (caption + free AI image) for posting --------------

# Authentic, UGC-style photos tend to outperform polished studio ads ("ads
# that don't look like ads"), so these are mostly candid with one editorial.
_IMG_STYLES = [
    "authentic candid photo, shot on iPhone, natural window light, real environment, genuine unposed moment, true-to-life colors, sharp 4k detail, looks like a friend's photo not an ad",
    "candid documentary-style photograph, golden hour natural light, real person mid-action, authentic emotion, shallow depth of field, shot on 35mm lens, 4k, warm lifelike tones",
    "casual selfie-style photo, bright natural daylight, genuine happy expression, slightly imperfect framing, realistic skin texture, high resolution, feels real and relatable",
    "editorial lifestyle photograph, shot on Canon EOS R5 85mm f/1.4, soft natural light, crisp 4k, aspirational but authentic, magazine quality, real location",
]


def _pollinations(prompt: str) -> str:
    # Random seed per call so every image is new.
    seed = random.randint(1, 9_999_999)
    return (
        "https://image.pollinations.ai/prompt/"
        + quote(prompt)
        + f"?width=1080&height=1080&nologo=true&model=flux&enhance=true&seed={seed}"
    )


def _build_next_post(
    topic: str = "",
    lang: str = "en",
    target: str = "auto",
    store: Store = STORE,
) -> dict:
    """Generate one ready-to-post draft: caption + a free AI image.

    Shared by the daily auto-content endpoint and the HUD "Next Post" card.
    """
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        return _subscriber_next_post(businesses, topic, lang, store)
    cm = os.getenv("CAREERMIND_URL", "https://careermind2026-career-mind.hf.space")
    upwork = os.getenv("UPWORK_PROFILE_URL", UPWORK_PROFILE_URL).strip()
    # Titan is the product being marketed, so it's the default and needs no
    # configuration; TITAN_PRODUCT_URL overrides the link (landing, waitlist or
    # demo).
    titan_url = (os.getenv("TITAN_PRODUCT_URL", "").strip()
                 or "https://titanomega-ai.com/join")
    lang_name = "Urdu (اردو)" if lang == "ur" else "English"

    t = (target or "auto").lower()
    if t == "auto":
        pool = ["titan"]
        if upwork:
            pool.append("upwork")
        # Career Mind only when explicitly configured - it's an older product and
        # shouldn't be marketed by default.
        if os.getenv("CAREERMIND_URL", "").strip():
            pool.append("career_mind")
        t = pool[len(store.feed) % len(pool)]

    if t == "titan" and titan_url:
        link = titan_url
        pitch = (
            "Titan Omega — SEO, local ranking and legal compliance audited for any "
            "business in any jurisdiction. The legal check is the differentiator: "
            "Impressum / §5 DDG, GDPR consent and cookie disclosure across 9 "
            "countries, scored separately from SEO and never averaged. Free tier "
            "includes the legal findings in full. Write for a business owner who "
            "does not know they have a compliance problem yet."
        )
        img_subject = (
            "a glowing holographic 3D business dashboard floating in a dark modern room, "
            "futuristic AI command center with neon cyan interface, cinematic"
        )
    elif t == "upwork" and upwork:
        link = upwork
        pitch = (
            "Abdullah's Upwork AI services: custom AI chatbots, business automation, "
            "AI content writing, and resume/LinkedIn optimisation. Affordable, fast delivery."
        )
        img_subject = (
            "a confident young professional working on a laptop in a bright modern office, "
            "real candid moment, freelancer at work, genuine expression"
        )
    else:
        t = "career_mind"
        link = cm
        pitch = (
            "Career Mind AI — a FREE AI career-guidance platform for students: instant "
            "resume feedback, career matching, and interview prep."
        )
        img_subject = (
            "a happy young graduate celebrating a job offer, real person smiling, modern "
            "university setting, candid natural moment, warm and hopeful"
        )

    caption = llm.complete(
        task=model_router.CAPTION,
        system=(
            "Write ONE scroll-stopping social media caption (max 200 characters). Sound "
            "like a REAL PERSON sharing a genuine win or tip — not an ad and not corporate. "
            "Open with a hook, give one concrete benefit or mini-story, end with a casual "
            "call to action. Add 3-5 relevant hashtags. Do NOT include any URL (appended "
            f"separately). Write in {lang_name}. Output ONLY the caption."
        ),
        prompt=(topic + ". " if topic else "") + "Promote: " + pitch,
        max_tokens=160,
    ) or (
        "🚀 Land your dream job with AI — free career guidance for students! Try it today. "
        "#AI #careers #jobs #resume #students"
    )

    style = _IMG_STYLES[len(store.feed) % len(_IMG_STYLES)]
    img_prompt = ((topic + ", ") if topic else "") + img_subject + ", " + style
    image_url = _pollinations(img_prompt)

    return {
        "id": store.new_id("draft"),
        "target": t,
        "caption": f"{caption}\n\n👉 {link}",
        "image_prompt": img_prompt,
        "image_url": image_url,
        "link": link,
        "channels": ["linkedin", "instagram", "facebook"],
        "created_at": now().isoformat(),
    }


def _subscriber_next_post(businesses: list, topic: str, lang: str, store: Store) -> dict:
    """The next-post draft for a subscriber: about their own business, linked
    to their own site. With no business there's nothing to promote, and with
    no AI answer there's no caption; it says so rather than falling back to a
    canned caption about someone else's product.
    """
    draft = {"id": store.new_id("draft"), "image_prompt": "", "image_url": "",
             "channels": [], "created_at": now().isoformat()}
    if not businesses:
        return {**draft, "target": "your business", "link": "", "unavailable": "no_business",
                "caption": "Add your business in the Clients tab and Titan drafts "
                           "posts about it here."}
    main = businesses[0]
    lang_name = "Urdu (اردو)" if lang == "ur" else "English"
    link = main.get("website") or ""
    caption = llm.complete(
        task=model_router.CAPTION,
        system=(
            "Write ONE scroll-stopping social media caption (max 200 characters). Sound "
            "like a REAL PERSON sharing a genuine win or tip — not an ad and not corporate. "
            "Open with a hook, give one concrete benefit or mini-story, end with a casual "
            "call to action. Add 3-5 relevant hashtags. Do NOT include any URL (appended "
            f"separately). Write in {lang_name}. Output ONLY the caption."
        ),
        prompt=(topic + ". " if topic else "") + "Promote: " + owner.describe(businesses)
        + ". Write for people nearby who could become its customers.",
        max_tokens=160,
    )
    if not caption:
        return {**draft, "target": main.get("business_name") or "your business",
                "link": link, "unavailable": "no_ai", "caption": quota.no_answer_note("")}
    style = _IMG_STYLES[len(store.feed) % len(_IMG_STYLES)]
    img_prompt = ((topic + ", ") if topic else "") + (
        f"{main.get('industry') or 'small'} business, real people, welcoming, "
        f"natural light, {style}")
    return {**draft, "target": main.get("business_name") or "your business",
            "caption": f"{caption}\n\n👉 {link}" if link else caption,
            "image_prompt": img_prompt, "image_url": _pollinations(img_prompt),
            "link": link, "channels": ["linkedin", "instagram", "facebook"]}


@router.get("/content/daily", tags=["system"])
def content_daily(
    topic: str = Query(default=""),
    lang: str = Query(default="en"),
    target: str = Query(default="auto", description="career_mind | fiverr | auto"),
) -> dict:
    """Fresh caption + a free AI image for the daily post."""
    post = _build_next_post(topic, lang, target, STORE)
    STORE.emit(
        "content-studio", "activity",
        f"Generated daily {post['target'].replace('_', ' ')} post (caption + image).",
        "success",
    )
    return post


# --- HUD "Next Post" card (preview + approve/regenerate) -------------------

def publish_readiness() -> dict:
    """Can a post actually reach a platform right now?

    The card shows real reachability, so approving a post with no connected
    channel doesn't look like it worked.

    A subscriber is never routed through the founder's webhook, which would
    post to the founder's accounts.
    """
    from ..core import cockpit_scope
    if cockpit_scope.is_customer():
        return {"ready": False, "route": None, "reason": (
            "Titan does not post to your accounts. Approving saves the post "
            "to your queue with its caption and image - copy them to your "
            "channels yourself.")}
    hook = os.getenv("TITAN_PUBLISH_WEBHOOK", "").strip()
    return {
        "ready": bool(hook),
        "route": "webhook" if hook else None,
        "reason": "" if hook else (
            "No publishing route is connected, so approving a post queues it "
            "and sends nothing. Titan posts through an automation webhook "
            "(Make.com, Zapier or Buffer): create a scenario there, connect "
            "your accounts to it, and set its catch-hook URL as "
            "TITAN_PUBLISH_WEBHOOK. Nothing is lost meanwhile — approved "
            "posts wait in the queue with their captions and images."),
    }


@router.get("/next-post", tags=["system"])
def next_post(lang: str = Query(default="en")) -> dict:
    """The current next post the founder can approve. Generated lazily, cached.

    A subscriber's "add your business first" placeholder is rebuilt once they
    have a business. A draft that failed for lack of an AI answer isn't
    rebuilt on every poll - that would spend their AI calls every five
    seconds; they press Regenerate instead.
    """
    from ..core import billing, cockpit_scope
    if billing.is_demo(cockpit_scope.customer_email()):
        # Every visitor shares the demo account; drafting a post for each would spend
        # AI calls on nobody's behalf.
        return {"id": "demo-draft", "target": "your business", "link": "",
                "caption": ("In your own workspace, Titan drafts your next post here "
                            "- about your business, with an image. Sign up free to "
                            "get one."),
                "image_prompt": "", "image_url": "", "channels": [],
                "created_at": now().isoformat(), "unavailable": "demo",
                "publish": publish_readiness()}
    cached = STORE.next_post
    stale = (bool(cached) and cached.get("unavailable") == "no_business"
             and bool(owner.subscriber_businesses()))
    if not cached or stale:
        STORE.next_post = _build_next_post("", lang, "auto", STORE)
    return {**STORE.next_post, "publish": publish_readiness()}


class RegenRequest(BaseModel):
    topic: str = Field(default="")
    lang: str = Field(default="en")
    target: str = Field(default="auto")


@router.post("/next-post/regenerate", tags=["system"])
def next_post_regenerate(req: RegenRequest) -> dict:
    """Throw away the current draft and make a fresh caption + image."""
    if owner.subscriber_businesses() is not None:
        from .growth import limit_subscriber
        limit_subscriber()
    STORE.next_post = _build_next_post(req.topic, req.lang, req.target, STORE)
    STORE.emit("content-studio", "activity", "Regenerated the next post (new caption + image).", "info")
    return STORE.next_post


@router.post("/next-post/approve", tags=["system"])
def next_post_approve() -> dict:
    """Schedule the current next post to its channels, then queue up a fresh one."""
    post = STORE.next_post or _build_next_post("", "en", "auto", STORE)
    if post.get("unavailable"):
        # A placeholder isn't a post; scheduling it would put "add your business
        # first" in their queue as content.
        raise HTTPException(status_code=409, detail=post["caption"])
    scheduled = publisher.schedule(
        post["caption"], post.get("channels", ["linkedin"]), post.get("image_url"), None, store=STORE
    )
    ready = publish_readiness()
    STORE.emit(
        "content-studio", "publish",
        (f"Approved next post — scheduled to {', '.join(scheduled['channels'])}."
         if ready["ready"] else
         "Approved next post — QUEUED only. No publishing route is connected, "
         "so nothing was sent."),
        "success" if ready["ready"] else "warn",
    )
    STORE.next_post = _build_next_post("", "en", "auto", STORE)
    return {
        "scheduled_id": scheduled["id"],
        "channels": scheduled["channels"],
        # The caller must be able to tell "sent" from "saved", or a button can look
        # like it worked when it didn't.
        "sent": ready["ready"],
        "publish": ready,
        "next_post": STORE.next_post,
    }


# --- social / work channels rail (Make.com pushes the real numbers) --------

_CHANNELS = [
    {"id": "instagram", "name": "Instagram", "metric": "instagram_followers", "label": "followers", "accent": "rose", "icon": "instagram", "env": "INSTAGRAM_URL", "default": "https://instagram.com"},
    {"id": "facebook", "name": "Facebook", "metric": "facebook_followers", "label": "followers", "accent": "blue", "icon": "facebook", "env": "FACEBOOK_URL", "default": "https://facebook.com"},
    {"id": "pinterest", "name": "Pinterest", "metric": "pinterest_followers", "label": "followers", "accent": "rose", "icon": "pinterest", "env": "PINTEREST_URL", "default": "https://pinterest.com"},
    {"id": "linkedin", "name": "LinkedIn", "metric": "linkedin_followers", "label": "followers", "accent": "cyan", "icon": "linkedin", "env": "LINKEDIN_URL", "default": "https://linkedin.com"},
    {"id": "upwork", "name": "Upwork", "metric": "upwork_invites", "label": "invites", "accent": "emerald", "icon": "upwork", "env": "UPWORK_URL", "default": "https://upwork.com"},
    {"id": "gmail", "name": "Gmail", "metric": "gmail_unread", "label": "unread", "accent": "amber", "icon": "gmail", "env": "GMAIL_URL", "default": "https://mail.google.com"},
]


@router.get("/channels", tags=["system"])
def channels() -> dict:
    """One tile per channel. A real number appears once Make.com pushes it via
    /api/metrics/update (key e.g. ``instagram_followers``); until then: pending.
    """
    out = []
    for c in _CHANNELS:
        connected = c["metric"] in STORE.metrics
        out.append({
            "id": c["id"],
            "name": c["name"],
            "accent": c["accent"],
            "icon": c["icon"],
            "status": "connected" if connected else "pending",
            "value": int(STORE.metrics.get(c["metric"], 0.0)),
            "label": c["label"],
            "href": os.getenv(c["env"], c["default"]),
        })
    return {"channels": out}


# --- live activity stream (Server-Sent Events) -----------------------------

def _feed_id_num(eid: str) -> int:
    try:
        return int(str(eid).rsplit("-", 1)[-1])
    except Exception:
        return 0


def _event_json(e: dict) -> dict:
    ts = e.get("timestamp")
    return {
        "id": e.get("id"),
        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "actor": e.get("actor"),
        "kind": e.get("kind"),
        "message": e.get("message"),
        "severity": e.get("severity", "info"),
    }


def _intensity(new_count: int, status: dict) -> float:
    total = status.get("total_agents") or 1
    active = status.get("active_agents", 0)
    base = 0.22 + 0.5 * (active / total)
    return round(min(1.0, base + 0.1 * new_count), 3)


def _stream_frame(store: Store, last_id: int, guest: bool = False):
    events = [e for e in list(store.feed) if _feed_id_num(e["id"]) > last_id]
    if events:
        last_id = max(_feed_id_num(e["id"]) for e in events)
    if guest:
        # A demo visitor must never receive real order lines, and the money has to
        # match the sampled numbers elsewhere in the demo - otherwise the ledger says
        # $693 and this stream overwrites it with $0.
        events = [e for e in events if not demo_data.is_revenue_event(e)]
    status = executive.empire_status(store)
    if guest:
        status = {**status, "mrr": demo_data.DEMO_MRR,
                  "pipeline_value": demo_data.DEMO_PIPELINE,
                  "traffic": demo_data.DEMO_TRAFFIC}
    frame = {
        "ts": now().isoformat(),
        "status": {
            "health": status["health"],
            "mrr": status["mrr"],
            "traffic": status["traffic"],
            "active_agents": status["active_agents"],
            "total_agents": status["total_agents"],
            "open_opportunities": status["open_opportunities"],
            "actions_in_flight": status["actions_in_flight"],
            "pipeline_value": status["pipeline_value"],
        },
        "events": [_event_json(e) for e in events[-12:]],
        "intensity": _intensity(len(events), status),
    }
    return frame, last_id


@router.get("/stream", tags=["system"])
async def stream(request: Request) -> StreamingResponse:
    """Push a compact live frame (~every 1.5s): status, new feed events, and an
    activity ``intensity`` that drives the 3D core, so the dashboard is live
    without manual refreshes.
    """

    tok = (request.headers.get("authorization", "").removeprefix("Bearer ").strip()
           or request.query_params.get("token", "").strip())
    guest = auth.valid_guest_token(tok)

    async def gen():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            frame, last_id = _stream_frame(STORE, last_id, guest)
            yield "data: " + json.dumps(frame, default=str) + "\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- system doctor -----------------------------------------------------------

@router.get("/doctor", tags=["system"])
def doctor() -> dict:
    """Which integrations the running container can see (booleans only, values
    never exposed). If a secret saved on HF shows false here, the Space hasn't
    restarted since - restart and check again.
    """
    def has(name: str) -> bool:
        return bool(os.getenv(name, "").strip())

    # Live Telegram check: calls getMe server-side and reports the bot's username
    # (never the token) or the exact error, so "bot not answering" can be
    # diagnosed from this one URL.
    telegram_api = None
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if tok:
        try:
            import httpx

            r = httpx.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=8.0, trust_env=True)
            j = r.json()
            if j.get("ok"):
                telegram_api = "ok: @" + j["result"].get("username", "?")
            else:
                telegram_api = f"error: {str(j.get('description', j))[:120]}"
        except Exception as exc:
            telegram_api = f"error: {type(exc).__name__}: {str(exc)[:80]}"

    # Durable storage - the one row worth checking from outside the Space, since
    # every other surface that reports it needs the founder token.
    #
    # `state_backup_configured` is intent (a token is set); `state_backup_proven`
    # is proof (a verified snapshot reached the Hub in this process). They're
    # separate because they answer different questions. Booleans and a repo id
    # only; no token, path or manifest.
    durable = {"state_backup_configured": False, "state_backup_proven": False,
               "state_repo": None, "state_is_ephemeral": None}
    try:
        from ..core import remote_state
        st = remote_state.status()
        durable["state_backup_configured"] = bool(st.get("configured"))
        durable["state_backup_proven"] = bool((st.get("last_push") or {}).get("ok"))
        durable["state_repo"] = st.get("repo")
        durable["state_is_ephemeral"] = st.get("local_is_ephemeral")
        # The part that really matters: a snapshot on the Hub proves a backup
        # happened; only this proves one came back.
        restore = st.get("last_restore") or {}
        durable["state_restored_at_boot"] = restore.get("outcome") or "unknown"
    except Exception as exc:
        # A check that can't run is unknown, not "not configured": "go set the token"
        # and "something's broken" call for different actions.
        durable["state_backup_error"] = f"{type(exc).__name__}: {str(exc)[:80]}"

    return {
        "telegram_api": telegram_api,
        **durable,
        "llm_providers": llm.providers_configured(),
        "groq_key": has("GROQ_API_KEY"),
        "gemini_key": has("GEMINI_API_KEY"),
        "openrouter_key": has("OPENROUTER_API_KEY") or has("HERMES_API_KEY"),
        "tavily_key": has("TAVILY_API_KEY"),
        "github_token": has("GITHUB_TOKEN"),
        "telegram_bot": has("TELEGRAM_BOT_TOKEN"),
        "telegram_locked": has("TELEGRAM_CHAT_ID"),
        "publish_webhook": has("TITAN_PUBLISH_WEBHOOK"),
        "upwork_url": has("UPWORK_PROFILE_URL"),
        "titan_product_url": has("TITAN_PRODUCT_URL"),
        "auth_enabled": os.getenv("TITAN_REQUIRE_AUTH") == "1",
        # Failure detail from the most recent LLM call (doesn't run a new one), to see
        # which provider failed and why after any real request.
        "llm_last_error": llm.last_error(),
        "hint": "false for something you saved on HF? The Space hasn't restarted since you saved it.",
    }


# --- LLM health diagnostic --------------------------------------------------

@router.get("/llm/health", tags=["system"])
def llm_health() -> dict:
    """Run a tiny real completion and report what happened, so a model
    deprecation or bad key shows up instead of silently falling back.
    """
    # 128, not 10: reasoning models (gpt-oss, many :free OpenRouter ids) spend
    # completion tokens on hidden reasoning first, so a 10-token budget always
    # returns empty content and makes healthy providers look dead.
    sample = llm.complete(system="Reply with exactly: OK", prompt="Say OK", max_tokens=128)
    return {
        "provider": llm.provider(),
        "model": llm.active_model(),
        "providers": llm.providers_configured(),
        "ok": bool(sample),
        "sample": (sample or "")[:80],
        "last_error": llm.last_error(),
    }


# --- action-taking command --------------------------------------------------

class ActRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


def _resp(intent: str, response: str, routed_to=None, actions=None) -> dict:
    return {
        "understood": True,
        "intent": intent,
        "response": response,
        "routed_to": routed_to,
        "actions": actions or [],
    }


_POST_WORDS = ["post", "tweet", "linkedin", "instagram", "pinterest", "social", "share", "caption"]
_SCAN_WORDS = ["scan", "opportunit", "find revenue", "find new", "leads", "prospect"]
_REPORT_WORDS = ["report", "summary", "weekly"]
_OUTREACH_WORDS = ["email", "outreach", "school", "university", "college", "business",
                   "customer", "reply", "sell", "contact"]


def _subscriber_act(text: str, businesses: list) -> dict:
    """The command bar in a subscriber's cockpit: the same four actions, done
    for their own business in their own workspace. Nothing is sent or posted
    for them; drafts wait where they can copy them.
    """
    low = text.lower()
    desc = owner.describe(businesses) or "a small business"

    if any(k in low for k in _POST_WORDS):
        if not businesses:
            return _resp("publish", "Add your business in the Clients tab first, and "
                                    "Titan writes posts about it.", "marketing-head")
        content = llm.complete(
            system=(f"Write ONE punchy social media post (max 280 chars) for {desc}, "
                    "based on the instruction. Include a clear call to action. "
                    "Output only the post."),
            prompt=text, max_tokens=160)
        if not content:
            return _resp("publish", quota.no_answer_note(""), "marketing-head")
        post = publisher.schedule(content, ["linkedin"], None, None, store=STORE)
        return _resp(
            "publish",
            f'Drafted a post and saved it to your queue: "{content[:140]}". Titan does '
            "not post to your accounts - copy it from Publishing.",
            "marketing-head", ["scheduled_post:" + str(post.get("id", ""))])

    if any(k in low for k in _SCAN_WORDS):
        from ..engines import autonomous
        from .growth import limit_subscriber
        limit_subscriber()
        intel = autonomous.growth_cycle(STORE)
        return _resp(
            "intelligence",
            ("Researched your market - the brief, competitors and keywords are in "
             "the War Room." if businesses else intel["summary"]),
            "intelligence-head", ["growth_research"])

    if any(k in low for k in _REPORT_WORDS):
        deliverables.generate("business_report", f"{text}\n\nThe business: {desc}",
                              "executive-board-reporting-analyst", store=STORE)
        return _resp("report", "Generated your report - open the Deliverables panel to read it.",
                     "executive-board-reporting-analyst", ["created_deliverable"])

    if any(k in low for k in _OUTREACH_WORDS):
        if any(k in low for k in ["customer", "reply", "care", "support"]):
            brief = f"Warm, professional customer-care reply from {desc} that resolves the issue."
        else:
            brief = f"Short, warm cold email from {desc} to a potential customer."
        content = llm.complete(
            system=(f"You are the sales and outreach writer for {desc}. Draft specific, "
                    "professional, ready-to-send copy."),
            prompt=brief + "\n\nWhat the owner asked: " + text, max_tokens=600)
        if not content:
            return _resp("outreach", quota.no_answer_note(""), "revenue-head")
        deliverables.generate("outreach_email", brief + "\n\n" + content, "revenue-head",
                              store=STORE)
        return _resp("outreach", "Drafted it and saved it to Deliverables. Titan does not "
                                 "send it - copy it into your email or chat.",
                     "revenue-head", ["created_deliverable"])

    answer = llm.complete(
        system=(f"You are Titan, the AI assistant in the owner's cockpit for {desc}. Speak "
                "to them as 'you'. Be concise and actionable. If they want an action, "
                "tell them you can draft posts, research their market, write reports, or "
                "draft outreach."),
        prompt=text, max_tokens=400,
    ) or quota.no_answer_note("")
    return _resp("answer", answer, "executive-core")


@router.post("/agent/act", tags=["system"])
def agent_act(req: ActRequest) -> dict:
    """Interpret an instruction and perform a real in-app action."""
    text = req.instruction.strip()
    low = text.lower()
    businesses = owner.subscriber_businesses()
    if businesses is not None:
        return _subscriber_act(text, businesses)

    if any(k in low for k in ["post", "tweet", "linkedin", "instagram", "pinterest", "social", "share", "caption"]):
        content = llm.complete(
            system=(
                "Write ONE punchy social media post (max 280 chars) promoting Abdullah's "
                "Career Mind AI (free AI career guidance for students) or his Upwork AI gigs, "
                "based on the instruction. Include a clear call to action. Output only the post."
            ),
            prompt=text,
            max_tokens=160,
        ) or "🚀 Career Mind AI — free AI career guidance for students. Try it now! #AI #careers"
        post = publisher.schedule(content, ["linkedin"], None, None, store=STORE)
        return _resp(
            "publish",
            f'Done, Abdullah — drafted & scheduled a post: "{content[:140]}". It publishes on the next '
            "cycle. Connect Make.com to push it live to your real socials.",
            "marketing-head",
            ["scheduled_post:" + str(post.get("id", ""))],
        )

    if any(k in low for k in ["scan", "opportunit", "find revenue", "find new", "leads", "prospect"]):
        STORE.opportunities.clear()
        opportunity.discover(STORE)
        n = len(STORE.opportunities)
        return _resp(
            "intelligence",
            f"Scanned the market — surfaced {n} fresh opportunities. Check the Opportunity Radar.",
            "intelligence-head",
            ["scanned_opportunities"],
        )

    if any(k in low for k in ["report", "summary", "weekly"]):
        deliverables.generate("business_report", text, "executive-board-reporting-analyst", store=STORE)
        return _resp(
            "report",
            "Generated your report — open the Deliverables panel to read it.",
            "executive-board-reporting-analyst",
            ["created_deliverable"],
        )

    if any(k in low for k in ["email", "outreach", "school", "university", "college", "business", "customer", "reply", "sell", "contact"]):
        if any(k in low for k in ["school", "university", "college"]):
            brief = "Cold email to a school/university administrator selling Career Mind AI (free-trial student career platform)."
        elif any(k in low for k in ["customer", "reply", "care", "support"]):
            brief = "Warm, professional customer-care reply that resolves the issue."
        elif any(k in low for k in ["business", "sell", "contact"]):
            brief = "Cold email to a small business owner offering Abdullah's Upwork AI services (chatbots, automation, content)."
        else:
            brief = "Helpful community message for job-seekers introducing Career Mind AI + Abdullah's Upwork resume services."
        content = llm.complete(
            system="You are Abdullah's sales/outreach writer. Draft specific, professional, ready-to-send copy.",
            prompt=brief + "\n\nContext from Abdullah: " + text,
            max_tokens=600,
        ) or "Draft unavailable — set an LLM key (Groq/Hermes, free)."
        deliverables.generate("outreach_email", brief + "\n\n" + content, "revenue-head", store=STORE)
        return _resp(
            "outreach",
            "Drafted the outreach and saved it to Deliverables. ⚠️ To actually SEND it to real people, "
            "connect your Gmail via Make.com — auto-emailing strangers without that is spam and risks a ban.",
            "revenue-head",
            ["created_deliverable"],
        )

    ans = llm.complete(
        system=(
            "You are Titan, Abdullah's AI chief of staff. Address him simply as 'Abdullah'. "
            "Be concise and actionable. If he wants an action, tell him you can post, scan "
            "opportunities, generate reports, or draft outreach."
        ),
        prompt=text,
        max_tokens=400,
    ) or (
        "Abdullah, I can post to socials, scan opportunities, generate reports, or draft outreach. "
        "Tell me which and I'll do it."
    )
    return _resp("answer", ans, "executive-core", [])
