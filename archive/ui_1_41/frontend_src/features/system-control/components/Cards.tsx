// Centrum sterowania cards: MT5 terminal and account, application behaviour (window, autostart, engine restart), Telegram, risk and
// costs, diagnostics. Values come from the engine (WS state + REST); every change goes through the protected local API.
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../../api";
import { useStore } from "../../../store";
import { useUi } from "../../../ui";
import { cls, fmtMoney, fmtNum, fmtTime } from "../../../util";

function useGet(path: string, every = 0) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => apiGet(path).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  useEffect(() => {
    load();
    if (!every) return;
    const t = setInterval(load, every);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, every]);
  return { d, err, load, setD };
}

export function Mt5Card() {
  const { s } = useStore();
  const ui = useUi();
  const c = s.connection || {};
  const acc = s.account || {};
  const q = s.quote || {};
  const comm = s.decision?.risk?.commission;
  const linked = s.ws === "OPEN";
  return (
    <section className="t-card" aria-labelledby="sc-mt5-h" data-testid="sc-mt5">
      <header className="t-card-head"><div><h2 id="sc-mt5-h">MetaTrader 5</h2><span className="t-dim">źródło danych i rachunek</span></div>
        <span className={cls("t-badge", linked && c.state === "CONNECTED" ? "t-badge-ok" : "t-badge-muted")}>{linked ? c.state ?? "NIEZNANY" : "NIEZNANY"}</span></header>
      <dl className="t-kv t-kv-wide">
        <dt>Terminal</dt><dd>{acc.server ? `${acc.company ?? ""} · ${acc.server}` : "—"}{s.synthetic ? " (symulator)" : ""}</dd>
        <dt>Rachunek / typ</dt><dd>{acc.login ? `${acc.login} · ${acc.trade_mode} · ${acc.margin_mode ?? ""}` : "—"}</dd>
        <dt>Symbol</dt><dd>{s.symbol?.symbol ?? "—"}{s.assets ? ` · aktywo ${s.assets.active}` : ""}</dd>
        <dt>Bid / Ask</dt><dd>{linked && q.bid != null ? `${fmtNum(q.bid, s.symbol?.info?.digits ?? 2)} / ${fmtNum(q.ask, s.symbol?.info?.digits ?? 2)}` : "— / —"}</dd>
        <dt>Spread</dt><dd>{linked && q.spread_points != null ? `${fmtNum(q.spread_points, 0)} pkt (${fmtNum(q.spread, s.symbol?.info?.digits ?? 2)})` : "—"}</dd>
        <dt>Prowizja</dt><dd>{comm?.per_lot_per_side != null ? `${fmtNum(comm.per_lot_per_side, 2)} / lot / stronę (${comm.source})` : `nieznana${comm?.note ? " – " + comm.note : ""}`}</dd>
        <dt>Dźwignia (broker)</dt><dd>{acc.leverage ? `1:${acc.leverage}` : "—"}</dd>
        <dt>Handel dozwolony</dt><dd>{acc.trade_allowed == null ? "—" : acc.trade_allowed && acc.trade_expert ? "tak (terminal i EA)" : "NIE – włącz Algo Trading w MT5"}</dd>
        <dt>Ostatni heartbeat</dt><dd>{fmtTime(c.last_heartbeat, true)}</dd>
      </dl>
      <div className="t-row">
        <button className="t-btn t-btn-acc" onClick={ui.openSettings} data-testid="sc-mt5-config">Konfiguracja MT5</button>
        <span className="t-note">Symbol brokera dla złota: XAUUSD- (wg użytkownika); BTC wybierany z listy symboli brokera w Ustawieniach → mapowanie aktywów.</span>
      </div>
    </section>);
}

