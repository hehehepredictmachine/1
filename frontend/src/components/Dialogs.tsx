import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls } from "../util";

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={cls("modal", wide && "wide")}>
        <div className="modal-head"><b>{title}</b><span className="spacer" /><button className="icon" onClick={onClose}>✕</button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ settings / first run
export function SettingsModal({ onClose }: { onClose: () => void }) {
  const { s, refresh } = useStore();
  const [cfg, setCfg] = useState<any>(null);
  const [secrets, setSecrets] = useState<any>({});
  const [key, setKey] = useState("");
  const [models, setModels] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [tab, setTab] = useState("mt5");
  const load = () => apiGet("/api/v1/config").then((r) => { setCfg(r.config); setSecrets(r.secrets); });
  useEffect(() => { load(); }, []);
  if (!cfg) return <Modal title="Ustawienia" onClose={onClose}><div>Ładowanie…</div></Modal>;
  const set = (path: string, value: any) => {
    const [a, b] = path.split(".");
    setCfg({ ...cfg, [a]: { ...cfg[a], [b]: value } });
  };
  const num = (v: string) => (v === "" ? null : Number(v.replace(",", ".")));
  const save = async (extra: any = {}) => {
    setMsg(null);
    try {
      const patch = { mt5: cfg.mt5, strategy: cfg.strategy, risk: cfg.risk, costs: cfg.costs, agent: cfg.agent, news: cfg.news, telegram: cfg.telegram, execution: cfg.execution, ...extra };
      const r = await apiSend("PUT", "/api/v1/config", patch);
      setCfg(r.config);
      setMsg("Zapisano.");
      refresh();
    } catch (e: any) {
      setMsg("Błąd: " + (e.message || e));
    }
  };
  const saveKey = async () => {
    try {
      await apiSend("POST", "/api/v1/secrets/anthropic", { api_key: key });
      setKey("");
      setMsg("Klucz zapisany lokalnie (DPAPI).");
      load();
    } catch (e: any) {
      setMsg("Błąd: " + (e.message || e));
    }
  };
  const listModels = async () => {
    const r = await apiGet("/api/v1/agent/models");
    if (r.ok) setModels(r.models);
    setMsg(r.ok ? `Dostępnych modeli: ${r.models.length}` : `Błąd: ${r.error}`);
  };
  const testAgent = async () => {
    const r = await apiSend("POST", "/api/v1/agent/test");
    setMsg(r.ok ? `Połączenie OK: ${r.model}` : `Test nieudany: ${r.error}`);
  };
  const field = (label: string, path: string, type: "text" | "num" | "bool" = "text", hint?: string, opts?: string[]) => {
    const [a, b] = path.split(".");
    const v = cfg[a][b];
    return (
      <label className="field">
        <span>{label}{hint && <small> – {hint}</small>}</span>
        {opts ? (
          <select value={v ?? ""} onChange={(e) => set(path, e.target.value)}>{opts.map((o) => <option key={o} value={o}>{o}</option>)}</select>
        ) : type === "bool" ? (
          <input type="checkbox" checked={!!v} onChange={(e) => set(path, e.target.checked)} />
        ) : (
          <input value={v ?? ""} placeholder={type === "num" ? "nie ustawiono" : ""} onChange={(e) => set(path, type === "num" ? num(e.target.value) : (e.target.value || null))} />
        )}
      </label>
    );
  };
  const acct = s.account;
  return (
    <Modal title={cfg.first_run_completed ? "Ustawienia" : "Pierwsze uruchomienie – konfiguracja"} onClose={onClose} wide>
      <div className="tabs">
        {[["mt5", "MT5"], ["agent", "Agent Claude"], ["risk", "Ryzyko"], ["costs", "Koszty"], ["strategy", "Strategia"], ["other", "Inne"]].map(([k, l]) =>
          <button key={k} className={cls(tab === k && "on")} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "mt5" && <div className="form">
        <div className="note">Terminal: <b>{s.connection?.state}</b> {acct ? `· rachunek ${acct.login} (${acct.trade_mode}) ${acct.server} · ${acct.currency}` : ""}
          {s.symbol?.status && <> · symbol <b>{s.symbol.symbol}</b>: {s.symbol.status}</>}
          {s.symbol?.candidates?.length ? <div className="warn">Symbol nie znaleziony. Symbole złota u brokera: {s.symbol.candidates.join(", ")} – program NIE zmienia symbolu sam.</div> : null}</div>
        {field("Dokładny symbol brokera", "mt5.symbol", "text", "np. XAUUSD- (z myślnikiem)")}
        {field("Ścieżka terminal64.exe", "mt5.terminal_path", "text", "puste = domyślny/już uruchomiony terminal; przy kilku terminalach wskaż właściwy")}
        {field("Symbol DXY (opcjonalnie)", "mt5.dxy_symbol", "text", "tylko prawdziwy symbol indeksu u brokera – nie EURUSD")}
        {field("Liczba świec na wykresie", "mt5.chart_bars", "num")}
        <div className="note">Hasło do rachunku nie jest potrzebne – aplikacja łączy się z już zalogowanym terminalem.</div>
      </div>}
      {tab === "agent" && <div className="form">
        <div className="note">Klucz: <b>{secrets.ANTHROPIC_API_KEY?.source}</b> {secrets.ANTHROPIC_API_KEY?.masked ?? ""}. Klucz zostaje w tym komputerze (Windows DPAPI), nie trafia do przeglądarki ani logów.</div>
        <label className="field"><span>Klucz Anthropic API</span><input type="password" value={key} autoComplete="off" onChange={(e) => setKey(e.target.value)} placeholder="sk-ant-…" /></label>
        <div className="row"><button className="btn" disabled={key.length < 10} onClick={saveKey}>Zapisz klucz</button>
          <button className="btn ghost" onClick={listModels}>Pobierz listę modeli</button><button className="btn ghost" onClick={testAgent}>Testuj połączenie</button></div>
        <label className="field"><span>Model (ANTHROPIC_MODEL)</span>
          <select value={cfg.agent.model ?? ""} onChange={(e) => set("agent.model", e.target.value || null)}>
            <option value="">– wybierz –</option>
            {cfg.agent.model && !models.find((m) => m.id === cfg.agent.model) && <option value={cfg.agent.model}>{cfg.agent.model}</option>}
            {models.map((m) => <option key={m.id} value={m.id}>{m.display_name} ({m.id})</option>)}
          </select></label>
        {field("Wysiłek (effort)", "agent.effort", "text", "", ["low", "medium", "high", "xhigh", "max"])}
        {field("Dzienny budżet USD (szacunek)", "agent.daily_budget_usd", "num")}
        {field("Min. odstęp analiz automatycznych [s]", "agent.min_interval_seconds", "num")}
        {field("Rola AI w decyzji", "agent.gate_policy", "text", "VETO = blokuje tylko, gdy Claude jawnie się nie zgadza; brak klucza/odpowiedzi nie blokuje · REQUIRED = wymagana zgoda · ADVISORY = tylko opinia", ["VETO", "REQUIRED", "ADVISORY"])}
        {field("Czekanie na ocenę AI [s]", "agent.ai_wait_seconds", "num", "tylko VETO: po tym czasie brak odpowiedzi nie blokuje")}
        {field("Ocena AI może wpływać na wejście", "agent.required_for_entry", "bool", "odznaczone = ADVISORY")}
        {field("Agent włączony", "agent.enabled", "bool")}
      </div>}
      {tab === "risk" && <div className="form">
        <div className="note warn">Wartości ze zdjęcia (1%, 5%, 10%, 6 pozycji) to przykład widoku – nie są ustawieniami Twojego rachunku. Bez limitów tryby wykonawcze są zablokowane.</div>
        {field("Ryzyko na transakcję [% equity]", "risk.risk_per_trade_pct", "num")}
        {field("Suma otwartego ryzyka [% equity]", "risk.max_total_open_risk_pct", "num")}
        {field("Dzienny limit straty [% salda z początku dnia]", "risk.daily_loss_limit_pct", "num", "dzień = północ czasu serwera; realizowane netto + ujemny P/L otwarty")}
        {field("Maks. drawdown [% od szczytu equity]", "risk.max_drawdown_pct", "num")}
        {field("Maks. liczba pozycji (rachunek)", "risk.max_open_positions", "num")}
        {field("Przerwa po stracie [min]", "risk.cooldown_minutes_after_loss", "num")}
        {field("Zapas wolnego marginu [%]", "risk.min_free_margin_buffer_pct", "num")}
        {field("Maks. spread [punkty]", "risk.max_spread_points", "num")}
        {field("RR netto – blokada poniżej", "risk.rr_block_below", "num", "domyślnie 1.0 (oryginał M11: 1.5)")}
        {field("RR netto – pełne ryzyko od", "risk.rr_pass_from", "num", "domyślnie 1.5 (oryginał M11: 2.0)")}
        {field("RR pomiędzy progami: wejście z mniejszym ryzykiem", "risk.conditional_rr_executes", "bool")}
        {field("Mnożnik ryzyka dla RR warunkowego", "risk.conditional_risk_factor", "num", "0.5 = połowa ryzyka na transakcję")}
        {field("Blokada wejść w oknie wydarzenia makro", "risk.macro_block_high_impact", "bool")}
        {field("Brak kalendarza makro blokuje wejścia", "risk.macro_calendar_required", "bool", "domyślnie wyłączone")}
      </div>}
      {tab === "costs" && <div className="form">
        <div className="note">Profil „Zero” to deklaracja – nie dowód zerowych kosztów. Spread jest w cenach Bid/Ask (nie odejmujemy go drugi raz).</div>
        {field("Źródło prowizji", "costs.commission_mode", "text", "", ["FROM_DEAL_HISTORY", "CONFIGURED", "UNKNOWN"])}
        {field("Prowizja na lot na stronę [waluta rachunku]", "costs.commission_per_lot_per_side", "num")}
        {field("Stres poślizgu [punkty]", "costs.slippage_stress_points", "num", "doliczany do kosztu w RR; domyślnie 20")}
        <div className="note">Reguła „spread do 40%”: w źródłach brak mianownika (M01 v4.2.1 §12) – status WYMAGA USTALENIA, nie jest używana jako filtr.</div>
      </div>}
      {tab === "strategy" && <div className="form">
        {field("Tryb strategii", "strategy.mode", "text", "AUTO = SMC > MVP > SCALPING (stała kolejność, nie ranking)", ["AUTO", "MVP", "SMC", "SCALPING"])}
        {field("Kierunek struktury", "strategy.structure_policy", "text", "H1_LEAD = decyduje H1 (najwięcej setupów) · H1_H4_NOT_OPPOSING = H1, o ile H4 nie jest przeciwny · STRICT_H4_H1 = oryginał MasterQUO (H4 i H1 zgodne)", ["H1_LEAD", "H1_H4_NOT_OPPOSING", "STRICT_H4_H1"])}
        {field("TTL setupu [świece TF setupu]", "strategy.setup_ttl_bars", "num")}
        {field("Okno wejścia po potwierdzeniu [świece]", "strategy.confirmed_window_bars", "num", "potem setup = MISSED_ENTRY")}
        {field("Konflikt D1 blokuje wejście", "strategy.d1_conflict_blocks_entry", "bool")}
        {field("Waga TP1", "strategy.tp1_weight", "num")}
        {field("Min. odległość celu [ATR]", "strategy.min_target_distance_atr", "num")}
        {field("SL na BE po TP1", "strategy.move_sl_to_breakeven_after_tp1", "bool")}
      </div>}
      {tab === "other" && <div className="form">
        {field("Newsy/kalendarz M04N", "news.enabled", "bool")}
        {field("Telegram włączony", "telegram.enabled", "bool")}
        {field("Telegram chat_id", "telegram.chat_id")}
        {field("Wysyłaj sygnały na Telegram", "telegram.send_signals", "bool")}
        {field("Saldo startowe PAPER", "execution.paper_starting_balance", "num")}
        {field("Odchylenie ceny [punkty]", "execution.deviation_points", "num")}
        <div className="note">LIVE wymaga dodatkowo ręcznego ustawienia <code>execution.allow_live_execution: true</code> w pliku data\config.json.</div>
      </div>}
      <div className="row end">
        {msg && <span className="small">{msg}</span>}
        <button className="btn" onClick={() => save()}>Zapisz</button>
        {!cfg.first_run_completed && <button className="btn ghost" onClick={async () => { await save({ first_run_completed: true }); onClose(); }}>Zakończ konfigurację</button>}
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ mode
export function ModeDialog({ onClose }: { onClose: () => void }) {
  const { s } = useStore();
  const [mode, setMode] = useState(s.mode?.mode ?? "READ_ONLY");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const a = s.account;
  const need = mode === "PAPER" ? "PAPER" : mode === "DEMO_EXECUTION" ? String(a?.login ?? "") : mode === "LIVE_EXECUTION" ? `LIVE ${a?.login ?? ""}` : "";
  const apply = async () => {
    try {
      await apiSend("POST", "/api/v1/mode", { mode, confirm });
      setMsg("Tryb zmieniony.");
    } catch (e: any) {
      setMsg("Odmowa: " + (e.message || e));
    }
  };
  const auto = async (on: boolean) => {
    try {
      await apiSend("POST", "/api/v1/auto", { on });
    } catch (e: any) {
      setMsg("Odmowa: " + (e.message || e));
    }
  };
  return (
    <Modal title="Tryb pracy" onClose={onClose}>
      <div className="note">Rachunek: {a ? `${a.login} · ${a.server} · ${a.trade_mode} · ${a.currency}` : "brak połączenia"}. Po restarcie lub zmianie rachunku aplikacja zawsze wraca do READ_ONLY i AUTO OFF.</div>
      <div className="modes">
        {[["READ_ONLY", "Tylko analiza, bez zleceń"], ["PAPER", "Symulacja lokalna (nie konto demo MT5)"], ["DEMO_EXECUTION", "Zlecenia na rachunku DEMO MT5"], ["LIVE_EXECUTION", "Zlecenia na rachunku REAL – wymaga allow_live_execution"]].map(([m, d]) => (
          <label key={m} className={cls("mode-opt", mode === m && "on", m === "LIVE_EXECUTION" && "danger")}>
            <input type="radio" checked={mode === m} onChange={() => { setMode(m); setConfirm(""); }} /> <b>{m}</b> <small>{d}</small>
          </label>
        ))}
      </div>
      {need && <label className="field"><span>Potwierdź wpisując: <code>{need}</code></span><input value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>}
      <div className="row"><button className="btn" onClick={apply}>Zastosuj tryb</button>
        <button className={cls("btn", s.mode?.auto_trading ? "danger" : "ghost")} onClick={() => auto(!s.mode?.auto_trading)}>AUTO TRADING: {s.mode?.auto_trading ? "WYŁĄCZ" : "WŁĄCZ"}</button></div>
      {msg && <div className="note">{msg}</div>}
    </Modal>
  );
}

// ------------------------------------------------------------------ power / stop
export function PowerDialog({ onClose }: { onClose: () => void }) {
  const { s } = useStore();
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const kill = async (on: boolean) => {
    await apiSend("POST", "/api/v1/kill", { on, reason: on ? "user_stop_button" : "user_resume" });
    setMsg(on ? "Nowe wejścia zatrzymane. Otwarte pozycje pozostają z SL/TP po stronie brokera." : "Wznowiono możliwość wejść (bramki sprawdzane ponownie).");
  };
  const close = async () => {
    try {
      const r = await apiSend("POST", "/api/v1/positions/close", { scope: "BOT", confirm });
      setMsg(`Zamknięto: ${r.closed.length}, błędy: ${r.errors.length}`);
    } catch (e: any) {
      setMsg("Odmowa: " + (e.message || e));
    }
  };
  const stopApp = async () => {
    setMsg("Zatrzymywanie aplikacji… (terminal MT5 pozostaje uruchomiony)");
    await apiSend("POST", "/api/v1/admin/shutdown").catch(() => undefined);
  };
  return (
    <Modal title="Zatrzymanie" onClose={onClose}>
      <div className="stack">
        <div className="box"><b>1. Zatrzymaj nowe wejścia</b><p className="small">Nie zamyka pozycji. Wyłącza AUTO TRADING.</p>
          <button className="btn danger" onClick={() => kill(!s.mode?.kill_switch)}>{s.mode?.kill_switch ? "Wznów nowe wejścia" : "STOP nowych wejść"}</button></div>
        <div className="box"><b>2. Zamknij pozycje bota</b><p className="small">Tylko pozycje otwarte/przejęte przez aplikację (bieżący rachunek + PAPER). Wpisz <code>ZAMKNIJ</code>.</p>
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="ZAMKNIJ" />
          <button className="btn danger" disabled={confirm !== "ZAMKNIJ"} onClick={close}>Zamknij pozycje</button></div>
        <div className="box"><b>3. Zatrzymaj aplikację</b><p className="small">Kończy tylko proces MasterQUO (jak 04_STOP_MASTERQUO.bat).</p>
          <button className="btn ghost" onClick={stopApp}>Zatrzymaj MasterQUO</button></div>
      </div>
      {msg && <div className="note">{msg}</div>}
    </Modal>
  );
}
