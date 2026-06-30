"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Banknote,
  Bot,
  FileBarChart,
  Globe2,
  RefreshCw,
  Radar as RadarIcon,
  Target,
  Zap,
} from "lucide-react";
import { api, authHeaders } from "@/lib/api";
import { useTitanStream } from "@/lib/useTitanStream";
import type {
  AgentView,
  ChannelTile,
  Connector,
  Deliverable,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  IntelligenceStatus,
  NextPost as NextPostType,
  Opportunity,
  ScheduledPost,
} from "@/lib/types";
import { compact, money } from "@/lib/format";
import { StatusBar } from "./StatusBar";
import { MetricCard } from "./MetricCard";
import { CommandBar } from "./CommandBar";
import { DivisionGrid } from "./DivisionGrid";
import { OpportunityRadar } from "./OpportunityRadar";
import { ExecutionFeed } from "./ExecutionFeed";
import { AgentActivity } from "./AgentActivity";
import { Deliverables } from "./Deliverables";
import { ConnectedAssets } from "./ConnectedAssets";
import { Publishing } from "./Publishing";
import { UrduVoiceAssistant } from "./UrduVoiceAssistant";
import { AskTitan } from "./AskTitan";
import { RevenueTracker } from "./RevenueTracker";
import { GrowthStudio } from "./GrowthStudio";
import { Sidebar } from "./Sidebar";
import { TitanCore } from "./TitanCore";
import { NextPost } from "./NextPost";

const POLL_MS = 5000;

