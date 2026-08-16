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

All are H.264 / AAC, 30fps, `+faststart`, with an original score and a
three-voice cast.

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
python marketing/PROJECT/audio_build.py vertical out.wav   # score + voices
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

`PROJECT/score2.py` synthesises the music from arithmetic — no library, no stock
bed — so every hit lands on the exact second of the cut it belongs to. 72 BPM,
D minor, progression Dm - Bb - F - C.

The first version was harmonically static: a sub, a pad, some ticks. It had
weight and no forward motion, and short-form retention research is blunt about
the cost — most drop-off happens in seconds 0-3 and the audio punch has to
arrive inside that window, not after a swell into one. v2 adds a hook in the
first half second, a 16th-note arpeggio for momentum, kick/hat/sub-drop
percussion, and stacked braam stabs on the refusals. The loudest event is the
impact on "$0"; the second loudest is the 0.55s of true silence before it.

### The voice cast

`PROJECT/voice.py`. No neural TTS was available: piper and kokoro install from
PyPI but their weights live on huggingface.co, which this session's egress
policy blocks. espeak-ng with MBROLA diphone voices from the Ubuntu archive was
available, and raw it sounds like a screen reader.

So it is not used raw. Titan is an AI command centre, and a *machine* voice is
on-brand rather than a compromise — the convention of MOTHER in Alien or TARS in
Interstellar. Three characters, each pitched, filtered and spaced differently:

- **TITAN** — the system. Low, wide, detuned against itself.
- **FOUNDER** — the human line. Closest to natural, dry, no doubling.
- **AGENT** — the refusals. Bandlimited like comms, hard-compressed.

`voice.duck()` pulls the music down under speech following the voice's own
envelope. `audio_build.py` asserts that no line overlaps another, that nothing
crosses the silence before the impact, and that nothing runs past the end — the
first pass had a line bleeding straight through that silence, so it is checked
rather than eyeballed.

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
