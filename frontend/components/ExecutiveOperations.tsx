"use client";

/**
 * ExecutiveOperations — the operator's daily surface.
 *
 * Four panels that existed only as API responses: what needs attention now,
 * what the business actually measures, what is connected, and a box that finds
 * a customer from anything you can remember about them.
 *
 * Two rules, both inherited from the backend rather than invented here:
 *
 * 1. **A null is not a zero.** Every metric arrives as
 *    `{value, measured, reason}`. When `measured` is false the value is `null`
 *    and this renders the REASON, never a `0`. With no payment processor
 *    connected, "$0 MRR" reads as a business result and the truth is that
 *    nobody could pay.
 * 2. **Empty is not broken.** `lib/api.ts`'s `get()` swallows failures into a
 *    fallback, which is right for a dashboard tile and wrong here — a panel
 *    that renders "nothing to show" when the request 500'd is the same lie in
 *    the other direction. So these fetch through a local helper that keeps the
 *    error and says so.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, CheckCircle2, HelpCircle, Plug, RefreshCw, Search as SearchIcon,
  ShieldAlert, XCircle,
} from "lucide-react";
import { authHeaders } from "@/lib/api";

/* ------------------------------------------------------------------ types */

type Measure = {
  value: number | Record<string, number> | null;
  measured: boolean;
  reason?: string;
  note?: string;
  source?: string;
};

type MetricsReport = {
  metrics: Record<string, Measure | Record<string, Measure>>;
  measured_count: number;
  unmeasured_count: number;
  durable: boolean;
};

type Note = {
  key: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  source: string;
  action: string;
};

type NotificationPayload = {
  notifications: Note[];
  counts: Record<string, number>;
  checks_failed: { check: string; error: string }[];
  not_emitted: { key: string; why: string }[];
};

type Integration = {
  key: string;
  name: string;
  category: string;
  status: "connected" | "not_configured" | "needs_attention" | "unknown";
  detail: string;
  unlocks: string;
  cost: string;
  configure?: string;
};

type IntegrationPayload = {
  integrations: Integration[];
  connected: number;
  total: number;
  note: string;
};

type Hit = {
  kind: string;
  id: string;
  label: string;
  sublabel: string;
  matched_on: string;
};

type SearchPayload = {
  results: Hit[];
  total: number;
  unavailable: { source: string; error: string }[];
};

type Loaded<T> = { state: "loading" } | { state: "ok"; data: T }
  | { state: "error"; error: string };

/* ------------------------------------------------------------- fetching */

async function load<T>(path: string): Promise<Loaded<T>> {
  try {
    const res = await fetch(`/api${path}`, {
      cache: "no-store",
      headers: authHeaders(),
    });
    if (!res.ok) return { state: "error", error: `HTTP ${res.status}` };
    return { state: "ok", data: (await res.json()) as T };
  } catch (e) {
    return { state: "error", error: e instanceof Error ? e.message : "failed" };
  }
}

/* -------------------------------------------------------------- helpers */

