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
import { api } from "@/lib/api";
import type {
  AgentView,
  Connector,
  Deliverable,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  IntelligenceStatus,
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
  const [online, setOnline] = useState(false);

  const refresh = useCallback(async () => {
    let isOnline = false;
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      isOnline = res.ok;
    } catch {
      isOnline = false;
    }
    setOnline(isOnline);

    const [s, d, a, o, f, dv, cn, ps, ig] = await Promise.all([
      api.status(),
      api.divisions(),
      api.agents(),
      api.opportunities(),
      api.feed(40),
      api.deliverables(),
      api.connectors(),
      api.posts(),
      api.intelligence(),
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
  }, []);

  const executeOpportunity = useCallback(
    async (id: string) => {
      await api.executeOpportunity(id);
      await refresh();
    },
    [refresh],
  );

  const schedulePost = useCallback(
    async (content: string, channels: string[]) => {
      await api.schedulePost(content, channels);
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

  const mrr = status?.mrr ?? 0;
  const mrrLabel = mrr === 0 ? "$0 — First order incoming" : money(mrr);
  const mrrSub = mrr === 0 ? "Update via Make.com webhook" : "MRR · agents forecasting";

  return (
    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      <StatusBar status={status} online={online} intel={intel} />

      {mrr === 0 && (
        <div className="mt-3 rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-4 py-3 text-xs text-hud-amber">
          <span className="font-semibold">Abdullah Boss — empire is live.</span>{" "}
          All metrics start at $0 (real data only). Push real numbers via Make.com → your dashboard shows truth.{" "}
          <span className="text-slate-400">Agents are already working on your first revenue opportunity.</span>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard
          label="Monthly Revenue"
          value={mrrLabel}
          sub={mrrSub}
          icon={Banknote}
          accent="emerald"
        />
        <MetricCard
          label="Traffic"
          value={status ? (status.traffic === 0 ? "0 — Connect analytics" : compact(status.traffic)) : "—"}
          sub="visitors / mo"
          icon={Globe2}
          accent="cyan"
        />
        <MetricCard
          label="Pipeline"
          value={status ? money(status.pipeline_value) : "—"}
          sub="open value"
          icon={Target}
          accent="violet"
        />
        <MetricCard
          label="Digital Employees"
          value={status ? `${status.active_agents}/${status.total_agents}` : "—"}
          sub="active now"
          icon={Bot}
          accent="blue"
        />
        <MetricCard
          label="Actions In Flight"
          value={status ? `${status.actions_in_flight}` : "—"}
          sub={`${status?.open_opportunities ?? 0} open opportunities`}
          icon={Zap}
          accent="amber"
        />
      </div>

      <div className="mt-4">
        <CommandBar onDispatched={refresh} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
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
        <UrduVoiceAssistant status={status} />
      </div>

      {/* Ask Titan — conversational assistant (voice/text, Urdu/English) */}
      <div className="mt-4">
        <AskTitan />
      </div>

      <div className="mt-4">
        <ConnectedAssets connectors={connectors} />
      </div>

      <div className="mt-4">
        <Publishing posts={posts} onSchedule={schedulePost} onPublish={publishPost} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
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
            <OpportunityRadar
              opportunities={opportunities}
              onExecute={executeOpportunity}
            />
          </div>
          <div className="h-[420px]">
            <Deliverables items={deliverables} />
          </div>
        </div>
      </div>

      <footer className="mt-6 flex items-center justify-between border-t border-edge/60 pt-4 text-[11px] text-slate-600">
        <span>Project Titan Omega · Executive Intelligence Core v0.2 · Abdullah&apos;s Empire</span>
        <span className="font-mono">
          {status
            ? `updated ${new Date(status.updated_at).toLocaleTimeString()}`
            : "connecting…"}
        </span>
      </footer>
    </main>
  );
}
