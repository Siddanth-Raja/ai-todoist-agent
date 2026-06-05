import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#070708",
        panel: "#141416",
        line: "rgba(255,255,255,0.11)",
        pearl: "#f6f1e8",
        mist: "#aeb7c7",
        moss: "#a7e8c4",
        coral: "#ff9b8a",
        gold: "#f5d681",
        iris: "#b7a7ff",
      },
      boxShadow: {
        glow: "0 24px 80px rgba(167, 232, 196, 0.14)",
        soft: "0 28px 90px rgba(0, 0, 0, 0.36)",
        card: "0 18px 60px rgba(0, 0, 0, 0.24)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
