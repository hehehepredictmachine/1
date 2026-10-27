// Execution mode, primary path and STOP. Every change goes through the engine's checked endpoints (POST /api/v1/mode with the account
// confirmation, /mode/primary-path, /kill). The first AUTO LIVE shows an explicit summary of the account and the user's risk limits and
// needs the confirmation phrase once - the choice is kept across restarts (bound to the account), it is not a lock to undo every time.
import { Fragment, useState } from "react";
import { apiSend } from "../../../api";
import { useStore } from "../../../store";
import { cls, fmtMoney } from "../../../util";

export const MODES: { id: string; label: string; sub: string; effect: string }[] = [
  { id: "SIGNALS", label: "Analiza", sub: "Setupy i sygnały, bez zleceń", effect: "Bot analizuje i pokazuje sygnały. Nie otwiera pozycji – ani prawdziwych, ani symulowanych." },
  { id: "PAPER", label: "PAPER", sub: "Symulacja lokalna", effect: "Bot „wykonuje” sygnały w lokalnej symulacji na notowaniach MT5. Do brokera nie trafia żadne zlecenie." },
  { id: "AUTO_DEMO", label: "AUTO DEMO", sub: "Rachunek testowy", effect: "Bot składa prawdziwe zlecenia na potwierdzonym rachunku DEMO (bez prawdziwych pieniędzy)." },
  { id: "AUTO_LIVE", label: "AUTO LIVE", sub: "Rachunek rzeczywisty", effect: "Bot składa prawdziwe zlecenia na rachunku REAL – prawdziwe pieniądze, możliwa strata kapitału." },
];

const ERR_PL: Record<string, string> = {
  NO_MT5_ACCOUNT: "Brak połączonego rachunku MT5.",
  ACCOUNT_IS_NOT_DEMO: "Połączony rachunek nie jest rachunkiem DEMO.",
  ACCOUNT_IS_NOT_REAL: "Połączony rachunek nie jest rachunkiem REAL.",
  CONFIRMATION_MUST_EQUAL_ACCOUNT_LOGIN: "Wpisz dokładnie numer rachunku (login).",
  CONFIRMATION_MUST_EQUAL_LIVE_LOGIN: "Wpisz dokładnie frazę LIVE i numer rachunku.",
  LIVE_NOT_AVAILABLE_ON_SYNTHETIC_DATA: "AUTO LIVE jest niedostępne na danych syntetycznych.",
};

