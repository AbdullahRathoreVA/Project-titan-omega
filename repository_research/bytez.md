# Bytez — research artifact

Source: https://github.com/Bytez-com/docs
Researched: 2026-08-13
**Research depth: repository documentation landing page only. Pricing and the
Python SDK surface were NOT verifiable from the material available, and are
marked UNVERIFIED below rather than guessed.**

## 1. Purpose
Serverless model inference API — "the largest serverless Model Inference API on
the internet". Claims 175k+ models across 33 ML tasks, plus 440k+ interactive
papers.

## 2. Architecture
Hosted serverless inference behind one API key. No local component.

## 3. Important modules
`bytez.js` (NPM) is the documented SDK. **A Python SDK was not confirmed** in
the material reviewed — this matters, because Titan's backend is Python.

## 4. Dependencies
HTTP + an API key.

## 5. APIs
Model inference with streaming, "3 lines of code" per the docs. Exact request
and response schemas were not verified.

## 6. Useful abstractions
Very wide model catalogue behind a single key, including many tasks a
general-purpose provider does not expose (classification, reranking, and other
non-chat heads). If real, that is a cheap source of a **reranking model** for
RAG 2.0 without hosting one.

## 7. Useful algorithms
None inspected.

## 8. Security implications
Same as any hosted inference provider: prompt and document content leave
Titan's infrastructure.

## 9. Licence
**Not verified.** The repo is documentation; individual model licences vary and
are not enumerated. Any commercial use would need this checked per model.

## 10. Resource requirements
None locally. Cost model **UNVERIFIED** — no pricing was published on the page
reviewed. There is a $200,000 free-inference grant programme for startups,
which is a marketing programme, not a pricing tier.

## 11. Production limitations
Unknown pricing, unconfirmed Python SDK, unknown SLA, unknown rate limits.
Three unknowns is too many to put on a customer-facing path.

## 12. Relevant code patterns
Single-key multi-model access — a pattern Titan already has via OpenRouter.

## 13. Titan integration opportunities
Only one that is not already covered by OpenRouter: access to **non-chat model
heads**, specifically a cross-encoder reranker for the retrieval pipeline. That
is worth revisiting *if* pricing and a Python path are confirmed.

## 14. Titan incompatibilities
Duplicates OpenRouter's role as a multi-model gateway. Adding a second gateway
that does the same job increases attack surface, key management and maintenance
for no measured gain — which fails the brief's own dependency-discipline rule.

## 15. Recommendation
**STUDY / DEFER.**
Do not integrate now. The brief is explicit: "Do not introduce Bytez merely
because it offers another provider." It does not currently offer Titan anything
OpenRouter does not, and three material facts (pricing, Python SDK, licence)
could not be verified. Revisit only if a reranker is needed and Bytez is
confirmed to be the cheapest verified route to one.

**Honest note:** research on Bytez is thinner than on the other four. I did not
have enough verified material to make a confident ADOPT/REJECT call, so the
recommendation is DEFER rather than a decision dressed up as one.
