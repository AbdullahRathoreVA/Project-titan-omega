"""Social media strategy based on how luxury brands actually post.

Figures read from the live Instagram profiles on 2026-07-26:

  brand            posts    followers   following
  CHANEL           7,446    59.0M       3
  Louis Vuitton    9,381    55.1M       7
  Gucci              367    50.5M       4
  Dior            14,480    46.5M       9
  Prada            9,906    33.5M       9
  Tommy Hilfiger   1,872    15.0M     347
  Jacquemus        8,120     6.8M    1,058
  Bottega Veneta      -        -         -   (account deleted, 2021)

What that means for a restaurant:

1. Following count signals positioning. The most prestigious brands follow
   3-9 accounts; Tommy Hilfiger (mass-market) follows 347, Jacquemus (young,
   accessible) 1,058. Following few reads as self-sufficient; a restaurant
   following 3,000 accounts looks like it's chasing customers.
2. Gucci has 367 posts and 50.5M followers - they periodically clear the
   grid, so it shows a deliberate current identity. Dior has 14,480. Both
   work if the choice is deliberate.
3. Bios are philosophy, not sales. Prada: "Thinking fashion since 1913." Dior
   quotes Christian Dior. Nobody writes "Shop now" or lists prices.
4. Dior puts a physical address in the bio ("30 avenue Montaigne, Paris").
   For a local restaurant that's free local SEO, and few independents do it.
5. Story highlights are named after collections in the brand's own language:
   LV in French (Le Keepall, Le Noé, L'Alma), Gucci in Italian (Primavera,
   La Famiglia), Dior by season code (Couture FW27, DiorSummer27). None use
   "Menu" or "About us". For a restaurant: name highlights after dishes and
   seasons in the cuisine's language.
6. The bio link points at the current campaign, not the homepage (Chanel to
   /-Connects-Season6, Gucci to a Monte Carlo campaign).
7. Bottega Veneta deleted every social account in 2021 and still grew.
   Presence is a choice; more posting isn't always better.

Overall: over-posting hurts premium positioning. Posting 3-5x a day signals
accessibility; fewer, well-made posts earn saves and shares. Discount and
urgency content damages brand equity fastest - scarcity ("limited", "while
it lasts") works where "50% OFF" doesn't.
"""

from __future__ import annotations

# Read from live profiles on 2026-07-26.
BENCHMARKS = {
    "chanelofficial": {"posts": 7446, "followers": 59_000_000, "following": 3},
    "louisvuitton": {"posts": 9381, "followers": 55_100_000, "following": 7},
    "gucci": {"posts": 367, "followers": 50_500_000, "following": 4},
    "dior": {"posts": 14480, "followers": 46_500_000, "following": 9},
    "prada": {"posts": 9906, "followers": 33_500_000, "following": 9},
    "tommyhilfiger": {"posts": 1872, "followers": 15_000_000, "following": 347},
    "jacquemus": {"posts": 8120, "followers": 6_800_000, "following": 1058},
}

# Restaurant-specific pillars. The luxury principles adapted for a local
# business: provenance and people instead of runway and celebrity.
PILLARS = [
    {
        "key": "craft",
        "name": "The craft",
        "share": 0.30,
        "what": "One dish, shot properly. Close, natural light, no clutter.",
        "why": "The product IS the brand. Luxury sells the object, not the offer.",
        "example": "Slow-motion pour of the sauce finishing a plate. No text.",
    },
    {
        "key": "people",
        "name": "The people",
        "share": 0.20,
        "what": "The chef, the kitchen, the hands doing the work.",
        "why": "Provenance and authorship are what justify a premium price.",
        "example": "The head chef plating, named, with one line about their training.",
    },
    {
        "key": "place",
        "name": "The place",
        "share": 0.15,
        "what": "The room, the light at a specific hour, the street outside.",
        "why": "Turns a meal into a destination — and carries the local signal.",
        "example": "The dining room at 18:40 as the lights come on.",
    },
    {
        "key": "season",
        "name": "Season and scarcity",
        "share": 0.20,
        "what": "What is on the menu only now, and when it ends.",
        "why": "Scarcity framing works where discounting destroys equity.",
        "example": "'White asparagus. Six weeks only.' — never 'SPECIAL OFFER'.",
    },
    {
        "key": "guest",
        "name": "Guests and proof",
        "share": 0.15,
        "what": "Reposted guest photos, a quiet full room, a review quote.",
        "why": "Social proof drives reservations and feeds review signals, "
                "which are 16-20% of local ranking.",
        "example": "A repost credited to the guest, thanking them by name.",
    },
]

