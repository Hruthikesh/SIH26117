/** Slash commands (SPEC §17.3). Each returns lines for the transcript or drives the app. */

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import type { RpcClient } from "../rpc/client.js";
import type { Action, TuiState } from "../state.js";

export interface CommandCtx {
  client: RpcClient;
  state: () => TuiState;
  dispatch: (action: Action) => void;
  system: (text: string, tone?: "dim" | "error" | "ok" | "warn") => void;
  sendPrompt: (text: string) => Promise<void>;
  openTrace: (runId: string | null) => Promise<void>;
  openResume: () => Promise<void>;
  workspace: string;
  exit: () => void;
}

export interface SlashCommand {
  name: string;
  help: string;
  run: (ctx: CommandCtx, args: string) => Promise<void> | void;
}

async function rpc(ctx: CommandCtx, method: string, params: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  try {
    return (await ctx.client.call(method as never, params as never)) as Record<string, unknown>;
  } catch (err) {
    ctx.system(`${method}: ${(err as Error).message}`, "error");
    return null;
  }
}

export const COMMANDS: SlashCommand[] = [
  {
    name: "help",
    help: "Show commands and keys (use /help <cmd> for details)",
    run: (ctx, args) => {
      const query = args.trim();
      if (query) {
        const cmd = COMMANDS.find((c) => c.name === query.replace(/^\//, ""));
        ctx.system(cmd ? `/${cmd.name} — ${cmd.help}` : `unknown command /${query}`);
        return;
      }
      ctx.system("Commands: " + COMMANDS.map((c) => "/" + c.name).join("  "));
      ctx.system(
        "Keys: Tab mode · Esc cancel · Ctrl+T tasks · Ctrl+O verbose · Ctrl+E thinking · " +
          "Ctrl+L clear · Ctrl+C ×2 exit · @ files · ! shell · ? keys",
      );
    },
  },
  {
    name: "init",
    help: "Draft YANTRA.md from the workspace (runs the agent)",
    run: async (ctx) => {
      await ctx.sendPrompt(
        "Draft a YANTRA.md project memory file for this workspace: conventions, key paths, " +
          "standing instructions an agent should know. Write it to YANTRA.md.",
      );
    },
  },
  {
    name: "plan",
    help: "plan show|edit — view the plan or write it to .yantra/plan.json for editing",
    run: async (ctx, args) => {
      const state = ctx.state();
      if (args.trim() === "edit") {
        const runId = state.runId;
        if (!runId) return ctx.system("no active run");
        const trace = await rpc(ctx, "trace.get", { run_id: runId });
        void trace;
        ctx.system("plan editing: edit .yantra/plan.json then send /plan apply", "dim");
        return;
      }
      if (state.tasks.length === 0) return ctx.system("no plan yet");
      for (const task of state.tasks) {
        ctx.system(`${task.id} [${task.status}] ${task.title} (${task.role})`);
      }
    },
  },
  {
    name: "mode",
    help: "mode ask|auto|plan — set the interaction mode (Tab cycles)",
    run: (ctx, args) => {
      const mode = args.trim() as "ask" | "auto" | "plan";
      if (!["ask", "auto", "plan"].includes(mode)) return ctx.system("usage: /mode ask|auto|plan");
      ctx.dispatch({ type: "set", patch: { mode } });
      ctx.system(`mode: ${mode}`, "ok");
    },
  },
  {
    name: "model",
    help: "Show models and routing availability",
    run: async (ctx) => {
      const result = await rpc(ctx, "models.list", {});
      if (!result) return;
      const models = (result["models"] as { id: string; engine: string; params_b: number; healthy: boolean; roles: string[] }[]) ?? [];
      for (const m of models.filter((x) => x.healthy)) {
        ctx.system(`${m.id} (${m.engine}, ${m.params_b}B) roles: ${m.roles.join(",")}`, "ok");
      }
      const down = models.filter((x) => !x.healthy);
      if (down.length > 0) ctx.system(`${down.length} more registered but not being served`, "dim");
    },
  },
  { name: "models", help: "Alias of /model", run: (ctx, args) => COMMANDS.find((c) => c.name === "model")!.run(ctx, args) },
  {
    name: "agents",
    help: "List agent personas",
    run: async (ctx) => {
      const result = await rpc(ctx, "config.get", {});
      if (result) ctx.system("agents are listed with `yantra agents list` (roster is server-side data)");
    },
  },
  {
    name: "rag",
    help: "rag list|use <collection> — knowledge collections",
    run: async (ctx, args) => {
      const [sub] = args.trim().split(/\s+/);
      if (!sub || sub === "list" || sub === "status") {
        const result = await rpc(ctx, "rag.collections", {});
        if (result) {
          const collections = (result["collections"] as { name: string; documents: number }[]) ?? [];
          if (collections.length === 0) ctx.system("no collections indexed yet (yantra index add <path>)");
          for (const c of collections) ctx.system(`${c.name}: ${c.documents} documents`);
        }
        return;
      }
      ctx.system("collection selection applies on the next prompt", "dim");
    },
  },
  {
    name: "search",
    help: "search <query> — raw retrieval with scores (demo view)",
    run: async (ctx, args) => {
      if (!args.trim()) return ctx.system("usage: /search <query>");
      const result = await rpc(ctx, "rag.search", { query: args.trim(), collections: [], k: 8 });
      if (!result) return;
      const hits = (result["hits"] as { title: string; page: number | null; score: number; snippet: string }[]) ?? [];
      if (hits.length === 0) ctx.system("no hits");
      hits.forEach((hit, i) =>
        ctx.system(`${i + 1}. [${hit.score.toFixed(3)}] ${hit.title} p.${hit.page ?? "-"} — ${hit.snippet.slice(0, 80)}`),
      );
    },
  },
  {
    name: "trace",
    help: "Open the span tree for the current (or given) run",
    run: async (ctx, args) => {
      await ctx.openTrace(args.trim() || ctx.state().runId);
    },
  },
  {
    name: "seal",
    help: "seal [verify|demo] — seal status / verification",
    run: async (ctx, args) => {
      const sub = args.trim();
      const method = sub === "verify" ? "seal.verify" : sub === "demo" ? "seal.demo" : "seal.status";
      const result = await rpc(ctx, method, {});
      if (!result) return;
      if (method === "seal.status") {
        ctx.system(
          `sealed: ${result["sealed"]} · blocked attempts: ${result["blocked_attempts_total"]} · allowlist: ${(result["allowlist"] as string[]).join(", ")}`,
          result["sealed"] ? "ok" : "warn",
        );
        return;
      }
      ctx.system(JSON.stringify(result).slice(0, 400));
    },
  },
  {
    name: "memory",
    help: "Show project memory (YANTRA.md) and stored facts",
    run: async (ctx) => {
      const memoryPath = path.join(ctx.workspace, "YANTRA.md");
      if (fs.existsSync(memoryPath)) {
        ctx.system("YANTRA.md:\n" + fs.readFileSync(memoryPath, "utf-8").slice(0, 1200));
      } else {
        ctx.system("no YANTRA.md in this workspace (/init drafts one)");
      }
      const result = await rpc(ctx, "memory.list", {});
      if (result) {
        const memories = (result["memories"] as { kind: string; text: string }[]) ?? [];
        memories.slice(0, 10).forEach((m) => ctx.system(`[${m.kind}] ${m.text.slice(0, 100)}`));
      }
    },
  },
  {
    name: "skills",
    help: "skills [review] — list skills / review proposals",
    run: async (ctx) => {
      const result = await rpc(ctx, "skills.list", {});
      if (!result) return;
      const skills = (result["skills"] as { name: string; description: string; status: string; success_count: number }[]) ?? [];
      if (skills.length === 0) ctx.system("no skills yet");
      skills.forEach((s) =>
        ctx.system(`${s.status === "proposed" ? "⧗" : "✔"} ${s.name} (${s.success_count}×) — ${s.description.slice(0, 70)}`),
      );
    },
  },
  {
    name: "budget",
    help: "budget [tokens=N] [seconds=N] — show or override run budgets",
    run: (ctx, args) => {
      const overrides = { ...ctx.state().budgetOverrides };
      for (const pair of args.trim().split(/\s+/).filter(Boolean)) {
        const [key, value] = pair.split("=");
        if (key && value && !Number.isNaN(Number(value))) {
          overrides[key === "tokens" ? "max_tokens" : key === "seconds" ? "max_seconds" : key] = Number(value);
        }
      }
      ctx.dispatch({ type: "set", patch: { budgetOverrides: overrides } });
      ctx.system(
        Object.keys(overrides).length
          ? "budget overrides for next runs: " + JSON.stringify(overrides)
          : "no overrides; defaults from config apply",
      );
    },
  },
  {
    name: "compact",
    help: "Note: compaction is automatic per step; this shows current context usage",
    run: (ctx) => ctx.system(`context ${ctx.state().stats.contextPct.toFixed(0)}% of the role budget (auto-compacts at 75%)`),
  },
  {
    name: "cost",
    help: "Token usage and the ₹ cost-equivalent proxy",
    run: (ctx) => {
      const stats = ctx.state().stats;
      ctx.system(`tokens ${stats.tokensIn} · ≈₹${stats.costSavedInr.toFixed(2)} API-cost equivalent avoided`);
    },
  },
  {
    name: "resume",
    help: "Pick an earlier session to resume",
    run: async (ctx) => ctx.openResume(),
  },
  {
    name: "fork",
    help: "Fork the current session",
    run: async (ctx) => {
      const result = await rpc(ctx, "session.fork", { session_id: ctx.state().sessionId });
      if (result) {
        ctx.dispatch({ type: "set", patch: { sessionId: String(result["session_id"]) } });
        ctx.system(`forked → session ${String(result["session_id"]).slice(0, 8)}`, "ok");
      }
    },
  },
  { name: "clear", help: "Clear the transcript", run: (ctx) => ctx.dispatch({ type: "clear" }) },
  {
    name: "config",
    help: "Show the effective server configuration summary",
    run: async (ctx) => {
      const result = await rpc(ctx, "config.get", {});
      if (!result) return;
      const config = result["config"] as Record<string, Record<string, unknown>>;
      ctx.system(
        `profile ${result["profile"]} · db ${(config["db"]?.["url"] as string) ?? "sqlite (default)"} · ` +
          `budgets ${JSON.stringify(config["budgets"]).slice(0, 120)}`,
      );
    },
  },
  {
    name: "doctor",
    help: "Run the environment doctor (spawns the CLI)",
    run: (ctx) => {
      const python = process.env["YANTRA_PYTHON"] ?? "python";
      const result = spawnSync(python, ["-m", "yantra_server.cli", "doctor"], { encoding: "utf-8" });
      ctx.system(result.stdout || result.stderr || "doctor produced no output");
    },
  },
  {
    name: "theme",
    help: "Theme note (colors follow your terminal palette)",
    run: (ctx) => ctx.system("yantra uses your terminal palette; no colour-only signals are used"),
  },
  {
    name: "vim",
    help: "Toggle vim-style input (Esc→normal, i→insert)",
    run: (ctx) => {
      const vim = !ctx.state().vim;
      ctx.dispatch({ type: "set", patch: { vim } });
      ctx.system(`vim mode ${vim ? "on" : "off"}`, "ok");
    },
  },
  { name: "exit", help: "Quit yantra", run: (ctx) => ctx.exit() },
  { name: "quit", help: "Alias of /exit", run: (ctx) => ctx.exit() },
];

export function findCommand(name: string): SlashCommand | undefined {
  return COMMANDS.find((c) => c.name === name);
}
