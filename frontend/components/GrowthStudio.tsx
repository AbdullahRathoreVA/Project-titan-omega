"use client";

import { useCallback, useState } from "react";
import { Rocket, Copy, Check, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { isCustomer } from "@/lib/session";

// School and job-seeker outreach sell the founder's Career Mind. A
// subscriber's studio offers only the kinds that fit any business.
const FOUNDER_ONLY = new Set(["school_outreach", "jobseeker_outreach"]);

const KINDS: { id: string; label: string }[] = [
  { id: "find_leads", label: "🎯 Find leads (live)" },
  { id: "latest_news", label: "📰 Latest news" },
  { id: "market_analysis", label: "📊 Market analysis" },
  { id: "school_outreach", label: "🎓 School / Uni email" },
  { id: "business_outreach", label: "💼 Business outreach" },
  { id: "jobseeker_outreach", label: "🤝 Reach job-seekers" },
  { id: "customer_reply", label: "💬 Customer care" },
  { id: "youtube_ideas", label: "▶️ YouTube ideas" },
];

export function GrowthStudio() {
  const [customer] = useState(() => isCustomer());
  const [kind, setKind] = useState("find_leads");
  const [topic, setTopic] = useState("");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const run = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setOut("");
    try {
      let res: { content: string } | null;
      if (kind === "find_leads") {
        res = await api.findLeads(topic);
      } else if (kind === "latest_news") {
        res = await api.intelNews(topic);
      } else {
        res = await api.intelGenerate(kind, topic);
      }
      setOut(res?.content ?? "No output — is the core online and an LLM key set?");
    } finally {
      setBusy(false);
    }
  }, [kind, topic, busy]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(out);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* no-op */
    }
  }, [out]);

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-hud-amber" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Growth Studio</h2>
        </div>
        <span className="hud-label">leads · live news · outreach</span>
      </header>

      <div className="space-y-3 p-3">
        <div className="flex flex-wrap gap-1.5">
          {KINDS.filter((k) => !(customer && FOUNDER_ONLY.has(k.id))).map((k) => (
            <button
              key={k.id}
              onClick={() => setKind(k.id)}
              className={`rounded-lg border px-2.5 py-1 text-[11px] ${
                kind === k.id
                  ? "border-hud-amber/50 bg-hud-amber/10 text-hud-amber"
                  : "border-edge bg-panel/80 text-slate-400 hover:text-slate-200"
              }`}
            >
              {k.label}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder={customer
              ? "Optional focus (e.g. 'offices near me that order catering')"
              : "Optional focus (e.g. 'universities in Pakistan' or 'businesses needing chatbots')"}
            className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600 focus:border-hud-amber/40 focus:outline-none"
          />
          <button
            onClick={run}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg border border-hud-amber/40 bg-hud-amber/10 px-4 py-2 text-xs font-medium text-hud-amber transition-colors hover:bg-hud-amber/20 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
            {busy ? "Working…" : "Generate"}
          </button>
        </div>

        {out && (
          <div className="relative rounded-lg border border-edge bg-panel-2/40 p-3">
            <button
              onClick={copy}
              title="Copy"
              className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-hud-emerald" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
            <pre className="scroll-thin max-h-72 overflow-y-auto whitespace-pre-wrap pr-6 text-[11px] leading-relaxed text-slate-300">
              {out}
            </pre>
          </div>
        )}
      </div>
    </section>
  );
}
