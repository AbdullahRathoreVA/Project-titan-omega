// Shared Web Speech API helpers. Browser TTS voice lists load asynchronously,
// so we wait for them before picking a voice — otherwise the first click is
// silent. Urdu voices are rare; we fall back ur -> hi (phonetically close) ->
// default so the report is as likely as possible to speak aloud.

export async function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  let voices = window.speechSynthesis.getVoices();
  if (voices.length > 0) return voices;

  // Voices (esp. Chrome's online voices) can take a moment to populate. Wait for
  // the onvoiceschanged event, and also poll, up to ~3 seconds.
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
  lang: "ur" | "en",
): SpeechSynthesisVoice | null {
  if (lang === "en") {
    return voices.find((v) => v.lang.startsWith("en")) ?? null;
  }
  // Urdu first, then Hindi (same phonetics, widely available).
  return (
    voices.find((v) => v.lang.startsWith("ur") || v.name.toLowerCase().includes("urdu")) ??
    voices.find((v) => v.lang.startsWith("hi") || v.name.toLowerCase().includes("hindi")) ??
    null
  );
}

// Returns true if a voice suitable for the language was found (so callers can
// surface a hint when Urdu TTS isn't installed on the device).
export async function speakText(
  text: string,
  lang: "ur" | "en",
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
    u.lang = lang === "ur" ? "ur-PK" : "en-US";
  }
  u.rate = lang === "ur" ? 0.92 : 1.0;
  u.pitch = 1.0;
  if (onEnd) {
    u.onend = onEnd;
    u.onerror = onEnd;
  }
  window.speechSynthesis.speak(u);
  // Chrome bug workaround: speech sometimes pauses immediately on long text.
  setTimeout(() => {
    try {
      window.speechSynthesis.resume();
    } catch {
      /* no-op */
    }
  }, 150);
  return voice !== null;
}
