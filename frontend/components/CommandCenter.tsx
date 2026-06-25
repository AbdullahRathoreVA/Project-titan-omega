"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Banknote,
  Bot,
  Globe2,
  Target,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentView,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  Opportunity,
} from "@/lib/types";
import { compact, money } from "@/lib/format";
import { StatusBar } from "./StatusBar";
import { MetricCard } from "./MetricCard";
import { CommandBar } from "./CommandBar";
import { DivisionGrid } from "./DivisionGrid";
import { OpportunityRadar } from "./OpportunityRadar";
import { ExecutionFeed } from "./ExecutionFeed";
import { AgentActivity } from "./AgentActivity";

const POLL_MS = 5000;

export function CommandCenter() {
  const [status, setStatus] = useState<EmpireStatus | null>(null);
  const [divisions, setDivisions] = useState<DivisionView[]>([]);
  const [agents, setAgents] = useState<AgentView[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [online, setOnline] = useState(false);

  const refresh = useCallback(async () => {
    // Probe the core directly so we can show an honest online/offline badge.
    let isOnline = false;
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      isOnline = res.ok;
    } catch {
      isOnline = false;
    }
    setOnline(isOnline);

    const [s, d, a, o, f] = await Promise.all([
      api.status(),
      api.divisions(),
      api.agents(),
      api.opportunities(),
      api.feed(40),
    ]);
    setStatus(s);
    setDivisions(d);
    setAgents(a);
    setOpportunities(o);
    setFeed(f);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      <StatusBar status={status} online={online} />

      {/* headline metrics */}
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard
          label="Monthly Revenue"
          value={status ? money(status.mrr) : "—"}
          sub="MRR · forecast +18%"
          icon={Banknote}
          accent="emerald"
        />
        <MetricCard
          label="Traffic"
          value={status ? compact(status.traffic) : "—"}
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

      {/* main grid */}
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
        <div className="xl:col-span-4">
          <div className="h-full min-h-[560px]">
            <OpportunityRadar opportunities={opportunities} />
          </div>
        </div>
      </div>

      <footer className="mt-6 flex items-center justify-between border-t border-edge/60 pt-4 text-[11px] text-slate-600">
        <span>Project Titan Omega · Executive Intelligence Core v0.1</span>
        <span className="font-mono">
          {status
            ? `updated ${new Date(status.updated_at).toLocaleTimeString()}`
            : "connecting…"}
        </span>
      </footer>
    </main>
  );
}
