import React from "react";

export type Tone = "ok" | "warn" | "bad" | "accent" | "neutral";

export function Pill({ tone, children, dot = true }: { tone: Tone; children: React.ReactNode; dot?: boolean }) {
  return (
    <span className={`pill ${tone}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

export function statusTone(status: string): Tone {
  if (status === "done" || status === "healthy" || status === "verified") return "ok";
  if (status.includes("fail") || status === "TAMPERED" || status === "unhealthy") return "bad";
  if (status === "done_with_gaps" || status === "running" || status === "starting") return "warn";
  return "neutral";
}

export function Page({
  title,
  desc,
  actions,
  children,
}: {
  title: string;
  desc?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          {desc && <p className="page-desc">{desc}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Section({ children }: { children: React.ReactNode }) {
  return <div className="section">{children}</div>;
}

export function Card({ children, pad = true, style }: { children: React.ReactNode; pad?: boolean; style?: React.CSSProperties }) {
  return (
    <div className="card" style={style}>
      {pad ? <div className="card-pad">{children}</div> : children}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <Card>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </Card>
  );
}

export function Empty({ glyph, title, hint }: { glyph: string; title: string; hint?: React.ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-glyph">{glyph}</div>
      <div className="empty-title">{title}</div>
      {hint && <div style={{ fontSize: 12.5 }}>{hint}</div>}
    </div>
  );
}

export function timeAgo(iso: string): string {
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
