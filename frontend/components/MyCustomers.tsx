"use client";

/**
 * MyCustomers — the Customers tab in a subscriber's cockpit.
 *
 * The founder's Customers tab lists Titan's own subscribers, which a
 * subscriber must never see. Theirs is the other end of their CRM: every
 * lead they have marked won. It reads the same /api/me/leads the CRM tab
 * does, so the two can never disagree.
 *
 * A failed request is shown as a failure, not as "no customers yet" - an
 * owner who reads an empty list after a network error assumes the worst.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Trophy, Users } from "lucide-react";
import { apiBase, authHeaders } from "@/lib/api";
import type { LeadsState } from "@/lib/types";

export function MyCustomers({ onOpenCrm }: { onOpenCrm: () => void }) {
  const [state, setState] = useState<LeadsState | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await fetch(`${apiBase()}/leads`, {
        headers: authHeaders(),
        cache: "no-store",
      });
      if (!r.ok) throw new Error(String(r.status));
      setState((await r.json()) as LeadsState);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const won = (state?.items ?? [])
    .filter((l) => l.status === "won")
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  const open = (state?.items ?? []).filter((l) =>
    ["new", "contacted", "replied"].includes(l.status),
  ).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-widest text-white">
            <Users className="h-4 w-4 text-hud-emerald" /> CUSTOMERS
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Everyone you have won from your CRM pipeline.
          </div>
        </div>
        <button
          onClick={() => void load()}
          className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-amber/50 hover:text-hud-amber"
        >
          <RefreshCw className={`h-3 w-3 ${busy ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {failed && (
        <div className="rounded-xl border border-hud-rose/30 bg-hud-rose/5 px-4 py-3 text-[11px] text-hud-rose">
          Couldn&apos;t load your customers just now. Nothing was changed; try
          Refresh in a moment.
        </div>
      )}

      {state && (
        <div className="grid grid-cols-3 gap-3">
          {(
            [
              ["Customers", won.length, "text-hud-emerald"],
              ["Still in the pipeline", open, "text-hud-cyan"],
              ["Win rate", `${state.conversion_pct}%`, "text-hud-violet"],
            ] as [string, string | number, string][]
          ).map(([label, value, tone]) => (
            <div key={label} className="panel px-4 py-3">
              <div className="hud-label">{label}</div>
              <div className={`mt-2 font-mono text-2xl font-semibold ${tone}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {state && (
        <section className="panel">
          <header className="panel-header">
            <div className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
              <h2 className="text-sm font-medium text-slate-200">Won</h2>
            </div>
          </header>
          {won.length === 0 ? (
            <div className="space-y-3 p-5 text-center text-[11px] text-slate-500">
              <p>
                No customers yet. When a lead in your CRM says yes, mark it
                won and it appears here.
              </p>
              <button
                onClick={onOpenCrm}
                className="rounded-lg border border-hud-cyan/50 bg-hud-cyan/10 px-4 py-1.5 text-xs text-hud-cyan hover:bg-hud-cyan/20"
              >
                Open your CRM
              </button>
            </div>
          ) : (
            <div className="space-y-1.5 p-3">
              {won.map((c) => (
                <div
                  key={c.id}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-edge/60 bg-panel-2/40 px-3 py-2"
                >
                  <span className="min-w-0 flex-1 truncate text-[12px] text-slate-200">{c.name}</span>
                  {c.contact && (
                    <span className="truncate text-[11px] text-slate-400">{c.contact}</span>
                  )}
                  <span className="rounded border border-edge px-1.5 py-0.5 text-[9px] uppercase text-slate-500">
                    {c.source || "manual"}
                  </span>
                  <span className="text-[10px] text-slate-600">
                    updated {new Date(c.updated_at).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
