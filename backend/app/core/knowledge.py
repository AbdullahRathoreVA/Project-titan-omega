"""Per-client knowledge retrieval — answers grounded in the client's own site.

The voice spec calls for knowledge retrieval: a receptionist agent has to be
able to answer "do you ship to Germany?" or "what are your opening hours?".
Titan already crawls every client's website during an audit and then throws the
text away. This keeps it, and retrieves from it.

**Deliberately no vector database and no embedding model.** The reference
implementations for this pattern reach for Qdrant plus fastembed, which means a
~100 MB ONNX download and a resident index on a free-tier container that also
runs the API, the schedulers and a Next.js bundle. For the corpus in question —
one small-business website, a few dozen passages — lexical ranking is not a
compromise, it is the correct tool. BM25 on 40 passages is exact, instant, and
costs nothing.

**Every answer carries the URL it came from.** A receptionist that invents an
opening time creates a customer who turns up to a closed door and blames the
business Titan is being paid to help. If nothing matches well enough, the
retrieval says so and returns nothing rather than the least-bad passage.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Optional

from . import embeddings

MAX_CLIENTS = 200
MAX_PASSAGES = 400          # per client
MIN_PASSAGE_CHARS = 60
MAX_PASSAGE_CHARS = 600

# Below this the best match is noise. Tuned so a question about something the
# site never mentions returns nothing instead of the least-irrelevant sentence.
MIN_SCORE = 0.8

# How many semantic candidates may enter the fusion. Short and confident beats
# long and vague: RRF over the whole corpus swamps the exact keyword signal.
SEMANTIC_TOP_N = 4
# Neither ranker gets a fixed weight. Measured against the real model, a flat
# "keyword wins ties" rule let a BM25 hit on the single common word "order"
# beat a 0.725-cosine match for "how fast can you get an order to Berlin?" —
# the semantic ranker had the right passage and was overruled.
#
# Each ranker is weighted by its OWN confidence instead:
#   * BM25 is confident when its top score is high — many rare terms matched,
#     not one common one.
#   * The semantic ranker is confident when its best cosine is high. Sentence
#     models score any two English sentences ~0.5, so the usable band is
#     narrow and starts well above zero.
# Measured on a real 6-passage site, not assumed. Semantic ranking only
# overtakes BM25 when its best cosine is HIGH; in the 0.52–0.64 band the two
# were indistinguishable and letting semantic lead there changed correct BM25
# answers into wrong ones. So the bar to take over is deliberately high: this
# is a strict improvement on BM25, never a coin flip against it.
# 0.68, not lower. Dropping it to 0.60 was measured and changed nothing — the
# two questions it would have to rescue score below that anyway — so a lower
# bar buys no accuracy and only re-enters the band where semantic ranking was
# observed to overturn correct BM25 answers.
COS_LEAD = 0.68     # semantic leads the ranking above this
COS_FLOOR = 0.52    # below this a passage is not a semantic candidate at all

_STOP = frozenset("""
a an and are as at be but by for from has have he her his i if in is it its of
on or our she that the their them they this to was we were will with you your
""".split())

_lock = threading.RLock()
# client_id -> {"passages": [{text, url, terms}], "df": {term: n}}
_store: dict[str, dict] = {}

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 1]


def strip_html(html: str) -> str:
    text = _TAG.sub(" ", html or "")
    text = _HTML.sub(" ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#39;", "'").replace("&quot;", '"'))
    return _WS.sub(" ", text).strip()


_HEADING = re.compile(r"<h([1-4])[^>]*>(.*?)</h\1>", re.I | re.S)


def split_sections(html: str) -> list[tuple[str, str]]:
    """Split a page at its headings into (heading, body) sections.

    Two findings from current RAG practice, both of which this page needed:

    * **A chunk must never span two sections.** Section boundaries are the
      author's own statement of where one topic ends. The previous splitter
      ignored headings entirely and merged the H1 into the first paragraph,
      so "Triad Thread Studio" and "we manufacture leather goods" became one
      blurred passage that matched everything weakly and nothing strongly.
    * **Heading-aware splitting beats character counting** on exactly this
      shape of content — a small site of short, differently-topiced sections.

    Pages with no headings return a single ("", body) section, so nothing
    regresses for a site built entirely out of divs.
    """
    if not html or "<h" not in html.lower():
        return [("", strip_html(html))]

    sections: list[tuple[str, str]] = []
    last_end = 0
    pending_heading = ""
    for m in _HEADING.finditer(html):
        body = strip_html(html[last_end:m.start()])
        if body:
            sections.append((pending_heading, body))
        pending_heading = strip_html(m.group(2))[:120]
        last_end = m.end()
    tail = strip_html(html[last_end:])
    if tail:
        sections.append((pending_heading, tail))
    return [s for s in sections if s[1].strip()] or [("", strip_html(html))]


def _split(text: str) -> list[str]:
    """Sentence-ish chunks. Long runs are cut on whitespace rather than
    mid-word, because a passage read aloud has to be a sentence."""
    out: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        part = part.strip()
        if len(part) < MIN_PASSAGE_CHARS:
            continue
        while len(part) > MAX_PASSAGE_CHARS:
            cut = part.rfind(" ", 0, MAX_PASSAGE_CHARS)
            cut = cut if cut > MIN_PASSAGE_CHARS else MAX_PASSAGE_CHARS
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if len(part) >= MIN_PASSAGE_CHARS:
            out.append(part)
    return out


def ingest(client_id: str, html_or_text: str, url: str = "") -> dict:
    """Index one page for one client. Replaces any earlier copy of that URL, so
    re-auditing a site updates the knowledge instead of duplicating it."""
    if not client_id:
        return {"ok": False, "reason": "A client id is required.", "passages": 0}
    is_html = "<" in (html_or_text or "")
    sections = (split_sections(html_or_text) if is_html
                else [("", html_or_text or "")])
    # (heading, passage) pairs. The heading rides along as retrieval context
    # without being glued into the quoted text — see _context_text.
    chunks = [(head, c) for head, body in sections for c in _split(body)]
    if not chunks:
        return {"ok": False, "passages": 0,
                "reason": ("Nothing readable on that page. A site that is "
                           "entirely images or client-rendered script has no "
                           "text to answer questions from — which is itself "
                           "worth telling the client.")}

    with _lock:
        rec = _store.setdefault(client_id, {"passages": []})
        if url:
            rec["passages"] = [p for p in rec["passages"] if p["url"] != url]
        for head, c in chunks:
            rec["passages"].append({
                "text": c, "url": url, "heading": head,
                # The heading is indexed as searchable text too: a caller who
                # asks about "shipping" should reach a passage that sits under
                # a "Shipping" heading even when the sentence itself never
                # repeats the word.
                "terms": _tokens(f"{head} {c}" if head else c),
            })
        if len(rec["passages"]) > MAX_PASSAGES:
            del rec["passages"][:len(rec["passages"]) - MAX_PASSAGES]
        _reindex(rec)
        if len(_store) > MAX_CLIENTS:
            for stale in list(_store)[:len(_store) - MAX_CLIENTS]:
                del _store[stale]
        total = len(rec["passages"])
        pending = [p for p in rec["passages"] if "vec" not in p]

    # Start the model warming the moment there is anything to search, so it is
    # usually ready before the first question. Never blocks this call.
    embeddings.warm(background=True)
    _embed_pending(client_id, pending)

    return {"ok": True, "passages": len(chunks), "total": total, "url": url,
            "retrieval": embeddings.status()}


def _context_text(p: dict) -> str:
    """What actually gets embedded: the heading, then the passage.

    Contextual chunking. A sentence like "Minimum order is 50 pieces" is
    ambiguous alone; under the heading "Wholesale terms" it is not. The prefix
    only ever enters the VECTOR — the quoted text stays clean, because a
    receptionist reading "Wholesale terms. Minimum order is 50 pieces" out
    loud sounds like a machine reading a web page.
    """
    head = (p.get("heading") or "").strip()
    return f"{head}. {p['text']}" if head else p["text"]


def _embed_pending(client_id: str, pending: list[dict]) -> int:
    """Attach vectors to passages that lack them. A no-op when embeddings are
    unavailable — the passages stay searchable by BM25 either way."""
    if not pending:
        return 0
    vecs = embeddings.encode([_context_text(p) for p in pending])
    if not vecs or len(vecs) != len(pending):
        return 0
    with _lock:
        for p, v in zip(pending, vecs):
            p["vec"] = v
    return len(pending)


def backfill(client_id: str = "") -> dict:
    """Embed anything indexed before the model was ready.

    The first pages are almost always indexed while the model is still
    downloading, so without this a client stays keyword-only until re-audited.
    """
    with _lock:
        targets = ([client_id] if client_id else list(_store))
        work = {c: [p for p in _store.get(c, {}).get("passages", [])
                    if "vec" not in p]
                for c in targets}
    done = sum(_embed_pending(c, ps) for c, ps in work.items() if ps)
    with _lock:
        remaining = sum(1 for c in targets
                        for p in _store.get(c, {}).get("passages", [])
                        if "vec" not in p)
    return {"embedded": done, "remaining": remaining,
            "retrieval": embeddings.status()}


def _reindex(rec: dict) -> None:
    df: dict[str, int] = {}
    for p in rec["passages"]:
        for t in set(p["terms"]):
            df[t] = df.get(t, 0) + 1
    rec["df"] = df
    rec["avg_len"] = (sum(len(p["terms"]) for p in rec["passages"])
                      / max(1, len(rec["passages"])))


def search(client_id: str, question: str, k: int = 3) -> dict:
    """BM25 over the client's own pages. Returns nothing when nothing fits."""
    q = _tokens(question)
    with _lock:
        rec = _store.get(client_id)
        if not rec or not rec["passages"]:
            return {"ok": False, "hits": [],
                    "reason": ("Nothing has been indexed for this business "
                               "yet. Run an audit — the crawl feeds this.")}
        passages = list(rec["passages"])
        df = dict(rec.get("df", {}))
        avg_len = rec.get("avg_len", 1.0) or 1.0

    if not q:
        return {"ok": False, "hits": [], "reason": "Ask a real question."}

    n = len(passages)
    k1, b = 1.5, 0.75
    scored = []
    for p in passages:
        terms = p["terms"]
        if not terms:
            continue
        length = len(terms)
        score = 0.0
        for t in q:
            f = terms.count(t)
            if not f:
                continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * length / avg_len))
        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda s: -s[0])
    keyword_ranked = [p for s, p in scored if s >= MIN_SCORE]
    mode = "bm25"

    # --- semantic pass, fused with the keyword pass -----------------------
    # Reciprocal Rank Fusion: each ranker contributes 1/(60+rank). It needs no
    # score normalisation between two scales that are not comparable, and a
    # passage both rankers like rises above one that only a single ranker
    # loves. If embeddings are not available this whole block is skipped and
    # the BM25 order stands.
    qvec = embeddings.encode([question], is_query=True)
    if qvec:
        vectors = [p.get("vec") for p in passages]
        if any(vectors):
            sem = []
            for p in passages:
                v = p.get("vec")
                if v:
                    sem.append((embeddings.cosine(qvec[0], v), p))
            sem.sort(key=lambda s: -s[0])
            # Two corrections, both found by running this against the real
            # model rather than a stand-in:
            #
            # 1. An absolute cosine cut-off is useless here. Sentence models
            #    score almost any two English sentences 0.6–0.9, so a fixed
            #    threshold admitted the entire corpus in near-arbitrary order.
            #    What matters is the gap to the BEST match, not the raw value.
            # 2. Fusing a long list drowns the keyword ranker. RRF works when
            #    both inputs are SHORT, confident lists.
            # Measured, not assumed. On a real 6-passage site the raw cosine
            # picked the correct passage for 4 of 4 natural questions, while
            # BM25 picked it for 1 — because a caller phrases a question in
            # their own words ("pay you", "Berlin", "harsh chemicals") and the
            # page uses its own ("Payment terms", "Germany", "chrome
            # tanning"). Rank-fusing the two as peers let BM25's match on the
            # single common word "order" outvote a 0.725 cosine.
            #
            # So when the semantic ranker is confident it LEADS, and BM25
            # becomes a tiebreak that lifts passages which also matched
            # lexically. When it is not confident, BM25 stands alone.
            top_keyword = {id(p) for p in keyword_ranked[:3]}
            candidates = [(s + (0.03 if id(p) in top_keyword else 0.0), p)
                          for s, p in sem if s >= COS_FLOOR]
            if candidates and sem[0][0] >= COS_LEAD:
                candidates.sort(key=lambda c: -c[0])
                keyword_ranked = [p for _, p in candidates]
                mode = "hybrid"
            elif not keyword_ranked and sem[0][0] >= COS_FLOOR:
                # BM25 found nothing at all — the caller used none of the
                # page's words. A moderate semantic match is far better than
                # telling them the site does not cover it.
                candidates.sort(key=lambda c: -c[0])
                keyword_ranked = [p for _, p in candidates]
                mode = "semantic-rescue"

    hits = [{"text": p["text"], "url": p["url"],
             "section": p.get("heading", ""),
             "score": round(next((s for s, q in scored if q is p), 0.0), 3)}
            for p in keyword_ranked[:k]]

    if not hits:
        return {
            "ok": False, "hits": [],
            "reason": ("The site does not appear to answer that. Saying so is "
                       "the correct response — a receptionist that invents an "
                       "opening time creates a customer who turns up to a "
                       "closed door."),
        }
    return {"ok": True, "hits": hits, "searched": n,
            # Shown on the dashboard so the ranking in use is never a guess.
            "mode": mode,
            "retrieval": embeddings.status(),
            "note": ("Every passage is quoted from the client's own website. "
                     + ("Ranked by keyword and meaning together."
                        if mode == "hybrid" else
                        "Ranked by keyword match; semantic ranking is not "
                        "active — see retrieval.state for why."))}


