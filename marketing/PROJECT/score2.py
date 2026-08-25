"""Titan Ω — score v2.

The first score was harmonically static: a sub, a pad, some ticks. It had
weight and no forward motion, which is why it read as ambience rather than
music. Research on short-form retention is blunt about the cost — most drop-off
happens in seconds 0-3, and the audio punch has to arrive inside that window,
not after a slow fade-in.

What changed:

  * A hook in the first half second, not a swell into one.
  * A real progression — Dm · Bb · F · C, the tension/resolution cycle the film
    actually follows — instead of one held chord.
  * A 16th-note arpeggio carrying momentum under everything.
  * Percussion: kick, sub-drop, a hat pattern, and rim ticks on the grid.
  * Braam-style stacked brass stabs for the refusals.
  * Risers that sweep pitch, filter and amplitude together rather than just
    getting louder.
  * The silence before "$0" is kept, and now it means something because there
    is something to take away.

72 BPM, D minor. One bar = 3.333s, one 16th = 0.2083s.
"""

from __future__ import annotations

import json
import sys
import wave

import numpy as np

SR = 48_000
BPM = 72.0
BEAT = 60.0 / BPM
BAR = BEAT * 4
S16 = BEAT / 4

N = {"D2": 73.42, "F2": 87.31, "A2": 110.00, "Bb2": 116.54, "C3": 130.81,
     "D3": 146.83, "F3": 174.61, "G3": 196.00, "A3": 220.00, "Bb3": 233.08,
     "C4": 261.63, "D4": 293.66, "F4": 349.23, "A4": 440.00, "D5": 587.33}

# Dm · Bb · F · C — minor home, lift, release, turnaround.
PROG = [
    [N["D3"], N["F3"], N["A3"]],
    [N["Bb2"], N["D3"], N["F3"]],
    [N["F2"], N["A2"], N["C3"]],
    [N["C3"], N["F3"], N["G3"]],
]


def _t(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def env(n: int, a: float, d: float, curve: float = 2.5) -> np.ndarray:
    t = _t(n)
    return np.clip(t / max(a, 1e-6), 0, 1) * np.exp(-t / max(d, 1e-6)) ** (1 / curve)


def saw(f: float, dur: float, detune: float = 0.006, voices: int = 3) -> np.ndarray:
    """Band-limited-ish saw stack. Additive, so it never aliases into fizz."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for v in range(voices):
        fv = f * (1 + detune * (v - (voices - 1) / 2))
        for h in range(1, 15):
            if fv * h > 15000:
                break
            out += np.sin(2 * np.pi * fv * h * t) / h
    return out / (voices * 2.2)


def pluck(f: float, dur: float, amp: float) -> np.ndarray:
    """Arp voice: short, bright, decaying. This is the momentum."""
    n = int(dur * SR)
    t = _t(n)
    sig = (np.sin(2 * np.pi * f * t)
           + 0.5 * np.sin(2 * np.pi * f * 2 * t)
           + 0.25 * np.sin(2 * np.pi * f * 3 * t)
           + 0.12 * np.sin(2 * np.pi * f * 4.02 * t))
    return amp * sig * env(n, 0.002, 0.10)


def pad(freqs, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    rng = np.random.default_rng(7)
    for f in freqs:
        for k, det in enumerate((-0.005, 0.0, 0.006)):
            lfo = 1 + 0.0018 * np.sin(2 * np.pi * (0.06 + 0.03 * k) * t + rng.random() * 6)
            out += np.sin(2 * np.pi * f * (1 + det) * t * lfo) / (len(freqs) * 3)
            out += 0.2 * np.sin(2 * np.pi * 2 * f * (1 + det) * t) / (len(freqs) * 3)
    # Slow swell so pads breathe in rather than switch on.
    return amp * out * np.clip(t / 0.5, 0, 1)


def braam(root: float, dur: float, amp: float) -> np.ndarray:
    """The trailer brass stab. Stacked fifths/octaves, hard attack, a little
    pitch fall, distorted — the sound of a door closing on a refusal."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for mult, g in ((0.5, 1.0), (1.0, 0.9), (1.5, 0.5), (2.0, 0.45), (3.0, 0.2)):
        f = root * mult * (1 + 0.03 * np.exp(-t / 0.12))
        ph = 2 * np.pi * np.cumsum(f) / SR
        out += g * (np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph))
    out /= 4.0
    out = np.tanh(out * 2.2)
    return amp * out * env(n, 0.012, dur * 0.42, 1.8)


def kick(dur: float, amp: float, f0: float = 120, f1: float = 42) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.0012, 0.20, 1.6)
    click = np.random.default_rng(5).standard_normal(n) * np.exp(-t / 0.004) * 0.25
    return amp * (body + click)


