"use client";

/**
 * API Command Center: what Titan has catalogued vs what it can actually call.
 *
 * 1,675 providers are catalogued and a handful of capabilities are
 * integrated. Both numbers are shown side by side, with the integrated count
 * as the headline.
 *
 * Mobile first: results are stacking cards, the catalogue is searched and
 * capped server-side (never 1,675 rows sent to a phone), and every control is
 * at least a 44px touch target.
 */

import { useCallback, useEffect, useState } from "react";
import { Activity, Globe, RefreshCw, Search } from "lucide-react";

import { api } from "@/lib/api";

type Integrated = {
  integrated: { capabilities: string[]; count: number; providers: string[]; note: string };
  catalogued: number;
  adapters_written: number;
};

export default function ApiCommand() {
  const [meta, setMeta] = useState<Integrated | null>(null);
  const [rates, setRates] = useState<any>(null);
  const [weather, setWeather] = useState<any>(null);
  const [place, setPlace] = useState("Sialkot");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<any>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.apisIntegrated().then(setMeta).catch(() => setMeta(null));
  }, []);

  const loadRates = useCallback(async () => {
    setBusy("rates");
    try {
      setRates(await api.apisRates("USD", "PKR,EUR,GBP"));
    } catch {
      setRates({ ok: false, error: "Could not reach the rates endpoint." });
    }
    setBusy("");
  }, []);

  const loadWeather = useCallback(async () => {
    if (place.trim().length < 2) return;
    setBusy("weather");
    try {
      setWeather(await api.apisWeather(place));
    } catch {
      setWeather({ ok: false, error: "Could not reach the weather endpoint." });
    }
    setBusy("");
  }, [place]);

  const search = useCallback(async () => {
    if (!query.trim()) return;
    setBusy("search");
    try {
      setFound(await api.apisSearch(query, 8));
    } catch {
      setFound(null);
    }
    setBusy("");
  }, [query]);

  return (
    <div className="space-y-4">
      {/* Headline: catalogued is big, callable is small. */}
      <section className="panel p-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Catalogued" value={meta ? String(meta.catalogued) : "—"} tone="mut" />
          <Stat label="Callable now" value={meta ? String(meta.integrated.count) : "—"} tone="cyan" />
          <Stat label="Adapters written" value={meta ? String(meta.adapters_written + meta.integrated.count) : "—"} tone="mut" />
          <Stat label="Credentials" value="none needed" tone="emerald" />
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          {meta?.integrated.note ??
            "Catalogued means Titan knows the provider exists. Callable means it has a tested adapter."}
        </p>
      </section>

      {/* Live currency */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Exchange rates</h2>
          </div>
          <button
            onClick={loadRates}
            disabled={busy === "rates"}
            className="flex min-h-11 items-center gap-1.5 rounded-lg border border-edge bg-panel/80 px-3 text-xs text-slate-300 hover:border-hud-emerald/40 hover:text-hud-emerald disabled:opacity-50 sm:min-h-0 sm:py-1"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${busy === "rates" ? "animate-spin" : ""}`} />
            {busy === "rates" ? "Fetching…" : "Fetch live"}
          </button>
        </header>
        <div className="p-3">
          {!rates && <p className="text-xs text-slate-500">Not fetched yet — nothing is shown until a real call returns.</p>}
          {rates?.ok === false && <p className="text-xs text-hud-rose">{rates.error}</p>}
          {rates?.ok && (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {Object.entries(rates.rates as Record<string, number>).map(([code, v]) => (
                  <div key={code} className="rounded-lg border border-edge bg-panel/60 p-2">
                    <div className="hud-label">{rates.base} → {code}</div>
                    <div className="font-mono text-lg text-hud-cyan">{Number(v).toFixed(4)}</div>
                  </div>
                ))}
              </div>
              <p className="mt-2 font-mono text-[10px] text-slate-500">
                {rates.provider} · {rates.as_of} · {rates.latency_ms}ms
                {rates.unavailable_symbols?.length ? ` · unavailable: ${rates.unavailable_symbols.join(", ")}` : ""}
              </p>
            </>
          )}
        </div>
      </section>

      {/* Geocode + weather chained */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Place → weather</h2>
          </div>
        </header>
        <div className="space-y-2 p-3">
          <div className="flex gap-2">
            <input
              value={place}
              onChange={(e) => setPlace(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadWeather()}
              placeholder="City name"
              className="min-h-11 min-w-0 flex-1 rounded-lg border border-edge bg-panel/80 px-3 text-sm text-slate-200 outline-none focus:border-hud-cyan/50"
            />
            <button
              onClick={loadWeather}
              disabled={busy === "weather"}
              className="min-h-11 shrink-0 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-4 text-sm text-hud-cyan disabled:opacity-50"
            >
              {busy === "weather" ? "…" : "Go"}
            </button>
          </div>
          {weather?.ok === false && (
            <p className="text-xs text-hud-rose">
              {weather.error}{weather.stage ? ` (stage: ${weather.stage})` : ""}
            </p>
          )}
          {weather?.ok && (
            <div className="rounded-lg border border-edge bg-panel/60 p-3">
              <div className="text-sm text-slate-200">
                {weather.place.name}, {weather.place.country}
              </div>
              <div className="mt-1 font-mono text-2xl text-hud-cyan">
                {weather.weather.temperature_c}°C
              </div>
              <div className="text-xs text-slate-400">
                {weather.weather.conditions ?? "conditions not classified"} · humidity{" "}
                {weather.weather.humidity_pct}% · wind {weather.weather.wind_speed_kmh} km/h
              </div>
              <div className="mt-1 font-mono text-[10px] text-slate-500">
                {weather.place.latitude}, {weather.place.longitude} · {weather.place.timezone} ·{" "}
                {weather.providers.join(" + ")}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Catalogue search — server-side, capped */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-slate-400" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Catalogue</h2>
            <span className="hud-label">metadata only</span>
          </div>
        </header>
        <div className="space-y-2 p-3">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="weather, crypto, geocoding…"
              className="min-h-11 min-w-0 flex-1 rounded-lg border border-edge bg-panel/80 px-3 text-sm text-slate-200 outline-none focus:border-hud-cyan/50"
            />
            <button
              onClick={search}
              disabled={busy === "search"}
              className="min-h-11 shrink-0 rounded-lg border border-edge bg-panel/80 px-4 text-sm text-slate-300"
            >
              {busy === "search" ? "…" : "Search"}
            </button>
          </div>
          {found && (
            <>
              <p className="hud-label">{found.total} match — showing {found.results.length}</p>
              <div className="space-y-1.5">
                {found.results.map((r: any) => (
                  <div key={r.id} className="rounded-lg border border-edge bg-panel/60 p-2">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 truncate text-sm text-slate-200">{r.name}</span>
                      <span className="hud-label shrink-0">{r.category}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{r.description}</p>
                    <p className="mt-1 font-mono text-[10px] text-slate-600">
                      auth: {r.auth} · https: {String(r.https)} · METADATA_ONLY
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  const color =
    tone === "cyan" ? "text-hud-cyan" : tone === "emerald" ? "text-hud-emerald" : "text-slate-300";
  return (
    <div className="rounded-lg border border-edge bg-panel/60 p-2">
      <div className="hud-label">{label}</div>
      <div className={`mt-0.5 font-mono text-lg ${color}`}>{value}</div>
    </div>
  );
}
