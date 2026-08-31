/** YANTRA terminal UI (SPEC §17): transcript, tool cards, plan review, permissions,
 *  palette, file picker, trace viewer, status line. */

import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Box, Static, Text, useApp, useInput, useStdin, useStdout } from "ink";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import type { RpcClient, ConnectionState } from "./rpc/client.js";
import { COMMANDS, findCommand, type CommandCtx } from "./commands/index.js";
import { EntryView, ToolCard } from "./components/Entries.js";
import { StatusLine, TaskPanel } from "./components/Chrome.js";
import { PermissionView, PlanReviewView, QuestionView } from "./components/Prompts.js";
import { filterItems, PickerView, type PickerItem } from "./components/Picker.js";
import { flattenSpans, TraceViewComponent, type SpanNode, type TraceRow } from "./components/TraceView.js";
import { Spinner } from "./components/Spinner.js";
import { initialState, reduce, type Entry } from "./state.js";
import { detectImageProtocol, inlineImage } from "./imageProto.js";
import { theme } from "./theme.js";

export interface AppProps {
  client: RpcClient;
  workspace: string;
}

interface PickerState {
  kind: "palette" | "file" | "resume";
  query: string;
  selected: number;
  items: PickerItem[];
}

interface TraceState {
  runId: string;
  spans: SpanNode[];
  expanded: Set<string>;
  cursor: number;
  detail: boolean;
}

const IGNORE_DIRS = new Set([".git", "node_modules", ".venv", "__pycache__", ".yantra", "dist"]);

