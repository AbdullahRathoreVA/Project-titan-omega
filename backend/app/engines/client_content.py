"""Actual posts for a client — the thing they are paying for.

brand_playbook says WHAT to post and why. This writes the posts.

Every caption is generated against constraints taken from measured behaviour of
the brands themselves, not from marketing advice:

  - Under ~15 words. The luxury accounts do not write essays under a photo.
  - No emoji stacks, no "LINK IN BIO!!", no discount language. Discount-led
    posting is the fastest way to destroy premium positioning, and none of the
    seven brands measured does any of it.
  - Scarcity, never urgency: "six weeks only" reads as desirable, "HURRY 50%
    OFF" reads as desperate.
  - Written in the client's own market language (a Berlin restaurant posts in
    German), because their customers are local.

Nothing is auto-published. Posts land in a queue the client or Abdullah
approves, for the same reason Aether never auto-posts: automated posting through
unofficial endpoints is how accounts get banned, and a banned account ends the
service the client is paying for.
"""

from __future__ import annotations

import random
import time
from typing import Optional

from ..core import llm
from . import brand_playbook

LANG_NAME = {
    "de": "German", "fr": "French", "it": "Italian", "es": "Spanish",
    "nl": "Dutch", "en": "English",
}

SYSTEM = (
    "You write social captions for a premium local restaurant. You write the "
    "way Chanel, Louis Vuitton and Jacquemus write: short, declarative, "
    "confident, never salesy. Hard rules you never break: under 15 words; no "
    "emoji; no hashtags unless asked; never mention discounts, sales, offers or "
    "urgency; never write 'link in bio'; never use exclamation marks. State the "
    "thing plainly and stop. If the language requested is not English, write "
    "ONLY in that language."
)

# Deterministic fallbacks, used when no model is reachable. Deliberately plain:
# a weak caption that obeys the rules beats a florid one that breaks them.
FALLBACK = {
    "craft": {
        "en": "{dish}. Made this morning.",
        "de": "{dish}. Heute Morgen zubereitet.",
        "fr": "{dish}. Préparé ce matin.",
        "it": "{dish}. Preparato stamattina.",
    },
    "people": {
        "en": "{who} has cooked this dish for eleven years.",
        "de": "{who} kocht dieses Gericht seit elf Jahren.",
        "fr": "{who} prépare ce plat depuis onze ans.",
        "it": "{who} prepara questo piatto da undici anni.",
    },
    "place": {
        "en": "The room, before service.",
        "de": "Der Raum, vor dem Service.",
        "fr": "La salle, avant le service.",
        "it": "La sala, prima del servizio.",
    },
    "season": {
        "en": "{item}. Six weeks only.",
        "de": "{item}. Nur sechs Wochen.",
        "fr": "{item}. Six semaines seulement.",
        "it": "{item}. Solo sei settimane.",
    },
    "guest": {
        "en": "Thank you, {who}.",
        "de": "Danke, {who}.",
        "fr": "Merci, {who}.",
        "it": "Grazie, {who}.",
    },
}

BANNED = [
    "link in bio", "!", "50%", "discount", "sale", "offer", "hurry",
    "limited time", "buy now", "order now", "dm us", "swipe up", "🔥", "😍",
]


def language_for(country: str) -> str:
    return {"Germany": "de", "Austria": "de", "Switzerland": "de",
            "France": "fr", "Italy": "it", "Spain": "es",
            "Netherlands": "nl"}.get(country or "", "en")


def _violates(caption: str) -> Optional[str]:
    """Return the rule broken, or None. Guards against a chatty model."""
    low = caption.lower()
    for b in BANNED:
        if b in low:
            return f"contains banned element: {b!r}"
    if len(caption.split()) > 18:
        return f"too long ({len(caption.split())} words, limit ~15)"
    if caption.count("#") > 0:
        return "contains hashtags"
    return None


