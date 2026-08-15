"""Titan's own published contact details — the single place they come from.

The 25 landing pages cap at **89/B** on Titan's own audit for exactly one
reason: no phone number and no postal address. That check fails HONESTLY. The
pages carry no contact block because there were no details to carry, and a
plausible-looking one would be the precise failure the rest of this codebase
exists to prevent — Titan sells the finding that a missing Impressum is worth
a fine, so a fabricated address on its own site is not a cosmetic lie.

So: everything here is read from the environment, and **nothing is published
unless it is complete.**

A partial address is not published at all. That is deliberate and it is not
pedantry:

  - Titan's own `client_seo._has_address` needs a postcode standing next to a
    place name ("52200 Sialkot") or a street number next to a street word.
    A bare postcode matches neither, so publishing one would leave the check
    failing while making the page *look* like it had been addressed.
  - §5 DDG and every equivalent Impressum rule require a postal address a
    letter can actually reach. A postcode alone is not one.

The phone is independent of the address — one can publish without the other,
because they satisfy different halves of the NAP check.

Set, all of them, to publish an address:

    TITAN_PHONE       e.g. +92 321 8811027
    TITAN_STREET      street and building number
    TITAN_LOCALITY    city or town
    TITAN_POSTCODE    postal code
    TITAN_COUNTRY     country name

`status()` names exactly which of those are missing, so the dashboard can say
what is absent rather than reporting a silent zero.
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

    Deliberately not reformatted. Turning "03218811027" into "+92 321 8811027"
    means asserting the country, and a wrong country code on a published
    number is a number that does not ring.
    """
    return _env("TITAN_PHONE") or None


def address() -> Optional[dict]:
    """The published postal address, or None unless EVERY part is present."""
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
    """What is actually published, and what is not. Never guesses."""
    p, a = phone(), address()
    notes = []
    if p and not p.lstrip().startswith("+"):
        # Not an error and not corrected here — a local-format number is
        # correct for local callers and unusable for everyone else, and only
        # Abdullah can say which audience the published number is for.
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
    """A visible contact block, or "" when there is nothing to publish.

    Visible text on purpose. `client_seo._visible_text` strips script, style,
    comments and attributes before looking for a phone or an address, which is
    what closed the false pass where a Cloudflare beacon URL counted as a phone
    number. Contact details that exist only in JSON-LD would not be seen by
    Titan's own check — nor by a human.
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

    # The <address> ELEMENT is emitted only when there is a postal address in
    # it. `client_seo._has_address` returns True for any `<address\b` it finds,
    # so wrapping a phone-only block in one would make Titan's own audit report
    # a postal address on a page that has none. That is Titan gaming its own
    # check, and it is the same shape as the Cloudflare-beacon false pass that
    # had it reporting a phone number for every site behind Cloudflare.
    tag = "address" if a else "p"
    return f"<{tag}>" + " · ".join(rows) + f"</{tag}>"
