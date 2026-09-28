"""Registry of the settings Titan is allowed to change about itself.

This is the boundary of the self-improvement engine, and it's narrow on
purpose. Titan can't modify its own code: a code change needs a git push, a
GitHub Action and a Hugging Face rebuild, and the container has no git
credentials.

What it can change are a few numbers that were chosen by measurement, are read
as module globals at call time, and have a benchmark that says whether another
value is better. `COS_FLOOR` is the typical case: it was first set to 0.52,
below the 0.6-0.9 range where sentence models score any two English
sentences, so semantic rescue answered questions it shouldn't have. The
benchmark caught it and it was recalibrated to 0.60.

A parameter can only be changed if:

  * it's registered here with bounds. "Tune anything" is how a rate limit gets
    switched off at 3am.
  * it's read as a module global at call time, so an override actually takes
    effect. A value copied into a local at import would accept the override
    and change nothing.
  * it has a benchmark. A change nobody can measure can't be proposed.

`why_default` records the evidence for the current value; a proposal has to
argue against it.
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
    # Other numbers from the same benchmark that must not get worse, as
    # (metric, higher_is_better). Improving one metric by making another worse
    # (fewer silences, more invented answers) isn't allowed.
    guards: tuple = ()


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
            "questions. Lowering this trades invented answers for coverage."),
        guards=(("silence", False),)),
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
            "benchmark answers 10/10 on the full site and on one-page sites."),
        guards=(("false_answers", False), ("small_site_false_answers", False),
                ("small_site_near_miss_answered", False))),
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
            "where one common word clears MIN_SCORE."),
        guards=(("silence", False), ("false_answers", False),
                ("small_site_false_answers", False),
                ("small_site_near_miss_answered", False))),
}


# --- benchmarks -------------------------------------------------------------
# A benchmark is a callable returning a dict of measured numbers. Registered by
# name so a proposal records which harness judged it, and so tests can supply a
# deterministic one instead of downloading a 130MB embedding model.
_BENCHMARKS: dict[str, Any] = {}


def register_benchmark(key: str, fn) -> None:
    with _lock:
        _BENCHMARKS[key] = fn


def benchmark(key: str):
    return _BENCHMARKS.get(key)


def _default_benchmarks() -> None:
    def retrieval() -> dict:
        # Imported inside the function: the benchmark corpus and the embedding path
        # must never load at module import time.
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
    """The value the running code is using, read from the module."""
    param = PARAMS[name]
    return getattr(_module(param), param.attr)


def overrides() -> dict:
    from . import db
    stored = db.get(_OVERRIDE_KEY, {}) or {}
    return {k: v for k, v in stored.items() if k in PARAMS}


def set_value(name: str, value: Any) -> Any:
    """Apply a value to the live module and persist it. Returns the value set.

    The setattr changes behaviour now; persisting it survives the container
    being recycled, which a free Space does regularly.
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
    """Drop the override. Doesn't restore the shipped value by itself - callers
    that need the old behaviour must set it explicitly, because the shipped
    default isn't always what was running before.
    """
    from . import db
    with _lock:
        stored = db.get(_OVERRIDE_KEY, {}) or {}
        stored.pop(name, None)
        db.put(_OVERRIDE_KEY, stored)


def apply_stored() -> list:
    """Re-apply persisted overrides to the live modules. Called at boot.

    Without this an approved change would silently revert on the next rebuild.
    """
    applied = []
    for name, value in overrides().items():
        try:
            param = PARAMS[name]
            setattr(_module(param), param.attr, coerce(param, value))
            applied.append(name)
        except Exception:
            # A stored value that no longer validates is ignored, not fatal; booting
            # matters more than a stale override.
            continue
    return applied


def status() -> dict:
    """What's tunable, what's overridden, and the evidence for each default."""
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
