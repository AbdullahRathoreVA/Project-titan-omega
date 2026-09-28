"""Check LLM output against its evidence before a customer sees it.

Used for text customers read: knowledge.answer() (the voice receptionist)
and client reports. A model told to use only the given passages usually
does; this makes it a check rather than a hope.

The main check is number grounding: every figure in the output must appear in
the evidence it was built from, so the receptionist can't invent a price or
an opening time.

Verdicts:

    PASS      grounded; show it
    RETRY     fixable defect; generate again
    REJECT    ungrounded or prohibited; don't show it to a customer
    ESCALATE  needs a human

Limitation: it confirms claims trace to the source, not that a grounded
sentence actually answers the question. A model can quote a real number
about the wrong thing.
"""

from __future__ import annotations

import re
from typing import Optional

PASS = "pass"
RETRY = "retry"
REJECT = "reject"
ESCALATE = "escalate"

# Figures worth grounding. Bare small integers are skipped ("two sentences",
# "the 3 findings" are prose, not claims), otherwise the check is mostly noise.
_MONEY = re.compile(r"(?:[$£€₨]|PKR|USD|EUR|GBP|Rs\.?)\s?\d[\d,.]*", re.I)
_PERCENT = re.compile(r"\d[\d.]*\s?%")
_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\s?(?:am|pm)?\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)
_BIG_NUMBER = re.compile(r"\b\d[\d,]{2,}(?:\.\d+)?\b")

# Claims a business must never make through Titan.
_PROHIBITED: tuple[tuple[str, str], ...] = (
    (r"\bguarantee(?:d|s)?\b(?![^.]{0,30}\bnot\b)", "an unqualified guarantee"),
    (r"\b(?:#1|number one|best in the world|world'?s best)\b",
     "an unverifiable superlative"),
    (r"\brisk[- ]free\b", "a risk-free claim"),
    (r"\b(?:certified|accredited|award[- ]winning)\b",
     "a credential claim Titan cannot verify"),
    (r"\bas an ai\b|\bi'?m an ai\b|\blanguage model\b",
     "the model breaking character to the customer"),
    (r"\blorem ipsum\b|\bTODO\b|\bFIXME\b|\bplaceholder\b",
     "unfinished placeholder text"),
    (r"<[a-z][a-z ]{2,30}>", "an unfilled template placeholder"),
)

_COMPILED_PROHIBITED = tuple((re.compile(p, re.I), why)
                             for p, why in _PROHIBITED)


def _figures(text: str) -> list[str]:
    """Every claim-shaped figure in a piece of text."""
    out: list[str] = []
    for pattern in (_MONEY, _PERCENT, _TIME, _BIG_NUMBER):
        out.extend(m.group().strip() for m in pattern.finditer(text or ""))
    return out


def _normalise(figure: str) -> str:
    """Compare figures by their digits, so '1,200' matches '1200'."""
    return re.sub(r"[^\d]", "", figure)


def check(output: str, *, evidence: str = "", question: str = "",
          kind: str = "customer text") -> dict:
    """Check one generated artifact against the evidence it came from.

    `evidence` is the source material the model was given. Figures from the
    question also count as grounded ("do you open at 9?" -> "9").
    """
    output = output or ""
    haystack = f"{evidence or ''}\n{question or ''}"

    if not output.strip():
        return {"verdict": RETRY, "ok": False, "kind": kind,
                "reasons": ["The model returned nothing."],
                "ungrounded_figures": [], "prohibited": []}

    prohibited = [why for pattern, why in _COMPILED_PROHIBITED
                  if pattern.search(output)]

    ungrounded: list[str] = []
    if evidence or question:
        grounded = {_normalise(f) for f in _figures(haystack)}
        # Also accept any digit run in the source, so "50%" matches "50 percent" and
        # "1200" matches "PKR 1,200".
        grounded |= {_normalise(m.group())
                     for m in re.finditer(r"\d[\d,.]*", haystack)}
        for figure in _figures(output):
            digits = _normalise(figure)
            if digits and digits not in grounded:
                ungrounded.append(figure)

    reasons: list[str] = []
    verdict = PASS
    if prohibited:
        verdict = REJECT
        reasons += [f"Contains {why}." for why in prohibited]
    if ungrounded:
        verdict = REJECT
        reasons.append(
            "These figures do not appear in the source material and were "
            "invented by the model: " + ", ".join(sorted(set(ungrounded))))

    return {
        "verdict": verdict,
        "ok": verdict == PASS,
        "kind": kind,
        "reasons": reasons or ["Every figure traces to the source material."],
        "ungrounded_figures": sorted(set(ungrounded)),
        "prohibited": prohibited,
        "checked_figures": len(_figures(output)),
        "note": ("Verifies that claims TRACE to the source, not that they "
                 "answer the question correctly. A grounded figure about the "
                 "wrong subject would still pass — a smaller and rarer failure "
                 "than invention, and one this does not claim to catch."),
    }


def safe_or_none(output: str, **kw) -> Optional[str]:
    """The output if it passed, else None - for callers that have a fallback."""
    return output if check(output, **kw)["ok"] else None
