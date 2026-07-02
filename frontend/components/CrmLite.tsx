"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Plus, Trash2, Users } from "lucide-react";
import { api } from "@/lib/api";
import type { LeadsState } from "@/lib/types";

const STATUS_COLOR: Record<string, string> = {
  new: "text-hud-cyan border-hud-cyan/30",
  contacted: "text-hud-amber border-hud-amber/30",
  replied: "text-hud-violet border-hud-violet/30",
  won: "text-hud-emerald border-hud-emerald/30",
  lost: "text-slate-500 border-edge",
};

const NEXT_STATUS: Record<string, string> = {
  new: "contacted",
  contacted: "replied",
  replied: "won",
};

// CRM-lite: the leads pipeline — new → contacted → replied → won/lost.
export function CrmLite() {
  const [state, setState] = useState<LeadsState | null>(null);
  const [name, setName] = useState("");
  const [source, setSource] = useState("manual");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setState(await api.leads());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
              <option value="manual">Manual</option>
              <option value="fiverr">Fiverr</option>
              <option value="linkedin">LinkedIn</option>
              <option value="school">School/Uni</option>
              <option value="jobradar">Job Radar</option>
              <option value="instagram">Instagram</option>
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