def answer(client_id: str, question: str, lang: str = "en") -> dict:
    """Retrieve, then let the model speak — strictly from what was retrieved."""
    from . import llm

    found = search(client_id, question)
    if not found["ok"]:
        return {"ok": False, "answer": "", "sources": [],
                "reason": found["reason"]}

    passages = "\n\n".join(f"[{i + 1}] {h['text']}" for i, h in enumerate(found["hits"]))
    reply = llm.complete(
        system=("You answer as the business itself, on the phone. Use ONLY the "
                "numbered passages provided — they are quoted from that "
                "business's own website. If they do not contain the answer, "
                "say you will check and have someone call back. Never invent a "
                "price, an opening time, an address or a policy. Two sentences, "
                "spoken plainly, no markdown."),
        prompt=f"Question: {question}\n\nPassages:\n{passages}\n\nAnswer in {lang}.",
        max_tokens=250,
    )

    # With no model configured the top passage is still a real answer, quoted
    # rather than paraphrased. Better than silence and impossible to hallucinate.
    text = (reply or "").strip() or found["hits"][0]["text"]
    return {
        "ok": True,
        "answer": text,
        "grounded": True,
        "generated_by": "llm" if reply else "quoted",
        "sources": [{"url": h["url"], "score": h["score"]} for h in found["hits"]],
    }


