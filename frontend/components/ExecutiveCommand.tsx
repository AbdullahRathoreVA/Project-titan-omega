"use client";

/**
 * ExecutiveCommand — the Part 4C / Part 6 view.
 *
 * Surfaces four things that existed only as API responses: the BI period
 * report, the forecast, what reflection has learned, and how the model router
 * is actually performing.
 *
 * The design rule here is the one the engines already follow: where there is
 * not enough data, say so in words. A dashboard that renders 0 for "not
 * measured" and 0 for "measured zero" teaches the founder to distrust every
 * number on it, which is worse than showing nothing.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, BarChart3, Brain, Gauge, RefreshCw, TrendingUp,
} from "lucide-react";

type ForecastOff = { available: false; reason: string; needed?: number };
type ForecastOn = {
  available: true;
  method: string;
  days_of_data: number;
  horizon_days: number;
  projected_total: number;
  low: number;
  high: number;
  direction: string;
  provisional: boolean;
  assumptions: string[];
};
type Forecast = ForecastOff | ForecastOn;

type BiReport = {
  period: string;
  window_days: number;
  revenue: number;
  expenses: number;
  profit: number;
  comparison: string;
  chart: { daily_revenue: Record<string, number> };
  insights: string[];
  actions: string[];
  forecast: Forecast;
  note: string;
};

type ReflectionReport = {
  tasks_reflected: number;
  achieved: number;
  success_rate: number;
  calibration_factor: number;
  calibration_verdict: string;
  confidence_brier: number | null;
  confidence_note: string;
  tools_that_failed: Record<string, number>;
  recent: { goal: string; achieved: boolean; ratio: number; lessons: string[] }[];
};

type RoutingReport = {
  providers: {
    provider: string; calls: number; success_rate: number;
    p50_latency_ms: number; tripped: boolean; routable: boolean;
    last_error: string;
  }[];
  configured_chain: string[];
  effective_order: string[];
  note: string;
};

const PERIODS = ["daily", "weekly", "monthly", "quarterly"] as const;

function token(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("titan_token") ||
    sessionStorage.getItem("titan_token") ||
    ""
  );
}

async function api<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`/api${path}`, {
      headers: { Authorization: `Bearer ${token()}` },
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

/** Sparkline from the daily series. Drawn only when there is something to draw
 *  — an empty chart axis implies data that does not exist. */
