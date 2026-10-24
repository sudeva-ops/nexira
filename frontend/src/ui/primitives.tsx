import { Icon, type IconName } from "@blueprintjs/core";
import type { ReactNode } from "react";

import type { Severity, SourceRef } from "../api/intel";
import { sourceLabel } from "./format";

const SEV_CLASS: Record<Severity, string> = {
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "med",
  LOW: "low",
};

export function Sev({ severity, label }: { severity: Severity; label?: string }) {
  return <span className={`nx-sev ${SEV_CLASS[severity]}`}>{label ?? severity}</span>;
}

export function SourceChip({ source }: { source: Pick<SourceRef, "name" | "simulated"> }) {
  return <span className="nx-src">{sourceLabel(source)}</span>;
}

export function Card({
  icon,
  title,
  sub,
  actions,
  children,
  className,
}: {
  icon?: IconName;
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`nx-card ${className ?? ""}`}>
      <header className="nx-card-hd">
        {icon && <Icon icon={icon} size={13} />}
        <h3>{title}</h3>
        {sub && <span className="nx-card-sub">{sub}</span>}
        <span className="nx-grow" />
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Kpi({
  icon,
  label,
  value,
  detail,
  alert,
}: {
  icon: IconName;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  alert?: boolean;
}) {
  return (
    <div className={`nx-card nx-kpi${alert ? " alert" : ""}`}>
      <div className="l">
        <Icon icon={icon} size={11} />
        {label}
      </div>
      <div className="v">{value}</div>
      {detail && <div className="d">{detail}</div>}
    </div>
  );
}

export function ConfidenceBar({ value, width = 60 }: { value: number | null; width?: number }) {
  if (value === null) return <span className="nx-dim">—</span>;
  return (
    <span className="nx-confidence">
      <span className="nx-bar" style={{ width }}>
        <i style={{ width: `${value}%` }} className={value < 85 ? "warn" : undefined} />
      </span>
      <span className="nx-mono">{value}%</span>
    </span>
  );
}
