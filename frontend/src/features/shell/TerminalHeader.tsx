// Global header of the new panels: branding, environment, MT5 status with a details panel, data freshness, instrument,
// execution mode, notifications, diagnostics and settings. Read-only: nothing here changes the state of the bot.
import { useEffect, useRef, useState } from "react";
import { href } from "../../router";
import { useUi } from "../../ui";
import { cls, fmtNum, fmtTime } from "../../util";
import { fmtUnknown } from "./StateView";
import type { TerminalContext } from "./useTerminalContext";

type Pop = null | "mt5" | "alerts";

const ENV_TONE: Record<string, string> = { LIVE: "bad", DEMO: "info", SYNTHETIC: "warn", HISTORY: "info", UNKNOWN: "muted" };
const FRESH_TONE: Record<string, string> = { FRESH: "ok", DEGRADED: "warn", STALE: "warn", DISCONNECTED: "bad", UNKNOWN: "muted" };

function usePopover(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    const c = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (ref.current && !ref.current.contains(t) && !t.closest?.("[data-pop-toggle]")) close();
    };
    window.addEventListener("keydown", k);
    window.addEventListener("mousedown", c);
    return () => { window.removeEventListener("keydown", k); window.removeEventListener("mousedown", c); };
  }, [open, close]);
  return ref;
}

function Mt5Details({ ctx, quoteAge, onClose }: { ctx: TerminalContext; quoteAge: number | null; onClose: () => void }) {
  const ref = usePopover(true, onClose);
  const c = ctx.connection || {};
  const clock = c.clock || {};
  const lastErr = (c.errors || []).slice(-1)[0];
  const row = (k: string, v: string) => <><dt>{k}</dt><dd>{v}</dd></>;
  return (
    <div className="t-pop" ref={ref} role="dialog" aria-label="Szczegóły połączenia MT5" data-testid="t-mt5-details">
      <dl className="t-kv">
        {row("Stan", fmtUnknown(c.state, undefined, "UNKNOWN"))}
        {row("Przyczyna", fmtUnknown(c.reason))}
        {row("Ostatni heartbeat", fmtUnknown(c.last_heartbeat, (x) => fmtTime(x, true)))}
        {row("Połączony od", fmtUnknown(c.connected_since, (x) => fmtTime(x, true)))}
        {row("Epoka sesji", fmtUnknown(c.session_epoch))}
        {row("Próby połączenia", fmtUnknown(c.attempts))}
        {row("Wiek ostatniego ticka", fmtUnknown(quoteAge, (x) => `${fmtNum(x, 1)} s`))}
        {row("Czas serwera", clock.status === "VERIFIED" ? `UTC${clock.offset_hours >= 0 ? "+" : ""}${clock.offset_hours} (zweryfikowany)` : fmtUnknown(clock.status, undefined, "UNKNOWN"))}
        {row("Rachunek", fmtUnknown(c.account_key))}
        {row("Ostatni błąd", lastErr ? (typeof lastErr === "string" ? lastErr : JSON.stringify(lastErr)) : "brak")}
      </dl>
      <p className="t-note">Opóźnienie zapytań do terminala nie jest mierzone osobno – pokazany jest wiek ostatniego ticka.</p>
    </div>);
}

function AlertsList({ alerts, onClose }: { alerts: any[]; onClose: () => void }) {
  const ref = usePopover(true, onClose);
  return (
    <div className="t-pop t-pop-wide" ref={ref} role="dialog" aria-label="Powiadomienia" data-testid="t-alerts-list">
      {alerts.length === 0 ? <p className="t-note">Brak ostrzeżeń i błędów w bieżącej sesji.</p> : (
        <ul className="t-alerts">
          {alerts.slice(0, 20).map((a, i) => (
            <li key={a.id ?? `${a.ts}-${i}`} className={a.level === "ERROR" ? "bad" : "warn"}>
              <span className="t-time">{fmtTime(a.ts, true)}</span> <b>{a.level}</b> <span className="t-dim">{a.category ?? ""}</span> {a.message}
            </li>))}
        </ul>)}
      <a className="t-link" href={href("diagnostyka")}>Diagnostyka systemu →</a>
    </div>);
}

