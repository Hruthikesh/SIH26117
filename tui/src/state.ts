/** TUI state: transcript entries, task panel, prompts, status — one reducer over
 *  server notifications and local UI events. */

export type Tone = "normal" | "dim" | "error" | "ok" | "warn";

export interface PlanTaskView {
  id: string;
  title: string;
  role: string;
  status: string; // pending|running|done|partial|failed|cancelled
  attempt: number;
  rung: number;
}

export type Entry =
  | { kind: "header"; workspace: string; version: string; profile: string; sealed: boolean }
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "system"; text: string; tone: Tone }
  | { kind: "plan"; tasks: PlanTaskView[]; version: number }
  | {
      kind: "tool";
      stepId: string;
      taskId: string | null;
      tool: string;
      args: Record<string, unknown>;
      output: string;
      summary: string;
      ok: boolean;
      done: boolean;
      artifactId: string | null;
    }
  | { kind: "verify"; taskId: string; verdict: string; score: number | null; failures: string[] }
  | { kind: "escalation"; taskId: string; rung: string; attempt: number }
  | { kind: "image"; artifactId: string; dims: number[]; caption: string | null }
  | {
      kind: "finish";
      status: string;
      summary: string;
      artifacts: { name: string; path: string }[];
      assumptions: string[];
      unverified: string[];
    };

export interface PendingPermission {
  requestId: string;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  explanation: string | null;
  isPlan: boolean;
}

export interface PendingQuestion {
  requestId: string;
  questions: string[];
}

export interface Stats {
  tokensIn: number;
  tokensOut: number;
  contextPct: number;
  elapsedS: number;
  costSavedInr: number;
  activeModel: string;
}

export type UiMode =
  | "input"
  | "palette"
  | "filepick"
  | "permission"
  | "question"
  | "planreview"
  | "resume"
  | "trace"
  | "help";

export interface TuiState {
  finalized: Entry[];
  liveTools: Map<string, Extract<Entry, { kind: "tool" }>>;
  tasks: PlanTaskView[];
  runActive: boolean;
  runId: string | null;
  sessionId: string;
  mode: "ask" | "auto" | "plan";
  uiMode: UiMode;
  permissionQueue: PendingPermission[];
  question: PendingQuestion | null;
  thinking: string;
  spinnerActive: boolean;
  showThinking: boolean;
  verbose: boolean;
  showTasks: boolean;
  stats: Stats;
  sealed: boolean | null;
  profile: string;
  serverVersion: string;
  connection: string;
  vim: boolean;
  budgetOverrides: Record<string, number>;
}

export function initialState(): TuiState {
  return {
    finalized: [],
    liveTools: new Map(),
    tasks: [],
    runActive: false,
    runId: null,
    sessionId: "",
    mode: "ask",
    uiMode: "input",
    permissionQueue: [],
    question: null,
    thinking: "",
    spinnerActive: false,
    showThinking: false,
    verbose: false,
    showTasks: true,
    stats: { tokensIn: 0, tokensOut: 0, contextPct: 0, elapsedS: 0, costSavedInr: 0, activeModel: "" },
    sealed: null,
    profile: "",
    serverVersion: "",
    connection: "connecting",
    vim: false,
    budgetOverrides: {},
  };
}

export type Action =
  | { type: "connection"; state: string }
  | {
      type: "handshake";
      sessionId: string;
      sealed: boolean;
      profile: string;
      version: string;
      mode: "ask" | "auto" | "plan";
      workspace: string;
    }
  | { type: "entry"; entry: Entry }
  | { type: "notification"; method: string; params: Record<string, unknown> }
  | { type: "set"; patch: Partial<TuiState> }
  | { type: "run-started"; runId: string }
  | { type: "clear" }
  | { type: "resolve-permission"; requestId: string }
  | { type: "cycle-mode" };

const RUNG_ORDER = ["raise_effort", "best_of_n", "switch_role", "replan"];

