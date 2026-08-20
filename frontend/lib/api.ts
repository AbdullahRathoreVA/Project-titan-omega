// Thin API client for the Executive Intelligence Core.

import type {
  AgentView,
  ChannelTile,
  CommandResponse,
  Connector,
  Debate,
  DecisionEntry,
  Deliverable,
  DivisionView,
  EmpireStatus,
  ExecutionItem,
  ExpenseItem,
  FeedEvent,
  FinanceState,
  Lead,
  LeadsState,
  GrowthIntel,
  IntelligenceStatus,
  JobItem,
  JobsState,
  NextPost,
  Opportunity,
  Performance,
  PrResult,
  Progress,
  RepurposePack,
  RevenueEntry,
  ScheduledPost,
  SeoReport,
  TelegramLogEntry,
  TelegramStatus,
} from "./types";

const EMPTY_INTEL: GrowthIntel = {
  opportunities: [],
  competitors: [],
  keywords: [],
  headlines: [],
  summary: "",
  live: false,
  last_run: null,
};
import { MOCK } from "./mock";

const TOKEN_KEY = "titan_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export async function verifyToken(): Promise<boolean> {
  if (!getToken()) return false;
  try {
    const res = await fetch("/api/status", { cache: "no-store", headers: authHeaders() });
    return res.ok;
  } catch {
    return false;
  }
}

async function get<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, { cache: "no-store", headers: authHeaders() });
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

