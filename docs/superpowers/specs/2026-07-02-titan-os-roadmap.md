# Titan OS — Executive Operating System Roadmap

Date: 2026-07-02
Status: living roadmap. Built increment-by-increment; each phase ships only
after the previous is verified live. Constraint: $0 budget, HF free tier.

## Already live (as of 2026-07-02)

- 3D HUD: Titan Core, Neural Lattice (War Room), global particle backdrop
- Live SSE stream, channel sidebar, talk-to-agent chat, next-post card with
  realistic seeded images
- Autonomous Growth Engine (24/7 web/news research, 4h cadence, Tavily-budgeted)
- Marketing War Room (multi-agent debate → head decision → action plan)
- SEO Co-pilot (live ranking landscape + action list)
- Auto-PRs to Career Mind (real GitHub pull requests, review-gated)
- Telegram Command Center (/status /revenue /agents /opportunities /report
  /news /search /ask /nextpost /approve) + dashboard page
- Job Radar (live job hunting + fit scores + truthful proposal drafts +
  applied tracking) + dashboard page
- Multi-provider LLM failover (Groq → OpenRouter multi-model) + /api/llm/health

## Phase next (small, high-value increments)

1. **Financial Center page** — expense logging alongside the revenue ledger,
   profit = revenue − expenses, simple forecast from run-rate. (All real data,
   no simulated numbers.)
2. **Approvals queue on Telegram** — war-room decisions and next-posts pushed
   to Telegram as approve/reject messages.
3. **Make.com Scenario 5/6 wiring** — channel stats + scheduled auto-posting
   (9:00 / 18:00 PKT windows).
4. **CRM-lite** — leads table (from lead-finder + Job Radar), status pipeline
   (new → contacted → replied → won), conversion counts.

## Parked — needs money, accounts, or its own project (honest constraints)

- **WhatsApp Business Cloud API**: needs Meta business verification; free tier
  exists but setup is heavy. Revisit once revenue > $0.
- **Local computer-control agent**: cloud Space cannot touch the laptop; needs
  a small local app that polls the Space for commands. Own project.
- **AI voice calls / phone answering**: paid telephony + robocall legality —
  out of scope until there's budget and a compliant use case.
- **Auto-apply bots (LinkedIn/Upwork/Fiverr)**: ToS violation, ban risk —
  permanently out; Job Radar (find + draft, human applies) is the compliant
  version.
- **Multi-user / mobile apps / enterprise scaling**: premature at $0 revenue;
  architecture (FastAPI + static Next) doesn't block it later.
- **Digital twin / business valuation simulations**: would be fabricated
  numbers at current data volume; revisit when there's real history to model.

## Design principles (unchanged)

- Real data or clearly-labeled absence — never fake numbers.
- Every automation degrades gracefully with a missing key.
- Additive API changes only; the dashboard contract stays stable.
- Verify (typecheck + build + TestClient + live probe) before every push.