# Placeholder defaults must be localised too. Interpolating an English default
# into a German template produced "our head chef kocht dieses Gericht seit elf
# Jahren" — a mixed-language caption that would embarrass the client publicly.
DEFAULTS = {
    "de": {"dish": "Der Teller des Tages", "item": "Jetzt in der Saison",
           "who": "unser Küchenchef"},
    "fr": {"dish": "L'assiette du jour", "item": "De saison",
           "who": "notre chef"},
    "it": {"dish": "Il piatto del giorno", "item": "Di stagione",
           "who": "il nostro chef"},
    "es": {"dish": "El plato del día", "item": "De temporada",
           "who": "nuestro chef"},
    "nl": {"dish": "Het gerecht van vandaag", "item": "Nu in het seizoen",
           "who": "onze chef"},
    "en": {"dish": "Today's plate", "item": "In season now",
           "who": "our head chef"},
}


def _fallback(pillar: str, lang: str, ctx: dict) -> str:
    tpl = FALLBACK.get(pillar, FALLBACK["craft"])
    text = tpl.get(lang) or tpl["en"]
    # Fall back to the SAME language the template is in, not to English.
    used_lang = lang if lang in tpl else "en"
    d = DEFAULTS.get(used_lang, DEFAULTS["en"])
    return text.format(
        dish=ctx.get("dish") or d["dish"],
        item=ctx.get("dish") or d["item"],
        who=ctx.get("who") or d["who"])


def write_caption(pillar: str, *, business: str, cuisine: str, city: str,
                  lang: str = "en", dish: str = "", who: str = "") -> dict:
    """One caption for one pillar. Always returns something usable."""
    ctx = {"dish": dish, "who": who}
    p = next((x for x in brand_playbook.PILLARS if x["key"] == pillar),
             brand_playbook.PILLARS[0])

    prompt = (
        f"Restaurant: {business} — {cuisine} in {city}.\n"
        f"Post theme: {p['name']} — {p['what']}\n"
        + (f"Subject: {dish}\n" if dish else "")
        + (f"Person: {who}\n" if who else "")
        + f"Write ONE caption in {LANG_NAME.get(lang, 'English')}. "
          f"Under 15 words. Output the caption only, nothing else."
    )

    text = (llm.complete(SYSTEM, prompt, max_tokens=80) or "").strip()
    text = text.strip('"').strip("'").split("\n")[0].strip()

    source = "model"
    problem = _violates(text) if text else "empty"
    if problem:
        # A caption that breaks positioning rules is worse than a plain one.
        text = _fallback(pillar, lang, ctx)
        source = f"fallback ({problem})"

    return {
        "pillar": p["name"],
        "pillar_key": pillar,
        "caption": text,
        "language": lang,
        "format": "Reel" if pillar in ("craft", "people") else "Photo",
        "shot_brief": p["example"],
        "why": p["why"],
        "source": source,
    }


def week_of_posts(client: dict, *, dishes: Optional[list[str]] = None) -> dict:
    """A full week of ready-to-post captions for one client."""
    lang = language_for(client.get("country", ""))
    business = client.get("business_name", "the restaurant")
    cuisine = client.get("industry") or "restaurant"
    city = client.get("city", "")
    dishes = [d for d in (dishes or []) if d]

    slots = [("Monday", "season"), ("Tuesday", "craft"),
             ("Thursday", "people"), ("Saturday", "guest")]

    posts = []
    for i, (day, pillar) in enumerate(slots):
        dish = dishes[i % len(dishes)] if dishes else ""
        post = write_caption(pillar, business=business, cuisine=cuisine,
                             city=city, lang=lang, dish=dish)
        post["day"] = day
        posts.append(post)

    return {
        "business": business,
        "language": lang,
        "posts": posts,
        "cadence": brand_playbook.CADENCE,
        "avoid": brand_playbook.FORBIDDEN,
        "note": ("Nothing is posted automatically. Approve each one and post it "
                 "yourself — automated posting through unofficial endpoints is "
                 "how business accounts get banned, and a banned account ends "
                 "the service you are paying for."),
        "generated_at": time.time(),
    }
