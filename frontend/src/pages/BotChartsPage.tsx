// Page 2 "Wykresy bota": every TF the engine uses, built from the backend TF registry (/api/v1/timeframes) - roles and
// "used by" come from the backend, never from a hard-coded list. Views: all / context / setup & entry / focus on one
// chart. "Pokaż na wykresie" from page 3 arrives as #/wykresy?tf=..&price=..&label=..&setup=.. (presentation only).
import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { AutoPanel, StrategiesPanel, useAutoFull } from "../components/AutoPanels";
import ChartPanel, { type Highlight } from "../components/ChartPanel";
import ChartToolbar, { useChartOpts } from "../components/ChartToolbar";
import { BotSignalsPanel, MarketDetail, MarketsPanel } from "../components/MarketsPanel";
import VolPanel from "../components/VolPanel";
import CandleForecastPanel from "../components/CandleForecastPanel";
import ScalpPanel from "../components/ScalpPanel";
import { navigate, usePersisted, type Route } from "../router";
import { useStore } from "../store";
import { cls } from "../util";
import Section from "../components/Section";

type TfRow = { tf: string; seconds: number; role: string; core: boolean; data: string | null; closed_bars: number | null; required: number | null; used_by: string[] };
type View = "all" | "context" | "setup" | "focus";
export const ROLE_PL: Record<string, string> = { TRIGGER: "potwierdzenie / trigger", SETUP: "setup", SETUP_CONTEXT: "kontekst setupu", LOCAL_CONTEXT: "kontekst lokalny",
  HTF: "wyższy kontekst", TREND_REGIME_CONTEXT: "kontekst trendu / reżimu", BACKGROUND: "tło rynku" };
const CONTEXT_ROLES = new Set(["BACKGROUND", "TREND_REGIME_CONTEXT", "HTF", "LOCAL_CONTEXT"]);
const VIEWS: [View, string][] = [["all", "Wszystkie"], ["context", "Kontekst"], ["setup", "Setup i wejście"], ["focus", "Skupienie na wykresie"]];

