// Thin API client for the Executive Intelligence Core.
//
// Requests go to /api/* which Next rewrites to the FastAPI core (see
// next.config.mjs). If the core is unreachable, each call falls back to a small
// deterministic mock so the command center still renders for design/demo work.

import type {
  AgentView,
  CommandResponse,
  Connector,
  Deliverable,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  IntelligenceStatus,
  Opportunity,
  RevenueEntry,
  ScheduledPost,
} from "./types";
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

// Confirms the stored token is accepted by the core (used by AuthGate so a stale
// token can't trap the dashboard in demo mode).
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

  async command(text: string): Promise<CommandResponse> {
    const res = await post<CommandResponse>("/command", { text });
    return (
      res ?? {
        understood: true,
        intent: "offline",
        response:
          "Core unreachable — command queued locally. Start the backend to dispatch it.",
        routed_to: null,
        actions: [],
      }
    );
  },
};
