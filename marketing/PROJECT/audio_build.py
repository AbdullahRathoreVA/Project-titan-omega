"""Titan Ω — final audio: score v2 + a three-voice cast, ducked and mastered.

    python audio_build.py vertical out.wav
    python audio_build.py hero     out.wav
"""

from __future__ import annotations

import sys

import numpy as np

import score2
import voice

SR = score2.SR

BEATS = {
    "vertical": {"boot": 1.70, "cut": 4.90, "zero": 6.50, "proof": 10.40,
                 "city": 12.40, "black": 15.00, "mark": 15.35, "end": 18.00},
    "hero": {"boot": 2.45, "cut": 8.78, "zero": 10.65, "r1": 14.35, "r2": 16.95,
             "r3": 19.55, "city": 21.90, "black": 29.38, "mark": 29.82, "end": 32.30},
}
DUR = {"vertical": 18.0, "hero": 32.3}

# (start seconds, voice, line). Kept sparse on purpose: the captions already
# carry the words for muted viewing, so the voice is there to add weight and a
# second character, not to read the screen aloud.
LINES = {
    "vertical": [
        (0.30, "FOUNDER", "My A.I. company has made zero dollars."),
        (2.70, "TITAN",   "One hundred two agents."),
        (7.10, "TITAN",   "Revenue. Zero."),
        (9.10, "FOUNDER", "It could have shown any number I wanted."),
        (11.50, "TITAN",  "Nothing is shown unless it was measured."),
        (15.05, "TITAN",  "Titan Omega. Trust the zero."),
    ],
    "hero": [
        (0.45, "FOUNDER", "My A.I. company has made zero dollars."),
        (3.30, "TITAN",   "One hundred two digital employees. Twelve divisions."),
        (7.50, "FOUNDER", "So I checked what it had earned."),
        (11.25, "TITAN",  "Revenue. Zero. Measured."),
        (14.40, "AGENT",  "Refused. Four zero nine."),
        (17.00, "AGENT",  "No score. It has not audited itself."),
        # Colons make espeak insert a long pause; the punctuated version ran
        # 3.46s and collided with the next line.
        (19.62, "AGENT",  "Sixteen seventy five catalogued. Five wired."),
        (22.60, "TITAN",  "Every number here was measured."),
        (26.90, "FOUNDER", "It hasn't earned anything yet."),
        (29.85, "TITAN",  "Trust the zero."),
    ],
}

# The pause before the "$0" impact is the strongest moment in either film. A
# voice line bleeding across it destroys the effect, and that is exactly what
# happened on the first pass — so it is asserted rather than eyeballed.
def check(kind, spans):
    beats, problems = BEATS[kind], []
    quiet = (beats["zero"] - 0.58, beats["zero"])
    for (s0, e0, w0, t0) in spans:
        if s0 < quiet[1] and e0 > quiet[0]:
            problems.append(f"{w0} at {s0:.2f}s runs to {e0:.2f}s, crossing the "
                            f"silence {quiet[0]:.2f}-{quiet[1]:.2f}s: {t0[:40]}")
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0] + 0.01:
            problems.append(f"{a[2]} at {a[0]:.2f}s overlaps {b[2]} at {b[0]:.2f}s "
                            f"by {a[1] - b[0]:.2f}s")
    last = spans[-1]
    if last[1] > DUR[kind] + 0.05:
        problems.append(f"{last[2]} runs {last[1] - DUR[kind]:.2f}s past the end")
    return problems


def build(kind: str) -> np.ndarray:
    dur = DUR[kind]
    beats = BEATS[kind]
    n = int(dur * SR)

    music = score2.build(kind, beats, dur)
    music = np.pad(music, (0, max(0, n - len(music))))[:n]

    vo = np.zeros(n)
    spans = []
    for start, who, text in LINES[kind]:
        clip = voice.say(text, who)
        spans.append((start, start + len(clip) / SR, who, text))
        i = int(start * SR)
        if i >= n:
            continue
        seg = clip[: n - i]
        # A short fade on each end stops the espeak boundary from clicking.
        f = min(int(0.012 * SR), len(seg) // 4)
        if f > 0:
            seg = seg.copy()
            seg[:f] *= np.linspace(0, 1, f)
            seg[-f:] *= np.linspace(1, 0, f)
        gain = {"FOUNDER": 1.0, "TITAN": 0.92, "AGENT": 0.88}[who]
        vo[i : i + len(seg)] += seg * gain
        print(f"  {start:5.2f}s {who:<8} {len(clip)/SR:4.2f}s  {text[:52]}")

    for p in check(kind, spans):
        raise SystemExit(f"VO TIMING: {p}")

    # The voice must never fight the sub — duck the bed under it.
    ducked = voice.duck(music, vo, depth=0.52)

    # Voice sits slightly forward of centre-mono music; keep it dry-centre.
    mixed = ducked + vo * 0.72
    st = score2.master_bus(mixed)

    # Report headroom so a clipped master cannot ship unnoticed.
    peak = np.abs(st).max()
    print(f"  peak {peak:.3f}  clipped {int((np.abs(st) > 0.999).sum())}")
    return st


if __name__ == "__main__":
    kind, out = sys.argv[1], sys.argv[2]
    print(f"building {kind} audio")
    score2.write(out, build(kind))
    print(f"-> {out}")
