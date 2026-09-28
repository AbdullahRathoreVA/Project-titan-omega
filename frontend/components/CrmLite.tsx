"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Filter, Plus, Search, Trash2, Users } from "lucide-react";
import { api } from "@/lib/api";
import { isCustomer } from "@/lib/session";
import type { LeadsState } from "@/lib/types";

type DiscoverResult = {
  created: { id: string; name: string; website?: string }[];
  researched: number;
  reason: string;
  rejected?: { directory: number; duplicate: number; already_known: number };
};

const STAGE_BAR: Record<string, string> = {
  new: "bg-hud-cyan",
  contacted: "bg-hud-amber",
  replied: "bg-hud-violet",
  won: "bg-hud-emerald",
};

const STAGE_LABEL: Record<string, string> = {
  new: "Leads added",
  contacted: "Contacted",
  replied: "Replied",
  won: "Won",
};

const STATUS_COLOR: Record<string, string> = {
  new: "text-hud-cyan border-hud-cyan/30",
  contacted: "text-hud-amber border-hud-amber/30",
  replied: "text-hud-violet border-hud-violet/30",
  won: "text-hud-emerald border-hud-emerald/30",
  lost: "text-slate-500 border-edge",
};

// Where a lead came from. The founder's list names his own channels (Fiverr,
// schools for Career Mind); a subscriber's covers how any business meets people.
const FOUNDER_SOURCES: [string, string][] = [
  ["manual", "Manual"], ["fiverr", "Fiverr"], ["linkedin", "LinkedIn"],
  ["school", "School/Uni"], ["jobradar", "Job Radar"], ["instagram", "Instagram"],
];
const CUSTOMER_SOURCES: [string, string][] = [
  ["manual", "Manual"], ["website", "Website"], ["phone", "Phone / walk-in"],
  ["google", "Google"], ["instagram", "Instagram"], ["facebook", "Facebook"],
  ["linkedin", "LinkedIn"],
];

const NEXT_STATUS: Record<string, string> = {
  new: "contacted",
  contacted: "replied",
  replied: "won",
};

