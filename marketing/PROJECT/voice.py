"""Titan Ω — voice cast.

There is no neural TTS available in this environment: piper and kokoro install
from PyPI but their weights live on huggingface.co, which the session's egress
policy blocks. What IS available is espeak-ng driving MBROLA diphone voices
from the Ubuntu archive.

Raw, those sound like 2010 screen-reader output and would cheapen the film. So
they are not used raw. Titan is an AI command centre, and a *machine* voice is
on-brand rather than a compromise — the same convention as MOTHER in Alien or
TARS in Interstellar. Each line is pitched, filtered, doubled and spaced to
read as a designed system voice, and the cast is split three ways so the film
has more than one speaker.

    TITAN    — the system. Low, cold, wide, slightly detuned against itself.
    FOUNDER  — the human line. Closer, warmer, drier, no doubling.
    AGENT    — the refusals. Bandlimited like comms, hard-compressed, urgent.
"""

from __future__ import annotations

import subprocess
import tempfile
import wave

import numpy as np

SR = 48_000


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[:300]}")


# voice -> (espeak voice, words/min, espeak pitch, sox chain)
CAST = {
    # Deep, wide, a little inhuman. The chorus is what stops it reading as a
    # screen reader: two detuned copies of the same take, slightly apart.
    "TITAN": (
        "mb-us2", 138, 22,
        ["pitch", "-260", "tempo", "0.97",
         "highpass", "75", "lowpass", "7200",
         "chorus", "0.7", "0.9", "42", "0.4", "0.25", "2", "-t",
         "overdrive", "4", "12",
         "compand", "0.02,0.25", "6:-40,-24,-12", "-4", "-90", "0.1",
         "reverb", "38", "48", "70", "100", "12"],
    ),
    # The founder's own line. Closest to natural: least processing, no chorus,
    # short reverb so it sits in a room rather than a hangar.
    "FOUNDER": (
        "mb-us1", 150, 34,
        ["pitch", "-110", "tempo", "1.0",
         "highpass", "95", "lowpass", "8800",
         "equalizer", "220", "1.4q", "3",
         "equalizer", "2600", "1.8q", "4",
         "compand", "0.01,0.18", "6:-38,-22,-10", "-3", "-90", "0.05",
         "reverb", "18", "35", "42", "100", "8"],
    ),
    # Comms. Bandlimited and squashed so the refusals cut through the impacts.
    "AGENT": (
        "mb-us3", 165, 48,
        ["pitch", "80", "tempo", "1.03",
         "highpass", "420", "lowpass", "3400",
         "overdrive", "8", "18",
         "compand", "0.005,0.1", "6:-30,-18,-6", "-2", "-90", "0.02",
         "reverb", "22", "40", "30", "100", "6"],
    ),
}


def say(text: str, voice: str = "TITAN", gap_ms: int = 0) -> np.ndarray:
    """Render one line and return it as mono float at the project rate."""
    espeak_voice, wpm, pitch, chain = CAST[voice]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as a:
        raw = a.name
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as b:
        out = b.name

    _run(["espeak-ng", "-v", espeak_voice, "-s", str(wpm), "-p", str(pitch),
          "-g", str(gap_ms), "-w", raw, text])
    # `rate` must lead the chain: sox runs effects at the INPUT rate, and the
    # MBROLA voices are 16 kHz, so an 8.8 kHz lowpass is above Nyquist and the
    # chain is rejected outright. Resampling first also gives the pitch and
    # chorus stages room to work.
    _run(["sox", raw, "-c", "1", "-b", "16", out, "rate", "-v", str(SR), *chain])

    with wave.open(out, "rb") as w:
        buf = w.readframes(w.getnframes())
    sig = np.frombuffer(buf, dtype="<i2").astype(np.float64) / 32768.0
    peak = np.abs(sig).max()
    return sig / peak * 0.9 if peak > 0 else sig


def duck(bed: np.ndarray, vo: np.ndarray, depth: float = 0.42,
         attack: float = 0.08, release: float = 0.34) -> np.ndarray:
    """Pull the music down under speech.

    Without this the sub and the pad sit exactly where the voice lives and the
    words turn to mud. The envelope follows the voice rather than a fixed
    schedule, so it also rides the gaps between lines.
    """
    n = min(len(bed), len(vo))
    env = np.abs(vo[:n])
    # Smooth to an amplitude envelope: fast to duck, slow to recover.
    win_a, win_r = max(1, int(attack * SR)), max(1, int(release * SR))
    sm = np.zeros(n)
    acc = 0.0
    for i in range(0, n, 64):                       # 64-sample hops: fast enough, cheap
        target = env[i : i + 64].max()
        k = 1.0 / win_a if target > acc else 1.0 / win_r
        acc += (target - acc) * min(1.0, k * 64)
        sm[i : i + 64] = acc
    sm = sm / (sm.max() or 1.0)
    gain = 1.0 - depth * np.clip(sm * 2.2, 0, 1)
    out = bed.copy()
    out[:n] *= gain
    return out
