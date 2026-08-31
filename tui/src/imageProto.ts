/** Inline terminal graphics: Kitty and iTerm2/WezTerm protocols, detected at start. */

export type ImageProtocol = "kitty" | "iterm" | "none";

export function detectImageProtocol(env: NodeJS.ProcessEnv = process.env): ImageProtocol {
  if (env["KITTY_WINDOW_ID"] || (env["TERM"] ?? "").includes("kitty")) return "kitty";
  const program = env["TERM_PROGRAM"] ?? "";
  if (program === "iTerm.app" || program === "WezTerm" || env["WEZTERM_EXECUTABLE"]) return "iterm";
  if (env["KONSOLE_VERSION"]) return "kitty";
  return "none";
}

/** Escape sequence rendering a PNG inline, or null when unsupported. */
export function inlineImage(
  png: Buffer,
  protocol: ImageProtocol,
  opts: { columns?: number } = {},
): string | null {
  const b64 = png.toString("base64");
  if (protocol === "iterm") {
    const size = opts.columns ? `width=${opts.columns};` : "";
    return `]1337;File=inline=1;${size}preserveAspectRatio=1:${b64}`;
  }
  if (protocol === "kitty") {
    const chunks: string[] = [];
    const chunkSize = 4096;
    for (let i = 0; i < b64.length; i += chunkSize) {
      const part = b64.slice(i, i + chunkSize);
      const isFirst = i === 0;
      const hasMore = i + chunkSize < b64.length ? 1 : 0;
      const control = isFirst ? `a=T,f=100,m=${hasMore}` : `m=${hasMore}`;
      chunks.push(`_G${control};${part}\\`);
    }
    return chunks.join("");
  }
  return null;
}