export function AppPrefsCard() {
  const { d, err, setD } = useGet("/api/v1/desktop");
  const [p, setP] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [ask, setAsk] = useState(false);
  useEffect(() => { if (d && !p) setP(d.prefs); }, [d, p]);
  const save = async () => {
    setMsg(null);
    try {
      const r = await apiSend("POST", "/api/v1/desktop/prefs", p);
      setD(r);
      setP(r.prefs);
      setMsg("Zapisano.");
    } catch (e: any) {
      setMsg(`Nie zapisano: ${String(e?.message || e)}`);
    }
  };
  const restart = async () => {
    setAsk(false);
    try {
      await apiSend("POST", "/api/v1/desktop/restart-engine", {});
      setMsg("Silnik uruchamia się ponownie – panel odświeży się sam po kilku sekundach.");
    } catch (e: any) {
      setMsg(`Odmowa: ${String(e?.message || e)}`);
    }
  };
  return (
    <section className="t-card" aria-labelledby="sc-app-h" data-testid="sc-app">
      <header className="t-card-head"><div><h2 id="sc-app-h">Praca aplikacji</h2>
        <span className="t-dim">{d ? (d.desktop ? "aplikacja Windows (PepeMarketWizardDesktop.exe)" : "panel w przeglądarce – opcje okna działają w aplikacji Windows") : "—"}</span></div></header>
      {err ? <p className="t-bad-text">{err}</p> : !p ? <p className="t-dim">Ładowanie…</p> : (
        <>
          <label className="t-field">Po zamknięciu okna
            <select value={p.close_action} onChange={(e) => setP({ ...p, close_action: e.target.value })} data-testid="sc-close-action">
              <option value="ask">Zapytaj za każdym razem</option>
              <option value="background">Pracuj w tle (ikona przy zegarze)</option>
              <option value="exit">Zamknij aplikację i zatrzymaj bota</option>
            </select></label>
          <label className="t-check"><input type="checkbox" checked={!!p.autostart} disabled={!d.autostart_supported}
            onChange={(e) => setP({ ...p, autostart: e.target.checked })} data-testid="sc-autostart" /> Uruchamiaj wraz z Windows
            {!d.autostart_supported && <small> (tylko w aplikacji Windows)</small>}</label>
          <label className="t-check"><input type="checkbox" checked={!!p.start_minimized} disabled={!p.autostart}
            onChange={(e) => setP({ ...p, start_minimized: e.target.checked })} /> Przy autostarcie startuj w tle (bez okna)</label>
          {d.autostart_other_exe && <p className="t-notice">Wpis autostartu wskazuje inną kopię programu – zapisz, aby wskazywał tę.</p>}
          <div className="t-row">
            <button className="t-btn t-btn-acc" onClick={save} data-testid="sc-app-save">Zapisz preferencje</button>
            {d.restart_supported && <button className="t-btn" onClick={() => setAsk(true)} data-testid="sc-restart">Uruchom ponownie silnik</button>}
          </div>
          {ask && (
            <div className="t-confirm" role="alertdialog" aria-label="Ponowne uruchomienie silnika">
              <p>Silnik zatrzyma się i uruchomi ponownie (kilka–kilkanaście sekund). Tryb, STOP i otwarte pozycje pozostają; w tym czasie bot nie analizuje rynku.</p>
              <div className="t-row"><button className="t-btn t-btn-acc" onClick={restart}>Uruchom ponownie</button><button className="t-btn" onClick={() => setAsk(false)}>Anuluj</button></div>
            </div>)}
          <p className="t-note">Autostart jest wyłączony, dopóki go nie włączysz (wpis tylko dla bieżącego użytkownika Windows, bez uprawnień administratora).
            Dane aplikacji: <code>{d.data_dir}</code></p>
        </>)}
      {msg && <p className="t-note" role="status" data-testid="sc-app-msg">{msg}</p>}
    </section>);
}

const TG_STATE: Record<string, [string, string]> = {
  NOT_CONFIGURED: ["nieskonfigurowany", "t-badge-muted"], DISABLED: ["wyłączony", "t-badge-muted"], UNTESTED: ["nie sprawdzono połączenia", "t-badge-gold"],
  OK: ["połączenie działa", "t-badge-ok"], ERROR: ["błąd wysyłki", "t-badge-bad"],
};

