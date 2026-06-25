// Static fallback data so the command center renders without a live core.
// Shapes match lib/types.ts exactly.

import type {
  AgentView,
  DivisionView,
  EmpireStatus,
  FeedEvent,
  Opportunity,
} from "./types";

const nowIso = () => new Date().toISOString();

const status: EmpireStatus = {
  health: 77.4,
  total_agents: 102,
  active_agents: 62,
  divisions: 12,
  open_opportunities: 6,
  pipeline_value: 312000,
  actions_in_flight: 3,
  mrr: 48230,
  traffic: 184500,
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

const divisions: DivisionView[] = DIVS.map(({ d, head }, i) => ({
  division: d,
  head,
  agent_count: 8 + (i % 3),
  active_agents: 4 + (i % 4),
  health: 60 + ((i * 7) % 35),
  kpis: ["growth", "efficiency", "impact"],
}));

const agents: AgentView[] = DIVS.map(({ d, head }, i) => ({
  id: `${d}-head`,
  name: head,
  title: head,
  division: d,
  is_head: true,
  autonomy: d === "executive" ? "autonomous" : "execute",
  status: i % 4 === 0 ? "idle" : "working",
  mission: `Lead the ${d} division and maximize its KPIs.`,
  current_task: "Advancing division objectives",
  kpis: ["growth", "efficiency", "impact"],
  tools: ["planner", "analytics"],
  tasks_completed: 40 + i * 6,
  success_rate: 0.85 + (i % 10) / 100,
  impact_score: 60 + ((i * 5) % 38),
  last_active: nowIso(),
}));

const opportunities: Opportunity[] = [
  {
    id: "opp-1", title: "New niche: AI-assisted LinkedIn profile optimization",
    description: "Adjacent market with high intent and low tooling.",
    source_agent: "innovation-opportunity-scout", category: "new_market",
    status: "scored", expected_revenue: 88000, difficulty: 70, risk: 50,
    time_estimate_days: 45, priority_score: 64.3,
    execution_plan: ["Size TAM", "Landing page test", "Adapt engine", "Soft launch"],
    discovered_at: nowIso(),
  },
  {
    id: "opp-2", title: "Launch affiliate program for Career Mind AI",
    description: "Recruit creators on revenue share.",
    source_agent: "partnerships-affiliate-manager", category: "partnership",
    status: "scored", expected_revenue: 52000, difficulty: 60, risk: 35,
    time_estimate_days: 30, priority_score: 58.1,
    execution_plan: ["Define tiers", "Build tracking", "Source creators", "Measure CAC"],
    discovered_at: nowIso(),
  },
  {
    id: "opp-3", title: "Introduce annual pricing tier with discount",
    description: "Improve cash flow and retention.",
    source_agent: "finance-pricing-strategist", category: "pricing",
    status: "scored", expected_revenue: 41000, difficulty: 30, risk: 20,
    time_estimate_days: 10, priority_score: 56.0,
    execution_plan: ["Model LTV", "Set discount", "Add tier", "Email subscribers"],
    discovered_at: nowIso(),
  },
];

const feed: FeedEvent[] = [
  { id: "e1", timestamp: nowIso(), actor: "executive-core", kind: "system", message: "Executive Intelligence Core online.", severity: "success" },
  { id: "e2", timestamp: nowIso(), actor: "intelligence-head", kind: "discovery", message: "Opportunity Engine surfaced 6 scored opportunities.", severity: "success" },
  { id: "e3", timestamp: nowIso(), actor: "growth-head", kind: "activity", message: "VP of Growth: auditing SEO keyword gaps.", severity: "info" },
];

export const MOCK = { status, divisions, agents, opportunities, feed };
