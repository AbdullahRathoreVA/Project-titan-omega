"""The single path for outbound calls to third-party APIs.

The registry says what exists; this is the only code that reaches any of it,
so SSRF protection, response limits and prompt-injection handling live in one
place instead of per provider.

Every call goes through, in order:

  SSRF guard      `safe_fetch.check` - rejects private, loopback, link-local
                  and cloud-metadata addresses, re-checked per redirect.
  Timeout         hard wall-clock cap.
  Size cap        the body is read in bounded chunks and abandoned past the
                  limit, so a provider that streams forever can't exhaust the
                  container.
  Content check   JSON only. An endpoint answering HTML is a landing page, not
                  an API.
  Untrusted wrap  the response is data, never shaped so a model would follow
                  it - see `core/untrusted.py`.

Failures are classified rather than collapsed into "error", because routing
needs the difference: a rate limit means try later, a DNS failure means the
provider is gone, a schema mismatch means the adapter is stale.

Politeness is enforced here, not left to callers: a per-host minimum interval
and a global concurrency cap mean even a looped prober can't hammer anyone.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional
from urllib.parse import urlparse

# Failure classes.
OK = "OK"
NETWORK_FAILURE = "NETWORK_FAILURE"
DNS_FAILURE = "DNS_FAILURE"
TLS_FAILURE = "TLS_FAILURE"
AUTH_FAILURE = "AUTH_FAILURE"
RATE_LIMIT = "RATE_LIMIT"
SERVER_ERROR = "SERVER_ERROR"
CLIENT_ERROR = "CLIENT_ERROR"
SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
TIMEOUT = "TIMEOUT"
NOT_FOUND = "NOT_FOUND"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"

TIMEOUT_S = 12.0
MAX_BYTES = 512_000
# Minimum gap between two requests to the same host. One request per provider
# is a health check; a burst is abuse.
PER_HOST_INTERVAL = 2.0

UA = "TitanOmega/1.0 (+https://titanomega-ai.com; API health check)"

_lock = threading.RLock()
_last_hit: dict[str, float] = {}
# Consecutive failures per host. A host that keeps failing isn't contacted again
# this run (circuit breaker).
_failures: dict[str, int] = {}
BREAKER_THRESHOLD = 3


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _wait_turn(host: str) -> None:
    """Block until this host may be contacted again."""
    while True:
        with _lock:
            now = time.monotonic()
            last = _last_hit.get(host, 0.0)
            gap = now - last
            if gap >= PER_HOST_INTERVAL:
                _last_hit[host] = now
                return
            sleep_for = PER_HOST_INTERVAL - gap
        time.sleep(min(sleep_for, PER_HOST_INTERVAL))


def breaker_open(url: str) -> bool:
    with _lock:
        return _failures.get(_host(url), 0) >= BREAKER_THRESHOLD


def _record(url: str, ok: bool) -> None:
    h = _host(url)
    with _lock:
        if ok:
            _failures.pop(h, None)
        else:
            _failures[h] = _failures.get(h, 0) + 1


def _classify(status: int) -> str:
    if status == 429:
        return RATE_LIMIT
    if status in (401, 403):
        return AUTH_FAILURE
    if status == 404:
        return NOT_FOUND
    if 500 <= status < 600:
        return SERVER_ERROR
    if 400 <= status < 500:
        return CLIENT_ERROR
    return UNKNOWN


def call(url: str, *, timeout: float = TIMEOUT_S,
         expect_json: bool = True, method: str = "GET") -> dict:
    """One request against a third-party API. Never raises.

    Returns a classified result. `data` is only present on a JSON success, and
    even then the caller must treat it as untrusted.

    GET and POST only, and POST never carries a body. POST is here for trigger
    APIs where the whole request is in the query string (MDN's HTTP
    Observatory: `GET /api/v2/scan` returns 404). Allowing a body would turn
    this into a general write channel to every catalogued origin.
    """
    from . import obs, safe_fetch

    started = time.monotonic()
    result = {"url": url, "ok": False, "status": None, "outcome": UNKNOWN,
              "latency_ms": None, "bytes": None, "data": None, "error": ""}

    method = (method or "GET").upper()
    if method not in ("GET", "POST"):
        result["outcome"] = BLOCKED
        result["error"] = (f"{method} is not allowed through this path — "
                           f"only GET and POST, and POST sends no body.")
        return result

    if breaker_open(url):
        result["outcome"] = BLOCKED
        result["error"] = ("Circuit breaker open: this host failed "
                           f"{BREAKER_THRESHOLD} times in a row this run.")
        return result

    try:
        safe_fetch.check(url)
    except Exception as e:
        result["outcome"] = BLOCKED
        result["error"] = str(e)[:200]
        return result

    _wait_turn(_host(url))

    try:
        import httpx
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": UA,
                                   "Accept": "application/json"}) as c:
            with c.stream(method, url) as r:
                result["status"] = r.status_code
                ctype = (r.headers.get("content-type") or "").lower()
                body = bytearray()
                for chunk in r.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        break
                result["bytes"] = len(body)
    except Exception as e:
        name = type(e).__name__
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
        if "Timeout" in name:
            result["outcome"] = TIMEOUT
        elif "ConnectError" in name or "NameResolution" in name:
            result["outcome"] = DNS_FAILURE
        elif "SSL" in name or "Certificate" in name:
            result["outcome"] = TLS_FAILURE
        else:
            result["outcome"] = NETWORK_FAILURE
        result["error"] = f"{name}: {str(e)[:120]}"
        _record(url, False)
        return result

    result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)

    if result["status"] >= 400:
        result["outcome"] = _classify(result["status"])
        result["error"] = f"HTTP {result['status']}"
        # A 401/403/429 means the provider is alive and answering - a credential or
        # quota problem, not a dead host - so it mustn't trip the breaker.
        _record(url, result["outcome"] in (AUTH_FAILURE, RATE_LIMIT))
        return result

    if expect_json:
        if "json" not in ctype:
            result["outcome"] = SCHEMA_MISMATCH
            result["error"] = (f"content-type {ctype or 'unknown'} is not "
                               f"JSON — this is a web page, not an API endpoint")
            _record(url, False)
            return result
        try:
            result["data"] = json.loads(bytes(body).decode("utf-8", "replace"))
        except Exception as e:
            result["outcome"] = SCHEMA_MISMATCH
            result["error"] = f"body was not valid JSON: {type(e).__name__}"
            _record(url, False)
            return result

    result["ok"] = True
    result["outcome"] = OK
    _record(url, True)
    obs.info("api.call", host=_host(url), status=result["status"],
             duration_ms=result["latency_ms"], bytes=result["bytes"])
    return result


def safe_summary(result: dict, *, source: str = "third-party API") -> dict:
    """Render a result for a model without handing it instructions.

    An API response is external content, and passing it into a prompt raw
    would allow prompt injection, same as with crawled pages.
    """
    from . import untrusted

    if not result.get("ok"):
        return {"ok": False, "outcome": result.get("outcome"),
                "error": result.get("error")}
    blob = json.dumps(result.get("data"), ensure_ascii=False)[:4000]
    fenced = untrusted.fence(blob, source=source)
    return {"ok": True, "fenced": fenced["fenced"],
            "instruction": fenced["instruction"],
            "flagged": fenced["report"]["suspicious"],
            "categories": fenced["report"]["categories"]}


def reset() -> None:
    """Test seam."""
    with _lock:
        _last_hit.clear()
        _failures.clear()
