"""Print the cosine scores answerable and unanswerable questions actually get.

Sentence models score almost any two English sentences 0.6-0.9, so the
semantic floor has to sit above that band or it lets everything through.
Use this output to pick COS_FLOOR from data rather than by guessing.

Run:  python -m evaluation.calibrate_cosine
"""

from __future__ import annotations

import time

from app.core import embeddings, knowledge
from evaluation.retrieval_benchmark import ANSWERABLE, CORPUS, UNANSWERABLE


def main() -> None:
    knowledge.import_state({"clients": {}})
    for url, html in CORPUS.items():
        knowledge.ingest("cal", html, url)

    embeddings.warm(background=True)
    for _ in range(180):
        if embeddings.status()["state"] in ("ready", "unavailable"):
            break
        time.sleep(1)
    if embeddings.status()["state"] != "ready":
        print("embedding model unavailable — cannot calibrate")
        return
    knowledge.backfill("cal")

    passages = knowledge._store["cal"]["passages"]

    def top_cosine(question: str) -> float:
        qv = embeddings.encode([question], is_query=True)
        if not qv:
            return 0.0
        return max(embeddings.cosine(qv[0], p["vec"])
                   for p in passages if p.get("vec"))

    print("\nANSWERABLE (the floor must stay BELOW these):")
    ans = []
    for q, _needle in ANSWERABLE:
        c = top_cosine(q)
        ans.append(c)
        print(f"  {c:.3f}  {q}")

    print("\nUNANSWERABLE (the floor must sit ABOVE these):")
    una = []
    for q in UNANSWERABLE:
        c = top_cosine(q)
        una.append(c)
        print(f"  {c:.3f}  {q}")

    print(f"\n  lowest answerable   {min(ans):.3f}")
    print(f"  highest unanswerable {max(una):.3f}")
    gap = min(ans) - max(una)
    print(f"  separation           {gap:+.3f}")
    if gap > 0:
        print(f"  -> a floor anywhere in ({max(una):.3f}, {min(ans):.3f}) "
              f"separates them cleanly; midpoint "
              f"{(max(una) + min(ans)) / 2:.3f}")
    else:
        print("  -> NO clean separation exists. Any single floor trades a "
              "silence for a false answer; pick by which error is worse.")
        for candidate in (0.55, 0.60, 0.62, 0.65, 0.68, 0.70, 0.72, 0.75):
            silenced = sum(1 for c in ans if c < candidate)
            false_a = sum(1 for c in una if c >= candidate)
            print(f"     floor {candidate:.2f}: silences {silenced}/{len(ans)}"
                  f" answerable, admits {false_a}/{len(una)} unanswerable")


if __name__ == "__main__":
    main()