CADENCE = {
    "feed_posts_per_week": 4,
    "reels_per_week": 2,
    "stories_per_day": 2,
    "rationale": (
        "Four crafted feed posts a week beats daily filler. Measured luxury "
        "practice is sub-frequency and high craft; posting 3-5x daily reads as "
        "accessibility, which is the opposite of what a premium restaurant "
        "wants. Stories carry the daily rhythm because they expire and "
        "therefore cost the grid nothing."
    ),
}

FORBIDDEN = [
    ("50% OFF / HUGE SALE", "Discount-led posting is the fastest way to damage "
     "premium positioning. Use scarcity, not price cuts."),
    ("LINK IN BIO!! 🔥🔥🔥", "Emoji-stacked urgency reads as desperation. None "
     "of the seven brands measured does this."),
    ("Generic stock food photos", "The product must be the actual product. "
     "Stock imagery is detectable and destroys trust."),
    ("Following thousands of accounts", "The top brands follow 3-9. Following "
     "thousands signals chasing rather than being sought."),
    ("Posting the same photo to feed and story", "Wastes the grid slot. The "
     "grid is the permanent identity; stories are the daily rhythm."),
]


def bio_template(name: str, cuisine: str, city: str, address: str = "",
                 founded: str = "") -> dict:
    """A bio built the way the measured brands build theirs."""
    line = (f"{cuisine} since {founded}." if founded
            else f"{cuisine}, cooked properly.")
    return {
        "line_1_philosophy": line,
        "line_2_place": address or f"{city}",
        "line_3_link": "One live thing — this week's menu or reservations. "
                       "Never the bare homepage.",
        "why": ("Prada's entire bio is 'Thinking fashion since 1913.' Dior "
                "quotes its founder and lists 30 avenue Montaigne. Philosophy "
                "plus address, no sales language. The address is also free "
                "local SEO that most independents omit."),
        "example": f"{line}\n{address or city}\n→ this week's menu",
    }


def highlights_plan(cuisine: str, language: str = "en") -> list[str]:
    """Highlight names follow the brands: collections in the native language."""
    by_lang = {
        "de": ["Die Karte", "Mittagstisch", "Weinkarte", "Das Team",
               "Der Raum", "Reservierung"],
        "it": ["Il Menù", "La Carta dei Vini", "La Cucina", "La Sala",
               "Stagione", "Prenota"],
        "fr": ["La Carte", "Les Vins", "La Cuisine", "La Salle",
               "Saison", "Réserver"],
        "en": ["The Menu", "The Wine", "The Kitchen", "The Room",
               "In Season", "Book"],
    }
    return by_lang.get(language, by_lang["en"])


def audit_profile(posts: int, followers: int, following: int) -> dict:
    """Compare a client's account against how the luxury brands operate."""
    findings = []

    if following > 500:
        findings.append({
            "severity": "high",
            "title": f"Following {following:,} accounts",
            "detail": ("The five most prestigious brands measured follow 3-9 "
                       "accounts (Chanel 3, Gucci 4, LV 7, Prada 9, Dior 9). "
                       "Following thousands reads as chasing attention."),
            "fix": "Unfollow down to suppliers, staff and genuine partners.",
        })

    ratio = followers / max(following, 1)
    if followers and ratio < 10:
        findings.append({
            "severity": "medium",
            "title": "Follower-to-following ratio is near 1:1",
            "detail": "Reads as follow-for-follow growth, which suppresses "
                      "perceived status and rarely converts to covers.",
            "fix": "Stop reciprocal following. Grow through craft and reposts.",
        })

    if posts > 3000 and followers < 50_000:
        findings.append({
            "severity": "medium",
            "title": f"{posts:,} posts but {followers:,} followers",
            "detail": ("High volume with low reach means the posts are not "
                       "earning saves or shares. Gucci holds 50.5M followers "
                       "on 367 posts — volume is not the lever."),
            "fix": "Cut to 4 crafted posts a week and archive weak old posts.",
        })

    return {
        "findings": findings,
        "benchmarks": BENCHMARKS,
        "verdict": ("aligned with premium practice" if not findings
                    else f"{len(findings)} positioning issue(s)"),
    }


