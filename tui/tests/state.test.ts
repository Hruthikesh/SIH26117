import { describe, expect, it } from "vitest";
import { initialState, reduce, type TuiState } from "../src/state.js";

function withHandshake(): TuiState {
  return reduce(initialState(), {
    type: "handshake",
    sessionId: "s1",
    sealed: true,
    profile: "mock",
    version: "0.1.0",
    mode: "ask",
    workspace: "/w",
  });
}

describe("reducer", () => {
  it("handshake pushes a single header entry", () => {
    let state = withHandshake();
    state = reduce(state, {
      type: "handshake",
      sessionId: "s1",
      sealed: true,
      profile: "mock",
      version: "0.1.0",
      mode: "ask",
      workspace: "/w",
    });
    expect(state.finalized.filter((e) => e.kind === "header")).toHaveLength(1);
  });

  it("plan.updated builds the task panel", () => {
    const state = reduce(withHandshake(), {
      type: "notification",
      method: "plan.updated",
      params: { plan: { version: 1, tasks: [{ id: "t1", title: "Do it", role: "coder" }] } },
    });
    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0]).toMatchObject({ id: "t1", status: "pending" });
    expect(state.finalized.at(-1)?.kind).toBe("plan");
  });

  it("tool lifecycle moves from live to finalized", () => {
    let state = withHandshake();
    state = reduce(state, {
      type: "notification",
      method: "tool.started",
      params: { step_id: "st1", tool: "read_file", args: { path: "a.txt" } },
    });
    expect(state.liveTools.size).toBe(1);
    state = reduce(state, {
      type: "notification",
      method: "tool.output.delta",
      params: { step_id: "st1", text: "line1\n" },
    });
    state = reduce(state, {
      type: "notification",
      method: "tool.finished",
      params: { step_id: "st1", tool: "read_file", summary: "3 lines", ok: true, artifact_id: null },
    });
    expect(state.liveTools.size).toBe(0);
    const last = state.finalized.at(-1);
    expect(last).toMatchObject({ kind: "tool", tool: "read_file", summary: "3 lines", done: true });
  });

  it("task.updated tracks attempts and rungs", () => {
    let state = reduce(withHandshake(), {
      type: "notification",
      method: "task.updated",
      params: { task: { task_id: "t1", title: "T", role: "coder", status: "running", attempt: 2, ladder_rung: 1 } },
    });
    expect(state.tasks[0]).toMatchObject({ status: "running", attempt: 2, rung: 1 });
    state = reduce(state, {
      type: "notification",
      method: "escalation",
      params: { task_id: "t1", rung: "best_of_n", attempt: 2 },
    });
    expect(state.tasks[0]?.rung).toBe(2);
  });

  it("permission.request routes plan approvals to planreview mode", () => {
    const normal = reduce(withHandshake(), {
      type: "notification",
      method: "permission.request",
      params: { request_id: "r1", tool: "write_file", args: {}, rule: { reason: "ask" } },
    });
    expect(normal.uiMode).toBe("permission");
    const plan = reduce(withHandshake(), {
      type: "notification",
      method: "permission.request",
      params: { request_id: "plan:run1", tool: "plan", args: {}, rule: {} },
    });
    expect(plan.uiMode).toBe("planreview");
    const resolved = reduce(plan, { type: "resolve-permission", requestId: "plan:run1" });
    expect(resolved.uiMode).toBe("input");
  });

  it("run.finished finalises and stops the spinner", () => {
    let state = reduce(withHandshake(), { type: "run-started", runId: "r1" });
    expect(state.runActive).toBe(true);
    state = reduce(state, {
      type: "notification",
      method: "run.finished",
      params: { status: "done", summary: "all good", artifacts: [], assumptions: [], unverified: [] },
    });
    expect(state.runActive).toBe(false);
    expect(state.finalized.at(-1)).toMatchObject({ kind: "finish", status: "done" });
  });

  it("cycle-mode walks ask→auto→plan→ask", () => {
    let state = withHandshake();
    const seen: string[] = [state.mode];
    for (let i = 0; i < 3; i++) {
      state = reduce(state, { type: "cycle-mode" });
      seen.push(state.mode);
    }
    expect(seen).toEqual(["ask", "auto", "plan", "ask"]);
  });

  it("run.stats updates the status line data", () => {
    const state = reduce(withHandshake(), {
      type: "notification",
      method: "run.stats",
      params: { tokens_in: 38200, context_pct: 41, elapsed_s: 252, cost_saved_inr: 18, active_model: "mock" },
    });
    expect(state.stats).toMatchObject({ tokensIn: 38200, contextPct: 41, activeModel: "mock" });
  });
});