export function TelegramCard() {
  const { s, refresh } = useStore();
  const st = useGet("/api/v1/telegram", 30000);
  const [cfg, setCfg] = useState<any>(null);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!cfg) apiGet("/api/v1/config").then((c: any) => setCfg(c.config?.telegram ?? c.telegram)).catch(() => undefined);
  }, [cfg]);
  const t = st.d;
  const saveToken = async () => {
    try {
      await apiSend("POST", "/api/v1/secrets", { name: "TELEGRAM_BOT_TOKEN", value: token.trim() || null });
      setToken("");
      setMsg(token.trim() ? "Token zapisany lokalnie (szyfrowanie Windows DPAPI). Nie jest wyświetlany ani logowany." : "Token usunięty.");
      st.load();
    } catch (e: any) {
      setMsg(`Nie zapisano tokenu: ${String(e?.message || e)}`);
    }
  };
  const save = async () => {
    try {
      const r: any = await apiSend("PUT", "/api/v1/config", { telegram: cfg });
      setCfg(r.config?.telegram ?? cfg);
      setMsg("Zapisano ustawienia Telegrama.");
      st.load();
      refresh();
    } catch (e: any) {
      setMsg(`Nie zapisano: ${String(e?.message || e)}`);
    }
  };
  const test = async () => {
    setMsg("Wysyłanie wiadomości testowej…");
    try {
      const r: any = await apiSend("POST", "/api/v1/telegram/test", {});
      setMsg(r.ok ? "Telegram przyjął wiadomość testową – sprawdź czat." : `Telegram nie przyjął wiadomości: ${r.error}`);
      st.load();
    } catch (e: any) {
      setMsg(`Błąd: ${String(e?.message || e)}`);
    }
  };
  const [label, tone] = TG_STATE[t?.state] ?? ["—", "t-badge-muted"];
  return (
    <section className="t-card" aria-labelledby="sc-tg-h" data-testid="sc-telegram">
      <header className="t-card-head"><div><h2 id="sc-tg-h">Telegram</h2><span className="t-dim">powiadomienia EN + 中文 · tylko informacje, bot nie przyjmuje poleceń</span></div>
        <span className={cls("t-badge", tone)} data-testid="sc-tg-state" data-state={t?.state ?? ""}>{label}</span></header>
      {t?.last_error && <p className="t-bad-text" role="status">Ostatni błąd ({fmtTime(t.last_error_at, true)}): {t.last_error}</p>}
      {t?.last_ok_at && <p className="t-note">Ostatnia dostarczona wiadomość: {fmtTime(t.last_ok_at, true)} · wysłano w tej sesji: {t.sent}</p>}
      <label className="t-field">Token bota {t?.token_set ? <small className="t-pos">(zapisany)</small> : <small>(brak)</small>}
        <span className="t-row" style={{ marginTop: 0 }}>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={t?.token_set ? "•••••• (wpisz nowy, aby zmienić)" : "123456:ABC… od @BotFather"}
            autoComplete="off" data-testid="sc-tg-token" />
          <button className="t-btn" onClick={saveToken} disabled={!token.trim() && !t?.token_set}>{token.trim() ? "Zapisz token" : "Usuń token"}</button>
        </span></label>
      {cfg && (
        <>
          <div className="t-grid2">
            <label className="t-field">Chat ID
              <input type="text" value={cfg.chat_id ?? ""} onChange={(e) => setCfg({ ...cfg, chat_id: e.target.value.trim() || null })} placeholder="np. 123456789 lub -100…"
                data-testid="sc-tg-chat" /></label>
            <label className="t-field">Język wiadomości
              <select value={cfg.language} onChange={(e) => setCfg({ ...cfg, language: e.target.value })} data-testid="sc-tg-lang">
                <option value="EN_ZH">English + 中文（简体）</option><option value="EN">English</option><option value="ZH">中文（简体）</option>
              </select></label>
          </div>
          <label className="t-check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="sc-tg-enabled" /> Powiadomienia włączone</label>
          <label className="t-check"><input type="checkbox" checked={cfg.send_signals} onChange={(e) => setCfg({ ...cfg, send_signals: e.target.checked })} /> Sygnały bota</label>
          <label className="t-check"><input type="checkbox" checked={cfg.send_trades} onChange={(e) => setCfg({ ...cfg, send_trades: e.target.checked })} data-testid="sc-tg-trades" /> Otwarcie i zamknięcie pozycji (z trybem: PAPER / DEMO / LIVE)</label>
          <label className="t-check"><input type="checkbox" checked={cfg.send_stats} onChange={(e) => setCfg({ ...cfg, send_stats: e.target.checked })} /> Dzienne podsumowanie o
            <input type="number" min={0} max={23} value={cfg.stats_hour_utc} onChange={(e) => setCfg({ ...cfg, stats_hour_utc: Number(e.target.value) })} style={{ width: 64, margin: "0 6px" }} />UTC</label>
          <div className="t-row">
            <button className="t-btn t-btn-acc" onClick={save} data-testid="sc-tg-save">Zapisz</button>
            <button className="t-btn" onClick={test} disabled={!t?.token_set || !cfg.chat_id} data-testid="sc-tg-test">Wyślij wiadomość testową</button>
            <button className="t-btn" onClick={() => apiSend("POST", "/api/v1/telegram/stats-now", {}).then(() => setMsg("Wysłano podsumowanie (jeśli połączenie działa – sprawdź stan)."))
              .catch((e) => setMsg(String(e?.message || e)))} disabled={!t?.token_set || !cfg.chat_id}>Wyślij podsumowanie teraz</button>
          </div>
        </>)}
      {msg && <p className="t-note" role="status" data-testid="sc-tg-msg">{msg}</p>}
      <p className="t-note">Token: utwórz bota u @BotFather. Chat ID: napisz do bota, a potem otwórz https://api.telegram.org/bot&lt;token&gt;/getUpdates (pole chat.id)
        – tokenu nie wklejaj nigdzie poza tym polem. {s.synthetic ? "Na danych syntetycznych wiadomości mają oznaczenie SYNTHETIC." : ""}</p>
    </section>);
}

