---
title: Project Titan Omega
emoji: 🏢
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: other
short_description: Autonomous Founder Empire OS with 102 AI agents
---

# Project Titan Omega

**The Autonomous Founder Empire Operating System.**

Titan Omega is a digital company: a hierarchy of autonomous AI divisions that
continuously analyze, execute, optimize and grow every business asset under their
control, all coordinated by an **Executive Intelligence Core** (the AI CEO) and
driven from a single Iron-Man-style **Empire Command Center**.

---

## What's here

```
project-titan-omega/
├── backend/    Executive Intelligence Core — FastAPI + the 102-agent network
└── frontend/   Empire Command Center — Next.js + Tailwind + Framer Motion dashboard
```

### Backend — Executive Intelligence Core

- **102 specialized agents** across **12 autonomous divisions**
- **Executive Intelligence Core**: planning, forecasting, command routing
- **Global Opportunity Engine**: scores growth opportunities
- **Autonomous Execution Layer**: logged, verified, reversible actions
- **Deliverable Engine**: real agent artifacts (emails, SEO, copy, reports)
- **Multi-model LLM**: Groq (free) · Claude · OpenAI-compatible · Gemini
- **Self-Evolution Engine**: scoring weights adapt from real outcomes
- **Real metrics webhooks**: Make.com pushes live Fiverr/Stripe data in
- **Career Mind connector**: polls live HF Space for real stats

### Frontend — Empire Command Center

Dark, animated, Jarvis/cyberpunk command center with live divisions, opportunity radar, agent deliverables, execution feed, and natural-language command bar.

---

## Quick start

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

### Free AI with Groq
1. Get key at https://console.groq.com/keys
2. Set `GROQ_API_KEY` in HF Space secrets
3. Restart — agents reason with Groq LLaMA/Mixtral instantly

---

## HF Spaces deployment

See [`docs/DEPLOY_HF_SPACES.md`](docs/DEPLOY_HF_SPACES.md). Required secrets:
- `TITAN_USERNAME` / `TITAN_PASSWORD` / `TITAN_SECRET`
- `GROQ_API_KEY`
- `TITAN_WEBHOOK_SECRET`

## Make.com automation

See [`docs/MAKECOM_AUTOMATION.md`](docs/MAKECOM_AUTOMATION.md) for 5 ready scenarios.

---

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/status` | Empire snapshot |
| GET | `/api/divisions` | Division org map + health |
| GET | `/api/agents` | 102-agent network |
| GET | `/api/plan/{daily\|weekly\|monthly}` | Strategic plan |
| GET | `/api/forecast/{metric}` | Revenue/traffic forecast |
| POST | `/api/command` | Natural-language command |
| GET | `/api/intelligence` | AI provider status |
| GET | `/api/opportunities` | Ranked opportunities |
| GET | `/api/deliverables` | Agent artifacts |
| POST | `/api/deliverables/draft` | Draft from brief |
| GET | `/api/executions` | Action log |
| GET | `/api/metrics` | All live metrics |
| POST | `/api/metrics/update` | Push single metric |
| POST | `/api/metrics/bulk` | Push multiple metrics |
| GET | `/api/evolution` | Evolution weight status |
| GET | `/api/feed` | Live execution feed |

---

## Status

| Capability | State |
| ---------- | ----- |
| 102 agents across 12 divisions | ✅ |
| Planning, forecasting, routing | ✅ |
| Opportunity Engine + scoring | ✅ |
| Execution Layer (logged/reversible) | ✅ |
| Deliverable Engine (AI artifacts) | ✅ |
| Multi-model LLM (Groq/Claude/OpenAI/Gemini) | ✅ |
| Self-Evolution Engine | ✅ |
| Real metrics webhooks | ✅ |
| Career Mind live connector | ✅ |
| Command Center dashboard | ✅ |
| HF Spaces deployment | ✅ |
| Fiverr live connector | 🟡 no public API |
| PostgreSQL/Redis persistence | 🟡 roadmap |

## Tech stack

**Frontend:** Next.js 14 · TypeScript · TailwindCSS · Framer Motion  
**Backend:** Python 3.11 · FastAPI · Pydantic v2  
**AI:** Groq · Claude · OpenAI-compatible · Gemini · free fallback
