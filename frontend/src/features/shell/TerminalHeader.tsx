// Global header of the new panels (approved mockups): page title, environment, MT5 status with a details panel, last update and
// data freshness, execution mode, STOP state, XAUUSD-/BTC switch, notifications, diagnostics and settings. The only action that
// changes the bot is the instrument switch (existing endpoint; in an automatic mode it asks first).
import { useEffect, useRef, useState } from "react";
import { apiSend } from "../../api";
import { href, type Page } from "../../router";
import { useStore } from "../../store";
import { useUi } from "../../ui";
import { cls, fmtNum, fmtTime } from "../../util";
import { fmtUnknown } from "./StateView";
import type { TerminalContext } from "./useTerminalContext";

type Pop = null | "mt5" | "alerts";

const ENV_TONE: Record<string, string> = { LIVE: "bad", DEMO: "info", SYNTHETIC: "warn", HISTORY: "info", UNKNOWN: "muted" };
const FRESH_TONE: Record<string, string> = { FRESH: "ok", DEGRADED: "warn", STALE: "warn", DISCONNECTED: "bad", UNKNOWN: "muted" };

const BELL = "M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0";
const PULSE = "M3 12h4l2.5-6 4 12 2.5-6h5";
const GEAR = "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM12 2.5v3m0 13v3M2.5 12h3m13 0h3M5.3 5.3l2.1 2.1m9.2 9.2 2.1 2.1M5.3 18.7l2.1-2.1m9.2-9.2 2.1-2.1";

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

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
        {row("Stan", ctx.backend === "OPEN" ? fmtUnknown(c.state, undefined, "UNKNOWN")
          : `UNKNOWN – brak połączenia z backendem${c.state ? ` (ostatni znany: ${c.state})` : ""}`)}
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

const TITLES: Partial<Record<Page, string>> = {
  "trading-intelligence": "Trading Intelligence", "ai-neural-lab": "AI Neural Lab", "system-control": "Centrum sterowania",
};

/** XAUUSD- / BTC: broker symbols of the two assets. Switching changes what the bot analyses and trades (existing endpoint); the mode
 *  stays. In an automatic mode the switch asks first. */
