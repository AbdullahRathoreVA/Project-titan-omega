"""Social posts for a client.

brand_playbook decides what to post and why; this writes the captions, under
rules taken from how premium brands actually post:

- Under ~15 words.
- No emoji stacks, "LINK IN BIO!!" or discount language, which undermine
  premium positioning.
- Scarcity rather than urgency ("six weeks only", not "HURRY 50% OFF").
- In the client's market language (a Berlin restaurant posts in German).

Nothing is published automatically. Posts go to a queue for approval, since
automated posting through unofficial routes gets accounts banned.
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

# Deterministic fallbacks for when no model is reachable. Plain on purpose:
# a simple caption that follows the rules beats a fancy one that breaks them.
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


def market_language(country: str) -> str:
    """The language the client's customers search and read in."""
    return {"Germany": "de", "Austria": "de", "Switzerland": "de",
            "France": "fr", "Italy": "it", "Spain": "es",
            "Netherlands": "nl"}.get(country or "", "en")


# Old name, kept for existing callers.
language_for = market_language


def _violates(caption: str) -> Optional[str]:
    """Return the rule a caption breaks, or None. Guards against a chatty model."""
    low = caption.lower()
    for b in BANNED:
        if b in low:
            return f"contains banned element: {b!r}"
    if len(caption.split()) > 18:
        return f"too long ({len(caption.split())} words, limit ~15)"
    if caption.count("#") > 0:
        return "contains hashtags"
    return None


# Placeholder defaults need localising too, or a German template ends up with
# an English phrase in the middle.
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
    # Fall back to the template's own language, not to English.
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
        # A caption that breaks the positioning rules is worse than a plain one.
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


def week_of_posts(client: dict, *, dishes: Optional[list[str]] = None,
                  lang: str = "en", with_market_language: bool = True) -> dict:
    """A full week of ready-to-post captions.

    Captions are in English so they can be reviewed before going out under a
    client's name. When the client's customers speak another language, each post
    also has a `local` caption in that language; English is the working copy and
    `local` is what gets published.
    """
    business = client.get("business_name", "the restaurant")
    cuisine = client.get("industry") or "restaurant"
    city = client.get("city", "")
    dishes = [d for d in (dishes or []) if d]
    market = market_language(client.get("country", ""))

    slots = [("Monday", "season"), ("Tuesday", "craft"),
             ("Thursday", "people"), ("Saturday", "guest")]

    posts = []
    for i, (day, pillar) in enumerate(slots):
        dish = dishes[i % len(dishes)] if dishes else ""
        post = write_caption(pillar, business=business, cuisine=cuisine,
                             city=city, lang=lang, dish=dish)
        post["day"] = day

        if with_market_language and market != lang:
            twin = write_caption(pillar, business=business, cuisine=cuisine,
                                 city=city, lang=market, dish=dish)
            post["local"] = twin["caption"]
            post["local_language"] = market
            post["local_source"] = twin["source"]
        posts.append(post)

    return {
        "business": business,
        "language": lang,
        "market_language": market,
        "language_note": (
            f"Captions are in English for your review. Each also has a "
            f"'{market}' version — post that one, because the client's "
            f"customers search in {LANG_NAME.get(market, market)}."
            if market != lang else
            "Client's market speaks English, so one version is enough."),
        "posts": posts,
        "cadence": brand_playbook.CADENCE,
        "avoid": brand_playbook.FORBIDDEN,
        "note": ("Nothing is posted automatically. Approve each one and post it "
                 "yourself — automated posting through unofficial endpoints is "
                 "how business accounts get banned, and a banned account ends "
                 "the service you are paying for."),
        "generated_at": time.time(),
    }
