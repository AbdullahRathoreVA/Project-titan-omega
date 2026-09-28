"""Retrieval benchmark. Measure before changing any retrieval setting.

The corpus is a small business website, since that's Titan's actual market
and the failure being measured only shows up there: four short pages modelled
on a leather wholesaler, not a 10,000-document research corpus.

Metrics:

  hit@1        the top result is a correct passage
  hit@3        a correct passage is anywhere in the top 3
  MRR          mean reciprocal rank
  silence      nothing returned for an answerable question
  false_answer something returned for an unanswerable question

  small_site_* the same questions with each page indexed alone, as a one-page
               business site: answerable misses, unanswerable answered, and
               near-miss (another page's question) answered

`silence` and `false_answer` pull against each other. Silence on an
answerable question is the problem being fixed; a false answer is worse (the
receptionist inventing an opening time). A change must not trade one for the
other.

Run:  python -m evaluation.retrieval_benchmark
"""

from __future__ import annotations

import sys

# Four pages of a small business. Section headings matter - the ingester
# splits on them.
CORPUS = {
    "https://triad.example/about": """
<h2>About Triad Thread Studio</h2>
<p>Triad Thread Studio is a leather manufacturer and wholesale supplier based
in Sialkot, Pakistan. We have been producing full-grain leather outerwear for
trade buyers since 2011, working with tanneries in the same district.</p>
""",
    "https://triad.example/products": """
<h2>Jackets</h2>
<p>We produce biker jackets, bomber jackets and classic blazers in full-grain
cowhide and lambskin. Every jacket is cut and stitched by hand in our own
workshop rather than subcontracted.</p>
<h2>Leather</h2>
<p>Our leather is vegetable tanned, which ages to a patina rather than
cracking. We also offer chrome tanned hides where a softer finish is
required.</p>
""",
    "https://triad.example/wholesale": """
<h2>Minimum order</h2>
<p>The minimum order is twenty units per style and per colourway. Mixed sizes
within a style are counted together toward that twenty.</p>
<h2>Lead times</h2>
<p>Production takes about six weeks from the day the specification sheet is
confirmed. Sampling adds a further two weeks before that.</p>
<h2>Payment terms</h2>
<p>We ask for a fifty percent deposit at order confirmation and the balance
against the bill of lading.</p>
""",
    "https://triad.example/contact": """
<h2>Opening hours</h2>
<p>The workshop is open Monday to Saturday, nine in the morning until six in
the evening. We are closed on Sunday.</p>
<h2>Shipping</h2>
<p>We ship worldwide. Sample runs go by air freight and full production orders
by sea freight from Karachi.</p>
""",
}

# (question, substring that must appear in a correct passage)
ANSWERABLE = [
    ("what is the minimum order", "twenty units"),
    ("how long does production take", "six weeks"),
    ("when are you open", "Monday to Saturday"),
    ("what kind of leather do you use", "vegetable tanned"),
    ("do you ship internationally", "ship worldwide"),
    ("what deposit do you need", "fifty percent"),
    ("where are you based", "Sialkot"),
    ("what jackets do you make", "biker jackets"),
    ("are the jackets handmade", "by hand"),
    ("how long does sampling take", "two weeks"),
]

# Questions the site doesn't answer. Returning anything here means the
# receptionist invents a fact, which is worse than silence.
UNANSWERABLE = [
    "do you offer a lifetime warranty",
    "can I visit the factory in Berlin",
    "do you sell handbags",
    "what is your VAT registration number",
    "do you accept cryptocurrency",
]


def run(use_embeddings: bool = False, backfill: bool = False) -> dict:
    """`backfill` reproduces the steady state the heartbeat maintains.

    Without it this measures the cold state: pages indexed while the embedding
    model was still downloading, which have no vectors.
    """
    import time as _t

    from app.core import embeddings, knowledge

    # A private store for this thread: improve._measure runs this inside the live
    # server, and it mustn't touch real clients' knowledge. With embeddings off the
    # keyword path is isolated, so a background model download can't decide the
    # result.
    with knowledge.sandbox(use_embeddings=use_embeddings):
        for url, html in CORPUS.items():
            knowledge.ingest("bench", html, url)

        if use_embeddings and backfill:
            embeddings.warm(background=True)
            for _ in range(120):
                if embeddings.status()["state"] in ("ready", "unavailable"):
                    break
                _t.sleep(1)
            knowledge.backfill("bench")
            vecs = sum(1 for p in knowledge._stores()["bench"]["passages"]
                       if p.get("vec"))
            print(f"  [backfill] {vecs}/"
                  f"{len(knowledge._stores()['bench']['passages'])} passages "
                  f"have vectors; model={embeddings.status()['state']}")

        hit1 = hit3 = silence = 0
        rr_total = 0.0
        misses = []
        for question, needle in ANSWERABLE:
            found = knowledge.search("bench", question, k=3)
            hits = found.get("hits", []) if found.get("ok") else []
            if not hits:
                silence += 1
                misses.append((question, "SILENCE"))
                continue
            ranks = [i for i, h in enumerate(hits, start=1)
                     if needle.lower() in h["text"].lower()]
            if ranks:
                rr_total += 1.0 / ranks[0]
                if ranks[0] == 1:
                    hit1 += 1
                hit3 += 1
            else:
                misses.append((question, f"WRONG: {hits[0]['text'][:60]}"))

        false_answers = []
        for question in UNANSWERABLE:
            found = knowledge.search("bench", question, k=3)
            if found.get("ok") and found.get("hits"):
                false_answers.append(
                    (question, found["hits"][0]["text"][:60]))

        n = len(ANSWERABLE)
        return {
            "embeddings": use_embeddings,
            "answerable": n,
            "hit@1": round(hit1 / n, 3),
            "hit@3": round(hit3 / n, 3),
            "mrr": round(rr_total / n, 3),
            "silence": silence,
            "silence_rate": round(silence / n, 3),
            "unanswerable": len(UNANSWERABLE),
            "false_answers": len(false_answers),
            "misses": misses,
            "false_answer_examples": false_answers,
            **_small_sites(knowledge),
        }


