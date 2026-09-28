"""Tested integrations for the few public APIs Titan actually calls.

The catalogue lists 1,675 providers; this module calls a handful of
capabilities. That gap is what the `METADATA_ONLY` status in `api_registry`
means.

Every endpoint here was checked by hand against the live service first,
because the catalogue lists homepages rather than API paths.

Providers:

`currency` - primary is open.er-api.com, not Frankfurter. Frankfurter serves
ECB reference rates, which cover about thirty major currencies and not PKR
(`api.frankfurter.dev/v1/latest?from=USD&to=PKR` returns "not found", while
open.er-api.com returns PKR). Titan is run from Pakistan and invoices in PKR,
so Frankfurter is only the fallback, where it's excellent for EUR/USD/GBP.

`weather` and `geocoding` - Open-Meteo. No key, clean JSON. Geocoding
resolves "Sialkot" to 32.4927/74.5313.

None of these need a credential, so they cost nothing to run.

Everything goes through `api_runtime` (SSRF guard, timeout, bounded read,
content-type check, classified failures, per-host politeness). Responses are
normalised to a stable shape so callers never parse provider-specific JSON and
a provider swap doesn't affect them.

Values are reported as the provider gave them. When a call fails the result is
`ok: False` with the reason, never a made-up rate or temperature.
"""

from __future__ import annotations

from typing import Optional

from . import api_runtime

# ------------------------------------------------------------------ currency --
_ER_API = "https://open.er-api.com/v6/latest/{base}"
_FRANKFURTER = "https://api.frankfurter.dev/v1/latest?base={base}"


def exchange_rates(base: str = "USD", symbols: Optional[list] = None) -> dict:
    """Live exchange rates, with a fallback. Never invents a rate."""
    base = (base or "USD").upper()[:3]
    attempts = []

    for provider, url in (("open.er-api.com", _ER_API.format(base=base)),
                          ("frankfurter", _FRANKFURTER.format(base=base))):
        r = api_runtime.call(url)
        attempts.append({"provider": provider, "outcome": r["outcome"],
                         "latency_ms": r["latency_ms"]})
        if not r["ok"]:
            continue
        data = r["data"] or {}
        rates = data.get("rates") or {}
        if not rates:
            attempts[-1]["outcome"] = "SCHEMA_MISMATCH"
            continue
        if symbols:
            wanted = {s.upper() for s in symbols}
            rates = {k: v for k, v in rates.items() if k in wanted}
            missing = sorted(wanted - set(rates))
        else:
            missing = []
        return {
            "ok": True, "capability": "currency.exchange_rates",
            "provider": provider, "base": data.get("base_code") or data.get("base") or base,
            "rates": rates,
            "as_of": data.get("time_last_update_utc") or data.get("date"),
            "latency_ms": r["latency_ms"],
            # Listed rather than silently dropped: Frankfurter only carries ECB rates, so
            # a missing currency is absent, not zero.
            "unavailable_symbols": missing,
            "attempts": attempts,
        }

    return {"ok": False, "capability": "currency.exchange_rates",
            "error": "Every currency provider failed.", "attempts": attempts,
            "rates": {}, "base": base}


# ------------------------------------------------------------------- weather --
_OPEN_METEO = ("https://api.open-meteo.com/v1/forecast"
               "?latitude={lat}&longitude={lon}"
               "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m")

