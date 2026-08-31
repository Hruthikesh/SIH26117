import React, { useEffect, useState } from "react";
import { getJson, postJson, type EngineStatus, type ModelInfo, type RoleAssignment } from "../api.js";
import { Card, Page, Pill, Section, statusTone } from "../components.js";

interface Candidate {
  path: string;
  name: string;
  kind: string;
  source: string;
  size_gb: number;
  registered: boolean;
}

const ROLE_HINT: Record<string, string> = {
  planner: "breaks goals into tasks",
  executor: "does the work, tool by tool",
  reviewer: "checks the result",
  router: "classifies and dispatches",
  utility: "small fast jobs",
  embed: "turns text into vectors",
  rerank: "orders search results",
  vision: "reads images",
  ocr: "reads scanned documents",
};

export function ModelsPage(): React.ReactElement {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [engines, setEngines] = useState<EngineStatus[]>([]);
  const [assignments, setAssignments] = useState<RoleAssignment[] | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<any>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [llamaOk, setLlamaOk] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [integrating, setIntegrating] = useState<string | null>(null);
  const [integrateMsg, setIntegrateMsg] = useState<string | null>(null);
  const [customPath, setCustomPath] = useState("");

  const refresh = () =>
    Promise.all([
      getJson<{ models: ModelInfo[]; engines: EngineStatus[] }>("/api/models")
        .then((d) => {
          setModels(d.models);
          setEngines(d.engines);
        })
        .catch(() => undefined),
      getJson<{ assignments: RoleAssignment[] }>("/api/routing/assignments")
        .then((d) => setAssignments(d.assignments))
        .catch(() => setAssignments(null)),
    ]);

  const discover = () => {
    setScanning(true);
    return getJson<{ candidates: Candidate[]; llamacpp_available: boolean }>("/api/models/discover")
      .then((d) => {
        setCandidates(d.candidates);
        setLlamaOk(d.llamacpp_available);
      })
      .catch(() => undefined)
      .finally(() => setScanning(false));
  };

  useEffect(() => {
    refresh();
    discover();
    const timer = setInterval(refresh, 5000);
    const timer2 = setInterval(discover, 15000);
    return () => {
      clearInterval(timer);
      clearInterval(timer2);
    };
  }, []);

  const probe = async (id: string) => {
    setProbing(id);
    setProbeResult(null);
    try {
      setProbeResult(await postJson<any>("/api/models/probe", { model_id: id }));
    } finally {
      setProbing(null);
    }
  };

  const integrate = async (path: string) => {
    setIntegrating(path);
    setIntegrateMsg(null);
    try {
      const result = await postJson<any>("/api/models/integrate", { path });
      setIntegrateMsg(
        `Integrated ${result.model.id} — routed for ${result.routed_roles.join(", ")}` +
          (result.engine ? `; engine ${result.engine.status}` : ""),
      );
      setCustomPath("");
      refresh();
      discover();
    } catch (e) {
      setIntegrateMsg(String(e));
    } finally {
      setIntegrating(null);
    }
  };

  const sources = [...new Set(candidates.map((c) => c.source))];

  return (
    <Page
      title="Models"
      desc="Everything on this computer, everything added, and which model handles each job — live."
      actions={
        <button onClick={discover} disabled={scanning}>
          {scanning ? "Scanning disk…" : "↺ Rescan disk"}
        </button>
      }
    >
      <Section>
        On this computer · {candidates.length} found
        {sources.length > 0 && <span style={{ textTransform: "none", letterSpacing: 0 }}> — {sources.join(" · ")}</span>}
      </Section>
      {!llamaOk && (
        <Card style={{ marginBottom: 12 }}>
          <span className="muted">
            <b>llama-server</b> is not on the server's PATH — GGUF models will register and route but
            cannot be served until it is installed.
          </span>
        </Card>
      )}
      {candidates.length === 0 ? (
        <Card>
          <span className="muted">
            No model files found yet. Downloads, Desktop, Documents, the models folder, Ollama,
            LM Studio, GPT4All and the Hugging Face cache are scanned — drop a <span className="mono">.gguf</span> anywhere
            in those and it appears here.
          </span>
        </Card>
      ) : (
        <Card pad={false} style={{ marginBottom: 12 }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>File</th><th>Kind</th><th>Where</th><th className="num">Size</th><th>Path</th><th></th></tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <tr key={c.path}>
                    <td style={{ fontWeight: 600, color: "var(--ink)" }}>{c.name}</td>
                    <td><span className="chip">{c.kind}</span></td>
                    <td><span className="chip hot">{c.source}</span></td>
                    <td className="num dim">{c.size_gb} GB</td>
                    <td className="mono muted path-cell" title={c.path}>{c.path}</td>
                    <td style={{ textAlign: "right" }}>
                      {c.registered ? (
                        <Pill tone="ok" dot={false}>added ✓</Pill>
                      ) : (
                        <button className="primary" onClick={() => integrate(c.path)} disabled={integrating !== null}>
                          {integrating === c.path ? "Integrating…" : "Integrate"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <div style={{ display: "flex", gap: 8, marginBottom: integrateMsg ? 8 : 0 }}>
        <input
          className="ws-input"
          value={customPath}
          onChange={(e) => setCustomPath(e.target.value)}
          placeholder="…or paste any path to a .gguf file / model folder"
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={() => integrate(customPath)} disabled={!customPath.trim() || integrating !== null}>
          Integrate
        </button>
      </div>
      {integrateMsg && (
        <div style={{ marginTop: 6 }}>
          <Pill tone={integrateMsg.startsWith("Integrated") ? "ok" : "bad"} dot={false}>{integrateMsg}</Pill>
        </div>
      )}

      <Section>Added models · {models.length}</Section>
      <Card pad={false}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Origin</th>
                <th className="num">Params</th>
                <th>Quant</th>
                <th>Roles</th>
                <th>Evidence</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td className="mono" style={{ fontWeight: 550, color: "var(--ink)" }} title={m.path ?? undefined}>{m.id}</td>
                  <td><span className={`chip${m.local ? " hot" : ""}`}>{m.local ? "added here" : "bundled"}</span></td>
                  <td className="num">{m.params_b}B</td>
                  <td className="dim">{m.quant ?? "—"}</td>
                  <td>
                    {m.roles.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      m.roles.map((r) => <span className="chip" key={r}>{r}</span>)
                    )}
                  </td>
                  <td>
                    {m.probes_total ? (
                      <span className={`probe-mini${(m.probes_passed ?? 0) === m.probes_total ? " good" : ""}`}>
                        {m.probes_passed}/{m.probes_total} probes
                      </span>
                    ) : (
                      <span className="probe-mini none">not probed</span>
                    )}
                  </td>
                  <td><Pill tone={m.available ? "ok" : "neutral"}>{m.available ? "available" : "missing"}</Pill></td>
                  <td style={{ textAlign: "right" }}>
                    <button onClick={() => probe(m.id)} disabled={probing === m.id}>
                      {probing === m.id ? "probing…" : "Probe"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {assignments && assignments.length > 0 && (
        <>
          <Section>Who does what right now</Section>
          <Card pad={false}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Job</th><th>Assigned model</th><th>How chosen</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {assignments.map((a) => (
                    <tr key={a.role}>
                      <td>
                        <span style={{ fontWeight: 600, color: "var(--ink)" }}>{a.role}</span>
                        {ROLE_HINT[a.role] && <div className="muted">{ROLE_HINT[a.role]}</div>}
                      </td>
                      <td className="mono">{a.model_id ?? <span className="muted">nothing can serve this</span>}</td>
                      <td>
                        <Pill
                          tone={a.source === "policy" ? "ok" : a.source === "fallback" ? "accent" : "neutral"}
                          dot={false}
                        >
                          {a.source === "policy" ? "configured" : a.source === "fallback" ? "best available" : "unassigned"}
                        </Pill>
                      </td>
                      <td className="assign-why">
                        {a.reason}
                        {a.probes_total ? ` · ${a.probes_passed}/${a.probes_total} probes passed` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <p className="muted" style={{ marginTop: 8 }}>
            Assignments re-resolve on every request: add a stronger model and the work moves to it
            automatically; take a model away and the best remaining one takes over.
          </p>
        </>
      )}

      <Section>Engines</Section>
      <div className="grid">
        {engines.map((e) => (
          <Card key={`${e.engine_id}-${e.replica}`}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 650, color: "var(--ink)" }}>{e.engine_id}</span>
              <Pill tone={statusTone(e.status)}>{e.status}</Pill>
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {e.kind} · {e.port ? <span className="mono">:{e.port}</span> : "in-process"}
            </div>
            {e.error && <div className="muted" style={{ color: "var(--bad)", marginTop: 4 }}>{e.error}</div>}
          </Card>
        ))}
      </div>

      <Section>How to get a model in — the complete guide</Section>
      <Card>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 18, fontSize: 13 }}>
          <div>
            <div style={{ fontWeight: 650, marginBottom: 4, color: "var(--ink)" }}>1 · Get a model file</div>
            <div className="dim">
              Any <b>GGUF</b> file works (CPU-friendly, from Hugging Face — e.g. search
              "Qwen2.5 Instruct GGUF", download the <span className="mono">Q4_K_M</span> file), or a full
              Hugging Face model folder (needs a GPU + vLLM). If you use <b>Ollama</b>, <b>LM Studio</b> or
              <b> GPT4All</b>, models you already pulled are found automatically — nothing to move.
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 650, marginBottom: 4, color: "var(--ink)" }}>2 · Drop it anywhere we scan</div>
            <div className="dim">
              <span className="mono">Downloads</span>, <span className="mono">Desktop</span>, <span className="mono">Documents</span>,
              <span className="mono"> models\weights\</span> in the project, the configured models dir, or any
              app store above. It appears in "On this computer" within seconds — or paste any other path
              into the field.
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 650, marginBottom: 4, color: "var(--ink)" }}>3 · Click Integrate</div>
            <div className="dim">
              One click: the model is inspected, registered (anything ≥120B parameters is refused),
              <b> roles are assigned automatically</b> from its capabilities — chat models take
              planner/executor/reviewer/router/utility, embedding models take embed, rerankers
              rerank, vision models add vision — then it is served immediately and re-served on
              every restart.
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 650, marginBottom: 4, color: "var(--ink)" }}>4 · It proves itself</div>
            <div className="dim">
              Probes run automatically once the engine is healthy (JSON, tool-calls, extraction,
              coding). "Who does what" above updates from that evidence: with several models the
              strongest takes each job; with one, everything routes to it. Then just use
              the <b>Workbench</b> — your goals run on it.
            </div>
          </div>
        </div>
      </Card>

      {probeResult && (
        <>
          <Section>Probe · {probeResult.model}</Section>
          <Card pad={false}>
            <div className="table-wrap">
              <table>
                <tbody>
                  {(probeResult.outcomes ?? []).map((o: any, i: number) => (
                    <tr key={i}>
                      <td style={{ width: 80 }}>
                        <Pill tone={o.passed ? "ok" : "bad"}>{o.passed ? "pass" : "fail"}</Pill>
                      </td>
                      <td style={{ width: 160, fontWeight: 550 }}>{o.probe}</td>
                      <td className="muted">{o.score != null && `score ${o.score} · `}{o.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </Page>
  );
}