# Industries this playbook was researched for.
#
# The pillars (the dish, the chef, the room, the guest, the season) were built
# for hospitality. Nothing here was researched for a wholesaler, a law firm or
# a software company, so they don't get "hero dish, close and clean".
#
# Keys match core verticals. The generic parts - CADENCE, FORBIDDEN,
# BENCHMARKS and audit_profile() - aren't gated: following count,
# post-to-follower ratio and discount-led posting apply to any brand.
COVERED_INDUSTRIES = ("restaurant", "cafe", "bar", "bakery", "hotel")

# What people actually type into a free-text industry box, mapped to the keys
# above. Kept short on purpose: wrongly including a business is worse than
# leaving it out, because being left out is visible.
_ALIASES = {
    "restaurants": "restaurant", "dining": "restaurant", "bistro": "restaurant",
    "pizzeria": "restaurant", "food": "restaurant", "catering": "restaurant",
    "coffee": "cafe", "coffee shop": "cafe", "café": "cafe", "cafeteria": "cafe",
    "pub": "bar", "wine bar": "bar", "cocktail bar": "bar",
    "patisserie": "bakery", "bakehouse": "bakery",
    "hospitality": "hotel", "guesthouse": "hotel", "b&b": "hotel",
}


def normalise_industry(industry: str) -> str:
    """A free-text industry reduced to a covered key, or "" if it isn't one."""
    key = (industry or "").strip().lower()
    if not key:
        return ""
    key = _ALIASES.get(key, key)
    return key if key in COVERED_INDUSTRIES else ""



def coverage(industry: str) -> dict:
    """Whether the weekly plan applies here, and if not, why not.

    Returns the reason rather than False, so the screen can say something
    specific instead of going blank (a blank panel looks broken).
    """
    key = normalise_industry(industry)
    if key:
        return {"covered": True, "matched": key, "industry": industry,
                "reason": None}
    return {
        "covered": False,
        "matched": None,
        "industry": industry or "",
        "measured_for": list(COVERED_INDUSTRIES),
        "reason": (
            "Titan's social playbook was measured from seven luxury brand "
            "profiles and translated for hospitality — the dish, the kitchen, "
            "the room. Nothing in it was measured for "
            f"{industry or 'this kind of business'}, so no weekly plan is "
            "shown rather than restaurant advice with your name on it. The "
            "profile benchmarks below apply to any brand and are shown."),
    }


def weekly_plan(name: str, cuisine: str, city: str,
                language: str = "en") -> list[dict]:
    """A concrete week, weighted by the pillar shares."""
    slots = [
        ("Monday", "season", "Quiet week-opener: what just came into season."),
        ("Tuesday", "craft", "Hero dish, close and clean. Caption under 12 words."),
        ("Thursday", "people", "The kitchen at work. Name the person."),
        ("Saturday", "guest", "Repost a guest photo, credited."),
    ]
    out = []
    for day, pillar_key, brief in slots:
        p = next(x for x in PILLARS if x["key"] == pillar_key)
        out.append({
            "day": day, "pillar": p["name"], "brief": brief,
            "format": "Reel" if pillar_key in ("craft", "people") else "Photo",
            "caption_rule": ("Under 15 words. No emoji stacks, no 'link in "
                             "bio!!', no discounts. State the thing plainly."),
            "why": p["why"],
        })
    return out