async function post<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function del<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`/api${path}`, { method: "DELETE", headers: authHeaders() });
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export const api = {
  // External API command centre. `get` returns the fallback on any error, so
  // these pass a shaped failure object rather than null — the panel renders
  // the reason instead of silently showing nothing.
  apisIntegrated: () =>
    get<any>("/apis/integrated", { integrated: { capabilities: [], count: 0, providers: [], note: "" }, catalogued: 0, adapters_written: 0 }),
  apisRates: (base = "USD", symbols = "PKR,EUR,GBP") =>
    get<any>(`/apis/live/rates?base=${encodeURIComponent(base)}&symbols=${encodeURIComponent(symbols)}`,
      { ok: false, error: "Could not reach the rates endpoint." }),
  apisWeather: (place: string) =>
    get<any>(`/apis/live/weather?place=${encodeURIComponent(place)}`,
      { ok: false, error: "Could not reach the weather endpoint." }),
  apisSearch: (q: string, limit = 8) =>
    get<any>(`/apis?q=${encodeURIComponent(q)}&limit=${limit}`,
      { total: 0, results: [] }),

  status: () => get<EmpireStatus>("/status", MOCK.status),
  divisions: () => get<DivisionView[]>("/divisions", MOCK.divisions),
  agents: () => get<AgentView[]>("/agents", MOCK.agents),
  opportunities: () => get<Opportunity[]>("/opportunities", MOCK.opportunities),
  feed: (limit = 40) => get<FeedEvent[]>(`/feed?limit=${limit}`, MOCK.feed),
  deliverables: () => get<Deliverable[]>("/deliverables", []),
  executions: () => get<ExecutionItem[]>("/executions", []),
  decisions: () => get<DecisionEntry[]>("/decisions", []),
  connectors: () => get<Connector[]>("/connectors", []),
  posts: () => get<ScheduledPost[]>("/posts", []),
  intelligence: () =>
    get<IntelligenceStatus>("/intelligence", {
      claude_connected: false,
      model: null,
      mode: "free",
    }),

  // auth
  authStatus: () =>
    get<{
      required: boolean;
      demo: boolean;
      guest?: boolean;
      guest_available?: boolean;
      /** Which login is answering. `identity` = real accounts with roles;
       *  `legacy` = the single TITAN_USERNAME/TITAN_PASSWORD gate. The sign-in
       *  form asks for an email under one and a username under the other, so
       *  the label is read from here rather than guessed. Carries no address:
       *  this endpoint answers before anyone has signed in. */
      identity?: {
        mode: "identity" | "legacy";
        founder_email_configured: boolean;
        founder_account_exists: boolean;
        environment_gate_reachable: boolean;
      };
    }>("/auth", {
      required: false,
      demo: true,
      guest: false,
      guest_available: true,
    }),
  /** What kind of session does the stored token represent? Authoritative —
   *  never infer this from browser storage. */
  sessionKind: () =>
    get<{ founder: boolean; guest: boolean }>("/session", { founder: false, guest: false }),
  /** Start the public read-only demo session (no login). */
  async enterDemo(): Promise<boolean> {
    try {
      const res = await fetch("/api/demo/enter", { method: "POST" });
      if (!res.ok) return false;
      const data = (await res.json()) as { token: string };
      setToken(data.token);
      return true;
    } catch {
      return false;
    }
  },
  async login(username: string, password: string): Promise<boolean> {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { token: string };
    setToken(data.token);
    return true;
  },
  logout: () => setToken(null),

  // actions (all auth-aware via post())
  schedulePost: (content: string, channels: string[], image_url?: string | null) =>
    post<ScheduledPost>("/posts", { content, channels, image_url: image_url ?? null }),
  publishPost: (id: string) => post<ScheduledPost>(`/posts/${id}/publish`),
  executeOpportunity: (id: string) => post<Deliverable>(`/deliverables/from-opportunity/${id}`),
  scanOpportunities: () => post<Opportunity[]>("/opportunities/scan"),
  refreshConnectors: () => post<Connector[]>("/connectors/refresh"),
  weeklyReport: () => post<Deliverable>("/report/weekly"),

  // revenue ledger
  logRevenue: (amount: number, source: string, note: string) =>
    post<{ entry: RevenueEntry; total: number; source_total: number }>("/revenue/log", {
      amount,
      source,
      note,
    }),
  revenueEntries: () => get<RevenueEntry[]>("/revenue/entries", []),
  cancelRevenue: (id: string) => del<{ cancelled: string; total: number }>(`/revenue/entry/${id}`),

  // growth studio
  intelGenerate: (kind: string, topic: string) =>
    post<{ kind: string; content: string }>("/intel/generate", { kind, topic }),
  intelNews: (topic: string) => post<{ content: string }>("/intel/news", { topic }),
  findLeads: (query: string) => post<{ content: string; live: boolean }>("/leads/find", { query }),

  // HUD: channels rail + next-post card
  channels: () => get<{ channels: ChannelTile[] }>("/channels", { channels: [] }),
  nextPost: () => get<NextPost | null>("/next-post", null),
  approveNextPost: () =>
    post<{ scheduled_id: string; channels: string[]; next_post: NextPost }>("/next-post/approve"),
  regenerateNextPost: (topic = "") => post<NextPost>("/next-post/regenerate", { topic }),

  // action-taking agents
  act: (instruction: string) => post<CommandResponse>("/agent/act", { instruction }),

  // talk to one specific agent (it replies in character)
  agentChat: (agentId: string, message: string, lang = "en") =>
    post<{ agent_id: string; name: string; reply: string }>(`/agents/${agentId}/chat`, {
      message,
      lang,
    }),

  // autonomous growth engine + war room + SEO co-pilot
  growthIntel: () => get<GrowthIntel>("/growth/intel", EMPTY_INTEL),
  growthScan: () => post<GrowthIntel>("/growth/scan"),
  warroomDebate: (topic = "") => post<Debate>("/warroom/debate", { topic }),
  seoReport: (keyword = "") => post<SeoReport>("/seo/report", { keyword }),
  openPr: (instruction: string, opts?: { owner?: string; repo?: string; path?: string }) =>
    post<PrResult>("/devops/pr", { instruction, ...(opts ?? {}) }),

  // content factory + gamification + performance
  repurpose: (idea: string, lang = "en") =>
    post<RepurposePack>("/content/repurpose", { idea, lang }),
  progress: () =>
    get<Progress>("/progress", { xp: 0, level: 1, level_floor: 0, next_level_xp: 100, milestones: [] }),
  performance: () => get<Performance | null>("/performance", null),

  // telegram command center
  telegramStatus: () =>
    get<TelegramStatus>("/telegram/status", { configured: false, locked: false, handled: 0 }),
  telegramLog: (limit = 50) => get<TelegramLogEntry[]>(`/telegram/log?limit=${limit}`, []),

  // financial center
  finance: () =>
    get<FinanceState>("/finance", {
      revenue_total: 0, expenses_total: 0, profit: 0, revenue_30d: 0, expenses_30d: 0,
      forecast_monthly_revenue: 0, forecast_monthly_profit: 0, expenses: [],
    }),
  logExpense: (amount: number, category: string, note: string) =>
    post<ExpenseItem>("/finance/expense", { amount, category, note }),
  deleteExpense: (id: string) => del<{ deleted: string }>(`/finance/expense/${id}`),

  // crm-lite
  leads: () =>
    get<LeadsState>("/leads", {
      items: [], counts: {}, statuses: [], stages: [],
      funnel: [], lost: 0, conversion_pct: 0,
    }),
  /** Find real businesses, file them, audit their sites, draft the approach.
   *  Directories and duplicates are dropped server-side. Sends nothing. */
  discoverLeads: (query: string) =>
    post<{
      created: { id: string; name: string; website?: string }[];
      researched: number;
      reason: string;
      rejected?: { directory: number; duplicate: number; already_known: number };
    }>("/leads/discover", { query, limit: 6, research: true, research_limit: 3 }),
  createLead: (name: string, source: string, contact: string, note: string) =>
    post<Lead>("/leads", { name, source, contact, note }),
  setLeadStatus: (id: string, status: string) => post<Lead>(`/leads/${id}/status`, { status }),
  deleteLead: (id: string) => del<{ deleted: string }>(`/leads/${id}`),

  // job radar
  jobs: () => get<JobsState>("/jobs", { items: [], live: false, last_scan: null }),
  jobsScan: (query = "") => post<JobsState>("/jobs/scan", { query }),
  jobProposal: (title: string, url: string, why: string) =>
    post<{ proposal: string }>("/jobs/proposal", { title, url, why }),
  jobApplied: (id: string) => post<JobItem>(`/jobs/${id}/applied`),

  async command(text: string): Promise<CommandResponse> {
    const res = await post<CommandResponse>("/agent/act", { instruction: text });
    return (
      res ?? {
        understood: false,
        intent: "offline",
        response: "Core unreachable — try again in a moment.",
        routed_to: null,
        actions: [],
      }
    );
  },
};
