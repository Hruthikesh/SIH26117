import React from "react";
import { describe, expect, it } from "vitest";
import { render } from "ink-testing-library";
import { EntryView } from "../src/components/Entries.js";
import { PermissionView, QuestionView } from "../src/components/Prompts.js";
import { PickerView } from "../src/components/Picker.js";
import { flattenSpans } from "../src/components/TraceView.js";
import type { Entry } from "../src/state.js";

const frame = (entry: Entry, verbose = false) =>
  render(<EntryView entry={entry} verbose={verbose} />).lastFrame() ?? "";

describe("transcript entries", () => {
  it("header shows seal state", () => {
    const out = frame({ kind: "header", workspace: "/plant/unit3", version: "0.1.0", profile: "standard", sealed: true });
    expect(out).toContain("YANTRA");
    expect(out).toContain("SEALED · 0 egress");
    expect(out).toContain("profile: standard");
  });

  it("tool card renders args and summary", () => {
    const out = frame({
      kind: "tool",
      stepId: "s1",
      taskId: "t1",
      tool: "search_knowledge",
      args: { query: "P-3101 seal failure", k: 10 },
      output: "",
      summary: "10 chunks · top: MaintLog_2025_Q3.xlsx p.4 (0.91)",
      ok: true,
      done: true,
      artifactId: null,
    });
    expect(out).toContain("search_knowledge");
    expect(out).toContain("P-3101 seal failure");
    expect(out).toContain("10 chunks");
  });

  it("failed tool shows output box", () => {
    const out = frame({
      kind: "tool",
      stepId: "s1",
      taskId: null,
      tool: "run_tests",
      args: {},
      output: "E  assert 1 == 2\n1 failed",
      summary: "tests FAILED (exit 1)",
      ok: false,
      done: true,
      artifactId: "abc",
    });
    expect(out).toContain("tests FAILED");
    expect(out).toContain("1 failed");
  });

  it("edit_file card colours a diff without crashing", () => {
    const out = frame(
      {
        kind: "tool",
        stepId: "s1",
        taskId: null,
        tool: "edit_file",
        args: { path: "a.py" },
        output: "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new",
        summary: "edited a.py",
        ok: true,
        done: true,
        artifactId: null,
      },
      true,
    );
    expect(out).toContain("+new");
    expect(out).toContain("-old");
  });

  it("verify entry lists failures on fail", () => {
    const out = frame({
      kind: "verify",
      taskId: "t2",
      verdict: "fail",
      score: 61,
      failures: ["file_exists: missing report.md"],
    });
    expect(out).toContain("t2");
    expect(out).toContain("61");
    expect(out).toContain("missing report.md");
  });

  it("finish block shows deliverables, assumptions and unverified claims", () => {
    const out = frame({
      kind: "finish",
      status: "done_with_gaps",
      summary: "Completed 6 of 7 tasks.",
      artifacts: [{ name: "report.docx", path: "/w/report.docx" }],
      assumptions: ["assumed 2025 data only"],
      unverified: ["pump was replaced in June"],
    });
    expect(out).toContain("done_with_gaps");
    expect(out).toContain("report.docx");
    expect(out).toContain("Assumptions made");
    expect(out).toContain("Unverified claims");
  });

  it("plan entry renders checkboxes", () => {
    const out = frame({
      kind: "plan",
      version: 1,
      tasks: [
        { id: "t1", title: "Find logs", role: "analyst", status: "done", attempt: 1, rung: 0 },
        { id: "t2", title: "Compute MTBF", role: "data_engineer", status: "running", attempt: 1, rung: 0 },
      ],
    });
    expect(out).toContain("☑ t1");
    expect(out).toContain("◐ t2");
  });
});

describe("prompts", () => {
  it("permission prompt shows options", () => {
    const out = render(
      <PermissionView
        pending={{ requestId: "r1", tool: "bash", args: { cmd: "pytest -q" }, reason: "rule(tool=bash) → ask", explanation: null, isPlan: false }}
      />,
    ).lastFrame();
    expect(out).toContain("Yantra wants to run");
    expect(out).toContain("bash");
    expect(out).toContain("[y] yes once");
    expect(out).toContain("[a] always");
  });

  it("question prompt tracks progress", () => {
    const out = render(
      <QuestionView
        question={{ requestId: "q1", questions: ["Which unit?", "Which year?"] }}
        buffer="Unit 3"
        answered={[]}
      />,
    ).lastFrame();
    expect(out).toContain("(1/2)");
    expect(out).toContain("Which unit?");
    expect(out).toContain("Unit 3");
  });

  it("picker filters fuzzily", () => {
    const out = render(
      <PickerView
        title="/"
        query="se"
        items={[
          { id: "seal", label: "/seal", hint: "seal status" },
          { id: "search", label: "/search", hint: "raw retrieval" },
        ]}
        selected={0}
      />,
    ).lastFrame();
    expect(out).toContain("/seal");
    expect(out).toContain("/search");
  });
});

describe("trace tree", () => {
  it("flattens spans by parent with expansion", () => {
    const spans = [
      { span_id: "a", parent_id: null, name: "run", kind: "run", start_ns: 1, end_ns: 10, status: "ok", attrs: {} },
      { span_id: "b", parent_id: "a", name: "task.attempt", kind: "task", start_ns: 2, end_ns: 9, status: "ok", attrs: {} },
      { span_id: "c", parent_id: "b", name: "llm.call", kind: "llm.call", start_ns: 3, end_ns: 4, status: "ok", attrs: {} },
    ];
    expect(flattenSpans(spans, new Set())).toHaveLength(1);
    expect(flattenSpans(spans, new Set(["a"]))).toHaveLength(2);
    const all = flattenSpans(spans, new Set(["a", "b"]));
    expect(all).toHaveLength(3);
    expect(all[2]?.depth).toBe(2);
  });
});
