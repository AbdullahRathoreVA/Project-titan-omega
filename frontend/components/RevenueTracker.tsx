"use client";

import { useCallback, useState } from "react";
import { DollarSign, Plus, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";

type Source = "fiverr" | "career_mind" | "kindle" | "other";

const SOURCES: { id: Source; label: string }[] = [
  { id: "fiverr", label: "Fiverr" },
  { id: "career_mind", label: "Career Mind" },
  { id: "kindle", label: "Kindle" },
  { id: "other", label: "Other" },
];

export function RevenueTracker({ total, onLogged }: { total: number; onLogged: () => void }) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState<Source>("fiverr");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    const value = parseFloat(amount);
    if (!value || value <= 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.logRevenue(value, source, note);
      if (!res) {
        setError("Could not save — are you logged in? (Core may need auth.)");
        return;
      }
      setAmount("");
      setNote("");
      setOpen(false);
      onLogged();
    } finally {
      setBusy(false);
    }
  }, [amount, source, note, busy, onLogged]);

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <DollarSign className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Revenue Ledger</h2>
        </div>
        <span className="hud-label">real earnings only</span>
      </header>

      <div className="flex items-center justify-between p-4">
        <div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold text-hud-emerald">
              ${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
            <span className="text-[10px] text-slate-500">total earned</span>
          </div>
          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500">
            <TrendingUp className="h-3 w-3 text-hud-emerald" />
            {total === 0 ? "Log your first order — it's coming, Boss!" : "Every dollar counts toward the billion."}
          </p>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 rounded-lg border border-hud-emerald/40 bg-hud-emerald/10 px-3 py-2 text-xs font-medium text-hud-emerald transition-colors hover:bg-hud-emerald/20"
        >
          <Plus className="h-3.5 w-3.5" />
          Log order
        </button>
      </div>

      {open && (
        <div className="space-y-2.5 border-t border-edge/60 p-4">
          <div className="flex gap-2">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Amount ($)"
              className="w-28 rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600 focus:border-hud-emerald/40 focus:outline-none"
            />
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note (e.g. AI resume gig — first order)"
              className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600 focus:border-hud-emerald/40 focus:outline-none"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {SOURCES.map((s) => (
              <button
                key={s.id}
                onClick={() => setSource(s.id)}
                className={`rounded-lg border px-2.5 py-1 text-[11px] ${
                  source === s.id
                    ? "border-hud-emerald/50 bg-hud-emerald/10 text-hud-emerald"
                    : "border-edge bg-panel/80 text-slate-400 hover:text-slate-200"
                }`}
              >
                {s.label}
              </button>
            ))}
            <button
              onClick={submit}
              disabled={busy || !amount}
              className="ml-auto rounded-lg border border-hud-emerald/40 bg-hud-emerald/15 px-4 py-1 text-xs font-medium text-hud-emerald disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
          {error && <p className="text-[11px] text-hud-rose">{error}</p>}
        </div>
      )}
    </section>
  );
}
