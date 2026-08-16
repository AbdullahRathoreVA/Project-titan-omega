"""Titan Ω — score v3. Music-forward, no voice.

v2 added motion. v3 is built to carry the film on its own, because the
synthesised voices were not good enough to keep and the captions already carry
the words for muted viewing.

What v3 adds over v2:

  * A **lead line** — a real melody over the scale section, so the track has
    something to remember rather than only something to feel.
  * **Sidechain pumping**: the pad and bass duck on every kick. This is the
    single biggest "sounds produced" difference; a static bed reads as a demo,
    a breathing one reads as a record.
  * **Filter movement** on the arpeggio — it opens across each section instead
    of repeating at one brightness.
  * **Reverse swell** into every major hit, so impacts are arrived at rather
    than merely struck.
  * A **wider, deeper braam** for the refusals, and tape-style saturation plus
    bus glue on the master.

72 BPM, D minor, Dm · Bb · F · C.
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

N = {"D1": 36.71, "D2": 73.42, "F2": 87.31, "A2": 110.00, "Bb2": 116.54,
     "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.00,
     "A3": 220.00, "Bb3": 233.08, "C4": 261.63, "D4": 293.66, "E4": 329.63,
     "F4": 349.23, "G4": 392.00, "A4": 440.00, "D5": 587.33, "F5": 698.46}

PROG = [
    [N["D3"], N["F3"], N["A3"]],
    [N["Bb2"], N["D3"], N["F3"]],
    [N["F2"], N["A2"], N["C3"]],
    [N["C3"], N["F3"], N["G3"]],
]
ROOTS = [N["D2"], N["Bb2"], N["F2"], N["C3"]]

# The hook melody. Simple, stepwise, resolves down to the tonic — the shape you
# can still hum after one listen.
LEAD = [(0.0, N["A4"], 1.0), (1.0, N["G4"], 0.5), (1.5, N["F4"], 1.5),
        (3.0, N["E4"], 1.0), (4.0, N["F4"], 1.0), (5.0, N["A4"], 1.5),
        (6.5, N["G4"], 0.5), (7.0, N["F4"], 1.0), (8.0, N["D4"], 2.0)]


def _t(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def env(n: int, a: float, d: float, curve: float = 2.5) -> np.ndarray:
    t = _t(n)
    return np.clip(t / max(a, 1e-6), 0, 1) * np.exp(-t / max(d, 1e-6)) ** (1 / curve)


def onepole_lp(x: np.ndarray, cutoff: np.ndarray) -> np.ndarray:
    """Time-varying one-pole low-pass. Cheap, and enough to make a filter sweep
    read as movement rather than a volume change."""
    a = np.clip(1.0 - np.exp(-2 * np.pi * cutoff / SR), 0.0, 1.0)
    out = np.empty_like(x)
    y = 0.0
    for i in range(len(x)):
        y += a[i] * (x[i] - y)
        out[i] = y
    return out


def pluck(f: float, dur: float, amp: float, bright: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    sig = (np.sin(2 * np.pi * f * t)
           + 0.5 * bright * np.sin(2 * np.pi * f * 2 * t)
           + 0.28 * bright * np.sin(2 * np.pi * f * 3 * t)
           + 0.14 * bright * np.sin(2 * np.pi * f * 4.02 * t))
    return amp * sig * env(n, 0.002, 0.11)


def lead_voice(f: float, dur: float, amp: float) -> np.ndarray:
    """Warm sine-triangle lead with vibrato and a soft attack."""
    n = int(dur * SR)
    t = _t(n)
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.clip(t / 0.35, 0, 1)
    ph = 2 * np.pi * np.cumsum(f * vib) / SR
    sig = np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    a = np.clip(t / 0.045, 0, 1)
    r = np.clip((dur - t) / 0.25, 0, 1)
    return amp * sig * a * r


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
    return amp * out * np.clip(t / 0.5, 0, 1)


def bass(f: float, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    sig = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2 * t)
    return amp * sig * np.clip(t / 0.02, 0, 1) * np.clip((dur - t) / 0.12, 0, 1)


def braam(root: float, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for mult, g in ((0.5, 1.0), (1.0, 0.95), (1.5, 0.55), (2.0, 0.5), (3.0, 0.26), (4.0, 0.14)):
        f = root * mult * (1 + 0.035 * np.exp(-t / 0.14))
        ph = 2 * np.pi * np.cumsum(f) / SR
        out += g * (np.sin(ph) + 0.45 * np.sin(2 * ph) + 0.22 * np.sin(3 * ph))
    out = np.tanh(out / 4.0 * 2.4)
    return amp * out * env(n, 0.014, dur * 0.45, 1.7)


def kick(dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    f = 42 + 78 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.0012, 0.20, 1.6)
    click = np.random.default_rng(5).standard_normal(n) * np.exp(-t / 0.0035) * 0.22
    return amp * (body + click)


def subdrop(dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    f = 28 + 44 * np.exp(-t / 0.22)
    return amp * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, dur * 0.5, 1.4)


def hat(dur: float, amp: float, bright: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(int(bright * 977) % 4096)
    x = rng.standard_normal(n)
    k = 10
    x = x - np.convolve(x, np.ones(k) / k, mode="same")
    return amp * x * env(n, 0.0005, 0.028 * bright, 1.2)


def riser(dur: float, amp: float, f0: float = 180, f1: float = 7000) -> np.ndarray:
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(11)
    out = np.zeros(n)
    for _ in range(30):
        f = f0 * (f1 / f0) ** ((t / max(dur, 1e-6)) ** 1.35) * (0.7 + 0.6 * rng.random())
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6)
    out /= 30
    return amp * out * (t / dur) ** 2.0


def reverse_swell(dur: float, amp: float) -> np.ndarray:
    """Noise swell that grows into the hit — reversed-cymbal shape. Makes an
    impact feel arrived at instead of merely struck."""
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(31)
    x = rng.standard_normal(n)
    k = 6
    x = x - np.convolve(x, np.ones(k) / k, mode="same")
    return amp * x * (t / dur) ** 3.0


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


def reverb(x: np.ndarray, decay: float = 2.2, mix: float = 0.24) -> np.ndarray:
    n = int(decay * SR)
    rng = np.random.default_rng(23)
    ir = rng.standard_normal(n) * np.exp(-_t(n) / (decay / 4.2))
    ir[0] = 1.0
    ir /= np.abs(ir).sum() / 6
    return (1 - mix) * x + mix * np.convolve(x, ir)[: len(x)]


class Mix:
    def __init__(self, dur: float):
        self.n = int(dur * SR)
        self.harmony = np.zeros(self.n)   # ducked by the kick
        self.rhythm = np.zeros(self.n)    # not ducked
        self.kicks: list[float] = []

    def h(self, sec: float, x: np.ndarray, g: float = 1.0):
        self._add(self.harmony, sec, x, g)

    def r(self, sec: float, x: np.ndarray, g: float = 1.0):
        self._add(self.rhythm, sec, x, g)

    def _add(self, buf, sec, x, g):
        i = int(sec * SR)
        if i >= self.n:
            return
        if i < 0:
            x, i = x[-i:], 0
        seg = x[: self.n - i]
        buf[i : i + len(seg)] += seg * g

    def kick_at(self, sec: float, amp: float = 0.72):
        self.r(sec, kick(0.55, amp))
        self.kicks.append(sec)

    def sidechain(self, depth: float = 0.55, hold: float = 0.28) -> np.ndarray:
        """Duck the harmony bus on every kick. The pump is what separates a bed
        from a production."""
        g = np.ones(self.n)
        L = int(hold * SR)
        shape = 1.0 - depth * (1.0 - np.linspace(0, 1, L) ** 0.55)
        for k in self.kicks:
            i = int(k * SR)
            if i >= self.n:
                continue
            seg = shape[: self.n - i]
            g[i : i + len(seg)] = np.minimum(g[i : i + len(seg)], seg)
        return self.harmony * g + self.rhythm

    def silence(self, buf, a: float, b: float, fade: float = 0.014):
        i, j = max(0, int(a * SR)), min(self.n, int(b * SR))
        if j <= i:
            return
        f = int(fade * SR)
        buf[i : i + f] *= np.linspace(1, 0, min(f, j - i))
        buf[i + f : j] = 0.0
        buf[j : j + f] *= np.linspace(0, 1, min(f, max(0, self.n - j)))


def master_bus(buf: np.ndarray) -> np.ndarray:
    buf = reverb(buf, 2.2, 0.22)
    buf = buf / (np.abs(buf).max() or 1.0) * 0.95
    # Tape-ish saturation, then gentle glue.
    buf = np.tanh(buf * 1.45) / np.tanh(1.45)
    buf = buf / (np.abs(buf).max() or 1.0) * 0.94
    right = np.concatenate([np.zeros(int(0.0005 * SR)), buf])[: len(buf)]
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


def section(m: Mix, t0: float, t1: float, amp: float, arp: float,
            groove: bool, oct_up: bool = False, lead: bool = False,
            bright0: float = 0.35, bright1: float = 1.0):
    """One musical block: pad + bass on the progression, arpeggio with a filter
    opening across it, optional groove and lead."""
    if t1 <= t0:
        return
    span = t1 - t0
    t = t0
    while t < t1:
        idx = int((t - t0) / BAR) % len(PROG)
        chord, root = PROG[idx], ROOTS[idx]
        m.h(t, pad(chord, min(BAR, t1 - t) + 0.6, amp))
        m.h(t, bass(root, min(BEAT * 3.6, t1 - t), amp * 1.35))
        t += BAR

    # arpeggio, brightness opening across the section
    t, i = t0, 0
    while t < t1:
        chord = PROG[int((t - t0) / BAR) % len(PROG)]
        f = chord[i % len(chord)] * (2.0 if (oct_up and (i // 3) % 2) else 1.0)
        u = (t - t0) / span
        accent = 1.3 if i % 4 == 0 else (0.7 if i % 2 else 0.92)
        m.h(t, pluck(f, 0.28, arp * accent, bright0 + (bright1 - bright0) * u))
        t += S16
        i += 1

    if groove:
        t, i = t0, 0
        while t < t1:
            if i % 4 == 0:
                m.kick_at(t)
            if i % 2 == 1:
                m.r(t, hat(0.09, 0.095, 1.0 if i % 4 == 1 else 0.6))
            t += BEAT / 2
            i += 1

    if lead:
        for off, f, dur in LEAD:
            at = t0 + off * BEAT
            if at < t1:
                m.h(at, lead_voice(f, min(dur * BEAT, t1 - at), amp * 1.15))


def build(kind: str, b: dict, dur: float) -> np.ndarray:
    m = Mix(dur + 0.4)
    boot, cut, zero = b["boot"], b["cut"], b["zero"]
    city, black, mark, end = b["city"], b["black"], b["mark"], b["end"]

    # 0.0 — the hook lands immediately.
    m.r(0.00, subdrop(2.6, 0.60))
    m.r(0.00, hat(0.16, 0.22, 1.4))
    m.h(0.02, bell(N["D4"], 2.0, 0.20))
    m.h(0.10, pad([N["D3"], N["A3"]], boot + 0.4, 0.05))
    m.r(max(0.0, boot - 1.1), riser(1.1, 0.15, 200, 2800))
    m.r(max(0.0, boot - 0.55), reverse_swell(0.55, 0.17))

    # boot — the empire wakes
    m.r(boot, subdrop(3.2, 1.0))
    m.kick_at(boot, 0.85)
    m.r(boot, whoosh(0.85, 0.24))
    m.h(boot, braam(N["D2"], 2.4, 0.32))
    section(m, boot, cut, 0.105, 0.085, groove=True, bright0=0.4, bright1=0.95)

    # approach — tighten into the cut
    m.r(cut - 1.7, riser(1.7, 0.24, 300, 6400))
    m.r(cut - 0.06, whoosh(0.5, 0.32))
    quiet_from = zero - 0.62
    section(m, cut, quiet_from, 0.055, 0.040, groove=False, bright0=0.9, bright1=0.35)

    # the drop
    m.r(zero - 0.35, reverse_swell(0.35, 0.26))
    m.r(zero, subdrop(4.0, 1.0))
    m.kick_at(zero, 0.95)
    m.h(zero, braam(N["D2"], 3.0, 0.54))
    m.h(zero, bell(N["D3"], 3.4, 0.26))

    mid_end = city if kind == "vertical" else b["r1"]
    section(m, zero + BEAT, mid_end, 0.078, 0.055, groove=True, bright0=0.5, bright1=1.0)

    if kind == "vertical":
        p = b["proof"]
        m.r(p - 0.3, reverse_swell(0.3, 0.18))
        m.kick_at(p, 0.7)
        m.h(p, braam(N["F2"], 1.8, 0.22))
    else:
        for k, (sec, root) in enumerate(((b["r1"], N["D2"]),
                                         (b["r2"], N["D2"] * 1.0595),
                                         (b["r3"], N["D2"] * 1.1225))):
            m.r(sec - 0.32, reverse_swell(0.32, 0.20 + 0.03 * k))
            m.h(sec, braam(root, 2.4, 0.48 + 0.05 * k))
            m.kick_at(sec, 0.8)
            m.r(sec, subdrop(2.0, 0.5))
            m.h(sec + 0.02, pad([root * 2, root * 3, root * 4], 2.2, 0.05))
            m.r(sec + BEAT, hat(0.1, 0.09, 0.9))
        section(m, b["r3"] + BEAT, city, 0.05, 0.03, groove=False, bright0=0.5, bright1=0.8)

    # scale — fullest, and the lead line arrives here
    m.r(city - 0.9, riser(0.9, 0.22, 400, 7200))
    m.r(city - 0.4, reverse_swell(0.4, 0.24))
    m.r(city, subdrop(3.0, 0.72))
    m.kick_at(city, 0.9)
    m.h(city, braam(N["D2"], 2.6, 0.30))
    section(m, city, black, 0.100, 0.078, groove=True, oct_up=True, lead=True,
            bright0=0.7, bright1=1.0)

    buf = m.sidechain(depth=0.55)
    m.silence(buf, zero - 0.62, zero)
    m.silence(buf, black, mark)

    # the mark
    tail = np.zeros(m.n)
    def add_tail(sec, x):
        i = int(sec * SR)
        if i < m.n:
            seg = x[: m.n - i]
            tail[i : i + len(seg)] += seg
    add_tail(mark, bell(N["D3"], 3.0, 0.48))
    add_tail(mark, subdrop(2.0, 0.34))
    add_tail(min(mark + 0.72, end - 0.3), bell(N["A3"], 2.4, 0.34))
    add_tail(min(mark + 1.42, end - 0.2), bell(N["D4"], 2.0, 0.22))
    buf = buf + tail

    return buf[: int(dur * SR)]


if __name__ == "__main__":
    kind, beats, dur, out = sys.argv[1], json.loads(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    write(out, master_bus(build(kind, beats, dur)))
    print(f"{kind} score v3 -> {out}")
