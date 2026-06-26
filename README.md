# Project Titan Omega
---
title: Project Titan Omega
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---
**The Autonomous Founder Empire Operating System.**

Titan Omega is a digital company: a hierarchy of autonomous AI divisions that
continuously analyze, execute, optimize and grow every business asset under their
control, all coordinated by an **Executive Intelligence Core** (the AI CEO) and
driven from a single Iron-Man-style **Empire Command Center**.

This repository is the **runnable foundation** for that vision — a real,
working vertical slice of the architecture, built so the larger system can grow
on top of it. See [Status](#status--whats-built) for an honest map of what is
implemented today versus what is on the roadmap.

---

## What's here

```
project-titan-omega/
├── backend/    Executive Intelligence Core — FastAPI + the 102-agent network
└── frontend/   Empire Command Center — Next.js + Tailwind + Framer Motion dashboard
```

### Backend — Executive Intelligence Core (`backend/`)

The AI CEO and the Digital Employee Network.

- **102 specialized agents** across **12 autonomous divisions** (Executive,
  Operations, Finance, Marketing, Technology, Product, Revenue, Growth,
  Intelligence, Customer, Partnerships, Innovation) — each with a mission, KPIs,
  tools and an **autonomy level** (`observe` → `suggest` → `execute` →
  `autonomous`). Defined in `app/domain/network.py`.
- **Executive Intelligence Core** (`app/core/executive.py`): empire health,
  division health, daily/weekly/monthly **strategic plans**, revenue/traffic
  **forecasts**, and natural-language **command routing** to the right division.
- **Global Opportunity Engine** (`app/engines/opportunity.py`): surfaces growth
  opportunities and scores each on a transparent rubric (expected revenue
  discounted by difficulty, risk and time-to-value).
- **Autonomous Execution Layer** (`app/engines/execution.py`): turns intents into
  **logged, verified, reversible** actions. `suggest`-level agents require human
  approval; `execute`/`autonomous` agents act within guardrails.
- **Deliverable Engine** (`app/engines/deliverables.py`): agents produce **real,
  usable artifacts** — outreach emails, SEO plans, landing copy, growth
  strategies, product roadmaps, business reports.
- **Claude reasoning** (`app/core/llm.py`): with an `ANTHROPIC_API_KEY` set,
  agents plan, reply, and draft with **Claude (`claude-opus-4-8`)**; with no key
  they fall back to deterministic logic, so the platform always runs free.
- **Live feed + heartbeat**: a background loop keeps the empire working 24/7 and
  streams activity to the command center.

### Frontend — Empire Command Center (`frontend/`)

A dark, animated, Jarvis/cyberpunk command center.

- Headline empire metrics (revenue, traffic, pipeline, employees, actions).
- **Autonomous Divisions** org map with live health bars.
- **Agent Activity** panel (busiest, highest-impact employees first).
- **Global Opportunity Radar** with animated sweep and scored blips.
- **Agent Deliverables** panel — read the real artifacts agents produced; one
  click on an opportunity's **Execute** button drafts a new one.
- **Live Execution Feed** streaming agent decisions and actions.
- **Natural-language command bar** — type or pick a suggestion to task a division.
- A **Claude / Free mode** badge shows whether agents are reasoning with Claude.
- Polls the core every 5s; falls back to local mock data (with an honest
  "Core offline (demo)" badge) so the UI renders even without the backend.

---

## Quick start

**Non-technical?** Read [`START_HERE.md`](START_HERE.md) — or just run
`make install && make dev` and open <http://localhost:3000>.

### 1. Executive Intelligence Core (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

Runs with **no external services** — agents, opportunities and metrics are seeded
deterministically into an in-memory store on boot.

### 2. Empire Command Center (frontend)

```bash
cd frontend
npm install
cp .env.local.example .env.local      # points the proxy at the core
npm run dev                            # http://localhost:3000
```

The dashboard proxies `/api/*` to the core (configurable via `TITAN_API_URL`).

### Tests

```bash
cd backend && python -m pytest        # 14 tests: network, engines, core, API
cd frontend && npm run build          # type-checks + builds the dashboard
```

---

## API surface

| Method | Path                                          | Purpose                                  |
| ------ | --------------------------------------------- | ---------------------------------------- |
| GET    | `/api/status`                                 | Empire snapshot (health, MRR, agents…)   |
| GET    | `/api/divisions`                              | Division org map + health                |
| GET    | `/api/agents` `?division=&heads_only=`        | Digital Employee Network                 |
| GET    | `/api/plan/{daily\|weekly\|monthly}`          | Strategic plan                           |
| GET    | `/api/forecast/{metric}?horizon=`             | Revenue / traffic forecast               |
| POST   | `/api/command`                                | Route a natural-language command         |
| GET    | `/api/intelligence`                           | Claude-connected? (mode: claude \| free) |
| GET    | `/api/opportunities`                          | Ranked opportunities                     |
| POST   | `/api/opportunities/scan`                     | Re-run the Opportunity Engine            |
| GET    | `/api/deliverables`                           | Artifacts agents have produced           |
| POST   | `/api/deliverables/from-opportunity/{id}`     | Have an agent draft an artifact          |
| POST   | `/api/deliverables/draft`                     | Draft an artifact from a free-text brief |
| GET    | `/api/executions`                             | Action log                               |
| POST   | `/api/executions/from-opportunity/{id}`       | Launch an action from an opportunity     |
| POST   | `/api/executions/{id}/{approve\|complete\|revert}` | Action lifecycle                    |
| GET    | `/api/connectors`                             | Connected business assets                |
| GET    | `/api/feed?limit=`                            | Live execution feed                      |

---

## Status — what's built

| Capability                                   | State                                      |
| -------------------------------------------- | ------------------------------------------ |
| 100+ agent network across divisions          | ✅ 102 agents, 12 divisions                 |
| Executive Core: planning, forecasting, routing | ✅ rule-based + Claude-backed              |
| Global Opportunity Engine + scoring          | ✅                                          |
| Autonomous Execution Layer (logged/reversible) | ✅                                         |
| Deliverable Engine (real agent artifacts)    | ✅ Claude-generated, template fallback      |
| LLM-backed reasoning (Claude `claude-opus-4-8`) | ✅ live when `ANTHROPIC_API_KEY` is set    |
| Command Center dashboard (live, animated)    | ✅                                          |
| Business connectors (GitHub/Fiverr/Career Mind) | 🟡 registry + seeded metrics (not live yet) |
| Gemini / OpenAI / open-source models         | 🟡 same `llm.complete` seam, not wired      |
| Persistence (PostgreSQL/Redis/Celery)        | 🟡 in-memory store behind a swappable API   |
| Voice control, mobile/desktop apps           | ⬜ roadmap                                   |
| Self-Evolution Engine                        | ⬜ roadmap (scoring weights are tunable)     |

### Wiring real models

Claude is already wired in. `app/core/llm.py` exposes a single `complete(system,
prompt)` seam that every agent reasons through: it uses **`claude-opus-4-8`** with
adaptive thinking when `ANTHROPIC_API_KEY` is set, and returns `None` (so callers
fall back to deterministic logic) when it isn't — the platform never requires a
key to run. Command replies and deliverable generation already flow through it;
pointing a Gemini/OpenAI/open-source model at the same seam is a localized change.

### Production architecture (target)

The in-memory `Store` (`app/store.py`) is intentionally hidden behind a small
interface. Swapping in **PostgreSQL** (system of record), **Redis** (live state +
pub/sub for the feed) and **Celery** (agent task execution) is an implementation
change behind that interface, not a rewrite of the engines or routes. A vector DB
+ RAG layer provides the long-term memory referenced in the agent specs.

---

## Tech stack

**Frontend:** Next.js 14 · TypeScript · TailwindCSS · Framer Motion · lucide-react
**Backend:** Python 3.11 · FastAPI · Pydantic v2 · (PostgreSQL / Redis / Celery on the roadmap)
**AI (roadmap):** Claude · Gemini · OpenAI · open-source models · vector DB / RAG · multi-agent orchestration · MCP