// CRM-lite: the leads pipeline — new → contacted → replied → won/lost.
export function CrmLite() {
  const [customer] = useState(() => isCustomer());
  const [state, setState] = useState<LeadsState | null>(null);
  const [name, setName] = useState("");
  const [source, setSource] = useState("manual");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [finding, setFinding] = useState(false);
  const [found, setFound] = useState<DiscoverResult | null>(null);

  const refresh = useCallback(async () => {
    setState(await api.leads());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const discover = async () => {
    if (finding || query.trim().length < 3) return;
    setFinding(true);
    setFound(null);
    try {
      const res = await api.discoverLeads(query.trim());
      setFound(res);
      await refresh();
    } finally {
      setFinding(false);
    }
  };

  const add = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await api.createLead(name, source, contact, "");
      setName("");
      setContact("");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const advance = async (id: string, current: string) => {
    const next = NEXT_STATUS[current];
    if (!next) return;
    await api.setLeadStatus(id, next);
    await refresh();
  };

  const markLost = async (id: string) => {
    await api.setLeadStatus(id, "lost");
    await refresh();
  };

  const remove = async (id: string) => {
    await api.deleteLead(id);
    await refresh();
  };

  const counts = state?.counts ?? {};

  return (
    <div className="space-y-4">
      {/* Find real businesses, file them, audit their sites, draft the approach.
          Directories and duplicates are dropped server-side — see
          engines/prospecting.py for why that filtering is the whole value. */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Find leads</h2>
          </div>
          <span className="hud-label">audits their site · drafts nothing sent</span>
        </header>
        <div className="space-y-2 p-3">
          <div className="flex flex-wrap gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void discover()}
              placeholder="leather goods manufacturer Sialkot Pakistan"
              className="min-w-0 flex-1 rounded-lg border border-edge bg-black/40 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600"
            />
            <button
              onClick={() => void discover()}
              disabled={finding || query.trim().length < 3}
              className="rounded-lg border border-hud-emerald/40 bg-hud-emerald/10 px-4 py-2 text-xs font-medium text-hud-emerald transition hover:bg-hud-emerald/20 disabled:opacity-40"
            >
              {finding ? "Searching…" : "Find"}
            </button>
          </div>
          <p className="text-[10px] text-slate-600">
            A town and a trade works better than an industry alone. Titan audits
            the first three sites it finds and drafts outreach from the real
            findings — it never sends anything.
          </p>
          {found && (
            <div
              className={`rounded-lg border px-3 py-2 text-[11px] ${
                found.created.length
                  ? "border-hud-emerald/30 bg-hud-emerald/5 text-hud-emerald"
                  : "border-hud-amber/30 bg-hud-amber/5 text-hud-amber"
              }`}
            >
              {found.created.length ? (
                <>
                  Added {found.created.length} lead
                  {found.created.length === 1 ? "" : "s"}, audited{" "}
                  {found.researched}.{" "}
                  {found.rejected && (
                    <span className="text-slate-500">
                      Dropped {found.rejected.directory} director
                      {found.rejected.directory === 1 ? "y" : "ies"},{" "}
                      {found.rejected.duplicate} duplicate
                      {found.rejected.duplicate === 1 ? "" : "s"},{" "}
                      {found.rejected.already_known} already in your CRM.
                    </span>
                  )}
                </>
              ) : (
                found.reason
              )}
            </div>
          )}
        </div>
      </section>

      <div className="grid grid-cols-5 gap-2">
        {(state?.statuses ?? ["new", "contacted", "replied", "won", "lost"]).map((s) => (
          <div key={s} className="panel px-3 py-2 text-center">
            <div className={`font-mono text-xl font-semibold ${STATUS_COLOR[s]?.split(" ")[0] ?? "text-slate-300"}`}>
              {counts[s] ?? 0}
            </div>
            <div className="text-[9px] uppercase tracking-wide text-slate-500">{s}</div>
          </div>
        ))}
      </div>

      {/* Conversion funnel. Built from how far each lead EVER got, not from the
          status counts above — a lead that reached WON has already left
          CONTACTED, so a counts-based chart would show conversion rising. */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Lead → Won Funnel</h2>
          </div>
          <span className="hud-label">
            {(state?.conversion_pct ?? 0).toFixed(1)}% end-to-end
          </span>
        </header>
        <div className="space-y-3 p-3">
          {!state?.funnel?.length || state.items.length === 0 ? (
            <div className="py-5 text-center text-[11px] text-slate-600">
              No leads yet — the funnel fills in as you add and advance them.
            </div>
          ) : (
            <>
              {state.funnel.map((row) => (
                <div key={row.stage}>
                  <div className="mb-1 flex items-baseline justify-between">
                    <span className="text-[11px] text-slate-300">
                      {STAGE_LABEL[row.stage] ?? row.stage}
                      {row.dropped > 0 && (
                        <span className="ml-2 text-[10px] text-hud-rose">
                          −{row.dropped} dropped here
                        </span>
                      )}
                    </span>
                    <span className="font-mono text-[10px] text-slate-500">
                      {row.reached} · {row.pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-black/50">
                    <div
                      className={`h-full rounded-full ${STAGE_BAR[row.stage] ?? "bg-slate-500"}`}
                      style={{ width: `${Math.max(row.pct, row.reached > 0 ? 2 : 0)}%` }}
                    />
                  </div>
                </div>
              ))}
              <div className="pt-1 text-[10px] text-slate-600">
                {state.lost > 0
                  ? `${state.lost} lead(s) marked lost — each still counts at the furthest stage it reached, so you can see where they leak.`
                  : "No leads marked lost."}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Leads Pipeline</h2>
          </div>
          <span className="hud-label">new → contacted → replied → won</span>
        </header>
        <div className="space-y-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Lead name (person / school / business)"
              className="min-w-44 flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-violet/40 focus:outline-none"
            />
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="rounded-lg border border-edge bg-panel-2/60 px-2 py-1.5 text-xs text-slate-300 focus:outline-none"
            >
              {(customer ? CUSTOMER_SOURCES : FOUNDER_SOURCES).map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
            <input
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void add()}
              placeholder="Email / profile link"
              className="min-w-40 flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-violet/40 focus:outline-none"
            />
            <button
              onClick={() => void add()}
              disabled={busy || !name.trim()}
              className="flex items-center gap-1.5 rounded-lg border border-hud-violet/40 bg-hud-violet/10 px-3 py-1.5 text-xs text-hud-violet hover:bg-hud-violet/20 disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> Add lead
            </button>
          </div>

          {(state?.items ?? []).length === 0 ? (
            <div className="py-5 text-center text-[11px] text-slate-600">
              No leads yet — add the schools, businesses, and people you contact, and track them to WON.
            </div>
          ) : (
            <div className="scroll-thin max-h-[420px] space-y-1.5 overflow-y-auto pr-1">
              {state!.items.map((l) => (
                <div key={l.id} className="flex items-center gap-3 rounded-lg border border-edge/60 bg-panel-2/40 px-3 py-2">
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] uppercase ${STATUS_COLOR[l.status] ?? "text-slate-400 border-edge"}`}>
                    {l.status}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-slate-200">{l.name}</div>
                    <div className="truncate text-[10px] text-slate-500">
                      {l.source}{l.contact ? ` · ${l.contact}` : ""}
                    </div>
                  </div>
                  {NEXT_STATUS[l.status] && (
                    <button
                      onClick={() => void advance(l.id, l.status)}
                      className="flex items-center gap-0.5 rounded border border-edge px-2 py-1 text-[10px] text-slate-300 hover:border-hud-emerald/40 hover:text-hud-emerald"
                    >
                      {NEXT_STATUS[l.status]} <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {l.status !== "lost" && l.status !== "won" && (
                    <button onClick={() => void markLost(l.id)} className="text-[10px] text-slate-600 hover:text-slate-400">
                      lost
                    </button>
                  )}
                  <button onClick={() => void remove(l.id)} className="text-slate-600 hover:text-hud-rose" aria-label="Delete lead">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
