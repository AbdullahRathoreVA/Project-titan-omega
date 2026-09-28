"""Per-client knowledge retrieval: answers grounded in the client's own site.

A receptionist agent has to answer "do you ship to Germany?" or "what are your
opening hours?". Titan already crawls each client's website during an audit;
this keeps the text and retrieves from it.

No vector database. The corpus is one small-business website - a few dozen
passages - so BM25 is exact, instant and free. Local embeddings
(core/embeddings.py) are an optional upgrade fused in when the model is
available; everything still works without them.

Every answer carries the URL it came from. If nothing matches well enough,
retrieval returns nothing rather than the least-bad passage: an invented
opening time sends a customer to a closed door.
"""

from __future__ import annotations

import contextlib
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
# IDF is computed as if the site had at least this many passages, the unseen
# ones not containing the term. BM25's IDF shrinks with the passage count: on a
# one-passage site every word has df == n and scores log(1.333) = 0.288, so
# MIN_SCORE would silence questions whose words are on the page - and Titan's
# market is small sites. Measured with the one-page scenario in
# evaluation/retrieval_benchmark.py (each page indexed as the whole site;
# answerable misses / near-miss questions from other pages answered anyway):
#     floor 1 (off) -> 4/10 missed, 1/30 near-miss
#     floor 4       -> 1/10 missed, 2/30 near-miss
#     floor 6       -> 0/10 missed, 3/30 near-miss   <- chosen
#     floor 8..40   -> 0/10 missed, 3/30 near-miss
# 6 is the smallest value that closes the gap; larger ones add nothing and only
# widen the range of site sizes where one common word clears the bar. The full
# benchmark site (12 passages) and its 5 unanswerable questions score the same
# at every floor.
IDF_MIN_PASSAGES = 6

# How many semantic candidates may enter the fusion. Short and confident beats
# long and vague: fusing over the whole corpus swamps the exact keyword signal.
SEMANTIC_TOP_N = 4
# Neither ranker gets a fixed weight; each is weighted by its own confidence.
# BM25 is confident when its top score is high (many rare terms matched, not
# one common one). The semantic ranker is confident when its best cosine is
# high - sentence models score any two English sentences around 0.5, so the
# useful band is narrow.
#
# On a real 6-passage site, semantic ranking only beat BM25 at high cosines;
# in the 0.52-0.64 band the two were indistinguishable, and letting semantic
# lead there turned correct BM25 answers into wrong ones. So the bar to take
# over is high. 0.60 was also tried and fixed nothing (the questions it would
# rescue score below it anyway) while re-entering that risky band.
COS_LEAD = 0.68     # semantic leads the ranking above this
# Calibrated with evaluation/calibrate_cosine.py against the benchmark corpus.
# Sentence models score almost any two English sentences 0.6-0.9, so a lower
# floor admits nearly the whole corpus. Top cosine per question, answerable vs
# unanswerable:
#     floor 0.55 -> silences 1/10 answerable, admits 2/5 unanswerable
#     floor 0.60 -> silences 1/10 answerable, admits 0/5 unanswerable  <- chosen
#     floor 0.65 -> silences 4/10 answerable, admits 0/5 unanswerable
# The two classes overlap (lowest answerable 0.494, highest unanswerable
# 0.580), so no floor is perfect. 0.60 errs towards silence: a receptionist who
# says "let me check" is recoverable, one who invents an opening time isn't.
COS_FLOOR = 0.60    # below this a passage is not a semantic candidate at all

_STOP = frozenset("""
a an and are as at be but by for from has have he her his i if in is it its of
on or our she that the their them they this to was we were will with you your
""".split())

_lock = threading.RLock()
# client_id -> {"passages": [{text, url, terms}], "df": {term: n}}
_store: dict[str, dict] = {}
# A benchmark's private store and embedding switch, per thread. See sandbox().
_local = threading.local()


def _stores() -> dict:
    private = getattr(_local, "store", None)
    return _store if private is None else private


def _encode(texts: list, **kw):
    return [] if getattr(_local, "no_embed", False) else embeddings.encode(texts, **kw)


