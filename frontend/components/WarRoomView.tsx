"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ExternalLink,
  GitPullRequest,
  RefreshCw,
  Search,
  Sparkles,
  Swords,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Debate, GrowthIntel, PrResult, SeoReport } from "@/lib/types";
import { NeuralString } from "./NeuralString";
import { ContentFactory } from "./ContentFactory";

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

  const [prInstruction, setPrInstruction] = useState(
    "Improve the README so students instantly understand Career Mind and want to try it — clearer, more compelling, and SEO-friendly.",
  );
  const [pr, setPr] = useState<PrResult | null>(null);
  const [prBusy, setPrBusy] = useState(false);

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

  const runPr = async () => {
    if (prBusy) return;
    setPrBusy(true);
    setPr(null);
    try {
      setPr(await api.openPr(prInstruction));
    } finally {
      setPrBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Unique 3D Neural String signature */}
      {/* 360px is 43% of an 844px phone for a decorative lattice. Halved on
          mobile so the panels below it are reachable without scrolling past a
          background animation. Desktop unchanged. */}
      <section className="panel relative h-[200px] overflow-hidden sm:h-[360px]">
        <div className="pointer-events-none absolute left-3 top-3 z-10 hud-label">
          Titan Neural Lattice · live
        </div>
        <div className="absolute inset-0">
          <NeuralString intensity={intensity} count={agentCount || 14} />
        </div>
        {/* These are two long strings in a `justify-between` row. On a 390px
            phone they met in the middle and overlapped into unreadable mush —
            `justify-between` distributes space it does not have, and nothing
            here allowed a wrap. Stacked on mobile, side by side from `sm`. */}
        <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10 flex flex-col items-start gap-0.5 font-mono text-[10px] leading-tight text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:gap-2">
          <span className="min-w-0 truncate sm:whitespace-nowrap">
            app core ↔ {agentCount || 102} agents · strings pulse with live activity
          </span>
          <span className="min-w-0 truncate sm:whitespace-nowrap">
            {intel?.live ? "live web: ON" : "live web: add TAVILY_API_KEY"}
          </span>
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

      <ContentFactory />

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
                {(debate.critiques ?? []).map((c, i) => (
                  <div key={i} className="rounded-lg border border-hud-amber/25 bg-hud-amber/5 p-2.5">
                    <div className="text-[11px] font-semibold text-hud-amber">{c.name}</div>
                    <div className="mt-0.5 text-xs text-slate-300">{c.note}</div>
                  </div>
                ))}
                <div className="rounded-lg border border-hud-emerald/30 bg-hud-emerald/5 p-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-hud-emerald">Head decision</span>
                    {typeof debate.confidence === "number" && (
                      <span className="rounded bg-hud-emerald/15 px-1.5 py-0.5 font-mono text-[10px] text-hud-emerald">
                        confidence {debate.confidence}%
                      </span>
                    )}
                  </div>
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

      {/* Auto-PR to Career Mind */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <GitPullRequest className="h-4 w-4 text-hud-blue" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Auto-PR to Career Mind</h2>
          </div>
          <span className="hud-label">real pull request</span>
        </header>
        <div className="space-y-3 p-3">
          <p className="text-[11px] text-slate-500">
            An agent drafts the change and opens a real pull request on
            AbdullahRathoreVA/career-mind — you review and merge. Safe: it edits one
            file and never auto-merges. (Needs GITHUB_TOKEN with repo write scope.)
          </p>
          <textarea
            value={prInstruction}
            onChange={(e) => setPrInstruction(e.target.value)}
            rows={2}
            className="scroll-thin w-full resize-none rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-blue/40 focus:outline-none"
            placeholder="What should the agent improve? (defaults to the README)"
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={runPr}
              disabled={prBusy}
              className="flex items-center gap-1.5 rounded-lg border border-hud-blue/40 bg-hud-blue/10 px-3 py-1.5 text-xs text-hud-blue hover:bg-hud-blue/20 disabled:opacity-50"
            >
              <GitPullRequest className="h-3.5 w-3.5" />
              {prBusy ? "Drafting & opening PR…" : "Draft & open PR"}
            </button>
            {pr?.ok && pr.pr_url && (
              <a href={pr.pr_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-hud-emerald hover:underline">
                View PR <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
          {pr?.ok && (
            <div className="text-xs text-hud-emerald">
              ✅ Pull request opened on {pr.repo} → {pr.path}. Review and merge it on GitHub.
            </div>
          )}
          {pr && !pr.ok && (
            <div className="text-xs text-hud-rose">⚠️ {pr.error}</div>
          )}
        </div>
      </section>
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
