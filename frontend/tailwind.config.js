/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Professional white/slate console palette
        paper: "#FFFFFF",
        "paper-dim": "#F6F7F8",
        panel: "#FFFFFF",
        ink: "#0F1522",
        "ink-soft": "#4B5563",
        line: "#E4E7EB",
        "line-soft": "#EDEFF2",

        // semantic states -- muted, professional, matching enterprise
        // security-tool conventions (green/red/amber/gray)
        pass: "#0A7A4C",
        "pass-bg": "#E7F5EC",
        fail: "#B3261E",
        "fail-bg": "#FCEBEA",
        review: "#B4590A",
        "review-bg": "#FDF0DF",
        missing: "#667085",
        "missing-bg": "#F0F1F3",

        accent: "#2653D6",
        "accent-bg": "#EAF0FE",
      },
      fontFamily: {
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
        display: ["var(--font-space-grotesk)", "var(--font-plex-sans)", "sans-serif"],
      },
      borderRadius: {
        panel: "16px",
      },
    },
  },
  plugins: [],
};
