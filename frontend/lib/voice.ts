// Shared Web Speech API helpers. Browser TTS voice lists load asynchronously,
// so we wait for them before picking a voice — otherwise the first click is
// silent. Urdu voices are rarely installed; a Hindi voice reading Devanagari
// text sounds the same to the ear, so callers can pass Hindi text with lang
// "hi" to get a working spoken Urdu briefing.

export type SpeakLang = "ur" | "en" | "hi";

export async function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  let voices = window.speechSynthesis.getVoices();
  if (voices.length > 0) return voices;

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve(window.speechSynthesis.getVoices());
    };
    window.speechSynthesis.onvoiceschanged = finish;
    let tries = 0;
    const timer = setInterval(() => {
      voices = window.speechSynthesis.getVoices();
      tries += 1;
      if (voices.length > 0 || tries > 15) {
        clearInterval(timer);
        finish();
      }
    }, 200);
  });
}

export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: SpeakLang,
): SpeechSynthesisVoice | null {
  if (lang === "en") {
    return voices.find((v) => v.lang.startsWith("en")) ?? null;
  }
  if (lang === "hi") {
    return (
      voices.find((v) => v.lang.startsWith("hi") || v.name.toLowerCase().includes("hindi")) ?? null
    );
  }
  // Urdu first, then Hindi (same phonetics, widely available).
  return (
    voices.find((v) => v.lang.startsWith("ur") || v.name.toLowerCase().includes("urdu")) ??
    voices.find((v) => v.lang.startsWith("hi") || v.name.toLowerCase().includes("hindi")) ??
    null
  );
}

// Chrome silently stops long utterances after ~15s (a long-standing bug), so we
// split text into sentence-sized chunks and queue them, plus run a pause/resume
// keep-alive while speaking. This is what makes long Urdu briefings finish.
function chunkText(text: string, maxLen = 160): string[] {
  const parts = text
    .split(/(?<=[.!؟?۔])\s+/u)
    .flatMap((s) => {
      if (s.length <= maxLen) return [s];
      const words = s.split(" ");
      const out: string[] = [];
      let cur = "";
      for (const w of words) {
        if ((cur + " " + w).trim().length > maxLen) {
          if (cur) out.push(cur.trim());
          cur = w;
        } else {
          cur = (cur + " " + w).trim();
        }
      }
      if (cur) out.push(cur.trim());
      return out;
    })
    .filter(Boolean);
  return parts.length ? parts : [text];
}

export async function speakText(
  text: string,
  lang: SpeakLang,
  onEnd?: () => void,
): Promise<boolean> {
  if (typeof window === "undefined" || !window.speechSynthesis) {
    onEnd?.();
    return false;
  }
  const synth = window.speechSynthesis;
  const voices = await loadVoices();
  synth.cancel();

  const voice = pickVoice(voices, lang);
  const chunks = chunkText(text);

  // Keep-alive: nudge the engine so Chrome doesn't stall mid-briefing.
  const keepAlive = setInterval(() => {
    try {
      if (!synth.speaking) return;
      synth.pause();
      synth.resume();
    } catch {
      /* no-op */
    }
  }, 8000);

  let finished = 0;
  const done = () => {
    finished += 1;
    if (finished >= chunks.length) {
      clearInterval(keepAlive);
      onEnd?.();
    }
  };

  for (const chunk of chunks) {
    const u = new SpeechSynthesisUtterance(chunk);
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    } else {
      u.lang = lang === "en" ? "en-US" : lang === "hi" ? "hi-IN" : "ur-PK";
    }
    u.rate = lang === "en" ? 1.0 : 0.92;
    u.pitch = 1.0;
    u.onend = done;
    u.onerror = done;
    synth.speak(u); // queues after the previous chunk
  }

  setTimeout(() => {
    try {
      synth.resume();
    } catch {
      /* no-op */
    }
  }, 150);
  return voice !== null;
}
