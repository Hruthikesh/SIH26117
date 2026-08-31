/** Interactive prompts: permission, question, plan review (SPEC §17.2). */

import React from "react";
import { Box, Text } from "ink";
import type { PendingPermission, PendingQuestion, TuiState } from "../state.js";
import { argsPreview, truncate } from "../format.js";
import { theme } from "../theme.js";

export function PermissionView({ pending }: { pending: PendingPermission }): React.ReactElement {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.warn} paddingX={1}>
      <Text>
        <Text color={theme.warn} bold>
          Yantra wants to run
        </Text>{" "}
        <Text bold>{pending.tool}</Text>
        <Text color={theme.dim}>: {argsPreview(pending.args, 120)}</Text>
      </Text>
      {pending.reason ? <Text color={theme.dim}>  {truncate(pending.reason, 110)}</Text> : null}
      {pending.explanation ? <Text color={theme.dim}>  why: {pending.explanation}</Text> : null}
      <Text>
        {"  "}
        <Text color={theme.ok}>[y]</Text> yes once  <Text color={theme.ok}>[a]</Text> always this
        session  <Text color={theme.bad}>[n]</Text> no  <Text color={theme.accent}>[e]</Text> explain
      </Text>
    </Box>
  );
}

export function QuestionView({
  question,
  buffer,
  answered,
}: {
  question: PendingQuestion;
  buffer: string;
  answered: string[];
}): React.ReactElement {
  const current = answered.length;
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.accent} paddingX={1}>
      <Text bold color={theme.accent}>
        Yantra needs input ({current + 1}/{question.questions.length})
      </Text>
      {question.questions.map((q, i) => (
        <Text key={i} color={i === current ? undefined : theme.dim}>
          {"  "}
          {i + 1}. {q}
          {i < current ? <Text color={theme.ok}> → {truncate(answered[i] ?? "", 40)}</Text> : null}
        </Text>
      ))}
      <Text>
        <Text color={theme.accent}>{"answer> "}</Text>
        {buffer}
        <Text color={theme.dim}>█</Text>
      </Text>
    </Box>
  );
}

export function PlanReviewView({ state }: { state: TuiState }): React.ReactElement {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.accent} paddingX={1}>
      <Text bold color={theme.accent}>
        Plan ready — {state.tasks.length} tasks
      </Text>
      <Text color={theme.dim}>
        {"  [Enter] run   [e] write plan to .yantra/plan.json for editing   [n] reject   Tab: switch to auto first"}
      </Text>
    </Box>
  );
}