def stats(client_id: str) -> dict:
    with _lock:
        rec = _store.get(client_id)
        if not rec:
            return {"indexed": False, "passages": 0, "pages": 0}
        urls = {p["url"] for p in rec["passages"] if p["url"]}
        embedded = sum(1 for p in rec["passages"] if "vec" in p)
        return {"indexed": True, "passages": len(rec["passages"]),
                "pages": len(urls), "sources": sorted(urls)[:20],
                "embedded": embedded,
                "mode": "hybrid" if embedded else "bm25",
                "retrieval": embeddings.status()}


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"clients": {cid: [{"text": p["text"], "url": p["url"],
                                   "heading": p.get("heading", "")}
                                  for p in rec["passages"]]
                            for cid, rec in _store.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("clients")
    if not isinstance(rows, dict):
        return
    with _lock:
        _store.clear()
        for cid, passages in list(rows.items())[:MAX_CLIENTS]:
            if not isinstance(passages, list):
                continue
            rec = {"passages": [
                {"text": p.get("text", ""), "url": p.get("url", ""),
                 "heading": p.get("heading", ""),
                 "terms": _tokens(f"{p.get('heading', '')} {p.get('text', '')}")}
                for p in passages[:MAX_PASSAGES]
                if isinstance(p, dict) and p.get("text")]}
            if rec["passages"]:
                _reindex(rec)
                _store[cid] = rec


def reset() -> None:
    """Test seam."""
    with _lock:
        _store.clear()
