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
| P3 | 3D command centre, 12 views | running |

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
library, model profiling. Each is real work; none of it earns money before the
German restaurant client is onboarded.

---

## The `HELLO ABDULLAH BOSS` conflict

Spec Part 3 specifies that startup message. Abdullah's standing instruction is
to be addressed as **Abdullah, never Boss**, and "Boss" appears nowhere in the
codebase. The spec line is wrong and should be struck, or a future session will
reintroduce it.
