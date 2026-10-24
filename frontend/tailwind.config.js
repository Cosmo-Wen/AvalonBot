/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        medieval: {
          black: "#0a0a0f",
          deeper: "#0e0e15",
          dark: "#14141e",
          surface: "#1c1c28",
          elevated: "#242432",
          border: "#2a2a3a",
          "border-bright": "#3a3a4e",
          gold: "#c9a84c",
          "gold-dim": "#8a7535",
          "gold-bright": "#e8c95a",
          "gold-mist": "rgba(201, 168, 76, 0.08)",
          crimson: "#8b1a1a",
          "crimson-bright": "#c42b2b",
          blood: "#6b0f0f",
          good: "#2e9e5b",
          "good-dim": "#1e6b3d",
          evil: "#c42b2b",
          "evil-dim": "#8b1a1a",
          parchment: "#e8dcc8",
          "parchment-dim": "#b8a88a",
          "parchment-muted": "#8a7e6e",
          silver: "#9a9aaa",
          merlin: "#7a5af5",
        },
      },
      fontFamily: {
        display: ['"Cinzel"', "serif"],
        body: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: {
        bezel: "1.5rem",
        "bezel-inner": "calc(1.5rem - 0.375rem)",
      },
      animation: {
        "speak-pulse":
          "speakPulse 1.4s cubic-bezier(0.32, 0.72, 0, 1) infinite",
        "glow-ring":
          "glowRing 2.2s cubic-bezier(0.32, 0.72, 0, 1) infinite",
        "fade-up":
          "fadeUp 0.7s cubic-bezier(0.32, 0.72, 0, 1) forwards",
        "vote-in":
          "voteIn 0.5s cubic-bezier(0.32, 0.72, 0, 1) forwards",
        "shimmer":
          "shimmer 2.4s cubic-bezier(0.32, 0.72, 0, 1) infinite",
        "float":
          "float 4s cubic-bezier(0.32, 0.72, 0, 1) infinite",
      },
      keyframes: {
        speakPulse: {
          "0%, 100%": { transform: "scale(1)", opacity: "0.85" },
          "50%": { transform: "scale(1.06)", opacity: "1" },
        },
        glowRing: {
          "0%, 100%": {
            boxShadow:
              "0 0 16px 3px rgba(201, 168, 76, 0.2), inset 0 0 8px 1px rgba(201, 168, 76, 0.05)",
          },
          "50%": {
            boxShadow:
              "0 0 32px 8px rgba(201, 168, 76, 0.45), inset 0 0 16px 2px rgba(201, 168, 76, 0.12)",
          },
        },
        fadeUp: {
          from: { transform: "translateY(16px)", opacity: "0", filter: "blur(4px)" },
          to: { transform: "translateY(0)", opacity: "1", filter: "blur(0)" },
        },
        voteIn: {
          from: { transform: "scale(0.4) rotateY(90deg)", opacity: "0" },
          to: { transform: "scale(1) rotateY(0deg)", opacity: "1" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
      transitionTimingFunction: {
        fluid: "cubic-bezier(0.32, 0.72, 0, 1)",
        spring: "cubic-bezier(0.175, 0.885, 0.32, 1.275)",
      },
    },
  },
  plugins: [],
};
