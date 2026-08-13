# NVIDIA NIM Anywhere — research artifact

Source: https://github.com/NVIDIA/nim-anywhere
Researched: 2026-08-13
**Research depth: repository documentation and architecture description.**

## 1. Purpose
A reference implementation of a production RAG stack built on NVIDIA NIM
inference microservices.

## 2. Architecture
Service-oriented, not a library:
`Chain Server (LangChain)` → `Milvus` (vector store) + `Redis` (conversation
state) → `NIM microservices` (LLM, embedding, reranking, each in its own
container).

## 3. Important modules
Chain server orchestration, document ingestion notebooks, evaluation tooling,
configuration management, service boundaries between retrieval and generation.

## 4. Dependencies
Milvus, Redis, Docker, NVIDIA AI Workbench, LangChain, NIM containers.

## 5. APIs
NIM containers expose OpenAI-compatible inference endpoints — which is the
portability lesson: the whole stack is swappable behind one API shape.

## 6. Useful abstractions  ← the actual value to Titan
- **Retrieval is a pipeline of separable stages**, not one function: ingest →
  embed → store → retrieve → **rerank** → generate. Titan currently does BM25
  and stops; the missing stage is reranking.
- **Model serving is a separate concern from model choice.** Everything talks
  OpenAI-shaped HTTP, so an embedding model can be swapped without touching
  the chain.
- **Evaluation is a first-class component**, not an afterthought. There is
  tooling to measure retrieval quality as part of the system.

## 7. Useful algorithms
Two-stage retrieve-then-rerank; conversation state kept outside the model.

## 8. Security implications
Standard service-mesh concerns. Nothing directly transferable.

## 9. Licence
**Apache-2.0** — permissive and commercially safe, unlike VoiceStudio.

## 10. Resource requirements — **THE DECIDING FACTOR**
Local inference needs **one dedicated GPU per NIM**: 1 GPU for LLM only, 2 with
embeddings, 3 with reranking. Ubuntu 22.04 for remote deployment. A GPU-free
path exists but only by calling NVIDIA's **hosted** ai.nvidia.com endpoints.

Titan's machine is an i5-1135G7 with **Intel Iris Xe and no CUDA**, deploying
to a free CPU-only Hugging Face Space. Milvus and Redis alone would not fit the
deployment model, let alone three GPUs.

## 11. Production limitations for Titan
Every component is an additional container to run and pay for. Titan's entire
constraint is that it must stay on one free container.

## 12. Relevant code patterns
Staged retrieval pipeline; OpenAI-shaped provider seam; built-in evaluation.

## 13. Titan integration opportunities
Architecture only, and it maps cleanly onto a real measured Titan defect:
retrieval is **2/4 on natural questions**, and the recorded finding is that
lowering the cosine threshold changed nothing — meaning the next lever is
**better chunking and a reranking stage**, which is exactly the stage this
architecture separates out. A reranker can be implemented as a pure-Python
scoring pass over BM25 candidates with no new service.

## 14. Titan incompatibilities
Milvus, Redis, Docker-compose topology, and GPU-per-model economics.

## 15. Recommendation
**ADAPT (architecture) / REJECT (stack).**
Take the staged retrieve→rerank→generate pipeline and the
evaluation-as-a-component idea. Implement reranking in-process against the
existing BM25 candidates. Do **not** install Milvus, Redis, or any NIM
container. Keep an optional `NVIDIAProvider` behind a feature flag that targets
the *hosted* endpoints, so a GPU path exists later without a GPU today.
