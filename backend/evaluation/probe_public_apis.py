"""Attempt every credential-free API and record what actually happened.

This is the honest version of "integrate them all". It does not hand-write
1,675 adapters. It sends ONE polite request to each credential-free provider
through the hardened runtime and writes down the result, so a provider is
promoted out of METADATA_ONLY only on evidence.

Why only the credential-free ones: the other 887 need an API key or OAuth.
Probing them without one produces 401s that say nothing about the provider,
and there is no key to use. They stay AUTH_REQUIRED, which is the true status.

Politeness, because the brief's §47 is a hard requirement:
  * one request per provider, never a burst
  * a per-host minimum interval enforced inside the runtime itself
  * a circuit breaker that stops contacting a host after repeated failures
  * a --budget cap so a run can be bounded

A REAL LIMITATION, STATED UP FRONT: the catalogue records each provider's
homepage, not its API base URL. `https://frankfurter.app` is a website;
`https://api.frankfurter.app/latest` is the endpoint. So a plain GET of the
listed URL will return HTML for many providers that are perfectly healthy.
That is why SCHEMA_MISMATCH (content-type is not JSON) is counted separately
from a failure — it means "this URL is a web page", not "this API is broken".

Run:  python -m evaluation.probe_public_apis --budget 50
      python -m evaluation.probe_public_apis --all
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "api_probe_results.json")


def main() -> int:
    from app.core import api_registry, api_runtime

    budget = None
    if "--budget" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--budget") + 1])
    elif "--all" not in sys.argv:
        budget = 25

    api_registry.load()
    targets = [a for a in api_registry.all_apis() if a["auth"] == "none"]
    if budget:
        targets = targets[:budget]

    print(f"probing {len(targets)} credential-free APIs "
          f"(of {api_registry.stats()['no_credential_required']} total)")
    print(f"per-host interval {api_runtime.PER_HOST_INTERVAL}s, "
          f"timeout {api_runtime.TIMEOUT_S}s\n")

    results, counts = [], {}
    started = time.monotonic()
    for i, api in enumerate(targets, 1):
        r = api_runtime.call(api["url"])
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        results.append({
            "id": api["id"], "name": api["name"], "category": api["category"],
            "url": api["url"], "outcome": r["outcome"], "status": r["status"],
            "latency_ms": r["latency_ms"], "bytes": r["bytes"],
            "error": r["error"][:160],
            # Evidence-based promotion: JSON came back, so a generic adapter
            # can genuinely read this one.
            "json_ok": bool(r["ok"]),
        })
        if i % 10 == 0 or i == len(targets):
            el = time.monotonic() - started
            print(f"  {i}/{len(targets)}  {el:6.1f}s  {counts}")

    ok = sum(1 for r in results if r["json_ok"])
    payload = {
        "probed_at": time.time(),
        "attempted": len(results),
        "json_ok": ok,
        "outcomes": counts,
        "results": results,
        "note": (
            "One request per provider through core/api_runtime. `json_ok` "
            "means the listed URL returned parseable JSON, so a generic "
            "adapter can read it today. SCHEMA_MISMATCH usually means the "
            "catalogue lists a homepage rather than an API endpoint — the "
            "provider may be perfectly healthy. Nothing here is a claim "
            "about providers that were not probed."),
    }
    io.open(OUT, "w", encoding="utf-8", newline="").write(
        json.dumps(payload, indent=1, ensure_ascii=False))

    print(f"\nattempted {len(results)}  json_ok {ok} "
          f"({ok / max(1, len(results)):.0%})")
    print("outcomes:", dict(sorted(counts.items(), key=lambda x: -x[1])))
    print("->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
