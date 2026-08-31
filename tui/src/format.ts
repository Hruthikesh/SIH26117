/** Small formatting helpers for the status line and cards. */

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const rest = s % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function fmtInr(amount: number): string {
  if (amount >= 1000) return `₹${(amount / 1000).toFixed(1)}k`;
  return `₹${amount.toFixed(amount < 10 ? 1 : 0)}`;
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, Math.max(0, max - 1)) + "…";
}

export function argsPreview(args: Record<string, unknown>, max = 90): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(args)) {
    const raw = typeof value === "string" ? value : JSON.stringify(value);
    parts.push(`${key}: ${truncate(String(raw).replace(/\n/g, "⏎"), 40)}`);
  }
  return truncate(parts.join(", "), max);
}

/** Simple subsequence fuzzy score; higher is better, -1 = no match. */
export function fuzzyScore(query: string, candidate: string): number {
  if (!query) return 0;
  const q = query.toLowerCase();
  const c = candidate.toLowerCase();
  let qi = 0;
  let score = 0;
  let streak = 0;
  for (let ci = 0; ci < c.length && qi < q.length; ci++) {
    if (c[ci] === q[qi]) {
      qi++;
      streak++;
      score += 1 + streak;
    } else {
      streak = 0;
    }
  }
  if (qi < q.length) return -1;
  return score - c.length * 0.01;
}
