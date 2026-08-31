/** Header, task panel, status line (SPEC §17.1 layout). */

import React from "react";
import { Box, Text } from "ink";
import type { TuiState } from "../state.js";
import { fmtDuration, fmtInr, fmtTokens, truncate } from "../format.js";
import { glyphs, theme } from "../theme.js";
import { statusGlyph } from "./Entries.js";

export function Header({ state, workspace }: { state: TuiState; workspace: string }): React.ReactElement {
  const sealText =
    state.sealed === null ? "…" : state.sealed ? `${glyphs.sealed} SEALED · 0 egress` : `${glyphs.unsealed} UNSEALED (dev)`;
  return (
    <Box borderStyle="round" borderColor={theme.border} flexDirection="column" paddingX={1}>
      <Text>
        <Text color={theme.accent}>{glyphs.logo} YANTRA</Text> v{state.serverVersion || "…"} · Sovereign
        Agentic Workbench
      </Text>
      <Text color={theme.dim}>
        {truncate(workspace, 46)}
        {"   profile: "}
        {state.profile || "…"}
        {"   "}
        <Text color={state.sealed === false ? theme.bad : theme.ok}>{sealText}</Text>
      </Text>
    </Box>
  );
}

export function TaskPanel({ state }: { state: TuiState }): React.ReactElement | null {
  if (!state.showTasks || state.tasks.length === 0) return null;
  return (
    <Box flexDirection="column" paddingX={1}>
      {state.tasks.map((task) => (
        <Text key={task.id}>
          {"  "}
          <Text color={task.status === "running" ? theme.accent : undefined}>
            {statusGlyph(task.status)}
          </Text>{" "}
          {task.id} {truncate(task.title, 56)}
          <Text color={theme.dim}> {task.role}</Text>
          {task.attempt > 1 || task.rung > 0 ? (
            <Text color={theme.warn}>
              {"  ↻ attempt "}
              {task.attempt}
              {task.rung > 0 ? ` · rung ${task.rung}` : ""}
            </Text>
          ) : null}
        </Text>
      ))}
    </Box>
  );
}

export function StatusLine({ state }: { state: TuiState }): React.ReactElement {
  const seal =
    state.sealed === null ? "" : state.sealed ? ` · ${glyphs.sealed}` : ` · ${glyphs.unsealed} UNSEALED`;
  const stats = state.stats;
  return (
    <Box paddingX={1} justifyContent="space-between">
      <Text color={theme.dim}>
        <Text color={state.mode === "auto" ? theme.warn : theme.accent}>{state.mode}</Text>
        {" ▸ Tab"}
        {state.vim ? " · vim" : ""}
        {" · "}
        {state.connection === "open" ? `session ${state.sessionId.slice(0, 8)}` : state.connection}
      </Text>
      <Text color={state.sealed === false ? theme.bad : theme.dim}>
        {stats.activeModel ? `${stats.activeModel} · ` : ""}
        {fmtTokens(stats.tokensIn)}↑ · ctx {stats.contextPct.toFixed(0)}% ·{" "}
        {fmtDuration(stats.elapsedS)} · ≈{fmtInr(stats.costSavedInr)} saved{seal}
      </Text>
    </Box>
  );
}
