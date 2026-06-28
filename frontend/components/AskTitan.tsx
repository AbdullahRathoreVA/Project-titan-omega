"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Mic, MicOff, Send, Sparkles, Volume2 } from "lucide-react";
import { speakText } from "@/lib/voice";

type Lang = "en" | "ur";
type Turn = { role: "you" | "titan"; text: string };

// Minimal typing for the Web Speech API (not in standard TS lib).
/* eslint-disable @typescript-eslint/no-explicit-any */
function getRecognition(): any {
  if (typeof window === "undefined") return null;
  const w = window as any;
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
  return SR ? new SR() : null;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export function AskTitan() {
  const [lang, setLang] = useState<Lang>("ur");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceOut, setVoiceOut] = useState(true);
  const recRef = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const endRef = useRef<HTMLDivElement | null>(null);

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
      try {
        const res = await fetch("/api/assistant", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q, lang }),
        });
        const data = res.ok ? await res.json() : null;
        const answer =
          data?.answer ??
          (lang === "ur"
            ? "معذرت باس، سرور سے جواب نہیں ملا۔ دوبارہ کوشش کریں۔"
            : "Sorry Boss, no answer from the core. Please try again.");
        setTurns((t) => [...t, { role: "titan", text: answer }]);
        if (voiceOut) void speakText(answer, lang);
      } catch {
        setTurns((t) => [
          ...t,
          { role: "titan", text: lang === "ur" ? "رابطہ میں مسئلہ۔" : "Connection issue." },
        ]);
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
    rec.lang = lang === "ur" ? "ur-PK" : "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
      const said = e.results[0][0].transcript;
      setInput(said);
      void ask(said);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }, [listening, lang, ask]);

  const placeholder =
    lang === "ur"
      ? "سوال پوचھیں… مثلاً: آج کتنے نئے یوزرز آئے؟"
      : "Ask anything… e.g. How many new users today?";

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Ask Titan — عبداللہ باس</h2>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setLang("ur")}
            className={`rounded px-2 py-0.5 text-[11px] ${
              lang === "ur" ? "bg-hud-violet/20 text-hud-violet" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            اردو
          </button>
          <button
            onClick={() => setLang("en")}
            className={`rounded px-2 py-0.5 text-[11px] ${
              lang === "en" ? "bg-hud-violet/20 text-hud-violet" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            EN
          </button>
          <button
            onClick={() => setVoiceOut((v) => !v)}
            title="Speak answers aloud"
            className={`ml-1 rounded p-1 ${
              voiceOut ? "text-hud-emerald" : "text-slate-600"
            }`}
          >
            <Volume2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      <div className="scroll-thin max-h-72 space-y-2 overflow-y-auto p-3" dir={lang === "ur" ? "rtl" : "ltr"}>
        {turns.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">
            {lang === "ur"
              ? "باس، کوئی بھی سوال پوचھیں — آواز یا ٹیکسٹ سے۔"
              : "Boss, ask me anything — by voice or text."}
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
            {lang === "ur" ? "ٹائٹن سوच رہا ہے…" : "Titan is thinking…"}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="flex items-center gap-2 border-t border-edge/60 p-3">
        <button
          onClick={toggleMic}
          title={lang === "ur" ? "بول کر پوचھیں" : "Speak your question"}
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
          dir={lang === "ur" ? "rtl" : "ltr"}
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