def subdrop(dur: float, amp: float) -> np.ndarray:
    """The impact. Sub sine falling from 70Hz to 28Hz with a long tail."""
    n = int(dur * SR)
    t = _t(n)
    f = 28 + 42 * np.exp(-t / 0.22)
    return amp * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, dur * 0.5, 1.4)


def hat(dur: float, amp: float, bright: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(int(bright * 977) % 4096)
    x = rng.standard_normal(n)
    # crude high-pass: subtract a moving average
    k = 12
    x = x - np.convolve(x, np.ones(k) / k, mode="same")
    return amp * x * env(n, 0.0005, 0.03 * bright, 1.2)


def riser(dur: float, amp: float, f0: float = 180, f1: float = 6500) -> np.ndarray:
    """Pitch, brightness and level all climb together — one moving parameter
    reads as a fade, three read as tension."""
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(11)
    out = np.zeros(n)
    for _ in range(28):
        f = f0 * (f1 / f0) ** ((t / max(dur, 1e-6)) ** 1.35) * (0.7 + 0.6 * rng.random())
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6)
    out /= 28
    tone = np.sin(2 * np.pi * np.cumsum(N["D3"] * (1 + 0.5 * (t / dur) ** 2)) / SR) * 0.35
    return amp * (out + tone) * (t / dur) ** 2.0


def whoosh(dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(3)
    out = np.zeros(n)
    for _ in range(20):
        f = 800 * (1 + 3.6 * np.sin(np.pi * t / dur)) * (0.55 + rng.random())
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6)
    return amp * (out / 20) * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5


