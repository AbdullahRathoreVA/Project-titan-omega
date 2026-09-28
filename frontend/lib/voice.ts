// Shared Web Speech API helpers. Browser TTS voice lists load asynchronously,
// so we wait for them before picking a voice, otherwise the first click is
// silent. Urdu voices are rarely installed; a Hindi voice reading Devanagari
// sounds the same, so callers can pass Hindi text with lang "hi" to get a
// working spoken Urdu briefing.

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

/**
 * True when Urdu was asked for and no Urdu voice exists on this device, so a
 * Hindi voice is speaking. Shown in the UI: the phonetics carry over, but
 * the user should know why it doesn't sound quite like Urdu.
 */
export function usedUrduFallback(
  voices: SpeechSynthesisVoice[],
  lang: string,
): boolean {
  if (lang !== "ur") return false;
  const hasUrdu = voices.some(
    (v) => v.lang.toLowerCase().startsWith("ur") || /urdu/i.test(v.name),
  );
  return !hasUrdu;
}

// Broadcast speaking state so visuals (the holographic founder) can react.
export function emitSpeech(speaking: boolean) {
  try {
    window.dispatchEvent(new CustomEvent("titan-speech", { detail: { speaking } }));
  } catch {
    /* silent */
  }
}

// One impulse per spoken word. Browsers don't expose synthesized speech to
// the audio graph, so a visualiser can't sample the waveform; `onboundary` is
// the only real speech-timed signal available. VoiceSphere drives its
// deformation from this.
export function emitSpeechWord() {
  try {
    window.dispatchEvent(new CustomEvent("titan-speech-word"));
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
    // A real Urdu voice first (ur-PK or ur-IN). Only if none is installed do we
    // fall back to Hindi, which shares Urdu's phonetics and ships far more
    // widely. `usedUrduFallback` reports when that happens.
    const real = voices.find((v) => byTag(v) || byName(v));
    if (real) return real;
    return (
      voices.find(
        (v) => v.lang.toLowerCase().startsWith("hi") || /hindi/i.test(v.name),
      ) ?? null
    );
  }
  // Prefer non-local (higher-quality online) voices when several match.
  const matches = voices.filter((v) => byTag(v) || byName(v));
  return matches.find((v) => !v.localService) ?? matches[0] ?? null;
}

// Chrome silently stops long utterances after ~15s, so text is split into
// sentence-sized chunks and queued, with a keep-alive running while speaking.
// That's what lets long Urdu briefings finish.
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

// TTS engines read punctuation and symbols aloud: a caption like "**Free**
// audit 💡 #SEO https://titanomega-ai.com/join" comes out as "asterisk
// asterisk Free... hash S E O h t t p colon slash slash...". Markup is for the
// eye, so it's stripped before speaking.
//
// Not applied to the displayed text - the reader still sees the emoji and the
// link. Only the spoken copy is cleaned.
const URL_RE = /\bhttps?:\/\/\S+/g;
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu;

export function speakable(text: string): string {
  return (text || "")
    // Links: skip them rather than spelling them out character by character.
    .replace(URL_RE, " ")
    // **bold**, *italic*, __underline__, `code`, ~~strike~~
    .replace(/[*_`~]{1,3}/g, "")
    // Markdown headings and blockquotes at line starts.
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    // Bullet markers, which otherwise become "dash" or "star" every line.
    .replace(/^\s*[-•·]\s+/gm, "")
    // #hashtags read as "hash word" - keep the word, drop the hash.
    .replace(/(^|\s)#(\w)/g, "$1$2")
    .replace(EMOJI_RE, " ")
    // Table pipes and rules.
    .replace(/[|]{1,}/g, " ")
    .replace(/^\s*[-=]{3,}\s*$/gm, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
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
  // Clean once, here, so every caller gets it without having to remember.
  text = speakable(text);
  if (!text) {
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

  // Keep-alive: resume() only, never pause(). Chrome kills its online (Google)
  // voices on pause, which silences non-English speech.
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
    u.onboundary = (ev) => {
      if (ev.name === "word" || ev.charLength) emitSpeechWord();
    };
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
