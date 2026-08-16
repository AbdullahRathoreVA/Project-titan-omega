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

All are H.264 / AAC, 30fps, `+faststart`, with an original score.

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
python marketing/PROJECT/score.py vertical '{...beats...}' 18.0 out.wav
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

`PROJECT/score.py` synthesises the music and sound design from arithmetic —
there is no library and no stock bed, so every hit is placed on the exact second
of the cut it belongs to. 72 BPM, D minor. A 41 Hz sub carries the weight, a
detuned pad carries the harmony, and the UI ticks stand in for the product's own
`chime()`/`blip()`. The loudest event is the impact on "$0"; the second loudest
is the 0.55s of true silence immediately before it.

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
