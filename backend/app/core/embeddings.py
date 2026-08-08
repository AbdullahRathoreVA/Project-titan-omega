"""Local semantic embeddings — CPU only, no API key, no GPU, no per-call cost.

Abdullah asked for the heavier retrieval stack from the reference repos even at
the cost of space. This is that, done so it cannot take production down.

`fastembed` runs a small ONNX sentence model on the CPU. Measured on this
machine: **18.2 s** for the first load (it downloads ~130 MB), then **0.02 s**
to embed a batch. That first load is the entire reason for the design below.

**It is never loaded at import, and never at boot.** Hugging Face Spaces health-
check the container on startup; an 18-second blocking download there fails the
check and the Space never comes up. reportlab already took production down once
by being imported at module level. So the model loads lazily, on the first
search that asks for it, in a background-safe way — and if it fails for any
reason (no disk, no network, package missing) retrieval silently drops back to
BM25, which is always present and needs nothing.

That fallback is the point. Semantic search is an upgrade here, not a
dependency: Titan must keep answering on a container where this never loads.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# Small, fast, good enough for a few hundred passages of business copy.
# 384 dimensions keeps the stored vectors cheap.
MODEL_NAME = os.getenv("TITAN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
DIMS = 384

# Disabled by default is the wrong default here — Abdullah asked for it on.
# Set TITAN_EMBEDDINGS=0 to force pure BM25 (useful if a Space is memory-tight).
ENABLED = os.getenv("TITAN_EMBEDDINGS", "1") != "0"

_lock = threading.RLock()
_model = None
_state = "not_loaded"      # not_loaded | loading | ready | unavailable
_error = ""
_loaded_at: Optional[float] = None
_load_seconds: Optional[float] = None


def available() -> bool:
    return _state == "ready"


def status() -> dict:
    """Shown on the dashboard: which retrieval is actually running, and why."""
    return {
        "enabled": ENABLED,
        "state": _state,
        "model": MODEL_NAME if ENABLED else None,
        "dimensions": DIMS,
        "load_seconds": _load_seconds,
        "loaded_at": _loaded_at,
        "error": _error or None,
        "note": {
            "ready": ("Semantic search is active. Results fuse keyword (BM25) "
                      "and meaning-based ranking."),
            "loading": ("The embedding model is downloading (~130 MB, once). "
                        "Search is answering from BM25 until it finishes — no "
                        "request is blocked waiting for it."),
            "not_loaded": ("Not loaded yet. It loads on the first search, not "
                           "at boot: an 18-second download during startup "
                           "would fail the Space health check."),
            "unavailable": ("Semantic search could not start, so retrieval is "
                            "using BM25 only. That is a downgrade in ranking "
                            "quality, not an outage — every query still "
                            "returns sourced answers."),
        }.get(_state, ""),
    }


def _load() -> None:
    """Load once. Never raises to the caller."""
    global _model, _state, _error, _loaded_at, _load_seconds
    with _lock:
        if _state in ("ready", "loading", "unavailable"):
            return
        _state = "loading"
    started = time.time()
    try:
        # Imported here, never at module level. See the docstring.
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=MODEL_NAME)
        # Prove it actually works before declaring ready — a model that
        # imports but cannot embed would fail on every later query instead.
        probe = list(model.embed(["titan omega readiness probe"]))
        if not probe or len(probe[0]) != DIMS:
            raise RuntimeError(f"unexpected embedding shape from {MODEL_NAME}")
        with _lock:
            _model = model
            _state = "ready"
            _load_seconds = round(time.time() - started, 1)
            _loaded_at = time.time()
            _error = ""
    except Exception as exc:
        with _lock:
            _model = None
            _state = "unavailable"
            _error = f"{type(exc).__name__}: {str(exc)[:200]}"
            _load_seconds = round(time.time() - started, 1)


def warm(background: bool = True) -> dict:
    """Start loading. Returns immediately when background=True.

    Called after the first client is indexed so the model is usually ready
    before anyone searches, without ever blocking a request.
    """
    if not ENABLED:
        return status()
    if _state in ("ready", "loading", "unavailable"):
        return status()
    if background:
        threading.Thread(target=_load, name="embed-warm", daemon=True).start()
    else:
        _load()
    return status()


# BGE retrieval models are trained asymmetrically: the QUERY carries an
# instruction prefix, the documents do not. Embedding a question without it
# leaves query and passage vectors in subtly different regions, and ranking
# collapses — measured here as every test question missing its answer while
# plain BM25 got them right. This prefix is required, not cosmetic.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def encode(texts: list[str], is_query: bool = False) -> Optional[list[list[float]]]:
    """Embed texts, or None if semantic search is not available.

    None is a real answer — the caller falls back to BM25 rather than failing.
    Pass is_query=True for the search string; see QUERY_PREFIX.
    """
    if not ENABLED or not texts:
        return None
    if is_query:
        texts = [QUERY_PREFIX + t for t in texts]
    if _state == "not_loaded":
        warm(background=True)
        return None            # this query uses BM25; the next one may not
    if _state != "ready" or _model is None:
        return None
    try:
        with _lock:
            model = _model
        return [list(map(float, v)) for v in model.embed(list(texts))]
    except Exception:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """Both vectors come from the same normalised model, so a dot product is
    the cosine. Guarded anyway — a zero vector would divide by zero."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def reset() -> None:
    """Test seam."""
    global _model, _state, _error, _loaded_at, _load_seconds
    with _lock:
        _model = None
        _state = "not_loaded"
        _error = ""
        _loaded_at = None
        _load_seconds = None
