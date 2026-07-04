// Shared Web Speech API helpers. Browser TTS voice lists load asynchronously,
// so we wait for them before picking a voice — otherwise the first click is
// silent. Urdu voices are rarely installed; a Hindi voice reading Devanagari
// text sounds the same to the ear, so callers can pass Hindi text with lang
// "hi" to get a working spoken Urdu briefing.

// Any two-letter language code works; these are the ones Titan's UI offers.
export type SpeakLang = string;

// BCP-47 defaults per language (used for utterance lang + mic recognition).
export const LANG_TAGS: Record<string, string> = {
  en: "en-US",
  ur: "ur-PK",
  hi: "hi-IN",
  ar: "ar-SA",
  es: "es-ES",
  fr: "fr-FR",
  de: "de-DE",
  zh: "zh-CN",
  ja: "ja-JP",
  tr: "tr-TR",
  pt: "pt-BR",
  ru: "ru-RU",
};

export function langTag(lang: string): string {
  return LANG_TAGS[lang] ?? "en-US";
}

// Broadcast speaking state so visuals (the holographic Founder) can react.
export function emitSpeech(speaking: boolean) {
  try {
    window.dispatchEvent(new CustomEvent("titan-speech", { detail: { speaking } }));
  } catch {
    /* silent */
  }
}

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

// Voice-name hints — some engines label voices by language NAME, not tag.
const NAME_HINTS: Record<string, RegExp> = {
  en: /english/i,
  ur: /urdu/i,
  hi: /hindi|हिन्दी/i,
  ar: /arab|العربية/i,
  es: /spanish|español/i,
  fr: /french|français/i,
  de: /german|deutsch/i,
  zh: /chinese|mandarin|中文|普通话/i,
  ja: /japanese|日本語/i,
  tr: /turkish|türk/i,
  pt: /portug/i,
  ru: /russian|русский/i,
};

export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: SpeakLang,
): SpeechSynthesisVoice | null {
  const code = lang.toLowerCase();
  const byTag = (v: SpeechSynthesisVoice) =>
    v.lang.toLowerCase().replace("_", "-").split("-")[0] === code;
  const hint = NAME_HINTS[code];
  const byName = (v: SpeechSynthesisVoice) => (hint ? hint.test(v.name) : false);

  if (code === "ur") {
    // Urdu first, then Hindi (same phonetics, far more widely installed).
    return (
      voices.find((v) => byTag(v) || byName(v)) ??
      voices.find(
        (v) => v.lang.toLowerCase().startsWith("hi") || /hindi/i.test(v.name),
      ) ??
      null
    );
  }
  // Prefer non-local (higher-quality online) voices when several match.
  const matches = voices.filter((v) => byTag(v) || byName(v));
  return matches.find((v) => !v.localService) ?? matches[0] ?? null;
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
  // Chrome race: speak() immediately after cancel() gets silently swallowed.
  await new Promise((r) => setTimeout(r, 90));

  const voice = pickVoice(voices, lang);
  const chunks = chunkText(text);

  // Keep-alive: resume() only. NEVER pause() here — Chrome kills its online
  // (Google) voices on pause, which is exactly how non-English speech died.
  const keepAlive = setInterval(() => {
    try {
      if (synth.speaking) synth.resume();
    } catch {
      /* no-op */
    }
  }, 8000);

  emitSpeech(true);
  let finished = 0;
  const done = () => {
    finished += 1;
    if (finished >= chunks.length) {
      clearInterval(keepAlive);
      emitSpeech(false);
      onEnd?.();
    }
  };

  for (const chunk of chunks) {
    const u = new SpeechSynthesisUtterance(chunk);
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    } else {
      u.lang = langTag(lang);
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
