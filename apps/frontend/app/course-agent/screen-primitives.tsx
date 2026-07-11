import type React from "react";

export function StatusBadge({ tone, children }: { tone: string; children: React.ReactNode }) {
  return <span className="status-badge" data-tone={tone}>{children}</span>;
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><strong>{title}</strong><p>{detail}</p></div>;
}

export function PageToolbar({ children }: { children: React.ReactNode }) {
  return <div className="page-toolbar">{children}</div>;
}

export function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}
