/** /trace: navigable span tree of a run (SPEC §15.4). */

import React from "react";
import { Box, Text } from "ink";
import { fmtTokens, truncate } from "../format.js";
import { theme } from "../theme.js";

export interface SpanNode {
  span_id: string;
  parent_id: string | null;
  name: string;
  kind: string;
  start_ns: number;
  end_ns: number;
  status: string;
  attrs: Record<string, unknown>;
}

export interface TraceRow {
  span: SpanNode;
  depth: number;
}

export function flattenSpans(spans: SpanNode[], expanded: Set<string>): TraceRow[] {
  const children = new Map<string | null, SpanNode[]>();
  const ids = new Set(spans.map((s) => s.span_id));
  for (const span of spans) {
    const parent = span.parent_id && ids.has(span.parent_id) ? span.parent_id : null;
    const list = children.get(parent) ?? [];
    list.push(span);
    children.set(parent, list);
  }
  for (const list of children.values()) list.sort((a, b) => a.start_ns - b.start_ns);
  const rows: TraceRow[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const span of children.get(parent) ?? []) {
      rows.push({ span, depth });
      if (expanded.has(span.span_id)) visit(span.span_id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

function spanSummary(span: SpanNode): string {
  const ms = Math.max(0, Math.round((span.end_ns - span.start_ns) / 1e6));
  const attrs = span.attrs;
  const bits: string[] = [`${ms}ms`];
  if (span.kind === "llm.call") {
    const tokens = attrs["tokens"] as { prompt_tokens?: number; completion_tokens?: number } | undefined;
    if (attrs["model"]) bits.push(String(attrs["model"]));
    if (tokens) bits.push(`${fmtTokens(tokens.prompt_tokens ?? 0)}↑${fmtTokens(tokens.completion_tokens ?? 0)}↓`);
    if (attrs["cache_hit"]) bits.push("cache");
  }
  if (span.kind === "tool.call" && attrs["tool"]) bits.push(String(attrs["tool"]));
  if (span.status === "error") bits.push("ERROR");
  return bits.join(" · ");
}

export function TraceViewComponent({
  runId,
  rows,
  cursor,
  detail,
  height,
}: {
  runId: string;
  rows: TraceRow[];
  cursor: number;
  detail: boolean;
  height: number;
}): React.ReactElement {
  const window = Math.max(5, height - 8);
  const start = Math.max(0, Math.min(cursor - Math.floor(window / 2), rows.length - window));
  const visible = rows.slice(start, start + window);
  const selected = rows[cursor];
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.accent} paddingX={1}>
      <Text bold color={theme.accent}>
        Trace {runId.slice(0, 12)} · {rows.length} spans
      </Text>
      {visible.map((row, index) => {
        const isSelected = start + index === cursor;
        return (
          <Text key={row.span.span_id} inverse={isSelected}>
            {"  ".repeat(row.depth)}
            <Text color={row.span.status === "error" ? theme.bad : theme.accent}>
              {row.span.kind === "llm.call" ? "◆" : row.span.kind === "tool.call" ? "●" : "▪"}
            </Text>{" "}
            {truncate(row.span.name, 28).padEnd(30 - row.depth * 2 > 0 ? 30 - row.depth * 2 : 5)}
            <Text color={theme.dim}> {spanSummary(row.span)}</Text>
          </Text>
        );
      })}
      {detail && selected ? (
        <Box flexDirection="column" borderStyle="single" borderColor={theme.border} paddingX={1}>
          {Object.entries(selected.span.attrs)
            .slice(0, 12)
            .map(([key, value]) => (
              <Text key={key} color={theme.dim}>
                {key}: {truncate(typeof value === "string" ? value : JSON.stringify(value), 120)}
              </Text>
            ))}
        </Box>
      ) : null}
      <Text color={theme.dim}>  ↑↓ move · →/← expand/collapse · Enter attrs · q close</Text>
    </Box>
  );
}
