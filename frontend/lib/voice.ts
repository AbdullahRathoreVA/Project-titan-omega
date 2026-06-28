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

export async function speakText(
  text: string,
  lang: SpeakLang,
  onEnd?: () => void,
): Promise<boolean> {
  if (typeof window === "undefined" || !window.speechSynthesis) {
    onEnd?.();
    return false;
  }
  const voices = await loadVoices();
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  const voice = pickVoice(voices, lang);
  if (voice) {
    u.voice = voice;
    u.lang = voice.lang;
  } else {
    u.lang = lang === "en" ? "en-US" : lang === "hi" ? "hi-IN" : "ur-PK";
  }
  u.rate = lang === "en" ? 1.0 : 0.92;
  u.pitch = 1.0;
  if (onEnd) {
    u.onend = onEnd;
    u.onerror = onEnd;
  }
  window.speechSynthesis.speak(u);
  setTimeout(() => {
    try {
      window.speechSynthesis.resume();
    } catch {
      /* no-op */
    }
  }, 150);
  return voice !== null;
}
