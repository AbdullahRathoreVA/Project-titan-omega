"""Titan Ω — original score and sound design, built to measured picture.

There is no music library here and no stock bed. Every sound is generated from
arithmetic and placed at the exact second of the cut it belongs to.

The important part: the beat times are NOT the times written in the director.
Playwright records variable-rate video and this page drops frames unevenly, so
script time and video time diverge non-linearly — no single speed correction
fixes it. The director stamps a marker on every scored beat in a strip below the
frame; master.py reads those marks back and passes the real times in here. The
score is therefore built to fit the picture, which is the only way the impact
lands on the frame that earns it.

Design: 72 BPM, D minor. A 41 Hz sub carries the weight, a detuned pad carries
the harmony, and the loudest event is the impact on "$0" — with the second
loudest being the silence immediately before it.
"""

from __future__ import annotations

import json
import sys
import wave

import numpy as np

SR = 48_000

D2, A2, D3, F3, A3, C4, D4, F4, A4 = 73.42, 110.0, 146.83, 174.61, 220.0, 261.63, 293.66, 349.23, 440.0


def _t(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def env(n: int, attack: float, decay: float, curve: float = 2.5) -> np.ndarray:
    t = _t(n)
    return np.clip(t / max(attack, 1e-6), 0, 1) * np.exp(-t / max(decay, 1e-6)) ** (1 / curve)


def sine(freq: float, dur: float, amp: float = 1.0, detune: float = 0.0) -> np.ndarray:
    t = _t(int(dur * SR))
    if detune:
        return amp * 0.5 * (np.sin(2 * np.pi * freq * t) + np.sin(2 * np.pi * freq * (1 + detune) * t))
    return amp * np.sin(2 * np.pi * freq * t)


def sub(freq: float, dur: float, amp: float, attack: float = 0.004, decay: float = 0.9) -> np.ndarray:
    """Weight. The pitch drop on the attack is what makes it read as an impact
    rather than a note."""
    n = int(dur * SR)
    t = _t(n)
    sweep = freq * (1 + 0.55 * np.exp(-t / 0.05))
    return amp * np.sin(2 * np.pi * np.cumsum(sweep) / SR) * env(n, attack, decay)


def pad(freqs, dur: float, amp: float) -> np.ndarray:
    """Detuned additive pad, three drifting voices per note so it breathes."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    rng = np.random.default_rng(7)
    for f in freqs:
        for k, det in enumerate((-0.004, 0.0, 0.005)):
            lfo = 1 + 0.0016 * np.sin(2 * np.pi * (0.07 + 0.03 * k) * t + rng.random() * 6)
            out += np.sin(2 * np.pi * f * (1 + det) * t * lfo) / (len(freqs) * 3)
            out += 0.18 * np.sin(2 * np.pi * 2 * f * (1 + det) * t) / (len(freqs) * 3)
    return amp * out


def noise_riser(dur: float, amp: float, f0: float = 300, f1: float = 5200) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(11)
    out = np.zeros(n)
    for _ in range(26):
        f = f0 * (f1 / f0) ** (t / max(dur, 1e-6)) * (0.75 + 0.5 * rng.random())
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6)
    return amp * (out / 26) * (t / dur) ** 2.2


def tick(freq: float, amp: float, dur: float = 0.06) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    return amp * (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2.7 * t)) * env(n, 0.0008, 0.012)


def whoosh(dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(3)
    out = np.zeros(n)
    for _ in range(18):
        f = 900 * (1 + 3.4 * np.sin(np.pi * t / dur)) * (0.6 + rng.random())
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6)
    return amp * (out / 18) * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6


def bell(freq: float, dur: float, amp: float) -> np.ndarray:
    """Sonic-logo voice: inharmonic partials, long tail, no attack transient."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for mult, a, dec in ((1.0, 1.0, 2.6), (2.01, 0.36, 1.5), (3.02, 0.16, 0.9), (4.9, 0.07, 0.5)):
        out += a * np.sin(2 * np.pi * freq * mult * t) * np.exp(-t / dec)
    return amp * (out / 1.6) * np.clip(t / 0.012, 0, 1)


def reverb(x: np.ndarray, decay: float = 1.9, mix: float = 0.30) -> np.ndarray:
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

    def at(self, sec: float, x: np.ndarray, gain: float = 1.0):
        i = int(sec * SR)
        if i >= self.n or i < 0:
            return
        seg = x[: self.n - i]
        self.buf[i : i + len(seg)] += seg * gain

    def silence(self, start: float, end: float, fade: float = 0.012):
        """Hard-gate a window. The pause before the impact is the single most
        important sound in the film, so it is cut in rather than hoped for."""
        a, b = max(0, int(start * SR)), min(self.n, int(end * SR))
        if b <= a:
            return
        f = int(fade * SR)
        self.buf[a : a + f] *= np.linspace(1, 0, min(f, b - a))
        self.buf[a + f : b] = 0.0
        self.buf[b : b + f] *= np.linspace(0, 1, min(f, max(0, self.n - b)))


def master_bus(buf: np.ndarray) -> np.ndarray:
    buf = reverb(buf, decay=2.2, mix=0.26)
    buf = buf / (np.abs(buf).max() or 1.0) * 0.94
    buf = np.tanh(buf * 1.25) / np.tanh(1.25)
    right = np.concatenate([np.zeros(int(0.00042 * SR)), buf])[: len(buf)]
    st = np.stack([buf, right * 0.985], axis=1)
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
def build_vertical(b: dict, dur: float) -> np.ndarray:
    m = Mix(dur + 0.2)
    boot, cut, zero = b["boot"], b["cut"], b["zero"]
    proof, city, black, mark_, end = b["proof"], b["city"], b["black"], b["mark"], b["end"]

    # the void
    m.at(0.0, sine(D2 / 2, boot + 0.5, 0.16, detune=0.004) * np.linspace(0.2, 1, int((boot + 0.5) * SR)))
    m.at(0.0, pad([D3, A3], boot + 0.7, 0.030))
    m.at(0.2, noise_riser(max(0.4, boot - 0.2), 0.055, 200, 1800))

    # the empire wakes
    m.at(boot, sub(41, 2.6, 0.95))
    m.at(boot, whoosh(0.9, 0.22))
    m.at(boot + 0.02, pad([D3, F3, A3, D4], 3.4, 0.115))
    m.at(boot, tick(2400, 0.11))
    for k in range(4):
        m.at(boot + 0.40 + k * 0.22, tick(1500 + 260 * k, 0.075))

    # the approach
    m.at(cut - 1.5, pad([D3, A3, C4], 1.7, 0.085))
    m.at(cut - 1.5, noise_riser(1.5, 0.20, 320, 4600))

    # hard cut, thin out, then true silence before the number
    m.at(cut - 0.02, whoosh(0.45, 0.34))
    m.at(cut, tick(3200, 0.09))
    m.at(cut + 0.05, pad([D3, A3], max(0.4, zero - cut - 0.5), 0.055))
    m.at(cut + 0.4, sine(D3, max(0.3, zero - cut - 0.9), 0.075, detune=0.003))
    m.silence(zero - 0.55, zero)

    # THE IMPACT
    m.at(zero, sub(35, 3.6, 1.0))
    m.at(zero, bell(D3, 3.2, 0.16))
    m.at(zero + 0.02, pad([D3, F3, A3], 3.6, 0.075))
    m.at(zero + 1.2, tick(900, 0.045))
    m.at(zero + 2.7, tick(900, 0.045))
    m.at(zero + 2.1, pad([D3, F3, A3, C4], 3.0, 0.070))

    # the proof beat
    m.at(proof - 0.06, whoosh(0.35, 0.20))
    m.at(proof, sub(45, 1.6, 0.40))
    m.at(proof + 0.02, pad([F3, A3, C4], 2.4, 0.085))

    # everything else is real too — fullest moment
    m.at(city - 0.06, whoosh(0.4, 0.24))
    m.at(city, sub(41, 2.2, 0.55))
    m.at(city + 0.02, pad([D3, F3, A3, D4, F4], 2.4, 0.130))
    for k in range(5):
        m.at(city + 0.15 + k * 0.23, tick(1300 + 300 * k, 0.05))

    # black, then the mark
    m.silence(black, mark_)
    m.at(mark_, bell(D3, 2.6, 0.42))
    m.at(min(mark_ + 0.64, end - 0.2), bell(A3, 1.9, 0.30))
    m.at(mark_, sub(41, 1.4, 0.30))
    return master_bus(m.buf[: int(dur * SR)])


def build_hero(b: dict, dur: float) -> np.ndarray:
    m = Mix(dur + 0.2)
    boot, cut, zero = b["boot"], b["cut"], b["zero"]
    r1, r2, r3 = b["r1"], b["r2"], b["r3"]
    city, black, mark_, end = b["city"], b["black"], b["mark"], b["end"]

    m.at(0.0, sine(D2 / 2, boot + 0.5, 0.15, detune=0.004) * np.linspace(0.15, 1, int((boot + 0.5) * SR)))
    m.at(0.0, pad([D3, A3], boot + 0.6, 0.028))
    m.at(0.3, noise_riser(max(0.5, boot - 0.4), 0.06, 200, 1700))

    m.at(boot, sub(41, 2.8, 0.92))
    m.at(boot, whoosh(1.0, 0.22))
    m.at(boot + 0.02, pad([D3, F3, A3, D4], 4.2, 0.115))
    for k in range(5):
        m.at(boot + 0.5 + k * 0.22, tick(1500 + 240 * k, 0.070))

    m.at(cut - 2.2, pad([D3, A3, C4], 2.2, 0.080))
    m.at(cut - 2.0, noise_riser(2.0, 0.20, 320, 4600))
    m.at(cut - 0.05, whoosh(0.45, 0.32))
    m.at(cut + 0.05, sine(D3, max(0.4, zero - cut - 0.7), 0.070, detune=0.003))
    m.silence(zero - 0.55, zero)

    m.at(zero, sub(35, 3.8, 1.0))
    m.at(zero, bell(D3, 3.4, 0.16))
    m.at(zero + 0.02, pad([D3, F3, A3], 3.8, 0.075))

    # the refusals — three stabs, each a semitone up
    for k, (sec, f) in enumerate(((r1, D3), (r2, D3 * 1.0595), (r3, D3 * 1.1225))):
        m.at(sec - 0.06, whoosh(0.24, 0.16))
        m.at(sec, sub(38 + 3 * k, 1.9, 0.62))
        m.at(sec, tick(700 + 120 * k, 0.10, 0.05))
        m.at(sec + 0.02, pad([f, f * 1.5, f * 2], 2.3, 0.070))

    m.at(city - 0.1, whoosh(0.5, 0.26))
    m.at(city, sub(41, 3.0, 0.66))
    m.at(city + 0.05, pad([D3, F3, A3, D4, F4, A4], 5.0, 0.135))
    for k in range(8):
        m.at(city + 0.3 + k * 0.22, tick(1200 + 240 * k, 0.042))
    m.at(black - 2.4, pad([D3, A3, D4], 2.4, 0.085))
    m.at(black - 2.4, sub(45, 1.6, 0.34))

    m.silence(black, mark_)
    m.at(mark_, bell(D3, 2.8, 0.44))
    m.at(min(mark_ + 0.78, end - 0.3), bell(A3, 2.2, 0.32))
    m.at(mark_, sub(41, 1.6, 0.30))
    return master_bus(m.buf[: int(dur * SR)])


if __name__ == "__main__":
    kind, beats_json, dur, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    beats = json.loads(beats_json)
    st = (build_vertical if kind == "vertical" else build_hero)(beats, dur)
    write(out, st)
    print(f"{kind}: {len(st)/SR:.2f}s -> {out}")
