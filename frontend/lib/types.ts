// Mirrors the FastAPI core's pydantic schemas (backend/app/domain/schemas.py).

export type Division =
  | "executive" | "operations" | "finance" | "marketing" | "technology"
  | "product" | "revenue" | "growth" | "intelligence" | "customer"
  | "partnerships" | "innovation";

export type AgentStatus = "idle" | "working" | "blocked" | "offline";
export type Autonomy = "observe" | "suggest" | "execute" | "autonomous";

export interface EmpireStatus {
  health: number;
  total_agents: number;
  active_agents: number;
  divisions: number;
  open_opportunities: number;
  pipeline_value: number;
  actions_in_flight: number;
  mrr: number;
  traffic: number;
  updated_at: string;
}

export interface DivisionView {
  division: Division;
  head: string;
  agent_count: number;
  active_agents: number;
  health: number;
  kpis: string[];
}

export interface AgentView {
  id: string;
  name: string;
  title: string;
  division: Division;
  is_head: boolean;
  autonomy: Autonomy;
  status: AgentStatus;
  mission: string;
  current_task: string | null;
  kpis: string[];
  tools: string[];
  tasks_completed: number;
  success_rate: number;
  impact_score: number;
  last_active: string | null;
}

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  source_agent: string;
  category: string;
  status: string;
  expected_revenue: number;
  difficulty: number;
  risk: number;
  time_estimate_days: number;
  priority_score: number;
  execution_plan: string[];
  discovered_at: string;
}

export interface FeedEvent {
  id: string;
  timestamp: string;
  actor: string;
  kind: string;
  message: string;
  severity: "info" | "success" | "warn" | "critical";
}

export interface CommandResponse {
  understood: boolean;
  intent: string;
  response: string;
  routed_to: string | null;
  actions: string[];
}

export interface Deliverable {
  id: string;
  title: string;
  kind: string;
  agent_id: string;
  agent_name: string;
  opportunity_id: string | null;
  content: string;
  source: "ai" | "template";
  created_at: string;
}

export interface IntelligenceStatus {
  claude_connected: boolean;
  model: string | null;
  mode: "claude" | "free";
}

export interface Connector {
  id: string;
  name: string;
  kind: string;
  status: string;
  url: string | null;
  discovered_at: string;
  last_sync: string | null;
  metrics: Record<string, number>;
}