export function reduce(state: TuiState, action: Action): TuiState {
  switch (action.type) {
    case "connection":
      return { ...state, connection: action.state };
    case "handshake": {
      const hasHeader = state.finalized.some((e) => e.kind === "header");
      const finalized = hasHeader
        ? state.finalized
        : [
            {
              kind: "header" as const,
              workspace: action.workspace,
              version: action.version,
              profile: action.profile,
              sealed: action.sealed,
            },
            ...state.finalized,
          ];
      return {
        ...state,
        finalized,
        sessionId: action.sessionId,
        sealed: action.sealed,
        profile: action.profile,
        serverVersion: action.version,
        mode: action.mode,
      };
    }
    case "entry":
      return { ...state, finalized: [...state.finalized, action.entry] };
    case "run-started":
      return { ...state, runId: action.runId, runActive: true, spinnerActive: true, thinking: "" };
    case "set":
      return { ...state, ...action.patch };
    case "clear":
      return { ...state, finalized: [], liveTools: new Map() };
    case "cycle-mode": {
      const order: TuiState["mode"][] = ["ask", "auto", "plan"];
      const next = order[(order.indexOf(state.mode) + 1) % order.length] ?? "ask";
      return { ...state, mode: next };
    }
    case "resolve-permission": {
      const queue = state.permissionQueue.filter((p) => p.requestId !== action.requestId);
      return {
        ...state,
        permissionQueue: queue,
        uiMode: queue.length > 0 ? "permission" : state.question ? "question" : "input",
      };
    }
    case "notification":
      return applyNotification(state, action.method, action.params);
    default:
      return state;
  }
}