@contextlib.contextmanager
def sandbox(use_embeddings: bool = True):
    """A private, empty knowledge store for this thread, for benchmarks.

    improve._measure runs the retrieval benchmark inside the live server, and
    the benchmark indexes a fake site. Thread-local, so live requests on other
    threads keep answering from the real store and real clients' knowledge is
    never touched.
    """
    _local.store, _local.no_embed = {}, not use_embeddings
    try:
        yield
    finally:
        _local.store, _local.no_embed = None, False

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9']+")


# Question words carry the shape of a question, not its topic ("where are you
# based" shouldn't match a passage on the word "where"). Removed from queries
# only; "may" isn't here because "open in May" is a fact.
#
# Measured on evaluation/retrieval_benchmark.py (BM25 path), together with
# _stem below:
#                         hit@1   MRR    near-miss answered (one-page sites)
#     neither             0.70    0.85   3/30
#     question words      0.80    0.90   2/30
#     stemming            0.80    0.90   4/30
#     both                0.90    0.95   3/30   <- shipped
# Silence and false answers are the same in all four. Stemming's extra near-miss
# is the contact page offering "production orders by sea freight" for "what is
# the minimum order" - quoted, not invented.
_QUESTION = frozenset("""
what when where which who whom whose why how do does did can could would should
""".split())


def _stem(w: str) -> str:
    """Harman's S-stemmer: plurals and third-person -s, nothing else.

    So "Production takes about six weeks" matches "how long does production
    take". The weakest stemmer on purpose: a Porter-style one conflates
    "organisation" with "organ", and answering a question about one with a
    passage about the other would be making things up.
    """
    if len(w) > 4 and w.endswith("ies") and not w.endswith(("eies", "aies")):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("es") and not w.endswith(("aes", "ees", "oes")):
        return w[:-1]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("us", "ss")):
        return w[:-1]
    return w


def _tokens(text: str, query: bool = False) -> list[str]:
    return [_stem(w) for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 1
            and not (query and w in _QUESTION)]


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

    * A chunk never spans two sections. Headings are the author's own topic
      boundaries; merging the H1 into the first paragraph gives a blurred
      passage that matches everything weakly and nothing strongly.
    * Heading-aware splitting beats character counting for this kind of
      content: a small site of short sections on different topics.

    Pages with no headings return a single ("", body) section.
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


_SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")


def _split(text: str) -> list[str]:
    """Sentence-ish chunks. Long runs are cut on whitespace rather than mid-word,
    because a passage read aloud has to be a sentence.

    A short sentence joins its neighbour instead of being dropped: "We ship
    worldwide." or "We are closed on Sunday." are exactly the facts callers
    ask for. It joins the sentence before it (the usual referent: "Sampling
    adds a further two weeks before that."), or the one after when it opens its
    section. A short fragment without sentence punctuation is still dropped -
    that's a menu label or a button, not a fact.
    """
    out: list[str] = []
    carry = ""  # short sentences waiting for the next full one
    for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        part = part.strip()
        if len(part) < MIN_PASSAGE_CHARS:
            if not _SENTENCE_END.search(part):
                continue
            if out and not carry and len(out[-1]) + len(part) < MAX_PASSAGE_CHARS:
                out[-1] = f"{out[-1]} {part}"
            else:
                carry = f"{carry} {part}".strip()
            continue
        part, carry = f"{carry} {part}".strip(), ""
        while len(part) > MAX_PASSAGE_CHARS:
            cut = part.rfind(" ", 0, MAX_PASSAGE_CHARS)
            cut = cut if cut > MIN_PASSAGE_CHARS else MAX_PASSAGE_CHARS
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if len(part) >= MIN_PASSAGE_CHARS:
            out.append(part)
    if carry:
        if out and len(out[-1]) + len(carry) < MAX_PASSAGE_CHARS:
            out[-1] = f"{out[-1]} {carry}"
        elif len(_tokens(carry)) >= 2:  # a section that is one short fact
            out.append(carry)
    return out


