"""Learning layer: adapt opportunity ranking to what the founder actually does.

The opportunity engine scores candidates with a fixed formula over expected
revenue, difficulty, risk and time, so ranking never changes with use. Here,
every executed or dismissed opportunity becomes a labelled example. A Naive
Bayes classifier over the title and rationale learns which kinds get acted on
and re-ranks new candidates, blended with the formula score and weighted by
how much evidence there is.

- Pure stdlib (no numpy/sklearn) for a small container.
- Below MIN_TRAIN it doesn't predict. Accuracy is cross-validated on held-out
  data, and the model's influence grows with evidence so an early model can't
  dominate.
- The learned tokens are exposed, so the dashboard can show why something
  ranked high.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter
from typing import Iterable

MIN_TRAIN = 10          # too little data below this to predict
CONFIDENT_AT = 35       # examples before the model fully outranks the formula

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "as", "it",
    "its", "this", "that", "these", "those", "i", "my", "me", "you", "your",
    "we", "our", "they", "them", "have", "has", "had", "do", "does", "did",
    "not", "no", "so", "if", "then", "than", "there", "here", "what", "which",
    "who", "how", "can", "will", "would", "could", "should", "just", "any",
    "all", "some", "into", "via", "per", "new", "add", "more",
}

_lock = threading.RLock()

# label 1 = pursued, 0 = dismissed
_examples: list[tuple[str, int]] = []
_model: "_NaiveBayes | None" = None
_dirty = True


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z'-]{2,}", (text or "").lower())
    out = [w for w in words if w not in STOPWORDS]
    out += [f"{a}_{b}" for a, b in zip(out, out[1:])]
    return out


class _NaiveBayes:
    """Multinomial Naive Bayes with Laplace smoothing."""

    def __init__(self) -> None:
        self.counts: dict[int, Counter] = {0: Counter(), 1: Counter()}
        self.totals: dict[int, int] = {0: 0, 1: 0}
        self.docs: dict[int, int] = {0: 0, 1: 0}
        self.vocab: set[str] = set()

    def fit(self, samples: Iterable[tuple[str, int]]) -> None:
        for text, label in samples:
            toks = tokens(text)
            self.counts[label].update(toks)
            self.totals[label] += len(toks)
            self.docs[label] += 1
            self.vocab.update(toks)

    def predict(self, text: str) -> float:
        n = self.docs[0] + self.docs[1]
        if n == 0:
            return 0.5
        v = max(len(self.vocab), 1)
        logp: dict[int, float] = {}
        for label in (0, 1):
            logp[label] = math.log((self.docs[label] + 1) / (n + 2))
            denom = self.totals[label] + v
            for tok in tokens(text):
                logp[label] += math.log((self.counts[label][tok] + 1) / denom)
        hi = max(logp.values())
        e0, e1 = math.exp(logp[0] - hi), math.exp(logp[1] - hi)
        return e1 / (e0 + e1)

    def top_tokens(self, label: int = 1, n: int = 10) -> list[tuple[str, float]]:
        other = 1 - label
        scored: list[tuple[str, float]] = []
        v = len(self.vocab) or 1
        for tok in self.vocab:
            a = self.counts[label][tok]
            if a < 2:
                continue
            b = self.counts[other][tok]
            ratio = ((a + 1) / (self.totals[label] + v)) / \
                    ((b + 1) / (self.totals[other] + v))
            scored.append((tok.replace("_", " "), round(ratio, 2)))
        scored.sort(key=lambda x: -x[1])
        return scored[:n]


def record(text: str, pursued: bool) -> None:
    """Record one real decision. Called when an opportunity is executed/dismissed."""
    global _dirty
    if not text:
        return
    with _lock:
        _examples.append((text[:2000], 1 if pursued else 0))
        # Keep memory bounded on a small container.
        if len(_examples) > 4000:
            del _examples[:1000]
        _dirty = True


def _train() -> "_NaiveBayes | None":
    global _model, _dirty
    with _lock:
        if len(_examples) < MIN_TRAIN:
            return None
        if _model is not None and not _dirty:
            return _model
        m = _NaiveBayes()
        m.fit(_examples)
        _model = m
        _dirty = False
        return m


def accuracy(folds: int = 5) -> float | None:
    """Cross-validated accuracy. Never scored on data it trained on."""
    with _lock:
        data = list(_examples)
    if len(data) < MIN_TRAIN:
        return None
    data.sort(key=lambda d: hash(d[0]) & 0xFFFF)   # de-correlate ordering
    correct = total = 0
    for f in range(folds):
        test = [d for i, d in enumerate(data) if i % folds == f]
        train = [d for i, d in enumerate(data) if i % folds != f]
        if not test or not train:
            continue
        m = _NaiveBayes()
        m.fit(train)
        for text, label in test:
            if (m.predict(text) >= 0.5) == bool(label):
                correct += 1
            total += 1
    return round(correct / total, 3) if total else None


def rerank(text: str, formula_score: float) -> tuple[float, str]:
    """Blend the learned prediction with the engine's formula score.

    formula_score is the existing 0..100 priority. Returns the adjusted score
    and a readable reason, so the UI never shows an unexplained number.
    """
    m = _train()
    if m is None:
        need = MIN_TRAIN - len(_examples)
        return formula_score, (
            f"formula only — {need} more of your decisions needed before "
            f"Titan can learn your preference")

    p = m.predict(text)
    n = len(_examples)
    trust = min(n / CONFIDENT_AT, 1.0)
    blended = formula_score * (1 - trust) + (p * 100) * trust
    return round(blended, 1), (
        f"you pursue {p * 100:.0f}% of opportunities like this "
        f"(learned from {n} decisions, weighted {trust * 100:.0f}%)")


def stats() -> dict:
    with _lock:
        data = list(_examples)
    pursued = sum(1 for _, l in data if l == 1)
    m = _train()
    acc = accuracy()
    return {
        "examples": len(data),
        "pursued": pursued,
        "dismissed": len(data) - pursued,
        "ready": len(data) >= MIN_TRAIN,
        "needs": max(0, MIN_TRAIN - len(data)),
        "trust_pct": round(min(len(data) / CONFIDENT_AT, 1.0) * 100),
        "accuracy": acc,
        "accuracy_label": (f"{acc * 100:.0f}% on held-out data" if acc is not None
                           else "not enough data to measure honestly"),
        "learned_pursue": m.top_tokens(1, 8) if m else [],
        "learned_ignore": m.top_tokens(0, 6) if m else [],
        "vocab": len(m.vocab) if m else 0,
    }


# ----------------------------------------------------------------- teacher ---
# Cold start: waiting for 10 real decisions would leave ranking on the fixed
# formula for weeks, so the LLM labels the seed opportunities first. Real
# decisions override these later; the model is only a bootstrap.

_TEACHER_SYSTEM = (
    "You advise a solo technical founder in Pakistan with no capital, no team, "
    "and an unlaunched digital product. He needs revenue in weeks, not quarters. "
    "You judge whether he would realistically pursue a given business "
    "opportunity NOW. Work that reaches paying customers fast scores HIGH. "
    "Internal tooling, compliance, enterprise infrastructure and anything "
    "requiring a team or existing revenue scores LOW."
)

_TEACHER_PROMPT = (
    "Opportunity:\n{text}\n\n"
    'Reply with JSON only: {{"score": <0-10 how likely he pursues this now>}}'
)


def teach_from_llm(items: Iterable[tuple[str, float]], max_items: int = 12) -> dict:
    """Label opportunities with the LLM chain so ranking works from day one.

    items: (text, formula_score) pairs. Returns a summary dict; never raises.
    """
    from . import llm as _llm  # local import: avoids a cycle at module load

    labelled = skipped = 0
    for text, _formula in list(items)[:max_items]:
        if not text or not text.strip():
            continue
        raw = _llm.complete(_TEACHER_SYSTEM,
                            _TEACHER_PROMPT.format(text=text[:1200]),
                            max_tokens=120)
        score = _parse_score(raw)
        if score is None:
            skipped += 1
            continue
        # The middle is ambiguous - learning from it only adds noise.
        if 4.0 < score < 6.0:
            skipped += 1
            continue
        record(text, score >= 6.0)
        labelled += 1

    return {"labelled": labelled, "skipped": skipped,
            "source": "llm_teacher", "stats": stats()}


def _parse_score(raw: str | None) -> float | None:
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    if start != -1:
        for end in range(len(raw), start, -1):
            try:
                obj = json.loads(raw[start:end])
                if isinstance(obj, dict) and "score" in obj:
                    return max(0.0, min(10.0, float(obj["score"])))
            except Exception:
                continue
    m = re.search(r"\b(10|\d(?:\.\d)?)\b", raw)
    return max(0.0, min(10.0, float(m.group(1)))) if m else None


def export_state() -> dict:
    """For persistence.py so learning survives a restart."""
    with _lock:
        return {"examples": list(_examples)}


def import_state(data: dict) -> None:
    global _dirty
    if not isinstance(data, dict):
        return
    rows = data.get("examples") or []
    with _lock:
        _examples.clear()
        for r in rows:
            if isinstance(r, (list, tuple)) and len(r) == 2:
                _examples.append((str(r[0])[:2000], int(bool(r[1]))))
        _dirty = True