function InstrumentSwitch({ ctx }: { ctx: TerminalContext }) {
  const { s, refresh } = useStore();
  const a = s.assets;
  const [ask, setAsk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = usePopover(!!ask || !!err, () => { setAsk(null); setErr(null); });
  const go = async (asset: string) => {
    setAsk(null);
    setBusy(true);
    setErr(null);
    try {
      await apiSend("POST", "/api/v1/assets/active", { asset });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const pick = (asset: string) => {
    if (!a || asset === a.active || busy) return;
    if (ctx.mode === "AUTO_DEMO" || ctx.mode === "AUTO_LIVE") setAsk(asset);
    else go(asset);
  };
  const ids: string[] = a?.allowed || [];
  return (
    <div className="t-pop-anchor">
      <div className="t-seg-switch" role="group" aria-label="Instrument" data-testid="t-instrument" data-broker-symbol={ctx.brokerSymbol ?? ""}
        data-active={a?.active ?? ""}>
        {ids.length === 0 && <span className="t-dim">Instrument UNKNOWN</span>}
        {ids.map((id) => {
          const it = a?.assets?.[id] || {};
          return (
            <button key={id} className={cls(a?.active === id && "on")} aria-pressed={a?.active === id} data-asset={id} data-pop-toggle
              disabled={!it.usable || busy || ctx.backend !== "OPEN"} onClick={() => pick(id)}
              title={it.usable ? `${id} → symbol brokera ${it.broker_symbol} (${it.mapping_status})` :
                `${id}: niedostępne – ${it.blocked_reason ?? "brak mapowania"} (Ustawienia → mapowanie aktywów)`}>
              {it.broker_symbol ?? id}</button>);
        })}
      </div>
      {(ask || err) && (
        <div className="t-pop t-pop-wide" ref={ref} role="dialog" aria-label="Zmiana instrumentu" data-testid="t-instrument-confirm">
          {err ? <p className="t-bad-text" role="alert">Nie zmieniono instrumentu: {err}</p> : (
            <>
              <p>Tryb <b>{ctx.mode}</b> jest aktywny. Przełączenie na <b>{a?.assets?.[ask!]?.broker_symbol ?? ask}</b> zmieni instrument, który bot
                analizuje i na którym otwiera nowe pozycje. Tryb pozostaje bez zmian; dane terminala zostaną przeładowane.</p>
              <div className="t-row">
                <button className="t-btn t-btn-acc" onClick={() => go(ask!)} data-testid="t-instrument-yes">Przełącz</button>
                <button className="t-btn" onClick={() => setAsk(null)}>Anuluj</button>
              </div>
            </>)}
        </div>)}
    </div>);
}

export default function TerminalHeader({ ctx, page, quoteAge }: { ctx: TerminalContext; page: Page; quoteAge: number | null }) {
  const ui = useUi();
  const { s } = useStore();
  const [pop, setPop] = useState<Pop>(null);
  const toggle = (p: Pop) => setPop(pop === p ? null : p);
  const close = () => setPop(null);
  const updated = s.quote?.time_utc ?? s.decision?.as_of_utc ?? null;
  return (
    <header className="t-header" data-testid="t-header">
      <div className="t-title">
        <b>Terminal</b>
        <span>{TITLES[page] ?? page}</span>
      </div>
      <span className="t-spacer" />
      <span className={cls("t-chip", `t-env-${ENV_TONE[ctx.env]}`)} title={ctx.envDetail} data-testid="t-env" data-env={ctx.env}>
        <b>{ctx.env === "SYNTHETIC" ? "SYMULATOR" : ctx.env}</b></span>
      <div className="t-pop-anchor">
        <button className={cls("t-chip", ctx.mt5 === "CONNECTED" ? "ok" : ctx.mt5 === "UNKNOWN" ? "muted" : "bad")} data-pop-toggle aria-expanded={pop === "mt5"}
          aria-haspopup="dialog" onClick={() => toggle("mt5")} data-testid="t-mt5" data-mt5={ctx.mt5}>
          <i className="t-dot" aria-hidden="true" />MT5: <b>{ctx.mt5 === "CONNECTED" ? "POŁĄCZONY" : ctx.mt5 === "UNKNOWN" ? "NIEZNANY" : "ROZŁĄCZONY"}</b>
          {ctx.mt5State && ctx.mt5State !== ctx.mt5 && ctx.mt5State !== "CONNECTED"
            ? <span className="t-dim"> ({ctx.backend === "OPEN" ? ctx.mt5State : `ostatnio ${ctx.mt5State}`})</span> : null}
        </button>
        {pop === "mt5" && <Mt5Details ctx={ctx} quoteAge={quoteAge} onClose={close} />}
      </div>
      <span className={cls("t-chip", FRESH_TONE[ctx.freshness])} title={`Dane: ${ctx.freshness} – ${ctx.freshnessDetail}`} data-testid="t-fresh"
        data-fresh={ctx.freshness}>
        <i className="t-dot" aria-hidden="true" /><span className="t-lbl">Aktualizacja: </span><b>{updated && ctx.backend === "OPEN" ? fmtTime(updated) : "—"}</b>
        <span className="t-sr">Dane {ctx.freshness}</span></span>
      <span className={cls("t-chip", ctx.mode === "AUTO_LIVE" ? "bad" : ctx.mode === "SIGNALS" || !ctx.mode ? "muted" : "warn")} data-testid="t-mode"
        title={`Tryb wykonania bota${ctx.modeLabel ? `: ${ctx.modeLabel}` : ""} – zmiana w Centrum sterowania`}>
        <span className="t-lbl">Tryb: </span><b>{fmtUnknown(ctx.mode?.replace("_", " "), undefined, "NIEZNANY")}</b></span>
      <span className={cls("t-chip", ctx.killSwitch ? "bad" : ctx.mode ? "ok" : "muted")} data-testid="t-entries"
        title="STOP zatrzymuje tylko nowe wejścia; otwarte pozycje są dalej prowadzone">Wejścia: <b>{ctx.mode ? (ctx.killSwitch ? "STOP" : "AKTYWNE") : "UNKNOWN"}</b></span>
      <InstrumentSwitch ctx={ctx} />
      {ctx.backend !== "OPEN" && <span className="t-chip bad" data-testid="t-backend">Backend <b>{ctx.backend}</b></span>}
      <div className="t-pop-anchor">
        <button className={cls("t-btn", "t-icon-btn", ctx.alerts.length > 0 && "t-btn-warn")} data-pop-toggle aria-expanded={pop === "alerts"} aria-haspopup="dialog"
          onClick={() => toggle("alerts")} data-testid="t-alerts" aria-label={`Powiadomienia: ${ctx.alerts.length}`} title="Powiadomienia (ostrzeżenia i błędy)">
          <Icon d={BELL} /><b>{ctx.alerts.length}</b></button>
        {pop === "alerts" && <AlertsList alerts={ctx.alerts} onClose={close} />}
      </div>
      <a className="t-btn t-icon-btn" href={href("diagnostyka")} data-testid="t-diag" aria-label="Diagnostyka" title="Diagnostyka"><Icon d={PULSE} /></a>
      <button className="t-btn t-icon-btn" onClick={ui.openSettings} data-testid="t-settings" aria-label="Ustawienia" title="Ustawienia"><Icon d={GEAR} /></button>
    </header>);
}