def _small_sites(knowledge) -> dict:
    """What the four-page corpus can't show: a business whose whole site is one
    page. BM25's IDF shrinks with the passage count, so a score cut-off tuned
    on the full corpus can silence a small site on questions whose words are on
    the page. Each page is indexed alone and asked the questions it answers,
    plus every UNANSWERABLE one.
    """
    silent, false, near = [], [], []
    answerable = probes = near_probes = 0
    for url, html in CORPUS.items():
        cid = f"bench-page:{url}"
        knowledge.ingest(cid, html, url)
        text = knowledge.strip_html(html).lower()
        for question, needle in ANSWERABLE:
            found = knowledge.search(cid, question, k=3)
            hits = found.get("hits", []) if found.get("ok") else []
            if needle.lower() not in text:
                # Answered on another page, so not on this one-page site. The hard case,
                # because it shares the site's vocabulary.
                near_probes += 1
                if hits:
                    near.append((url.rsplit("/", 1)[-1], question))
                continue
            answerable += 1
            if not any(needle.lower() in h["text"].lower() for h in hits):
                silent.append((url.rsplit("/", 1)[-1], question))
        for question in UNANSWERABLE:
            probes += 1
            found = knowledge.search(cid, question, k=3)
            if found.get("ok") and found.get("hits"):
                false.append((url.rsplit("/", 1)[-1], question,
                              found["hits"][0]["text"][:60]))
    return {"small_site_answerable": answerable,
            "small_site_silence": len(silent),
            "small_site_probes": probes,
            "small_site_false_answers": len(false),
            "small_site_near_miss_probes": near_probes,
            "small_site_near_miss_answered": len(near),
            "small_site_misses": silent,
            "small_site_false_answer_examples": false,
            "small_site_near_miss_examples": near}


def _print(result: dict, label: str = "") -> None:
    mode = label or ("BM25 + embeddings" if result["embeddings"] else "BM25 only")
    print(f"\n=== {mode} ===")
    print(f"  hit@1          {result['hit@1']:.3f}")
    print(f"  hit@3          {result['hit@3']:.3f}")
    print(f"  MRR            {result['mrr']:.3f}")
    print(f"  silence        {result['silence']}/{result['answerable']} "
          f"({result['silence_rate']:.0%}) <- answerable questions with NO result")
    print(f"  false answers  {result['false_answers']}/{result['unanswerable']}"
          f" <- unanswerable questions that got one")
    if result["misses"]:
        print("  misses:")
        for q, why in result["misses"]:
            print(f"    - {q!r}: {why}")
    if result["false_answer_examples"]:
        print("  false answers:")
        for q, txt in result["false_answer_examples"]:
            print(f"    - {q!r} -> {txt!r}")
    print(f"  one-page sites: missed {result['small_site_silence']}/"
          f"{result['small_site_answerable']} answerable, answered "
          f"{result['small_site_false_answers']}/{result['small_site_probes']}"
          f" unanswerable and {result['small_site_near_miss_answered']}/"
          f"{result['small_site_near_miss_probes']} near-miss (other pages')")
    for page, q in result["small_site_misses"]:
        print(f"    - missed on /{page}: {q!r}")
    for page, q, txt in result["small_site_false_answer_examples"]:
        print(f"    - false on /{page}: {q!r} -> {txt!r}")
    for page, q in result["small_site_near_miss_examples"]:
        print(f"    - near-miss answered on /{page}: {q!r}")


if __name__ == "__main__":
    _print(run(use_embeddings=False), "BM25 only (keyword path in isolation)")
    if "--with-embeddings" in sys.argv:
        _print(run(use_embeddings=True, backfill=False),
               "BEFORE — cold: indexed while the model was still downloading")
        _print(run(use_embeddings=True, backfill=True),
               "AFTER  — backfilled, the state the heartbeat now maintains")
