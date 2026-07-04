"use client";

import { useState } from "react";
import { Copy, Factory, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { RepurposePack } from "@/lib/types";

const LABELS: [keyof RepurposePack, string][] = [
  ["blog", "Blog post"],
  ["linkedin", "LinkedIn"],
  ["xthread", "X thread"],
  ["instagram", "Instagram"],
  ["email", "Email"],
  ["shorts", "Shorts script"],
];

// Content Repurposing Factory: one idea → six ready-to-publish pieces.
// Every pack is also saved to Deliverables automatically.
export function ContentFactory() {
  const [idea, setIdea] = useState("");
  const [pack, setPack] = useState<RepurposePack | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string>("blog");

  const run = async () => {
    if (!idea.trim() || busy) return;
    setBusy(true);
    try {
      const res = await api.repurpose(idea);
      if (res) setPack(res);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Factory className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Content Factory</h2>
        </div>
        <span className="hud-label">1 idea → 6 pieces · saved to Deliverables</span>
      </header>
      <div className="space-y-3 p-3">
        <div className="flex items-center gap-2">
          <input
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void run()}
            placeholder="One idea (e.g. '5 AI resume mistakes students make')"
            className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-cyan/40 focus:outline-none"
          />
          <button
            onClick={() => void run()}
            disabled={busy || !idea.trim()}
            className="flex items-center gap-1.5 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-3 py-1.5 text-xs text-hud-cyan hover:bg-hud-cyan/20 disabled:opacity-50"
          >
            <Sparkles className={`h-3.5 w-3.5 ${busy ? "animate-pulseGlow" : ""}`} />
            {busy ? "Producing…" : "Repurpose"}
          </button>
        </div>

        {pack && (
          <>
            <div className="flex flex-wrap gap-1.5">
              {LABELS.map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setOpen(key)}
                  className={`rounded px-2 py-1 text-[10px] ${
                    open === key
                      ? "bg-hud-cyan/15 text-hud-cyan"
                      : "border border-edge text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="rounded-lg border border-edge/60 bg-panel-2/40 p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-hud-cyan">
                  {LABELS.find(([k]) => k === open)?.[1]}
                </span>
                <button
                  onClick={() => void navigator.clipboard.writeText(pack[open as keyof RepurposePack] ?? "")}
                  className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-hud-cyan"
                >
                  <Copy className="h-3 w-3" /> Copy
                </button>
              </div>
              <p className="scroll-thin max-h-64 overflow-y-auto whitespace-pre-line text-[11px] leading-relaxed text-slate-300">
                {pack[open as keyof RepurposePack]}
              </p>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
