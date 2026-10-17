import type { Config } from "tailwindcss";

/**
 * ISGEC AI design tokens.
 * Premium dark: charcoal gradient ground, glass panels, hairline borders,
 * one restrained orange accent. Gradients stay under 10% opacity -- the
 * interface should feel calm, not lit.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ground
        base: {
          950: "#080B10",
          900: "#0D1117",
        },
        // glass panels
        panel: {
          DEFAULT: "#11161D",
          raised: "#151B23",
          hover: "#1A212A",
        },
        accent: {
          DEFAULT: "#FF8C28",
          soft: "rgba(255,140,40,0.10)",
          glow: "rgba(255,140,40,0.18)",
        },
      },
      borderRadius: {
        xl: "12px",
        "2xl": "16px",
      },
      borderColor: {
        hair: "rgba(255,255,255,0.08)",
        "hair-strong": "rgba(255,255,255,0.14)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        // deliberately shallow -- no glow
        card: "0 1px 2px rgba(0,0,0,0.35), 0 8px 24px -12px rgba(0,0,0,0.5)",
        lift: "0 2px 4px rgba(0,0,0,0.4), 0 16px 40px -16px rgba(0,0,0,0.6)",
        pop: "0 24px 64px -16px rgba(0,0,0,0.7)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "rise": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "progress-indeterminate": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(400%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 240ms ease-out both",
        rise: "rise 320ms cubic-bezier(0.16,1,0.3,1) both",
        "slide-in-right": "slide-in-right 280ms cubic-bezier(0.16,1,0.3,1) both",
        "progress-indeterminate": "progress-indeterminate 1.4s ease-in-out infinite",
      },
      backgroundImage: {
        // the one background treatment: a single diagonal warm wash
        "app-ground":
          "radial-gradient(1100px 620px at 82% -8%, rgba(255,140,40,0.075), transparent 58%), radial-gradient(900px 700px at 8% 108%, rgba(90,130,255,0.045), transparent 60%)",
      },
    },
  },
  plugins: [],
};

export default config;