export function RiskCostsCard() {
  const { s, refresh } = useStore();
  const [risk, setRisk] = useState<any>(null);
  const [costs, setCosts] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!risk && s.risk_config) setRisk(s.risk_config);
    if (!costs && s.costs_config) setCosts(s.costs_config);
  }, [s.risk_config, s.costs_config, risk, costs]);
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
  const save = async () => {
    try {
      await apiSend("PUT", "/api/v1/config", {
        risk: { risk_per_trade_pct: risk.risk_per_trade_pct, daily_loss_limit_pct: risk.daily_loss_limit_pct, max_open_positions: risk.max_open_positions,
          max_total_open_risk_pct: risk.max_total_open_risk_pct, max_drawdown_pct: risk.max_drawdown_pct },
        costs: { commission_per_lot_per_side: costs.commission_per_lot_per_side, slippage_stress_points: costs.slippage_stress_points,
          commission_mode: costs.commission_per_lot_per_side != null ? "CONFIGURED" : "FROM_DEAL_HISTORY" },
      });
      setMsg("Zapisano. Nowe limity obowiązują od następnej decyzji.");
      refresh();
    } catch (e: any) {
      setMsg(`Nie zapisano: ${String(e?.message || e)}`);
    }
  };
  const field = (obj: any, set: (x: any) => void, k: string, label: string, unit: string, hint: string, int = false) => (
    <label className="t-field" key={k}>{label} <small>{hint}</small>
      <span className="t-row" style={{ marginTop: 0 }}>
        <input type="number" step={int ? 1 : 0.01} value={obj[k] ?? ""} placeholder="nieustawione" onChange={(e) => set({ ...obj, [k]: num(e.target.value) })}
          data-testid={`sc-risk-${k}`} style={{ width: 130 }} /><span className="t-dim">{unit}</span></span></label>);
  const acc = s.account || {};
  const q = s.quote || {};
  return (
    <section className="t-card" aria-labelledby="sc-risk-h" data-testid="sc-risk">
      <header className="t-card-head"><div><h2 id="sc-risk-h">Ryzyko i koszty</h2><span className="t-dim">parametry ustawiasz świadomie – brak wartości = wejścia wstrzymane</span></div></header>
      {!risk || !costs ? <p className="t-dim">Ładowanie…</p> : (
        <>
          <div className="t-grid2">
            {field(risk, setRisk, "risk_per_trade_pct", "Ryzyko na transakcję", "% equity", "strata przy SL (z kosztami)")}
            {field(risk, setRisk, "daily_loss_limit_pct", "Dzienny limit straty", "% equity", "doba serwera brokera")}
            {field(risk, setRisk, "max_open_positions", "Maks. otwartych pozycji", "", "obie ścieżki łącznie", true)}
            {field(risk, setRisk, "max_total_open_risk_pct", "Maks. łączne ryzyko otwarte", "% equity", "")}
            {field(risk, setRisk, "max_drawdown_pct", "Maks. obsunięcie", "% equity", "")}
            {field(costs, setCosts, "commission_per_lot_per_side", "Prowizja", `${acc.currency ?? ""} / lot / stronę`, "puste = z historii transakcji")}
            {field(costs, setCosts, "slippage_stress_points", "Stres poślizgu", "pkt", "doliczany do kosztu")}
          </div>
          <div className="t-row"><button className="t-btn t-btn-acc" onClick={save} data-testid="sc-risk-save">Zapisz ryzyko i koszty</button></div>
        </>)}
      {msg && <p className="t-note" role="status">{msg}</p>}
      <dl className="t-kv">
        <dt>Bieżący spread</dt><dd>{q.spread_points != null ? `${fmtNum(q.spread_points, 0)} pkt` : "—"}</dd>
        <dt>Dźwignia z brokera</dt><dd>{acc.leverage ? `1:${acc.leverage}` : "—"}</dd>
        <dt>Equity / wolny margin</dt><dd>{fmtMoney(acc.equity, acc.currency)} / {fmtMoney(acc.free_margin, acc.currency)}</dd>
      </dl>
      <p className="t-note">Profil rachunku „Zero” nie oznacza zerowych kosztów: prowizja i poślizg są liczone osobno, a nieznana prowizja jest pokazywana jako nieznana.</p>
    </section>);
}

