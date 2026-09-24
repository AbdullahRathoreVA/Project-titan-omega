"""The registry of things Titan is allowed to change about itself.

This is the boundary of the self-improvement engine, and it is deliberately
narrow. **Titan cannot modify its own source code**, and nothing here pretends
otherwise: deploying a code change means a git push, a GitHub Action and a
Hugging Face rebuild, and the running container has no git credentials, no
write access to its own image, and loses `/tmp` on every rebuild. An engine
that claimed to ship a code change would be describing something that cannot
happen.

What CAN happen honestly is this. Several numbers in Titan were chosen by
measurement, are read as module globals at call time, and have a benchmark
that says whether a different value is better. `COS_FLOOR` is the worked
example: it shipped at 0.52, which sat below the 0.6-0.9 band where sentence
models score any two English sentences, so semantic rescue answered 5 of 5
UNANSWERABLE questions. A benchmark caught it and it was recalibrated to 0.60.
That episode is the whole design brief — the value was wrong, the benchmark
knew, and a human decided.

So a parameter may be changed only if:

  * it is REGISTERED here, with bounds. Arbitrary attributes are not tunable,
    and "tune anything" is how a model turns a rate limit off at 3am.
  * it is read as a module global at call time, so an override actually takes
    effect. A value captured into a local at import would accept the override
    and change nothing, which is worse than refusing it.
  * it has a BENCHMARK. A change nobody can measure cannot be proposed, let
    alone approved — that is the same rule the rest of the codebase runs on.

`why_default` is not documentation. It is the evidence for the value that is
already there, and a proposal has to argue against it.
"""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass
from typing import Any, Optional

_OVERRIDE_KEY = "params.overrides"
_lock = threading.RLock()


@dataclass(frozen=True)
class Param:
    name: str                 # stable id, e.g. "retrieval.cos_floor"
    module: str               # dotted path of the module holding the global
    attr: str                 # the module-level NAME being overridden
    kind: str                 # "float" | "int"
    low: float                # inclusive bound
    high: float               # inclusive bound
    benchmark: str            # which benchmark decides whether a value is better
    metric: str               # the number in that benchmark's result that decides
    higher_is_better: bool
    why_default: str          # the measured reason the shipped value was chosen


PARAMS: dict[str, Param] = {
    "retrieval.cos_floor": Param(
        name="retrieval.cos_floor",
        module="app.core.knowledge", attr="COS_FLOOR",
        kind="float", low=0.50, high=0.95,
        benchmark="retrieval", metric="false_answers", higher_is_better=False,
        why_default=(
            "0.60, set by evaluation/calibrate_cosine.py. At 0.52 the floor sat "
            "below the 0.6-0.9 band where sentence models score ANY two English "
            "sentences, and semantic rescue answered 5 of 5 unanswerable "
            "questions. Lowering this trades invented answers for coverage.")),
    "retrieval.min_score": Param(
        name="retrieval.min_score",
        module="app.core.knowledge", attr="MIN_SCORE",
        kind="float", low=0.10, high=3.00,
        benchmark="retrieval", metric="silence", higher_is_better=False,
        why_default=(
            "0.8. BM25 scales with corpus size through IDF, so on its own this "
            "silenced small sites: a two-term exact match on a one-passage "
            "site scored ~0.58. retrieval.idf_min_passages now holds the IDF "
            "of a small site at the scale this cut-off works on; with it, the "
            "benchmark answers 10/10 on the full site and on one-page sites.")),
    "retrieval.idf_min_passages": Param(
        name="retrieval.idf_min_passages",
        module="app.core.knowledge", attr="IDF_MIN_PASSAGES",
        kind="int", low=1, high=50,
        benchmark="retrieval", metric="small_site_silence",
        higher_is_better=False,
        why_default=(
            "6, swept on the benchmark's one-page sites. 1 (off) missed 4/10 "
            "answerable questions whose words were on the page; 4 missed 1; 6 "
            "and above missed 0. The cost is near-miss questions (another "
            "page's) that get a passage anyway: 1/30 -> 3/30. Anything above 6 "
            "measured the same, so it only widens the range of site sizes "
            "where one common word clears MIN_SCORE.")),
}


