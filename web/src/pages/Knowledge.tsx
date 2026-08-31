import React, { useEffect, useState } from "react";
import { getJson } from "../api.js";
import { Card, Empty, Page, Pill } from "../components.js";

interface Collection {
  name: string;
  documents: number;
  chunks: number;
  pending: number;
  errors: number;
}

export function KnowledgePage(): React.ReactElement {
  const [data, setData] = useState<{ collections: Collection[]; note?: string } | null>(null);

  useEffect(() => {
    const refresh = () =>
      getJson<{ collections: Collection[]; note?: string }>("/api/knowledge")
        .then(setData)
        .catch(() => setData({ collections: [] }));
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  if (!data) return <Page title="Knowledge"><div className="muted">Loading…</div></Page>;
  return (
    <Page
      title="Knowledge"
      desc="Indexed document collections: hybrid lexical + dense retrieval with page-level citations."
      actions={<span className="cmd">yantra index add &lt;path&gt;</span>}
    >
      {data.note && <Card><span className="muted">{data.note}</span></Card>}
      {data.collections.length === 0 && !data.note ? (
        <Empty
          glyph="▤"
          title="No collections indexed"
          hint={<>Index a folder from a terminal: <code>yantra index add ./docs --collection plant</code></>}
        />
      ) : (
        <div className="grid">
          {data.collections.map((c) => (
            <Card key={c.name}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 650 }}>{c.name}</span>
                {c.errors > 0 ? (
                  <Pill tone="bad">{c.errors} errors</Pill>
                ) : c.pending > 0 ? (
                  <Pill tone="warn">{c.pending} pending</Pill>
                ) : (
                  <Pill tone="ok">indexed</Pill>
                )}
              </div>
              <div className="stat-value">{c.documents.toLocaleString()}</div>
              <div className="stat-sub">documents · {c.chunks.toLocaleString()} chunks</div>
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}
