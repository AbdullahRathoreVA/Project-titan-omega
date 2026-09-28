"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Mic, MicOff, Send, Sparkles, Volume2 } from "lucide-react";
import { langTag, loadVoices, speakText, usedUrduFallback } from "@/lib/voice";
import { speakPremium } from "@/lib/sound";
import { isGuest } from "@/lib/guest";
import { apiBase, authHeaders } from "@/lib/api";
import { isCustomer } from "@/lib/session";
import VoiceSphere from "./VoiceSphere";
import { VoiceSession } from "@/lib/voiceSession";

// Universal voice: Titan answers and SPEAKS in any of these languages.
const LANGS: [string, string][] = [
  ["en", "English"],
  ["ur", "اردو"],
  ["hi", "हिन्दी"],
  ["ar", "العربية"],
  ["es", "Español"],
  ["fr", "Français"],
  ["de", "Deutsch"],
  ["zh", "中文"],
  ["ja", "日本語"],
  ["tr", "Türkçe"],
  ["pt", "Português"],
  ["ru", "Русский"],
];
const RTL = new Set(["ur", "ar"]);

type Lang = string;
type Turn = { role: "you" | "titan"; text: string };

/* eslint-disable @typescript-eslint/no-explicit-any */
function getRecognition(): any {
  if (typeof window === "undefined") return null;
  const w = window as any;
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
  return SR ? new SR() : null;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export function AskTitan() {
  // A subscriber asks about their own businesses (/api/me/assistant). The
  // founder's assistant is briefed with his empire and greets him by name.
  const [customer] = useState(() => isCustomer());
  const [lang, setLang] = useState<Lang>(() => (isCustomer() ? "en" : "ur"));
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceOut, setVoiceOut] = useState(true);
  // Language code whose TTS voice is missing on this device (honest notice).
  const [voiceMissing, setVoiceMissing] = useState<string | null>(null);
  // Urdu asked for, but only a Hindi voice available on this device.
  const [urduFallback, setUrduFallback] = useState(false);
  const recRef = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const endRef = useRef<HTMLDivElement | null>(null);
  // One session per mounted panel, so the Voice Agents screen shows a
  // conversation rather than a fresh node per sentence. Every call inside is
  // best-effort: a guest is refused the whole /api/voice prefix and must still
  // be able to talk to Titan.
  const voiceRef = useRef<VoiceSession | null>(null);
  if (voiceRef.current === null && typeof window !== "undefined") {
    voiceRef.current = new VoiceSession("web", "titan-assistant");
  }

  // Close the session when the panel unmounts, otherwise it sits on the live
  // screen forever claiming to be in progress.
  useEffect(() => {
    const s = voiceRef.current;
    const leave = () => s?.endOnExit();
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      void s?.end();
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || busy) return;
      setTurns((t) => [...t, { role: "you", text: q }]);
      setInput("");
      setBusy(true);
      // Record the real conversation. `thinking` starts here so the latency
      // the Voice Agents screen reports is the actual wait for /api/assistant,
      // not a number invented to fill the dial.
      const vs = voiceRef.current;
      void vs?.turn("user", q, lang);
      void vs?.state("thinking");
      try {
        const res = await fetch(`${apiBase()}/assistant`, {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ question: q, lang }),
        });
        const data = res.ok ? await res.json() : null;
        const answer =
          data?.answer ??
          (lang === "ur"
            ? "معذرت، سرور سے جواب نہیں ملا۔ دوبارہ کوشش کریں۔"
            : "Sorry, no answer from the core. Please try again.");
        // 'spoken' is Hindi/Devanagari for Urdu so the Hindi voice can read it.
        const spoken = data?.spoken ?? answer;
        setTurns((t) => [...t, { role: "titan", text: answer }]);
        void vs?.turn("agent", answer, lang);
        // Only claim `speaking` when Titan is actually going to speak. With
        // voice output off it goes straight back to idle — the screen must not
        // animate a mouth that is closed.
        void vs?.state(voiceOut ? "speaking" : "idle");
        if (voiceOut) {
          // Back to idle when the speech genuinely finishes — speakText's
          // onEnd fires on the last chunk, so the screen stops showing
          // "speaking" at the moment the voice actually stops.
          const done = () => void vs?.state("idle");
          if (lang === "en" && !customer) {
            // Founder gets the premium ElevenLabs voice for English (if a key is
            // set); everyone else, and every other language, uses the browser voice.
            // A subscriber never spends the founder's ElevenLabs key.
            void speakPremium(answer, () => {
              void speakText(answer, "en", done).then((found) =>
                setVoiceMissing(found ? null : "en"),
              );
            }).then(done);
          } else {
            // Urdu is requested as "ur" so a real ur-PK voice is used when one
            // exists; pickVoice falls back to Hindi only if none is installed.
            // Previously this passed "hi" outright, which meant a device WITH
            // an Urdu voice never used it.
            void speakText(spoken, lang, done).then((found) =>
              setVoiceMissing(found ? null : lang),
            );
            if (lang === "ur") {
              void loadVoices().then((vs2) =>
                setUrduFallback(usedUrduFallback(vs2, "ur")),
              );
            } else {
              setUrduFallback(false);
            }
          }
        }
      } catch {
        setTurns((t) => [
          ...t,
          { role: "titan", text: lang === "ur" ? "رابطہ میں مسئلہ۔" : "Connection issue." },
        ]);
        // A failed exchange is still a real session event. Leaving it stuck on
        // "thinking" would show a hung agent on the live screen forever.
        void vs?.state("idle", "core unreachable");
      } finally {
        setBusy(false);
      }
    },
    [busy, lang, voiceOut]
  );

  const toggleMic = useCallback(() => {
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      void voiceRef.current?.state("idle");
      return;
    }
    const rec = getRecognition();
    if (!rec) {
      alert(
        lang === "ur"
          ? "آپ کا براؤزر وائس سپورٹ نہیں کرتا۔ Chrome استعمال کریں۔"
          : "Your browser doesn't support voice input. Use Chrome."
      );
      return;
    }
    rec.lang = langTag(lang);
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
      const said = e.results[0][0].transcript;
      setInput(said);
      void ask(said);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => {
      setListening(false);
      void voiceRef.current?.state("idle", "recognition error");
    };
    recRef.current = rec;
    setListening(true);
    // The mic is genuinely open now, so the state is true rather than assumed.
    void voiceRef.current?.state("listening");
    rec.start();
  }, [listening, lang, ask]);

  const placeholder =
    lang === "ur"
      ? customer
        ? "سوال پوچھیں… مثلاً: میری ویب سائٹ کا SEO کیسا ہے؟"
        : "سوال پوچھیں… مثلاً: آج کتنے نئے یوزرز آئے؟"
      : customer
        ? "Ask anything… e.g. How is my website's SEO?"
        : "Ask anything… e.g. How many new users today?";

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">{isGuest() || customer ? "Ask Titan" : "Ask Titan — عبداللہ"}</h2>
        </div>
        <div className="flex items-center gap-1.5">
          <select
            value={lang}
            onChange={(e) => {
              setLang(e.target.value);
              setVoiceMissing(null);
            }}
            title="Titan speaks your language"
            className="rounded-lg border border-edge bg-panel-2/60 px-2 py-1 text-[11px] text-slate-300 focus:border-hud-violet/40 focus:outline-none"
          >
            {LANGS.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
          <button
            onClick={() => setVoiceOut((v) => !v)}
            title="Speak answers aloud"
            className={`ml-1 rounded p-1 ${voiceOut ? "text-hud-emerald" : "text-slate-600"}`}
          >
            <Volume2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {/* The avatar slot. HoloFounder (R3F) is still in the repo if this is
          ever reverted — the sphere replaced it because it reacts to the real
          speech signal and costs no 3D library. */}
      <VoiceSphere height={240} listening={listening} />

      <div className="scroll-thin max-h-60 space-y-2 overflow-y-auto p-3" dir={RTL.has(lang) ? "rtl" : "ltr"}>
        {turns.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">
            {customer
              ? lang === "ur"
                ? "اپنے کاروبار کے بارے میں کوئی بھی سوال پوچھیں — آواز یا ٹیکسٹ سے۔"
                : "Ask me anything about your business — by voice or text."
              : lang === "ur"
                ? "عبداللہ، کوئی بھی سوال پوچھیں — آواز یا ٹیکسٹ سے۔"
                : "Abdullah, ask me anything — by voice or text."}
          </p>
        )}
        {turns.map((t, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className={`max-w-[85%] rounded-lg border p-2.5 text-xs ${
              t.role === "you"
                ? "ml-auto border-hud-cyan/30 bg-hud-cyan/5 text-slate-200"
                : "mr-auto border-hud-violet/30 bg-hud-violet/5 text-slate-200"
            }`}
          >
            <span className="mb-0.5 block text-[9px] uppercase tracking-wide text-slate-500">
              {t.role === "you" ? (lang === "ur" ? "آپ" : "You") : "Titan"}
            </span>
            {t.text}
          </motion.div>
        ))}
        {busy && (
          <div className="mr-auto max-w-[85%] rounded-lg border border-hud-violet/30 bg-hud-violet/5 p-2.5 text-xs text-slate-400">
            {lang === "ur" ? "ٹائٹن سوچ رہا ہے…" : "Titan is thinking…"}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Urdu is written in Arabic script, Hindi in Devanagari, and they share
          phonetics — so a Hindi voice reading transliterated Urdu is
          intelligible, and is what most devices fall back to. Saying so beats
          leaving an Urdu speaker to conclude Titan simply speaks Hindi. */}
      {urduFallback && !voiceMissing && (
        <div className="border-t border-hud-violet/20 bg-hud-violet/5 px-3 py-2 text-[10px] leading-relaxed text-hud-violet">
          کوئی اردو آواز انسٹال نہیں — ہندی آواز اردو الفاظ بول رہی ہے۔
          <span className="mt-0.5 block text-slate-400">
            No Urdu voice is installed, so a Hindi voice is speaking the Urdu
            words — the two share pronunciation, so it stays understandable.
            For a true Urdu voice, open Titan in{" "}
            <span className="font-semibold">Microsoft Edge</span>, or add Urdu
            under Windows Settings → Time &amp; Language → Speech.
          </span>
        </div>
      )}

      {voiceMissing && (
        <div className="border-t border-hud-amber/20 bg-hud-amber/5 px-3 py-2 text-[10px] leading-relaxed text-hud-amber">
          No {LANGS.find(([c]) => c === voiceMissing)?.[1] ?? voiceMissing} voice is installed in this
          browser, so the answer is text-only. Fix: open Titan in <span className="font-semibold">Microsoft Edge</span>{" "}
          (natural voices for ALL languages, including اردو and العربية), or install the voice in
          Windows Settings → Time &amp; Language → Speech.
        </div>
      )}

      <div className="flex items-center gap-2 border-t border-edge/60 p-3">
        <button
          onClick={toggleMic}
          title={lang === "ur" ? "بول کر پوچھیں" : "Speak your question"}
          className={`rounded-lg border p-2 transition-colors ${
            listening
              ? "animate-pulse border-hud-rose/50 bg-hud-rose/10 text-hud-rose"
              : "border-edge bg-panel/80 text-slate-300 hover:border-hud-violet/40 hover:text-hud-violet"
          }`}
        >
          {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(input)}
          placeholder={placeholder}
          dir={RTL.has(lang) ? "rtl" : "ltr"}
          className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600 focus:border-hud-violet/40 focus:outline-none"
        />
        <button
          onClick={() => ask(input)}
          disabled={busy || !input.trim()}
          className="flex items-center gap-1.5 rounded-lg border border-hud-violet/40 bg-hud-violet/10 px-3 py-2 text-xs font-medium text-hud-violet transition-colors hover:bg-hud-violet/20 disabled:opacity-50"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
    </section>
  );
}
