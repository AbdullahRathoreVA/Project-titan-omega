"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ExternalLink,
  RefreshCw,
  Search,
  Sparkles,
  Swords,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Debate, GrowthIntel, SeoReport } from "@/lib/types";
import { NeuralString } from "./NeuralString";

// The War Room: Titan's autonomous growth brain. Live research engine (runs
// 24/7 server-side), a marketing team that argues then decides, and an SEO
// co-pilot — all wrapped around the unique 3D Neural String signature.
export function WarRoomView({
  intensity,
  agentCount,
}: {
  intensity: number;
  agentCount: number;
}) {
  const [intel, setIntel] = useState<GrowthIntel | null>(null);
  const [scanning, setScanning] = useState(false);

  const [topic, setTopic] = useState("");
  const [debate, setDebate] = useState<Debate | null>(null);
  const [debating, setDebating] = useState(false);

  const [keyword, setKeyword] = useState("");
  const [seo, setSeo] = useState<SeoReport | null>(null);
  const [seoBusy, setSeoBusy] = useState(false);

  const loadIntel = useCallback(async () => {
    setIntel(await api.growthIntel());
  }, []);

  useEffect(() => {
    void loadIntel();
    const id = setInterval(() => void loadIntel(), 15000);
    return () => clearInterval(id);
  }, [loadIntel]);

  const scan = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const res = await api.growthScan();
      if (res) setIntel(res);
    } finally {
      setScanning(false);
    }
  };

  const runDebate = async () => {
    if (debating) return;
    setDebating(true);
    try {
      setDebate(await api.warroomDebate(topic));
    } finally {
      setDebating(false);
    }
  };

  const runSeo = async () => {
    if (seoBusy) return;
    setSeoBusy(true);
    try {
      setSeo(await api.seoReport(keyword));
    } finally {
      setSeoBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Unique 3D Neural String signature */}
      <section className="panel relative h-[360px] overflow-hidden">
        <div className="pointer-events-none absolute left-3 top-3 z-10 hud-label">
          Titan Neural Lattice · live
        </div>
        <div className="absolute inset-0">
          <NeuralString intensity={intensity} count={agentCount || 14} />
        </div>
        <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10 flex items-center justify-between font-mono text-[10px] text-slate-500">
          <span>app core ↔ {agentCount || 102} agents · strings pulse with live activity</span>
          <span>{intel?.live ? "live web: ON" : "live web: add TAVILY_API_KEY"}</span>
        </div>
      </section>

      {/* Autonomous Growth Engine */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Autonomous Growth Engine</h2>
            <span className="hud-label">24/7 research</span>
          </div>
          <button
            onClick={scan}
            disabled={scanning}
            className="flex items-center gap-1.5 rounded-lg border border-edge bg-panel/80 px-2.5 py-1 text-xs text-slate-300 hover:border-hud-emerald/40 hover:text-hud-emerald disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
            {scanning ? "Researching…" : "Scan now"}
          </button>
        </header>
        <div className="grid gap-4 p-3 lg:grid-cols-2">
          <div>
            <div className="hud-label mb-1.5">This week&apos;s brief</div>
            <p className="scroll-thin max-h-48 overflow-y-auto whitespace-pre-line text-xs leading-relaxed text-slate-300">
              {intel?.summary || "Booting the research engine… (runs automatically every 15 min)"}
            </p>
            {intel?.keywords && intel.keywords.length > 0 && (
              <div className="mt-3">
                <div className="hud-label mb-1.5">Target keywords</div>
                <div className="flex flex-wrap gap-1.5">
                  {intel.keywords.map((k, i) => (
                    <span key={i} className="rounded border border-hud-cyan/20 bg-hud-cyan/5 px-2 py-0.5 text-[10px] text-hud-cyan">
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="space-y-3">
            <Linklist label="Earning opportunities" icon={TrendingUp} items={intel?.opportunities ?? []} accent="emerald" />
            <Linklist label="Competitor signals" icon={Search} items={intel?.competitors ?? []} accent="violet" />
          </div>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Marketing War Room */}
        <section className="panel">
          <header className="panel-header">
            <div className="flex items-center gap-2">
              <Swords className="h-4 w-4 text-hud-rose" strokeWidth={1.6} />
              <h2 className="text-sm font-medium text-slate-200">Marketing War Room</h2>
            </div>
            <span className="hud-label">debate → decide</span>
          </header>
          <div className="space-y-3 p-3">
            <div className="flex items-center gap-2">
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void runDebate()}
                placeholder="Goal (e.g. first 10 Fiverr orders, free)"
                className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-rose/40 focus:outline-none"
              />
              <button
                onClick={runDebate}
                disabled={debating}
                className="rounded-lg border border-hud-rose/40 bg-hud-rose/10 px-3 py-1.5 text-xs text-hud-rose hover:bg-hud-rose/20 disabled:opacity-50"
              >
                {debating ? "Arguing…" : "Run debate"}
              </button>
            </div>
            {debate && (
              <div className="space-y-2">
                {debate.proposals.map((p, i) => (
                  <div key={i} className="rounded-lg border border-edge/60 bg-panel-2/40 p-2.5">
                    <div className="text-[11px] font-semibold text-hud-cyan">{p.name}</div>
                    <div className="mt-0.5 text-xs text-slate-300">{p.proposal}</div>
                  </div>
                ))}
                <div className="rounded-lg border border-hud-emerald/30 bg-hud-emerald/5 p-2.5">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-hud-emerald">Head decision</div>
                  <div className="mt-1 whitespace-pre-line text-xs text-slate-200">{debate.decision}</div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* SEO Co-pilot */}
        <section className="panel">
          <header className="panel-header">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-hud-amber" strokeWidth={1.6} />
              <h2 className="text-sm font-medium text-slate-200">SEO Co-pilot</h2>
            </div>
            <span className="hud-label">rank · gaps · actions</span>
          </header>
          <div className="space-y-3 p-3">
            <div className="flex items-center gap-2">
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void runSeo()}
                placeholder="Keyword (e.g. AI resume help)"
                className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-amber/40 focus:outline-none"
              />
              <button
                onClick={runSeo}
                disabled={seoBusy}
                className="rounded-lg border border-hud-amber/40 bg-hud-amber/10 px-3 py-1.5 text-xs text-hud-amber hover:bg-hud-amber/20 disabled:opacity-50"
              >
                {seoBusy ? "Analyzing…" : "Analyze"}
              </button>
            </div>
            {seo && (
              <>
                <p className="scroll-thin max-h-48 overflow-y-auto whitespace-pre-line text-xs leading-relaxed text-slate-300">
                  {seo.report}
                </p>
                {seo.competitors.length > 0 && (
                  <Linklist label="Currently ranking" icon={ExternalLink} items={seo.competitors.map((c) => ({ ...c, snippet: "" }))} accent="cyan" />
                )}
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Linklist({
  label,
  icon: Icon,
  items,
  accent,
}: {
  label: string;
  icon: typeof TrendingUp;
  items: { title: string; url: string; snippet: string }[];
  accent: "emerald" | "violet" | "cyan";
}) {
  const color = { emerald: "text-hud-emerald", violet: "text-hud-violet", cyan: "text-hud-cyan" }[accent];
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon className={`h-3.5 w-3.5 ${color}`} />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      </div>
      {items.length === 0 ? (
        <div className="text-[10px] text-slate-600">No live results yet — add TAVILY_API_KEY for live web search.</div>
      ) : (
        <div className="scroll-thin max-h-40 space-y-1 overflow-y-auto pr-1">
          {items.slice(0, 6).map((it, i) => (
            <a
              key={i}
              href={it.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded border border-edge/60 bg-panel-2/40 px-2 py-1.5 transition-colors hover:border-hud-cyan/30"
            >
              <div className="truncate text-[11px] text-slate-200">{it.title}</div>
              {it.snippet && <div className="truncate text-[10px] text-slate-500">{it.snippet}</div>}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
