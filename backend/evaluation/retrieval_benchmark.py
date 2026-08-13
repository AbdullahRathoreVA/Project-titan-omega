"""Retrieval benchmark — measure before changing anything.

The brief's rule, and this codebase's: never claim an improvement that was not
measured, and never tune a threshold without a benchmark to prove the tuning.

The corpus is a small business website, because that is Titan's actual market
and the failure mode being measured only appears there. It is modelled on the
leather wholesaler that is the real client: four short pages, the kind of site
a business actually has, not a 10,000-document research corpus.

Metrics reported:

  hit@1        the top result is a correct passage
  hit@3        a correct passage is anywhere in the top 3
  MRR          mean reciprocal rank
  silence      the retriever returned NOTHING for an answerable question
  false_answer the retriever returned something for an UNANSWERABLE question

`silence` and `false_answer` are the two that matter commercially and they pull
against each other. Silence on an answerable question is the defect being
chased. A false answer on an unanswerable one is worse — it is the receptionist
inventing an opening time — so the benchmark measures both and any change must
not trade one for the other.

Run:  python -m evaluation.retrieval_benchmark
"""

from __future__ import annotations

import sys

# Four pages of a real small business. Section headings matter — the ingester
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

# Questions the site genuinely does not answer. Returning anything here is the
# receptionist inventing a fact, which is worse than silence.
UNANSWERABLE = [
    "do you offer a lifetime warranty",
    "can I visit the factory in Berlin",
    "do you sell handbags",
    "what is your VAT registration number",
    "do you accept cryptocurrency",
]


def run(use_embeddings: bool = False, backfill: bool = False) -> dict:
    """`backfill` reproduces the steady state the heartbeat now maintains.

    Without it this measures the COLD state: pages indexed while the embedding
    model was still downloading, which keep no vectors. That was production's
    permanent state until the backfill was wired to the heartbeat, because
    knowledge.backfill() existed but nothing ever called it.
    """
    import time as _t

    from app.core import embeddings, knowledge

    real_encode = embeddings.encode
    if not use_embeddings:
        # Isolate the keyword path. With embeddings on, a background model
        # download decides the result, which is not a measurement.
        embeddings.encode = lambda *a, **k: []
    try:
        knowledge.import_state({"clients": {}})
        for url, html in CORPUS.items():
            knowledge.ingest("bench", html, url)

        if use_embeddings and backfill:
            embeddings.warm(background=True)
            for _ in range(120):
                if embeddings.status()["state"] in ("ready", "unavailable"):
                    break
                _t.sleep(1)
            knowledge.backfill("bench")
            vecs = sum(1 for p in knowledge._store["bench"]["passages"]
                       if p.get("vec"))
            print(f"  [backfill] {vecs}/"
                  f"{len(knowledge._store['bench']['passages'])} passages "
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
        }
    finally:
        embeddings.encode = real_encode


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


if __name__ == "__main__":
    _print(run(use_embeddings=False), "BM25 only (keyword path in isolation)")
    if "--with-embeddings" in sys.argv:
        _print(run(use_embeddings=True, backfill=False),
               "BEFORE — cold: indexed while the model was still downloading")
        _print(run(use_embeddings=True, backfill=True),
               "AFTER  — backfilled, the state the heartbeat now maintains")
