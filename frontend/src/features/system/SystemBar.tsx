// Wskaźnik stanu wykonania (prawy górny róg, każdy ekran) i 4 ikony paneli systemowych (prawy dół). Logika chipów z AppShell 1.41:
// „Tryb PAPER / AUTO_DEMO / AUTO_LIVE / SIGNALS” albo „STOP nowych wejść”; AUTO_LIVE ostrzegawczy, STOP czerwony. STOP jednym kliknięciem.
import { BRAND } from "../../brand";
import { useStore } from "../../store";
import { cls } from "../../util";
import type { SysPanel } from "./SystemDrawer";

export function ExecStatus({ onOpen }: { onOpen(p: SysPanel): void }) {
  const { s } = useStore();
  const mode = s.mode || {};
  return (
    <div className="sys-exec" aria-live="polite">
      <button type="button" className={cls("sys-chip", mode.kill_switch ? "bad" : mode.mode === "AUTO_LIVE" ? "warn" : "ok")} data-testid="chip-exec"
        title="Tryb wykonania z backendu; STOP zatrzymuje tylko nowe wejścia" onClick={() => onOpen("mode")}>
        <i className="dot" />{mode.kill_switch ? "STOP nowych wejść" : `Tryb ${mode.mode_label ?? mode.mode ?? "—"}`}</button>
      <button type="button" className={cls("sys-chip mode", mode.mode === "AUTO_LIVE" ? "bad" : mode.mode === "SIGNALS" ? "muted" : "warn")} data-testid="chip-mode"
        title="Tryb wykonania – kliknij, aby zmienić" onClick={() => onOpen("mode")}>WYKONANIE <b>{mode.mode_label ?? mode.mode ?? "…"}</b></button>
      {s.synthetic && <span className="sys-chip syn" data-testid="badge-synthetic">SYNTETYCZNE</span>}
    </div>);
}

const ICONS: [SysPanel, string, string][] = [
  ["settings", "Ustawienia (w tym MT5)", "M10 7.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2M10 2.5v2.2M10 15.3v2.2M2.5 10h2.2M15.3 10h2.2M4.7 4.7l1.6 1.6M13.7 13.7l1.6 1.6M4.7 15.3l1.6-1.6M13.7 6.3l1.6-1.6"],
  ["mode", "Tryb pracy", "M3 6h9m4 0h1M3 14h3m4 0h7M14 4v4M8 12v4"],
  ["diagnostics", "Diagnostyka", "M2 10h4l2-5 4 10 2-5h4"],
  ["training", `Centrum Treningowe ${BRAND}`, "M2 7.5 10 4l8 3.5-8 3.5zM5.5 9v4.2c1.4 1.3 3 1.9 4.5 1.9s3.1-.6 4.5-1.9V9M18 7.5v5"],
];

export function SystemIcons({ onOpen }: { onOpen(p: SysPanel): void }) {
  const { s } = useStore();
  return (
    <nav className="sys-icons" aria-label="Panele systemowe">
      {ICONS.map(([k, label, d]) => (
        <button key={k} type="button" className="sys-icon" aria-label={label} data-label={label} data-testid={"open-" + k} onClick={() => onOpen(k)}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d={d} /></svg></button>))}
      <button type="button" className={cls("sys-icon stop", s.mode?.kill_switch && "on")} data-testid="stop-button" aria-label="STOP" data-label="STOP – nowe wejścia / pozycje bota / aplikacja"
        onClick={() => onOpen("stop")}>{s.mode?.kill_switch ? "STOP ●" : "STOP"}</button>
    </nav>);
}
