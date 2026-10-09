import { useEffect, useState } from "react";
import { apiGet, apiSend, apiUpload } from "../api";
import { useAppearance, type AnimMode } from "../appearance";
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
    const keys = path.split(".");
    const upd = (obj: any, i: number): any => (i === keys.length - 1 ? { ...obj, [keys[i]]: value } : { ...obj, [keys[i]]: upd(obj?.[keys[i]] ?? {}, i + 1) });
    setCfg(upd(cfg, 0));
  };
  const num = (v: string) => (v === "" ? null : Number(v.replace(",", ".")));
  const save = async (extra: any = {}) => {
    setMsg(null);
    try {
      const { strategies: _st, ...activeRest } = cfg.active || {};
      const patch = { mt5: cfg.mt5, strategy: cfg.strategy, risk: cfg.risk, costs: cfg.costs, agent: cfg.agent, news: cfg.news, telegram: cfg.telegram, execution: cfg.execution,
        active: activeRest, ...extra };
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
    const v = path.split(".").reduce((o: any, k) => (o == null ? undefined : o[k]), cfg);
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
        {[["mt5", "MT5"], ["agent", "Agent Claude"], ["risk", "Ryzyko"], ["costs", "Koszty"], ["active", "AUTO / ACTIVE"], ["strategy", "Strategia M07"], ["look", "Wygląd"], ["other", "Inne"]].map(([k, l]) =>
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
      {tab === "active" && <div className="form">
        <div className="note">Profil ACTIVE: 10 strategii S01–S10, etapy WATCH / EARLY / CONFIRMED z punktacją 0–100 (heurystyka, nie prawdopodobieństwo).
          AUTO wybiera strategię – <b>nie</b> włącza składania zleceń (to osobny przełącznik „Wykonywanie zleceń”). ORIGINAL = wyłącznie dotychczasowy M07.</div>
        {field("Profil wykrywania", "active.profile", "text", "", ["ACTIVE", "ORIGINAL"])}
        {field("Wybór strategii", "active.strategy_mode", "text", "AUTO = bot dobiera strategię do rynku", ["AUTO", "MANUAL"])}
        {field("Strategia w trybie MANUAL", "active.manual_strategy_id", "text", "", ["", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10"])}
        {field("Próg WATCH", "active.thresholds.watch", "num")}
        {field("Próg EARLY", "active.thresholds.early", "num")}
        {field("Próg CONFIRMED", "active.thresholds.confirmed", "num", "plus prawdziwy trigger strategii")}
        {field("Min. odstęp skanów [s]", "active.scan_min_interval_seconds", "num", "tylko przy nowych danych")}
        {field("Przewaga do przełączenia [pkt rankingu]", "active.min_switch_margin", "num")}
        {field("Potwierdzenia przewagi [aktualizacje]", "active.switch_confirm_updates", "num", "liczone tylko na nowych danych")}
        {field("Min. czas utrzymania wyboru [s]", "active.min_selection_hold_seconds", "num")}
        {field("Margines konfliktu LONG/SHORT", "active.conflict_margin", "num")}
        {field("Obniżenie etapu po [aktualizacjach]", "active.downgrade_confirm_updates", "num")}
        {field("Anulowanie po [aktualizacjach bez struktury]", "active.cancel_after_misses", "num")}
        {field("Okno wejścia po CONFIRMED [świece]", "active.confirmed_window_bars", "num")}
        <div className="note">Skanowanie i dopuszczenie do handlu każdej strategii ustawiasz w panelu „Strategie (10)”. Powrót do poprzedniej konfiguracji: profil ORIGINAL (instrukcja w ROLLBACK.md).</div>
      </div>}
      {tab === "look" && <LookTab />}
      {tab === "other" && <div className="form">
        {field("Newsy/kalendarz M04N", "news.enabled", "bool")}
        {field("Telegram włączony", "telegram.enabled", "bool")}
        {field("Telegram chat_id", "telegram.chat_id")}
        {field("Wysyłaj sygnały na Telegram", "telegram.send_signals", "bool")}
        {field("Saldo startowe PAPER", "execution.paper_starting_balance", "num")}
        {field("Odchylenie ceny [punkty]", "execution.deviation_points", "num")}
        <div className="note">Tryb wykonania (Analiza warunków / PAPER / AUTO DEMO / AUTO LIVE) zmieniasz przyciskiem TRYB w nagłówku.</div>
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
  const { s, refresh } = useStore();
  const [mode, setMode] = useState(s.mode?.mode ?? "PAPER");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const a = s.account;
  const need = mode === "AUTO_DEMO" ? String(a?.login ?? "") : mode === "AUTO_LIVE" ? `LIVE ${a?.login ?? ""}` : "";
  const run = async (fn: () => Promise<any>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      await refresh();
    } catch (e: any) {
      setMsg("Odmowa: " + (e.message || e));
    }
  };
  const strategyMode = s.auto?.strategy_mode ?? s.active_config?.strategy_mode ?? "AUTO";
  const mlMode = s.ml?.mode ?? s.mode?.ml_mode ?? "SHADOW";
  return (
    <Modal title="Tryby pracy" onClose={onClose}>
      <div className="note">Rachunek wg terminala: {a ? `${a.login} · ${a.server} · ${a.trade_mode} · ${a.currency}` : "brak połączenia"}.
        Trzy niezależne ustawienia – zmiana jednego nie zmienia pozostałych. Wybór jest zapisywany i odtwarzany po restarcie.</div>
      <b>1. Wybór strategii</b>
      <div className="row">
        {["AUTO", "MANUAL"].map((m) => <button key={m} className={cls("btn", strategyMode === m ? "" : "ghost")}
          onClick={() => run(() => apiSend("POST", "/api/v1/strategy/mode", m === "AUTO" ? { strategy_mode: "AUTO" } : { strategy_mode: "MANUAL", manual_strategy_id: s.auto?.selected_strategy_id || "S01" }), `Wybór strategii: ${m}`)}>{m}</button>)}
      </div>
      <b>2. Rola modeli ML</b>
      <div className="row">
        {[["OFF", "wyłączone"], ["SHADOW", "oceniają w tle, bez wpływu"], ["ASSIST", "zatwierdzony model wpływa na ranking i bramkę"]].map(([m, d]) => (
          <button key={m} title={d} className={cls("btn", mlMode === m ? "" : "ghost")} onClick={() => run(() => apiSend("POST", "/api/v1/ml/mode", { mode: m }), `Tryb ML: ${m}`)}>{m}</button>))}
      </div>
      <b>3. Wykonanie</b>
      <div className="modes">
        {[["SIGNALS", "Analiza warunków", "checklista warunków, bez zleceń"], ["PAPER", "PAPER", "automatyczna symulacja lokalna – nigdy nie wysyła zleceń do brokera"],
          ["AUTO_DEMO", "AUTO DEMO", "automatyczne zlecenia tylko na rachunku DEMO (typ odczytany z terminala)"],
          ["AUTO_LIVE", "AUTO LIVE", "automatyczne zlecenia na rachunku REAL – prawdziwe pieniądze"]].map(([m, l, d]) => (
          <label key={m} className={cls("mode-opt", mode === m && "on", m === "AUTO_LIVE" && "danger")}>
            <input type="radio" checked={mode === m} onChange={() => { setMode(m); setConfirm(""); }} /> <b>{l}</b> <small>{d}</small>
          </label>
        ))}
      </div>
      {need && <label className="field"><span>Jednorazowe potwierdzenie przełączenia (nie każdej transakcji) – wpisz: <code>{need}</code></span>
        <input value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>}
      <div className="row"><button className="btn" onClick={() => run(() => apiSend("POST", "/api/v1/mode", { mode, confirm }), "Tryb wykonania zmieniony.")}>Zastosuj tryb wykonania</button></div>
      {(s.decision?.mode_gate?.reason_codes || []).length > 0 && <div className="note warn">Wysyłka zleceń teraz niedozwolona: {(s.decision.mode_gate.reason_codes || []).join(", ")}</div>}
      <div className="note">STOP (przycisk ⏻) zatrzymuje tylko nowe wejścia; zamykanie pozycji to osobna operacja w tym samym oknie.</div>
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

// ------------------------------------------------------------------ appearance (presentation only)
function LookTab() {
  const { prefs, setPrefs, assets, reloadAssets } = useAppearance();
  const [msg, setMsg] = useState<string | null>(null);
  const upload = async (slot: "background" | "frog", f: File | undefined) => {
    if (!f) return;
    setMsg(null);
    try {
      const r = await apiUpload(`/api/v1/appearance/upload?slot=${slot}`, f);
      setMsg(`Wgrano: ${r.gif.width}×${r.gif.height}, ${r.gif.frames} klatek, pętla ${r.gif.loop_duration_ms} ms, przezroczystość: ${r.gif.transparency ? "tak" : "nie"}`);
      reloadAssets();
    } catch (e: any) {
      setMsg("Błąd: " + (e?.message || e));
    }
  };
  const info = (slot: string) => {
    const a = assets?.[slot];
    if (!a) return "brak informacji";
    if (!a.animated_available) return "animowany GIF niedostępny – używany kadr statyczny";
    return `${a.source === "USER_UPLOAD" ? "wgrany przez Ciebie" : "wbudowany"}: ${a.gif?.width}×${a.gif?.height}, ${a.gif?.frames} klatek, ${a.gif?.loop_duration_ms} ms`;
  };
  return (
    <div className="form">
      <div className="note">Ustawienia wyglądu nie zmieniają danych, wyboru strategii ani zleceń. Zapisywane lokalnie w tej przeglądarce.</div>
      <label className="field"><span>Animacje</span>
        <select value={prefs.mode} onChange={(e) => setPrefs({ mode: e.target.value as AnimMode })}>
          <option value="FULL">FULL – animowane tło i tańcząca żaba</option>
          <option value="LIGHT">LIGHT – statyczne tło, żaba animowana</option>
          <option value="OFF">OFF – statyczne kadry obu grafik</option>
        </select></label>
      <label className="field"><span>Przyciemnienie tła <small>{Math.round(prefs.dim * 100)}%</small></span>
        <input type="range" min={0} max={0.9} step={0.05} value={prefs.dim} onChange={(e) => setPrefs({ dim: Number(e.target.value) })} /></label>
      <label className="field"><span>Kadrowanie tła – poziomo <small>{prefs.posX}%</small></span>
        <input type="range" min={0} max={100} step={1} value={prefs.posX} onChange={(e) => setPrefs({ posX: Number(e.target.value) })} /></label>
      <label className="field"><span>Kadrowanie tła – pionowo <small>{prefs.posY}%</small></span>
        <input type="range" min={0} max={100} step={1} value={prefs.posY} onChange={(e) => setPrefs({ posY: Number(e.target.value) })} /></label>
      <div className="note">Tło (pierwszy GIF, 4FDC48DF…): {info("background")}.<br />Żaba przy BALANCE (drugi GIF, 2C98C50C…): {info("frog")}.</div>
      <label className="field"><span>Wgraj oryginalny GIF tła (4FDC48DF-6C65-4AF7-9C88-3AA720BEAEB4.gif)</span>
        <input type="file" accept="image/gif" onChange={(e) => upload("background", e.target.files?.[0])} /></label>
      <label className="field"><span>Wgraj GIF żaby (opcjonalnie – wbudowany jest już dołączony)</span>
        <input type="file" accept="image/gif" onChange={(e) => upload("frog", e.target.files?.[0])} /></label>
      {msg && <div className="note">{msg}</div>}
    </div>
  );
}
