/** Markdown → ANSI for the transcript: headings, emphasis, code, lists, tables, quotes. */

import { createRequire } from "node:module";

import chalk from "chalk";

type HighlightFn = (code: string, opts?: { language?: string }) => string;
let highlightFn: HighlightFn | null | undefined;

function highlight(code: string, language?: string): string {
  if (highlightFn === undefined) {
    try {
      const req = createRequire(import.meta.url);
      highlightFn = (req("cli-highlight") as { highlight: HighlightFn }).highlight ?? null;
    } catch {
      highlightFn = null;
    }
  }
  if (!highlightFn) return code;
  try {
    return highlightFn(code, language ? { language } : undefined);
  } catch {
    return code;
  }
}

function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, (_m, code: string) => chalk.cyan(code))
    .replace(/\*\*([^*]+)\*\*/g, (_m, bold: string) => chalk.bold(bold))
    .replace(/(?<![*\w])\*([^*\n]+)\*(?![*\w])/g, (_m, it: string) => chalk.italic(it))
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label: string, url: string) =>
      `${chalk.underline(label)} ${chalk.dim(`(${url})`)}`,
    );
}

function renderTable(rows: string[]): string {
  const cells = rows
    .filter((r) => !/^\s*\|?[\s:-]+\|[\s|:-]*$/.test(r))
    .map((r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim()));
  if (cells.length === 0) return rows.join("\n");
  const widths: number[] = [];
  for (const row of cells) {
    row.forEach((cell, i) => {
      widths[i] = Math.max(widths[i] ?? 0, Math.min(cell.length, 40));
    });
  }
  return cells
    .map((row, rowIndex) => {
      const line = row
        .map((cell, i) => cell.slice(0, 40).padEnd(widths[i] ?? 0))
        .join(chalk.dim(" │ "));
      return rowIndex === 0 ? chalk.bold(line) : line;
    })
    .join("\n");
}

export function renderMarkdown(source: string, width = 100): string {
  const out: string[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    const fence = line.match(/^```(\w+)?\s*$/);
    if (fence) {
      const language = fence[1];
      const body: string[] = [];
      index++;
      while (index < lines.length && !/^```\s*$/.test(lines[index] ?? "")) {
        body.push(lines[index] ?? "");
        index++;
      }
      index++; // closing fence
      const code = highlight(body.join("\n"), language);
      out.push(
        code
          .split("\n")
          .map((codeLine) => "  " + codeLine)
          .join("\n"),
      );
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const tableRows: string[] = [];
      while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index] ?? "")) {
        tableRows.push(lines[index] ?? "");
        index++;
      }
      out.push(renderTable(tableRows));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1]?.length ?? 1;
      const text = inline(heading[2] ?? "");
      out.push(level <= 2 ? chalk.bold.cyanBright(text) : chalk.bold(text));
      index++;
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      out.push(chalk.dim("│ " + inline(line.replace(/^\s*>\s?/, ""))));
      index++;
      continue;
    }
    const bullet = line.match(/^(\s*)[-*]\s+(.*)$/);
    if (bullet) {
      out.push(`${bullet[1] ?? ""}${chalk.dim("•")} ${inline(bullet[2] ?? "")}`);
      index++;
      continue;
    }
    const numbered = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
    if (numbered) {
      out.push(`${numbered[1] ?? ""}${chalk.dim(`${numbered[2]}.`)} ${inline(numbered[3] ?? "")}`);
      index++;
      continue;
    }
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      out.push(chalk.dim("─".repeat(Math.min(width, 60))));
      index++;
      continue;
    }
    out.push(inline(line));
    index++;
  }
  return out.join("\n");
}

/** Colourise a unified diff. */
export function renderDiff(diff: string): string {
  return diff
    .split("\n")
    .map((line) => {
      if (line.startsWith("+++") || line.startsWith("---")) return chalk.bold(line);
      if (line.startsWith("@@")) return chalk.cyan(line);
      if (line.startsWith("+")) return chalk.green(line);
      if (line.startsWith("-")) return chalk.red(line);
      return chalk.dim(line);
    })
    .join("\n");
}
