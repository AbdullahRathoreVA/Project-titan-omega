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

// Mission Control (GET /api/executions, /api/decisions)
export interface ExecutionItem {
  id: string;
  title: string;
  description: string;
  agent_id: string;
  division: Division;
  status: string;
  requires_approval: boolean;
  created_at: string;
  updated_at: string;
}

export interface DecisionEntry {
  goal: string;
  decision: string;
  confidence: number;
  time: string;
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
  progress?: number;
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

export interface RevenueEntry {
  id: string;
  amount: number;
  source: string;
  note: string;
  created_at: string;
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

export interface ScheduledPost {
  id: string;
  content: string;
  channels: string[];
  image_url: string | null;
  agent_id: string;
  scheduled_at: string;
  status: "scheduled" | "queued" | "published" | "failed";
  results: { channel: string; status: string; detail?: string }[];
  created_at: string;
}

// A social / work channel tile in the HUD sidebar. Real numbers arrive via
// Make.com pushing metric keys (e.g. instagram_followers); else status="pending".
export interface ChannelTile {
  id: string;
  name: string;
  accent: string;
  icon: string;
  status: "connected" | "pending";
  value: number;
  label: string;
  href: string;
}

// The next ready-to-post draft shown on the HUD "Next Post" card.
export interface NextPost {
  id: string;
  target: string;
  caption: string;
  image_prompt: string;
  image_url: string;
  link: string;
  channels: string[];
  created_at: string;
}

// Autonomous Growth Engine research (GET /api/growth/intel).
export interface GrowthIntel {
  opportunities: { title: string; url: string; snippet: string }[];
  competitors: { title: string; url: string; snippet: string }[];
  keywords: string[];
  headlines: { title: string; link: string }[];
  summary: string;
  live: boolean;
  last_run: string | null;
}

// Marketing war room debate (POST /api/warroom/debate).
export interface Debate {
  goal: string;
  proposals: { name: string; proposal: string }[];
  critiques?: { name: string; note: string }[];
  decision: string;
  confidence?: number;
}

// Content Repurposing Factory (POST /api/content/repurpose).
export interface RepurposePack {
  blog: string;
  linkedin: string;
  xthread: string;
  instagram: string;
  email: string;
  shorts: string;
}

// Gamification (GET /api/progress) — real events only.
export interface Progress {
  xp: number;
  level: number;
  level_floor: number;
  next_level_xp: number;
  milestones: { label: string; done: boolean }[];
}

// Automation performance (GET /api/performance).
export interface Performance {
  posts_scheduled: number;
  posts_published: number;
  deliverables: number;
  jobs_found: number;
  jobs_applied: number;
  leads_total: number;
  leads_won: number;
  telegram_commands: number;
  council_decisions: number;
  research_last_run: string | null;
  time_saved_minutes_estimate: number;
}

// SEO co-pilot report (POST /api/seo/report).
export interface SeoReport {
  keyword: string;
  live: boolean;
  competitors: { title: string; url: string }[];
  report: string;
}

// Telegram command center (GET /api/telegram/*).
export interface TelegramStatus {
  configured: boolean;
  locked: boolean;
  handled: number;
}

export interface TelegramLogEntry {
  time: string;
  from: string;
  chat_id: number;
  command: string;
  reply: string;
}

// Job Radar (GET /api/jobs).
export interface JobItem {
  id: string;
  score: number | null;
  title: string;
  url: string;
  why: string;
  applied: boolean;
  found_at: string;
}

export interface JobsState {
  items: JobItem[];
  live: boolean;
  last_scan: string | null;
}

// Financial Center (GET /api/finance).
export interface ExpenseItem {
  id: string;
  amount: number;
  category: string;
  note: string;
  created_at: string;
}

export interface FinanceState {
  revenue_total: number;
  expenses_total: number;
  profit: number;
  revenue_30d: number;
  expenses_30d: number;
  forecast_monthly_revenue: number;
  forecast_monthly_profit: number;
  expenses: ExpenseItem[];
}

// CRM-lite (GET /api/leads).
export interface Lead {
  id: string;
  name: string;
  source: string;
  contact: string;
  note: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** One rung of the lead funnel: how many leads EVER reached this stage.
 *  Not the same as `counts`, which is where leads are sitting right now. */
export interface FunnelStage {
  stage: string;
  reached: number;
  pct: number;
  dropped: number;
}

export interface LeadsState {
  items: Lead[];
  counts: Record<string, number>;
  statuses: string[];
  stages: string[];
  funnel: FunnelStage[];
  lost: number;
  conversion_pct: number;
}

// Result of opening an auto-PR (POST /api/devops/pr).
export interface PrResult {
  ok: boolean;
  pr_url: string | null;
  error?: string;
  repo?: string;
  path?: string;
  branch?: string;
}

// One live frame from GET /api/stream (Server-Sent Events).
export interface StreamFrame {
  ts: string;
  status: {
    health: number;
    mrr: number;
    traffic: number;
    active_agents: number;
    total_agents: number;
    open_opportunities: number;
    actions_in_flight: number;
    pipeline_value: number;
  };
  events: FeedEvent[];
  intensity: number;
}