def ingest(client_id: str, html_or_text: str, url: str = "") -> dict:
    """Index one page for one client. Replaces any earlier copy of that URL, so
    re-auditing a site updates the knowledge instead of duplicating it.
    """
    if not client_id:
        return {"ok": False, "reason": "A client id is required.", "passages": 0}
    is_html = "<" in (html_or_text or "")
    sections = (split_sections(html_or_text) if is_html
                else [("", html_or_text or "")])
    # (heading, passage) pairs. The heading goes along as retrieval context
    # without being glued into the quoted text - see _context_text.
    chunks = [(head, c) for head, body in sections for c in _split(body)]
    if not chunks:
        return {"ok": False, "passages": 0,
                "reason": ("Nothing readable on that page. A site that is "
                           "entirely images or client-rendered script has no "
                           "text to answer questions from — which is itself "
                           "worth telling the client.")}

    with _lock:
        store = _stores()
        rec = store.setdefault(client_id, {"passages": []})
        if url:
            rec["passages"] = [p for p in rec["passages"] if p["url"] != url]
        for head, c in chunks:
            rec["passages"].append({
                "text": c, "url": url, "heading": head,
                # The heading is searchable too: a question about "shipping" should reach a
                # passage under a "Shipping" heading even if the sentence never repeats the
                # word.
                "terms": _tokens(f"{head} {c}" if head else c),
            })
        if len(rec["passages"]) > MAX_PASSAGES:
            del rec["passages"][:len(rec["passages"]) - MAX_PASSAGES]
        _reindex(rec)
        if len(store) > MAX_CLIENTS:
            for stale in list(store)[:len(store) - MAX_CLIENTS]:
                del store[stale]
        total = len(rec["passages"])
        pending = [p for p in rec["passages"] if "vec" not in p]

    # Start loading the model as soon as there's anything to search, so it's
    # usually ready before the first question. Never blocks this call.
    if not getattr(_local, "no_embed", False):
        embeddings.warm(background=True)
    _embed_pending(client_id, pending)

    return {"ok": True, "passages": len(chunks), "total": total, "url": url,
            "retrieval": embeddings.status()}


def _context_text(p: dict) -> str:
    """What actually gets embedded: the heading, then the passage.

    "Minimum order is 50 pieces" is ambiguous alone but not under "Wholesale
    terms". The prefix only goes into the vector; the quoted text stays clean,
    since reading "Wholesale terms. Minimum order is..." aloud sounds robotic.
    """
    head = (p.get("heading") or "").strip()
    return f"{head}. {p['text']}" if head else p["text"]


def _embed_pending(client_id: str, pending: list[dict]) -> int:
    """Attach vectors to passages that lack them. A no-op when embeddings are
    unavailable; passages stay searchable by BM25 either way.
    """
    if not pending:
        return 0
    vecs = _encode([_context_text(p) for p in pending])
    if not vecs or len(vecs) != len(pending):
        return 0
    with _lock:
        for p, v in zip(pending, vecs):
            p["vec"] = v
    return len(pending)


