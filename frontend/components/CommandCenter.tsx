"use client";

import ClientCommand from "./ClientCommand";
import VoiceAgents from "./VoiceAgents";
import SeoCommand from "./SeoCommand";
import ExecutiveCommand from "./ExecutiveCommand";
import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
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
import { adminFetch, api, apiBase, authHeaders } from "@/lib/api";
import { useTitanStream } from "@/lib/useTitanStream";
import { displayName, isCustomer } from "@/lib/session";
import type {
  AgentView,
  ChannelTile,
  Connector,
  DecisionEntry,
  Deliverable,
  DivisionView,
  EmpireStatus,
  ExecutionItem,
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
import { WarRoomView } from "./WarRoomView";
import { TelegramCenter } from "./TelegramCenter";
import { JobRadar } from "./JobRadar";
import { FinanceCenter } from "./FinanceCenter";
import { CrmLite } from "./CrmLite";
import ApiCommand from "./ApiCommand";
import Customers from "./Customers";
import { MyCustomers } from "./MyCustomers";
import { AICity } from "./AICity";
import { BootSequence } from "./BootSequence";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { MissionControl } from "./MissionControl";
import { ProgressStrip } from "./ProgressStrip";
import { ThinkingTrace } from "./ThinkingTrace";
import { Universe } from "./Universe";
import { chime, speak, speakPremium, tap, unlockAudio } from "@/lib/sound";
import { isGuest } from "@/lib/guest";

// Global 3D backdrop — behind the whole app, never blocks clicks.
const Background3D = dynamic(() => import("./Background3D"), { ssr: false });

const POLL_MS = 5000;

// Tabs a subscriber's cockpit shows: those whose routes are open to customers
// on the backend (core/cockpit_scope.ALLOWED). Each later phase adds its tab
// here together with its routes there.
const CUSTOMER_TABS = new Set<string>([
  "universe", "dashboard", "mission", "clients", "seo", "crm", "voice",
  "finance", "customers", "executive", "graph", "city", "warroom", "apis",
  "telegram", "jobs",
]);

export function CommandCenter() {
  // Fixed for the life of the page: signing out reloads into the sign-in screen.
  const [customer] = useState(() => isCustomer());
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
  const [view, setView] = useState<
    "universe" | "dashboard" | "mission" | "graph" | "city" | "warroom" | "telegram" | "jobs" | "finance" | "crm" | "clients" | "customers" | "seo" | "executive" | "voice" | "apis"
  >("universe");
  const [executions, setExecutions] = useState<ExecutionItem[]>([]);
  const [decisions, setDecisions] = useState<DecisionEntry[]>([]);
  // A subscriber's next post is about their business, so until they have one
  // the card asks them to add it instead. Read once, and again after a refresh.
  const [hasBusiness, setHasBusiness] = useState(false);
  const hasBusinessRef = useRef(false);
  // Increments whenever real feed activity arrives → fires comets in the Universe.
  const [pulse, setPulse] = useState(0);

  // Cinematic boot: plays on EVERY open/reload (founder's preference) — the
  // dashboard loads underneath it, and SKIP is always available. When the boot
  // lifts, Titan speaks a live status briefing (real numbers, not a script).
  const [boot, setBoot] = useState<"boot" | "done">("boot");
  const statusRef = useRef<EmpireStatus | null>(null);
  const finishBoot = useCallback(() => {
    setBoot("done");
    chime();
    const guest =
      typeof window !== "undefined" &&
      (window as unknown as { __TITAN_GUEST?: boolean }).__TITAN_GUEST === true;
    const closer = guest
      ? "Explore the command center."
      : isCustomer()
        ? `Let's build, ${displayName()}.`
        : "Let's build, Abdullah.";
    const s = statusRef.current;
    const line = s
      ? `${s.active_agents} of ${s.total_agents} agents are working. ` +
        `${s.open_opportunities} opportunities on the radar. ` +
        (Math.round(s.mrr) > 0 ? `Revenue at ${Math.round(s.mrr)} dollars. ` : `First revenue incoming. `) +
        closer
      : guest
        ? `Titan Omega ready. ${closer}`
        : `Dashboard ready. ${closer}`;
    // Premium ElevenLabs voice for the founder (if a key is set), else the free
    // browser voice — audio is already unlocked by the boot tap. Subscribers
    // get the browser voice: /api/tts is the founder's key.
    if (isCustomer()) speak(line);
    else void speakPremium(line, () => speak(line));
  }, []);

  // Belt-and-suspenders: unlock audio on the first interaction anywhere, so the
  // voice assistant works even if the boot was skipped without a tap.
  useEffect(() => {
    const unlock = () => unlockAudio();
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  // Live SSE stream — makes the dashboard move the instant it opens. It
  // streams the founder's Store, so a subscriber's cockpit polls instead.
  const { frame, live } = useTitanStream(!customer);

  const refresh = useCallback(async () => {
    let isOnline = false;
    try {
      const res = await fetch(`${apiBase()}/status`, { cache: "no-store", headers: authHeaders() });
      isOnline = res.ok;
    } catch {
      isOnline = false;
    }
    setOnline(isOnline);

    // Three feeds are the founder's alone: his connected assets, his AI
    // provider and his social profile links. A subscriber's cockpit does not
    // ask for them at all. Their next post is asked for only once they have a
    // business to promote - drafting one spends their AI calls.
    if (customer) {
      try {
        const r = await adminFetch("/admin/clients");
        const d = r.ok ? ((await r.json()) as { total?: number }) : null;
        hasBusinessRef.current = (d?.total ?? 0) > 0;
        setHasBusiness(hasBusinessRef.current);
      } catch {
        // Keep what we knew; the next poll tries again.
      }
    }
    const none = <T,>(v: T) => Promise.resolve(v);
    const [s, d, a, o, f, dv, cn, ps, ig, ch, np, ex, dc] = await Promise.all([
      api.status(),
      api.divisions(),
      api.agents(),
      api.opportunities(),
      api.feed(40),
      api.deliverables(),
      customer ? none<Connector[]>([]) : api.connectors(),
      api.posts(),
      customer ? none<IntelligenceStatus | null>(null) : api.intelligence(),
      customer ? none({ channels: [] as ChannelTile[] }) : api.channels(),
      customer && !hasBusinessRef.current ? none<NextPostType | null>(null) : api.nextPost(),
      api.executions(),
      api.decisions(),
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
    setExecutions(ex);
    setDecisions(dc);
  }, [customer]);

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
      setPulse((p) => p + 1); // real activity → light packets fire in the Universe
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

  // Keep the freshest status available for the post-boot voice briefing.
  useEffect(() => {
    statusRef.current = liveStatus;
  });

  const intensity = frame?.intensity ?? 0.35;
  const mrr = liveStatus?.mrr ?? 0;
  const mrrLabel = mrr === 0 ? "$0 — First order incoming" : money(mrr);
  const mrrSub = customer
    ? "revenue recorded in your workspace"
    : mrr === 0 ? "Log your first order below" : "total earned · real revenue";

  return (
    <main className="mx-auto max-w-[1600px] px-3 py-4 sm:px-5">
      {boot === "boot" && (
        <div className="fixed inset-0 z-[900] bg-[#020409]">
          <BootSequence onDone={finishBoot} />
        </div>
      )}
      {/* During boot, hide the ENTIRE dashboard (display:none) so no WebGL
          canvas — the backdrop OR the Universe — can bleed through the intro
          overlay. `contents` restores the exact layout once boot completes. */}
      <div className={boot === "done" ? "contents" : "hidden"}>
      {boot === "done" && <Background3D />}
      <StatusBar status={liveStatus} online={online || live} intel={intel} />
      <ProgressStrip />

      <div className="mt-4 grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
        {/* Main HUD column — FIRST in the document.
            It used to be second, after the channels + agents rail. On a
            desktop the grid turned that rail into a left column, but on a
            phone the grid collapses and document order IS reading order, so
            the first thing a phone showed was a 722px roster of channels and
            agent names. Measured at 375x812: "Total Revenue" started at
            y=1064 — a full screen below the fold — and the tab strip at
            y=1489.

            The rail is now second in the document and pinned back to column 1
            on `lg`. That is deliberate: explicit grid placement moves it
            visually without moving it in reading order, so keyboard tabbing
            and screen readers reach the numbers first on every screen size,
            not only on phones. `order:` would have moved the pixels and left
            the reading order wrong. */}
        <div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            {/* Revenue is the number the business exists for, so on a phone it
                gets the full width instead of sharing a row with Traffic.
                Desktop keeps all five equal. */}
            <MetricCard
              label="Total Revenue"
              value={mrrLabel}
              sub={mrrSub}
              icon={Banknote}
              accent="emerald"
              className="col-span-2 lg:col-span-1"
            />
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

          {/* Explains the $0 above rather than pre-empting it. It used to sit
              between the header and the grid, which cost ~120px before the
              first number on a phone — the reader gets the figure, then the
              reason it is what it is. */}
          {mrr === 0 && !isGuest() && !customer && (
            <div className="rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-4 py-3 text-xs text-hud-amber">
              <span className="font-semibold">Abdullah — your empire is live.</span>{" "}
              All numbers are real and start at $0. Got an order? Hit{" "}
              <span className="font-semibold">Log order</span> in the Revenue Ledger — your dashboard shows the truth.
            </div>
          )}
          {customer && (
            <div className="rounded-lg border border-hud-cyan/30 bg-hud-cyan/5 px-4 py-3 text-xs text-hud-cyan">
              <span className="font-semibold">{displayName()} — your Titan workspace is live.</span>{" "}
              Every number here is yours and starts at zero. Add your first business to
              get its audit, fixes and monitoring:{" "}
              <button
                onClick={() => setView("clients")}
                className="font-semibold underline underline-offset-2"
              >
                set up a business
              </button>
              .
            </div>
          )}

          {/* View switcher.
              Only EXECUTIVE is founder-only. It is Abdullah's private
              business intelligence — real revenue, real provider errors, what
              the platform learned about itself — and no substitute would be
              honest.

              Everything else stays in the demo, because the demo is the sales
              pitch. Clients and SEO in particular are the screens that show
              the German Impressum finding priced as a fine, which is the whole
              reason to pay for this; the backend serves [SAMPLE] businesses
              for them rather than blocking them. Finance, CRM, Telegram and
              Job Radar already had demo-safe payloads all along. */}
          {/* Fourteen tabs in a `flex` with no wrap and no scroll put ~980px
              of buttons inside a 390px phone: the last six were unreachable,
              clipped at the right edge with nothing to indicate they existed.
              Measured on a real iPhone screenshot.

              Now a horizontal scroller with snap points. The negative margin
              lets it bleed to the screen edge so the cut-off tab is visibly
              half-shown — that is the affordance that tells a thumb to swipe.

              This used to carry `sm:overflow-visible` on the belief that above
              `sm` the tabs all fit. They do not. There are fifteen of them and
              they live in the main column, not the window: on a 1280px laptop
              that column is 999px and the row measures ~1092px, so the last
              two tabs hung 58px past the right edge of the PAGE — measured,
              `document.body.scrollWidth` 1338 against a 1280 viewport, which
              is a horizontal scrollbar on the whole dashboard. Letting the
              scroller stay live at every width fixes it without a breakpoint
              guess: when the tabs do fit, an `overflow-x-auto` container with
              nothing to scroll simply never scrolls. */}
          <div className="no-scrollbar -mx-3 flex snap-x snap-mandatory gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:px-0 sm:pb-0">
            {(([
              ["universe", "Universe", false],
              ["dashboard", "Dashboard", false],
              ["mission", "Mission", false],
              ["clients", "Clients", false],
              ["seo", "SEO", false],
              ["executive", "Executive", true],
              // Founder-only, and it must stay that way: every row is a real
              // customer's email address and there is no demo-safe substitute
              // for a customer list. The backend refuses a guest regardless
              // (/api/founder is registered sensitive) — this only stops the
              // tab appearing and producing a 403 nobody can explain.
              ["customers", "Customers", true],
              // Was founder-only because /api/voice is guest-blocked and had
              // no demo substitute, so the tab could only have produced a wall
              // of 403s. It has one now (demo_data serves sample sessions
              // through the real summariser), so the demo can show the feature
              // prospects are actually being sold. Transcripts stay founder-
              // only — the substitute covers /live and /sessions, nothing else.
              ["voice", "Voice", false],
              ["graph", "Graph", false],
              ["city", "AI City", false],
              ["warroom", "War Room", false],
              ["telegram", "Telegram", false],
              ["jobs", "Job Radar", false],
              ["finance", "Finance", false],
              ["crm", "CRM", false],
              ["apis", "APIs", false],
            ] as const)
              .filter(([, , founderOnly]) => !(founderOnly && isGuest()))
              .filter(([v]) => !customer || CUSTOMER_TABS.has(v))
            ).map(([v, label]) => (
              <button
                key={v}
                onClick={() => {
                  tap();
                  setView(v);
                }}
                // shrink-0 or flex squeezes 14 tabs into unreadable slivers
                // instead of letting them scroll. min-h-11 is the 44px touch
                // target; the old py-1.5/text-xs measured 17px tall, which is
                // a thumb-miss every time. Desktop keeps the compact size.
                className={`min-h-11 shrink-0 snap-start whitespace-nowrap rounded-lg border px-4 text-sm transition-colors sm:min-h-0 sm:px-3 sm:py-1.5 sm:text-xs ${
                  view === v
                    ? "border-hud-cyan/50 bg-hud-cyan/10 text-hud-cyan"
                    : "border-edge bg-panel/80 text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <AnimatePresence mode="wait">
          <motion.div
            key={view}
            initial={{ opacity: 0, y: 16, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -12, scale: 1.012 }}
            transition={{ duration: 0.32, ease: "easeOut" }}
            className="space-y-4"
          >
          {view === "universe" && (
            <Universe
              status={liveStatus}
              divisions={divisions}
              agents={agents}
              posts={posts}
              intensity={intensity}
              pulse={pulse}
              onNavigate={(v) => setView(v as typeof view)}
            />
          )}

          {view === "mission" && (
            <MissionControl
              status={liveStatus}
              agents={agents}
              opportunities={opportunities}
              executions={executions}
              decisions={decisions}
              feed={feed}
            />
          )}

          {view === "graph" && <KnowledgeGraph divisions={divisions} agents={agents} />}

          {view === "city" && (
            <AICity divisions={divisions} agents={agents} intensity={intensity} />
          )}

          {view === "warroom" && (
            <WarRoomView intensity={intensity} agentCount={liveStatus?.total_agents ?? agents.length} />
          )}

          {view === "clients" && <ClientCommand />}

          {view === "seo" && <SeoCommand />}

          {view === "executive" && <ExecutiveCommand />}

          {/* A subscriber's customers are the leads they have won - the
              founder's list is his own subscribers and never theirs. */}
          {view === "customers" &&
            (customer ? <MyCustomers onOpenCrm={() => setView("crm")} /> : <Customers />)}

          {view === "voice" && <VoiceAgents />}

          {view === "telegram" && <TelegramCenter />}

          {view === "jobs" && <JobRadar />}

          {view === "finance" && <FinanceCenter />}

          {view === "crm" && <CrmLite />}

          {view === "apis" && <ApiCommand />}

          {view === "dashboard" && (
          <>
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
              {customer && !hasBusiness ? (
                <section className="panel flex h-full flex-col justify-center gap-3 p-5">
                  <div className="hud-label">Your first business</div>
                  <p className="text-sm text-slate-300">
                    Titan audits your website for SEO and legal compliance, drafts the
                    fixes and keeps watching it. It all starts with one business.
                  </p>
                  <button
                    onClick={() => setView("clients")}
                    className="self-start rounded-lg border border-hud-cyan/50 bg-hud-cyan/10 px-4 py-2 text-sm text-hud-cyan hover:bg-hud-cyan/20"
                  >
                    Add a business
                  </button>
                </section>
              ) : (
                <NextPost post={nextPost} onChange={refreshNextPost} />
              )}
            </div>
          </div>

          <CommandBar onDispatched={refresh} />

          {/* The scan / refresh / weekly-report actions run the founder's own
              engines and connectors. A subscriber's row holds the Urdu
              briefing only, which speaks their own numbers. */}
          <div className="flex flex-wrap gap-2">
            {!customer && [
              { key: "scan", label: "Scan opportunities", icon: RadarIcon, fn: () => api.scanOpportunities() },
              { key: "refresh", label: "Refresh assets", icon: RefreshCw, fn: () => api.refreshConnectors() },
              { key: "report", label: "Generate weekly report", icon: FileBarChart, fn: () => api.weeklyReport() },
            ].map(({ key, label, icon: Icon, fn }) => (
              <button
                key={key}
                onClick={() => runAction(key, fn)}
                disabled={actionBusy === key || isGuest()}
                title={isGuest() ? "Disabled in the read-only demo" : label}
                className="flex items-center gap-1.5 rounded-lg border border-edge bg-panel/80 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan disabled:opacity-50"
              >
                <Icon className={`h-3.5 w-3.5 ${actionBusy === key ? "animate-spin" : ""}`} />
                {actionBusy === key ? "Working…" : label}
              </button>
            ))}
            <UrduVoiceAssistant status={liveStatus} />
          </div>

          {/* AI thinking visualization — shown while a command runs */}
          <AnimatePresence>
            {actionBusy && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
              >
                <ThinkingTrace label={`Executing: ${actionBusy}`} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Revenue ledger + Ask Titan. A subscriber's are their own:
              /api/me/revenue/* writes their workspace ledger, and Ask Titan
              answers from their businesses (router._subscriber_brief). */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RevenueTracker total={mrr} onLogged={refresh} />
            <AskTitan />
          </div>

          <GrowthStudio />

          {/* Connected assets are the founder's live products. A subscriber
              has none connected yet, and an empty frame says nothing. */}
          {!customer && <ConnectedAssets connectors={connectors} />}

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
          </>
          )}
          </motion.div>
          </AnimatePresence>
        </div>

        {/* Channels + agent roster. It is reference material, not a headline:
            below the numbers on a phone, and the sticky left rail on `lg`
            exactly as before. */}
        <div className="lg:sticky lg:top-4 lg:col-start-1 lg:row-start-1 lg:h-[calc(100vh-1.5rem)]">
          <Sidebar channels={channels} agents={agents} />
        </div>
      </div>

      <footer className="mt-6 flex items-center justify-between border-t border-edge/60 pt-4 text-[11px] text-slate-600">
        <span>
          Project Titan Omega · Executive Intelligence Core v0.3 ·{" "}
          {customer ? `${displayName()}'s workspace` : "Abdullah's Empire"}
        </span>
        <span className="font-mono">
          {liveStatus ? `updated ${new Date(liveStatus.updated_at).toLocaleTimeString()}` : "connecting…"}
        </span>
      </footer>
      </div>
    </main>
  );
}
