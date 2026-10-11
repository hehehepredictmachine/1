// 1.8: "Setup" selector (AUTO / WYBRANY SETUP / WSZYSTKIE), scenario list and "Szczegóły setupu", plus the
// "Dźwignia / limit ekspozycji" setting. Everything is backed by the engine (backend: prefs.py, engine/setup_details.py);
// the choice is stored per MT5 account (server:login) on the backend, so a refresh or restart keeps it.
// Choosing a setup never creates a signal or an order: it only chooses what the engine analyses and what is shown.
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const SCEN_TONE: Record<string, string> = { WARUNKI_SPELNIONE: "ok", OCZEKIWANIE: "warn", UNIEWAZNIONY: "muted", BRAK_DANYCH: "bad" };
const SCEN_PL: Record<string, string> = { WARUNKI_SPELNIONE: "WARUNKI SPEŁNIONE", OCZEKIWANIE: "OCZEKIWANIE", UNIEWAZNIONY: "UNIEWAŻNIONY", BRAK_DANYCH: "BRAK DANYCH" };
const CK_ICON: Record<string, string> = { "SPEŁNIONY": "✓", "NIESPEŁNIONY": "✗", "BRAK DANYCH": "?", "ODCZYT": "•", "—": "–" };
const AGREE_TONE: Record<string, string> = { ZGODNY: "ok", KONFLIKT: "bad", NEUTRALNY: "muted", "BRAK DANYCH": "muted" };
const BIND_PL: Record<string, string> = { risk: "budżet ryzyka", margin: "wolny margin", exposure: "limit ekspozycji (dźwignia)", volume_max: "maks. wolumen symbolu" };

function useTick(ms: number) {
  const [t, setT] = useState(0);
  useEffect(() => { const h = setInterval(() => setT((x) => x + 1), ms); return () => clearInterval(h); }, [ms]);
  return t;
}

