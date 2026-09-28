"""Titan's own published contact details, all from one place.

Titan's landing pages lose points on its own audit for having no phone number
or postal address. That's correct: there were no details to publish, and a
made-up address would be exactly what Titan warns clients about (a missing
Impressum can mean a fine).

So everything comes from the environment, and nothing is published unless
it's complete. A partial address isn't published at all:

  - `client_seo._has_address` needs a postcode next to a place name
    ("52200 Sialkot") or a street number next to a street word. A bare
    postcode matches neither, so it would leave the check failing while
    looking addressed.
  - §5 DDG and similar Impressum rules need a postal address a letter can
    reach. A postcode alone isn't one.

The phone is independent of the address; they cover different parts of the
NAP check.

Set all of these to publish an address:

    TITAN_PHONE       e.g. +92 321 8811027
    TITAN_STREET      street and building number
    TITAN_LOCALITY    city or town
    TITAN_POSTCODE    postal code
    TITAN_COUNTRY     country name

`status()` names the ones that are missing, so the dashboard can say what's
absent.
"""

from __future__ import annotations

import os
from typing import Optional

_ADDRESS_FIELDS = (
    ("TITAN_STREET", "street"),
    ("TITAN_LOCALITY", "locality"),
    ("TITAN_POSTCODE", "postcode"),
    ("TITAN_COUNTRY", "country"),
)


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip()


def phone() -> Optional[str]:
    """The published number, exactly as supplied. None when unset.

    Not reformatted: turning "03218811027" into "+92 321 8811027" means
    assuming the country, and a wrong country code is a number that doesn't
    ring.
    """
    return _env("TITAN_PHONE") or None


def address() -> Optional[dict]:
    """The published postal address, or None unless every part is present."""
    parts = {name: _env(key) for key, name in _ADDRESS_FIELDS}
    if not all(parts.values()):
        return None
    return parts


def missing() -> list:
    """Which env vars are still needed, in the order they would be filled."""
    out = [key for key, _ in _ADDRESS_FIELDS if not _env(key)]
    if not _env("TITAN_PHONE"):
        out.insert(0, "TITAN_PHONE")
    return out


def status() -> dict:
    """What's published and what isn't. Never guesses."""
    p, a = phone(), address()
    notes = []
    if p and not p.lstrip().startswith("+"):
        # Not an error and not corrected here: a local-format number works for local
        # callers only, and only the founder knows which audience it's for.
        notes.append("The number has no country code, so it is dialable only "
                     "from inside its own country.")
    if not a and any(_env(k) for k, _ in _ADDRESS_FIELDS):
        notes.append("A partial address was supplied and is NOT published: "
                     "an address a letter cannot reach satisfies neither "
                     "Titan's own check nor an Impressum obligation.")
    return {
        "phone": p,
        "address": a,
        "phone_published": p is not None,
        "address_published": a is not None,
        "missing_env": missing(),
        "notes": notes,
    }


def schema_fragment() -> dict:
    """`telephone` / `address` for an Organization node. Empty when unset."""
    out: dict = {}
    p, a = phone(), address()
    if p:
        out["telephone"] = p
    if a:
        out["address"] = {
            "@type": "PostalAddress",
            "streetAddress": a["street"],
            "addressLocality": a["locality"],
            "postalCode": a["postcode"],
            "addressCountry": a["country"],
        }
    return out


def html_block() -> str:
    """A visible contact block, or "" when there's nothing to publish.

    Visible text on purpose. `client_seo._visible_text` strips scripts,
    styles, comments and attributes before looking for a phone or address, so
    details that only exist in JSON-LD wouldn't be found by Titan's own check,
    or by a person.
    """
    import html as _html

    p, a = phone(), address()
    if not p and not a:
        return ""

    rows = []
    if p:
        tel = "".join(c for c in p if c.isdigit() or c == "+")
        rows.append(f'<a href="tel:{_html.escape(tel)}">{_html.escape(p)}</a>')
    if a:
        rows.append(_html.escape(
            f'{a["street"]}, {a["postcode"]} {a["locality"]}, {a["country"]}'))

    # The <address> element is only used when there's a postal address in it.
    # `client_seo._has_address` returns True for any `<address\b`, so wrapping a
    # phone-only block in one would make Titan's own audit report a postal
    # address that isn't there.
    tag = "address" if a else "p"
    return f"<{tag}>" + " · ".join(rows) + f"</{tag}>"
