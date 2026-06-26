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
- **Multi-model LLM reasoning** (`app/core/llm.py`): supports **Groq** (free),
  **Claude**, **OpenAI-compatible**, and **Gemini** — falls back to deterministic
  logic when no key is set, so the platform always runs free.
- **Self-Evolution Engine** (`app/engines/evolution.py`): scoring weights adapt
  from real execution outcomes — the system learns what works.
- **Live feed + heartbeat**: a background loop keeps the empire working 24/7 and
  streams activity to the command center.

### Frontend — Empire Command Center (`frontend/`)

A dark, animated, Jarvis/cyberpunk command center.

- Headline empire metrics (revenue, traffic, pipeline, employees, actions).
- **Autonomous Divisions** org map with live health bars.
- **Agent Activity** panel (busiest, highest-impact employees first).
- **Global Opportunity Radar** with animated sweep and scored blips.
- **Agent Deliverables** panel — read the real artifacts agents produced.
- **Live Execution Feed** streaming agent decisions and actions.
- **Natural-language command bar** — type or pick a suggestion to task a division.
- Polls the core every 5s; falls back to local mock data with an honest badge.

---

## Quick start

### 1. Executive Intelligence Core (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

### 2. Empire Command Center (frontend)

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev   # http://localhost:3000
```

### Groq (free AI — no credit card)

1. Get a free key at https://console.groq.com/keys
2. Set `GROQ_API_KEY` in your HF Space secrets or local `.env`
3. Restart — agents immediately start reasoning with Groq LLaMA/Mixtral

### Tests

```bash
cd backend && python -m pytest
cd frontend && npm run build
```

---

## Hugging Face Spaces deployment

This repo is ready to deploy as a Docker Space. See [`docs/DEPLOY_HF_SPACES.md`](docs/DEPLOY_HF_SPACES.md).

Required secrets in your Space settings:
- `TITAN_USERNAME` / `TITAN_PASSWORD` / `TITAN_SECRET` — dashboard login
- `GROQ_API_KEY` — free AI reasoning
- `TITAN_WEBHOOK_SECRET` — secures Make.com webhooks

---

## Make.com automation

See [`docs/MAKECOM_AUTOMATION.md`](docs/MAKECOM_AUTOMATION.md) for 5 ready-to-use
scenarios that push real Fiverr/Stripe/Career Mind numbers into the live dashboard.

---

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/status` | Empire snapshot (health, MRR, agents…) |
| GET | `/api/divisions` | Division org map + health |
| GET | `/api/agents` | Digital Employee Network |
| GET | `/api/plan/{daily\|weekly\|monthly}` | Strategic plan |
| GET | `/api/forecast/{metric}?horizon=` | Revenue / traffic forecast |
| POST | `/api/command` | Route a natural-language command |
| GET | `/api/intelligence` | AI provider status |
| GET | `/api/opportunities` | Ranked opportunities |
| POST | `/api/opportunities/scan` | Re-run the Opportunity Engine |
| GET | `/api/deliverables` | Artifacts agents have produced |
| POST | `/api/deliverables/draft` | Draft an artifact from a brief |
| GET | `/api/executions` | Action log |
| GET | `/api/metrics` | All live metrics |
| POST | `/api/metrics/update` | Push a single real metric (Make.com) |
| POST | `/api/metrics/bulk` | Push multiple real metrics (Make.com) |
| GET | `/api/evolution` | Self-evolution weight status |
| GET | `/api/connectors` | Connected business assets |
| GET | `/api/feed?limit=` | Live execution feed |

---

## Status — what's built

| Capability | State |
| ---------- | ----- |
| 100+ agent network across divisions | ✅ 102 agents, 12 divisions |
| Executive Core: planning, forecasting, routing | ✅ rule-based + AI-backed |
| Global Opportunity Engine + scoring | ✅ |
| Autonomous Execution Layer (logged/reversible) | ✅ |
| Deliverable Engine (real agent artifacts) | ✅ AI-generated, template fallback |
| Multi-model LLM (Groq / Claude / OpenAI / Gemini) | ✅ auto-detects from env vars |
| Self-Evolution Engine (adaptive scoring weights) | ✅ |
| Real metrics webhooks (Make.com integration) | ✅ |
| Career Mind live connector | ✅ polls live HF Space |
| Command Center dashboard (live, animated) | ✅ |
| HF Spaces deployment (always-on, free) | ✅ |
| Fiverr live connector | 🟡 seeded metrics (no public Fiverr API) |
| Persistence (PostgreSQL/Redis/Celery) | 🟡 in-memory store, swappable |
| Voice control, mobile/desktop apps | ⬜ roadmap |

---

## Tech stack

**Frontend:** Next.js 14 · TypeScript · TailwindCSS · Framer Motion · lucide-react  
**Backend:** Python 3.11 · FastAPI · Pydantic v2  
**AI:** Groq (free) · Claude · OpenAI-compatible · Gemini · deterministic fallback  