function Panel({ title, icon, children, right }: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="panel p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-hud-cyan">{icon}</span>
          <h3 className="hud-label">{title}</h3>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function Failed({ what, error }: { what: string; error: string }) {
  return (
    <p className="text-[11px] leading-relaxed text-hud-rose">
      {what} could not be loaded ({error}). This is a fault, not an empty
      result — the difference matters, so it is not shown as &ldquo;nothing to
      display&rdquo;.
    </p>
  );
}

const MONEY = new Set(["mrr_usd", "arr_usd", "granted_list_value_usd"]);

function formatValue(key: string, value: Measure["value"]): string {
  if (value === null) return "—";
  if (typeof value === "number") {
    if (MONEY.has(key)) return `$${value.toLocaleString()}`;
    if (key.endsWith("_pct")) return `${value}%`;
    return value.toLocaleString();
  }
  const entries = Object.entries(value);
  return entries.length ? entries.map(([k, v]) => `${k} ${v}`).join(" · ") : "none";
}

function label(key: string): string {
  return key
    .replace(/_usd$/, "")
    .replace(/_pct$/, " %")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function MeasureTile({ name, m }: { name: string; m: Measure }) {
  return (
    <div className="rounded-lg border border-edge bg-panel-2/40 p-3">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">
        {label(name)}
      </div>
      {m.measured ? (
        <>
          <div className="mt-1 font-mono text-xl font-semibold text-white">
            {formatValue(name, m.value)}
          </div>
          {m.note && (
            <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
              {m.note}
            </p>
          )}
        </>
      ) : (
        <>
          {/* Never a 0. `measured: false` means nothing was measured, and a
              zero here would be read as a business result. */}
          <div className="mt-1 font-mono text-sm font-semibold text-hud-amber">
            Not measured
          </div>
          <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
            {m.reason}
          </p>
        </>
      )}
    </div>
  );
}

const SEVERITY: Record<Note["severity"], { cls: string; icon: React.ReactNode }> = {
  critical: { cls: "text-hud-rose", icon: <ShieldAlert className="h-4 w-4" /> },
  warning: { cls: "text-hud-amber", icon: <AlertTriangle className="h-4 w-4" /> },
  info: { cls: "text-hud-cyan", icon: <HelpCircle className="h-4 w-4" /> },
};

const STATUS: Record<Integration["status"], { cls: string; icon: React.ReactNode; label: string }> = {
  connected: {
    cls: "text-hud-emerald", label: "Connected",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
  },
  needs_attention: {
    cls: "text-hud-amber", label: "Needs attention",
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
  },
  not_configured: {
    cls: "text-slate-500", label: "Not configured",
    icon: <XCircle className="h-3.5 w-3.5" />,
  },
  unknown: {
    cls: "text-hud-rose", label: "Could not check",
    icon: <HelpCircle className="h-3.5 w-3.5" />,
  },
};

/* ---------------------------------------------------------- the component */

export default function ExecutiveOperations() {
  const [metrics, setMetrics] = useState<Loaded<MetricsReport>>({ state: "loading" });
  const [notes, setNotes] = useState<Loaded<NotificationPayload>>({ state: "loading" });
  const [integrations, setIntegrations] = useState<Loaded<IntegrationPayload>>({ state: "loading" });
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Loaded<SearchPayload> | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    const [m, n, i] = await Promise.all([
      load<MetricsReport>("/founder/metrics"),
      load<NotificationPayload>("/founder/notifications"),
      load<IntegrationPayload>("/founder/integrations"),
    ]);
    setMetrics(m);
    setNotes(n);
    setIntegrations(i);
    setBusy(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    setHits({ state: "loading" });
    setHits(await load<SearchPayload>(`/founder/search?q=${encodeURIComponent(q)}`));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <button
          onClick={() => void refresh()}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg border border-edge bg-panel px-3 py-1.5 text-xs text-slate-400 transition-colors hover:text-slate-200 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* ---------------------------------------------------- attention -- */}
      <Panel title="Needs attention" icon={<AlertTriangle className="h-4 w-4" />}>
        {notes.state === "loading" && (
          <p className="text-[11px] text-slate-500">Checking…</p>
        )}
        {notes.state === "error" && <Failed what="Notifications" error={notes.error} />}
        {notes.state === "ok" && (
          <>
            {notes.data.notifications.length === 0 ? (
              <p className="text-[11px] text-hud-emerald">
                Nothing needs attention right now.
              </p>
            ) : (
              <ul className="space-y-2">
                {notes.data.notifications.map((n) => (
                  <li
                    key={n.key}
                    className="rounded-lg border border-edge bg-panel-2/40 p-3"
                  >
                    <div className={`flex items-center gap-2 ${SEVERITY[n.severity].cls}`}>
                      {SEVERITY[n.severity].icon}
                      <span className="text-xs font-semibold">{n.title}</span>
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                      {n.detail}
                    </p>
                    {n.action && (
                      <p className="mt-1 text-[11px] leading-relaxed text-hud-cyan">
                        → {n.action}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {notes.data.checks_failed.length > 0 && (
              <p className="mt-3 text-[11px] leading-relaxed text-hud-rose">
                {notes.data.checks_failed.length} check(s) could not run:{" "}
                {notes.data.checks_failed.map((c) => c.check).join(", ")}. A check
                that could not run is not an absence of a problem.
              </p>
            )}

            {/* The honest footnote. These are things the brief asks for that
                Titan cannot know yet, listed rather than faked. */}
            {notes.data.not_emitted.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-[10.5px] text-slate-500">
                  Deliberately not shown ({notes.data.not_emitted.length})
                </summary>
                <ul className="mt-2 space-y-1.5">
                  {notes.data.not_emitted.map((n) => (
                    <li key={n.key} className="text-[10.5px] leading-relaxed text-slate-500">
                      <span className="text-slate-400">{label(n.key)}</span> — {n.why}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </Panel>

      {/* ------------------------------------------------------ metrics -- */}
      <Panel
        title="Business metrics"
        icon={<CheckCircle2 className="h-4 w-4" />}
        right={
          metrics.state === "ok" ? (
            <span className="text-[10px] text-slate-500">
              {metrics.data.measured_count} measured ·{" "}
              {metrics.data.unmeasured_count} not
            </span>
          ) : null
        }
      >
        {metrics.state === "loading" && (
          <p className="text-[11px] text-slate-500">Loading…</p>
        )}
        {metrics.state === "error" && <Failed what="Metrics" error={metrics.error} />}
        {metrics.state === "ok" && (
          <>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {Object.entries(metrics.data.metrics).flatMap(([name, m]) =>
                "measured" in m
                  ? [<MeasureTile key={name} name={name} m={m as Measure} />]
                  : Object.entries(m as Record<string, Measure>).map(([sub, sm]) => (
                      <MeasureTile key={`${name}.${sub}`} name={sub} m={sm} />
                    )),
              )}
            </div>
            {!metrics.data.durable && (
              <p className="mt-3 text-[11px] leading-relaxed text-hud-amber">
                These counts do not survive the next rebuild — storage is not
                on a persistent mount.
              </p>
            )}
          </>
        )}
      </Panel>

      {/* ------------------------------------------------- integrations -- */}
      <Panel
        title="Integrations"
        icon={<Plug className="h-4 w-4" />}
        right={
          integrations.state === "ok" ? (
            <span className="text-[10px] text-slate-500">
              {integrations.data.connected} of {integrations.data.total} connected
            </span>
          ) : null
        }
      >
        {integrations.state === "loading" && (
          <p className="text-[11px] text-slate-500">Checking…</p>
        )}
        {integrations.state === "error" && (
          <Failed what="Integrations" error={integrations.error} />
        )}
        {integrations.state === "ok" && (
          <>
            <ul className="space-y-2">
              {integrations.data.integrations.map((row) => (
                <li
                  key={row.key}
                  className="rounded-lg border border-edge bg-panel-2/40 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`flex items-center gap-1.5 ${STATUS[row.status].cls}`}>
                      {STATUS[row.status].icon}
                      <span className="text-xs font-semibold">{row.name}</span>
                    </span>
                    <span className={`text-[10px] ${STATUS[row.status].cls}`}>
                      {STATUS[row.status].label}
                    </span>
                    <span className="rounded border border-edge px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-slate-500">
                      {row.cost}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                    {row.detail}
                  </p>
                  {row.configure && row.status !== "connected" && (
                    <p className="mt-1 text-[11px] leading-relaxed text-hud-cyan">
                      → {row.configure}
                    </p>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[10.5px] leading-relaxed text-slate-500">
              {integrations.data.note}
            </p>
          </>
        )}
      </Panel>

      {/* ------------------------------------------------------- search -- */}
      <Panel title="Find a customer" icon={<SearchIcon className="h-4 w-4" />}>
        <form onSubmit={runSearch} className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Email, business name, or a domain like example.com"
            className="w-full rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-sm text-slate-100 focus:border-hud-cyan/40 focus:outline-none"
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-4 text-sm text-hud-cyan transition-colors hover:bg-hud-cyan/20"
          >
            Search
          </button>
        </form>

        {hits?.state === "loading" && (
          <p className="mt-3 text-[11px] text-slate-500">Searching…</p>
        )}
        {hits?.state === "error" && (
          <div className="mt-3">
            <Failed what="Search" error={hits.error} />
          </div>
        )}
        {hits?.state === "ok" && (
          <div className="mt-3">
            {hits.data.results.length === 0 ? (
              <p className="text-[11px] text-slate-500">Nothing matched.</p>
            ) : (
              <ul className="space-y-1.5">
                {hits.data.results.map((h) => (
                  <li
                    key={`${h.kind}:${h.id}`}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-edge bg-panel-2/40 px-3 py-2"
                  >
                    <span className="rounded border border-edge px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-slate-500">
                      {h.kind}
                    </span>
                    <span className="text-xs text-slate-200">{h.label}</span>
                    <span className="text-[10.5px] text-slate-500">{h.sublabel}</span>
                    {/* Why this matched. A hit with no visible reason looks
                        like a bug, and a domain match is not a name match. */}
                    <span className="ml-auto text-[9.5px] text-hud-cyan">
                      matched {h.matched_on}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {hits.data.unavailable.length > 0 && (
              <p className="mt-2 text-[11px] leading-relaxed text-hud-rose">
                Could not search:{" "}
                {hits.data.unavailable.map((u) => u.source).join(", ")}. Fewer
                results because a source was down is not the same as fewer
                results because there are fewer.
              </p>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
