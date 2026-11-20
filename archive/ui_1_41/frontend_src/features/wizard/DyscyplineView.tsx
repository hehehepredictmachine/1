// Dyscypline – setups, signals and entry conditions from the engine S01–S12, SCALPING / HEDGING and the bot's signals. A setup is
// opened in the details panel with its chart; the selection lives in the URL (?setup=…) so refresh and Back keep it. Read-only: this
// view never sends an order - manual actions stay in the existing plan views behind their own confirmation and the backend's gates.
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { apiGet } from "../../api";
import ChartPanel from "../../components/ChartPanel";
import { useChartOpts } from "../../components/ChartToolbar";
import { href, navigate, type Route } from "../../router";
import { useStore } from "../../store";
import { telemetry } from "../../telemetry";
import { cls, fmtNum, fmtTime } from "../../util";
import { botSignals, engineSetups, shSetups, UI_STATE_PL, type SetupItem, type UiState } from "./setups";
import ViewHeader from "./ViewHeader";

const TONE: Record<UiState, string> = { OBSERWACJA: "muted", FORMUJE_SIE: "info", GOTOWY: "warn", AKTYWNY: "ok", UNIEWAZNIONY: "bad", WYGASLY: "muted", ZAKONCZONY: "muted" };
type StateFilter = "all" | UiState;

function useSh(): any {
  const [sh, setSh] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    apiGet("/api/v1/sh").then((x: any) => { if (alive) setSh(x); }).catch(() => undefined);
    const off = telemetry.subscribe((e) => { if (e.type === "sh" && e.data) setSh((p: any) => ({ ...(p || {}), ...e.data })); });   // same single WebSocket
    return () => { alive = false; off(); };
  }, []);
  return sh;
}

const SNAP = "mq.wz.setup.";
function saveSnap(x: SetupItem) {
  try { sessionStorage.setItem(SNAP + x.key, JSON.stringify({ ...x, raw: null })); } catch { /* storage unavailable - only the live list */ }
}
function loadSnap(key: string): SetupItem | null {
  try { const v = sessionStorage.getItem(SNAP + key); return v ? (JSON.parse(v) as SetupItem) : null; } catch { return null; }
}

function age(t: string | number | null): string {
  if (t == null) return "—";
  const ms = typeof t === "number" ? t : Date.parse(t);
  if (!Number.isFinite(ms)) return "—";
  const d = Math.round((Date.now() - ms) / 1000), s = Math.abs(d);
  const span = s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;
  return `${fmtTime(new Date(ms).toISOString(), true)} (${d >= 0 ? `${span} temu` : `za ${span}`})`;
}