# WMO codes, the subset Open-Meteo actually emits.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle",
    53: "moderate drizzle", 55: "dense drizzle", 61: "slight rain",
    63: "moderate rain", 65: "heavy rain", 71: "slight snow",
    73: "moderate snow", 75: "heavy snow", 80: "slight rain showers",
    81: "moderate rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def weather(latitude: float, longitude: float) -> dict:
    """Current conditions for a coordinate. Open-Meteo, no key required."""
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return {"ok": False, "capability": "weather.current",
                "error": "latitude and longitude must be numbers."}
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return {"ok": False, "capability": "weather.current",
                "error": f"({lat}, {lon}) is not a point on Earth."}

    r = api_runtime.call(_OPEN_METEO.format(lat=lat, lon=lon))
    if not r["ok"]:
        return {"ok": False, "capability": "weather.current",
                "provider": "open-meteo", "error": r["error"],
                "outcome": r["outcome"]}

    cur = (r["data"] or {}).get("current") or {}
    if "temperature_2m" not in cur:
        return {"ok": False, "capability": "weather.current",
                "provider": "open-meteo",
                "error": "The response carried no current temperature.",
                "outcome": "SCHEMA_MISMATCH"}
    code = cur.get("weather_code")
    return {
        "ok": True, "capability": "weather.current", "provider": "open-meteo",
        "latitude": (r["data"] or {}).get("latitude"),
        "longitude": (r["data"] or {}).get("longitude"),
        "temperature_c": cur.get("temperature_2m"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "wind_speed_kmh": cur.get("wind_speed_10m"),
        "weather_code": code,
        # None, not "unknown": an unmapped WMO code is a gap in this table, and
        # making up a description would invent an observation.
        "conditions": _WMO.get(code),
        "observed_at": cur.get("time"),
        "latency_ms": r["latency_ms"],
    }


# ----------------------------------------------------------------- geocoding --
_GEOCODE = ("https://geocoding-api.open-meteo.com/v1/search"
            "?name={q}&count={n}&format=json")


def geocode(place: str, limit: int = 3) -> dict:
    """Resolve a place name to coordinates. Feeds local SEO and weather."""
    import urllib.parse

    place = (place or "").strip()
    if len(place) < 2:
        return {"ok": False, "capability": "geo.geocode",
                "error": "Give a place name of at least two characters."}

    r = api_runtime.call(_GEOCODE.format(
        q=urllib.parse.quote(place), n=max(1, min(int(limit or 3), 10))))
    if not r["ok"]:
        return {"ok": False, "capability": "geo.geocode",
                "provider": "open-meteo", "error": r["error"],
                "outcome": r["outcome"]}

    rows = (r["data"] or {}).get("results") or []
    return {
        "ok": True, "capability": "geo.geocode", "provider": "open-meteo",
        "query": place,
        "results": [{
            "name": x.get("name"),
            "country": x.get("country"),
            "country_code": x.get("country_code"),
            "admin1": x.get("admin1"),
            "latitude": x.get("latitude"),
            "longitude": x.get("longitude"),
            "timezone": x.get("timezone"),
            "population": x.get("population"),
        } for x in rows],
        # An empty list is a real answer - the provider doesn't know this place. It
        # isn't an error.
        "found": len(rows),
        "latency_ms": r["latency_ms"],
    }


def weather_for_place(place: str) -> dict:
    """Geocode then fetch weather.

    An agent asks for "weather in Sialkot" without needing to know two
    providers and a coordinate lookup are involved.
    """
    located = geocode(place, limit=1)
    if not located["ok"]:
        return {"ok": False, "capability": "weather.for_place",
                "error": located["error"], "stage": "geocode"}
    if not located["results"]:
        return {"ok": False, "capability": "weather.for_place",
                "error": f"No place called {place!r} was found.",
                "stage": "geocode", "found": 0}

    top = located["results"][0]
    w = weather(top["latitude"], top["longitude"])
    if not w["ok"]:
        return {"ok": False, "capability": "weather.for_place",
                "error": w["error"], "stage": "weather", "place": top}
    return {"ok": True, "capability": "weather.for_place",
            "place": top, "weather": w,
            "providers": ["open-meteo (geocoding)", "open-meteo (forecast)"]}


# -------------------------------------------------------- security headers --
# MDN HTTP Observatory. The catalogue entry points at the old
# `mozilla/http-observatory` README, whose host
# (http-observatory.security.mozilla.org) is gone - both GET and POST return
# 502. The live service is MDN's v2 API, which only answers POST
# (`GET /api/v2/scan` is a 404).
#
# This gives an independent, third-party grade for something Titan already
# audits.
_OBSERVATORY = "https://observatory-api.mdn.mozilla.net/api/v2/scan?host={host}"


def security_headers(host: str) -> dict:
    """A third party's grade for a host's HTTP security headers."""
    import ipaddress
    import urllib.parse

    raw = (host or "").strip()
    if not raw:
        return {"ok": False, "capability": "security.headers",
                "error": "Give a hostname, or a URL to take one from."}

    name = raw
    if "//" in name:
        name = urllib.parse.urlsplit(name).hostname or ""
    name = name.split("/")[0].split("@")[-1].split(":")[0].strip().lower()

    if not name or "." not in name:
        return {"ok": False, "capability": "security.headers",
                "error": f"{raw!r} is not a hostname."}
    # The scan is run by Mozilla, not Titan, so Titan's SSRF guard never sees the
    # target. Don't point a third-party scanner at anything that isn't a public
    # name.
    try:
        ipaddress.ip_address(name)
        return {"ok": False, "capability": "security.headers",
                "error": "Scan a hostname, not an IP address."}
    except ValueError:
        pass
    if name.endswith(".local") or name.endswith(".internal"):
        return {"ok": False, "capability": "security.headers",
                "error": f"{name} is not a public hostname."}

    r = api_runtime.call(_OBSERVATORY.format(host=urllib.parse.quote(name)),
                         method="POST")
    if not r["ok"]:
        return {"ok": False, "capability": "security.headers",
                "provider": "mdn-observatory", "host": name,
                "error": r["error"], "outcome": r["outcome"]}

    d = r["data"] or {}
    if d.get("error"):
        return {"ok": False, "capability": "security.headers",
                "provider": "mdn-observatory", "host": name,
                "error": str(d["error"])[:200], "stage": "provider"}
    if d.get("grade") is None:
        # No grade means no grade. Defaulting a missing score to 0 would read as an F
        # for a site nobody managed to scan.
        return {"ok": False, "capability": "security.headers",
                "provider": "mdn-observatory", "host": name,
                "error": "The scan returned no grade.",
                "outcome": "SCHEMA_MISMATCH"}

    return {
        "ok": True, "capability": "security.headers",
        "provider": "mdn-observatory", "host": name,
        "grade": d.get("grade"),
        "score": d.get("score"),
        "tests_passed": d.get("tests_passed"),
        "tests_failed": d.get("tests_failed"),
        "tests_total": d.get("tests_quantity"),
        # Mozilla serves cached scans, so the grade needs the time it was taken.
        "scanned_at": d.get("scanned_at"),
        "algorithm_version": d.get("algorithm_version"),
        "details_url": d.get("details_url"),
        "latency_ms": r["latency_ms"],
    }


CAPABILITIES = {
    "currency.exchange_rates": exchange_rates,
    "weather.current": weather,
    "weather.for_place": weather_for_place,
    "geo.geocode": geocode,
    "security.headers": security_headers,
}


def integrated() -> dict:
    """What Titan can actually call, as opposed to what it has catalogued."""
    return {
        "capabilities": sorted(CAPABILITIES),
        "count": len(CAPABILITIES),
        "providers": ["open.er-api.com", "frankfurter", "open-meteo",
                      "observatory-api.mdn.mozilla.net"],
        "credentials_required": False,
        "note": ("These are verified against the live services and normalised "
                 "to a stable shape. Everything else in the API catalogue is "
                 "METADATA_ONLY — catalogued, not callable."),
    }
