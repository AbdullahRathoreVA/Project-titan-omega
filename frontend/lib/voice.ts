// Shared Web Speech API helpers. Browser TTS voice lists load asynchronously,
// so we wait for them before picking a voice — otherwise the first click is
// silent. Urdu voices are rare; we fall back ur -> hi (phonetically close) ->
// default so the report always speaks aloud.

export async function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  const existing = window.speechSynthesis.getVoices();
  if (existing.length > 0) return existing;
  return new Promise((resolve) => {
    const done = () => resolve(window.speechSynthesis.getVoices());
    window.speechSynthesis.onvoiceschanged = done;
    // Safety timeout in case the event never fires.
    setTimeout(done, 1200);
  });
}

export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: "ur" | "en",
): SpeechSynthesisVoice | null {
  if (lang === "en") {
    return voices.find((v) => v.lang.startsWith("en")) ?? null;
  }
  // Urdu first, then Hindi (same phonetics, widely available), then anything.
  return (
    voices.find((v) => v.lang.startsWith("ur") || v.name.toLowerCase().includes("urdu")) ??
    voices.find((v) => v.lang.startsWith("hi") || v.name.toLowerCase().includes("hindi")) ??
    null
  );
}

export async function speakText(text: string, lang: "ur" | "en", onEnd?: () => void) {
  if (typeof window === "undefined" || !window.speechSynthesis) {
    onEnd?.();
    return;
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
  u.rate = lang === "ur" ? 0.9 : 1.0;
  u.pitch = 1.0;
  if (onEnd) {
    u.onend = onEnd;
    u.onerror = onEnd;
  }
  window.speechSynthesis.speak(u);
}