export default function DyscyplineView({ route }: { route: Route }) {
  const { s } = useStore();
  const sh = useSh();
  const [stateF, setStateF] = useState<StateFilter>("all");
  const [srcF, setSrcF] = useState<string>("all");
  const [opts] = useChartOpts("wz-dys", { showAiLevels: true, showZoneMap: true });
  const items = useMemo(() => [...engineSetups(s), ...shSetups(sh), ...botSignals(s)], [s.decision, s.auto, s.bot_signals, s.symbol, sh]);   // eslint-disable-line react-hooks/exhaustive-deps
  const selKey = route.params.get("setup");
  const live = items.find((x) => x.key === selKey) ?? null;
  // setups come and go with every evaluation: the selected one keeps its last known state (also across a refresh) and is marked
  // as no longer reported instead of silently disappearing
  const remembered = useMemo(() => (live || !selKey ? null : loadSnap(selKey)), [live, selKey]);
  useEffect(() => { if (live) saveSnap(live); }, [live]);
  const sel = live ?? remembered;
  const shown = items.filter((x) => (stateF === "all" || x.state === stateF) && (srcF === "all" || x.source === srcF));
  const pick = (k: string | null) => navigate("dyscypline", { params: { setup: k } });
  const activeSymbol = s.symbol?.symbol;
  const mode = s.mode || {};
  return (
    <div className="wz-view wz-dyscypline" data-testid="page-dyscypline">
      <ViewHeader tower="dyscypline" />
      <section className="wz-panel wz-risk-strip" aria-label="Kontrola ryzyka" data-testid="wz-risk">
        <span>Tryb: <b>{mode.mode ?? "—"}</b></span>
        <span className={cls(mode.kill_switch && "wz-bad")}>Nowe wejścia: <b>{mode.mode ? (mode.kill_switch ? "STOP" : "aktywne") : "—"}</b></span>
        <span>Ścieżka główna: <b>{mode.primary_path_label ?? mode.primary_path ?? "—"}</b></span>
        <span>Execution Lock: <b>wycofany w 1.24 (Twoja decyzja)</b> – zlecenia chronią tryb, STOP, limity ryzyka i bramki backendu</span>
        <a className="wz-link" href={href("system-control")}>Centrum sterowania →</a>
      </section>
      <div className="wz-view-grid wz-dys-grid">
        <section className="wz-panel" aria-label="Setupy i sygnały">
          <div className="wz-filters" role="group" aria-label="Filtr stanu">
            {(["all", "AKTYWNY", "GOTOWY", "FORMUJE_SIE", "OBSERWACJA", "UNIEWAZNIONY", "WYGASLY", "ZAKONCZONY"] as StateFilter[]).map((f) => (
              <button key={f} className={cls("wz-mini", stateF === f && "on")} aria-pressed={stateF === f} onClick={() => setStateF(f)}>
                {f === "all" ? "Wszystkie" : UI_STATE_PL[f as UiState]} <span className="wz-dim">{f === "all" ? items.length : items.filter((x) => x.state === f).length}</span></button>))}
          </div>
          <div className="wz-filters" role="group" aria-label="Filtr źródła">
            {["all", "SILNIK", "SCALPING", "HEDGING", "SYGNAŁ"].map((f) => (
              <button key={f} className={cls("wz-mini", srcF === f && "on")} aria-pressed={srcF === f} onClick={() => setSrcF(f)}>
                {f === "all" ? "Wszystkie źródła" : f === "SILNIK" ? "Silnik S01–S12" : f === "SYGNAŁ" ? "Sygnały bota" : f}</button>))}
          </div>
          {shown.length === 0 ? <p className="wz-dim" data-testid="wz-setups-empty">Brak setupów w wybranym filtrze – bot nie raportuje teraz takich setupów.</p> : (
            <ul className="wz-setups" data-testid="wz-setups">
              {shown.map((x) => (
                <li key={x.key}>
                  <button className={cls("wz-setup", sel?.key === x.key && "on")} onClick={() => pick(x.key)} data-testid="wz-setup" data-state={x.state} data-source={x.source}>
                    <span className={cls("wz-side-tag", x.side === "BUY" && "buy", x.side === "SELL" && "sell")}>{x.side ?? "—"}</span>
                    <span className="wz-setup-main"><b>{x.strategy}</b><small>{x.source === "SYGNAŁ" ? "sygnał bota" : x.source === "SILNIK" ? "silnik S01–S12" : x.source} · {x.instrument} · {x.tf ?? "—"}</small></span>
                    <span className={cls("wz-state", TONE[x.state])}>{UI_STATE_PL[x.state]}</span>
                    <span className="wz-dim wz-score" title="Ocena setupu – heurystyka 0–100, nie prawdopodobieństwo">{x.score != null ? `ocena ${fmtNum(x.score, 0)}` : ""}</span>
                  </button>
                </li>))}
            </ul>)}
        </section>
        <section className="wz-panel wz-setup-detail" aria-label="Szczegóły setupu" data-testid="wz-setup-detail">
          {!sel ? (selKey
            ? <p className="wz-dim" data-testid="wz-setup-gone">Setup {selKey} nie jest już raportowany przez bota (zniknął z bieżącej oceny albo wygasł). <button className="wz-mini" onClick={() => pick(null)}>Zamknij</button></p>
            : <p className="wz-dim">Wybierz setup z listy, aby zobaczyć warunki, trigger, unieważnienie, poziomy, uzasadnienie i wykres.</p>) : (<>
            {!live && <p className="wz-strip warn wz-stale-note" role="status" data-testid="wz-setup-stale">Ten setup nie jest już raportowany w bieżącej ocenie – poniżej ostatni znany stan (nieaktualny).</p>}
            <SetupDetail x={sel} opts={opts} chartOk={!activeSymbol || sel.instrument === activeSymbol || sel.source !== "SYGNAŁ"} onClose={() => pick(null)} /></>)}
        </section>
      </div>
    </div>);
}