function listWorkspaceFiles(root: string, cap = 1500): string[] {
  const out: string[] = [];
  const walk = (dir: string, depth: number) => {
    if (out.length >= cap || depth > 6) return;
    let names: fs.Dirent[] = [];
    try {
      names = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of names) {
      if (out.length >= cap) return;
      if (IGNORE_DIRS.has(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full, depth + 1);
      else out.push(path.relative(root, full).replace(/\\/g, "/"));
    }
  };
  walk(root, 0);
  return out;
}

export function App({ client, workspace }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const { isRawModeSupported } = useStdin();
  const { stdout } = useStdout();
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const [input, setInput] = useState("");
  const [multiline, setMultiline] = useState<string[]>([]);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [historySearch, setHistorySearch] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const [trace, setTrace] = useState<TraceState | null>(null);
  const [questionBuffer, setQuestionBuffer] = useState("");
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [ctrlCArmed, setCtrlCArmed] = useState(false);
  const [vimInsert, setVimInsert] = useState(true);
  const stateRef = useRef(state);
  stateRef.current = state;
  const renderedImages = useRef(new Set<string>());
  const imageProtocol = useMemo(() => detectImageProtocol(), []);

  useEffect(() => {
    if (imageProtocol === "none") return;
    for (const entry of state.finalized) {
      if (entry.kind !== "image" || renderedImages.current.has(entry.artifactId)) continue;
      renderedImages.current.add(entry.artifactId);
      const url = (process.env["YANTRA_SERVER_URL"] ?? "ws://127.0.0.1:7331/rpc")
        .replace(/^ws/, "http")
        .replace("/rpc", "");
      void fetch(`${url}/api/artifacts/${entry.artifactId}`)
        .then(async (res) => (res.ok ? Buffer.from(await res.arrayBuffer()) : null))
        .then((buf) => {
          if (!buf) return;
          const seq = inlineImage(buf, imageProtocol);
          if (seq) process.stdout.write("\n" + seq + "\n");
        })
        .catch(() => undefined);
    }
  }, [state.finalized, imageProtocol]);

  const system = useCallback(
    (text: string, tone: "dim" | "error" | "ok" | "warn" = "dim") =>
      dispatch({ type: "entry", entry: { kind: "system", text, tone } }),
    [],
  );

  // ---------------------------------------------------------------- rpc wiring
  useEffect(() => {
    const onState = (connection: ConnectionState) => {
      dispatch({ type: "connection", state: connection });
      if (connection !== "open") return;
      void (async () => {
        try {
          const pong = (await client.call("ping", {})) as { version?: string };
          const cfg = (await client.call("config.get", {})) as {
            sealed?: boolean;
            profile?: string;
          };
          const previousSession = stateRef.current.sessionId;
          if (previousSession) {
            await client.call("session.resume", {
              session_id: previousSession,
              last_seq: stateRef.current.runId ? client.lastSeqFor(stateRef.current.runId) : 0,
            });
            dispatch({
              type: "handshake",
              sessionId: previousSession,
              sealed: cfg.sealed ?? true,
              profile: cfg.profile ?? "",
              version: pong.version ?? "",
              mode: stateRef.current.mode,
              workspace,
            });
            return;
          }
          const created = (await client.call("session.create", {
            workspace,
            collections: [],
            mode: stateRef.current.mode,
          })) as { session_id: string };
          dispatch({
            type: "handshake",
            sessionId: created.session_id,
            sealed: cfg.sealed ?? true,
            profile: cfg.profile ?? "",
            version: pong.version ?? "",
            mode: stateRef.current.mode,
            workspace,
          });
        } catch (err) {
          system(`handshake failed: ${(err as Error).message}`, "error");
        }
      })();
    };
    const onNotification = (method: string, params: Record<string, unknown>) =>
      dispatch({ type: "notification", method, params });
    client.on("state", onState);
    client.on("notification", onNotification);
    onState(client.state);
    return () => {
      client.off("state", onState);
      client.off("notification", onNotification);
    };
  }, [client, workspace, system]);

  // ---------------------------------------------------------------- actions
  const sendPrompt = useCallback(
    async (text: string) => {
      dispatch({ type: "entry", entry: { kind: "user", text } });
      try {
        const result = (await client.call("session.prompt", {
          session_id: stateRef.current.sessionId,
          text,
          attachments: [],
          mode: stateRef.current.mode,
          budget_overrides: Object.keys(stateRef.current.budgetOverrides).length
            ? stateRef.current.budgetOverrides
            : null,
        })) as { run_id: string };
        dispatch({ type: "run-started", runId: result.run_id });
      } catch (err) {
        system((err as Error).message, "error");
      }
    },
    [client, system],
  );

  const openTrace = useCallback(
    async (runId: string | null) => {
      if (!runId) {
        system("no run to trace yet");
        return;
      }
      try {
        const result = (await client.call("trace.get", { run_id: runId })) as { spans: SpanNode[] };
        setTrace({ runId, spans: result.spans, expanded: new Set(), cursor: 0, detail: false });
        dispatch({ type: "set", patch: { uiMode: "trace" } });
      } catch (err) {
        system((err as Error).message, "error");
      }
    },
    [client, system],
  );

  const openResume = useCallback(async () => {
    try {
      const result = (await client.call("session.list", { limit: 20 })) as {
        sessions: { session_id: string; workspace: string; last_goal: string | null; updated_at: string; status: string }[];
      };
      const items: PickerItem[] = result.sessions.map((s) => ({
        id: s.session_id,
        label: s.last_goal ? s.last_goal.slice(0, 46) : "(no runs yet)",
        hint: `${s.updated_at.slice(0, 16)} ${s.workspace.slice(-30)}`,
      }));
      setPicker({ kind: "resume", query: "", selected: 0, items });
      dispatch({ type: "set", patch: { uiMode: "resume" } });
    } catch (err) {
      system((err as Error).message, "error");
    }
  }, [client, system]);

  const commandCtx: CommandCtx = useMemo(
    () => ({
      client,
      state: () => stateRef.current,
      dispatch,
      system,
      sendPrompt,
      openTrace,
      openResume,
      workspace,
      exit: () => {
        client.close();
        exit();
      },
    }),
    [client, system, sendPrompt, openTrace, openResume, workspace, exit],
  );

  const submit = useCallback(async () => {
    const joined = [...multiline, input].join("\n");
    setInput("");
    setMultiline([]);
    const text = joined.trim();
    if (!text) return;
    if (!text.startsWith("!")) setHistory((h) => [...h.slice(-200), text]);
    setHistoryIndex(-1);
    if (text.startsWith("/")) {
      const [name, ...rest] = text.slice(1).split(/\s+/);
      const command = findCommand(name ?? "");
      if (!command) {
        system(`unknown command /${name} (try /help)`, "error");
        return;
      }
      await command.run(commandCtx, rest.join(" "));
      return;
    }
    if (text.startsWith("!")) {
      const cmd = text.slice(1).trim();
      dispatch({ type: "entry", entry: { kind: "user", text } });
      const result = spawnSync(cmd, { shell: true, encoding: "utf-8", cwd: workspace, timeout: 60_000 });
      const output = [result.stdout, result.stderr].filter(Boolean).join("\n").slice(0, 6000);
      system(output || `(exit ${result.status})`, result.status === 0 ? "dim" : "error");
      return;
    }
    await sendPrompt(text);
  }, [input, multiline, commandCtx, sendPrompt, system, workspace]);

  const approvePermission = useCallback(
    async (decision: "once" | "always" | "deny", note?: string) => {
      const pending = stateRef.current.permissionQueue[0];
      if (!pending) return;
      try {
        await client.call("run.approve", {
          run_id: stateRef.current.runId ?? "",
          request_id: pending.requestId,
          decision,
          note: note ?? null,
        });
      } catch (err) {
        system((err as Error).message, "error");
      }
      dispatch({ type: "resolve-permission", requestId: pending.requestId });
    },
    [client, system],
  );

  const answerQuestions = useCallback(
    async (answers: string[]) => {
      const question = stateRef.current.question;
      if (!question) return;
      try {
        await client.call("run.approve", {
          run_id: stateRef.current.runId ?? "",
          request_id: question.requestId,
          decision: "once",
          answers,
        });
      } catch (err) {
        system((err as Error).message, "error");
      }
      dispatch({ type: "set", patch: { question: null, uiMode: "input" } });
      setQuestionAnswers([]);
      setQuestionBuffer("");
    },
    [client, system],
  );

  // ---------------------------------------------------------------- input handling
  useInput(
    (char, key) => {
      const ui = stateRef.current.uiMode;
      // global chords
      if (key.ctrl && char === "c") {
        if (ctrlCArmed) {
          client.close();
          exit();
          return;
        }
        setCtrlCArmed(true);
        setTimeout(() => setCtrlCArmed(false), 1500);
        return;
      }
      if (key.ctrl && char === "l") return dispatch({ type: "clear" });
      if (key.ctrl && char === "t")
        return dispatch({ type: "set", patch: { showTasks: !stateRef.current.showTasks } });
      if (key.ctrl && char === "o")
        return dispatch({ type: "set", patch: { verbose: !stateRef.current.verbose } });
      if (key.ctrl && char === "e")
        return dispatch({ type: "set", patch: { showThinking: !stateRef.current.showThinking } });

      if (ui === "trace" && trace) {
        const rows = flattenSpans(trace.spans, trace.expanded);
        if (char === "q" || key.escape) {
          setTrace(null);
          dispatch({ type: "set", patch: { uiMode: "input" } });
        } else if (key.upArrow) setTrace({ ...trace, cursor: Math.max(0, trace.cursor - 1) });
        else if (key.downArrow)
          setTrace({ ...trace, cursor: Math.min(rows.length - 1, trace.cursor + 1) });
        else if (key.rightArrow) {
          const row = rows[trace.cursor];
          if (row) {
            const expanded = new Set(trace.expanded);
            expanded.add(row.span.span_id);
            setTrace({ ...trace, expanded });
          }
        } else if (key.leftArrow) {
          const row = rows[trace.cursor];
          if (row) {
            const expanded = new Set(trace.expanded);
            expanded.delete(row.span.span_id);
            setTrace({ ...trace, expanded });
          }
        } else if (key.return) setTrace({ ...trace, detail: !trace.detail });
        return;
      }

      if (picker) {
        const filtered = filterItems(picker.items, picker.query);
        if (key.escape) {
          setPicker(null);
          dispatch({ type: "set", patch: { uiMode: "input" } });
        } else if (key.upArrow)
          setPicker((prev) => (prev ? { ...prev, selected: Math.max(0, prev.selected - 1) } : prev));
        else if (key.downArrow)
          setPicker((prev) =>
            prev ? { ...prev, selected: Math.min(filtered.length - 1, prev.selected + 1) } : prev,
          );
        else if (key.return) {
          const chosen = filtered[picker.selected];
          setPicker(null);
          dispatch({ type: "set", patch: { uiMode: "input" } });
          if (!chosen) {
            if (picker.kind === "palette" && picker.query.trim()) {
              const raw = picker.query.trim().replace(/^\//, "");
              const [name, ...rest] = raw.split(/\s+/);
              const command = findCommand(name ?? "");
              if (command) void command.run(commandCtx, rest.join(" "));
              else system(`unknown command /${name} (try /help)`, "error");
            }
            return;
          }
          if (picker.kind === "file") setInput((v) => v + chosen.id + " ");
          else if (picker.kind === "palette") {
            setInput("");
            void findCommand(chosen.id)?.run(commandCtx, "");
          } else if (picker.kind === "resume") {
            void (async () => {
              try {
                await client.call("session.resume", { session_id: chosen.id, last_seq: 0 });
                dispatch({ type: "set", patch: { sessionId: chosen.id } });
                dispatch({ type: "clear" });
                system(`resumed session ${chosen.id.slice(0, 8)} — ${chosen.label}`, "ok");
              } catch (err) {
                system((err as Error).message, "error");
              }
            })();
          }
        } else if (key.backspace || key.delete)
          setPicker((prev) => (prev ? { ...prev, query: prev.query.slice(0, -1), selected: 0 } : prev));
        else if (char && !key.ctrl && !key.meta)
          setPicker((prev) => (prev ? { ...prev, query: prev.query + char, selected: 0 } : prev));
        return;
      }

      if (ui === "permission") {
        if (char === "y") void approvePermission("once");
        else if (char === "a") void approvePermission("always");
        else if (char === "n" || key.escape) void approvePermission("deny");
        else if (char === "e") system("explanation requested — the agent's rationale is in /trace (llm.call spans)");
        return;
      }

      if (ui === "planreview") {
        const pending = stateRef.current.permissionQueue.find((p) => p.isPlan);
        if (!pending) {
          dispatch({ type: "set", patch: { uiMode: "input" } });
          return;
        }
        if (key.return) {
          void approvePermission("once");
        } else if (char === "n" || key.escape) {
          void approvePermission("deny");
        } else if (char === "e") {
          const planPath = path.join(workspace, ".yantra", "plan.json");
          fs.mkdirSync(path.dirname(planPath), { recursive: true });
          fs.writeFileSync(planPath, JSON.stringify({ tasks: stateRef.current.tasks }, null, 2));
          system(`plan written to ${planPath}; edit it, then press Enter to run (server-side plan wins) `);
        }
        return;
      }

      if (ui === "question" && stateRef.current.question) {
        if (key.return) {
          const answers = [...questionAnswers, questionBuffer];
          setQuestionBuffer("");
          if (answers.length >= stateRef.current.question.questions.length) {
            void answerQuestions(answers);
          } else {
            setQuestionAnswers(answers);
          }
        } else if (key.backspace || key.delete) setQuestionBuffer((v) => v.slice(0, -1));
        else if (char && !key.ctrl && !key.meta) setQuestionBuffer((v) => v + char);
        return;
      }

      // ---- normal input mode
      if (key.escape) {
        if (stateRef.current.vim) setVimInsert(false);
        if (stateRef.current.runActive && stateRef.current.runId) {
          void client.call("run.cancel", { run_id: stateRef.current.runId });
          system("cancelling run…", "warn");
        }
        return;
      }
      if (stateRef.current.vim && !vimInsert) {
        if (char === "i" || char === "a") setVimInsert(true);
        return;
      }
      if (key.tab) return dispatch({ type: "cycle-mode" });
      if (key.return) {
        if (input.endsWith("\\")) {
          setMultiline((m) => [...m, input.slice(0, -1)]);
          setInput("");
          return;
        }
        void submit();
        return;
      }
      if (key.upArrow) {
        if (history.length === 0) return;
        const index = historyIndex < 0 ? history.length - 1 : Math.max(0, historyIndex - 1);
        setHistoryIndex(index);
        setInput(history[index] ?? "");
        return;
      }
      if (key.downArrow) {
        if (historyIndex < 0) return;
        const index = historyIndex + 1;
        if (index >= history.length) {
          setHistoryIndex(-1);
          setInput("");
        } else {
          setHistoryIndex(index);
          setInput(history[index] ?? "");
        }
        return;
      }
      if (key.ctrl && char === "r") {
        setHistorySearch("");
        return;
      }
      if (historySearch !== null) {
        if (key.return || key.escape) {
          setHistorySearch(null);
          return;
        }
        const query = key.backspace || key.delete ? historySearch.slice(0, -1) : historySearch + (char ?? "");
        setHistorySearch(query);
        const match = [...history].reverse().find((h) => h.includes(query));
        if (match) setInput(match);
        return;
      }
      if (key.backspace || key.delete) {
        setInput((v) => v.slice(0, -1));
        return;
      }
      if (char === "?" && input === "") {
        void findCommand("help")?.run(commandCtx, "");
        return;
      }
      if (char === "/" && input === "") {
        setPicker({
          kind: "palette",
          query: "",
          selected: 0,
          items: COMMANDS.map((c) => ({ id: c.name, label: "/" + c.name, hint: c.help })),
        });
        dispatch({ type: "set", patch: { uiMode: "palette" } });
        return;
      }
      if (char === "@") {
        const files = listWorkspaceFiles(workspace).map((f) => ({ id: "@" + f, label: f }));
        setPicker({ kind: "file", query: "", selected: 0, items: files });
        dispatch({ type: "set", patch: { uiMode: "filepick" } });
        return;
      }
      if (char && !key.ctrl && !key.meta) setInput((v) => v + char);
    },
    { isActive: isRawModeSupported === true },
  );

  // ---------------------------------------------------------------- render
  const liveTools = [...state.liveTools.values()];
  const pendingPermission = state.permissionQueue.find((p) => !p.isPlan);
  const showPlanReview = state.uiMode === "planreview" && state.permissionQueue.some((p) => p.isPlan);
  const rows: TraceRow[] = trace ? flattenSpans(trace.spans, trace.expanded) : [];

  return (
    <Box flexDirection="column">
      {state.connection !== "open" && state.finalized.length === 0 ? (
        <Text color={theme.dim}>
          connecting to yantra-server ({state.connection})… start it with: yantra serve
        </Text>
      ) : null}
      <Static items={state.finalized.map((entry, index) => ({ entry, index }))}>
        {({ entry, index }: { entry: Entry; index: number }) => (
          <EntryView key={index} entry={entry} verbose={state.verbose} />
        )}
      </Static>

      {liveTools.map((tool) => (
        <ToolCard key={tool.stepId} entry={tool} verbose={state.verbose} live />
      ))}
      {state.spinnerActive && state.runActive && (
        <Spinner thinking={state.thinking} expanded={state.showThinking} />
      )}
      <TaskPanel state={state} />

      {state.uiMode === "trace" && trace ? (
        <TraceViewComponent
          runId={trace.runId}
          rows={rows}
          cursor={trace.cursor}
          detail={trace.detail}
          height={stdout?.rows ?? 30}
        />
      ) : null}
      {picker ? (
        <PickerView
          title={picker.kind === "palette" ? "/" : picker.kind === "file" ? "@" : "resume"}
          query={picker.query}
          items={filterItems(picker.items, picker.query)}
          selected={picker.selected}
        />
      ) : null}
      {pendingPermission && state.uiMode === "permission" ? (
        <PermissionView pending={pendingPermission} />
      ) : null}
      {showPlanReview ? <PlanReviewView state={state} /> : null}
      {state.uiMode === "question" && state.question ? (
        <QuestionView question={state.question} buffer={questionBuffer} answered={questionAnswers} />
      ) : null}

      {state.uiMode === "input" || state.uiMode === "palette" || state.uiMode === "filepick" ? (
        <Box paddingX={1} flexDirection="column">
          {multiline.map((line, index) => (
            <Text key={index} color={theme.dim}>
              {"… "}
              {line}
            </Text>
          ))}
          <Text>
            <Text color={theme.accent}>{"> "}</Text>
            {historySearch !== null ? (
              <Text color={theme.warn}>(reverse-i-search “{historySearch}”) </Text>
            ) : null}
            {input}
            <Text color={theme.dim}>█</Text>
            {stateRef.current.vim && !vimInsert ? <Text color={theme.warn}> -- NORMAL --</Text> : null}
          </Text>
        </Box>
      ) : null}
      {ctrlCArmed ? (
        <Text color={theme.warn}> press Ctrl+C again to exit</Text>
      ) : null}
      <StatusLine state={state} />
    </Box>
  );
}
