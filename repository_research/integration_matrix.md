# Integration matrix

Decisions for the five external repositories supplied, made against Titan's
actual constraints: **$0 capital, pre-revenue, one free CPU-only container with
an ephemeral disk, no CUDA, and a private commercial fork that must stay
closed-source.**

Researched 2026-08-13. Research depth is stated in each per-repository artifact;
none of these is a line-by-line source audit, and nothing below is presented as
if it were.

| Repository | Capability | Titan need | Possible integration | Expected benefit | Complexity | Cost | Risk | Licence | Decision |
|---|---|---|---|---|---|---|---|---|---|
| **VoiceStudio** | Local STT/TTS, streaming, engine registry | Voice OS is browser Web Speech only | Reimplement the *pattern*: capability-declaring provider registry, never-fall-back-silently | Provider-swappable voice; honest failures | Medium | $0 (pattern) | **Licence-fatal if code copied** | **AGPL-3.0 + network copyleft** | **STUDY ONLY** |
| **AgentQL** | NL selectors, self-healing structured extraction | Extracting *variable* per-site data (menus, catalogues, hours) | Optional, feature-flagged, per-tenant adapter, off by default | Structured extraction regex cannot generalise | Low | **50 calls/mo free, then $0.02/call, or $99/mo** | Metered cost on a pre-revenue product; client page content egress | MIT (SDK) — but paid hosted service | **ADAPT — optional, off by default** |
| **NVIDIA NIM Anywhere** | Service-oriented RAG, rerank stage, eval tooling | Retrieval measured at **2/4**; no rerank stage | Take the staged retrieve→rerank→generate architecture; implement rerank in-process | Directly targets the measured retrieval defect | Medium | $0 (architecture) | None if stack rejected | Apache-2.0 | **ADAPT architecture / REJECT stack** |
| **OpenRouter** | 300+ models, runtime model + **pricing metadata** | Router is a hardcoded ranking; cost is `null` everywhere | Consume `/models` over existing `httpx` — no SDK | Capability-aware routing and the **first measured cost figures** | Low | $0 to read metadata | Low | Apache-2.0 | **ADAPT — no new dependency** |
| **Bytez** | 175k models, non-chat heads | Possibly a cheap reranker | None yet | Unclear | — | **UNVERIFIED** | Pricing, Python SDK and licence all unverified | Not verified | **DEFER** |

## Why nothing is being cloned into Titan

The brief forbids "dumping entire repositories into Titan" and "adding
dependencies simply to claim integration". Applying that honestly:

- **VoiceStudio cannot be copied at all.** AGPL-3.0's network clause would
  compel Titan's own source open. That is not a preference, it is a licence
  term, and it would destroy `titan-omega-infinity`. Ideas are not copyrightable;
  the two worth taking are reimplemented as original code.
- **AgentQL is a paid hosted service wearing an MIT SDK.** Cloning the repo
  gains nothing without a key, and the free tier (50 calls/month) is smaller
  than a single day of Titan's 24/7 cycle. Titan already solved the
  JS-rendering problem for $0 with its own `services/renderer/`. AgentQL solves
  a different problem Titan has no paying customer for yet.
- **NIM Anywhere's value is its shape, not its containers.** Milvus + Redis +
  one GPU per model is the opposite of a free CPU container.
- **OpenRouter's SDK would be a new dependency for HTTP calls Titan already
  makes.** The metadata endpoint is the valuable part and needs no package.
- **Bytez has three unverified facts.** A decision made on unverified pricing
  would be exactly the kind of confident guess this codebase refuses.

## What this research actually changed

1. **AgentQL is not the answer to the JS blind spot** — `services/renderer/`
   already is, at $0. That was worth establishing before spending money.
2. **OpenRouter's pricing metadata is the honest route out of `cost: null`.**
   Highest-value, lowest-cost item found.
3. **The rerank stage is the named next lever for retrieval**, matching the
   independently measured 2/4 result and the recorded finding that lowering the
   cosine threshold changed nothing.
4. **VoiceStudio's "refuses silent CPU fallback" is the same principle Titan
   already enforces** — independent convergence, worth noting as validation.
