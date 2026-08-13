# Implementation report — god-tier transformation, session 1

Commits `557a0ea..ecaeb46`. Tests **304 → 338**. All deployed and verified live.

## Session 2 addendum — observability, backup/restore, retrieval

| Item | Before | After |
|---|---|---|
| Observability | **1/10** — zero request ids, zero structured logs | **7/10** — JSON logs, request id on every response incl. 401s, structural credential redaction |
| Backup / restore | **1/10** — export only, never tested | **7/10** — self-verifying backups, reversible restore, a test that destroys the DB and recovers it |
| Retrieval | 3/10 | **6/10** — root cause found and fixed, measured before/after |

**Retrieval, measured on the same corpus and questions:**

| | Before | After |
|---|---|---|
| hit@1 | 0.600 | **0.700** |
| hit@3 | 0.800 | 0.800 |
| MRR | 0.700 | **0.750** |
| silence (answerable, no result) | 2/10 | **0/10** |
| false answers (unanswerable, answered) | 1/5 | 1/5 |

The cause was not a threshold. `knowledge.backfill()` existed, had a unit test,
and was exposed as an endpoint — **nothing ever called it**. Passages ingested
while the embedding model was downloading kept no vectors and were never
re-embedded, so the whole semantic branch was dead code in production. That
also explains the old note that lowering the cosine threshold "changed nothing".

Wiring it up immediately broke something else, which the benchmark caught before
it shipped: false answers went 1/5 → 5/5, because `COS_FLOOR` was 0.52 while the
module's own comment records that sentence models score almost any two English
sentences 0.6–0.9. Recalibrated to 0.60 from measurement
(`evaluation/calibrate_cosine.py`).

**Mutation testing is now a repo tool** (`evaluation/mutation_check.py`, 22
guards). It found two tests that protected nothing — one asserted on a *comment*
rather than the code, one never exercised its branch. A scratch version of this
tool also left `if False:` inside `backup.py`'s verification gate after a run;
the permanent tool now verifies every restore byte-for-byte and aborts loudly.

This report follows the brief's §56 deliverables. **It is deliberately explicit
about what was NOT done**, because the brief's §57 rule 6 forbids claiming an
integration was implemented when it was only studied.

## A. What changed

| Change | Status |
|---|---|
| Forensic verification of the prior assessment (16 claims) | Done — `forensic_verification.md` |
| Research artifacts for all 5 supplied repositories | Done — 5 files + integration matrix |
| **Prompt-injection boundary** (`core/untrusted.py`) | **Done, deployed, mutation-tested** |
| Retrieval corpus-size defect | **Found and documented, NOT fixed** — see below |
| Baselines captured | Done |

## B. Research — decisions

| Repo | Decision | Deciding factor |
|---|---|---|
| VoiceStudio | **STUDY ONLY** | AGPL-3.0 network copyleft would force Titan's source open and destroy the commercial fork |
| AgentQL | **ADAPT, optional, off by default** | Hosted paid service: 50 calls/month free, then $0.02/call. Titan's 24/7 cycle would exhaust that in a day |
| NVIDIA NIM Anywhere | **ADAPT architecture / REJECT stack** | 1 GPU per model; Titan has no CUDA and one free CPU container |
| OpenRouter | **ADAPT, no new dependency** | `/models` pricing metadata is the honest route out of `cost: null` |
| Bytez | **DEFER** | Pricing, Python SDK and licence all unverified — a decision here would be a guess |

**Nothing was cloned into Titan.** Full reasoning in `integration_matrix.md`.

## C. Architecture change

Before: crawled page text → prompt string → model → spoken to a caller.

After: crawled page text → `untrusted.fence()` → nonce-delimited region, with
a system declaration that the region is data → model.

Four trust levels are now structurally distinct: SYSTEM / USER / CLIENT /
EXTERNAL.

## D. Security report

**Critical, fixed:** prompt injection from crawled sites into the voice agent's
prompt. Traced end to end at `router.py:1053` → `knowledge.py:386` →
`voice.py:193`. Closed by `core/untrusted.py`.

**High, still open:** no `tenant_id` on any resource. Isolation is enforced ad
hoc per endpoint via `billing.owned_clients(email)`. Correct where applied — I
verified and tested the fix-loop endpoints — but there is no structural
guarantee, and the brief's §13 asks for one.

**Honest limitation, stated in the product:** injection detection is heuristic.
`untrusted.stats()` says so in the text an operator reads, and a test asserts
that wording so it cannot be quietly upgraded to a guarantee.

