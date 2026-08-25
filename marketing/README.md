# TITAN Ω — "Trust the Zero"

Finished promotional films for Titan Omega, cut from the real product.

Nothing here is a mockup and nothing here is a generated dashboard. Every frame
is the actual Next.js front end talking to the actual FastAPI core, driven by a
headless browser. Every number on screen is whatever the running instance
reported at render time, and the three proof cards in the hero film are live
HTTP responses fetched from the backend while the film was being rendered.

## The films

| File | Format | Runtime | Use |
|---|---|---|---|
| `FINAL/Titan_Omega_Vertical_1080x1920.mp4` | 9:16, 1080×1920 | 18.0s | Reels · Shorts · TikTok |
| `FINAL/Titan_Omega_Hero_1920x1080.mp4` | 16:9, 1920×1080 | 32.3s | YouTube · site · investors |
| `FINAL/Titan_Omega_Square_1080x1080.mp4` | 1:1, 1080×1080 | 18.0s | Feed posts · LinkedIn |

All are H.264 / AAC, 30fps, `+faststart`, with an original score. They are
instrumental — see **The voice** below.

## The idea

Every AI product video opens on a metric going up. This one opens on a founder
saying his AI company has made nothing, pushes in on a revenue counter that
reads **$0 — First order incoming**, and then explains why that zero is the
product working correctly.

It is built on the rule the codebase already lives by: *no number is shown
unless it was measured.* Cost is `null`, not `$0.00`. An unaudited site reads
"not audited", never `0`. The forecaster refuses to project on thin data. That
rule is the only thing in this market a competitor cannot copy without
rebuilding their product, and it is the reason the film can survive a developer
opening the repo.

The hero film's middle act is three real refusals, fetched live:

- `409` — `ended → listening is not a legal transition`
- `GET /api/self-seo` — *"Titan has not audited itself yet"*, rather than a score
- `GET /api/apis/stats` — 1,675 catalogued, `adapters_written: 0`

## Rebuilding

Needs the backend on `:8000` and the front end on `:3000`.

```bash
cd backend  && python -m uvicorn app.main:app --port 8000
cd frontend && TITAN_API_URL=http://127.0.0.1:8000 npx next dev -p 3000

node marketing/PROJECT/render.mjs vertical /tmp/frames_v
node marketing/PROJECT/render.mjs hero     /tmp/frames_h
python marketing/PROJECT/score3.py vertical '{...beats...}' 18.0 out.wav
ffmpeg -framerate 30 -i /tmp/frames_v/f%05d.png -i out.wav ... out.mp4
```

`PROJECT/capture.mjs` captures all 15 tabs as stills at phone size.

### Why frames instead of screen recording

Playwright's real-time video recording was tried first and abandoned. It writes
variable-rate output, this page drops frames unevenly under software GL, and the
resulting drift between script time and video time is **non-linear** — a 32s
edit came out ~1.8s long, with the logo pushed past the fade. A single speed
correction cannot fix a non-linear stretch, and sync markers stamped into the
frame were lost at exactly the re-render boundaries where the drift was worst.

`render.mjs` poses the scene at `t = f/30` and screenshots it, so frame N *is*
time N/30. Picture and score cannot drift apart by construction, and a re-run
reproduces the same file. The cost is that the product's ambient 3D motion
advances in wall-clock time and so reads a little faster than life; on an 18
second cut that plays as energy.

### The score

`PROJECT/score3.py` synthesises the music from arithmetic — no library, no stock
bed — so every hit lands on the exact second of the cut it belongs to. 72 BPM,
D minor, progression Dm - Bb - F - C.

It went through three passes. v1 was harmonically static — a sub, a pad, some
ticks: weight with no forward motion, opening on a slow swell. Short-form
retention research is blunt about the cost, since most drop-off happens in
seconds 0-3 and the audio punch has to arrive inside that window rather than
build toward one. v2 added the hook in the first half second, a 16th-note
arpeggio for momentum, kick/hat/sub-drop percussion and braam stabs.

v3 is what ships, and it is built to carry the film alone: a lead melody across
the scale section so the track has something to remember, sidechain pumping so
the bed breathes on every kick instead of sitting still, a filter that opens
across each arpeggio section, reverse swells into every major hit, a deeper
braam, and tape saturation with bus glue on the master.

Measured on the finished masters: no clipped samples, and the drop jumps **68 dB
out of the silence** that precedes it, sitting within ~1 dB of the fullest
section — which is where the film's biggest moment belongs.

### The voice

**The shipped films are instrumental.** A voiceover was built and then cut,
because it was not good enough to keep and a bad voice is worse than no voice.
The captions are burned into the picture and carry every word, which is what
most feed views need anyway — they play muted.

Why it was not good enough: no neural TTS is reachable from the environment
these are built in. `api.elevenlabs.io`, `api.openai.com`, `api.deepgram.com`
and `huggingface.co` are all refused by its egress policy, there is no TTS key
in the environment, and piper/kokoro install from PyPI but keep their weights on
HuggingFace. What remained was espeak-ng with MBROLA diphone voices from the
Ubuntu archive — screen-reader quality, and no amount of pitching and filtering
fixes that. `PROJECT/voice.py` and `PROJECT/audio_build.py` remain in the repo
as the processing and timing rig; they are not used by the shipped cut.

**To add real voices**, run `PROJECT/elevenlabs_vo.py` anywhere that can reach
the API:

```bash
export ELEVENLABS_API_KEY=sk_...
python marketing/PROJECT/elevenlabs_vo.py --list      # your voices
python marketing/PROJECT/elevenlabs_vo.py --frames-v /tmp/frames_v \
                                          --frames-h /tmp/frames_h
```

It regenerates the voiceover and re-muxes all three films. The cast defaults to
Adam for the founder line — the same voice `backend/app/api/tts.py` already uses,
so the film and the product speak alike — Daniel for the system, and Domi for
the comms refusals. It re-asserts timing against the *real* clip lengths, since
neural voices are not the same length as the synthetic ones, and refuses to
build if a line would cross the silence before the impact.

## What is deliberately not in these films

Kept out because the product does not do it, or does not do it yet:

- **The CHANNELS rail.** Six CONNECT tiles with no OAuth behind them — hidden
  by the renderer before a single frame is shot.
- **The demo numbers.** `$693` revenue, `1.3K` traffic, `$4.2K` pipeline are
  the public demo's *sample data*. The films use the real founder view, which
  reads `$0`.
- **"102 agents are working right now."** 102 agent specs exist across 12
  divisions and the count is real; the handoff notes say they are mostly
  presentation, so the copy says *digital employees on the org chart*.
- **"1,675 APIs integrated."** 1,675 are catalogued, all `METADATA_ONLY`, with
  five capabilities wired by hand. The hero film says the ratio out loud.
- **"It fixes your website automatically."** `site_fix` has no auto-apply and
  `fix_cycle` never applies, by design.

## One thing worth fixing in the product

The Universe view's HTML labels do not reflow at 393px — `EXECUTIVE 8/9 ACTIVE`,
`$0 REVENUE` and `TRAFFIC` overlap the core into an unreadable pile. It is the
default view and the worst mobile frame in the app, which is why the films shoot
the Universe at desktop width and use the AI City on the phone.