export function CommandCenter() {
  const [status, setStatus] = useState<EmpireStatus | null>(null);
  const [divisions, setDivisions] = useState<DivisionView[]>([]);
  const [agents, setAgents] = useState<AgentView[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [deliverables, setDeliverables] = useState<Deliverable[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [intel, setIntel] = useState<IntelligenceStatus | null>(null);
  const [channels, setChannels] = useState<ChannelTile[]>([]);
  const [nextPost, setNextPost] = useState<NextPostType | null>(null);
  const [online, setOnline] = useState(false);

  // Live SSE stream — makes the dashboard move the instant it opens.
  const { frame, live } = useTitanStream();

  const refresh = useCallback(async () => {
    let isOnline = false;
    try {
      const res = await fetch("/api/status", { cache: "no-store", headers: authHeaders() });
      isOnline = res.ok;
    } catch {
      isOnline = false;
    }
    setOnline(isOnline);

    const [s, d, a, o, f, dv, cn, ps, ig, ch, np] = await Promise.all([
      api.status(),
      api.divisions(),
      api.agents(),
      api.opportunities(),
      api.feed(40),
      api.deliverables(),
      api.connectors(),
      api.posts(),
      api.intelligence(),
      api.channels(),
      api.nextPost(),
    ]);
    setStatus(s);
    setDivisions(d);
    setAgents(a);
    setOpportunities(o);
    setFeed(f);
    setDeliverables(dv);
    setConnectors(cn);
    setPosts(ps);
    setIntel(ig);
    setChannels(ch.channels);
    setNextPost(np);
  }, []);

  const refreshNextPost = useCallback(async () => {
    const np = await api.nextPost();
    setNextPost(np);
  }, []);

  const executeOpportunity = useCallback(
    async (id: string) => {
      await api.executeOpportunity(id);
      await refresh();
    },
    [refresh],
  );

  const schedulePost = useCallback(
    async (content: string, channelList: string[]) => {
      await api.schedulePost(content, channelList);
      await refresh();
    },
    [refresh],
  );

  const publishPost = useCallback(
    async (id: string) => {
      await api.publishPost(id);
      await refresh();
    },
    [refresh],
  );

  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const runAction = useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      if (actionBusy) return;
      setActionBusy(key);
      try {
        await fn();
        await refresh();
      } finally {
        setActionBusy(null);
      }
    },
    [actionBusy, refresh],
  );

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Merge fresh stream events into the feed between polls (dedup by id).
  useEffect(() => {
    if (!frame?.events?.length) return;
    setFeed((prev) => {
      const seen = new Set(prev.map((e) => e.id));
      const fresh = frame.events.filter((e) => !seen.has(e.id));
      if (!fresh.length) return prev;
      return [...fresh.reverse(), ...prev].slice(0, 60);
    });
  }, [frame]);

  // Live numbers prefer the stream frame, falling back to the polled snapshot.
  const liveStatus: EmpireStatus | null =
    status && frame
      ? {
          ...status,
          health: frame.status.health,
          mrr: frame.status.mrr,
          traffic: frame.status.traffic,
          active_agents: frame.status.active_agents,
          total_agents: frame.status.total_agents,
          open_opportunities: frame.status.open_opportunities,
          actions_in_flight: frame.status.actions_in_flight,
          pipeline_value: frame.status.pipeline_value,
        }
      : status;

  const intensity = frame?.intensity ?? 0.35;
  const mrr = liveStatus?.mrr ?? 0;
  const mrrLabel = mrr === 0 ? "$0 — First order incoming" : money(mrr);
  const mrrSub = mrr === 0 ? "Log your first order below" : "total earned · real revenue";

  return (
    <main className="mx-auto max-w-[1600px] px-3 py-4 sm:px-5">
      <StatusBar status={liveStatus} online={online || live} intel={intel} />

      {mrr === 0 && (
        <div className="mt-3 rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-4 py-3 text-xs text-hud-amber">
          <span className="font-semibold">Abdullah Boss — empire is live.</span>{" "}
          All numbers are real and start at $0. Got an order? Hit{" "}
          <span className="font-semibold">Log order</span> in the Revenue Ledger — your dashboard shows the truth.
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
        {/* Left rail — channels + agents */}
        <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-1.5rem)]">
          <Sidebar channels={channels} agents={agents} />
        </div>

        {/* Main HUD column */}
        <div className="min-w-0 space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <MetricCard label="Total Revenue" value={mrrLabel} sub={mrrSub} icon={Banknote} accent="emerald" />
            <MetricCard
              label="Traffic"
              value={liveStatus ? (liveStatus.traffic === 0 ? "0 — Connect analytics" : compact(liveStatus.traffic)) : "—"}
              sub="visitors / mo"
              icon={Globe2}
              accent="cyan"
            />
            <MetricCard label="Pipeline" value={liveStatus ? money(liveStatus.pipeline_value) : "—"} sub="open value" icon={Target} accent="violet" />
            <MetricCard
              label="Digital Employees"
              value={liveStatus ? `${liveStatus.active_agents}/${liveStatus.total_agents}` : "—"}
              sub="active now"
              icon={Bot}
              accent="blue"
            />
            <MetricCard
              label="Actions In Flight"
              value={liveStatus ? `${liveStatus.actions_in_flight}` : "—"}
              sub={`${liveStatus?.open_opportunities ?? 0} open opportunities`}
              icon={Zap}
              accent="amber"
            />
          </div>

          {/* 3D core + Next post */}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
            <section className="panel relative h-[380px] overflow-hidden">
              <div className="pointer-events-none absolute left-3 top-3 z-10 hud-label">3D Titan Core</div>
              <div
                className={`absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] ${
                  live ? "border-hud-emerald/40 text-hud-emerald" : "border-hud-amber/40 text-hud-amber"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulseGlow bg-hud-emerald" : "bg-hud-amber"}`} />
                {live ? "LIVE" : "polling"}
              </div>
              <div className="absolute inset-0">
                <TitanCore intensity={intensity} />
              </div>
              <div className="pointer-events-none absolute bottom-3 left-3 z-10 font-mono text-[10px] text-slate-500">
                {liveStatus
                  ? `${liveStatus.active_agents}/${liveStatus.total_agents} agents working · health ${liveStatus.health.toFixed(0)}`
                  : "connecting…"}
              </div>
            </section>

            <div className="h-[380px]">
              <NextPost post={nextPost} onChange={refreshNextPost} />
            </div>
          </div>

          <CommandBar onDispatched={refresh} />

          <div className="flex flex-wrap gap-2">
            {[
              { key: "scan", label: "Scan opportunities", icon: RadarIcon, fn: () => api.scanOpportunities() },
              { key: "refresh", label: "Refresh assets", icon: RefreshCw, fn: () => api.refreshConnectors() },
              { key: "report", label: "Generate weekly report", icon: FileBarChart, fn: () => api.weeklyReport() },
            ].map(({ key, label, icon: Icon, fn }) => (
              <button
                key={key}
                onClick={() => runAction(key, fn)}
                disabled={actionBusy === key}
                className="flex items-center gap-1.5 rounded-lg border border-edge bg-panel/80 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan disabled:opacity-50"
              >
                <Icon className={`h-3.5 w-3.5 ${actionBusy === key ? "animate-spin" : ""}`} />
                {actionBusy === key ? "Working…" : label}
              </button>
            ))}
            <UrduVoiceAssistant status={liveStatus} />
          </div>

          {/* Revenue ledger + Ask Titan */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RevenueTracker total={mrr} onLogged={refresh} />
            <AskTitan />
          </div>

          <GrowthStudio />

          <ConnectedAssets connectors={connectors} />

          <Publishing posts={posts} onSchedule={schedulePost} onPublish={publishPost} />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="space-y-4 xl:col-span-8">
              <DivisionGrid divisions={divisions} />
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="h-[420px]">
                  <AgentActivity agents={agents} />
                </div>
                <div className="h-[420px]">
                  <ExecutionFeed events={feed} />
                </div>
              </div>
            </div>
            <div className="space-y-4 xl:col-span-4">
              <div className="h-[560px]">
                <OpportunityRadar opportunities={opportunities} onExecute={executeOpportunity} />
              </div>
              <div className="h-[420px]">
                <Deliverables items={deliverables} />
              </div>
            </div>
          </div>
        </div>
      </div>

      <footer className="mt-6 flex items-center justify-between border-t border-edge/60 pt-4 text-[11px] text-slate-600">
        <span>Project Titan Omega · Executive Intelligence Core v0.3 · Abdullah&apos;s Empire</span>
        <span className="font-mono">
          {liveStatus ? `updated ${new Date(liveStatus.updated_at).toLocaleTimeString()}` : "connecting…"}
        </span>
      </footer>
    </main>
  );
}
