# VoiceStudio — research artifact

Source: https://github.com/debpalash/VoiceStudio
Researched: 2026-08-13
**Research depth: documentation and repository metadata, not a full source audit.**
Stated here so nothing below is mistaken for a line-by-line review.

## 1. Purpose
Local-first desktop voice studio — voice cloning, dubbing, audiobooks,
transcription, dictation. Positioned as a self-hosted alternative to ElevenLabs.

## 2. Architecture
Three layers: a Tauri v2 (Rust) desktop shell, a React/Vite frontend, and a
**FastAPI Python sidecar on localhost:3900** with SQLite + Alembic migrations,
SSE/WebSocket streaming and 100+ REST endpoints.

## 3. Important modules
TTS engine registry (14 engines), STT engine registry (11 engines), a streaming
WebSocket TTS path that chunks by sentence, a live-dictation streaming ASR path,
Demucs for source separation, Pyannote for diarization, AudioSeal watermarking.

## 4. Dependencies
Python 3.10+ managed by `uv`; WhisperX, Faster-Whisper, CosyVoice, GPT-SoVITS,
sherpa-onnx, MLX-audio, PyTorch, CTranslate2, Demucs, Pyannote. Heavy.

## 5. APIs
OpenAI-compatible `/v1/audio/speech` and `/v1/audio/transcriptions`, plus
VoiceStudio-specific extensions. Bearer auth for remote backends.

## 6. Useful abstractions  ← the actual value to Titan
- **Engine registry with explicit capability declaration per engine.** Titan's
  `STTProvider`/`TTSProvider` abstraction should look like this.
- **Refusal to fall back silently.** "Engine routing refuses silent CPU
  fallback; incompatible engines error explicitly." This is precisely Titan's
  own never-pretend rule, independently arrived at, and is worth copying as a
  *principle*.
- **Sentence-chunked streaming TTS over WebSocket** — the right shape for
  Titan's voice OS, which currently uses browser Web Speech only.
- **Frontend able to point at a remote backend with bearer auth** — the same
  split Titan needs between the Space and a voice worker.

## 7. Useful algorithms
Sentence-boundary chunking for unbounded-length streaming synthesis.

## 8. Security implications
Local-first, no API keys required for the core path. A remote backend is bearer
authenticated. Nothing alarming; but see licence.

## 9. Licence — **THE DECIDING FACTOR**
**AGPL-3.0, with the network copyleft clause.** Modified versions offered over
a network must publish source under AGPL-3.0. Commercial closed-source
embedding requires a separate proprietary licence from the author (pricing not
yet published).

Titan Omega is a commercial product **served over a network**, and has a
private commercial fork (`titan-omega-infinity`). Incorporating any AGPL-3.0
code would compel Titan's own source under AGPL-3.0 and destroy that fork.

## 10. Resource requirements
8 GB RAM minimum / 16 GB recommended; 4 GB VRAM minimum / 8 GB recommended;
10–20 GB disk. GPU strongly preferred (CPU ~3× slower for TTS).

## 11. Production limitations for Titan
Titan runs on a free Hugging Face Space: CPU-only, no GPU, **ephemeral disk**.
A 10–20 GB model cache would not survive a rebuild even if it fitted. This is
operationally incompatible with the current deployment, independent of licence.

## 12. Relevant code patterns
Capability-declaring engine registry; explicit-failure routing; sentence-chunked
streaming; OpenAI-compatible audio endpoints as a portability seam.

## 13. Titan integration opportunities
Architecture only: shape `STTProvider`/`TTSProvider` after the engine registry,
adopt the explicit-failure rule, and expose OpenAI-compatible audio endpoints so
any future engine drops in.

## 14. Titan incompatibilities
Licence (fatal for code reuse), GPU/RAM/disk requirements, Tauri desktop shell
irrelevant to a web platform.

## 15. Recommendation
**STUDY ONLY.** Do not copy, vendor, clone, or depend on any VoiceStudio code.
Reimplement the two good ideas — capability-declaring provider registry and
never-fall-back-silently — as original Titan code. Both are ideas, not
expression, and are not covered by copyright.