export default function TerminalHeader({ ctx, quoteAge }: { ctx: TerminalContext; quoteAge: number | null }) {
  const ui = useUi();
  const [pop, setPop] = useState<Pop>(null);
  const toggle = (p: Pop) => setPop(pop === p ? null : p);
  const close = () => setPop(null);
  return (
    <header className="t-header" data-testid="t-header">
      <a className="t-brand" href={href("trading-intelligence")} aria-label="Pepe Market Wizard – Trading Intelligence">
        <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true"><rect width="32" height="32" rx="7" fill="none" stroke="currentColor" />
          <path d="M8 22V11m5 11V7m5 15v-8m5 8V13" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /></svg>
        <span>Pepe Market <em>Wizard</em></span>
      </a>
      <span className={cls("t-badge", `t-badge-${ENV_TONE[ctx.env]}`)} title={ctx.envDetail} data-testid="t-env" data-env={ctx.env}>
        Środowisko: <b>{ctx.env}</b></span>
      <div className="t-pop-anchor">
        <button className={cls("t-chip", ctx.mt5 === "CONNECTED" ? "ok" : ctx.mt5 === "UNKNOWN" ? "muted" : "bad")} data-pop-toggle aria-expanded={pop === "mt5"}
          aria-haspopup="dialog" onClick={() => toggle("mt5")} data-testid="t-mt5" data-mt5={ctx.mt5}>
          <i className="t-dot" aria-hidden="true" />MT5 <b>{ctx.mt5}</b>{ctx.mt5State && ctx.mt5State !== ctx.mt5 ? <span className="t-dim"> ({ctx.mt5State})</span> : null}
        </button>
        {pop === "mt5" && <Mt5Details ctx={ctx} quoteAge={quoteAge} onClose={close} />}
      </div>
      <span className={cls("t-chip", FRESH_TONE[ctx.freshness])} title={ctx.freshnessDetail} data-testid="t-fresh" data-fresh={ctx.freshness}>
        <i className="t-dot" aria-hidden="true" />Dane <b>{ctx.freshness}</b></span>
      <span className="t-chip muted" data-testid="t-instrument"
        title="Instrument aktywny w bocie. Przełączanie zmienia pracę bota (reset trybu) – w nowych panelach dostępne od etapu 2, po decyzji D1.">
        Instrument <b>{fmtUnknown(ctx.instrument, undefined, "UNKNOWN")}</b>{ctx.brokerSymbol ? <span className="t-dim"> · {ctx.brokerSymbol}</span> : null}</span>
      <span className={cls("t-chip", ctx.mode === "AUTO_LIVE" ? "bad" : ctx.mode === "SIGNALS" ? "muted" : "warn")} data-testid="t-mode"
        title="Tryb wykonania bota (zmiana w obecnym panelu: przycisk „Wykonanie”)">Wykonanie <b>{fmtUnknown(ctx.modeLabel ?? ctx.mode, undefined, "UNKNOWN")}</b></span>
      <span className={cls("t-chip", ctx.executionLock === "LOCKED" ? "ok" : ctx.executionLock ? "bad" : "muted")} data-testid="t-lock"
        title="Execution Lock: LOCKED = żadna ścieżka nie wysyła zleceń do terminala">Lock <b>{fmtUnknown(ctx.executionLock, undefined, "UNKNOWN")}</b></span>
      {ctx.backend !== "OPEN" && <span className="t-chip bad" data-testid="t-backend">Backend <b>{ctx.backend}</b></span>}
      <span className="t-spacer" />
      <div className="t-pop-anchor">
        <button className={cls("t-btn", ctx.alerts.length > 0 && "t-btn-warn")} data-pop-toggle aria-expanded={pop === "alerts"} aria-haspopup="dialog"
          onClick={() => toggle("alerts")} data-testid="t-alerts" aria-label={`Powiadomienia: ${ctx.alerts.length}`}>
          Powiadomienia <b>{ctx.alerts.length}</b></button>
        {pop === "alerts" && <AlertsList alerts={ctx.alerts} onClose={close} />}
      </div>
      <a className="t-btn" href={href("diagnostyka")} data-testid="t-diag">Diagnostyka</a>
      <button className="t-btn" onClick={ui.openSettings} data-testid="t-settings">Ustawienia</button>
    </header>);
}
