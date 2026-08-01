"use client";

/**
 * SeoCommand — the SEO view of the command centre.
 *
 * The engines already existed (client_seo, local_seo, compliance,
 * client_watch) but the only way to see their output was the client-facing
 * portal or a PDF. That is backwards: the person doing the work had the least
 * detailed view of it.
 *
 * The one rule this view exists to preserve: legal exposure is shown BESIDE
 * the SEO score, never folded into it. A missing Impressum is not "8 points
 * off" — it is a fine and an open invitation for a competitor Abmahnung, and
 * averaging it into a 0-100 number hides the single most valuable finding the
 * product produces.
 *
 * Everything here reads /api/admin/*, which stays behind the founder token.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity, AlertTriangle, Check, Copy, Gavel, Globe2, Loader2,
  MapPin, RefreshCw, Search, Sparkles, TrendingDown, TrendingUp,
} from "lucide-react";

type Finding = {
  id: string;
  severity: string;
  title: string;
  detail: string;
  fix: string;
};

type Legal = {
  country?: string;
  country_name?: string;
  law?: string;
  in_eu_eea?: boolean;
  abmahnung_risk?: boolean;
  findings: Finding[];
  legal_critical: number;
  disclaimer?: string;
};

type LocalDim = { label: string; weight: number; earned: number };

type LocalReport = {
  score: number;
  vertical?: string;
  dimensions: Record<string, LocalDim>;
  findings: { dimension: string; severity: string; title: string }[];
  ai_search?: {
    note: string;
    why_it_matters: string;
    actions: string[];
  };
};

type Audit = {
  ok: boolean;
  url?: string;
  error?: string;
  score?: number;
  grade?: string;
  passed?: string[];
  failed?: string[];
  schema_types?: string[];
  findings: Finding[];
  legal?: Legal;
  local?: LocalReport;
  counts?: Record<string, number>;
  note?: string;
};

type ClientRow = {
  id: string;
  business_name: string;
  website?: string;
  city?: string;
  country?: string;
  industry?: string;
  last_audit?: Audit;
  last_watch?: number | null;
};

type WatchTrend = {
  client: string;
  from: number;
  to: number;
  delta: number;
  checks: number;
};

type WatchSummary = {
  watching: number;
  unwatched: number;
  interval_hours: number;
  recent_alerts: { client: string; message: string; ts: number; severity: string }[];
  trends: WatchTrend[];
  note?: string;
};

type WatchChange = {
  severity: string;
  kind: string;
  title: string;
  detail: string;
  action: string;
};

const SEV_STYLE: Record<string, string> = {
  "legal-critical": "border-rose-500/50 bg-rose-500/10 text-rose-300",
  critical: "border-rose-500/40 bg-rose-500/5 text-rose-400",
  high: "border-amber-500/40 bg-amber-500/5 text-amber-400",
  medium: "border-sky-500/40 bg-sky-500/5 text-sky-400",
  low: "border-slate-600/40 bg-slate-500/5 text-slate-400",
  info: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400",
};

const GRADE_TONE: Record<string, string> = {
  A: "text-hud-emerald",
  B: "text-hud-emerald",
  C: "text-hud-amber",
  D: "text-hud-amber",
  F: "text-hud-rose",
};

function token(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("titan_token") ||
    sessionStorage.getItem("titan_token") ||
    ""
  );
}

async function api(path: string, init: RequestInit = {}) {
  return fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token()}`,
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
}

function Bar({ dim }: { dim: LocalDim }) {
  const pct = dim.weight > 0 ? Math.round((dim.earned / dim.weight) * 100) : 0;
  const tone =
    pct >= 80 ? "bg-hud-emerald" : pct >= 40 ? "bg-hud-amber" : "bg-hud-rose";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[11px] text-slate-300">{dim.label}</span>
        <span className="font-mono text-[10px] text-slate-500">
          {dim.earned}/{dim.weight}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-black/50">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function SeoCommand() {
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<ClientRow | null>(null);
  const [watch, setWatch] = useState<WatchSummary | null>(null);
  // Kept as {firstRun, items} rather than a bare list: an empty list means two
  // different things — "no baseline yet" on the first check, and "nothing
  // changed" on every check after — and showing the first message for the
  // second case tells the client the monitoring never ran.
  const [changes, setChanges] =
    useState<{ firstRun: boolean; items: WatchChange[] } | null>(null);
  const [schema, setSchema] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState<"" | "audit" | "watch" | "schema">("");
  const [err, setErr] = useState("");

  const loadList = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([api("/admin/clients"), api("/admin/watch")]);
      if (a.ok) {
        const data = (await a.json()) as { clients: ClientRow[] };
        setClients(data.clients || []);
        setSelected((cur) => cur || data.clients?.[0]?.id || "");
      }
      if (b.ok) setWatch((await b.json()) as WatchSummary);
    } catch {
      /* polled again shortly */
    }
  }, []);

  const loadDetail = useCallback(async (cid: string) => {
    if (!cid) {
      setDetail(null);
      return;
    }
    try {
      const r = await api(`/admin/clients/${cid}`);
      if (r.ok) setDetail((await r.json()) as ClientRow);
    } catch {
      /* keep whatever is on screen */
    }
  }, []);

  useEffect(() => {
    loadList();
    const t = setInterval(loadList, 60_000);
    return () => clearInterval(t);
  }, [loadList]);

  useEffect(() => {
    setChanges(null);
    setSchema("");
    setCopied(false);
    setErr("");
    loadDetail(selected);
  }, [selected, loadDetail]);

  const runAudit = async () => {
    if (!selected) return;
    setBusy("audit");
    setErr("");
    try {
      const r = await api(`/admin/clients/${selected}/seo`, { method: "POST" });
      if (!r.ok) {
        setErr("The audit request failed. Check the site is reachable.");
        return;
      }
      await loadDetail(selected);
      await loadList();
    } finally {
      setBusy("");
    }
  };

  const checkNow = async () => {
    if (!selected) return;
    setBusy("watch");
    setErr("");
    try {
      const r = await api(`/admin/clients/${selected}/watch`, { method: "POST" });
      if (!r.ok) {
        setErr(
          ((await r.json()) as { detail?: string }).detail ||
            "Could not run the check.",
        );
        return;
      }
      const data = (await r.json()) as { changes: WatchChange[]; first_run: boolean };
      setChanges({ firstRun: data.first_run, items: data.changes || [] });
      await loadDetail(selected);
      await loadList();
    } finally {
      setBusy("");
    }
  };

  const loadSchema = async () => {
    if (!selected) return;
    setBusy("schema");
    try {
      const r = await api(`/admin/clients/${selected}/seo/schema`);
      if (r.ok) setSchema(((await r.json()) as { json_ld: string }).json_ld);
    } finally {
      setBusy("");
    }
  };

  const copySchema = async () => {
    try {
      await navigator.clipboard.writeText(schema);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — the block is selectable on screen anyway */
    }
  };

  const audit = detail?.last_audit;
  const legal = audit?.legal;
  const local = audit?.local;

  const legalCritical = legal?.legal_critical ?? 0;
  const otherFindings = useMemo(
    () => (audit?.findings || []).filter((f) => f.severity !== "legal-critical"),
    [audit],
  );
  const legalFindings = useMemo(
    () => (audit?.findings || []).filter((f) => f.severity === "legal-critical"),
    [audit],
  );

  const tile = (label: string, value: string, sub: string, tone: string) => (
    <div className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
      <div className={`font-mono text-2xl font-semibold leading-none ${tone}`}>
        {value}
      </div>
      <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-[10px] text-slate-600">{sub}</div>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-widest text-white">
            <Search className="h-4 w-4 text-hud-cyan" /> SEO COMMAND
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Technical · local · legal — measured from the live site, per client
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={runAudit}
            disabled={!selected || busy !== ""}
            className="flex items-center gap-1 rounded-lg border border-hud-cyan/40 px-3 py-1.5 text-[11px] text-hud-cyan transition hover:bg-hud-cyan/10 disabled:opacity-40"
          >
            {busy === "audit" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Search className="h-3 w-3" />
            )}
            Run audit
          </button>
          <button
            onClick={checkNow}
            disabled={!selected || busy !== ""}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-violet/50 hover:text-hud-violet disabled:opacity-40"
          >
            {busy === "watch" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Activity className="h-3 w-3" />
            )}
            Check for changes
          </button>
          <button
            onClick={loadList}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-amber/50 hover:text-hud-amber"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </div>

      {/* client picker */}
      {clients.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-black/30 py-10 text-center text-[12px] text-slate-500">
          No clients yet. Onboard one in the Clients tab, then audit it here.
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {clients.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelected(c.id)}
              className={`rounded-lg border px-3 py-1.5 text-[11px] transition ${
                selected === c.id
                  ? "border-hud-cyan/50 bg-hud-cyan/10 text-hud-cyan"
                  : "border-edge bg-panel/80 text-slate-400 hover:text-slate-200"
              }`}
            >
              {c.business_name}
            </button>
          ))}
        </div>
      )}

      {err && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-[11px] text-rose-400">
          {err}
        </div>
      )}

      {/* no audit yet */}
      {clients.length > 0 && !audit && (
        <div className="rounded-xl border border-white/10 bg-black/30 py-10 text-center text-[12px] text-slate-500">
          No audit stored for {detail?.business_name || "this client"} yet. Run
          one — it reads the live site over HTTP and takes a few seconds.
        </div>
      )}

      {/* unreachable */}
      {audit && !audit.ok && (
        <div className="flex items-start gap-2 rounded-xl border border-rose-500/50 bg-rose-500/10 px-4 py-3 text-[12px] text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <b>{audit.url} could not be loaded</b> — {audit.error}. Nothing else
            can be checked until the site responds.
          </div>
        </div>
      )}

      {audit?.ok && (
        <>
          {/* scores — deliberately three separate numbers */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            {tile(
              "Technical SEO",
              `${audit.score}`,
              `grade ${audit.grade} · ${audit.passed?.length ?? 0} of ${
                (audit.passed?.length ?? 0) + (audit.failed?.length ?? 0)
              } checks pass`,
              GRADE_TONE[audit.grade || ""] || "text-hud-amber",
            )}
            {tile(
              "Local visibility",
              `${local?.score ?? 0}`,
              `${local?.vertical || "unknown"} · 2026 ranking weights`,
              (local?.score ?? 0) >= 60 ? "text-hud-emerald" : "text-hud-amber",
            )}
            {tile(
              "Legal exposure",
              `${legalCritical}`,
              legal?.country_name
                ? `${legal.country_name} · not scored, priced`
                : "jurisdiction unknown",
              legalCritical > 0 ? "text-hud-rose" : "text-hud-emerald",
            )}
            {tile(
              "Open findings",
              `${audit.findings.length}`,
              `${audit.counts?.critical ?? 0} critical · ${
                audit.counts?.high ?? 0
              } high`,
              "text-hud-violet",
            )}
          </div>

          <div className="text-[10px] italic text-slate-600">
            Legal exposure is counted separately on purpose. Averaging it into
            the SEO score would hide the most expensive finding on the page.
          </div>

          {/* Abmahnung banner — the differentiator, stated in money */}
          {legalCritical > 0 && legal?.abmahnung_risk && (
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-start gap-2 rounded-xl border border-rose-500/50 bg-rose-500/10 px-4 py-3 text-[12px] text-rose-200"
            >
              <Gavel className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <b>Competitor Abmahnung risk — {legal.country_name}.</b> In this
                jurisdiction any competitor can serve a formal cease-and-desist
                over these findings and bill their legal costs. Fix before
                anything else on this page.
                {legal.law ? (
                  <span className="mt-1 block text-[10px] text-rose-300/80">
                    {legal.law}
                  </span>
                ) : null}
              </div>
            </motion.div>
          )}

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {/* legal */}
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
                <Gavel className="h-3.5 w-3.5 text-rose-400" /> Legal compliance
                {legal?.country_name ? ` — ${legal.country_name}` : ""}
              </div>
              {legalFindings.length === 0 ? (
                <div className="py-6 text-center text-[11px] text-emerald-400">
                  Nothing legally critical found on the served page.
                </div>
              ) : (
                <div className="space-y-2">
                  {legalFindings.map((f) => (
                    <div
                      key={f.id}
                      className={`rounded-lg border px-3 py-2.5 ${SEV_STYLE["legal-critical"]}`}
                    >
                      <div className="text-[12px]">{f.title}</div>
                      <div className="mt-1 text-[10px] text-slate-300">{f.detail}</div>
                      <div className="mt-1 text-[10px] italic text-slate-400">
                        Fix: {f.fix}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {legal?.disclaimer && (
                <div className="mt-3 text-[9px] italic text-slate-600">
                  {legal.disclaimer}
                </div>
              )}
            </div>

            {/* local dimensions */}
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
                <MapPin className="h-3.5 w-3.5 text-hud-emerald" /> Local ranking
                factors
              </div>
              {!local?.dimensions ? (
                <div className="py-6 text-center text-[11px] text-slate-500">
                  Run an audit to score the local dimensions.
                </div>
              ) : (
                <div className="space-y-3">
                  {Object.entries(local.dimensions).map(([k, d]) => (
                    <Bar key={k} dim={d} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* findings */}
          <div className="rounded-xl border border-white/10 bg-black/30 p-4">
            <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
              <AlertTriangle className="h-3.5 w-3.5 text-hud-amber" /> SEO
              findings ({otherFindings.length})
            </div>
            {otherFindings.length === 0 ? (
              <div className="py-6 text-center text-[11px] text-emerald-400">
                No SEO findings outstanding.
              </div>
            ) : (
              <div className="scroll-thin max-h-[420px] space-y-2 overflow-y-auto pr-1">
                {otherFindings.map((f, i) => (
                  <div
                    key={`${f.id}-${i}`}
                    className={`rounded-lg border px-3 py-2.5 ${
                      SEV_STYLE[f.severity] || SEV_STYLE.low
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-[12px]">{f.title}</span>
                      <span className="shrink-0 rounded-full border border-current px-2 py-0.5 text-[9px] uppercase tracking-wider">
                        {f.severity}
                      </span>
                    </div>
                    <div className="mt-1 text-[10px] text-slate-400">{f.detail}</div>
                    <div className="mt-1 text-[10px] italic text-slate-500">
                      Fix: {f.fix}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {/* schema */}
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
                  <Sparkles className="h-3.5 w-3.5 text-hud-violet" /> Structured
                  data
                </div>
                <button
                  onClick={schema ? copySchema : loadSchema}
                  disabled={busy === "schema"}
                  className="flex items-center gap-1 rounded-md border border-white/10 px-2.5 py-1 text-[10px] text-slate-300 transition hover:border-hud-violet/50 hover:text-hud-violet disabled:opacity-40"
                >
                  {busy === "schema" ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : copied ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                  {schema ? (copied ? "Copied" : "Copy JSON-LD") : "Generate JSON-LD"}
                </button>
              </div>
              <div className="text-[11px] text-slate-400">
                Found on the page:{" "}
                {audit.schema_types?.length ? (
                  <span className="text-hud-emerald">
                    {audit.schema_types.join(", ")}
                  </span>
                ) : (
                  <span className="text-hud-rose">none</span>
                )}
              </div>
              {schema && (
                <pre className="scroll-thin mt-3 max-h-64 overflow-auto rounded-lg bg-black/50 p-3 font-mono text-[10px] leading-relaxed text-slate-300">
                  {schema}
                </pre>
              )}
            </div>

            {/* AI search */}
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
                <Globe2 className="h-3.5 w-3.5 text-hud-cyan" /> AI search
              </div>
              {local?.ai_search ? (
                <div className="space-y-2 text-[11px] text-slate-400">
                  <p>{local.ai_search.note}</p>
                  <p className="text-slate-500">{local.ai_search.why_it_matters}</p>
                  <ul className="mt-2 space-y-1">
                    {local.ai_search.actions.map((a) => (
                      <li key={a} className="flex items-start gap-1.5 text-slate-300">
                        <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-hud-cyan" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="py-6 text-center text-[11px] text-slate-500">
                  Run an audit to see the AI-search actions.
                </div>
              )}
            </div>
          </div>

          {audit.note && (
            <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-[10px] italic text-slate-500">
              {audit.note}
            </div>
          )}
        </>
      )}

      {/* monitoring */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <Activity className="h-3.5 w-3.5 text-hud-violet" /> 24/7 monitoring
          </div>
          <div className="mb-3 text-[11px] text-slate-400">
            Watching <b className="text-white">{watch?.watching ?? 0}</b> site(s)
            every <b className="text-white">{watch?.interval_hours ?? 6}h</b>
            {watch?.unwatched ? (
              <span className="text-hud-amber">
                {" "}
                · {watch.unwatched} client(s) have no website on file
              </span>
            ) : null}
          </div>

          {changes !== null && (
            <div className="mb-3 space-y-2">
              {changes.items.length === 0 ? (
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-400">
                  {changes.firstRun
                    ? "Baseline recorded — nothing to diff against yet. The next check reports what changed."
                    : "Checked just now — nothing changed since the last check."}
                </div>
              ) : (
                changes.items.map((c, i) => (
                  <div
                    key={`${c.kind}-${i}`}
                    className={`rounded-lg border px-3 py-2.5 ${
                      SEV_STYLE[c.severity] || SEV_STYLE.low
                    }`}
                  >
                    <div className="text-[12px]">{c.title}</div>
                    <div className="mt-1 text-[10px] text-slate-400">{c.detail}</div>
                    <div className="mt-1 text-[10px] italic text-slate-500">
                      {c.action}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          <div className="space-y-1.5">
            {!watch?.recent_alerts?.length ? (
              <div className="py-4 text-center text-[11px] text-slate-500">
                No alerts raised.
              </div>
            ) : (
              watch.recent_alerts.map((a, i) => (
                <div
                  key={`${a.client}-${i}`}
                  className={`rounded-lg border px-3 py-2 text-[11px] ${
                    SEV_STYLE[a.severity] || SEV_STYLE.low
                  }`}
                >
                  <b>{a.client}</b> — {a.message}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <TrendingUp className="h-3.5 w-3.5 text-hud-emerald" /> Trend since
            first check
          </div>
          {!watch?.trends?.length ? (
            <div className="py-6 text-center text-[11px] text-slate-500">
              A trend needs at least two checks. Run &ldquo;Check for
              changes&rdquo; twice, or let the heartbeat do it.
            </div>
          ) : (
            <div className="space-y-2">
              {watch.trends.map((t) => (
                <div
                  key={t.client}
                  className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12px] text-white">{t.client}</div>
                    <div className="text-[10px] text-slate-500">
                      {t.checks} checks · {t.from} → {t.to}
                    </div>
                  </div>
                  <div
                    className={`flex items-center gap-1 font-mono text-[13px] ${
                      t.delta > 0
                        ? "text-hud-emerald"
                        : t.delta < 0
                        ? "text-hud-rose"
                        : "text-slate-500"
                    }`}
                  >
                    {t.delta > 0 ? (
                      <TrendingUp className="h-3.5 w-3.5" />
                    ) : t.delta < 0 ? (
                      <TrendingDown className="h-3.5 w-3.5" />
                    ) : null}
                    {t.delta > 0 ? "+" : ""}
                    {t.delta}
                  </div>
                </div>
              ))}
            </div>
          )}
          {watch?.note && (
            <div className="mt-3 text-[9px] italic text-slate-600">{watch.note}</div>
          )}
        </div>
      </div>
    </div>
  );
}
