"use client";

import { useCallback, useEffect, useState } from "react";
import { Volume2, VolumeX, Loader2 } from "lucide-react";
import type { EmpireStatus } from "@/lib/types";
import { speakText } from "@/lib/voice";
import { apiBase, authHeaders } from "@/lib/api";
import { isCustomer } from "@/lib/session";

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
      // The founder's briefing needs his token now that it is not public; a
      // subscriber hears their own from /api/me/voice-report.
      const res = await fetch(`${apiBase()}/voice-report`, {
        cache: "no-store",
        headers: authHeaders(),
      });
      const data = res.ok ? await res.json() : null;

      const mrr = status?.mrr ?? 0;
      const active = status?.active_agents ?? 0;
      const total = status?.total_agents ?? 102;

      // Hindi (Devanagari) so the installed Hindi voice can actually read it.
      const hindiFallback = isCustomer()
        ? `अस्सलाम वालेकुम! ${active} एजेंट्स काम कर रहे हैं, कुल ${total} में से। आगे बढ़ते रहिए!`
        : mrr === 0
          ? `अस्सलाम वालेकुम अब्दुल्लाह! अभी तक कोई आमदनी नहीं हुई। ${active} एजेंट्स काम कर रहे हैं। आगे बढ़ते रहिए!`
          : `अस्सलाम वालेकुम अब्दुल्लाह! अब तक आपने कुल ${mrr.toFixed(0)} डॉलर कमाए हैं। ${active} एजेंट्स काम कर रहे हैं, कुल ${total} में से। मुबारक हो अब्दुल्लाह!`;

      const hindiText = data?.hindi ?? hindiFallback;

      setLoading(false);
      setSpeaking(true);
      await speakText(hindiText, "hi", () => setSpeaking(false));
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
      title={speaking ? "آواز بند کریں" : isCustomer() ? "اردو رپورٹ سنیں" : "اردو رپورٹ سنیں — عبداللہ"}
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
      {speaking ? "رکیں ◼" : loading ? "لوڈ ہو رہا ہے…" : isCustomer() ? "🎙 اردو رپورٹ" : "🎙 اردو رپورٹ — عبداللہ"}
    </button>
  );
}