const age = (s: number | null | undefined) => (s == null ? "—" : s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`);

export default function SetupPanel() {
  const { s } = useStore();
  const prefs = s.prefs;
  const view = prefs?.setup_view ?? { mode: "AUTO", strategy_id: null, focus_setup_id: null };
  const [list, setList] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const tick = useTick(5000);
  const decisionKey = `${s.decision?.decision_id}:${s.decision?.signal_view?.state}`;
  useEffect(() => { apiGet("/api/v1/setups").then(setList).catch(() => undefined); }, [tick, decisionKey, view.mode]);
  const setView = (v: any) => apiSend("POST", "/api/v1/prefs/setup-view", v).then(() => setErr(null)).catch((e) => setErr(String(e.message || e)));
  const strategies: any[] = list?.strategies ?? [];
  const engineSel = list?.engine_selected ?? null;          // tracker id of the engine's selection (same source as the details endpoint)
  const detailId = view.mode === "ALL" ? view.focus_setup_id : engineSel;
  const items: any[] = (list?.items ?? []).filter((i: any) => view.mode !== "SELECTED" || i.strategy_id === view.strategy_id);
  return (
    <section className="setup-panel" data-testid="setup-panel">
      <div className="setup-bar">
        <b>Setup:</b>
        <div className="tabs small" role="tablist">
          <button className={cls(view.mode === "AUTO" && "on")} data-testid="setup-auto" onClick={() => setView({ mode: "AUTO" })}
            title="automatyczny wybór setupu przez silnik (dotychczasowe działanie)">AUTO</button>
          <button className={cls(view.mode === "SELECTED" && "on")} data-testid="setup-selected"
            onClick={() => setView({ mode: "SELECTED", strategy_id: view.strategy_id ?? strategies[0]?.strategy_id ?? "S01" })}
            title="silnik analizuje i pokazuje tylko wskazaną strategię; nic nie jest wymuszane">WYBRANY SETUP</button>
          <button className={cls(view.mode === "ALL" && "on")} data-testid="setup-all" onClick={() => setView({ mode: "ALL", focus_setup_id: view.focus_setup_id })}
            title="przegląd wszystkich scenariuszy; silnik wybiera automatycznie">WSZYSTKIE</button>
        </div>
        {view.mode === "SELECTED" && (
          <select value={view.strategy_id ?? ""} data-testid="setup-strategy" onChange={(e) => setView({ mode: "SELECTED", strategy_id: e.target.value })}>
            {strategies.map((x) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} {x.name}</option>)}
          </select>)}
        <span className="muted small">Wybór nie wymusza sygnału ani zlecenia – obowiązują wszystkie filtry ryzyka i jakości danych. Zapisany dla rachunku {prefs?.account_key ?? "—"}.</span>
        {err && <span className="bad small">{err}</span>}
      </div>
      {(view.mode === "ALL" || view.mode === "SELECTED") && (
        <div className="table-wrap scen-list">
          <table className="tbl" data-testid="scenario-list">
            <thead><tr><th>Strategia</th><th>Kierunek</th><th>TF</th><th>Status scenariusza</th><th>Wynik</th><th>Powstał</th><th>Identyfikator</th><th></th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.setup_id} className={cls(detailId === i.setup_id && "sel")} data-setup={i.setup_id}>
                  <td>{i.strategy_id} {i.strategy_name}{i.engine_selected && <span className="badge ok" title="setup wybrany przez silnik"> silnik</span>}</td>
                  <td className={i.direction === "BUY" ? "pos" : "neg"}>{i.direction}</td><td>{i.timeframe}</td>
                  <td><span className={cls("badge", SCEN_TONE[i.scenario_status])}>{SCEN_PL[i.scenario_status]}</span></td>
                  <td>{i.setup_score ?? "—"}</td><td>{fmtTime(i.created_at, true)}</td><td className="muted small">{i.setup_id}</td>
                  <td>{view.mode === "ALL" && <button data-testid="open-details" onClick={() => setView({ mode: "ALL", focus_setup_id: i.setup_id })}>Szczegóły</button>}</td>
                </tr>))}
              {!items.length && <tr><td colSpan={8} className="muted">Brak scenariuszy{view.mode === "SELECTED" ? ` dla ${view.strategy_id}` : ""} – strategia nie wykryła struktury.</td></tr>}
            </tbody>
          </table>
        </div>)}
      <SetupDetails setupId={detailId} mode={view.mode} strategyId={view.strategy_id} tick={tick} decisionKey={decisionKey} />
    </section>
  );
}

function SetupDetails({ setupId, mode, strategyId, tick, decisionKey }: { setupId: string | null; mode: string; strategyId: string | null; tick: number; decisionKey: string }) {
  const { s } = useStore();
  const [d, setD] = useState<any>(null);
  const [miss, setMiss] = useState<string | null>(null);
  const settingsVer = s.prefs?.settings_version;
  useEffect(() => {
    if (!setupId) { setD(null); return; }
    apiGet(`/api/v1/setups/${encodeURIComponent(setupId)}/details`).then((r) => { setD(r); setMiss(null); }).catch(() => { setD(null); setMiss(setupId); });
  }, [setupId, tick, decisionKey, settingsVer]);
  if (!setupId || !d || d.setup_id !== setupId) {
    const why: string[] = (s.auto?.why_no_setup ?? []).filter((w: string) => !strategyId || w.startsWith(strategyId) || !/^S\d\d/.test(w)).slice(0, 6);
    return (
      <div className="setup-details empty" data-testid="setup-details">
        <h4>Szczegóły setupu</h4>
        <p className="muted">{miss ? "Scenariusz nie istnieje (wygasł lub zmieniono rachunek)." : mode === "ALL" ? "Wybierz scenariusz z listy (przycisk „Szczegóły”)." :
          mode === "SELECTED" ? `Brak aktywnego scenariusza strategii ${strategyId} – nic nie jest wymuszane.` : "Silnik nie wybrał teraz żadnego setupu."}</p>
        {why.length > 0 && <ul className="small muted">{why.map((w) => <li key={w}>{w}</li>)}</ul>}
      </div>);
  }
  const dig = s.decision?.signal_view?.digits ?? 2;
  const px = (v: any) => (v == null ? "—" : fmtNum(v, dig));
  const z = d.sizing || {};
  const lv = d.leverage || {};
  const cur = z.currency ?? "";
  return (
    <div className="setup-details" data-testid="setup-details" data-setup={d.setup_id}>
      <div className="sd-head">
        <h4>Szczegóły setupu</h4>
        <b>{d.strategy_id} {d.strategy_name}</b><span>{d.symbol}</span>
        <span className={cls("badge", d.direction === "BUY" ? "ok" : "bad")} title={d.direction_note} data-testid="sd-direction">
          {d.direction} – kierunek scenariusza</span>
        <span className="badge" title="interwały używane przez strategię">{d.timeframe} · {(d.timeframes_used || []).join(", ")}</span>
        {d.engine_selected && <span className="badge ok">wybrany przez silnik</span>}
      </div>
      <div className="sd-status">
        <div><label>Status scenariusza</label><b className={cls("st", SCEN_TONE[d.scenario_status])} data-testid="sd-scenario">{d.scenario_status_pl}</b>
          {d.terminal_reason && <small> – {d.terminal_reason}</small>}</div>
        <div><label>Możliwość wejścia</label><b className={cls("st", d.entry.status === "DOSTĘPNE" ? "ok" : "bad")} data-testid="sd-entry">{d.entry.status}</b>
          {d.entry.reasons.length > 0 && <small> – {d.entry.reasons.join("; ")}</small>}
          <small className="muted"> · tryb wykonania: {d.entry.execution_mode}</small></div>
      </div>
      <p className="sd-why"><b>Kontekst:</b> reżim {d.context.regime ?? "—"}{d.context.countertrend ? " (scenariusz przeciw trendowi)" : ""}. {d.context.rationale}</p>

      <details open className="sd-sec"><summary>Checklista warunków wejścia</summary>
        <table className="tbl" data-testid="sd-checklist">
          <thead><tr><th></th><th>Warunek</th><th>Wymagany próg</th><th>Aktualna wartość</th><th>Status</th><th>Powód</th></tr></thead>
          <tbody>{d.checklist.map((c: any, i: number) => (
            <tr key={i} className={"ck-" + (c.status || "").replace(/\s/g, "_")}>
              <td aria-label={c.status}>{CK_ICON[c.status] ?? "?"}</td><td>{c.name}</td><td>{c.threshold}</td><td>{c.value}</td><td>{c.status}</td><td>{c.reason ?? ""}</td>
            </tr>))}</tbody>
        </table>
      </details>

      <details open className="sd-sec"><summary>Poziomy i R</summary>
        <div className="sd-grid">
          <div><label>Strefa wejścia</label><b>{d.levels.entry_zone ? `${px(d.levels.entry_zone[0])} – ${px(d.levels.entry_zone[1])}` : "—"}</b></div>
          <div><label>Trigger</label><b>{d.levels.trigger ?? "—"}</b><small>{d.levels.trigger_level != null ? `poziom ${px(d.levels.trigger_level)}` : ""}</small></div>
          <div><label title="planowane wejście z bieżącej ceny (Ask/Bid) albo hipotetycznie na poziomie wyzwalacza">Planowane wejście</label><b>{px(d.levels.planned_entry)}</b>
            <small>{d.levels.entry_basis === "LIVE_QUOTE" ? "bieżąca cena" : d.levels.entry_basis ? "hipotetycznie – poziom wyzwalacza" : ""}</small></div>
          <div><label title="SL – stop loss (techniczny poziom strategii; nie zależy od dźwigni)">SL</label><b>{px(d.levels.stop_loss)}</b></div>
          <div><label title="TP – take profit">TP</label><b>{(d.levels.targets || []).map(px).join(" / ") || "—"}</b></div>
          <div><label>Unieważnienie</label><b>{d.levels.invalidation_rule}</b></div>
          <div><label title="R = zysk / ryzyko">R brutto / po kosztach</label><b>{d.rr.gross != null ? fmtNum(d.rr.gross, 2) : "—"} / {d.rr.net != null ? fmtNum(d.rr.net, 2) : "—"}</b><small>{d.rr.note}{d.rr.net_complete === false ? " (koszty niepełne)" : ""}</small></div>
          <div><label>Ważny do</label><b>{fmtTime(d.levels.expires_at, true)}</b></div>
        </div>
      </details>

      <details open className="sd-sec"><summary>Wielkość pozycji, margin i dźwignia</summary>
        <div className="sd-grid">
          <div><label>Proponowany wolumen</label><b data-testid="sd-lots">{z.lots ? `${z.lots} lot` : "—"}</b>
            <small>{z.lots ? `ogranicza: ${BIND_PL[z.binding_constraint] ?? z.binding_constraint ?? "—"}` : (z.reasons_pl || []).slice(0, 3).join("; ")}</small></div>
          <div><label title="szacunek: kalkulator brokera + prowizja + stres poślizgu; luki i poślizg mogą dać większą stratę">Szacowana strata przy SL</label>
            <b>{z.estimated_loss_at_sl != null ? `${fmtNum(z.estimated_loss_at_sl)} ${cur}` : "—"}</b><small>szacunek – nie gwarantowane maksimum</small></div>
          <div><label>Wynik przy TP (po kosztach)</label><b>{z.estimated_result_at_tp != null ? `${fmtNum(z.estimated_result_at_tp)} ${cur}` : "—"}</b></div>
          <div><label title="order_calc_margin dla tego wolumenu">Wymagany margin</label><b>{z.margin_required != null ? `${fmtNum(z.margin_required)} ${cur}` : "—"}</b></div>
          <div><label>Wolny margin teraz → po wejściu</label><b>{z.free_margin != null ? fmtNum(z.free_margin) : "—"} → {z.free_margin_after != null ? fmtNum(z.free_margin_after) : "—"} {cur}</b>
            <small>{z.pending_margin ? `zlecenia oczekujące rezerwują ${fmtNum(z.pending_margin)}` : ""}</small></div>
          <div><label>Budżet ryzyka (dostępny)</label><b>{z.budget != null ? `${fmtNum(z.budget)} (${fmtNum(z.available_budget)})` : "—"} {cur}</b>
            <small>otwarte ryzyko {z.open_risk != null ? fmtNum(z.open_risk) : "—"}</small></div>
          <div><label>Dźwignia rachunku (MT5)</label><b data-testid="sd-acc-lev">{lv.account_leverage ? `1:${lv.account_leverage}` : "—"}</b>
            <small>{lv.instrument_margin_leverage ? `dla tego instrumentu wg marginu brokera ≈ 1:${lv.instrument_margin_leverage}` : ""}</small></div>
          <div><label>Limit wybrany przez Ciebie</label><b data-testid="sd-user-lev">{lv.user_limit ? `1:${lv.user_limit}` : "AUTO"}</b><small>{lv.note}</small></div>
          <div><label title="wartość nominalna pozycji w walucie rachunku / equity">Efektywna ekspozycja</label>
            <b data-testid="sd-exposure">{lv.effective_exposure_position != null ? `${lv.effective_exposure_position}× (łącznie ${lv.effective_exposure_total ?? "—"}×)` : "—"}</b>
            <small>{lv.position_notional != null ? `nominał ${fmtNum(lv.position_notional)} ${cur}` : lv.missing_reason ?? ""}</small></div>
        </div>
        {z.max_lots_by && <p className="small muted">Maks. wolumen wg limitów: {Object.entries(z.max_lots_by).map(([k, v]: any) => `${BIND_PL[k] ?? k} ${fmtNum(v, 3)}`).join(" · ")} (zaokrąglenie w dół do kroku, ponowna weryfikacja kalkulatorem brokera)</p>}
      </details>

      <details className="sd-sec"><summary>Interwały strategii – zgodność / konflikt</summary>
        <div className="tfo-grid">{(d.timeframes || []).map((t: any) => (
          <div key={t.tf} className={cls("tfo", t.agreement === "KONFLIKT" && "conflict")}>
            <b>{t.tf}</b><span className={cls("badge", AGREE_TONE[t.agreement])}>{t.agreement}</span>
            <small>{t.direction === "UP" ? "↑ wzrost" : t.direction === "DOWN" ? "↓ spadek" : t.direction === "FLAT" ? "→ płasko" : "brak danych"} · {t.role}</small>
            <small>zamkn.: {t.last_closed_utc ? fmtTime(t.last_closed_utc) : "—"}{t.forming ? " · tworzy się nowa" : ""}</small>
            {t.conflict_impact && <small className="warn">{t.conflict_impact}</small>}
          </div>))}</div>
      </details>

      <details className="sd-sec"><summary>Wynik, historia i czas</summary>
        <p className="small"><b>Wynik ACTIVE:</b> {d.score.value ?? "—"} – {d.score.meaning}</p>
        <p className="small"><b>Historia strategii:</b> {d.history.trades ? `${d.history.trades} transakcji (${fmtTime(d.history.period_from, true)} – ${fmtTime(d.history.period_to, true)}), winrate netto ${d.history.stats?.win_rate ?? "—"}%, PF ${d.history.stats?.profit_factor ?? "—"}, E[R] ${d.history.stats?.expectancy_r ?? "—"}` : d.history.note}</p>
        <p className="small muted">Powstał {fmtTime(d.times.created_at, true)} (wiek {age(d.times.age_seconds)}) · ostatnia aktualizacja {fmtTime(d.times.updated_at, true)} ({age(d.times.since_update_seconds)} temu) ·
          źródło {d.times.data_source} · id {d.setup_id} · wersja ustawień {z.settings_version ?? "—"}</p>
      </details>
    </div>
  );
}

/** Settings → Ryzyko: "Dźwignia / limit ekspozycji". A planning / exposure limit of the bot - not a broker setting. */
export function LeverageSettings() {
  const { s } = useStore();
  const [p, setP] = useState<any>(null);
  const [mode, setMode] = useState<"AUTO" | "MANUAL">("AUTO");
  const [limit, setLimit] = useState<number>(30);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => apiGet("/api/v1/prefs").then((r) => { setP(r); setMode(r.leverage.mode); if (r.leverage.limit) setLimit(r.leverage.limit); }).catch(() => undefined);
  useEffect(() => { load(); }, [s.account?.login, s.prefs?.settings_version]);
  const acc = p?.exposure?.account_leverage;
  const save = () => apiSend("POST", "/api/v1/prefs/leverage", mode === "AUTO" ? { mode } : { mode, limit: Number(limit) })
    .then((r: any) => { setP(r); setMsg("Zapisano. Dotyczy przyszłych decyzji; otwarte pozycje i zlecenia bez zmian."); })
    .catch((e: any) => setMsg(String(e.message || e).replace(/LEVERAGE_LIMIT_ABOVE_ACCOUNT_1_(\d+)/, "Limit wyższy niż dźwignia rachunku 1:$1")));
  return (
    <div className="lev-settings" data-testid="leverage-settings">
      <h4>Dźwignia / limit ekspozycji</h4>
      <div className="lev-values">
        <div><label>Dźwignia rachunku (odczyt MT5)</label><b data-testid="lev-account">{acc ? `1:${acc}` : "brak danych"}</b></div>
        <div><label>Limit wybrany w bocie</label><b data-testid="lev-user">{p?.leverage?.mode === "MANUAL" ? `1:${p.leverage.limit}` : "AUTO (= dźwignia rachunku)"}</b></div>
        <div><label>Limit stosowany do wyliczeń</label><b>{p?.exposure?.limit ? `1:${p.exposure.limit}` : "— (tylko margin brokera)"}</b></div>
      </div>
      <div className="row">
        <label><input type="radio" checked={mode === "AUTO"} onChange={() => setMode("AUTO")} /> AUTO – parametry aktualnego rachunku MT5</label>
        <label><input type="radio" checked={mode === "MANUAL"} onChange={() => setMode("MANUAL")} /> RĘCZNIE</label>
        {mode === "MANUAL" && <select value={limit} data-testid="lev-select" onChange={(e) => setLimit(Number(e.target.value))}>
          {(p?.leverage_choices ?? [1, 10, 20, 30, 50, 100]).filter((x: number) => !acc || x <= acc).map((x: number) => <option key={x} value={x}>1:{x}</option>)}
        </select>}
        <button className="btn" data-testid="lev-save" onClick={save}>Zapisz limit</button>
      </div>
      {msg && <p className="small" data-testid="lev-msg">{msg}</p>}
      <p className="note small">Ręczny wybór to limit planowania i ekspozycji bota (nominał pozycji / equity) – <b>nie zmienia dźwigni u brokera</b>.
        Wymagany margin zawsze liczy kalkulator brokera dla konkretnego instrumentu (order_calc_margin). Wyższa dźwignia nie zwiększa procentowego
        budżetu ryzyka i nie przesuwa SL/TP. Ustawienie zapisuje się dla rachunku {p?.account_key ?? "—"}.</p>
    </div>
  );
}
