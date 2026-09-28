// UI sounds synthesized live with WebAudio - no audio files, no bundle cost.
// Everything is wrapped in try/catch; sound must never break the UI.

import { authHeaders } from "@/lib/api";

let ctx: AudioContext | null = null;

// Broadcast speaking state so the HoloFounder / mouth animations can react.
function emitSpeech(speaking: boolean) {
  try {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("titan-speech", { detail: { speaking } }));
    }
  } catch {
    /* silent */
  }
}

// One reusable <audio> element for premium (ElevenLabs) playback. Reusing a
// single element that was unlocked inside a gesture is what lets iOS play
// audio later. A tiny silent WAV primes it.
let mediaEl: HTMLAudioElement | null = null;
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

function ac(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    if (!ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

// --- Cross-device audio unlock -------------------------------------------
// Browsers (especially iOS Safari, Android Chrome, macOS Safari) refuse to play
// WebAudio or speech synthesis unless the first call happens inside a real user
// gesture (tap/click). `unlockAudio()` must be called synchronously from a
// click/tap handler: it resumes the audio context and primes the TTS engine so
// later speak()/tone() calls work for the rest of the session.
let audioUnlocked = false;

export function unlockAudio(): void {
  if (audioUnlocked) return;
  try {
    const a = ac();
    if (a && a.state === "suspended") void a.resume();
    const ss = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (ss) {
      try {
        ss.resume();
      } catch {
        /* silent */
      }
      // A silent utterance spoken inside the gesture is what unlocks TTS on
      // iOS/Android; after this, deferred speak() calls are allowed.
      const primer = new SpeechSynthesisUtterance(" ");
      primer.volume = 0;
      ss.speak(primer);
      ss.getVoices(); // warm the (async) voice list
    }
    // Prime the media element for premium (ElevenLabs) playback inside the gesture.
    try {
      if (!mediaEl) mediaEl = new Audio();
      mediaEl.src = SILENT_WAV;
      const p = mediaEl.play();
      if (p && typeof p.then === "function") p.then(() => mediaEl?.pause()).catch(() => {});
    } catch {
      /* silent */
    }
    audioUnlocked = true;
  } catch {
    /* silent */
  }
}

export function audioIsUnlocked(): boolean {
  return audioUnlocked;
}

function tone(freq: number, dur: number, vol: number, type: OscillatorType = "sine", delay = 0) {
  const a = ac();
  if (!a) return;
  try {
    const t0 = a.currentTime + delay;
    const o = a.createOscillator();
    const g = a.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g).connect(a.destination);
    o.start(t0);
    o.stop(t0 + dur + 0.05);
  } catch {
    /* silent */
  }
}

/** Tiny hover blip. */
export function blip() {
  tone(1180, 0.05, 0.015);
}

/** Tab / action click — two-tone. */
export function tap() {
  tone(620, 0.06, 0.03);
  tone(930, 0.09, 0.025, "sine", 0.05);
}

/** Success chime — rising triad. */
export function chime() {
  tone(523, 0.14, 0.02);
  tone(659, 0.14, 0.02, "sine", 0.1);
  tone(784, 0.22, 0.025, "sine", 0.2);
}

/** Boot-up sequence — slow cinematic rise with a deep base layer. */
export function bootSound() {
  tone(65, 2.2, 0.03, "sine");
  tone(130, 1.8, 0.02, "triangle", 0.2);
  tone(392, 0.5, 0.018, "sine", 1.0);
  tone(523, 0.5, 0.018, "sine", 1.5);
  tone(659, 0.6, 0.02, "sine", 2.0);
  tone(784, 0.9, 0.025, "sine", 2.5);
  tone(1046, 1.4, 0.02, "sine", 3.0);
}

// Cache a good English voice once the list is available. iOS/Android load
// voices asynchronously, so getVoices() is often empty on first call.
let cachedVoice: SpeechSynthesisVoice | null = null;

function pickVoice(ss: SpeechSynthesis): SpeechSynthesisVoice | null {
  try {
    if (cachedVoice) return cachedVoice;
    const voices = ss.getVoices();
    if (!voices.length) return null;
    cachedVoice =
      voices.find((v) => /^en[-_]US/i.test(v.lang)) ||
      voices.find((v) => /^en/i.test(v.lang)) ||
      voices[0];
    return cachedVoice;
  } catch {
    return null;
  }
}

if (typeof window !== "undefined" && window.speechSynthesis) {
  // Recompute the cached voice whenever the browser finishes loading voices.
  try {
    window.speechSynthesis.onvoiceschanged = () => {
      cachedVoice = null;
      pickVoice(window.speechSynthesis);
    };
  } catch {
    /* silent */
  }
}

/** Speak lines with the browser's TTS voice. Sentence-chunked so Chrome's
 * ~15s utterance kill-switch can't cut a briefing mid-sentence. Queues after
 * anything already speaking (never cancels). Resumes first (Chrome/iOS can
 * leave the queue paused). Never throws. */
export function speak(text: string) {
  try {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const ss = window.speechSynthesis;
    try {
      ss.resume();
    } catch {
      /* silent */
    }
    const parts = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    const chunks = parts.length ? parts : [text];
    const voice = pickVoice(ss);
    emitSpeech(true);
    let finished = 0;
    const done = () => {
      finished += 1;
      if (finished >= chunks.length) emitSpeech(false);
    };
    for (const chunk of chunks) {
      const u = new SpeechSynthesisUtterance(chunk);
      if (voice) {
        u.voice = voice;
        u.lang = voice.lang;
      }
      u.rate = 0.96;
      u.pitch = 0.85;
      u.volume = 0.9;
      u.onend = done;
      u.onerror = done;
      ss.speak(u);
    }
  } catch {
    /* silent */
  }
}

/**
 * Premium voice via the backend ElevenLabs proxy (founder-only, free when no
 * key is set). If the backend returns audio (200), play it through the primed
 * media element; on any miss (204/403/no key/guest/error) run `fallback()`,
 * the browser voice, so speech never goes silent. Resolves when playback (or
 * the fallback) starts.
 */
export async function speakPremium(text: string, fallback: () => void): Promise<void> {
  let played = false;
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text }),
    });
    if (res.status === 200) {
      const buf = await res.arrayBuffer();
      if (buf.byteLength > 200) {
        played = await new Promise<boolean>((resolve) => {
          try {
            const url = URL.createObjectURL(new Blob([buf], { type: "audio/mpeg" }));
            const el = mediaEl ?? (mediaEl = new Audio());
            el.src = url;
            el.volume = 0.9;
            emitSpeech(true);
            const finish = (ok: boolean) => {
              emitSpeech(false);
              URL.revokeObjectURL(url);
              resolve(ok);
            };
            el.onended = () => finish(true);
            el.onerror = () => finish(false);
            const p = el.play();
            if (p && typeof p.then === "function") p.catch(() => finish(false));
          } catch {
            resolve(false);
          }
        });
      }
    }
  } catch {
    /* fall through to browser voice */
  }
  if (!played) fallback();
}
