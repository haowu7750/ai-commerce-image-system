import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#17201d",
        canvas: "#f3f5ef",
        panel: "#fffdf8",
        brand: {
          50: "#eefaf3",
          100: "#d9f3e2",
          500: "#1f8f5f",
          600: "#14744b",
          700: "#105d3e"
        },
        amberline: "#dca951"
      },
      boxShadow: {
        card: "0 18px 50px rgba(30, 45, 38, 0.08)"
      }
    },
  },
  plugins: [],
};

export default config;
