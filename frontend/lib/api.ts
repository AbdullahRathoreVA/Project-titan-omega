// Thin API client for the Executive Intelligence Core.
//
// Requests go to /api/* which Next rewrites to the FastAPI core (see
// next.config.mjs). If the core is unreachable, each call falls back to a small
// deterministic mock so the command center still renders for design/demo work.

import type {
  AgentView,
  CommandResponse,
  Deliverable,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  IntelligenceStatus,
  Opportunity,
} from "./types";
import { MOCK } from "./mock";

async function get<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export const api = {
  status: () => get<EmpireStatus>("/status", MOCK.status),
  divisions: () => get<DivisionView[]>("/divisions", MOCK.divisions),
  agents: () => get<AgentView[]>("/agents", MOCK.agents),
  opportunities: () => get<Opportunity[]>("/opportunities", MOCK.opportunities),
  feed: (limit = 40) => get<FeedEvent[]>(`/feed?limit=${limit}`, MOCK.feed),
  deliverables: () => get<Deliverable[]>("/deliverables", []),
  intelligence: () =>
    get<IntelligenceStatus>("/intelligence", {
      claude_connected: false,
      model: null,
      mode: "free",
    }),

  async executeOpportunity(id: string): Promise<Deliverable | null> {
    try {
      const res = await fetch(`/api/deliverables/from-opportunity/${id}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`${res.status}`);
      return (await res.json()) as Deliverable;
    } catch {
      return null;
    }
  },

  async command(text: string): Promise<CommandResponse> {
    try {
      const res = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      return (await res.json()) as CommandResponse;
    } catch {
      return {
        understood: true,
        intent: "offline",
        response:
          "Core unreachable — command queued locally. Start the backend to dispatch it.",
        routed_to: null,
        actions: [],
      };
    }
  },
};
