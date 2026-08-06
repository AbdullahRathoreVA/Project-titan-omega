"""What kind of business this is, and how to talk to it.

Titan was written against one client — a German restaurant — and it shows in the
audit's wording, not in its scoring. The scoring engine was always generic: six
weighted local dimensions with no food assumption. But the advice a client reads
said "Restaurant in {city}", offered "wood-fired chicken karahi" as the alt-text
example, and told a law firm that "the food photography is the product".

That wording is the product. An audit that calls a dentist a restaurant is not
a credible €1,200 deliverable, so this file makes every client-facing string a
function of the vertical.

One source of truth. Previously the detection signals and the schema map lived
in local_seo with different key sets — VERTICAL_SCHEMA listed dentist, auto and
store, VERTICAL_SIGNALS did not, so those three could never actually be
detected and silently fell back to generic advice.

Adding a vertical means adding one entry here. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vertical:
    key: str
    label: str                 # "Restaurant", "Dental practice"
    schema_type: str           # correct Schema.org subtype
    signals: tuple             # detection words (English + German)
    asset_noun: str            # what the imagery actually IS for this business
    alt_example: str           # a concrete alt-text example in that trade
    title_example: str         # "{name} — {this} in {city}"
    extra_schema: str = ""     # subtype-specific properties worth adding
    share_context: str = ""    # why OG tags matter for this trade
    # Does this trade actually serve customers from a PLACE? Almost all do, but
    # a software product does not, and telling a SaaS to publish a street
    # address, opening hours and LocalBusiness markup is wrong advice. Titan
    # gave itself exactly that advice when it first audited its own site.
    local_business: bool = True


_V = Vertical

VERTICALS: dict[str, Vertical] = {
    "restaurant": _V(
        "restaurant", "Restaurant", "Restaurant",
        ("menu", "speisekarte", "reservier", "reservation", "dine", "takeaway",
         "lieferung", "cuisine", "küche", "tisch"),
        "the food photography",
        "wood-fired lamb karahi, served in a copper pan",
        "Restaurant",
        "servesCuisine, menu URL, and Menu/MenuSection/MenuItem so answer "
        "engines can quote individual dishes",
        "menus and dishes shared to WhatsApp and Instagram"),
    "cafe": _V(
        "cafe", "Café", "CafeOrCoffeeShop",
        ("coffee", "kaffee", "espresso", "barista", "café", "cake"),
        "the drinks and interior photography",
        "flat white in a ceramic cup on a walnut counter",
        "Café",
        "servesCuisine and openingHoursSpecification — café searches skew "
        "heavily to 'open now'",
        "posts shared to Instagram"),
    "bar": _V(
        "bar", "Bar", "BarOrPub",
        ("cocktail", "bier", "beer", "wine bar", "happy hour", "pub"),
        "the drinks photography",
        "negroni garnished with an orange peel",
        "Bar",
        "openingHoursSpecification — late-night hours are the differentiator",
        "event and happy-hour posts"),
    "bakery": _V(
        "bakery", "Bakery", "Bakery",
        ("bakery", "bäckerei", "brot", "pastry", "konditorei", "sourdough"),
        "the product photography",
        "sourdough loaf with an open crumb, cut on a board",
        "Bakery",
        "openingHoursSpecification — bakeries are found by early opening times",
        "daily-special posts"),
    "hotel": _V(
        "hotel", "Hotel", "Hotel",
        ("rooms", "zimmer", "booking", "check-in", "suite", "übernachtung"),
        "the room and property photography",
        "double room with a balcony overlooking the old town",
        "Hotel",
        "amenityFeature, checkinTime, checkoutTime and starRating",
        "room links shared in booking conversations"),
    "healthcare": _V(
        "healthcare", "Medical practice", "MedicalClinic",
        ("patient", "appointment", "termin", "praxis", "arzt", "clinic",
         "sprechstunde"),
        "the practice and team photography",
        "consultation room with accessible entrance",
        "Practice",
        "medicalSpecialty, availableService and openingHoursSpecification",
        "links shared by patients recommending you"),
    "dentist": _V(
        "dentist", "Dental practice", "Dentist",
        ("dentist", "zahnarzt", "dental", "zahn", "implant", "prophylaxe",
         "kieferorthop"),
        "the practice and treatment photography",
        "treatment room with modern chair and equipment",
        "Dental practice",
        "medicalSpecialty and availableService — list each treatment "
        "separately, they are searched separately",
        "links shared by patients recommending you"),
    "legal": _V(
        "legal", "Law firm", "LegalService",
        ("attorney", "anwalt", "kanzlei", "rechtsanwalt", "solicitor",
         "legal advice", "mandant"),
        "the team and office photography",
        "portrait of the managing partner in the office",
        "Law firm",
        "areaServed and knowsAbout for each practice area — clients search by "
        "the problem, not the firm",
        "profile links shared in referrals"),
    "salon": _V(
        "salon", "Salon", "HairSalon",
        ("haircut", "friseur", "salon", "styling", "coloring", "kosmetik"),
        "the before-and-after photography",
        "balayage colour result, side profile in natural light",
        "Salon",
        "availableService with priceRange per service",
        "before-and-after posts, which are the main sharing driver"),
    "gym": _V(
        "gym", "Gym", "ExerciseGym",
        ("fitness", "gym", "training", "membership", "mitgliedschaft",
         "personal trainer"),
        "the facility and class photography",
        "free-weights area with racks and mirrors",
        "Gym",
        "openingHoursSpecification and availableService for classes",
        "class timetables shared in group chats"),
    "auto": _V(
        "auto", "Auto business", "AutoRepair",
        ("werkstatt", "garage", "mot", "tüv", "car repair", "autohaus",
         "reifen", "inspektion"),
        "the workshop and vehicle photography",
        "vehicle on a two-post lift mid-service",
        "Garage",
        "availableService per repair type and areaServed",
        "quotes shared by customers"),
    "store": _V(
        "store", "Shop", "Store",
        ("shop", "laden", "geschäft", "produkte", "sortiment", "in stock",
         "warenkorb"),
        "the product photography",
        "product on a plain background, front view",
        "Shop",
        "Product and Offer markup for the range, with price and availability",
        "product links shared to friends"),
    "wholesale": _V(
        "wholesale", "Wholesale supplier", "WholesaleStore",
        ("wholesale", "bulk", "moq", "minimum order", "trade price",
         "b2b", "distributor", "supplier", "grosshandel", "großhandel",
         "per dozen", "per unit", "trade enquiry", "export"),
        "the product catalogue photography",
        "full-grain leather jacket, front view on a plain background",
        "Wholesale supplier",
        "Product and Offer markup per SKU with priceSpecification and "
        "eligibleQuantity (the MOQ), plus areaServed for the markets you ship to",
        "catalogue links sent to buyers",
        # A wholesaler is found by a buyer searching for the PRODUCT or the
        # trade, not by someone standing nearby. Scoring it on Google Business
        # Profile and review velocity produces a low number that means nothing.
        local_business=False),
    "manufacturer": _V(
        "manufacturer", "Manufacturer", "Organization",
        ("manufacturer", "factory", "oem", "odm", "production capacity",
         "we produce", "hersteller", "fabrik", "tannery", "workshop",
         "units per month", "private label"),
        "the production and facility photography",
        "stitching line in the workshop, wide shot",
        "Manufacturer",
        "Organization with makesOffer per product line, plus production "
        "capacity and certifications stated on the page",
        "specification sheets shared with buyers",
        local_business=False),
    "software": _V(
        "software", "Software product", "SoftwareApplication",
        ("saas", "software", "platform", "dashboard", "api", "subscription",
         "app", "pricing per month"),
        "the product screenshots",
        "the dashboard showing a completed audit",
        "Platform",
        "applicationCategory, operatingSystem and an Offer per pricing tier",
        "links shared in comparison threads",
        # Added because Titan audited ITSELF and was told to add LocalBusiness
        # schema. A SaaS is not a local business, and advising a software
        # company to publish an address and opening hours is wrong advice that
        # would have been given to every SaaS client too.
        local_business=False),
    "tradesperson": _V(
        "tradesperson", "Trades business", "HomeAndConstructionBusiness",
        ("installateur", "elektriker", "klempner", "plumber", "electrician",
         "handwerker", "sanitär", "heizung", "roofing"),
        "the completed-work photography",
        "completed bathroom installation, wide shot",
        "Trades business",
        "areaServed — for a callout trade this is the single most important "
        "property, and availableService per job type",
        "job photos shared by customers recommending you"),
}

# A generic profile so an unrecognised trade still gets sane, non-food advice
# instead of being told its food photography is the product.
GENERIC = Vertical(
    "", "Business", "LocalBusiness",  # noqa: E501 - generic fallback stays local
    (),
    "the imagery on the site",
    "the main product or service, photographed clearly",
    "Business",
    "the properties that match what you sell",
    "links shared by customers",
)


def profile(key: str) -> Vertical:
    return VERTICALS.get((key or "").strip().lower(), GENERIC)


def detect(html: str, industry_hint: str = "") -> str:
    """Best-matching vertical key, or "" when the evidence is too thin.

    The industry hint carries more weight than page text: an owner declaring
    "Zahnarztpraxis" at onboarding is better evidence than a stray word in a
    footer, and a single incidental keyword should never re-label a business.
    """
    hint = (industry_hint or "").strip().lower()
    for key, v in VERTICALS.items():
        if hint == key or hint == v.label.lower():
            return key
    if hint:
        # A hint can match several verticals at once — "Zahnarztpraxis"
        # contains both "praxis" (healthcare) and "zahnarzt" (dentist). Taking
        # the first match returned generic healthcare, so a dental practice was
        # handed MedicalClinic schema when Dentist exists. The longest matched
        # signal is the more specific term, and specificity is what wins.
        best_key, best_len = "", 0
        for key, v in VERTICALS.items():
            for w in v.signals:
                if w in hint and len(w) > best_len:
                    best_key, best_len = key, len(w)
        if best_key:
            return best_key

    low = f"{hint} {html or ''}".lower()
    best, score = "", 0
    for key, v in VERTICALS.items():
        n = sum(1 for w in v.signals if w in low)
        if n > score:
            best, score = key, n
    return best if score >= 2 else ""


# Back-compat re-exports: local_seo imported these names directly.
VERTICAL_SCHEMA = {k: v.schema_type for k, v in VERTICALS.items()}
VERTICAL_SIGNALS = {k: list(v.signals) for k, v in VERTICALS.items()}
