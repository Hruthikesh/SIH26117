import React, { useEffect, useState } from "react";
import { Text } from "ink";
import { glyphs, theme } from "../theme.js";

const VERBS = [
  "Tracing lines…",
  "Reading the manual…",
  "Checking relief paths…",
  "Reconciling tags…",
  "Walking the pipe rack…",
  "Cross-checking the SOP…",
  "Summing the failure counts…",
  "Consulting the datasheet…",
  "Following the loop…",
  "Inspecting the flange…",
];

export function Spinner({ thinking, expanded }: { thinking: string; expanded: boolean }): React.ReactElement {
  const [frame, setFrame] = useState(0);
  const [verb, setVerb] = useState(0);
  useEffect(() => {
    const spin = setInterval(() => setFrame((f) => (f + 1) % glyphs.spinnerFrames.length), 90);
    const rotate = setInterval(() => setVerb((v) => (v + 1) % VERBS.length), 2600);
    return () => {
      clearInterval(spin);
      clearInterval(rotate);
    };
  }, []);
  return (
    <Text>
      <Text color={theme.accent}>{glyphs.spinnerFrames[frame]}</Text>{" "}
      <Text color={theme.dim}>
        {VERBS[verb]}
        {"  "}
        {expanded ? "" : "(Ctrl+E to expand thinking)"}
      </Text>
      {expanded && thinking ? (
        <Text color={theme.dim}>{"\n  " + thinking.slice(-600).replace(/\n/g, "\n  ")}</Text>
      ) : null}
    </Text>
  );
}
