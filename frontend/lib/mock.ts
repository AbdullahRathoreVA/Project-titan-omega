// Static fallback data so the command center renders without a live core.
// Shapes match lib/types.ts exactly.
//
// IMPORTANT: all financial figures are ZERO. This is a real startup — the
// dashboard must never display fake earnings. When the live core is reachable
// these are replaced by real numbers; offline, the truth (zero) is shown.

import type {
  AgentView,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  Opportunity,
} from "./types";

const nowIso = () => new Date().toISOString();

const status: EmpireStatus = {
  health: 0,
  total_agents: 102,
  active_agents: 0,
  divisions: 12,
  open_opportunities: 0,
  pipeline_value: 0,
  actions_in_flight: 0,
  mrr: 0,
  traffic: 0,
  updated_at: nowIso(),
};

const DIVS: { d: DivisionView["division"]; head: string }[] = [
  { d: "executive", head: "Chief Executive Officer" },
  { d: "operations", head: "Chief Operating Officer" },
  { d: "finance", head: "Chief Financial Officer" },
  { d: "marketing", head: "Chief Marketing Officer" },
  { d: "technology", head: "Chief Technology Officer" },
  { d: "product", head: "Chief Product Officer" },
  { d: "revenue", head: "VP of Revenue" },
  { d: "growth", head: "VP of Growth" },
  { d: "intelligence", head: "Chief Intelligence Officer" },
  { d: "customer", head: "VP of Customer Success" },
  { d: "partnerships", head: "VP of Business Development" },
  { d: "innovation", head: "Chief Innovation Officer" },
];

const divisions: DivisionView[] = DIVS.map(({ d, head }) => ({
  division: d,
  head,
  agent_count: 8,
  active_agents: 0,
  health: 0,
  kpis: ["growth", "efficiency", "impact"],
}));

const agents: AgentView[] = DIVS.map(({ d, head }) => ({
  id: `${d}-head`,
  name: head,
  title: head,
  division: d,
  is_head: true,
  autonomy: d === "executive" ? "autonomous" : "execute",
  status: "idle",
  mission: `Lead the ${d} division toward Abdullah's first revenue.`,
  current_task: "Connecting to core…",
  kpis: ["growth", "efficiency", "impact"],
  tools: ["planner", "analytics"],
  tasks_completed: 0,
  success_rate: 0,
  impact_score: 0,
  last_active: nowIso(),
}));

// Opportunities are PROJECTIONS (not earned money) — kept as suggestions but
// with modest, honest estimates so nothing looks like real revenue.
const opportunities: Opportunity[] = [
  {
    id: "opp-1", title: "Promote your Fiverr AI gig in student communities",
    description: "Free, high-intent traffic from Reddit, Discord and university groups.",
    source_agent: "marketing-head", category: "growth",
    status: "scored", expected_revenue: 0, difficulty: 30, risk: 15,
    time_estimate_days: 3, priority_score: 70,
    execution_plan: ["List 10 communities", "Write value posts", "Share gig link", "Track clicks"],
    discovered_at: nowIso(),
  },
  {
    id: "opp-2", title: "Email 20 schools about Career Mind AI",
    description: "B2B outreach selling Career Mind as a free-trial career tool.",
    source_agent: "revenue-head", category: "sales",
    status: "scored", expected_revenue: 0, difficulty: 40, risk: 20,
    time_estimate_days: 5, priority_score: 65,
    execution_plan: ["Build school list", "Draft email", "Send via Gmail", "Follow up"],
    discovered_at: nowIso(),
  },
];

const feed: FeedEvent[] = [
  { id: "e1", timestamp: nowIso(), actor: "executive-core", kind: "system", message: "Connecting to Executive Intelligence Core…", severity: "info" },
];

export const MOCK = { status, divisions, agents, opportunities, feed };
