# Master spec — what is built, what is blocked, what is next

Tracks `TITAN OMEGA MASTER SPEC.md` against the codebase. Updated 2026-08-05.

Rule for this file: a row is only **Built** when it has been run and verified,
not when code exists.

---

## Part 8 — Repository research (licence gate)

Measured from the GitHub API on 2026-08-05. Licence decides integration mode,
so this gates everything else.

| Repo | Licence | Mode | Verdict |
|---|---|---|---|
| firecrawl/firecrawl | AGPL-3.0 | **wrap** | HTTP only. Embedding forces Titan's source open — Titan is sold. |
| MervinPraison/PraisonAI | MIT | embed | Safe. Not installed; benchmark before adopting. |
| livekit/agents | Apache-2.0 | embed | Safe, needs NOTICE. Voice transport only — calling needs paid telephony. |
| open-jarvis/OpenJarvis | Apache-2.0 | embed | Safe, needs NOTICE. |
| rmyndharis/OpenWA | MIT | embed | Safe. Ban risk — outbound-gated. |
| jamiepine/voicebox | MIT | embed | Safe. |
| floci-io/floci | MIT | embed | Safe. |
| trycompai/crm | MIT | embed | Safe. Titan already has CRM-lite; adapter is for clients who already run one. |
| TencentDB-Agent-Memory | NOASSERTION | **blocked** | No licence grant. Refuses to run until upstream states terms. |
| ripienaar/free-for-dev | none | refer | Read it; cannot redistribute. |
| awesome-selfhosted | NOASSERTION | refer | Read it; cannot redistribute. |

Kimi Browser Assistant is a Chrome Web Store extension with no public source.
Ideas only — there is nothing to licence-check or integrate.

---

## Built and verified

| Spec | What | Evidence |
|---|---|---|
| P2 L4, P7, P8 | Tool layer + adapters + licence gate | 60 tests; live `/api/tools` → 1 ready, 5 not_configured, 1 licence_blocked |
| P2, P7 | Typed event bus, bounded trace, isolated subscribers | `/api/events`; failing-subscriber test |
| P4A | CRM + lead→won funnel by stage reached | live API 4/3/2/1, 25% conversion |
| P4B | SEO engine: technical + local + legal, per client | live audit of a real site, 72/C |
| P4B | Compliance: 9 jurisdictions, Impressum/§5 DDG | jurisdiction bug fixed + regression tests |
| P4C | 24/7 monitoring with regression diffing | baseline + no-change paths verified |
| P6 | Measured model routing + per-provider profiling | live `/api/routing`; real 401 recorded, 4 ModelFailed events |
| P2 | Planning engine — plan before execute | live `/api/plan`; blocked steps named, review precedes send |
| P2 | Typed event bus + bounded trace | `/api/events`; failing-subscriber isolation test |
| P2 | Planning engine — plan before execute | `/api/plan`; blocked steps named |
| P2 | Self-reflection with estimate calibration | loop closed live: 3.5s -> 10.5s estimate |
| P4C | BI period reports + forecasting | `/api/bi/{period}`; refuses to project on thin data |
| P4C/P6 | Executive dashboard view | 13th tab, live |
| P5B | Signup + Free/Student/Individual/Enterprise | `/pricing` live; quota refusals explain themselves |
| P6 | Measured model routing + profiling | live: groq 5 calls, 100% success recorded |
| P3 | PWA — installable on Android/iOS/Windows | service worker active, manifest valid |
| P3 | HTTPS enforced + full security headers | http 301s; HSTS/CSP/nosniff verified live |
| P8 | Tool layer + adapters + licence gate | `/api/tools`; AGPL wrap-only enforced by test |
| P3 | 3D command centre, 13 views | running |

## Blocked on Abdullah — not on engineering

| Need | Why | Unblocks |
|---|---|---|
| Telephony account (Twilio/Vapi/Retell) + number | Paid, per-minute, must be in his name | The calling agent from the reference reel |
| Firecrawl instance (self-host in `D:\stacks\` or cloud key) | AGPL — must stay a separate process | JS-rendered crawling, clean markdown |
| Decision on PraisonAI | Heavy dep; boot time cost | Multi-agent orchestration |
| Upstream licence for TencentDB-Agent-Memory | No grant exists today | External long-term memory |
| A walkthrough recording of **Titan itself** | The clip supplied was a competitor's Reel | The spec's mandated project analysis |

## Not started

Marketplace, plugin SDK, mobile/desktop clients, SSO, forecasting, prompt
library, self-reflection loop. Each is real work; none of it earns money before
the German restaurant client is onboarded.

---

## The `HELLO ABDULLAH BOSS` conflict

Spec Part 3 specifies that startup message. Abdullah's standing instruction is
to be addressed as **Abdullah, never Boss**, and "Boss" appears nowhere in the
codebase. The spec line is wrong and should be struck, or a future session will
reintroduce it.

---

## Live deployment (verified 2026-08-06)

**https://titanomega-ai.com** — Cloudflare Worker reverse-proxy in front of the
Hugging Face Space. HF's own custom-domain feature is PRO-only ($9/mo, ~2x the
annual budget), so the Worker does the same job on the free plan.

Verified: 12/12 endpoint checks pass; SSL valid; Server-Sent Events stream
through the proxy (8 events over 11.9s, first at 1.4s — a buffering proxy would
have delivered them in one lump at disconnect); service worker registers and is
active; manifest serves with all 3 icons; the deployed bundle contains the SEO
view, the lead funnel and the legal-separation copy.

Worker source: `deploy/cloudflare-worker.js`, config `wrangler.toml`.
Deploys automatically on push to main via the connected repo.

**Outstanding:** `www.titanomega-ai.com` has no DNS record. A Worker *Route*
(`*.titanomega-ai.com/*`) does not create DNS — routes only match traffic that
already arrives. Needs a proxied CNAME `www -> titanomega-ai.com` added by hand
in the Cloudflare DNS tab; the Worker already handles the www->apex redirect.
