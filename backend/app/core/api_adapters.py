"""Three real, tested integrations — the ones Titan actually needs.

The catalogue knows 1,675 providers. This module can CALL three capabilities,
and the difference between those two sentences is the whole point of the
`METADATA_ONLY` status in `api_registry`.

Every endpoint here was verified by hand against the live service before the
code was written, because the catalogue lists homepages rather than API paths
and guessing an endpoint produces an adapter that has never worked.

**Provider choices, and the evidence for them**

`currency` — primary is open.er-api.com, NOT Frankfurter. Frankfurter is the
obvious pick and it is wrong here: it serves ECB reference rates, which cover
about thirty major currencies and **do not include PKR**. Measured 2026-08-14:
`api.frankfurter.dev/v1/latest?from=USD&to=PKR` returns `{"message":"not
found"}` while `open.er-api.com/v6/latest/USD` returns PKR at 277.82. Titan is
run from Pakistan and its first client invoices in PKR, so the provider that
lacks PKR cannot be the primary. Frankfurter stays as the fallback because it
is excellent for EUR/USD/GBP and independent of the primary.

`weather` and `geocoding` — Open-Meteo. No key, no attribution requirement for
non-commercial use, and it answers with clean JSON. Geocoding resolves
"Sialkot" to 32.4927/74.5313, which is the actual city the leather client
operates from.

**All three need no credential**, which is why they could be verified at all
and why they cost nothing to run.

Everything goes through `api_runtime`: SSRF guard, timeout, bounded read,
content-type check, classified failures, per-host politeness. Responses are
normalised to a stable shape so an agent never parses provider-specific JSON,
and a provider swap does not change the caller.

Values are reported as the provider gave them. Nothing here fabricates a rate
or a temperature when a call fails — it returns `ok: False` and the reason.
"""

from __future__ import annotations

from typing import Optional

from . import api_runtime

# ------------------------------------------------------------------ currency --
_ER_API = "https://open.er-api.com/v6/latest/{base}"
_FRANKFURTER = "https://api.frankfurter.dev/v1/latest?base={base}"


def exchange_rates(base: str = "USD", symbols: Optional[list] = None) -> dict:
    """Live exchange rates, with a real fallback. Never invents a rate."""
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
            # Named rather than silently dropped: Frankfurter carries ECB
            # rates only, so a currency it does not publish is absent, not
            # zero. A caller that sees {} must not read it as "rate is 0".
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
        # None, not "unknown" — an unmapped WMO code is a gap in this table,
        # and inventing a description for it would be a fabricated observation.
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
        # An empty list is a real answer: the provider does not know this
        # place. It is not an error and must not be reported as one.
        "found": len(rows),
        "latency_ms": r["latency_ms"],
    }


def weather_for_place(place: str) -> dict:
    """Geocode then fetch weather — the two capabilities chained.

    This is what the capability router is for: an agent asks for "weather in
    Sialkot" and never learns that two providers and a coordinate lookup were
    involved.
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


CAPABILITIES = {
    "currency.exchange_rates": exchange_rates,
    "weather.current": weather,
    "weather.for_place": weather_for_place,
    "geo.geocode": geocode,
}


def integrated() -> dict:
    """What Titan can genuinely call, as opposed to what it has catalogued."""
    return {
        "capabilities": sorted(CAPABILITIES),
        "count": len(CAPABILITIES),
        "providers": ["open.er-api.com", "frankfurter", "open-meteo"],
        "credentials_required": False,
        "note": ("These are verified against the live services and normalised "
                 "to a stable shape. Everything else in the API catalogue is "
                 "METADATA_ONLY — catalogued, not callable."),
    }