def bell(f: float, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for m, a, d in ((1.0, 1.0, 2.8), (2.01, 0.34, 1.5), (3.02, 0.15, 0.9), (4.9, 0.06, 0.5)):
        out += a * np.sin(2 * np.pi * f * m * t) * np.exp(-t / d)
    return amp * (out / 1.6) * np.clip(t / 0.012, 0, 1)


def reverb(x: np.ndarray, decay: float = 2.2, mix: float = 0.26) -> np.ndarray:
    n = int(decay * SR)
    rng = np.random.default_rng(23)
    ir = rng.standard_normal(n) * np.exp(-_t(n) / (decay / 4.2))
    ir[0] = 1.0
    ir /= np.abs(ir).sum() / 6
    return (1 - mix) * x + mix * np.convolve(x, ir)[: len(x)]


class Mix:
    def __init__(self, dur: float):
        self.n = int(dur * SR)
        self.buf = np.zeros(self.n)

    def at(self, sec: float, x: np.ndarray, g: float = 1.0):
        i = int(sec * SR)
        if i >= self.n:
            return
        if i < 0:
            x, i = x[-i:], 0
        seg = x[: self.n - i]
        self.buf[i : i + len(seg)] += seg * g

    def silence(self, a: float, b: float, fade: float = 0.014):
        i, j = max(0, int(a * SR)), min(self.n, int(b * SR))
        if j <= i:
            return
        f = int(fade * SR)
        self.buf[i : i + f] *= np.linspace(1, 0, min(f, j - i))
        self.buf[i + f : j] = 0.0
        self.buf[j : j + f] *= np.linspace(0, 1, min(f, max(0, self.n - j)))


def arp_run(m: Mix, t0: float, t1: float, amp: float, oct_up: bool = False):
    """16th-note arpeggio through the progression. The engine of the track."""
    t = t0
    i = 0
    while t < t1:
        chord = PROG[int((t - t0) / BAR) % len(PROG)]
        f = chord[i % len(chord)] * (2.0 if (oct_up and (i // 3) % 2) else 1.0)
        accent = 1.25 if i % 4 == 0 else (0.72 if i % 2 else 0.92)
        m.at(t, pluck(f, 0.26, amp * accent))
        t += S16
        i += 1


def bed(m: Mix, t0: float, t1: float, amp: float, low: bool = True):
    """Pad + root movement following the progression."""
    t = t0
    while t < t1:
        chord = PROG[int((t - t0) / BAR) % len(PROG)]
        m.at(t, pad(chord, min(BAR, t1 - t) + 0.6, amp))
        if low:
            m.at(t, saw(chord[0] / 2, min(BAR, t1 - t) + 0.3) * 0.11 * amp / 0.1)
        t += BAR


def groove(m: Mix, t0: float, t1: float, amp: float, hats: bool = True):
    t = t0
    i = 0
    while t < t1:
        if i % 4 == 0:
            m.at(t, kick(0.5, 0.55 * amp))
        if hats and i % 2 == 1:
            m.at(t, hat(0.09, 0.10 * amp, 1.0 if i % 4 == 1 else 0.6))
        t += BEAT / 2
        i += 1


def master_bus(buf: np.ndarray) -> np.ndarray:
    buf = reverb(buf, 2.2, 0.24)
    buf = buf / (np.abs(buf).max() or 1.0) * 0.95
    buf = np.tanh(buf * 1.3) / np.tanh(1.3)
    right = np.concatenate([np.zeros(int(0.00045 * SR)), buf])[: len(buf)]
    st = np.stack([buf, right * 0.98], axis=1)
    f = int(0.02 * SR)
    st[:f] *= np.linspace(0, 1, f)[:, None]
    st[-f:] *= np.linspace(1, 0, f)[:, None]
    return st


def write(path: str, st: np.ndarray):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes())


# ---------------------------------------------------------------------------
def build(kind: str, b: dict, dur: float) -> np.ndarray:
    m = Mix(dur + 0.4)
    boot, cut, zero = b["boot"], b["cut"], b["zero"]
    city, black, mark = b["city"], b["black"], b["mark"]
    end = b["end"]

    # --- 0.0 THE HOOK. Punch first, atmosphere second. ---------------------
    m.at(0.00, subdrop(2.6, 0.62))
    m.at(0.00, hat(0.16, 0.24, 1.4))
    m.at(0.02, bell(N["D4"], 2.0, 0.20))
    m.at(0.06, riser(max(0.6, boot - 0.12), 0.16, 200, 2600))
    m.at(0.10, pad([N["D3"], N["A3"]], boot + 0.4, 0.045))

    # --- boot: the empire wakes -------------------------------------------
    m.at(boot, subdrop(3.2, 1.0))
    m.at(boot, kick(0.6, 0.7))
    m.at(boot, whoosh(0.85, 0.24))
    m.at(boot, braam(N["D2"], 2.4, 0.34))
    bed(m, boot, cut, 0.105)
    arp_run(m, boot + 0.2, cut, 0.085)
    groove(m, boot + BEAT, cut, 0.85)

    # --- approach: tighten, then cut --------------------------------------
    m.at(cut - 1.7, riser(1.7, 0.26, 300, 6200))
    m.at(cut - 0.06, whoosh(0.5, 0.34))
    m.at(cut, hat(0.12, 0.18, 1.2))
    bed(m, cut, zero - 0.6, 0.055, low=False)
    arp_run(m, cut, zero - 0.7, 0.042)

    # --- the silence, then the drop ---------------------------------------
    m.silence(zero - 0.58, zero)
    m.at(zero, subdrop(4.0, 1.0))
    m.at(zero, kick(0.7, 0.85))
    m.at(zero, braam(N["D2"], 3.0, 0.42))
    m.at(zero, bell(N["D3"], 3.4, 0.20))
    bed(m, zero + 0.05, city if kind == "vertical" else b["r1"], 0.075)
    arp_run(m, zero + BEAT, city if kind == "vertical" else b["r1"], 0.055)
    groove(m, zero + BEAT, city if kind == "vertical" else b["r1"], 0.62, hats=True)

    if kind == "vertical":
        # the proof beat
        m.at(b["proof"] - 0.06, whoosh(0.36, 0.20))
        m.at(b["proof"], kick(0.5, 0.5))
        m.at(b["proof"], braam(N["F2"], 1.8, 0.20))
    else:
        # --- the three refusals: braams a semitone apart, climbing ---------
        for k, (sec, root) in enumerate(((b["r1"], N["D2"]),
                                         (b["r2"], N["D2"] * 1.0595),
                                         (b["r3"], N["D2"] * 1.1225))):
            m.at(sec - 0.07, whoosh(0.3, 0.20))
            m.at(sec, braam(root, 2.3, 0.46 + 0.05 * k))
            m.at(sec, kick(0.55, 0.6))
            m.at(sec, subdrop(2.0, 0.5))
            m.at(sec + 0.02, pad([root * 2, root * 3, root * 4], 2.2, 0.055))
            m.at(sec + BEAT, hat(0.1, 0.10, 0.9))
            m.at(sec + BEAT * 1.5, hat(0.1, 0.08, 0.6))

    # --- scale: the fullest moment ----------------------------------------
    m.at(city - 0.1, riser(1.0, 0.22, 400, 7000))
    m.at(city, subdrop(3.0, 0.7))
    m.at(city, kick(0.6, 0.75))
    m.at(city, braam(N["D2"], 2.6, 0.30))
    bed(m, city, black, 0.125)
    arp_run(m, city, black, 0.095, oct_up=True)
    groove(m, city, black, 0.95)

    # --- black, then the mark ---------------------------------------------
    m.silence(black, mark)
    m.at(mark, bell(N["D3"], 3.0, 0.46))
    m.at(mark, subdrop(2.0, 0.34))
    m.at(min(mark + 0.72, end - 0.3), bell(N["A3"], 2.4, 0.32))
    m.at(min(mark + 1.42, end - 0.2), bell(N["D4"], 2.0, 0.20))

    return m.buf[: int(dur * SR)]


if __name__ == "__main__":
    kind, beats, dur, out = sys.argv[1], json.loads(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    write(out, master_bus(build(kind, beats, dur)))
    print(f"{kind} score v2 -> {out}")
