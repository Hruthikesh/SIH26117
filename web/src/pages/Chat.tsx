import React, { useEffect, useRef, useState } from "react";
import { RpcClient } from "../rpc.js";
import { Pill, timeAgo } from "../components.js";
import { Markdown } from "../md.js";

/* The workbench: a coding-agent-grade chat surface over the same JSON-RPC the TUI speaks.
   Sessions resume with their history; events stream live; every action is inspectable. */

type Entry =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "thinking"; text: string; done: boolean }
  | { kind: "plan"; tasks: { id: string; title: string; role: string }[] }
  | { kind: "tool"; stepId: string; tool: string; argsPreview: string; output: string; summary?: string; ok?: boolean; done: boolean }
  | { kind: "verify"; taskId: string; verdict: string; score: number | null }
  | { kind: "escalation"; taskId: string; rung: string; attempt: number }
  | { kind: "permission"; requestId: string; tool: string; argsPreview: string; explanation: string; resolved?: string }
  | { kind: "question"; requestId: string; questions: string[]; resolved?: boolean }
  | { kind: "finished"; status: string; summary: string; artifacts: { name?: string; path?: string }[] }
  | { kind: "error"; message: string }
  | { kind: "system"; text: string };

interface TaskChip { id: string; title: string; status: string }
interface Stats { model: string; tokensOut: number; ctxPct: number; elapsed: number }
interface SessionInfo { session_id: string; title: string | null; workspace: string; mode: string; updated_at: string; last_goal: string | null }

function argsPreview(args: Record<string, unknown>): string {
  const s = Object.entries(args ?? {})
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return s.length > 110 ? s.slice(0, 110) + "…" : s;
}

