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
  Activity, AlertTriangle, BarChart3, Brain, Eye, Gauge, RefreshCw, TrendingUp,
  Users,
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

/** Founder-only. Served from /api/founder/analytics, which is registered
 *  sensitive server-side — a demo visitor gets 403, not a sample. */
type FunnelStep = {
  step: string;
  count: number;
  pct_of_signups: number;
  dropped_from_previous: number | null;
  source: string;
  reliable: boolean;
};
type AccountRow = {
  email: string;
  plan: string;
  plan_name: string;
  status: string;
  paying: boolean;
  days_since_signup: number;
  usage: Record<string, number>;
  business_count: number;
  businesses: { business_name: string; website: string; industry: string }[];
  actions: Record<string, number>;
  days_since_seen: number | null;
  returned_after_signup: boolean;
};
type Analytics = {
  totals: {
    accounts: number;
    signed_up_in_window: number;
    paying: number;
    active_7d: number;
    dormant_30d: number;
    by_plan: Record<string, number>;
    by_status: Record<string, number>;
  };
  revenue: {
    collectable: boolean;
    paying_accounts: number;
    committed_mrr_usd: number | null;
    note: string;
  };
  funnel: FunnelStep[];
  accounts: AccountRow[];
  activity: {
    recent: { ts: number; email: string; action: string; meta: Record<string, unknown> }[];
    totals: Record<string, number>;
  };
  storage_warning: string | null;
  note: string;
};

type Traffic = {
  views: number;
  bot_views: number;
  visitors_today: number;
  busiest_day_visitors: number;
  days_measured: number;
  series: { day: string; views: number; visitors: number; bot_views: number }[];
  top_paths: Record<string, number>;
  top_referrers: Record<string, number>;
  signups_total: number;
  conversion_note: string;
  note: string;
};

type SeoOverview = {
  titan: {
    checked: boolean;
    url: string;
    score: number | null;
    grade: string | null;
    open_findings: { id: string; severity: string; title: string }[];
    passed: string[];
    failed: string[];
    counts: Record<string, number>;
    minutes_ago: number | null;
    next_check_in_minutes: number | null;
    interval_hours: number;
    error: string | null;
    note: string;
  };
  clients: {
    id: string;
    business_name: string;
    website: string;
    country: string;
    score: number | null;
    grade: string | null;
    findings: number;
    audited: boolean;
  }[];
  client_average: number | null;
  unaudited: number;
  note: string;
};

