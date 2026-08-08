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

MAX_CLIENTS = 200
MAX_PASSAGES = 400          # per client
MIN_PASSAGE_CHARS = 60
MAX_PASSAGE_CHARS = 600

# Below this the best match is noise. Tuned so a question about something the
# site never mentions returns nothing instead of the least-irrelevant sentence.
MIN_SCORE = 0.8

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
    text = strip_html(html_or_text) if "<" in (html_or_text or "") else (html_or_text or "")
    chunks = _split(text)
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
        for c in chunks:
            rec["passages"].append({"text": c, "url": url, "terms": _tokens(c)})
        if len(rec["passages"]) > MAX_PASSAGES:
            del rec["passages"][:len(rec["passages"]) - MAX_PASSAGES]
        _reindex(rec)
        if len(_store) > MAX_CLIENTS:
            for stale in list(_store)[:len(_store) - MAX_CLIENTS]:
                del _store[stale]
        total = len(rec["passages"])
    return {"ok": True, "passages": len(chunks), "total": total, "url": url}


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
    hits = [{"text": p["text"], "url": p["url"], "score": round(s, 3)}
            for s, p in scored[:k] if s >= MIN_SCORE]

    if not hits:
        return {
            "ok": False, "hits": [],
            "reason": ("The site does not appear to answer that. Saying so is "
                       "the correct response — a receptionist that invents an "
                       "opening time creates a customer who turns up to a "
                       "closed door."),
        }
    return {"ok": True, "hits": hits, "searched": n,
            "note": "Every passage is quoted from the client's own website."}


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
        return {"indexed": True, "passages": len(rec["passages"]),
                "pages": len(urls), "sources": sorted(urls)[:20]}


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"clients": {cid: [{"text": p["text"], "url": p["url"]}
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
                 "terms": _tokens(p.get("text", ""))}
                for p in passages[:MAX_PASSAGES]
                if isinstance(p, dict) and p.get("text")]}
            if rec["passages"]:
                _reindex(rec)
                _store[cid] = rec


def reset() -> None:
    """Test seam."""
    with _lock:
        _store.clear()
