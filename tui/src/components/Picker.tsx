/** Shared fuzzy picker: command palette (/), file picker (@), session resume. */

import React from "react";
import { Box, Text } from "ink";
import { fuzzyScore, truncate } from "../format.js";
import { theme } from "../theme.js";

export interface PickerItem {
  id: string;
  label: string;
  hint?: string;
}

export function filterItems(items: PickerItem[], query: string, limit = 8): PickerItem[] {
  if (!query) return items.slice(0, limit);
  return items
    .map((item) => ({ item, score: fuzzyScore(query, item.label) }))
    .filter((x) => x.score >= 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((x) => x.item);
}

export function PickerView({
  title,
  query,
  items,
  selected,
}: {
  title: string;
  query: string;
  items: PickerItem[];
  selected: number;
}): React.ReactElement {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.accent} paddingX={1}>
      <Text>
        <Text bold color={theme.accent}>
          {title}
        </Text>{" "}
        {query}
        <Text color={theme.dim}>█</Text>
      </Text>
      {items.length === 0 ? (
        <Text color={theme.dim}>  (no matches)</Text>
      ) : (
        items.map((item, index) => (
          <Text key={item.id} inverse={index === selected}>
            {"  "}
            {truncate(item.label, 48).padEnd(48)}
            <Text color={theme.dim}> {truncate(item.hint ?? "", 52)}</Text>
          </Text>
        ))
      )}
      <Text color={theme.dim}>  ↑↓ select · Enter confirm · Esc cancel</Text>
    </Box>
  );
}
