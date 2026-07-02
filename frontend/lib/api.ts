// Thin API client for the Executive Intelligence Core.

import type {
  AgentView,
  ChannelTile,
  CommandResponse,
  Connector,
  Debate,
  Deliverable,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  GrowthIntel,
  IntelligenceStatus,
  JobItem,
  JobsState,
  NextPost,
  Opportunity,
  PrResult,
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
  status: () => get<EmpireStatus>("/status", MOCK.status),
  divisions: () => get<DivisionView[]>("/divisions", MOCK.divisions),
  agents: () => get<AgentView[]>("/agents", MOCK.agents),
  opportunities: () => get<Opportunity[]>("/opportunities", MOCK.opportunities),
  feed: (limit = 40) => get<FeedEvent[]>(`/feed?limit=${limit}`, MOCK.feed),
  deliverables: () => get<Deliverable[]>("/deliverables", []),
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
    get<{ required: boolean; demo: boolean }>("/auth", { required: false, demo: true }),
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

  // telegram command center
  telegramStatus: () =>
    get<TelegramStatus>("/telegram/status", { configured: false, locked: false, handled: 0 }),
  telegramLog: (limit = 50) => get<TelegramLogEntry[]>(`/telegram/log?limit=${limit}`, []),

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
