"""Titan Ω — rebuild the films with real ElevenLabs voices.

Run this on any machine that can reach api.elevenlabs.io. It could not be run
in the session that produced these films: that environment's egress policy
blocks api.elevenlabs.io, api.openai.com and huggingface.co, so no neural voice
of any kind was reachable and the shipped cut is music-only.

    export ELEVENLABS_API_KEY=sk_...
    python marketing/PROJECT/elevenlabs_vo.py --list          # see your voices
    python marketing/PROJECT/elevenlabs_vo.py --frames-v /tmp/frames_v \\
                                              --frames-h /tmp/frames_h

Frames come from `render.mjs`; if you no longer have them, re-render first.
Nothing here invents a number — the lines are the same verified copy that is
already burned into the captions.

Default voices are chosen for the cast, and any of them can be overridden:
    --voice-founder <id>   --voice-titan <id>   --voice-agent <id>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import wave

import numpy as np

API = "https://api.elevenlabs.io/v1"
SR = 48_000

# ElevenLabs' own stock voice ids. Adam is the same default the Titan backend
# already uses in app/api/tts.py, so the film and the product speak alike.
DEFAULT_VOICES = {
    "FOUNDER": "pNInz6obpgDQGcFmaJgB",   # Adam — calm, grounded
    "TITAN": "onwK4e9ZLuTAKqWW03F9",     # Daniel — deep, authoritative
    "AGENT": "AZnzlk1XvdvUeBnXmlld",     # Domi — clipped, urgent
}

# (start seconds, voice, line). Same beats as audio_build.py.
LINES = {
    "vertical": [
        (0.30, "FOUNDER", "My AI company has made zero dollars."),
        (2.70, "TITAN", "One hundred two agents. Twelve divisions."),
        (7.10, "TITAN", "Revenue. Zero."),
        (9.10, "FOUNDER", "It could have shown any number I wanted."),
        (11.50, "TITAN", "Nothing is shown unless it was measured."),
        (15.05, "TITAN", "Titan Omega. Trust the zero."),
    ],
    "hero": [
        (0.45, "FOUNDER", "My AI company has made zero dollars."),
        (3.30, "TITAN", "One hundred two digital employees. Twelve divisions."),
        (7.50, "FOUNDER", "So I checked what it had earned."),
        (11.25, "TITAN", "Revenue. Zero. Measured."),
        (14.40, "AGENT", "Refused. Four zero nine. Illegal state transition."),
        (17.00, "AGENT", "No score. It has not audited itself yet."),
        (19.62, "AGENT", "Sixteen seventy five catalogued. Five wired."),
        (22.60, "TITAN", "Every number here was measured."),
        (26.90, "FOUNDER", "It hasn't earned anything yet."),
        (29.85, "TITAN", "Trust the zero."),
    ],
}
DUR = {"vertical": 18.0, "hero": 32.3}
BEATS = {
    "vertical": {"boot": 1.70, "cut": 4.90, "zero": 6.50, "proof": 10.40,
                 "city": 12.40, "black": 15.00, "mark": 15.35, "end": 18.00},
    "hero": {"boot": 2.45, "cut": 8.78, "zero": 10.65, "r1": 14.35, "r2": 16.95,
             "r3": 19.55, "city": 21.90, "black": 29.38, "mark": 29.82, "end": 32.30},
}


def key() -> str:
    k = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not k:
        sys.exit("ELEVENLABS_API_KEY is not set. Nothing was changed.")
    return k


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={"xi-api-key": key()})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def list_voices() -> None:
    for v in _get("/voices").get("voices", []):
        labels = ", ".join(f"{a}={b}" for a, b in (v.get("labels") or {}).items())
        print(f"{v['voice_id']}  {v['name']:<22} {labels}")


def tts(text: str, voice_id: str, out_mp3: str, model: str = "eleven_multilingual_v2") -> None:
    """One line to MP3. `stability` low and `style` moderate keeps delivery
    controlled — the direction note is not to sell the line."""
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                           "style": 0.25, "use_speaker_boost": True},
    }).encode()
    req = urllib.request.Request(
        f"{API}/text-to-speech/{voice_id}",
        data=body,
        headers={"xi-api-key": key(), "content-type": "application/json",
                 "accept": "audio/mpeg"},
    )
    with urllib.request.urlopen(req, timeout=180) as r, open(out_mp3, "wb") as f:
        f.write(r.read())


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def load_mono(path: str) -> np.ndarray:
    wav = path + ".wav"
    subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error", "-i", path,
                    "-ac", "1", "-ar", str(SR), "-y", wav], check=True)
    with wave.open(wav, "rb") as w:
        buf = w.readframes(w.getnframes())
    a = np.frombuffer(buf, dtype="<i2").astype(np.float64) / 32768.0
    peak = np.abs(a).max()
    return a / peak * 0.9 if peak else a


def build_audio(kind: str, voices: dict, workdir: str) -> str:
    """Real VO over score v3, ducked, with the same timing assertions."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import score3
    import voice as voicemod

    dur = DUR[kind]
    n = int(dur * SR)
    music = score3.build(kind, BEATS[kind], dur)
    music = np.pad(music, (0, max(0, n - len(music))))[:n]

    vo = np.zeros(n)
    spans = []
    for start, who, text in LINES[kind]:
        mp3 = os.path.join(workdir, f"{kind}_{who}_{start:.2f}.mp3")
        tts(text, voices[who], mp3)
        clip = load_mono(mp3)
        spans.append((start, start + len(clip) / SR, who, text))
        i = int(start * SR)
        seg = clip[: max(0, n - i)]
        f = min(int(0.012 * SR), len(seg) // 4)
        if f > 0:
            seg = seg.copy()
            seg[:f] *= np.linspace(0, 1, f)
            seg[-f:] *= np.linspace(1, 0, f)
        vo[i : i + len(seg)] += seg
        print(f"  {start:5.2f}s {who:<8} {len(clip)/SR:4.2f}s  {text[:48]}")

    # Real voices are not the same length as the synthetic ones, so the timing
    # is re-checked rather than assumed. The silence before the impact is the
    # strongest moment in the film and nothing may cross it.
    quiet = (BEATS[kind]["zero"] - 0.58, BEATS[kind]["zero"])
    problems = []
    for s0, e0, w0, t0 in spans:
        if s0 < quiet[1] and e0 > quiet[0]:
            problems.append(f"{w0} at {s0:.2f}s runs to {e0:.2f}s, crossing the silence")
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0] + 0.01:
            problems.append(f"{a[2]} at {a[0]:.2f}s overlaps {b[2]} at {b[0]:.2f}s by {a[1]-b[0]:.2f}s")
    if spans[-1][1] > dur + 0.05:
        problems.append(f"last line runs {spans[-1][1]-dur:.2f}s past the end")
    if problems:
        print("\nVO TIMING — shorten these lines or move their start times:")
        for p in problems:
            print("  ! " + p)
        sys.exit(1)

    mixed = voicemod.duck(music, vo, depth=0.52) + vo * 0.72
    out = os.path.join(workdir, f"{kind}_final.wav")
    score3.write(out, score3.master_bus(mixed))
    return out


