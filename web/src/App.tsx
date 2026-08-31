import React, { useEffect, useState } from "react";
import { getJson } from "./api.js";
import { Pill } from "./components.js";
import { RunsPage } from "./pages/Runs.js";
import { SealPage } from "./pages/Seal.js";
import { ModelsPage } from "./pages/Models.js";
import { KnowledgePage } from "./pages/Knowledge.js";
import { EvalsPage } from "./pages/Evals.js";
import { AuditPage } from "./pages/Audit.js";

const PAGES = {
  runs: { label: "Runs", ico: "▶", component: RunsPage },
  seal: { label: "Seal Monitor", ico: "◈", component: SealPage },
  models: { label: "Models", ico: "◆", component: ModelsPage },
  knowledge: { label: "Knowledge", ico: "▤", component: KnowledgePage },
  evals: { label: "Evaluations", ico: "✓", component: EvalsPage },
  audit: { label: "Audit", ico: "≡", component: AuditPage },
} as const;

type PageKey = keyof typeof PAGES;

interface Health {
  status: string;
  version: string;
  profile: string;
  sealed: boolean;
}

export function App(): React.ReactElement {
  const [page, setPage] = useState<PageKey>(() => {
    const hash = location.hash.replace("#", "") as PageKey;
    return hash in PAGES ? hash : "runs";
  });
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const onHash = () => {
      const hash = location.hash.replace("#", "") as PageKey;
      if (hash in PAGES) setPage(hash);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const refresh = () => getJson<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, []);

  const Current = PAGES[page].component;
  return (
    <div className="app">
      <div className="sidebar">
        <div className="brand">
          <div className="brand-mark">✦</div>
          <div>
            <div className="brand-name">YANTRA</div>
            <div className="brand-sub">Sovereign AI Workbench</div>
          </div>
        </div>
        <nav className="nav">
          {(Object.keys(PAGES) as PageKey[]).map((key) => (
            <a key={key} className={key === page ? "active" : ""} href={`#${key}`} onClick={() => setPage(key)}>
              <span className="nav-ico">{PAGES[key].ico}</span>
              {PAGES[key].label}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div>
            {health === null ? (
              <Pill tone="bad">server offline</Pill>
            ) : health.sealed ? (
              <Pill tone="ok">Sealed · zero egress</Pill>
            ) : (
              <Pill tone="warn">Unsealed · dev mode</Pill>
            )}
          </div>
          <div>
            profile <span className="mono">{health?.profile ?? "—"}</span> · v{health?.version ?? "—"}
          </div>
        </div>
      </div>
      <div className="main">
        <Current />
      </div>
    </div>
  );
}
