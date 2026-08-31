/** Renderers for every transcript entry kind (SPEC §17.2 tool cards, plan, verify…). */

import React from "react";
import { Box, Text } from "ink";
import type { Entry, PlanTaskView } from "../state.js";
import { argsPreview, truncate } from "../format.js";
import { renderDiff, renderMarkdown } from "../markdown.js";
import { glyphs, theme } from "../theme.js";

const OUTPUT_PREVIEW_LINES = 6;
const VERBOSE_LINES = 40;

export function EntryView({ entry, verbose }: { entry: Entry; verbose: boolean }): React.ReactElement {
  switch (entry.kind) {
    case "header":
      return (
        <Box borderStyle="round" borderColor={theme.border} flexDirection="column" paddingX={1}>
          <Text>
            <Text color={theme.accent}>✦ YANTRA</Text> v{entry.version} · Sovereign Agentic Workbench
          </Text>
          <Text color={theme.dim}>
            {truncate(entry.workspace, 46)}
            {"   profile: "}
            {entry.profile}
            {"   "}
            <Text color={entry.sealed ? theme.ok : theme.bad}>
              {entry.sealed ? `${glyphs.sealed} SEALED · 0 egress` : `${glyphs.unsealed} UNSEALED (dev)`}
            </Text>
          </Text>
        </Box>
      );
    case "user":
      return (
        <Box marginTop={1}>
          <Text>
            <Text color={theme.accent}>{"> "}</Text>
            {entry.text}
          </Text>
        </Box>
      );
    case "assistant":
      return (
        <Box marginTop={1} flexDirection="column">
          <Text>{renderMarkdown(entry.text)}</Text>
        </Box>
      );
    case "system": {
      const color =
        entry.tone === "error"
          ? theme.bad
          : entry.tone === "ok"
            ? theme.ok
            : entry.tone === "warn"
              ? theme.warn
              : theme.dim;
      return (
        <Text color={color}>
          {"  "}
          {entry.text}
        </Text>
      );
    }
    case "plan":
      return <PlanBlock tasks={entry.tasks} version={entry.version} />;
    case "tool":
      return <ToolCard entry={entry} verbose={verbose} />;
    case "verify": {
      const pass = entry.verdict === "pass";
      return (
        <Box flexDirection="column">
          <Text color={pass ? theme.ok : theme.warn}>
            {pass ? glyphs.done : glyphs.fail} {entry.taskId} verified: {entry.verdict}
            {entry.score !== null ? ` · reviewer ${entry.score}/100` : ""}
          </Text>
          {!pass &&
            entry.failures.map((failure, i) => (
              <Text key={i} color={theme.dim}>
                {"    - "}
                {truncate(failure, 110)}
              </Text>
            ))}
        </Box>
      );
    }
    case "escalation":
      return (
        <Text color={theme.warn}>
          {"  ↻ "}
          {entry.taskId}: escalating → {entry.rung} (attempt {entry.attempt})
        </Text>
      );
    case "image":
      return (
        <Text color={theme.dim}>
          {"  🖼 image artifact "}
          {entry.artifactId.slice(0, 8)}
          {entry.dims.length === 2 ? ` (${entry.dims[0]}×${entry.dims[1]})` : ""}
          {entry.caption ? ` — ${entry.caption}` : ""}
        </Text>
      );
    case "finish":
      return <FinishBlock entry={entry} />;
    default:
      return <Text />;
  }
}

export function ToolCard({
  entry,
  verbose,
  live = false,
}: {
  entry: Extract<Entry, { kind: "tool" }>;
  verbose: boolean;
  live?: boolean;
}): React.ReactElement {
  const isDiff = entry.tool === "edit_file" || entry.tool === "apply_patch";
  const outputLines = entry.output.split("\n");
  const limit = verbose ? VERBOSE_LINES : OUTPUT_PREVIEW_LINES;
  const shown = outputLines.slice(-limit);
  const showOutput =
    (live && entry.output) || (entry.done && ((verbose && entry.output) || (!entry.ok && entry.output)));
  return (
    <Box flexDirection="column">
      <Text>
        <Text color={entry.done ? (entry.ok ? theme.ok : theme.bad) : theme.accent}>{glyphs.tool}</Text>{" "}
        <Text bold>{entry.tool}</Text>
        <Text color={theme.dim}>({argsPreview(entry.args)})</Text>
      </Text>
      {entry.done && (
        <Text color={entry.ok ? undefined : theme.bad}>
          {"  "}
          {glyphs.toolResult} {truncate(entry.summary || (entry.ok ? "ok" : "failed"), 120)}
          {entry.artifactId && !verbose ? (
            <Text color={theme.dim}> [Ctrl+O for output]</Text>
          ) : null}
        </Text>
      )}
      {showOutput ? (
        <Box flexDirection="column" marginLeft={4} borderStyle="round" borderColor={theme.border} paddingX={1}>
          {isDiff && entry.done ? (
            <Text>{renderDiff(shown.join("\n"))}</Text>
          ) : (
            shown.map((line, i) => (
              <Text key={i} color={theme.dim}>
                {truncate(line, 140)}
              </Text>
            ))
          )}
          {outputLines.length > limit && (
            <Text color={theme.dim}>… ({outputLines.length - limit} more lines)</Text>
          )}
        </Box>
      ) : null}
    </Box>
  );
}

export function PlanBlock({
  tasks,
  version,
}: {
  tasks: PlanTaskView[];
  version: number;
}): React.ReactElement {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text>
        <Text color={theme.accent}>{glyphs.tool}</Text> <Text bold>Plan</Text>
        <Text color={theme.dim}>
          {" "}
          v{version} · {tasks.length} task{tasks.length === 1 ? "" : "s"}
        </Text>
      </Text>
      {tasks.map((task) => (
        <Text key={task.id}>
          {"  "}
          {statusGlyph(task.status)} {task.id} {truncate(task.title, 60)}
          <Text color={theme.dim}> {task.role}</Text>
        </Text>
      ))}
    </Box>
  );
}

export function statusGlyph(status: string): string {
  switch (status) {
    case "done":
      return "☑";
    case "running":
      return glyphs.doing;
    case "partial":
      return "◪";
    case "failed":
      return glyphs.fail;
    case "cancelled":
      return "✖";
    default:
      return glyphs.todo;
  }
}

function FinishBlock({ entry }: { entry: Extract<Entry, { kind: "finish" }> }): React.ReactElement {
  const good = entry.status === "done" || entry.status === "planned";
  return (
    <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={good ? theme.ok : theme.warn} paddingX={1}>
      <Text bold color={good ? theme.ok : theme.warn}>
        {good ? glyphs.done : "◪"} run {entry.status}
      </Text>
      <Text>{renderMarkdown(entry.summary)}</Text>
      {entry.artifacts.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold>Deliverables</Text>
          {entry.artifacts.map((artifact, index) => (
            <Text key={index}>
              {"  "}
              {index + 1}. {artifact.name} <Text color={theme.dim}>{artifact.path}</Text>
            </Text>
          ))}
        </Box>
      )}
      {entry.assumptions.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={theme.dim}>
            Assumptions made
          </Text>
          {entry.assumptions.map((assumption, index) => (
            <Text key={index} color={theme.dim}>
              {"  - "}
              {assumption}
            </Text>
          ))}
        </Box>
      )}
      {entry.unverified.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={theme.warn}>
            Unverified claims
          </Text>
          {entry.unverified.map((claim, index) => (
            <Text key={index} color={theme.warn}>
              {"  - "}
              {truncate(claim, 110)}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  );
}
