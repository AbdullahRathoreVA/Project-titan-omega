// Futuristic UI sounds, synthesized live with WebAudio — no audio files, no
// bundle cost. Everything is wrapped in try/catch: sound must never break UI.

let ctx: AudioContext | null = null;

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

/** Speak lines with the browser's TTS voice. Sentence-chunked so Chrome's
 * ~15s utterance kill-switch can't cut a briefing mid-sentence. Queues after
 * anything already speaking (never cancels). Never throws. */
export function speak(text: string) {
  try {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const chunks = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    for (const chunk of chunks.length ? chunks : [text]) {
      const u = new SpeechSynthesisUtterance(chunk);
      u.rate = 0.96;
      u.pitch = 0.85;
      u.volume = 0.9;
      window.speechSynthesis.speak(u);
    }
  } catch {
    /* silent */
  }
}
