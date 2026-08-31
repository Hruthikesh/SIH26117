/** Colour + glyph vocabulary. Every signal also has a text form (no colour-only meaning). */

export const theme = {
  accent: "cyanBright",
  dim: "gray",
  ok: "green",
  warn: "yellow",
  bad: "red",
  border: "gray",
} as const;

export const glyphs = {
  logo: "✦",
  sealed: "🔒",
  unsealed: "⚠",
  tool: "●",
  toolResult: "⎿",
  done: "✔",
  fail: "✘",
  todo: "☐",
  doing: "◐",
  spinnerFrames: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
} as const;