export function ChatPage(): React.ReactElement {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [tasks, setTasks] = useState<Record<string, TaskChip>>({});
  const [input, setInput] = useState("");
  const [workspace, setWorkspace] = useState("C:\\Users\\HP");
  const [mode, setMode] = useState<"auto" | "ask" | "plan">("auto");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [queued, setQueued] = useState<string[]>([]);
  const rpc = useRef<RpcClient | null>(null);
  const runIdRef = useRef<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const queuedRef = useRef<string[]>([]);
  const historyRef = useRef<string[]>([]);
  const historyPos = useRef(-1);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  const push = (e: Entry) => setEntries((prev) => [...prev, e]);
  const patch = (fn: (prev: Entry[]) => Entry[]) => setEntries(fn);

  const refreshSessions = () =>
    rpc.current
      ?.call<{ sessions: SessionInfo[] }>("session.list", { limit: 20 })
      .then((d) => setSessions(d.sessions))
      .catch(() => undefined);

  useEffect(() => {
    const client = new RpcClient((method, p) => {
      switch (method) {
        case "assistant.delta":
          patch((prev) => {
            const last = prev[prev.length - 1];
            if (last?.kind === "assistant") return [...prev.slice(0, -1), { ...last, text: last.text + p.text }];
            return [...prev, { kind: "assistant", text: String(p.text ?? "") }];
          });
          break;
        case "thinking.delta":
          patch((prev) => {
            const last = prev[prev.length - 1];
            if (last?.kind === "thinking" && !last.done) return [...prev.slice(0, -1), { ...last, text: (last.text + p.text).slice(-4000) }];
            return [...prev, { kind: "thinking", text: String(p.text ?? ""), done: false }];
          });
          break;
        case "plan.updated":
          push({ kind: "plan", tasks: (p.plan?.tasks ?? []).map((t: any) => ({ id: t.id, title: t.title, role: t.role })) });
          break;
        case "task.updated": {
          const t = p.task ?? {};
          const tid = t.task_id ?? t.id;
          if (tid) setTasks((prev) => ({ ...prev, [tid]: { id: String(tid), title: t.title ?? "", status: t.status ?? "" } }));
          break;
        }
        case "tool.started":
          patch((prev) => [
            ...prev.map((e) => (e.kind === "thinking" ? { ...e, done: true } : e)),
            { kind: "tool", stepId: String(p.step_id), tool: String(p.tool), argsPreview: argsPreview(p.args), output: "", done: false },
          ]);
          break;
        case "tool.output":
          patch((prev) => prev.map((e) => (e.kind === "tool" && e.stepId === p.step_id && !e.done ? { ...e, output: (e.output + p.text).slice(-6000) } : e)));
          break;
        case "tool.finished":
          patch((prev) => prev.map((e) => (e.kind === "tool" && e.stepId === p.step_id ? { ...e, done: true, ok: Boolean(p.ok), summary: String(p.summary ?? "") } : e)));
          break;
        case "verify.result":
          push({ kind: "verify", taskId: String(p.task_id), verdict: String(p.report?.verdict ?? "?"), score: p.report?.reviewer?.score ?? null });
          break;
        case "escalation":
          push({ kind: "escalation", taskId: String(p.task_id), rung: String(p.rung), attempt: Number(p.attempt ?? 1) });
          break;
        case "permission.request":
          push({ kind: "permission", requestId: String(p.request_id), tool: String(p.tool ?? "action"), argsPreview: argsPreview(p.args), explanation: String(p.explanation ?? "") });
          break;
        case "question":
          push({ kind: "question", requestId: String(p.request_id), questions: p.questions ?? [] });
          break;
        case "run.stats":
          setStats({ model: String(p.active_model ?? ""), tokensOut: Number(p.tokens_out ?? 0), ctxPct: Number(p.context_pct ?? 0), elapsed: Number(p.elapsed_s ?? 0) });
          break;
        case "run.finished": {
          setRunning(false);
          patch((prev) => [
            ...prev.map((e) => (e.kind === "thinking" ? { ...e, done: true } : e)),
            { kind: "finished", status: String(p.status), summary: String(p.summary ?? ""), artifacts: p.artifacts ?? [] },
          ]);
          refreshSessions();
          const next = queuedRef.current.shift();
          setQueued([...queuedRef.current]);
          if (next) void promptRun(next);
          break;
        }
        case "error":
          push({ kind: "error", message: `${p.code}: ${p.message}` });
          break;
      }
    }, setConnected);
    client.connect();
    rpc.current = client;
    const t = setTimeout(refreshSessions, 400);
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && runIdRef.current) void client.call("run.cancel", { run_id: runIdRef.current });
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      client.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (pinned.current) scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [entries, tasks]);

  const promptRun = async (text: string) => {
    if (!rpc.current || !sessionRef.current) return;
    setRunning(true);
    setStats(null);
    setTasks({});
    try {
      const res = await rpc.current.call<{ run_id: string }>("session.prompt", { session_id: sessionRef.current, text, mode });
      runIdRef.current = res.run_id;
    } catch (e) {
      setRunning(false);
      push({ kind: "error", message: String(e) });
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || !rpc.current) return;
    setInput("");
    historyRef.current = [text, ...historyRef.current].slice(0, 50);
    historyPos.current = -1;
    push({ kind: "user", text });
    if (running) {
      queuedRef.current = [...queuedRef.current, text];
      setQueued([...queuedRef.current]);
      push({ kind: "system", text: "queued — will run when the current goal finishes" });
      return;
    }
    try {
      if (!sessionRef.current) {
        const created = await rpc.current.call<{ session_id: string }>("session.create", { workspace, collections: [], mode, title: text.slice(0, 60) });
        sessionRef.current = created.session_id;
        setSessionId(created.session_id);
        push({ kind: "system", text: `session started in ${workspace} · mode ${mode}` });
        refreshSessions();
      }
      await promptRun(text);
    } catch (e) {
      setRunning(false);
      push({ kind: "error", message: String(e) });
    }
  };

  const resume = async (info: SessionInfo) => {
    if (!rpc.current || running) return;
    setEntries([]);
    setTasks({});
    setStats(null);
    runIdRef.current = null;
    sessionRef.current = info.session_id;
    setSessionId(info.session_id);
    setWorkspace(info.workspace);
    if (info.mode === "auto" || info.mode === "ask" || info.mode === "plan") setMode(info.mode);
    try {
      const data = await rpc.current.call<any>("session.resume", { session_id: info.session_id, last_seq: 0 });
      const history: Entry[] = [{ kind: "system", text: `resumed session in ${info.workspace}` }];
      for (const run of data.runs ?? []) {
        history.push({ kind: "user", text: run.goal });
        if (run.final?.summary) {
          history.push({ kind: "finished", status: run.status, summary: run.final.summary, artifacts: run.final.artifacts ?? [] });
        } else {
          history.push({ kind: "system", text: `run ${String(run.run_id).slice(0, 8)} · ${run.status}` });
        }
        if (run.status === "running" || run.status === "planning") {
          runIdRef.current = run.run_id;
          setRunning(true);
        }
      }
      setEntries(history);
    } catch (e) {
      push({ kind: "error", message: String(e) });
    }
  };

  const approve = async (requestId: string, decision: string, answers?: string[]) => {
    if (!rpc.current || !runIdRef.current) return;
    await rpc.current.call("run.approve", { run_id: runIdRef.current, request_id: requestId, decision, answers });
    patch((prev) =>
      prev.map((e) => {
        if (e.kind === "permission" && e.requestId === requestId) return { ...e, resolved: decision };
        if (e.kind === "question" && e.requestId === requestId) return { ...e, resolved: true };
        return e;
      }),
    );
  };

  const reset = () => {
    sessionRef.current = null;
    runIdRef.current = null;
    queuedRef.current = [];
    setSessionId(null);
    setEntries([]);
    setTasks({});
    setStats(null);
    setRunning(false);
    setQueued([]);
  };

  const onInputKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
      return;
    }
    if (e.key === "ArrowUp" && !input) {
      const h = historyRef.current;
      if (h.length) {
        historyPos.current = Math.min(historyPos.current + 1, h.length - 1);
        setInput(h[historyPos.current] ?? "");
        e.preventDefault();
      }
    }
    if (e.key === "ArrowDown" && historyPos.current >= 0) {
      historyPos.current -= 1;
      setInput(historyPos.current >= 0 ? (historyRef.current[historyPos.current] ?? "") : "");
      e.preventDefault();
    }
  };

  const taskList = Object.values(tasks);

  return (
    <div className="wb">
      <div className="wb-rail">
        <button className="primary" style={{ width: "100%" }} onClick={reset}>+ New session</button>
        <div className="wb-rail-list">
          {sessions.map((s) => (
            <div key={s.session_id} className={`wb-sess ${s.session_id === sessionId ? "on" : ""}`} onClick={() => resume(s)}>
              <div className="wb-sess-title">{s.title || s.last_goal || "(untitled)"}</div>
              <div className="wb-sess-meta">{timeAgo(s.updated_at)} · {s.workspace.split("\\").pop()}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="chat-shell">
        <div className="chat-topbar">
          <span className="muted">workspace</span>
          <input className="ws-input" value={workspace} onChange={(e) => setWorkspace(e.target.value)} disabled={sessionId !== null} spellCheck={false} />
          <div className="mode-tabs">
            {(["auto", "ask", "plan"] as const).map((m) => (
              <button key={m} className={mode === m ? "mode on" : "mode"} onClick={() => setMode(m)}>{m}</button>
            ))}
          </div>
          <span style={{ flex: 1 }} />
          {connected ? <Pill tone="ok">connected</Pill> : <Pill tone="bad">reconnecting…</Pill>}
        </div>

        <div
          className="term"
          ref={scroller}
          onScroll={() => {
            const el = scroller.current;
            if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
          }}
        >
          {entries.length === 0 && (
            <div className="term-welcome">
              <div className="term-box">
                <div className="term-logo">✻ Welcome to YANTRA</div>
                <div className="t-path">cwd: {workspace}</div>
              </div>
              <div>Type a goal below. The agent plans it, works step by step in your workspace, verifies its own work, and shows every tool call here.</div>
              <div className="term-hints">
                <span>"Create a folder reports and write status.txt inside it"</span>
                <span>"Read the files in this folder and summarise them into notes.md"</span>
                <span>Enter send · Shift+Enter newline · ↑ history · Esc stop</span>
              </div>
            </div>
          )}
          {entries.map((e, i) => <EntryView key={i} e={e} onApprove={approve} />)}
          {running && <div className="t-running">▍ working…</div>}
        </div>

        {taskList.length > 0 && (
          <div className="task-strip">
            {taskList.map((t) => (
              <span key={t.id} className={`task-chip s-${t.status}`} title={t.title}>
                {t.status === "done" ? "✓" : t.status === "running" ? "●" : t.status === "failed" || t.status === "partial" ? "✗" : "○"} {t.id.split(":").pop()}
              </span>
            ))}
            {queued.length > 0 && <span className="task-chip">⧗ {queued.length} queued</span>}
          </div>
        )}

        <div className="chat-inputrow">
          <span className="t-prompt">❯</span>
          <textarea
            rows={1}
            value={input}
            placeholder={running ? "running — Enter queues the next goal, Esc stops" : "Describe what you want done…"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onInputKey}
          />
          {running ? (
            <button className="danger" onClick={() => runIdRef.current && rpc.current?.call("run.cancel", { run_id: runIdRef.current })}>Stop</button>
          ) : (
            <button className="primary" onClick={send} disabled={!input.trim()}>Send</button>
          )}
        </div>
        <div className="chat-statusline">
          {stats ? (
            <>model <b>{stats.model || "…"}</b> · {stats.tokensOut.toLocaleString()} tok out · ctx {Math.round(stats.ctxPct)}% · {Math.round(stats.elapsed)}s</>
          ) : (
            <>mode <b>{mode}</b> · every action is sandboxed, verified and audit-logged</>
          )}
        </div>
      </div>
    </div>
  );
}

function ToolCard({ e }: { e: Extract<Entry, { kind: "tool" }> }): React.ReactElement {
  const [open, setOpen] = useState(false);
  const hasOutput = e.output.trim().length > 0;
  return (
    <div className="t-tool">
      <div className={hasOutput ? "t-tool-head click" : "t-tool-head"} onClick={() => hasOutput && setOpen(!open)}>
        <span className={e.done ? (e.ok ? "t-dot ok" : "t-dot bad") : "t-dot run"}>●</span> <b>{e.tool}</b>{" "}
        <span className="t-args">{e.argsPreview}</span>
        {hasOutput && e.done && <span className="t-expander">{open ? "▾" : "▸"}</span>}
      </div>
      {hasOutput && (open || !e.done) && (
        <pre className="t-out">
          {(open ? e.output : e.output.slice(-1200)).split("\n").map((line, i) => (
            <div key={i} className={line.startsWith("+") ? "d-add" : line.startsWith("-") ? "d-del" : undefined}>{line || " "}</div>
          ))}
        </pre>
      )}
      {e.done && <div className="t-result">⎿ {e.ok ? "✔" : "✘"} {e.summary}</div>}
    </div>
  );
}

function EntryView({ e, onApprove }: { e: Entry; onApprove: (id: string, d: string, a?: string[]) => void }): React.ReactElement | null {
  const [answer, setAnswer] = useState("");
  switch (e.kind) {
    case "user":
      return <div className="t-user"><span className="t-prompt">❯</span> {e.text}</div>;
    case "assistant":
      return <div className="t-assistant"><Markdown text={e.text} /></div>;
    case "thinking":
      return e.done ? null : <div className="t-thinking">✳ {e.text.slice(-160)}</div>;
    case "system":
      return <div className="t-system">{e.text}</div>;
    case "plan":
      return (
        <div className="t-card">
          <div className="t-card-head">Plan · {e.tasks.length} task{e.tasks.length === 1 ? "" : "s"}</div>
          {e.tasks.map((t) => (
            <div key={t.id} className="t-plan-row"><span className="t-tid">{t.id}</span> {t.title} <span className="t-role">{t.role}</span></div>
          ))}
        </div>
      );
    case "tool":
      return <ToolCard e={e} />;
    case "verify":
      return <div className={`t-verify ${e.verdict === "pass" ? "ok" : "warn"}`}>verify {e.taskId.split(":").pop()}: {e.verdict}{e.score != null ? ` (reviewer ${e.score})` : ""}</div>;
    case "escalation":
      return <div className="t-escalation">↻ {e.taskId.split(":").pop()} escalating: {e.rung} (attempt {e.attempt})</div>;
    case "permission":
      return (
        <div className="t-card ask">
          <div className="t-card-head">Permission — <b>{e.tool}</b></div>
          <div className="t-args" style={{ margin: "4px 0 8px" }}>{e.argsPreview}{e.explanation ? ` — ${e.explanation}` : ""}</div>
          {e.resolved ? (
            <div className="t-system">answered: {e.resolved}</div>
          ) : (
            <div className="t-btnrow">
              <button className="primary" onClick={() => onApprove(e.requestId, "once")}>Allow once</button>
              <button onClick={() => onApprove(e.requestId, "always")}>Always this session</button>
              <button className="danger" onClick={() => onApprove(e.requestId, "deny")}>Deny</button>
            </div>
          )}
        </div>
      );
    case "question":
      return (
        <div className="t-card ask">
          <div className="t-card-head">The agent asks</div>
          {e.questions.map((q, i) => <div key={i} style={{ margin: "2px 0" }}>{q}</div>)}
          {e.resolved ? (
            <div className="t-system">answered</div>
          ) : (
            <div className="t-btnrow">
              <input className="ws-input" style={{ flex: 1 }} value={answer} onChange={(ev) => setAnswer(ev.target.value)} placeholder="Your answer…" />
              <button className="primary" onClick={() => onApprove(e.requestId, "once", [answer])}>Answer</button>
            </div>
          )}
        </div>
      );
    case "finished":
      return (
        <div className={`t-card done ${e.status === "done" ? "" : "gaps"}`}>
          <div className="t-card-head">{e.status === "done" ? "✔ Done" : e.status === "done_with_gaps" ? "◐ Done with gaps" : `✘ ${e.status}`}</div>
          <div className="t-final"><Markdown text={e.summary} /></div>
          {e.artifacts.length > 0 && (
            <div className="t-artifacts">
              {e.artifacts.map((a, i) => <div key={i}>📄 {a.path ?? a.name}</div>)}
            </div>
          )}
        </div>
      );
    case "error":
      return <div className="t-error">✘ {e.message}</div>;
    default:
      return null;
  }
}