export default function ModePanel() {
  const { s, refresh } = useStore();
  const m = s.mode || {};
  const acc = s.account || {};
  const risk = s.risk_config || {};
  const [pick, setPick] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      await refresh();
    } catch (e: any) {
      const code = String(e?.message || e);
      setMsg(ERR_PL[code] ?? `Odmowa: ${code}`);
    } finally {
      setBusy(false);
    }
  };
  const apply = () => run(async () => {
    await apiSend("POST", "/api/v1/mode", { mode: pick, confirm });
    setPick(null);
    setConfirm("");
  }, `Tryb zmieniony na ${pick}.`);
  const login = acc.login != null ? String(acc.login) : "";
  const need = pick === "AUTO_DEMO" ? login : pick === "AUTO_LIVE" ? `LIVE ${login}` : "";
  const sel = MODES.find((x) => x.id === pick);
  const limits: [string, any][] = [["Ryzyko na transakcję", risk.risk_per_trade_pct != null ? `${risk.risk_per_trade_pct} %` : null],
    ["Dzienny limit straty", risk.daily_loss_limit_pct != null ? `${risk.daily_loss_limit_pct} %` : null],
    ["Maks. otwartych pozycji", risk.max_open_positions], ["Maks. łączne ryzyko otwarte", risk.max_total_open_risk_pct != null ? `${risk.max_total_open_risk_pct} %` : null]];
  const inst = m.instrument ?? s.assets?.active;
  return (
    <section className="t-card" aria-labelledby="sc-mode-h" data-testid="sc-mode">
      <header className="t-card-head"><div><h2 id="sc-mode-h">Tryb pracy</h2>
        <span className="t-dim">rzeczywisty tryb: <b data-testid="sc-mode-current">{m.mode ?? "nieznany"}</b>{m.bound_account ? ` · rachunek ${m.bound_account}` : ""}</span></div></header>
      {m.mode_note && <p className="t-notice" role="note" data-testid="sc-mode-note">{m.mode_note}</p>}
      <div className="t-mode-grid" role="radiogroup" aria-label="Tryb pracy">
        {MODES.map((x) => (
          <button key={x.id} role="radio" aria-checked={m.mode === x.id} className={cls("t-mode-card", m.mode === x.id && "on", pick === x.id && "pick", x.id === "AUTO_LIVE" && "live")}
            disabled={busy || s.ws !== "OPEN"} onClick={() => { if (x.id !== m.mode) { setPick(x.id); setConfirm(""); setMsg(null); } }} data-mode={x.id}>
            <b>{x.label}</b><small>{x.sub}</small>
          </button>))}
      </div>
      {sel && (
        <div className={cls("t-confirm", pick === "AUTO_LIVE" && "t-confirm-live")} role="alertdialog" aria-label={`Zmiana trybu na ${sel.label}`} data-testid="sc-mode-confirm">
          <p><b>{sel.label}:</b> {sel.effect}</p>
          {(pick === "AUTO_DEMO" || pick === "AUTO_LIVE") && (
            <>
              <dl className="t-kv">
                <dt>Rachunek</dt><dd>{login ? `${login} · ${acc.server ?? "—"} · ${acc.company ?? "—"}` : "brak połączonego rachunku"}</dd>
                <dt>Typ (z terminala)</dt><dd className={cls(pick === "AUTO_LIVE" && acc.trade_mode === "REAL" && "t-neg")}>{acc.trade_mode ?? "—"}</dd>
                <dt>Saldo / equity</dt><dd>{fmtMoney(acc.balance, acc.currency)} / {fmtMoney(acc.equity, acc.currency)}</dd>
                <dt>Dźwignia (broker)</dt><dd>{acc.leverage ? `1:${acc.leverage}` : "—"}</dd>
                <dt>Instrument</dt><dd>{s.symbol?.symbol ?? "—"} · ścieżka główna {m.primary_path_label ?? "—"}</dd>
                {limits.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd className={cls(v == null && "t-neg")}>{v ?? "nieustawione – wejścia będą wstrzymane"}</dd></Fragment>)}
              </dl>
              <label className="t-field">Potwierdzenie – wpisz <code>{need || "(brak rachunku)"}</code>
                <input type="text" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" spellCheck={false} data-testid="sc-mode-phrase" />
              </label>
              {pick === "AUTO_LIVE" && <p className="t-note">Wybór AUTO LIVE jest zapamiętany dla tego rachunku i nie wymaga ponownego potwierdzania przy każdym starcie.
                STOP zatrzymuje nowe wejścia w każdej chwili; zmiana rachunku w terminalu wstrzymuje wysyłkę do czasu ponownego potwierdzenia.</p>}
            </>)}
          <div className="t-row">
            <button className={cls("t-btn", pick === "AUTO_LIVE" ? "t-btn-danger" : "t-btn-acc")} disabled={busy || (!!need && confirm.trim() !== need)} onClick={apply}
              data-testid="sc-mode-apply">Zmień tryb na {sel.label}</button>
            <button className="t-btn" onClick={() => setPick(null)}>Anuluj</button>
          </div>
        </div>)}
      <div className="t-row" aria-label="Ścieżka główna">
        <span>Ścieżka główna {inst}:</span>
        <div className="t-seg-switch" role="group" aria-label="Ścieżka główna">
          {([["ACTIVE", "S01–S12"], ["SH", "SCALPING / HEDGING"], ["UNSET", "nie wybrano"]] as const).map(([p, l]) => (
            <button key={p} className={cls(m.primary_path === p && "on")} aria-pressed={m.primary_path === p} disabled={busy || s.ws !== "OPEN"}
              onClick={() => run(() => apiSend("POST", "/api/v1/mode/primary-path", { instrument: inst, path: p }), `Ścieżka główna: ${l}.`)}
              data-testid={`sc-path-${p}`}>{l}</button>))}
        </div>
      </div>
      <p className="t-note">Ścieżka główna otwiera nowe pozycje na instrumencie; druga ścieżka tylko analizuje. Bez wybranej ścieżki nowe wejścia są wstrzymane.</p>
      {msg && <p className="t-note" role="status" data-testid="sc-mode-msg">{msg}</p>}
    </section>);
}

export function StopPanel() {
  const { s, refresh } = useStore();
  const m = s.mode || {};
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setErr(null);
    try {
      await apiSend("POST", "/api/v1/kill", { on: !m.kill_switch, reason: "USER_PANEL" });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const pos = (s.positions?.positions || []).length;
  return (
    <section className="t-card" aria-labelledby="sc-stop-h" data-testid="sc-stop">
      <header className="t-card-head"><h2 id="sc-stop-h">Sterowanie wejściami</h2>
        <span className={cls("t-badge", m.kill_switch ? "t-badge-bad" : "t-badge-ok")} data-testid="sc-stop-state">{m.kill_switch ? "STOP – nowe wejścia zatrzymane" : "nowe wejścia dozwolone"}</span></header>
      <button className={cls("t-btn", m.kill_switch ? "t-btn-acc" : "t-btn-danger")} disabled={busy || s.ws !== "OPEN" || !m.mode} onClick={toggle} data-testid="sc-stop-btn">
        {m.kill_switch ? "▶ Wznów nowe wejścia" : "■ Zatrzymaj nowe wejścia (STOP)"}</button>
      {err && <p className="t-bad-text" role="alert">{err}</p>}
      <p className="t-note">STOP dotyczy tylko nowych wejść. Otwarte pozycje ({pos} na rachunku) bot dalej prowadzi według planu (SL/TP, częściowe zamknięcia,
        break-even), o ile terminal MT5 jest dostępny. Ręczne zamknięcie pozycji działa także przy STOP.</p>
      {m.kill_reason && <p className="t-note">Powód zatrzymania: {m.kill_reason}</p>}
    </section>);
}