export function DiagnosticsCard() {
  const { s } = useStore();
  const dg = useGet("/api/v1/diagnostics", 30000);
  const d = dg.d || {};
  const alerts = (s.logs || []).filter((l: any) => l.level === "WARNING" || l.level === "ERROR").slice(0, 12);
  return (
    <div className="t-two" data-testid="sc-diag">
      <section className="t-card" aria-label="Stan systemu">
        <header className="t-card-head"><h2>Stan systemu</h2><a className="t-btn" href="#/diagnostyka">Pełna diagnostyka</a></header>
        {dg.err ? <p className="t-bad-text">{dg.err}</p> : (
          <dl className="t-kv t-kv-wide">
            <dt>Wersja</dt><dd>{d.app?.version ?? "—"} · kontrakt {d.app?.contract ?? "—"}{d.app?.synthetic ? " · DANE SYNTETYCZNE" : ""}</dd>
            <dt>Platforma</dt><dd>{d.platform ? `${d.platform.system ?? ""} ${d.platform.release ?? ""} · Python ${d.platform.python ?? ""}` : "—"}</dd>
            <dt>MT5</dt><dd>{d.connection?.state ?? "—"}{d.connection?.reason ? ` – ${d.connection.reason}` : ""}</dd>
            <dt>Wywołania terminala</dt><dd>{d.worker ? `${d.worker.calls} (błędy ${d.worker.failures})` : "—"}{d.worker?.module_error ? ` · ${d.worker.module_error}` : ""}</dd>
            <dt>Cykl silnika</dt><dd>{d.engine?.cycle_ms != null ? `${fmtNum(d.engine.cycle_ms, 0)} ms` : "—"}{d.engine?.last_error ? ` · błąd: ${String(d.engine.last_error).slice(0, 80)}` : ""}</dd>
            <dt>Agent AI</dt><dd>{d.agent?.state ?? "—"}</dd>
            <dt>Kalendarz makro</dt><dd>{d.news?.status ?? "—"}</dd>
            <dt>Zegar PC</dt><dd>{d.pc_clock?.status ?? "—"}{d.pc_clock?.skew_seconds != null ? ` (odchylenie ${fmtNum(d.pc_clock.skew_seconds, 1)} s)` : ""}</dd>
          </dl>)}
      </section>
      <section className="t-card" aria-label="Ostrzeżenia">
        <header className="t-card-head"><h2>Ostrzeżenia i błędy</h2><span className="t-dim">{alerts.length}</span></header>
        {alerts.length === 0 ? <p className="t-dim">Brak ostrzeżeń w tej sesji.</p> : (
          <ul className="t-alerts">{alerts.map((a: any, i: number) => (
            <li key={a.id ?? i} className={a.level === "ERROR" ? "bad" : "warn"}><span className="t-time">{fmtTime(a.ts, true)}</span> <b>{a.level}</b> {a.message}</li>))}</ul>)}
      </section>
    </div>);
}
