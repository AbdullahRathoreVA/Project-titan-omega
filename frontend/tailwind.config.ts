import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Command-center palette: deep space backdrop, cyan/emerald HUD accents.
        void: "#05070d",
        panel: "#0a0e1a",
        "panel-2": "#0d1322",
        edge: "#16203a",
        hud: {
          cyan: "#22d3ee",
          blue: "#3b82f6",
          emerald: "#34d399",
          amber: "#fbbf24",
          rose: "#fb7185",
          violet: "#a78bfa",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 0 24px -4px rgba(34,211,238,0.35)",
        "glow-emerald": "0 0 24px -4px rgba(52,211,153,0.35)",
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        sweep: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
        flicker: {
          "0%, 100%": { opacity: "1" },
          "92%": { opacity: "1" },
          "94%": { opacity: "0.7" },
          "96%": { opacity: "1" },
        },
      },
      animation: {
        pulseGlow: "pulseGlow 2.4s ease-in-out infinite",
        sweep: "sweep 6s linear infinite",
        flicker: "flicker 8s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