function SetupDetail({ x, opts, chartOk, onClose }: { x: SetupItem; opts: any; chartOk: boolean; onClose: () => void }) {
  const lv = (v: number | string | null) => (v == null ? "—" : typeof v === "number" ? fmtNum(v, 2) : v);
  return (
    <div style={{ "--tw": x.side === "SELL" ? "#ff6b8b" : "#2fe6a0" } as CSSProperties}>
      <header className="wz-detail-head">
        <div><h2>{x.strategy} <span className={cls("wz-side-tag", x.side === "BUY" && "buy", x.side === "SELL" && "sell")}>{x.side ?? "brak kierunku"}</span></h2>
          <p className="wz-dim">{x.instrument} · {x.tf ?? "—"} · stan: <b>{UI_STATE_PL[x.state]}</b> ({x.stateRaw})</p></div>
        <button className="wz-mini" onClick={onClose} aria-label="Zamknij szczegóły">✕</button>
      </header>
      <dl className="wz-kv wz-kv-2">
        <dt>Powstał</dt><dd>{age(x.createdAt)}</dd>
        <dt>Ważny do</dt><dd>{x.validUntil ? age(x.validUntil) : "—"}</dd>
        <dt>Wejście</dt><dd>{lv(x.entry)}</dd>
        <dt>SL</dt><dd>{lv(x.sl)}</dd>
        <dt>TP</dt><dd>{x.tps.length ? x.tps.map((t) => fmtNum(t, 2)).join(" / ") : "—"}</dd>
        <dt>Trigger</dt><dd>{x.trigger ?? "—"}</dd>
        <dt>Unieważnienie</dt><dd>{x.invalidation ?? "—"}</dd>
        <dt>Ocena setupu</dt><dd>{x.score != null ? `${fmtNum(x.score, 1)} / 100 – heurystyka, nie prawdopodobieństwo` : "—"}</dd>
        <dt>Prawdopodobieństwo</dt><dd>{x.probability ? `${fmtNum(x.probability.value * 100, 1)} % – ${x.probability.event} (skalibrowane)` : "brak skalibrowanego modelu – nie pokazuję"}</dd>
      </dl>
      <div className="wz-cols">
        <div>
          <h3>Warunki</h3>
          {x.conditions.length === 0 ? <p className="wz-dim">Backend nie podał listy warunków dla tego źródła.</p> : (
            <ul className="wz-conds" data-testid="wz-conds">
              {x.conditions.map((c, i) => (
                <li key={i} className={c.ok === true ? "ok" : c.ok === false ? "bad" : "muted"}>
                  <i aria-hidden="true">{c.ok === true ? "✓" : c.ok === false ? "✕" : "…"}</i>
                  <span><b>{c.label}</b>{c.detail ? <small> {c.detail}</small> : null}</span>
                  <span className="wz-sr">{c.ok === true ? "spełniony" : c.ok === false ? "niespełniony" : "w toku"}</span></li>))}
            </ul>)}
        </div>
        <div>
          <h3>Uzasadnienie i potwierdzenia</h3>
          {x.reasons.length ? <ul className="wz-list">{x.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="wz-dim">—</p>}
          <h3>Przeciw / brakujące</h3>
          {x.against.length ? <ul className="wz-list">{x.against.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="wz-dim">—</p>}
          <h3>Sprzeczności między modelami</h3>
          {x.conflicts.length ? <ul className="wz-list wz-bad">{x.conflicts.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="wz-dim">Brak zgłoszonych sprzeczności.</p>}
          <h3>Ryzyko</h3>
          <ul className="wz-list">{x.risk.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      </div>
      <div className="wz-detail-chart" data-testid="wz-setup-chart">
        {chartOk ? <ChartPanel tf={x.chartTf} index={0} chartId={`wz-dys-${x.chartTf}`} opts={opts} variant="compact" fullscreen={false} onFullscreen={() => undefined} />
          : <p className="wz-dim">Wykres jest dostępny dla aktywnego instrumentu bota – ten sygnał dotyczy {x.instrument}.</p>}
      </div>
      <p className="wz-note">Widok tylko do odczytu – żadne zlecenie nie jest stąd wysyłane. Ręczne akcje są w widokach planu (potwierdzenie + ponowna kontrola w backendzie):
        {" "}<a className="wz-link" href={href(x.source === "SILNIK" ? "warunki" : "strategie", x.source === "SILNIK" ? { setupId: x.key.startsWith("engine:") ? x.key.slice(7) : null } : {})}>pełny plan →</a></p>
    </div>);
}
