"use client";

import { useCallback, useEffect, useState } from "react";
import { Gauge, Plus, Trash2, TrendingUp, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import type { FinanceState, Performance } from "@/lib/types";
import { money } from "@/lib/format";

// Financial Center: real revenue (from the ledger) vs real expenses; profit and
// an honest run-rate forecast (last 30 days projected forward — no fake curves).
export function FinanceCenter() {
  const [state, setState] = useState<FinanceState | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("tools");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [f, p] = await Promise.all([api.finance(), api.performance()]);
    setState(f);
    setPerf(p);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addExpense = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0 || busy) return;
    setBusy(true);
    try {
      await api.logExpense(amt, category, note);
      setAmount("");
      setNote("");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await api.deleteExpense(id);
    await refresh();
  };

  const profit = state?.profit ?? 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Revenue (all time)", value: money(state?.revenue_total ?? 0), color: "text-hud-emerald" },
          { label: "Expenses (all time)", value: money(state?.expenses_total ?? 0), color: "text-hud-rose" },
          { label: "Profit", value: money(profit), color: profit >= 0 ? "text-hud-emerald" : "text-hud-rose" },
          { label: "Forecast / month", value: money(state?.forecast_monthly_profit ?? 0), color: "text-hud-cyan" },
        ].map(({ label, value, color }) => (
          <div key={label} className="panel px-4 py-3">
            <div className="hud-label">{label}</div>
            <div className={`mt-2 font-mono text-2xl font-semibold ${color}`}>{value}</div>
          </div>
        ))}
      </div>

      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Wallet className="h-4 w-4 text-hud-amber" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Expense Ledger</h2>
          </div>
          <span className="hud-label">
            30d: +{money(state?.revenue_30d ?? 0)} / -{money(state?.expenses_30d ?? 0)}
          </span>
        </header>
        <div className="space-y-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Amount ($)"
              inputMode="decimal"
              className="w-28 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-amber/40 focus:outline-none"
            />
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="rounded-lg border border-edge bg-panel-2/60 px-2 py-1.5 text-xs text-slate-300 focus:outline-none"
            >
              <option value="tools">Tools</option>
              <option value="ads">Ads</option>
              <option value="fees">Fees</option>
              <option value="other">Other</option>
            </select>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void addExpense()}
              placeholder="Note (e.g. domain renewal)"
              className="min-w-40 flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-amber/40 focus:outline-none"
            />
            <button
              onClick={() => void addExpense()}
              disabled={busy || !parseFloat(amount)}
              className="flex items-center gap-1.5 rounded-lg border border-hud-amber/40 bg-hud-amber/10 px-3 py-1.5 text-xs text-hud-amber hover:bg-hud-amber/20 disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> Log expense
            </button>
          </div>

          {(state?.expenses ?? []).length === 0 ? (
            <div className="py-5 text-center text-[11px] text-slate-600">
              No expenses logged — with $0 spend, everything you earn is pure profit. Keep it that way.
            </div>
          ) : (
            <div className="scroll-thin max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {state!.expenses.map((e) => (
                <div key={e.id} className="flex items-center gap-3 rounded-lg border border-edge/60 bg-panel-2/40 px-3 py-2">
                  <span className="font-mono text-xs text-hud-rose">-{money(e.amount)}</span>
                  <span className="rounded border border-edge px-1.5 py-0.5 text-[9px] uppercase text-slate-500">{e.category}</span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-slate-400">{e.note || "—"}</span>
                  <span className="text-[10px] text-slate-600">{new Date(e.created_at).toLocaleDateString()}</span>
                  <button onClick={() => void remove(e.id)} className="text-slate-600 hover:text-hud-rose" aria-label="Delete expense">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-start gap-2 rounded-lg border border-hud-cyan/20 bg-hud-cyan/5 px-3 py-2 text-[11px] text-slate-400">
            <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-hud-cyan" />
            <span>
              Forecast is an honest run-rate: your last 30 days of real revenue ({money(state?.revenue_30d ?? 0)})
              minus expenses ({money(state?.expenses_30d ?? 0)}) projected one month forward. It grows when your
              real numbers grow — no invented curves.
            </span>
          </div>
        </div>
      </section>

      {perf && (
        <section className="panel">
          <header className="panel-header">
            <div className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
              <h2 className="text-sm font-medium text-slate-200">Automation Performance</h2>
            </div>
            <span className="hud-label">
              ≈ {(perf.time_saved_minutes_estimate / 60).toFixed(1)}h saved (estimated)
            </span>
          </header>
          <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
            {(
              [
                ["Posts scheduled", perf.posts_scheduled],
                ["Posts published", perf.posts_published],
                ["Deliverables", perf.deliverables],
                ["Jobs found", perf.jobs_found],
                ["Jobs applied", perf.jobs_applied],
                ["Leads tracked", perf.leads_total],
                ["Leads won", perf.leads_won],
                ["Council decisions", perf.council_decisions],
              ] as [string, number][]
            ).map(([label, value]) => (
              <div key={label} className="rounded-lg border border-edge/60 bg-panel-2/40 px-3 py-2 text-center">
                <div className="font-mono text-lg font-semibold text-hud-violet">{value}</div>
                <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
              </div>
            ))}
          </div>
          <div className="px-3 pb-3 text-[10px] text-slate-600">
            Time-saved is an estimate (~30min per deliverable, 15min per post, 20min per application,
            2min per Telegram command) — real output counts, honest math.
          </div>
        </section>
      )}
    </div>
  );
}