function applyNotification(
  state: TuiState,
  method: string,
  params: Record<string, unknown>,
): TuiState {
  switch (method) {
    case "plan.updated": {
      const plan = (params["plan"] ?? {}) as { tasks?: { id: string; title: string; role: string }[]; version?: number };
      const tasks: PlanTaskView[] = (plan.tasks ?? []).map((t) => {
        const existing = state.tasks.find((x) => x.id === t.id);
        return existing
          ? { ...existing, title: t.title, role: t.role }
          : { id: t.id, title: t.title, role: t.role, status: "pending", attempt: 0, rung: 0 };
      });
      return {
        ...state,
        tasks,
        finalized: [...state.finalized, { kind: "plan", tasks, version: plan.version ?? 1 }],
      };
    }
    case "task.updated": {
      const task = params["task"] as { task_id?: string; title?: string; role?: string; status?: string; attempt?: number; ladder_rung?: number };
      const id = task.task_id ?? "";
      const existing = state.tasks.find((t) => t.id === id);
      const updated: PlanTaskView = {
        id,
        title: task.title ?? existing?.title ?? id,
        role: task.role ?? existing?.role ?? "",
        status: task.status ?? existing?.status ?? "pending",
        attempt: task.attempt ?? existing?.attempt ?? 0,
        rung: task.ladder_rung ?? existing?.rung ?? 0,
      };
      const tasks = existing
        ? state.tasks.map((t) => (t.id === id ? updated : t))
        : [...state.tasks, updated];
      return { ...state, tasks };
    }
    case "tool.started": {
      const stepId = String(params["step_id"] ?? "");
      const live = new Map(state.liveTools);
      live.set(stepId, {
        kind: "tool",
        stepId,
        taskId: (params["task_id"] as string) ?? null,
        tool: String(params["tool"] ?? ""),
        args: (params["args"] as Record<string, unknown>) ?? {},
        output: "",
        summary: "",
        ok: true,
        done: false,
        artifactId: null,
      });
      return { ...state, liveTools: live, spinnerActive: true };
    }
    case "tool.output.delta": {
      const stepId = String(params["step_id"] ?? "");
      const live = new Map(state.liveTools);
      const entry = live.get(stepId);
      if (entry) {
        const output = (entry.output + String(params["text"] ?? "")).slice(-8000);
        live.set(stepId, { ...entry, output });
      }
      return { ...state, liveTools: live };
    }
    case "tool.finished": {
      const stepId = String(params["step_id"] ?? "");
      const live = new Map(state.liveTools);
      const entry = live.get(stepId);
      live.delete(stepId);
      const finalizedEntry: Entry = {
        kind: "tool",
        stepId,
        taskId: entry?.taskId ?? null,
        tool: String(params["tool"] ?? entry?.tool ?? ""),
        args: entry?.args ?? {},
        output: entry?.output ?? "",
        summary: String(params["summary"] ?? ""),
        ok: Boolean(params["ok"] ?? true),
        done: true,
        artifactId: (params["artifact_id"] as string) ?? null,
      };
      return { ...state, liveTools: live, finalized: [...state.finalized, finalizedEntry] };
    }
    case "verify.result": {
      const report = (params["report"] ?? {}) as {
        verdict?: string;
        reviewer?: { score?: number; failures?: { what: string }[] };
        checks?: { check?: { kind?: string }; passed?: boolean; detail?: string }[];
      };
      const failures = [
        ...(report.checks ?? [])
          .filter((c) => !c.passed)
          .map((c) => `${c.check?.kind}: ${c.detail ?? ""}`),
        ...(report.reviewer?.failures ?? []).map((f) => f.what),
      ];
      return {
        ...state,
        finalized: [
          ...state.finalized,
          {
            kind: "verify",
            taskId: String(params["task_id"] ?? ""),
            verdict: report.verdict ?? "?",
            score: report.reviewer?.score ?? null,
            failures: failures.slice(0, 5),
          },
        ],
      };
    }
    case "escalation": {
      const rung = String(params["rung"] ?? "");
      const entry: Entry = {
        kind: "escalation",
        taskId: String(params["task_id"] ?? ""),
        rung,
        attempt: Number(params["attempt"] ?? 0),
      };
      const tasks = state.tasks.map((t) =>
        t.id === entry.taskId ? { ...t, rung: Math.max(t.rung, RUNG_ORDER.indexOf(rung) + 1) } : t,
      );
      return { ...state, tasks, finalized: [...state.finalized, entry] };
    }
    case "thinking.delta":
      return { ...state, thinking: (state.thinking + String(params["text"] ?? "")).slice(-2000) };
    case "assistant.delta":
      return {
        ...state,
        finalized: [...state.finalized, { kind: "assistant", text: String(params["text"] ?? "") }],
      };
    case "run.stats":
      return {
        ...state,
        stats: {
          tokensIn: Number(params["tokens_in"] ?? 0),
          tokensOut: Number(params["tokens_out"] ?? 0),
          contextPct: Number(params["context_pct"] ?? 0),
          elapsedS: Number(params["elapsed_s"] ?? 0),
          costSavedInr: Number(params["cost_saved_inr"] ?? 0),
          activeModel: String(params["active_model"] ?? ""),
        },
      };
    case "permission.request": {
      const requestId = String(params["request_id"] ?? "");
      const pending: PendingPermission = {
        requestId,
        tool: String(params["tool"] ?? ""),
        args: (params["args"] as Record<string, unknown>) ?? {},
        reason: String((params["rule"] as { reason?: string })?.reason ?? ""),
        explanation: (params["explanation"] as string) ?? null,
        isPlan: requestId.startsWith("plan:"),
      };
      return {
        ...state,
        permissionQueue: [...state.permissionQueue, pending],
        uiMode: pending.isPlan ? "planreview" : "permission",
      };
    }
    case "question":
      return {
        ...state,
        question: {
          requestId: String(params["request_id"] ?? ""),
          questions: (params["questions"] as string[]) ?? [],
        },
        uiMode: "question",
      };
    case "budget.warning":
      return {
        ...state,
        finalized: [
          ...state.finalized,
          {
            kind: "system",
            tone: "warn",
            text: `budget warning: ${String(params["budget"])} at ${Math.round(
              (Number(params["used"]) / Math.max(Number(params["limit"]), 1)) * 100,
            )}%`,
          },
        ],
      };
    case "seal.event":
      return {
        ...state,
        finalized: [
          ...state.finalized,
          {
            kind: "system",
            tone: "error",
            text: `SEAL: blocked ${String(params["kind"])} → ${String(params["dest"])} (${String(params["process"])})`,
          },
        ],
      };
    case "image":
      return {
        ...state,
        finalized: [
          ...state.finalized,
          {
            kind: "image",
            artifactId: String(params["artifact_id"] ?? ""),
            dims: (params["dims"] as number[]) ?? [],
            caption: (params["caption"] as string) ?? null,
          },
        ],
      };
    case "run.finished": {
      const entry: Entry = {
        kind: "finish",
        status: String(params["status"] ?? "done"),
        summary: String(params["summary"] ?? ""),
        artifacts: (params["artifacts"] as { name: string; path: string }[]) ?? [],
        assumptions: (params["assumptions"] as string[]) ?? [],
        unverified: (params["unverified"] as string[]) ?? [],
      };
      return {
        ...state,
        runActive: false,
        spinnerActive: false,
        thinking: "",
        finalized: [...state.finalized, entry],
      };
    }
    case "error":
      return {
        ...state,
        runActive: false,
        spinnerActive: false,
        finalized: [
          ...state.finalized,
          {
            kind: "system",
            tone: "error",
            text: `${String(params["code"])}: ${String(params["message"])}${
              params["hint"] ? ` — ${String(params["hint"])}` : ""
            }`,
          },
        ],
      };
    default:
      return state;
  }
}
