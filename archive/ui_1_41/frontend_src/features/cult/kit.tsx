// UI kit of the CULT panels: gold-framed monitors, gauges, bars, toggles and the data-kind tag. Pure presentation - values come in
// from the data layer; a missing value is rendered as "—" with its reason, never as a made-up number.
import type { CSSProperties, ReactNode } from "react";
import { cls } from "../../util";
import { KIND_LABEL, type Kind } from "./data";

const P: Record<string, string> = {
  home: "M3 11 12 4l9 7v9h-6v-6H9v6H3z", bolt: "M13 2 4 14h7l-1 8 9-12h-7z", bars: "M4 20V10m6 10V4m6 16v-7m6 7V8", snow: "M12 2v20M3 7l18 10M21 7 3 17",
  wind: "M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h8", fire: "M12 22c4 0 7-3 7-7 0-5-5-7-5-12-3 2-4 5-4 7-1-1-2-2-2-4-2 2-3 5-3 7 0 5 3 9 7 9z",
  sliders: "M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12m4 0h0M14 4v4M8 10v4M16 16v4", flask: "M9 2h6M10 2v7L4 20h16L14 9V2", db: "M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0zM4 6c0 2 16 2 16 0M4 12c0 2 16 2 16 0",
  gear: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm0-6v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2", bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 20h4",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6", brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V4a3 3 0 0 0-3 0zm6 0a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1",
  shield: "M12 2 4 5v6c0 5 3 9 8 11 5-2 8-6 8-11V5z", send: "M3 11 21 3l-8 18-2-8z", robot: "M5 9h14v10H5zM9 13h.01M15 13h.01M12 5v4M9 19v2m6-2v2",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01", log: "M5 3h10l4 4v14H5zM8 11h8M8 15h8M8 7h4", chart: "M3 3v18h18M7 14l4-4 3 3 5-6",
  check: "M5 12l5 5L20 7", x: "M6 6l12 12M18 6 6 18", alert: "M12 3 2 20h20zM12 10v4m0 3h.01", clock: "M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  coins: "M7 9a5 2 0 1 0 10 0 5 2 0 1 0-10 0zm0 0v6c0 1 2 2 5 2s5-1 5-2V9M3 15c0 1 2 2 4 2", signal: "M2 12h3l3-7 4 14 3-7h7", target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  dna: "M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12s10 6 10 6M8 7h8M8 17h8", grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
};

export function Icon({ n, size = 18, className }: { n: keyof typeof P | string; size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={cls("cu-ico", className)} aria-hidden="true" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round"><path d={P[n] || P.grid} /></svg>);
}

export function Tag({ kind, title }: { kind: Kind; title?: string }) {
  return <span className={cls("cu-tag", `k-${kind.toLowerCase()}`)} title={title ?? KIND_LABEL[kind]} data-kind={kind}>{KIND_LABEL[kind]}</span>;
}

/** Gold-framed monitor. `accent` colours the icon and the glow of the frame. */
export function Monitor({ title, icon, num, accent, id, testid, right, children, className, style }: {
  title: string; icon?: string; num?: string; accent?: string; id?: string; testid?: string; right?: ReactNode; children: ReactNode; className?: string; style?: CSSProperties;
}) {
  return (
    <section id={id} className={cls("cu-mon", className)} style={{ ...(accent ? { "--acc": accent } : {}), ...style } as CSSProperties} data-testid={testid}
      aria-label={title}>
      <header className="cu-mon-h">
        {icon && <Icon n={icon} size={17} />}<h2>{num && <span className="cu-num">{num}</span>}{title}</h2>
        {right && <span className="cu-mon-r">{right}</span>}
      </header>
      <div className="cu-mon-b">{children}</div>
    </section>);
}

/** Circular gauge; value null -> "—" (no fake ring). */
export function Ring({ value, max = 100, label, text, color, size = 120, testid }: {
  value: number | null; max?: number; label: string; text?: string; color?: string; size?: number; testid?: string;
}) {
  const r = 44, c = 2 * Math.PI * r;
  const f = value == null || !Number.isFinite(value) ? 0 : Math.max(0, Math.min(1, value / max));
  return (
    <div className="cu-ring" style={{ width: size, height: size, "--rc": color ?? "var(--cu-green)" } as CSSProperties} data-testid={testid}
      data-value={value ?? ""} role="img" aria-label={`${label}: ${text ?? (value == null ? "brak danych" : value)}`}>
      <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r={r} className="cu-ring-bg" />
        <circle cx="50" cy="50" r={r} className="cu-ring-fg" strokeDasharray={`${c * f} ${c}`} transform="rotate(-90 50 50)" /></svg>
      <div className="cu-ring-t"><small>{label}</small><b>{text ?? (value == null ? "—" : String(value))}</b></div>
    </div>);
}

export function Bar({ label, value, text, color, title }: { label: ReactNode; value: number | null; text: ReactNode; color?: string; title?: string }) {
  return (
    <div className="cu-bar" title={title}>
      <span className="cu-bar-l">{label}</span>
      <span className="cu-bar-t"><i style={{ width: `${value == null ? 0 : Math.max(2, Math.min(100, value * 100))}%`, background: color } as CSSProperties} /></span>
      <span className="cu-bar-v">{text}</span>
    </div>);
}

export function Stat({ icon, label, value, sub, kind, testid, tone }: {
  icon: string; label: string; value: ReactNode; sub?: ReactNode; kind?: Kind; testid?: string; tone?: "ok" | "bad" | "warn" | "muted";
}) {
  return (
    <div className={cls("cu-stat", tone && `t-${tone}`)} data-testid={testid}>
      <Icon n={icon} size={26} />
      <div><small>{label}</small><b>{value}</b>{sub && <em>{sub}</em>}{kind && <Tag kind={kind} />}</div>
    </div>);
}

export function Toggle({ on, onChange, label, disabled, testid, title }: { on: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean; testid?: string; title?: string }) {
  return (
    <label className={cls("cu-tog", disabled && "dis")} title={title}>
      <span>{label}</span>
      <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={() => onChange(!on)} data-testid={testid} className={cls(on && "on")}><i /></button>
    </label>);
}

export function NA({ children }: { children: ReactNode }) {
  return <p className="cu-na">{children}</p>;
}

export function Badge({ tone, children, title }: { tone: "ok" | "bad" | "warn" | "muted" | "info"; children: ReactNode; title?: string }) {
  return <span className={cls("cu-badge", `b-${tone}`)} title={title}>{children}</span>;
}

/** Shared bottom status bar of a tower (and the stat bar of the main menu). */
export function StatusBar({ children, centre, testid }: { children: ReactNode; centre?: ReactNode; testid?: string }) {
  return <footer className="cu-sbar" data-testid={testid}>{children}{centre && <div className="cu-sbar-c" aria-hidden="true">{centre}</div>}</footer>;
}