def mux(frames: str, audio: str, out: str, w: int, h: int, dur: float, crop: str = "") -> None:
    vf = (f"{crop}scale={w}:{h}:flags=lanczos,fade=t=in:st=0:d=0.35,"
          f"fade=t=out:st={dur-0.4:.2f}:d=0.4,eq=contrast=1.06:saturation=1.10")
    subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error",
                    "-framerate", "30", "-i", os.path.join(frames, "f%05d.png"),
                    "-i", audio, "-vf", vf,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "17",
                    "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                    "-shortest", "-movflags", "+faststart", "-y", out], check=True)
    print(f"  -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list your ElevenLabs voices and exit")
    ap.add_argument("--frames-v", help="vertical frame directory from render.mjs")
    ap.add_argument("--frames-h", help="hero frame directory from render.mjs")
    ap.add_argument("--out", default="marketing/FINAL")
    ap.add_argument("--work", default="/tmp/titan_vo")
    for role in DEFAULT_VOICES:
        ap.add_argument(f"--voice-{role.lower()}", default=DEFAULT_VOICES[role])
    a = ap.parse_args()

    if a.list:
        list_voices()
        return

    voices = {r: getattr(a, f"voice_{r.lower()}") for r in DEFAULT_VOICES}
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    if a.frames_v:
        print("vertical:")
        wav = build_audio("vertical", voices, a.work)
        mux(a.frames_v, wav, f"{a.out}/Titan_Omega_Vertical_1080x1920.mp4", 1080, 1920, 18.0)
        mux(a.frames_v, wav, f"{a.out}/Titan_Omega_Square_1080x1080.mp4", 1080, 1080, 18.0,
            crop="crop=540:540:0:210,")
    if a.frames_h:
        print("hero:")
        wav = build_audio("hero", voices, a.work)
        mux(a.frames_h, wav, f"{a.out}/Titan_Omega_Hero_1920x1080.mp4", 1920, 1080, 32.3)
    if not (a.frames_v or a.frames_h):
        ap.error("give --frames-v and/or --frames-h (or --list)")


if __name__ == "__main__":
    main()
