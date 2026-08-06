"""Evidence ledger — facts about a business, priced by how they were observed.

Pattern ported from trycompai/crm (MIT), whose README states the rule plainly:

    "Nothing about a person is guessed. No tool accepts a confidence score,
    because a model asked to grade its own certainty will, and it will be wrong
    in the direction that makes it look useful. Tools report what they
    *observed* ... and a ledger prices the evidence. Strong evidence writes to
    the record. Weak evidence becomes a suggestion a human settles. A
    confidently wrong fact about a customer is worse than a blank field,
    because nobody can tell it is wrong."

No code is copied — that project is a TypeScript/Bun monorepo and this is
Python. What is ported is the idea, which Titan needed badly: its CRM stored a
name, a phone and an address with no record of where any of them came from, so
a value scraped from a page footer was indistinguishable from one Abdullah
typed himself.

Titan is unusually well placed to apply it, because it already crawls client
sites for the SEO and compliance audit. The same fetch can *observe* facts.

The source ranking is not a guess about accuracy in the abstract — it is a
claim about how strongly each surface is tied to being correct:

  manual          Abdullah typed it. Nothing outranks a human.
  site.impressum  German law (§5 DDG) REQUIRES the operator's real legal name
                  and physical address here, and getting it wrong is the fine
                  Titan's whole compliance pitch is about. That makes it the
                  strongest machine-observable source on the internet for these
                  fields — stronger than schema, which nobody audits.
  site.schema     Published JSON-LD. Deliberate, structured, but self-declared.
  site.contact    A contact page. Intentional, unstructured.
  site.footer     Footer NAP. Often stale, often a template default.
  site.title      The page title. Weak: marketing copy, not a fact.

A model is never asked "how sure are you". It is only ever asked what it saw,
and the source it saw it on decides the weight.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import events


@dataclass(frozen=True)
class Source:
    key: str
    strength: float
    label: str
    why: str


SOURCES: dict[str, Source] = {
    "manual": Source(
        "manual", 1.00, "Entered by hand",
        "A person typed it. Nothing a machine observes outranks this."),
    "site.impressum": Source(
        "site.impressum", 0.95, "Impressum (legally required)",
        "§5 DDG requires the operator's real legal name and physical address "
        "here, and an incorrect one is a fineable offence — so it is the "
        "strongest machine-observable source for these fields."),
    "site.schema": Source(
        "site.schema", 0.85, "Schema.org markup",
        "Published deliberately and structured, but self-declared and audited "
        "by nobody."),
    "site.contact": Source(
        "site.contact", 0.70, "Contact page",
        "Intentional but unstructured; often out of date."),
    "site.footer": Source(
        "site.footer", 0.60, "Page footer",
        "Frequently a template default left unchanged."),
    "site.title": Source(
        "site.title", 0.40, "Page title",
        "Marketing copy. Weak evidence for a fact about the business."),
}

# At or above this, an observation writes straight to the record. Below it, the
# observation is filed as a SUGGESTION for a human to settle. The line sits
# between schema (0.85, published deliberately) and a contact page (0.70,
# unstructured), because that is where "the business asserted this" stops.
WRITE_THRESHOLD = 0.75

_lock = threading.RLock()
# subject_id -> field -> list of observations
_ledger: dict[str, dict[str, list]] = {}


def observe(subject_id: str, field: str, value: str, source: str,
            note: str = "") -> dict:
    """File one observation. Never raises, never guesses.

    `source` must be a known observation surface. A caller cannot pass a
    confidence number — that is the entire point of the pattern.
    """
    src = SOURCES.get(source)
    if src is None:
        raise ValueError(
            f"Unknown source {source!r}. Observations must name a surface "
            f"that was actually looked at, one of: {sorted(SOURCES)}")
    value = (value or "").strip()
    if not value:
        return {}

    entry = {
        "value": value[:300],
        "source": src.key,
        "strength": src.strength,
        "label": src.label,
        "ts": time.time(),
        "note": note[:200],
        "settled": src.key == "manual",     # human input needs no settling
    }
    with _lock:
        _ledger.setdefault(subject_id, {}).setdefault(field, []).append(entry)

    events.emit(events.MEMORY_UPDATED, {
        "subject": subject_id, "field": field, "source": src.key,
        "writes": src.strength >= WRITE_THRESHOLD,
    }, actor="evidence")
    return entry


def _ranked(subject_id: str, field: str) -> list:
    with _lock:
        rows = list(_ledger.get(subject_id, {}).get(field, []))
    # Strongest source first; newer wins a tie, because a business that changed
    # its phone number republished it, it did not republish the old one.
    return sorted(rows, key=lambda r: (-r["strength"], -r["ts"]))


def best(subject_id: str, field: str) -> Optional[dict]:
    """The observation that should be treated as true, if any qualifies."""
    for row in _ranked(subject_id, field):
        if row["strength"] >= WRITE_THRESHOLD:
            return row
    return None


def suggestions(subject_id: str) -> list:
    """Observations too weak to write, awaiting a human decision.

    A field that already has a strong value produces no suggestion — there is
    nothing to settle. Conflicts between two WEAK observations are surfaced,
    because that is precisely the case where guessing does damage.
    """
    out = []
    with _lock:
        fields = dict(_ledger.get(subject_id, {}))
    for field in sorted(fields):
        if best(subject_id, field) is not None:
            continue
        rows = [r for r in _ranked(subject_id, field) if not r["settled"]]
        if not rows:
            continue
        distinct = {r["value"] for r in rows}
        out.append({
            "field": field,
            "candidates": rows[:4],
            "conflict": len(distinct) > 1,
            "prompt": (
                f"{len(distinct)} different values were observed for {field}. "
                f"None came from a source strong enough to trust automatically."
                if len(distinct) > 1 else
                f"{field} was only seen on {rows[0]['label'].lower()}, which is "
                f"not strong enough to write without you confirming it."),
        })
    return out


def settle(subject_id: str, field: str, value: str) -> dict:
    """A human decides. Recorded as manual, so it outranks everything after."""
    with _lock:
        for row in _ledger.get(subject_id, {}).get(field, []):
            row["settled"] = True
    return observe(subject_id, field, value, "manual", note="settled by hand")


def record(subject_id: str) -> dict:
    """What Titan believes about this business, and why.

    Every field carries its provenance. A blank field is an honest blank, not a
    plausible guess — which is the whole reason this module exists.
    """
    with _lock:
        fields = sorted(_ledger.get(subject_id, {}))
    known, unresolved = {}, {}
    for field in fields:
        top = best(subject_id, field)
        if top:
            known[field] = {
                "value": top["value"],
                "source": top["source"],
                "why_trusted": SOURCES[top["source"]].why,
            }
        else:
            rows = _ranked(subject_id, field)
            if rows:
                unresolved[field] = {
                    "best_seen": rows[0]["value"],
                    "source": rows[0]["source"],
                    "reason": (f"{rows[0]['label']} is below the threshold for "
                               f"writing automatically."),
                }
    return {
        "subject": subject_id,
        "known": known,
        "unresolved": unresolved,
        "suggestions": suggestions(subject_id),
        "threshold": WRITE_THRESHOLD,
        "note": ("Fields under 'unresolved' are deliberately blank rather than "
                 "filled with a plausible value. A confidently wrong fact about "
                 "a client is worse than an empty field, because nobody can "
                 "tell it is wrong."),
    }


def observe_from_page(subject_id: str, html: str, *,
                      impressum: bool = False) -> list:
    """Extract facts from a page Titan already fetched, and file each with the
    surface it was seen on.

    This is the whole point of the pattern: the audit crawl is happening
    anyway, so the same bytes that produce SEO findings can also produce a
    provenance-tagged record of the business — for free, with no model asked to
    guess anything.

    `impressum=True` marks the page as the legally-required imprint, which
    upgrades everything found on it to the strongest machine-observable source.
    Only pass it when the page genuinely is that page.
    """
    import json as _json
    import re

    html = html or ""
    filed: list = []
    surface = "site.impressum" if impressum else "site.footer"

    def file(field: str, value: str, source: str) -> None:
        row = observe(subject_id, field, value, source)
        if row:
            filed.append({"field": field, **row})

    # --- JSON-LD: structured and deliberate, so it outranks scraped text ----
    for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
            html, re.I | re.S):
        try:
            data = _json.loads(block.strip())
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for n in (node.get("@graph") if isinstance(node.get("@graph"), list)
                      else [node]):
                if not isinstance(n, dict):
                    continue
                if isinstance(n.get("name"), str):
                    file("business_name", n["name"], "site.schema")
                if isinstance(n.get("telephone"), str):
                    file("phone", n["telephone"], "site.schema")
                if isinstance(n.get("email"), str):
                    file("email", n["email"], "site.schema")
                addr = n.get("address")
                if isinstance(addr, dict):
                    parts = [addr.get(k) for k in
                             ("streetAddress", "postalCode", "addressLocality")]
                    joined = ", ".join(p for p in parts if isinstance(p, str))
                    if joined:
                        file("address", joined, "site.schema")
                    if isinstance(addr.get("addressLocality"), str):
                        file("city", addr["addressLocality"], "site.schema")

    # --- plain text on the page ------------------------------------------
    tel = re.search(r'href=["\']tel:([+0-9()\s.\-]{6,})["\']', html, re.I)
    if tel:
        file("phone", tel.group(1).strip(), surface)

    mail = re.search(r'href=["\']mailto:([^"\'?]+)["\']', html, re.I)
    if mail:
        file("email", mail.group(1).strip(), surface)

    # A German Impressum must state the VAT id when the operator has one, so
    # finding it there is unusually strong evidence of the legal entity.
    vat = re.search(r'\b(DE\d{9}|ATU\d{8}|[A-Z]{2}\d{8,12})\b', html)
    if vat and impressum:
        file("vat_id", vat.group(1), "site.impressum")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title:
        name = re.sub(r"\s*[|–—-]\s*.*$", "", title.group(1).strip())
        if 2 < len(name) < 80:
            file("business_name", name, "site.title")

    return filed


def sources() -> dict:
    return {
        "sources": [
            {"key": s.key, "strength": s.strength, "label": s.label,
             "why": s.why, "writes_automatically": s.strength >= WRITE_THRESHOLD}
            for s in sorted(SOURCES.values(), key=lambda s: -s.strength)
        ],
        "threshold": WRITE_THRESHOLD,
        "rule": ("Observations name the surface they were seen on. Nothing "
                 "accepts a self-reported confidence score."),
    }


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"ledger": {s: {f: list(rows) for f, rows in fields.items()}
                           for s, fields in _ledger.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    raw = data.get("ledger")
    if not isinstance(raw, dict):
        return
    clean: dict[str, dict[str, list]] = {}
    for subject, fields in raw.items():
        if not isinstance(fields, dict):
            continue
        for field, rows in fields.items():
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict) or r.get("source") not in SOURCES:
                    continue
                try:
                    clean.setdefault(str(subject), {}).setdefault(str(field), []).append({
                        "value": str(r.get("value", ""))[:300],
                        "source": r["source"],
                        "strength": SOURCES[r["source"]].strength,
                        "label": SOURCES[r["source"]].label,
                        "ts": float(r.get("ts", 0) or 0),
                        "note": str(r.get("note", ""))[:200],
                        "settled": bool(r.get("settled")),
                    })
                except (TypeError, ValueError):
                    continue
    with _lock:
        _ledger.clear()
        _ledger.update(clean)


def reset() -> None:
    with _lock:
        _ledger.clear()