## E. Database migration report

Already SQLite before this session (prior claim of "one JSON file" is **FALSE**
— see forensic verification). Migration 2 added the `jobs` table earlier today.
JSON retained as documented disaster-recovery export. **No backup/restore
tooling exists yet** — brief §12 is not done.

## F. Model routing report

**NOT IMPLEMENTED.** Researched only. The OpenRouter `/models` metadata route
to measured cost is designed and justified in `openrouter.md`, but no code was
written. Cost remains `null` everywhere, correctly.

## G. RAG evaluation

**No before/after numbers, because no benchmark was run.** What was produced is
better than a number: a *root cause*. `MIN_SCORE` is a fixed `0.8` while BM25
scores scale with corpus size via IDF, so a single-passage site scores ≈0.58 on
a two-term exact match and returns nothing. Masked in CI by the embedding model
finishing its download mid-suite. Captured as a test asserting current
behaviour. **Not tuned**, because changing a retrieval threshold without a
benchmark is the unmeasured claim this codebase refuses.

## H. Voice evaluation

**NOT DONE.** VoiceStudio was researched; the licence makes code reuse
impossible and the GPU/disk requirements make it operationally impossible on a
free Space. No voice code changed.

## I. Performance report

Not re-benchmarked. Test suite runtime is stable (116s → 114s across the
session, ±noise). No latency work attempted.

## J. Test report

| | Before session | After |
|---|---|---|
| Tests | 264 | **323** |
| Injection/security tests | 0 | 19 |
| Guards mutation-verified | 0 | **24** |

Mutation testing is the method used throughout: each guard removed, its test
confirmed to fail, then restored. A test that cannot fail proves nothing.

## K. Production readiness — scored per category, no single meaningless number

| Category | Score | Evidence |
|---|---|---|
| Durable state | 7/10 | SQLite + migrations + one-transaction saves. **Not durable on free tier** — rebuild wipes it |
| Backup / restore | **1/10** | Export exists; no restore tooling, no verification, never tested |
| Multi-tenancy | 4/10 | Enforced per endpoint and tested there; no `tenant_id`, no structural guarantee |
| AuthN / sessions | 8/10 | Signed, expiring, revocable, restart-proof |
| SSRF | 8/10 | Resolve-then-check, per-hop revalidation, in the renderer too |
| Rate limiting | 5/10 | Works; in-process only, dies at 2 containers |
| Prompt injection | 7/10 | Boundary shipped and tested; heuristic by nature, and says so |
| Durable execution | 7/10 | Real queue, leases, backoff. Single-process |
| Observability | **1/10** | Zero structured logs, zero request IDs |
| Payments | **0/10** | No processor connected. Nothing can be sold |
| Verification layer | **0/10** | Item 013 untouched |
| Retrieval | 3/10 | Known defect, root-caused, unfixed |
| Web intelligence | 7/10 | Shell detection live; renderer built, unhosted |
| Honesty / evidence | 9/10 | The strongest property. Two false-pass bugs found and fixed today |

**Titan is NOT production-ready.** The gates that fail: backup/restore,
observability, payments, verification layer, and durability on the current host.

## L. Remaining risks

1. **Nothing can be sold** — no payment processor.
2. **A rebuild wipes customer state**, including rollback snapshots for changes
   made to customers' live websites.
3. **No structural tenant isolation.**
4. **No observability** — a production incident would be undiagnosable.
5. **Retrieval is broken for small sites** and only partly masked by embeddings.
6. **No restore has ever been tested.** An untested backup is not a backup.
7. 102 declared agents remain a data table, not 102 behaviours.

## M. Next 10, ranked by (impact × risk reduction) ÷ cost

1. **Paddle keys** — blocks all revenue. Blocked on Abdullah.
2. **Structured logging + request IDs** — 1/10 category, cheap, unblocks everything else.
3. **Backup + restore + a restore TEST** — 1/10, and the scariest gap.
4. **`tenant_id` on every resource** + adversarial cross-tenant tests.
5. **Retrieval benchmark, then fix `MIN_SCORE`** — benchmark first, always.
6. **Verification layer (013)** — no LLM output reaches a customer unchecked.
7. **OpenRouter `/models`** → the first measured cost numbers.
8. **Host the renderer** — code is done; needs a container host.
9. **HF persistent storage** — makes durability real.
10. **Reranking stage** — after the benchmark exists to prove it.
