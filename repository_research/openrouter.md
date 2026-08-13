# OpenRouter ecosystem — research artifact

Source: https://github.com/OpenRouterTeam
Researched: 2026-08-13
**Research depth: organisation repository inventory and stated purposes.**

## 1. Purpose
A single API in front of 300+ models from many providers, with routing and
fallback handled upstream.

## 2. Architecture / inventory
| Repo | Language | Licence | Note |
|---|---|---|---|
| `python-sdk` | Python | Apache-2.0 | Official Python SDK |
| `typescript-sdk` | TS | Apache-2.0 | Official TS SDK |
| `go-sdk` | Go | Apache-2.0 | Official Go SDK |
| `python-agent` | Python | — | Agent SDK (very early, 4 stars) |
| `typescript-agent` | TS | — | Agent SDK (21 stars) |
| `ai-sdk-provider` | TS | Apache-2.0 | Vercel AI SDK provider (674 stars) |
| `benchmark-harness` | TS | — | **Reproducible LLM benchmarks** |
| `terraform-provider-openrouter` | Go | — | Keys, guardrails, workspaces as IaC |
| `openrouter-examples-python` | Python | — | Examples |

## 3. Important modules
The benchmark harness is the most interesting piece for Titan — it is about
*measuring* models rather than calling them.

## 4. Dependencies
The Python SDK is a thin HTTP client. Titan already calls OpenRouter directly
over `httpx` with no SDK.

## 5. APIs
OpenAI-compatible chat completions, plus a **models endpoint exposing per-model
metadata: context length, modality, and per-token pricing.** This is the single
most valuable thing here.

## 6. Useful abstractions
- **Model metadata as data, retrieved at runtime** rather than a hardcoded list.
  Titan's router can ask what exists, what it costs, and what context it has,
  instead of shipping a stale table.
- **Provider preference / fallback expressed declaratively** in the request.
- A benchmark harness as a separate, reproducible artifact.

## 7. Useful algorithms
Cost estimation from token counts × published per-token price. This is the one
honest route to a *measured* cost figure — Titan currently reports cost as
`null` everywhere because nothing has ever measured it.

## 8. Security implications
One key fans out to many upstream providers; data passes through OpenRouter.
Sensitive-tenant work should be routable away from it — which argues for
privacy as a routing input, as the brief specifies.

## 9. Licence
**Apache-2.0** on the official SDKs. Commercially safe.

## 10. Resource requirements
None beyond HTTP. Costs are per-token and metered.

## 11. Production limitations
An outage is a single point of failure if it becomes the only provider; Titan
already has Groq and Gemini alongside it, which is the right shape.

## 12. Relevant code patterns
Runtime model discovery; declarative fallback; per-token pricing metadata.

## 13. Titan integration opportunities — highest value of the five repos
1. **Runtime model discovery + pricing metadata** feeding a real cost figure.
   This directly unlocks the `cost: null` fields without inventing a number.
2. **Capability metadata** (context length, modality) as router input, replacing
   a hardcoded ranking with measured capability.
3. A benchmark harness pattern for the model-scoring engine in §8 of the brief.

## 14. Titan incompatibilities
None material. Adding the SDK is unnecessary — Titan already speaks the API
over `httpx`, and a new dependency for HTTP calls it already makes would fail
the dependency-discipline rule.

## 15. Recommendation
**ADAPT — no new dependency.**
Consume the `/models` metadata endpoint directly over the existing `httpx`
client to drive model discovery, capability-aware routing and, importantly, the
first genuinely *measured* cost numbers in the product. Do not vendor the SDK.
Do not adopt the agent SDKs (4 and 21 stars; too early for a commercial
dependency).
