/** Scripted end-to-end flow of the App against a fake RPC client (M4 DoD). */

import React from "react";
import { describe, expect, it } from "vitest";
import { render } from "ink-testing-library";
import { EventEmitter } from "node:events";
import { App } from "../src/app.js";
import type { RpcClient } from "../src/rpc/client.js";

const ESC = "";

class FakeClient extends EventEmitter {
  state: "connecting" | "open" | "closed" | "reconnecting" = "connecting";
  calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  responses: Record<string, unknown> = {
    ping: { pong: true, version: "0.1.0-test" },
    "config.get": { sealed: true, profile: "mock" },
    "session.create": { session_id: "session123456" },
    "session.prompt": { run_id: "run42" },
    "run.approve": { resolved: true },
    "run.cancel": { cancelled: true },
    "session.list": { sessions: [] },
  };

  call(method: string, params: Record<string, unknown>): Promise<unknown> {
    this.calls.push({ method, params });
    const canned = this.responses[method];
    if (canned === undefined) return Promise.reject(new Error(`unknown method ${method}`));
    return Promise.resolve(canned);
  }

  lastSeqFor(): number {
    return 0;
  }

  open(): void {
    this.state = "open";
    this.emit("state", "open");
  }

  notify(method: string, params: Record<string, unknown>): void {
    this.emit("notification", method, params);
  }

  close(): void {}
}

const flush = (ms = 50) => new Promise((resolve) => setTimeout(resolve, ms));

function mount() {
  const client = new FakeClient();
  const view = render(<App client={client as unknown as RpcClient} workspace="/plant/unit3" />);
  return { client, view };
}

async function type(view: { stdin: { write: (s: string) => void } }, text: string): Promise<void> {
  for (const ch of text) {
    view.stdin.write(ch);
    await flush(8);
  }
}

describe("App flow", () => {
  it("handshakes and shows the header + ready state", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    const frame = view.lastFrame() ?? "";
    expect(frame).toContain("YANTRA");
    expect(frame).toContain("SEALED");
    expect(client.calls.map((c) => c.method)).toEqual(["ping", "config.get", "session.create"]);
  });

  it("typing a goal sends session.prompt and renders run events", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    await type(view, "find pump");
    view.stdin.write("\r");
    await flush();
    const promptCall = client.calls.find((c) => c.method === "session.prompt");
    expect(promptCall?.params["text"]).toBe("find pump");

    client.notify("plan.updated", {
      run_id: "run42",
      seq: 1,
      plan: { version: 1, tasks: [{ id: "t1", title: "Locate logs", role: "analyst" }] },
    });
    client.notify("tool.started", {
      run_id: "run42",
      seq: 2,
      step_id: "st1",
      tool: "search_knowledge",
      args: { query: "P-3101" },
    });
    client.notify("tool.finished", {
      run_id: "run42",
      seq: 3,
      step_id: "st1",
      tool: "search_knowledge",
      summary: "10 chunks",
      ok: true,
    });
    client.notify("verify.result", {
      run_id: "run42",
      seq: 4,
      task_id: "t1",
      report: { verdict: "pass", reviewer: { score: 91, failures: [] }, checks: [] },
    });
    client.notify("run.finished", {
      run_id: "run42",
      seq: 5,
      status: "done",
      summary: "Report written.",
      artifacts: [{ name: "report.docx", path: "/w/report.docx" }],
      assumptions: [],
      unverified: [],
    });
    await flush();
    const frames = view.frames.join("\n");
    expect(frames).toContain("Locate logs");
    expect(frames).toContain("search_knowledge");
    expect(frames).toContain("t1 verified: pass");
    expect(frames).toContain("report.docx");
  });

  it("permission prompt approves with y", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    client.notify("permission.request", {
      run_id: "run42",
      seq: 1,
      request_id: "req9",
      tool: "write_file",
      args: { path: "out.md" },
      rule: { reason: "rule(tool=*) → ask" },
    });
    await flush();
    expect(view.lastFrame()).toContain("Yantra wants to run");
    view.stdin.write("y");
    await flush();
    const approve = client.calls.find((c) => c.method === "run.approve");
    expect(approve?.params["request_id"]).toBe("req9");
    expect(approve?.params["decision"]).toBe("once");
  });

  it("plan review approves on Enter", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    client.notify("plan.updated", {
      run_id: "run42",
      seq: 1,
      plan: { version: 1, tasks: [{ id: "t1", title: "T", role: "coder" }] },
    });
    client.notify("permission.request", {
      run_id: "run42",
      seq: 2,
      request_id: "plan:run42",
      tool: "plan",
      args: {},
      rule: { reason: "plan approval (ask mode)" },
    });
    await flush();
    expect(view.lastFrame()).toContain("Plan ready");
    view.stdin.write("\r");
    await flush();
    const approve = client.calls.find((c) => c.method === "run.approve");
    expect(approve?.params["request_id"]).toBe("plan:run42");
  });

  it("slash palette runs an unknown command cleanly", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    view.stdin.write("/");
    await flush(40);
    expect(view.lastFrame()).toContain("↑↓ select");
    await type(view, "nope");
    view.stdin.write("\r");
    await flush(80);
    expect(view.frames.join("\n")).toContain("unknown command /nope");
  });

  it("esc cancels an active run", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    await type(view, "go");
    view.stdin.write("\r");
    await flush(80);
    view.stdin.write(ESC);
    await flush(300);
    const cancel = client.calls.find((c) => c.method === "run.cancel");
    expect(cancel?.params["run_id"]).toBe("run42");
  });

  it("errors surface as red system lines, never stack traces", async () => {
    const { client, view } = mount();
    client.open();
    await flush();
    client.notify("error", {
      run_id: "run42",
      seq: 1,
      code: "engine_down",
      message: "brain engine unhealthy",
      hint: "/models restart",
    });
    await flush();
    const frames = view.frames.join("\n");
    expect(frames).toContain("engine_down: brain engine unhealthy");
    expect(frames).not.toContain("Traceback");
    expect(frames).not.toContain("    at ");
  });
});
