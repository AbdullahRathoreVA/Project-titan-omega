"use client";

import { useCallback, useEffect, useState } from "react";
import { Volume2, VolumeX, Loader2 } from "lucide-react";
import type { EmpireStatus } from "@/lib/types";
import { speakText } from "@/lib/voice";

export function UrduVoiceAssistant({ status }: { status: EmpireStatus | null }) {
  const [speaking, setSpeaking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      setSupported(false);
    }
  }, []);

  const speak = useCallback(async () => {
    if (!supported || speaking || loading) return;
    setLoading(true);

    try {
      const res = await fetch("/api/voice-report", { cache: "no-store" });
      const data = res.ok ? await res.json() : null;

      const mrr = status?.mrr ?? 0;
      const traffic = status?.traffic ?? 0;
      const active = status?.active_agents ?? 0;
      const total = status?.total_agents ?? 102;
      const opps = status?.open_opportunities ?? 0;
      const health = status?.health ?? 0;

      const earningLine =
        mrr === 0
          ? "ابھی تک کوئی آمدنی نہیں ہوئی۔ لیکن ایجنٹ پہلا آرڈر لانے کے لیے کام کر رہے ہیں۔"
          : `اب تک آپ نے کل ${mrr.toFixed(0)} ڈالر کمائے ہیں۔`;

      const fallback =
        `السلام و علیکم عبداللہ باس! آپ کی امپائر کی تازہ رپورٹ یہ ہے۔ ` +
        `${earningLine} ` +
        `ویب سائٹ ٹریفک ${traffic.toFixed(0)} وزیٹرز ہے۔ ` +
        `اس وقت ${active} ڈیجیٹل ملازمین کام کر رہے ہیں، کل ${total} میں سے۔ ` +
        `${opps} نئے مواقع دستیاب ہیں۔ ` +
        `امپائر کی صحت ${health.toFixed(0)} فیصد ہے۔ ` +
        `باس، آگے بڑھتے رہیں، کامیابی یقینی ہے!`;

      const urduText = data?.urdu ?? fallback;

      setLoading(false);
      setSpeaking(true);
      await speakText(urduText, "ur", () => setSpeaking(false));
    } catch {
      setSpeaking(false);
      setLoading(false);
    }
  }, [supported, speaking, loading, status]);

  const stop = useCallback(() => {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }, []);

  if (!supported) return null;

  return (
    <button
      onClick={speaking ? stop : speak}
      disabled={loading}
      title={speaking ? "آواز بند کریں" : "اردو میں رپورٹ سنیں — عبداللہ باس"}
      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all ${
        speaking
          ? "animate-pulse border-hud-amber/60 bg-hud-amber/10 text-hud-amber"
          : loading
          ? "border-edge bg-panel/80 text-slate-500"
          : "border-edge bg-panel/80 text-slate-300 hover:border-hud-amber/40 hover:text-hud-amber"
      }`}
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : speaking ? (
        <VolumeX className="h-3.5 w-3.5" />
      ) : (
        <Volume2 className="h-3.5 w-3.5" />
      )}
      {speaking ? "رکیں ◼" : loading ? "لوڈ ہو رہا ہے…" : "🎙 اردو رپورٹ — باس"}
    </button>
  );
}