def backfill(client_id: str = "") -> dict:
    """Embed anything indexed before the model was ready.

    The first pages are usually indexed while the model is still downloading,
    so without this a client stays keyword-only until re-audited.
    """
    with _lock:
        store = _stores()
        targets = ([client_id] if client_id else list(store))
        work = {c: [p for p in store.get(c, {}).get("passages", [])
                    if "vec" not in p]
                for c in targets}
    done = sum(_embed_pending(c, ps) for c, ps in work.items() if ps)
    with _lock:
        remaining = sum(1 for c in targets
                        for p in store.get(c, {}).get("passages", [])
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
    q = _tokens(question, query=True)
    with _lock:
        rec = _stores().get(client_id)
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
    n_idf = max(n, IDF_MIN_PASSAGES)
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
            idf = math.log(1 + (n_idf - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * length / avg_len))
        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda s: -s[0])
    keyword_ranked = [p for s, p in scored if s >= MIN_SCORE]
    mode = "bm25"

    # --- semantic pass, fused with the keyword pass -----------------------
    # Reciprocal Rank Fusion: each ranker contributes 1/(60+rank). It needs no
    # score normalisation between two incomparable scales, and a passage both
    # rankers like rises above one only a single ranker likes. Without embeddings
    # this block is skipped and the BM25 order stands.
    qvec = _encode([question], is_query=True)
    if qvec:
        vectors = [p.get("vec") for p in passages]
        if any(vectors):
            sem = []
            for p in passages:
                v = p.get("vec")
                if v:
                    sem.append((embeddings.cosine(qvec[0], v), p))
            sem.sort(key=lambda s: -s[0])
            # Two things that matter with a real model:
            #
            # 1. An absolute cosine cut-off doesn't work. Sentence models score almost any
            #    two English sentences 0.6-0.9, so what matters is the gap to the best
            #    match, not the raw value.
            # 2. Fusing a long list drowns the keyword ranker; RRF works when both inputs
            #    are short, confident lists.
            #
            # Callers phrase questions in their own words ("pay you", "Berlin", "harsh
            # chemicals") while the page uses its own ("Payment terms", "Germany", "chrome
            # tanning"), and on a real 6-passage site the raw cosine found the right
            # passage far more often than BM25. So when the semantic ranker is confident
            # it leads, and BM25 becomes a tiebreak that lifts passages that also matched
            # lexically. When it isn't confident, BM25 stands alone.
            top_keyword = {id(p) for p in keyword_ranked[:3]}
            candidates = [(s + (0.03 if id(p) in top_keyword else 0.0), p)
                          for s, p in sem if s >= COS_FLOOR]
            if candidates and sem[0][0] >= COS_LEAD:
                candidates.sort(key=lambda c: -c[0])
                keyword_ranked = [p for _, p in candidates]
                mode = "hybrid"
            elif not keyword_ranked and sem[0][0] >= COS_FLOOR:
                # BM25 found nothing - the caller used none of the page's words. A moderate
                # semantic match beats telling them the site doesn't cover it.
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
    """Retrieve, then let the model answer - strictly from what was retrieved."""
    from . import llm, model_router

    found = search(client_id, question)
    if not found["ok"]:
        return {"ok": False, "answer": "", "sources": [],
                "reason": found["reason"]}

    # These passages were crawled from a website, so they're fenced as untrusted
    # before going into a prompt that answers a business's callers. See
    # core/untrusted.py.
    from . import untrusted
    built = untrusted.safe_prompt(
        question, [h["text"] for h in found["hits"]],
        source="the business's own website", client_id=client_id)

    reply = llm.complete(
        task=model_router.VOICE_ANSWER,
        system=("You answer as the business itself, on the phone. Use ONLY the "
                "numbered passages provided — they are quoted from that "
                "business's own website. If they do not contain the answer, "
                "say you will check and have someone call back. Never invent a "
                "price, an opening time, an address or a policy. Two sentences, "
                "spoken plainly, no markdown.\n\n" + built["system_suffix"]),
        prompt=f"{built['prompt']}\n\nAnswer in {lang}.",
        max_tokens=250,
    )

    # With no model configured, the top passage is still a real answer, quoted
    # rather than paraphrased. When a model is used, its output is checked
    # before reaching a caller: an invented opening time or price can't be
    # undone, so a failed check falls back to quoting the best passage instead
    # of using the generated sentence.
    from . import verify

    passage_text = found["hits"][0]["text"]
    checked = None
    if reply:
        checked = verify.check(
            reply, evidence="\n".join(h["text"] for h in found["hits"]),
            question=question, kind="voice answer")

    if reply and checked and checked["ok"]:
        text, source = reply.strip(), "llm"
    else:
        # Quoting the site verbatim can't hallucinate. Worse prose, but true.
        text, source = passage_text, "quoted"

    return {
        "ok": True,
        "answer": text,
        "grounded": True,
        "generated_by": source,
        # Surfaced, not swallowed: an operator should see that the model tried to
        # invent a figure and was stopped.
        "verification": checked,
        "sources": [{"url": h["url"], "score": h["score"]} for h in found["hits"]],
        # Surfaced so the operator can see when the answer was built on a page that
        # contained instruction-shaped text.
        "untrusted_content_flagged": built["report"]["suspicious"],
        "untrusted_categories": built["report"]["categories"],
    }


def stats(client_id: str) -> dict:
    with _lock:
        rec = _stores().get(client_id)
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
                            for cid, rec in _stores().items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("clients")
    if not isinstance(rows, dict):
        return
    with _lock:
        store = _stores()
        store.clear()
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
                store[cid] = rec


def reset() -> None:
    """Test seam."""
    with _lock:
        _stores().clear()