function Spark({ series }: { series: Record<string, number> }) {
  const points = Object.entries(series);
  if (points.length < 2) return null;
  const vals = points.map(([, v]) => v);
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const span = max - min || 1;
  const d = vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * 100;
      const y = 28 - ((v - min) / span) * 26;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-full">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.4"
            className="text-hud-emerald" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function ExecutiveCommand() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("monthly");
  const [bi, setBi] = useState<BiReport | null>(null);
  const [refl, setRefl] = useState<ReflectionReport | null>(null);
  const [route, setRoute] = useState<RoutingReport | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [b, r, m] = await Promise.all([
        api<BiReport>(`/bi/${period}`),
        api<ReflectionReport>("/reflection"),
        api<RoutingReport>("/routing"),
      ]);
      setBi(b);
      setRefl(r);
      setRoute(m);
    } finally {
      setBusy(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const money = (n: number) =>
    n.toLocaleString(undefined, { maximumFractionDigits: 2 });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-widest text-white">
            <BarChart3 className="h-4 w-4 text-hud-emerald" /> EXECUTIVE
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Business intelligence · forecasting · what Titan learned
          </div>
        </div>
        <div className="flex gap-2">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded-lg border px-3 py-1.5 text-[11px] capitalize transition ${
                period === p
                  ? "border-hud-emerald/50 bg-hud-emerald/10 text-hud-emerald"
                  : "border-edge bg-panel/80 text-slate-400 hover:text-slate-200"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            onClick={() => void load()}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-amber/50 hover:text-hud-amber"
          >
            <RefreshCw className={`h-3 w-3 ${busy ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {/* money */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        {[
          ["Revenue", bi ? money(bi.revenue) : "—", "text-hud-emerald"],
          ["Expenses", bi ? money(bi.expenses) : "—", "text-hud-amber"],
          ["Profit", bi ? money(bi.profit) : "—",
            (bi?.profit ?? 0) >= 0 ? "text-hud-emerald" : "text-hud-rose"],
          ["Window", bi ? `${bi.window_days}d` : "—", "text-slate-300"],
        ].map(([label, value, tone]) => (
          <div key={label as string} className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
            <div className={`font-mono text-2xl font-semibold leading-none ${tone}`}>
              {value}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
              {label}
            </div>
          </div>
        ))}
      </div>
      {bi && (
        <div className="text-[10px] text-slate-500">{bi.comparison}</div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* forecast */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <TrendingUp className="h-3.5 w-3.5 text-hud-cyan" /> Forecast
          </div>
          {!bi ? (
            <div className="py-6 text-center text-[11px] text-slate-500">Loading…</div>
          ) : bi.forecast.available === false ? (
            /* The honest path. Showing 0 here would be a lie with a chart. */
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-3">
              <div className="text-[12px] text-amber-300">
                Not enough data to project.
              </div>
              <div className="mt-1 text-[11px] text-slate-400">
                {bi.forecast.reason}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-2xl text-hud-cyan">
                  {money(bi.forecast.projected_total)}
                </span>
                <span className="text-[11px] text-slate-500">
                  over {bi.forecast.horizon_days}d · {bi.forecast.direction}
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                Range {money(bi.forecast.low)} – {money(bi.forecast.high)}
                <span className="text-slate-600"> (95%)</span>
              </div>
              {bi.forecast.provisional && (
                <div className="rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1 text-[10px] text-amber-300">
                  Provisional — {bi.forecast.days_of_data} days of data. A
                  direction of travel, not a number to plan against.
                </div>
              )}
              <ul className="mt-1 space-y-1">
                {bi.forecast.assumptions.map((a) => (
                  <li key={a} className="text-[10px] text-slate-500">· {a}</li>
                ))}
              </ul>
            </div>
          )}
          {bi && Object.keys(bi.chart.daily_revenue).length >= 2 && (
            <div className="mt-3">
              <div className="mb-1 text-[9px] uppercase tracking-widest text-slate-600">
                Daily revenue
              </div>
              <Spark series={bi.chart.daily_revenue} />
            </div>
          )}
        </div>

        {/* insights + actions */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <AlertTriangle className="h-3.5 w-3.5 text-hud-amber" /> Insights &amp; actions
          </div>
          {!bi?.insights?.length ? (
            <div className="py-6 text-center text-[11px] text-slate-500">
              Nothing to report yet.
            </div>
          ) : (
            <>
              <ul className="space-y-1.5">
                {bi.insights.map((i) => (
                  <li key={i} className="flex items-start gap-1.5 text-[11px] text-slate-300">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-hud-cyan" />
                    {i}
                  </li>
                ))}
              </ul>
              {bi.actions.length > 0 && (
                <div className="mt-3 border-t border-white/5 pt-3">
                  <div className="mb-1.5 text-[9px] uppercase tracking-widest text-slate-600">
                    Do next
                  </div>
                  <ul className="space-y-1.5">
                    {bi.actions.map((a) => (
                      <li key={a} className="flex items-start gap-1.5 text-[11px] text-hud-amber">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-hud-amber" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* reflection */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <Brain className="h-3.5 w-3.5 text-hud-violet" /> What Titan learned
          </div>
          {!refl ? (
            <div className="py-6 text-center text-[11px] text-slate-500">Loading…</div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <div className="font-mono text-xl text-hud-violet">
                    {refl.tasks_reflected}
                  </div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-600">
                    tasks
                  </div>
                </div>
                <div>
                  <div className="font-mono text-xl text-hud-emerald">
                    {refl.success_rate}%
                  </div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-600">
                    achieved
                  </div>
                </div>
                <div>
                  <div className="font-mono text-xl text-hud-cyan">
                    {refl.calibration_factor}×
                  </div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-600">
                    calibration
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-slate-400">
                {refl.calibration_verdict}
              </div>
              {refl.confidence_brier !== null && (
                <div className="text-[10px] text-slate-500">
                  Confidence score {refl.confidence_brier} — {refl.confidence_note}
                </div>
              )}
              {Object.keys(refl.tools_that_failed).length > 0 && (
                <div className="text-[10px] text-hud-rose">
                  Tools that failed:{" "}
                  {Object.entries(refl.tools_that_failed)
                    .map(([t, n]) => `${t} (${n})`)
                    .join(", ")}
                </div>
              )}
              {refl.recent.slice(0, 3).map((r, i) => (
                <div key={i} className="rounded border border-white/5 bg-black/20 px-2.5 py-2">
                  <div className="text-[11px] text-slate-300">
                    <span className={r.achieved ? "text-hud-emerald" : "text-hud-rose"}>
                      {r.achieved ? "✓" : "✗"}
                    </span>{" "}
                    {r.goal}
                  </div>
                  {r.lessons.slice(0, 1).map((l) => (
                    <div key={l} className="mt-0.5 text-[10px] italic text-slate-500">{l}</div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* model routing */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <Gauge className="h-3.5 w-3.5 text-hud-amber" /> Model routing
          </div>
          {!route ? (
            <div className="py-6 text-center text-[11px] text-slate-500">Loading…</div>
          ) : route.providers.length === 0 ? (
            <div className="py-6 text-center text-[11px] text-slate-500">
              No LLM provider configured — Titan is running on its deterministic
              paths.
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-[10px] text-slate-500">
                Order in use:{" "}
                <span className="font-mono text-slate-300">
                  {route.effective_order.join(" → ")}
                </span>
              </div>
              {route.providers.map((p) => (
                <div
                  key={p.provider}
                  className="flex items-center justify-between gap-2 rounded border border-white/5 bg-black/20 px-2.5 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-[12px] text-white">
                      {p.provider}
                      {p.tripped && (
                        <span className="ml-2 rounded-full bg-rose-500/15 px-2 py-0.5 text-[9px] uppercase tracking-wider text-rose-400">
                          cooling down
                        </span>
                      )}
                      {!p.routable && !p.tripped && (
                        <span className="ml-2 text-[9px] text-slate-600">
                          too few samples to rank
                        </span>
                      )}
                    </div>
                    {p.last_error && (
                      <div className="truncate text-[10px] text-hud-rose">{p.last_error}</div>
                    )}
                  </div>
                  <div className="shrink-0 text-right font-mono text-[10px] text-slate-400">
                    <div>{p.success_rate}% ok</div>
                    <div className="text-slate-600">
                      {p.p50_latency_ms || "—"}ms · {p.calls} calls
                    </div>
                  </div>
                </div>
              ))}
              <div className="pt-1 text-[9px] italic text-slate-600">{route.note}</div>
            </div>
          )}
        </div>
      </div>

      {bi?.note && (
        <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-[10px] italic text-slate-500">
          <Activity className="mr-1 inline h-3 w-3" />
          {bi.note}
        </div>
      )}
    </div>
  );
}
