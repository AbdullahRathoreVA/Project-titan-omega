---
title: Project Titan Omega
emoji: 🏢
colorFrom: purple
colorTo: cyan
sdk: docker
app_port: 7860
pinned: false
license: other
short_description: Autonomous Founder Empire OS — 102 AI agents running your business
---

# Project Titan Omega

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
- **Multi-model AI** (`app/core/llm.py`): Claude → Groq → OpenAI-compatible →
  Gemini → free fallback. Set any one API key and agents think with that model.
- **Self-Evolution Engine** (`app/engines/evolution.py`): scoring weights adapt
  based on real execution outcomes — the system learns what actually works.
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
- Polls the core every 5s; falls back to local mock data when backend is offline.

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

### Enable free AI (Groq — no credit card)

```bash
export GROQ_API_KEY=your_key_here   # get free key at console.groq.com
```

The dashboard badge switches from **Free mode** to **Groq online** and
deliverables become AI-generated automatically.

### Deploy to Hugging Face Spaces (free, always-on)

See **[docs/DEPLOY_HF_SPACES.md](docs/DEPLOY_HF_SPACES.md)** — takes ~10 minutes,
gives you a public URL you can open from your phone.

### Make.com automation (real data in the dashboard)

See **[docs/MAKECOM_AUTOMATION.md](docs/MAKECOM_AUTOMATION.md)** — 5 ready-to-use
scenarios that push real Fiverr/Stripe/Career Mind numbers into the dashboard.

---

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/status` | Empire snapshot (health, MRR, agents…) |
| GET | `/api/divisions` | Division org map + health |
| GET | `/api/agents` `?division=&heads_only=` | Digital Employee Network |
| GET | `/api/plan/{daily\|weekly\|monthly}` | Strategic plan |
| GET | `/api/forecast/{metric}?horizon=` | Revenue / traffic forecast |
| POST | `/api/command` | Route a natural-language command |
| GET | `/api/intelligence` | Active AI provider + mode |
| GET | `/api/evolution` | Self-evolution scoring weights |
| GET | `/api/metrics` | All current empire metrics |
| POST | `/api/metrics/update` | Push a real metric value (Make.com) |
| POST | `/api/metrics/bulk` | Push multiple real metrics at once |
| GET | `/api/opportunities` | Ranked opportunities |
| POST | `/api/opportunities/scan` | Re-run the Opportunity Engine |
| GET | `/api/deliverables` | Artifacts agents have produced |
| POST | `/api/deliverables/from-opportunity/{id}` | Have an agent draft an artifact |
| POST | `/api/deliverables/draft` | Draft an artifact from a free-text brief |
| GET | `/api/executions` | Action log |
| POST | `/api/executions/from-opportunity/{id}` | Launch an action from an opportunity |
| POST | `/api/executions/{id}/{approve\|complete\|revert}` | Action lifecycle |
| GET | `/api/connectors` | Connected business assets |
| POST | `/api/connectors/refresh` | Re-sync GitHub + Career Mind live data |
| GET | `/api/feed?limit=` | Live execution feed |
| POST | `/api/report/weekly` | Generate weekly empire report |

---

## Status — what's built

| Capability | State |
| ---------- | ----- |
| 100+ agent network across divisions | ✅ 102 agents, 12 divisions |
| Executive Core: planning, forecasting, routing | ✅ rule-based + multi-model AI |
| Global Opportunity Engine + scoring | ✅ |
| Autonomous Execution Layer (logged/reversible) | ✅ |
| Deliverable Engine (real agent artifacts) | ✅ AI-generated, template fallback |
| Multi-model AI (Claude/Groq/OpenAI-compat/Gemini) | ✅ set any key, agents use it |
| Self-Evolution Engine | ✅ weights adapt from execution outcomes |
| Real metrics webhooks (Make.com integration) | ✅ POST /api/metrics/update |
| Career Mind live connector | ✅ polls HF Space health + stats |
| GitHub live connector | ✅ live repo stats |
| Hugging Face Spaces deployment | ✅ one-click Docker deploy |
| Fiverr live connector | 🟡 seeded metrics (Fiverr has no public API) |
| Persistence (PostgreSQL/Redis/Celery) | 🟡 in-memory store behind a swappable API |
| Voice control, mobile/desktop apps | ⬜ roadmap |

---

## Tech stack

**Frontend:** Next.js 14 · TypeScript · TailwindCSS · Framer Motion · lucide-react
**Backend:** Python 3.11 · FastAPI · Pydantic v2
**AI:** Claude · Groq · OpenAI-compatible · Gemini (any one key; free fallback)
**Deploy:** Docker · Hugging Face Spaces · Render