export function useTimeframes() {
  const { s } = useStore();
  const [r, setR] = useState<{ timeframes: TfRow[]; strategies: Record<string, any> } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const dqKey = s.decision?.data_quality;
  useEffect(() => {
    apiGet("/api/v1/timeframes").then((x) => { setR(x); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  }, [dqKey, s.account?.login]);
  return { r, err };
}

export default function BotChartsPage({ route }: { route: Route }) {
  const { s } = useStore();
  const { r, err } = useTimeframes();
  const [view, setView] = usePersisted<View>("bot.view", "all", (x) => VIEWS.some(([v]) => v === x));
  const [cols, setCols] = usePersisted<number>("bot.cols", 2, (x) => [1, 2, 3].includes(x));
  const [focusTf, setFocusTf] = usePersisted<string>("bot.focus", "M5", (x) => typeof x === "string");
  const [opts, setOpt] = useChartOpts("bot", { showRsi: true, showMacd: true, showStructure: true, showZones: true, showVol: true, showPatterns: false, showAiLevels: false }, "chartopts.v2");
  const [full, setFull] = useState<string | null>(null);
  const [market, setMarket] = useState<string | null>(null);
  const [autoFull, reloadAuto] = useAutoFull();
  // presentation params from page 3 ("Pokaż na wykresie")
  const pTf = route.params.get("tf");
  const pPrice = route.params.get("price");
  const highlight: Highlight = pPrice != null && !isNaN(Number(pPrice)) ? { price: Number(pPrice), label: route.params.get("label") || "poziom setupu" } : null;
  const pSetup = route.params.get("setup");
  useEffect(() => {
    if (pTf) { setFocusTf(pTf); setView("focus"); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pTf]);
  const tfs: TfRow[] = r?.timeframes ?? [];
  // TFs needed by the strategy of the setup being looked at (from page 3) or by the engine's selected strategy
  const sid = route.params.get("sid") || s.auto?.selected_strategy_id || null;
  const need = sid && r?.strategies?.[sid] ? new Set<string>([...(r.strategies[sid].setup_tfs || []), ...(r.strategies[sid].required_tfs || []),
    ...(r.strategies[sid].context_tf ? [r.strategies[sid].context_tf] : [])]) : null;
  const ordered = [...tfs].sort((a, b) => b.seconds - a.seconds);            // D1 → M1
  const shown = view === "focus" ? ordered.filter((t) => t.tf === focusTf) : view === "context" ? ordered.filter((t) => CONTEXT_ROLES.has(t.role))
    : view === "setup" ? ordered.filter((t) => !CONTEXT_ROLES.has(t.role)) : ordered;
  const missingNeeded = need ? ordered.filter((t) => need.has(t.tf) && t.data !== "OK") : [];
  const clearParams = () => navigate("wykresy", { replace: true });
  return (
    <div className="bot-page" data-testid="page-bot">
      <div className="page-head">
        <h1>Wykresy bota</h1>
        <div className="tabs small" role="group" aria-label="Widok">
          {VIEWS.map(([v, l]) => <button key={v} className={cls(view === v && "on")} aria-pressed={view === v} data-view={v} onClick={() => setView(v)}>{l}</button>)}
        </div>
        {view !== "focus" && (
          <div className="tabs small" role="group" aria-label="Liczba kolumn">
            {[1, 2, 3].map((c) => <button key={c} className={cls(cols === c && "on", c === 3 && "wide-only")} aria-pressed={cols === c} data-cols={c} onClick={() => setCols(c)}>{c} kol.</button>)}
          </div>)}
        <ChartToolbar opts={opts} set={setOpt} show={["showPatterns", "showStructure", "showZones", "showVol", "showRsi", "showMacd", "syncCrosshair"]} />
      </div>
      <div className="tf-bar" role="navigation" aria-label="Interwały" data-testid="tf-bar">
        {ordered.map((t) => (
          <button key={t.tf} className={cls("tf-chip", need?.has(t.tf) && "need", t.data && t.data !== "OK" && "nodata", view === "focus" && focusTf === t.tf && "on")}
            data-tf={t.tf} onClick={() => { setFocusTf(t.tf); setView("focus"); }} title={`${ROLE_PL[t.role] ?? t.role} · dane: ${t.data ?? "?"} · używany przez: ${t.used_by.join(", ") || "—"}`}>
            <b>{t.tf}</b><small>{ROLE_PL[t.role] ?? t.role}</small><small>{t.data === "OK" ? "dane OK" : t.data ?? "?"}{need?.has(t.tf) ? " · wymagany" : ""}</small>
          </button>))}
        {err && <span className="bad small">Rejestr TF niedostępny: {err}</span>}
      </div>
      {need && (
        <p className={cls("small need-note", missingNeeded.length ? "warn" : "")} data-testid="need-note">
          Interwały wymagane przez {sid}{pSetup ? " (setup oglądany na stronie Warunki)" : " (strategia wybrana przez silnik)"}: {[...need].join(", ")} –{" "}
          {missingNeeded.length ? `niekompletne dane: ${missingNeeded.map((t) => `${t.tf} (${t.data ?? "?"})`).join(", ")}` : "dane kompletne"}.
        </p>)}
      {highlight && <p className="small hl-note">Zaznaczono: <b>{highlight.label}</b> na {pTf}. <button className="link" onClick={clearParams}>Usuń zaznaczenie</button></p>}
      <div className={cls("bot-layout", view === "focus" && "focus")}>
        <div className={cls("bot-grid", "cols-" + (view === "focus" ? 1 : cols))} data-testid="bot-grid">
          {shown.map((t) => (
            <ChartPanel key={t.tf} tf={t.tf} index={0} chartId={`bot-${t.tf}`} opts={opts} variant={view === "focus" ? "main" : "normal"} roleText={ROLE_PL[t.role] ?? t.role}
              needed={need ? need.has(t.tf) : null} highlight={pTf === t.tf ? highlight : null}
              fullscreen={full === t.tf} onFullscreen={() => setFull(full === t.tf ? null : t.tf)} />
          ))}
          {!tfs.length && !err && <p className="muted">Ładowanie rejestru interwałów…</p>}
        </div>
        {view === "focus" && (
          <aside className="tf-list" aria-label="Pozostałe interwały" data-testid="focus-list">
            <h4>Pozostałe interwały</h4>
            <ul>{ordered.filter((t) => t.tf !== focusTf).map((t) => (
              <li key={t.tf}><button className="link" onClick={() => setFocusTf(t.tf)}><b>{t.tf}</b> {ROLE_PL[t.role] ?? t.role}</button>
                <span className={cls("badge", t.data === "OK" ? "ok" : "warn")}>{t.data ?? "?"}</span>{need?.has(t.tf) && <span className="badge">wymagany</span>}</li>))}</ul>
          </aside>)}
      </div>
      <Section id="bot.scalp" title="Scalp M5 Range → M1 Sweep → Retest + hedge (SHADOW – bez zleceń)" defaultOpen testid="sec-scalp"><ScalpPanel /></Section>
      <Section id="bot.forecast" title="Świece i prognozy 5/15/30 min (SHADOW – bez zgody na zlecenia)" defaultOpen testid="sec-forecast"><CandleForecastPanel /></Section>
      <Section id="bot.vol" title="Zmienność i walls (źródło: HV_PROXY / IV)" testid="sec-vol"><VolPanel /></Section>
      <Section id="bot.regime" title="Reżim rynku i stan AUTO" testid="sec-regime"><AutoPanel full={autoFull} /></Section>
      <Section id="bot.strategies" title="Monitor strategii (S01–S12)" testid="sec-strategies"><StrategiesPanel full={autoFull} reload={() => reloadAuto()} /></Section>
      <Section id="bot.markets" title="Inne rynki i sygnały bota (podgląd – nie zmienia symbolu silnika)" testid="sec-markets">
        <div className="markets-row"><MarketsPanel onOpen={setMarket} /><BotSignalsPanel onOpen={setMarket} /></div>
      </Section>
      <Section id="bot.dq" title="Jakość danych per interwał" testid="sec-dq">
        <div className="table-wrap"><table className="tbl" data-testid="dq-table">
          <thead><tr><th>TF</th><th>Rola (rejestr)</th><th>Dane</th><th>Zamknięte świece / wymagane</th><th>Używany przez</th></tr></thead>
          <tbody>{ordered.map((t) => <tr key={t.tf}><td>{t.tf}</td><td>{ROLE_PL[t.role] ?? t.role}</td><td>{t.data ?? "brak oceny"}</td>
            <td>{t.closed_bars ?? "—"} / {t.required ?? "—"}</td><td>{t.used_by.join(", ") || "—"}</td></tr>)}</tbody>
        </table></div>
        <p className="small muted">Wolumen na wykresach to tick volume z MT5 (liczba zmian ceny), nie wolumen giełdowy.</p>
      </Section>
      {market && <MarketDetail symbol={market} onClose={() => setMarket(null)} />}
    </div>
  );
}