# --- benchmarks -------------------------------------------------------------
# A benchmark is a callable returning a dict of measured numbers. Registered by
# name so a proposal records WHICH harness judged it, and so tests can supply a
# deterministic one instead of downloading a 130MB embedding model.
_BENCHMARKS: dict[str, Any] = {}


def register_benchmark(key: str, fn) -> None:
    with _lock:
        _BENCHMARKS[key] = fn


def benchmark(key: str):
    return _BENCHMARKS.get(key)


def _default_benchmarks() -> None:
    def retrieval() -> dict:
        # Imported inside the function: the benchmark corpus and the embedding
        # path must never be pulled in at module import time.
        from evaluation import retrieval_benchmark
        return retrieval_benchmark.run(use_embeddings=False)

    register_benchmark("retrieval", retrieval)


_default_benchmarks()


# --- values -----------------------------------------------------------------
def _module(param: Param):
    return importlib.import_module(param.module)


def coerce(param: Param, value: Any) -> float:
    """Cast and bounds-check. Raises ValueError with a usable message."""
    try:
        cast = int(value) if param.kind == "int" else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{param.name} takes a {param.kind}, got {value!r}")
    if not (param.low <= cast <= param.high):
        raise ValueError(
            f"{param.name}={cast} is outside its registered bounds "
            f"[{param.low}, {param.high}]")
    return cast


def current(name: str) -> Any:
    """The value the running code is actually using, read from the module."""
    param = PARAMS[name]
    return getattr(_module(param), param.attr)


def overrides() -> dict:
    from . import db
    stored = db.get(_OVERRIDE_KEY, {}) or {}
    return {k: v for k, v in stored.items() if k in PARAMS}


def set_value(name: str, value: Any) -> Any:
    """Apply a value to the live module AND persist it. Returns the value set.

    Both halves matter: the setattr is what changes behaviour now, the persist
    is what survives the container being recycled — which a free Space does
    routinely.
    """
    from . import db
    param = PARAMS[name]
    cast = coerce(param, value)
    with _lock:
        setattr(_module(param), param.attr, cast)
        stored = db.get(_OVERRIDE_KEY, {}) or {}
        stored[name] = cast
        db.put(_OVERRIDE_KEY, stored)
    return cast


def clear(name: str) -> None:
    """Drop the override. Does NOT restore the shipped value on its own —
    callers that need the old behaviour must set it explicitly, because the
    shipped default is not always what was running before the override."""
    from . import db
    with _lock:
        stored = db.get(_OVERRIDE_KEY, {}) or {}
        stored.pop(name, None)
        db.put(_OVERRIDE_KEY, stored)


def apply_stored() -> list:
    """Re-apply persisted overrides to the live modules. Called at boot.

    Without this an approved, activated change silently reverts on the next
    rebuild and nobody would know why the numbers moved back.
    """
    applied = []
    for name, value in overrides().items():
        try:
            param = PARAMS[name]
            setattr(_module(param), param.attr, coerce(param, value))
            applied.append(name)
        except Exception:
            # A stored value that no longer validates is ignored, not fatal.
            # Booting is more important than honouring a stale override.
            continue
    return applied


def status() -> dict:
    """What is tunable, what is overridden, and the evidence for each default."""
    stored = overrides()
    rows = []
    for name in sorted(PARAMS):
        param = PARAMS[name]
        try:
            live = current(name)
        except Exception:
            live = None
        rows.append({
            "name": name,
            "module": f"{param.module}.{param.attr}",
            "value": live,
            "overridden": name in stored,
            "override": stored.get(name),
            "bounds": [param.low, param.high],
            "benchmark": param.benchmark,
            "metric": param.metric,
            "higher_is_better": param.higher_is_better,
            "why_default": param.why_default,
        })
    return {
        "params": rows,
        "count": len(rows),
        "overridden": sum(1 for r in rows if r["overridden"]),
        "note": ("Only these can be changed by the improvement engine. Titan "
                 "cannot modify its own source code — deploying a code change "
                 "needs a git push and a rebuild, and the container has no git "
                 "credentials."),
    }
