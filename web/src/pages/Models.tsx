import React, { useEffect, useState } from "react";
import { getJson, postJson, type EngineStatus, type ModelInfo } from "../api.js";
import { Card, Page, Pill, Section, statusTone } from "../components.js";

interface Candidate {
  path: string;
  name: string;
  kind: string;
  source: string;
  size_gb: number;
  registered: boolean;
}

export function ModelsPage(): React.ReactElement {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [engines, setEngines] = useState<EngineStatus[]>([]);
  const [probing, setProbing] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<any>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [llamaOk, setLlamaOk] = useState(true);
  const [integrating, setIntegrating] = useState<string | null>(null);
  const [integrateMsg, setIntegrateMsg] = useState<string | null>(null);
  const [customPath, setCustomPath] = useState("");

  const refresh = () =>
    getJson<{ models: ModelInfo[]; engines: EngineStatus[] }>("/api/models")
      .then((d) => {
        setModels(d.models);
        setEngines(d.engines);
      })
      .catch(() => undefined);

  const discover = () =>
    getJson<{ candidates: Candidate[]; llamacpp_available: boolean }>("/api/models/discover")
      .then((d) => {
        setCandidates(d.candidates);
        setLlamaOk(d.llamacpp_available);
      })
      .catch(() => undefined);

  useEffect(() => {
    refresh();
    discover();
    const timer = setInterval(refresh, 4000);
    const timer2 = setInterval(discover, 10000);
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

  const pending = candidates.filter((c) => !c.registered);

  return (
    <Page
      title="Models"
      desc="Serving engines and the local model registry. Drop weights in, integrate with one click."
    >
      <Section>Integrate a downloaded model</Section>
      {!llamaOk && (
        <Card>
          <span className="muted">
            <b>llama-server</b> is not on the server's PATH — GGUF models will register and route but
            cannot be served until it is installed.
          </span>
        </Card>
      )}
      {pending.length > 0 && (
        <Card pad={false} style={{ marginBottom: 12 }}>
          <div className="table-wrap">
            <table>
              <tbody>
                {pending.map((c) => (
                  <tr key={c.path}>
                    <td style={{ fontWeight: 600 }}>{c.name}</td>
                    <td><span className="chip">{c.kind}</span> <span className="chip">{c.source}</span></td>
                    <td className="num dim">{c.size_gb} GB</td>
                    <td className="mono muted" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.path}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="primary" onClick={() => integrate(c.path)} disabled={integrating !== null}>
                        {integrating === c.path ? "Integrating…" : "Integrate"}
                      </button>
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
          value={customPath}
          onChange={(e) => setCustomPath(e.target.value)}
          placeholder="…or paste a path to a .gguf file / model folder"
          style={{
            flex: 1, padding: "7px 12px", border: "1px solid var(--border)", borderRadius: 8,
            fontFamily: "var(--mono)", fontSize: 12.5, background: "var(--surface)",
          }}
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
      <Section>Engines</Section>
      <div className="grid">
        {engines.map((e) => (
          <Card key={`${e.engine_id}-${e.replica}`}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 650 }}>{e.engine_id}</span>
              <Pill tone={statusTone(e.status)}>{e.status}</Pill>
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {e.kind} · {e.port ? <span className="mono">:{e.port}</span> : "in-process"}
            </div>
            {e.error && <div className="muted" style={{ color: "var(--bad)", marginTop: 4 }}>{e.error}</div>}
          </Card>
        ))}
      </div>

      <Section>Registry · {models.length} models</Section>
      <Card pad={false}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Engine</th>
                <th className="num">Params</th>
                <th>Quant</th>
                <th>Router roles</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td className="mono" style={{ fontWeight: 550 }}>{m.id}</td>
                  <td className="dim">{m.engine}</td>
                  <td className="num">{m.params_b}B</td>
                  <td className="dim">{m.quant ?? "—"}</td>
                  <td>
                    {m.roles.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      m.roles.map((r) => <span className="chip" key={r}>{r}</span>)
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