/** Score colour. Null is grey — "not audited" must never look like "bad". */
function scoreTone(score: number | null): string {
  if (score === null || score === undefined) return "text-slate-600";
  if (score >= 80) return "text-hud-emerald";
  if (score >= 60) return "text-hud-amber";
  return "text-hud-rose";
}

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
  const [users, setUsers] = useState<Analytics | null>(null);
  const [traffic, setTraffic] = useState<Traffic | null>(null);
  const [seo, setSeo] = useState<SeoOverview | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [b, r, m, u, t, s] = await Promise.all([
        api<BiReport>(`/bi/${period}`),
        api<ReflectionReport>("/reflection"),
        api<RoutingReport>("/routing"),
        api<Analytics>("/founder/analytics"),
        api<Traffic>("/founder/traffic"),
        api<SeoOverview>("/founder/seo-overview"),
      ]);
      setBi(b);
      setRefl(r);
      setRoute(m);
      setUsers(u);
      setTraffic(t);
      setSeo(s);
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

      {/* who opened the site ---------------------------------------------- */}
      <div className="rounded-xl border border-white/10 bg-black/30 p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-slate-300">
          <Eye className="h-3.5 w-3.5 text-hud-cyan" /> Visitors
          <span className="ml-auto font-normal normal-case tracking-normal text-slate-600">
            no cookie · no vendor · no IP stored
          </span>
        </div>
        {!traffic ? (
          <div className="mt-3 text-[11px] text-slate-500">Not loaded.</div>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
              {[
                ["Page views", String(traffic.views), "text-white"],
                ["Visitors today", String(traffic.visitors_today), "text-hud-cyan"],
                ["Best day", String(traffic.busiest_day_visitors), "text-hud-emerald"],
                ["Crawler hits", String(traffic.bot_views), "text-slate-500"],
                ["Signups", String(traffic.signups_total),
                  traffic.signups_total > 0 ? "text-hud-emerald" : "text-slate-500"],
              ].map(([label, value, tone]) => (
                <div key={label as string}>
                  <div className={`font-mono text-xl font-semibold leading-none ${tone}`}>
                    {value}
                  </div>
                  <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                    {label}
                  </div>
                </div>
              ))}
            </div>

            {traffic.series.length > 1 && (
              <div className="mt-3">
                <Spark
                  series={Object.fromEntries(
                    traffic.series.map((d) => [d.day, d.visitors]),
                  )}
                />
                <div className="text-[10px] text-slate-600">
                  daily visitors · {traffic.days_measured} day
                  {traffic.days_measured === 1 ? "" : "s"} measured
                </div>
              </div>
            )}

            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-slate-600">
                  Top pages
                </div>
                {Object.keys(traffic.top_paths).length === 0 ? (
                  <div className="mt-1 text-[11px] text-slate-600">No page loads yet.</div>
                ) : (
                  Object.entries(traffic.top_paths).slice(0, 6).map(([p, n]) => (
                    <div key={p} className="mt-1 flex justify-between text-[11px]">
                      <span className="truncate text-slate-300">{p}</span>
                      <span className="font-mono text-slate-500">{n}</span>
                    </div>
                  ))
                )}
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-slate-600">
                  Where they came from
                </div>
                {Object.keys(traffic.top_referrers).length === 0 ? (
                  <div className="mt-1 text-[11px] text-slate-600">
                    No external referrers yet — every visit was direct.
                  </div>
                ) : (
                  Object.entries(traffic.top_referrers).slice(0, 6).map(([r, n]) => (
                    <div key={r} className="mt-1 flex justify-between text-[11px]">
                      <span className="truncate text-slate-300">{r}</span>
                      <span className="font-mono text-slate-500">{n}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="mt-3 text-[10px] leading-relaxed text-slate-600">
              {traffic.conversion_note}
            </div>
          </>
        )}
      </div>

      {/* Titan's own SEO beside every client's ----------------------------- */}
      <div className="rounded-xl border border-white/10 bg-black/30 p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-slate-300">
          <TrendingUp className="h-3.5 w-3.5 text-hud-emerald" /> SEO — Titan and clients
        </div>
        {!seo ? (
          <div className="mt-3 text-[11px] text-slate-500">Not loaded.</div>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap items-end gap-6">
              <div>
                <div className={`font-mono text-3xl font-semibold leading-none ${scoreTone(seo.titan.score)}`}>
                  {seo.titan.score ?? "—"}
                  {seo.titan.grade && (
                    <span className="ml-2 text-base text-slate-500">{seo.titan.grade}</span>
                  )}
                </div>
                <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                  Titan itself
                </div>
              </div>
              <div>
                <div className={`font-mono text-xl font-semibold leading-none ${scoreTone(seo.client_average)}`}>
                  {seo.client_average ?? "—"}
                </div>
                <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                  Client average
                </div>
              </div>
              {seo.unaudited > 0 && (
                <div>
                  <div className="font-mono text-xl font-semibold leading-none text-hud-amber">
                    {seo.unaudited}
                  </div>
                  <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                    Never audited
                  </div>
                </div>
              )}
            </div>

            {!seo.titan.checked && (
              <div className="mt-2 text-[11px] text-slate-500">
                Titan has not audited itself yet — the first check runs on the
                heartbeat shortly after boot.
              </div>
            )}

            {/* An audit that failed to run is not a passing audit. */}
            {seo.titan.error && (
              <div className="mt-2 flex items-start gap-2 rounded-lg border border-hud-rose/30 bg-hud-rose/5 px-3 py-2 text-[10px] text-hud-rose">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                <span>Last self-audit errored: {seo.titan.error}</span>
              </div>
            )}

            {seo.titan.checked && (
              <>
                <div className="mt-2 font-mono text-[10px] text-slate-500">
                  {seo.titan.url} · checked{" "}
                  {seo.titan.minutes_ago != null
                    ? `${seo.titan.minutes_ago} min ago`
                    : "—"}
                  {seo.titan.next_check_in_minutes != null &&
                    ` · next in ${Math.round(seo.titan.next_check_in_minutes)} min`}
                  {` · every ${seo.titan.interval_hours}h`}
                </div>

                {/* Everything it checked, not just the headline. A score with
                    no list is a number to be trusted rather than checked. */}
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-hud-rose">
                      Open findings ({seo.titan.open_findings.length})
                    </div>
                    {seo.titan.open_findings.length === 0 ? (
                      <p className="mt-1 text-[11px] text-hud-emerald">
                        Nothing outstanding.
                      </p>
                    ) : (
                      seo.titan.open_findings.map((f) => (
                        <div key={f.id} className="mt-1 flex gap-2 text-[11px]">
                          <span
                            className={`font-mono text-[9px] uppercase ${
                              f.severity === "critical" || f.severity === "high"
                                ? "text-hud-rose"
                                : f.severity === "medium"
                                  ? "text-hud-amber"
                                  : "text-slate-500"
                            }`}
                          >
                            {f.severity}
                          </span>
                          <span className="text-slate-300">{f.title}</span>
                        </div>
                      ))
                    )}
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-hud-emerald">
                      Passing ({seo.titan.passed.length})
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {seo.titan.passed.slice(0, 24).map((p) => (
                        <span
                          key={p}
                          className="rounded border border-hud-emerald/25 bg-hud-emerald/5 px-1.5 py-0.5 font-mono text-[9px] text-hud-emerald"
                        >
                          {p}
                        </span>
                      ))}
                      {seo.titan.passed.length === 0 && (
                        <span className="text-[11px] text-slate-600">
                          Nothing recorded as passing.
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}

            {seo.clients.length > 0 && (
              <div className="mt-4 space-y-1.5">
                {seo.clients.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 text-[11px]">
                    <span className="w-44 shrink-0 truncate text-slate-300">
                      {c.business_name}
                    </span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                      {c.score !== null && (
                        <div
                          className={`h-full rounded-full ${
                            c.score >= 80
                              ? "bg-hud-emerald/70"
                              : c.score >= 60
                                ? "bg-hud-amber/70"
                                : "bg-hud-rose/70"
                          }`}
                          style={{ width: `${c.score}%` }}
                        />
                      )}
                    </div>
                    <span className={`w-24 shrink-0 text-right font-mono ${scoreTone(c.score)}`}>
                      {c.score === null ? "not audited" : `${c.score} ${c.grade ?? ""}`}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* A client outscoring the platform selling them SEO is something
                he needs to find out here, not from the client. */}
            {seo.titan.score !== null &&
              seo.clients.some((c) => c.score !== null && c.score > (seo.titan.score ?? 0)) && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-3 py-2 text-[10px] leading-relaxed text-hud-amber">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>
                    A client site scores higher than Titan&apos;s own. Prospects can
                    check that score — fix Titan&apos;s findings before selling
                    against it.
                  </span>
                </div>
              )}

            <div className="mt-3 text-[10px] leading-relaxed text-slate-600">{seo.note}</div>
          </>
        )}
      </div>

      {/* who signed up, and what they actually did ------------------------ */}
      <div className="rounded-xl border border-white/10 bg-black/30 p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-slate-300">
          <Users className="h-3.5 w-3.5 text-hud-emerald" /> Subscribers
          <span className="ml-auto font-normal normal-case tracking-normal text-slate-600">
            founder only
          </span>
        </div>

        {!users ? (
          <div className="mt-3 text-[11px] text-slate-500">
            Not loaded. This endpoint is founder-only — a demo session is refused.
          </div>
        ) : users.totals.accounts === 0 ? (
          <div className="mt-3 text-[11px] text-slate-400">
            No one has signed up yet. This is a real measurement, not a loading
            state — the funnel below will fill in as people arrive.
          </div>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
              {[
                ["Accounts", String(users.totals.accounts), "text-white"],
                ["Paying", String(users.totals.paying),
                  users.totals.paying > 0 ? "text-hud-emerald" : "text-slate-500"],
                ["Active 7d", String(users.totals.active_7d), "text-hud-emerald"],
                ["Dormant 30d", String(users.totals.dormant_30d),
                  users.totals.dormant_30d > 0 ? "text-hud-amber" : "text-slate-500"],
                ["Committed MRR",
                  users.revenue.committed_mrr_usd === null
                    ? "n/a"
                    : `$${money(users.revenue.committed_mrr_usd)}`,
                  users.revenue.collectable ? "text-hud-emerald" : "text-slate-500"],
              ].map(([label, value, tone]) => (
                <div key={label as string}>
                  <div className={`font-mono text-xl font-semibold leading-none ${tone}`}>
                    {value}
                  </div>
                  <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                    {label}
                  </div>
                </div>
              ))}
            </div>

            {/* A currency figure that cannot be collected must say so, or a
                dash reads as "zero earned" rather than "nothing can be paid". */}
            {!users.revenue.collectable && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-3 py-2 text-[10px] leading-relaxed text-hud-amber">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{users.revenue.note}</span>
              </div>
            )}

            {/* funnel */}
            <div className="mt-4 space-y-1.5">
              {users.funnel.map((s) => (
                <div key={s.step} className="flex items-center gap-3">
                  <div className="w-44 shrink-0 text-[11px] text-slate-400">
                    {s.step}
                    {!s.reliable && (
                      <span
                        title={`Counted from the activity log, which began when analytics shipped. A zero here means not observed, not never happened.`}
                        className="ml-1 cursor-help text-slate-600"
                      >
                        *
                      </span>
                    )}
                  </div>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className={`h-full rounded-full ${
                        s.reliable ? "bg-hud-emerald/70" : "bg-slate-500/50"
                      }`}
                      style={{ width: `${Math.max(s.pct_of_signups, s.count > 0 ? 2 : 0)}%` }}
                    />
                  </div>
                  <div className="w-24 shrink-0 text-right font-mono text-[11px] text-slate-300">
                    {s.count}
                    <span className="ml-1 text-slate-600">{s.pct_of_signups}%</span>
                  </div>
                </div>
              ))}
              <div className="pt-1 text-[10px] text-slate-600">
                * counted from the activity log only — a zero means not observed
                since analytics shipped, not never happened.
              </div>
            </div>

            {/* per-account detail */}
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-[11px]">
                <thead className="text-[10px] uppercase tracking-widest text-slate-600">
                  <tr>
                    <th className="pb-2 font-normal">Email</th>
                    <th className="pb-2 font-normal">Plan</th>
                    <th className="pb-2 font-normal">Signed up</th>
                    <th className="pb-2 font-normal">Businesses</th>
                    <th className="pb-2 font-normal">Audits</th>
                    <th className="pb-2 font-normal">Last seen</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  {users.accounts.map((a) => (
                    <tr key={a.email} className="border-t border-white/5">
                      <td className="py-2 pr-3 font-mono text-slate-200">{a.email}</td>
                      <td className="py-2 pr-3">
                        <span
                          className={
                            a.paying ? "text-hud-emerald" : "text-slate-400"
                          }
                        >
                          {a.plan_name}
                        </span>
                        {a.status !== "active" && (
                          <span className="ml-1 text-hud-amber">({a.status})</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-slate-500">
                        {a.days_since_signup}d ago
                      </td>
                      <td className="py-2 pr-3">
                        {a.business_count === 0 ? (
                          <span className="text-hud-rose">none</span>
                        ) : (
                          <span title={a.businesses.map((b) => b.business_name).join(", ")}>
                            {a.business_count}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-slate-400">
                        {a.usage.audits ?? 0}
                      </td>
                      <td className="py-2 pr-3">
                        {a.days_since_seen === null ? (
                          <span className="text-hud-rose" title="Signed up and never came back">
                            never returned
                          </span>
                        ) : (
                          <span className="text-slate-500">{a.days_since_seen}d ago</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {users.storage_warning && (
              <div className="mt-3 flex items-start gap-2 text-[10px] leading-relaxed text-slate-500">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-hud-amber" />
                <span>{users.storage_warning}</span>
              </div>
            )}
          </>
        )}
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
