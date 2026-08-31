import React, { useEffect, useRef, useState } from "react";
import { getJson, LiveFeed, postJson, type SpanRow } from "../api.js";
import { Card, Empty, Page, Pill, Section, statusTone, timeAgo } from "../components.js";

interface RunSummary {
  run_id: string;
  goal: string;
  status: string;
  mode: string;
  created_at: string;
}

const KIND_COLOR: Record<string, string> = {
  "llm.call": "#2e90fa",
  "llm.embed": "#84adff",
  "tool.call": "#12b76a",
  retrieval: "#f79009",
  verify: "var(--violet)",
};
const KIND_LABEL: Record<string, string> = {
  "llm.call": "model",
  "tool.call": "tool",
  retrieval: "retrieval",
  verify: "verify",
};

export function RunsPage(): React.ReactElement {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [spans, setSpans] = useState<SpanRow[]>([]);
  const [detail, setDetail] = useState<SpanRow | null>(null);
  const [live, setLive] = useState<string>("");
  const feed = useRef<LiveFeed | null>(null);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  const refreshRuns = () =>
    getJson<{ runs: RunSummary[] }>("/api/runs")
      .then((d) => {
        setRuns(d.runs);
        const first = d.runs[0];
        if (selectedRef.current === null && first) void openRun(first.run_id);
      })
      .catch(() => undefined);

  useEffect(() => {
    refreshRuns();
    feed.current = new LiveFeed((method, params) => {
      if (method === "task.updated" || method === "run.finished") refreshRuns();
      if (method === "tool.started") setLive(`running ${params.tool}`);
      if (method === "tool.finished") setLive(String(params.summary ?? ""));
      if (method === "run.finished") setLive("");
    });
    feed.current.connect();
    const timer = setInterval(refreshRuns, 4000);
    return () => {
      feed.current?.close();
      clearInterval(timer);
    };
  }, []);

  const openRun = async (runId: string) => {
    setSelected(runId);
    setDetail(null);
    const data = await getJson<{ spans: SpanRow[] }>(`/api/runs/${runId}/trace`);
    setSpans(data.spans);
  };

  const minStart = spans.length ? Math.min(...spans.map((s) => s.start_ns)) : 0;
  const maxEnd = spans.length ? Math.max(...spans.map((s) => s.end_ns)) : 1;
  const totalNs = Math.max(1, maxEnd - minStart);
  const selectedRun = runs.find((r) => r.run_id === selected) ?? null;
  const counts = spans.reduce<Record<string, number>>((acc, s) => {
    acc[s.kind] = (acc[s.kind] ?? 0) + 1;
    return acc;
  }, {});

  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const startRun = async () => {
    if (!goal.trim()) return;
    setStarting(true);
    setStartError(null);
    try {
      const result = await postJson<{ run_id: string }>("/api/runs", { goal: goal.trim() });
      setGoal("");
      await refreshRuns();
      await openRun(result.run_id);
    } catch (e) {
      setStartError(String(e));
    } finally {
      setStarting(false);
    }
  };

  return (
    <Page
      title="Runs"
      desc="Give the workbench a goal here or from the terminal — same engine, same trace."
      actions={live ? <Pill tone="accent">{live}</Pill> : undefined}
    >
      <Card style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !starting && startRun()}
            placeholder='Describe a goal — e.g. "Create a folder reports and write status.txt inside it"'
            style={{
              flex: 1, padding: "9px 13px", border: "1px solid var(--border)", borderRadius: 8,
              fontSize: 13.5, fontFamily: "var(--font)", background: "var(--surface)", color: "var(--ink)",
            }}
          />
          <button className="primary" onClick={startRun} disabled={starting || !goal.trim()}>
            {starting ? "Starting…" : "Run"}
          </button>
        </div>
        {startError && <div className="muted" style={{ color: "var(--bad)", marginTop: 8 }}>{startError}</div>}
      </Card>
      {runs.length === 0 ? (
        <Empty
          glyph="▶"
          title="No runs yet"
          hint={<>Start one from a terminal: <code>yantra run "your goal"</code></>}
        />
      ) : (
        <div className="runs-layout">
          <div className="run-list">
            {runs.map((run) => (
              <div
                key={run.run_id}
                className={`run-card ${run.run_id === selected ? "selected" : ""}`}
                onClick={() => openRun(run.run_id)}
              >
                <div className="run-meta">
                  <Pill tone={statusTone(run.status)}>{run.status.replace(/_/g, " ")}</Pill>
                  <span className="muted">{timeAgo(run.created_at)}</span>
                </div>
                <div className="run-goal">{run.goal}</div>
                <div className="muted">
                  mode <span className="mono">{run.mode}</span> · <span className="mono">{run.run_id.slice(0, 8)}</span>
                </div>
              </div>
            ))}
          </div>

          <div>
            {selectedRun === null ? (
              <Empty glyph="◧" title="Select a run" hint="Its span waterfall and timings appear here." />
            ) : (
              <>
                <Card>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 650, marginBottom: 2 }}>{selectedRun.goal}</div>
                      <div className="muted">
                        {spans.length} spans · {(totalNs / 1e9).toFixed(1)}s total ·{" "}
                        <span className="mono">{selectedRun.run_id}</span>
                      </div>
                    </div>
                    <Pill tone={statusTone(selectedRun.status)}>{selectedRun.status.replace(/_/g, " ")}</Pill>
                  </div>
                </Card>

                <Section>Execution trace</Section>
                <Card>
                  <div className="legend" style={{ marginBottom: 10 }}>
                    {Object.entries(KIND_LABEL).map(([kind, label]) => (
                      <span key={kind}>
                        <span className="swatch" style={{ background: KIND_COLOR[kind] }} />
                        {label} {counts[kind] ? `(${counts[kind]})` : ""}
                      </span>
                    ))}
                  </div>
                  {spans.map((span) => {
                    const left = ((span.start_ns - minStart) / totalNs) * 100;
                    const width = Math.max(0.4, ((span.end_ns - span.start_ns) / totalNs) * 100);
                    const ms = (span.end_ns - span.start_ns) / 1e6;
                    return (
                      <div key={span.span_id} className="span-row" onClick={() => setDetail(span)}>
                        <span className="span-name">{span.name.slice(0, 18)}</span>
                        <div className="span-track">
                          <div
                            className="bar"
                            style={{
                              left: `${left}%`,
                              width: `${width}%`,
                              background: span.status === "error" ? "#f04438" : KIND_COLOR[span.kind] ?? "#98a2b3",
                            }}
                          />
                        </div>
                        <span className="span-ms">{ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms.toFixed(0)}ms`}</span>
                      </div>
                    );
                  })}
                </Card>

                {detail && (
                  <>
                    <Section>
                      Span · {detail.name} <span style={{ textTransform: "none", letterSpacing: 0 }}>({detail.kind})</span>
                    </Section>
                    <Card>
                      <pre>{JSON.stringify(detail.attrs, null, 2)}</pre>
                    </Card>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
