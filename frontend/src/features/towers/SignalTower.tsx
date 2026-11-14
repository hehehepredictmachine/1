// PEPE$SIGNAL V1.0 – Signal Intelligence Center (MASTERPROMPT #017). Layout of the approved reference: narrow tower | signal stream |
// wide analysis | models & metrics, signal table under the analysis. Every value comes from the bot:
//   signals   = signals.ts (bot-signals + engine scenarios + SH machines, dedup on stable ids)
//   details   = /api/v1/setups/{id}/details (checklist of the strategy definition, levels, R:R, MTF agreement) or /api/v1/sh/signals/{id}
//   chart     = SignalChart (/api/v1/markets/chart of the signal's own symbol + TF, scrolled to the moment of the signal)
//   models    = /api/v1/models/predictions of the signal's instrument (state, version, timestamp, direction, score semantics)
// Scores are heuristics / model outputs – never shown as a probability unless the model says it is calibrated. Opening the view sends
// no order and no state change: the only POST-free actions are selection, filters and navigation.
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { href, navigate, type Route } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { TFS, consensus, dt, fmt, hms, modelRows, rr, usePolled } from "./data";
import SignalChart from "./SignalChart";
import { conditions, mergeSignals, narrative, type Cond, type CondRow, type Lifecycle, type Sig } from "./signals";
import TowerFrame, { Card, Dir, Meter, Src } from "./TowerFrame";

type Tab = "center" | "live" | "strategies" | "ai" | "history" | "performance" | "builder";
const TABS: [Tab, string, string][] = [
  ["center", "SIGNAL INTELLIGENCE CENTER", "wszystkie sygnały i pełna analiza wybranego"], ["live", "LIVE SIGNALS", "tylko aktywne: kandydaci, potwierdzone, otwarte"],
  ["strategies", "ALL STRATEGIES", "przegląd wszystkich strategii bota"], ["ai", "AI EVALUATION", "wszystkie modele i ich stan dla wybranego instrumentu"],
  ["history", "SIGNAL HISTORY", "zakończone, unieważnione, wygasłe i odrzucone"], ["performance", "PERFORMANCE", "wyniki sygnałów bota w R (brutto)"],
  ["builder", "SETUP BUILDER", "otwiera istniejący widok setupu silnika"],
];
const LIVE: Lifecycle[] = ["CANDIDATE", "CONFIRMED", "FILLED", "WAIT"];
const HIST: Lifecycle[] = ["CLOSED", "EXPIRED", "INVALIDATED", "REJECTED"];
const RANGE: Record<string, number> = { "1h": 3600e3, "24h": 86400e3, "7d": 7 * 86400e3, all: Infinity };
const ROW_H = 92;
const ICON: Record<string, string> = { S01: "↗", S02: "≈", S03: "⇪", S04: "◫", S05: "◷", S06: "↻", S07: "⤺", S08: "⇆", S09: "⇋", S10: "∿", S11: "⟋", S12: "▥",
  SCALPING: "⚡", HEDGING: "⛨" };

export default function SignalTower({ route }: { route: Route }) {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const [tab, setTab] = useState<Tab>("center");
  const [paused, setPaused] = useState(false);
  const [f, setF] = useState({ strategy: "", symbol: "", tf: "", dir: "", status: "", range: "all", minStrength: 0, q: "", sort: "time" as "time" | "strength" });
  const bot = usePolled<any>(paused ? null : "/api/v1/bot-signals?limit=200", 8000);
  const setups = usePolled<any>(paused ? null : "/api/v1/setups", 10000);
  const sh = usePolled<any>(paused ? null : "/api/v1/sh/signals?limit=60", 15000);
  const frozen = useRef<{ bot: any; setups: any; sh: any }>({ bot: null, setups: null, sh: null });
  if (!paused) frozen.current = { bot: bot.d ?? frozen.current.bot, setups: setups.d ?? frozen.current.setups, sh: sh.d ?? frozen.current.sh };
  const all = useMemo(() => mergeSignals(frozen.current.bot?.items || [], frozen.current.setups?.items || [], frozen.current.sh?.items || []),
    [frozen.current.bot, frozen.current.setups, frozen.current.sh]);                       // eslint-disable-line react-hooks/exhaustive-deps
  const strategies = useMemo(() => [...new Set(all.map((x) => x.strategyId))].sort(), [all]);
  const symbols = useMemo(() => [...new Set(all.map((x) => x.symbol))].sort(), [all]);
  const list = useMemo(() => {
    const now = Date.now();
    const q = f.q.trim().toLowerCase();
    return all.filter((x) => (!f.strategy || x.strategyId === f.strategy) && (!f.symbol || x.symbol === f.symbol) && (!f.tf || x.tf === f.tf)
      && (!f.dir || x.direction === f.dir) && (!f.status || x.lifecycle === f.status) && (now - (Date.parse(x.updated || x.at || "") || 0) <= RANGE[f.range])
      && ((x.strength ?? 0) >= f.minStrength || (f.minStrength === 0)) && (!q || `${x.strategyId} ${x.strategyName} ${x.symbol} ${x.id}`.toLowerCase().includes(q))
      && (tab !== "live" || LIVE.includes(x.lifecycle)) && (tab !== "history" || HIST.includes(x.lifecycle)))
      .sort((a, b) => (f.sort === "strength" ? (b.strength ?? -1) - (a.strength ?? -1) : 0));
  }, [all, f, tab]);

  // ---- selection (stable id; competing updates never replace the user's choice)
  const urlId = route.params.get("id");
  const [selId, setSelId] = useState<string | null>(urlId);
  useEffect(() => { if (urlId) setSelId(urlId); }, [urlId]);
  const sel: Sig | null = all.find((x) => x.id === selId) ?? (selId ? null : list[0] ?? null);
  const pick = (x: Sig) => { setSelId(x.id); navigate("pepe-signal", { params: { id: x.id }, replace: true }); };
  const detId = sel?.setupId && (sel.kind === "SETUP" || sel.kind === "BOT") ? sel.setupId : null;
  const det = usePolled<any>(detId ? `/api/v1/setups/${encodeURIComponent(detId)}/details` : null, sel?.live ? 15000 : 0);
  const shDet = usePolled<any>(sel?.kind === "SH" ? `/api/v1/sh/signals/${encodeURIComponent(sel.id)}` : null, 0);
  const detOk = det.d && det.d.setup_id === detId ? det.d : null;                          // never show details of another selection
  const asset = useMemo(() => {
    const a = s.assets?.assets || {};
    return Object.keys(a).find((k) => a[k]?.broker_symbol === sel?.symbol) ?? null;
  }, [s.assets, sel?.symbol]);
  const preds = usePolled<any>(asset ? `/api/v1/models/predictions?instrument=${asset}` : null, 20000);
  const models = modelRows(preds.d?.items || []);
  const cons = consensus(models);
  const cond = conditions(sel, detOk, shDet.d);
  const story = narrative(sel, cond, detOk, cons);
  const levels = detOk?.levels;
  // SH levels: the stored plan of THIS signal (same backend numbers as the chart contract) - no second TP/SL solver in the browser
  const shp = sel?.kind === "SH" && shDet.d?.signal_id === sel.id ? shDet.d.payload : null;
  const shEntry = shp?.status === "READY" || shp?.pack?.analytical_state === "READY" ? (typeof shp?.entry_ref === "number" ? shp.entry_ref : null) : null;
  const entry = sel?.entry ?? shEntry ?? levels?.planned_entry ?? levels?.trigger_level ?? levels?.reference_price ?? null;
  const shSl: number | null = shEntry != null && typeof shp?.sl === "number" ? shp.sl : null;
  const sl = sel?.sl ?? shSl ?? levels?.stop_loss ?? null;
  const tps: number[] = sel?.targets?.length ? sel.targets : shEntry != null ? (shp?.tps || []).map((t: any) => t.price) : levels?.targets || [];
  const digits = sel?.symbol === s.symbol?.symbol ? s.symbol?.info?.digits ?? 2 : entry != null && Math.abs(entry) < 20 ? 5 : entry != null && Math.abs(entry) < 500 ? 3 : 2;
  // marker of a variant signal = the first bar on which the information was available (plan arrow), not the record's write time
  const sigView: Sig | null = sel ? { ...sel, entry, sl, targets: tps, at: shp?.pack?.arrow?.time ?? sel.at } : null;
  const rrTp = (i: number) => rr(sel?.scenarioDir, entry, sl, tps[i]);
  const mtfRows: any[] = detOk?.timeframes || [];
  const envK = ctx.env === "LIVE" ? "live" : ctx.env === "DEMO" || ctx.env === "SYNTHETIC" ? "demo" : "na";
  const envTxt = ctx.env === "SYNTHETIC" ? "DEMO·SIM" : ctx.env === "LIVE" ? "LIVE" : ctx.env === "DEMO" ? "DEMO" : "N/A";
  const historic = !!sel && !sel.live;

  // ---- signal wave on a NEW confirmed signal; invalidation alert of the selected one
  const known = useRef<Set<string> | null>(null);
  const [wave, setWave] = useState(0);
  useEffect(() => {
    const conf = all.filter((x) => x.lifecycle === "CONFIRMED" || x.lifecycle === "FILLED").map((x) => x.id);
    if (known.current && conf.some((id) => !known.current!.has(id))) setWave((n) => n + 1);
    known.current = new Set(conf);
  }, [all]);
  const prevLc = useRef<{ id: string | null; lc: string | null }>({ id: null, lc: null });
  const [alert, setAlert] = useState<string | null>(null);
  useEffect(() => {
    if (sel && prevLc.current.id === sel.id && prevLc.current.lc && prevLc.current.lc !== sel.lifecycle && (sel.lifecycle === "INVALIDATED" || sel.lifecycle === "EXPIRED"))
      setAlert(`${sel.strategyId} ${sel.symbol}: ${sel.lifecycle === "INVALIDATED" ? "UNIEWAŻNIONY" : "WYGASŁ"} (${hms(sel.updated)})`);
    prevLc.current = { id: sel?.id ?? null, lc: sel?.lifecycle ?? null };
  }, [sel?.id, sel?.lifecycle]);                                                            // eslint-disable-line react-hooks/exhaustive-deps

  // ---- table: sort + pagination
  const [ts, setTs] = useState<{ k: string; asc: boolean }>({ k: "time", asc: false });
  const [page, setPage] = useState(0);
  const [tableScope, setTableScope] = useState<"active" | "all">("active");
  const tableRows = useMemo(() => {
    const base = tableScope === "active" ? list.filter((x) => LIVE.includes(x.lifecycle) && x.lifecycle !== "WAIT") : list;
    const v = (x: Sig): any => ({ time: Date.parse(x.updated || x.at || "") || 0, strategy: x.strategyId, symbol: x.symbol, tf: TFS.indexOf(x.tf || ""), dir: x.direction,
      strength: x.strength ?? -1, entry: x.entry ?? -1, rr: x.rr ?? -1, status: x.lifecycle }[ts.k]);
    return [...base].sort((a, b) => (v(a) > v(b) ? 1 : v(a) < v(b) ? -1 : 0) * (ts.asc ? 1 : -1));
  }, [list, ts, tableScope]);
  const PER = 8;
  const pages = Math.max(1, Math.ceil(tableRows.length / PER));
  useEffect(() => { if (page >= pages) setPage(0); }, [pages, page]);
  const th = (k: string, label: string) => (
    <th aria-sort={ts.k === k ? (ts.asc ? "ascending" : "descending") : "none"}><button type="button" onClick={() => setTs({ k, asc: ts.k === k ? !ts.asc : false })}>{label}{ts.k === k ? (ts.asc ? " ▲" : " ▼") : ""}</button></th>);

  const goTab = (t: Tab) => {
    if (t === "builder") { if (detId) navigate("warunki", { setupId: detId }); else navigate("pepe-wtc"); return; }
    setTab(t);
  };
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <TowerFrame page="pepe-signal" accent="#39ff8f" testid="page-pepe-signal"
      title={<><span className="sg-logo" aria-hidden="true">((•))</span><span>PEPE<em>$</em>SIGNAL</span></>} subtitle="TOWER OF SIGNAL INTELLIGENCE" tagline="MULTI-STRATEGY · AI EVALUATION · REAL-TIME SIGNALS"
      tabs={
        <div className="sg-tabs" role="tablist" aria-label="Widoki PEPE$SIGNAL">
          {TABS.map(([id, label, title]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={cls(tab === id && "on", id === "center" && "first")} title={title}
              onClick={() => goTab(id)} data-testid={`sg-tab-${id}`}>{id === "live" && <i className="tw-dot ok" />}{label}</button>))}
          <span className="tw-grow" />
          <span className={cls("sg-flow", paused && "off")} data-testid="sg-flow"><i />{paused ? "PAUZA" : "LIVE"} · {all.length} sygnałów · {envTxt}</span>
        </div>}
      status={<>
        <b className="tw-st-name">PEPE$SIGNAL</b><span className="tw-st-c">Signal Intelligence &amp; Strategy Evaluation</span>
        <span><i className={cls("tw-dot", ctx.mt5 === "CONNECTED" ? "ok" : "bad")} />{ctx.env === "SYNTHETIC" ? "SYMULATOR MT5 – dane syntetyczne" : `MT5 ${envTxt}`}</span>
        <span>Źródła: bot-signals {bot.err ? "BŁĄD" : "OK"} · silnik {setups.err ? "BŁĄD" : "OK"} · SH {sh.err ? "BŁĄD" : "OK"}</span>
        <span>Widok tylko do analizy – brak akcji handlowych</span>
      </>}>
      {alert && <div className="sg-alert" role="alert" data-testid="sg-alert">⚠ {alert}<button type="button" onClick={() => setAlert(null)} aria-label="Zamknij alert">×</button></div>}
      <div className={cls("sg-grid", tab === "ai" && "ai", tab === "performance" && "perf")}>
        {/* ------------------------------------------------ tower */}
        <aside className="sg-tower" aria-label="Wieża PEPE$SIGNAL">
          <img src="/assets/towers/signal-tower.webp" alt="" aria-hidden="true" />
          <nav aria-label="Sekcje wieży">
            {([["AI SIGNALS", "sg-stream", 41.1], ["MULTI-STRATEGY", "sg-table", 45.7], ["MODEL CONSENSUS", "sg-models", 50.5], ["SETUP ANALYSIS", "sg-analysis", 55.2],
              ["RISK CONTEXT", "sg-metrics", 60], ["MTF ALIGNMENT", "sg-mtf", 65.2]] as [string, string, number][]).map(([l, id, y]) => (
              <button key={id} type="button" style={{ top: `${y}%` } as CSSProperties} onClick={() => scrollTo(id)} data-testid={`sg-tw-${id}`}><span>{l}</span></button>))}
          </nav>
        </aside>

        {/* ------------------------------------------------ stream */}
        <section className="tw-card sg-stream" id="sg-stream" data-testid="sg-stream" aria-label="Strumień sygnałów">
          {wave > 0 && <span className="sg-wave" key={wave} aria-hidden="true" />}
          <header className="tw-card-h"><h2 title={`Źródło: ${envTxt}`}><span className="tw-ico">➜</span>STRUMIEŃ SYGNAŁÓW (LIVE)</h2></header>
          <div className="sg-filters">
            <select value={f.strategy} onChange={(e) => setF({ ...f, strategy: e.target.value })} aria-label="Strategia" data-testid="sg-f-strategy">
              <option value="">Wszystkie strategie</option>{strategies.map((x) => <option key={x}>{x}</option>)}</select>
            <select value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })} aria-label="Symbol" data-testid="sg-f-symbol">
              <option value="">Wszystkie symbole</option>{symbols.map((x) => <option key={x}>{x}</option>)}</select>
            <button type="button" className={cls("tw-btn sq", paused && "on")} onClick={() => setPaused(!paused)} aria-pressed={paused} data-testid="sg-pause"
              title={paused ? "Wznów aktualizację strumienia" : "Wstrzymaj aktualizację strumienia (lista zamrożona)"}>{paused ? "▶" : "Ⅱ"}</button>
          </div>
          <details className="sg-more">
            <summary>Filtry i sortowanie</summary>
            <div className="sg-filters wrap">
              <select value={f.tf} onChange={(e) => setF({ ...f, tf: e.target.value })} aria-label="Timeframe"><option value="">TF: wszystkie</option>{TFS.map((x) => <option key={x}>{x}</option>)}</select>
              <select value={f.dir} onChange={(e) => setF({ ...f, dir: e.target.value })} aria-label="Kierunek" data-testid="sg-f-dir"><option value="">Kierunek: wszystkie</option><option>BUY</option><option>SELL</option><option>WAIT</option></select>
              <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status"><option value="">Status: wszystkie</option>
                {["CANDIDATE", "CONFIRMED", "FILLED", "WAIT", "CLOSED", "EXPIRED", "INVALIDATED", "REJECTED"].map((x) => <option key={x}>{x}</option>)}</select>
              <select value={f.range} onChange={(e) => setF({ ...f, range: e.target.value })} aria-label="Przedział czasu"><option value="1h">ostatnia 1 h</option><option value="24h">24 h</option><option value="7d">7 dni</option><option value="all">cały zapis</option></select>
              <label>Siła ≥ <input type="number" min={0} max={100} step={5} value={f.minStrength} onChange={(e) => setF({ ...f, minStrength: Number(e.target.value) || 0 })} /></label>
              <select value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value as any })} aria-label="Sortowanie"><option value="time">najnowsze</option><option value="strength">najsilniejsze</option></select>
              <input type="search" placeholder="Szukaj…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Szukaj sygnału" />
            </div>
          </details>
          <VirtualList items={list} sel={sel?.id ?? null} onPick={pick} />
          {!list.length && <p className="tw-na">{bot.err && setups.err ? `Błąd źródeł: ${bot.err}` : all.length ? "Brak sygnałów dla filtrów." : "Bot nie ma jeszcze sygnałów ani scenariuszy w tej sesji."}</p>}
        </section>

        {/* ------------------------------------------------ analysis */}
        <div className="sg-center" id="sg-analysis">
          {tab === "ai" ? <AiEvaluation models={models} asset={asset} err={preds.err} sel={sel} /> :
           tab === "performance" ? <Performance d={frozen.current.bot} /> : (
          <>
          <section className="tw-card sg-head" data-testid="sg-selected" aria-label="Analiza sygnału – wybrany sygnał">
            <header className="tw-card-h"><h2><span className="tw-ico">➜</span>ANALIZA SYGNAŁU — WYBRANY SYGNAŁ</h2>
              <span className="tw-card-r tw-dim">ID: {sel?.id ?? "—"}</span></header>
            {sel ? (
              <div className="sg-head-b" key={sel.id}>
                <span className="sg-crown" aria-hidden="true">{ICON[sel.strategyId] ?? "♛"}</span>
                <div className="sg-name"><b>{sel.strategyId}</b> <span>({sel.strategyName})</span><small>{sel.kind === "BOT" ? "SYGNAŁ STRATEGII" : sel.kind === "SETUP" ? "SCENARIUSZ SILNIKA" : "MASZYNA SH"} · {sel.source}</small></div>
                <div className="sg-sym"><b>{sel.symbol}</b> <em>{sel.tf ?? "—"}</em><small>{hms(sel.at)} · {sel.lifecycle}{historic ? " · HISTORYCZNY" : ""}</small></div>
                <span className={cls("sg-big", `d-${sel.direction.toLowerCase()}`)} data-testid="sg-direction">{sel.direction}</span>
                <div className="sg-str"><small>SIŁA SYGNAŁU <i title="wynik ACTIVE strategii – heurystyka 0–100, nie prawdopodobieństwo">ⓘ</i></small><b>{sel.strength != null ? `${Math.round(sel.strength)}/100` : "N/A"}</b><Meter value={sel.strength} label=" " title="siła sygnału (heurystyka)" /></div>
              </div>) : <p className="tw-na">Wybierz sygnał ze strumienia lub tabeli.</p>}
          </section>
          <div className="sg-row2">
            <section className="tw-card sg-ctx" aria-label="Kontekst sygnału">
              <header className="tw-card-h"><h2>KONTEKST SYGNAŁU ({sel?.symbol ?? "—"} — {sel?.tf ?? "—"})</h2>
                <span className="tw-card-r"><ChartTools /></span></header>
              <SignalChart sig={sigView} showLevels resetKey={0} />
            </section>
            <Card title="PODSUMOWANIE SYGNAŁU" className="sg-sum" testid="sg-summary">
              <dl className="tw-kv dense">
                <dt>Strategia</dt><dd>{sel ? `${sel.strategyId} (${sel.strategyName})` : "N/A"}</dd>
                <dt>Kierunek</dt><dd className={sel?.direction === "BUY" ? "ok" : sel?.direction === "SELL" ? "bad" : "warn"}>{sel ? (sel.direction === "WAIT" ? `WAIT${sel.scenarioDir ? ` (scenariusz ${sel.scenarioDir})` : ""}` : `${sel.direction} (${sel.direction === "BUY" ? "Long" : "Short"})`) : "N/A"}</dd>
                <dt>Symbol / TF</dt><dd>{sel ? `${sel.symbol} / ${sel.tf ?? "—"}` : "N/A"}</dd>
                <dt>Sugerowane wejście</dt><dd>{fmt(entry, digits)}</dd>
                <dt>Stop Loss (SL)</dt><dd className="bad">{fmt(sl, digits)}{entry != null && sl != null ? ` (${fmt(sl - entry, digits)})` : ""}</dd>
                {[0, 1, 2].map((i) => (tps[i] != null || i < 2) && <Fragment key={i}><dt>Take Profit {i + 1} (TP{i + 1})</dt><dd className="ok">{fmt(tps[i], digits)}{tps[i] != null && entry != null ? ` (${fmt(tps[i] - entry, digits)})` : ""}</dd></Fragment>)}
                <dt>R:R (TP2)</dt><dd>{rrTp(1) != null ? `1 : ${fmt(rrTp(1), 2)}` : rrTp(0) != null ? `1 : ${fmt(rrTp(0), 2)} (TP1)` : "N/A"}</dd>
                <dt>Jakość setupu</dt><dd>{detOk?.summary ? `${detOk.summary.required_met}/${detOk.summary.required_total} wymagań` : "N/A"}</dd>
                <dt>Zezwolenie (silnik)</dt><dd>{detOk?.entry?.status ?? (sel?.kind === "BOT" ? (sel.raw.validation?.ok ? "walidacja OK" : "odrzucony") : "N/A")}</dd>
                <dt>Konsensus AI</dt><dd>{cons.active ? `${cons.dir} ${cons.agree}/${cons.active}` : "N/A"}</dd>
              </dl>
            </Card>
          </div>
          <div className="sg-conds">
            <CondCard title="WARUNKI WEJŚCIA" sub="(ENTRY CONDITIONS)" icon="◎" rows={cond.entry} testid="sg-entry" />
            <CondCard title="WARUNKI WYZWALAJĄCE" sub="(TRIGGER)" icon="ϟ" rows={cond.trigger} testid="sg-trigger" />
            <CondCard title="INWALIDACJA" sub="(INVALIDATION)" icon="⛨" rows={cond.invalidation} testid="sg-invalidation" bad />
          </div>
          <div className="sg-row3">
            <Card title={<>NARRACJA SETUPU <small>(SETUP NARRATIVE)</small></>} icon="▤" testid="sg-narrative">
              <p className="sg-story">{story}</p><p className="tw-note">Źródło warunków: {cond.source}.</p>
            </Card>
            <Card title={<>ENTRY CONDITIONS <small>(SKRÓT)</small></>} testid="sg-entry-short">
              <ul className="sg-short">
                <li>Entry: <b>{fmt(entry, digits)}</b></li><li className="bad">SL: <b>{fmt(sl, digits)}</b></li>
                {tps.slice(0, 2).map((p, i) => <li key={i} className="ok">TP{i + 1}: <b>{fmt(p, digits)}</b></li>)}
              </ul>
            </Card>
            <Card title={<>INVALIDATION <small>(SKRÓT)</small></>} testid="sg-inv-short">
              <ul className="sg-short x">{cond.invalidation.slice(0, 3).map((r, i) => <li key={i}>{r.label}</li>)}{!cond.invalidation.length && <li className="tw-dim">N/A</li>}</ul>
            </Card>
          </div>
          </>)}

          {/* table of strategies and active signals */}
          {tab === "strategies" ? <StrategiesTable all={all} catalogue={frozen.current.setups?.strategies || []} sources={frozen.current.bot?.strategies || []} onPick={pick} /> : (
          <section className="tw-card sg-table" id="sg-table" data-testid="sg-table" aria-label="Przegląd strategii i aktywnych sygnałów">
            <header className="tw-card-h"><h2><span className="tw-ico">➜</span>PRZEGLĄD STRATEGII I AKTYWNYCH SYGNAŁÓW <small>(LIVE OVERVIEW)</small></h2>
              <span className="tw-card-r">
                <span className="tw-seg mini">
                  <button type="button" className={cls(tableScope === "active" && "on")} aria-pressed={tableScope === "active"} onClick={() => setTableScope("active")} data-testid="sg-scope-active">Aktywne ({list.filter((x) => LIVE.includes(x.lifecycle) && x.lifecycle !== "WAIT").length})</button>
                  <button type="button" className={cls(tableScope === "all" && "on")} aria-pressed={tableScope === "all"} onClick={() => setTableScope("all")} data-testid="sg-scope-all">Wszystkie ({list.length})</button></span>
                <span className="tw-dim">Auto-odświeżanie {paused ? "wstrzymane" : "8 s"}</span></span></header>
            <div className="tw-scroll-x">
              <table className="tw-tbl sg-tbl">
                <thead><tr><th>#</th>{th("strategy", "Strategia")}{th("symbol", "Symbol")}{th("tf", "TF")}{th("dir", "Sygnał")}{th("strength", "Siła")}{th("entry", "Entry")}<th>SL</th><th>TP1</th><th>TP2</th>{th("rr", "R:R")}{th("status", "Status")}<th>Źródło</th></tr></thead>
                <tbody>
                  {tableRows.slice(page * PER, page * PER + PER).map((x, i) => (
                    <tr key={x.id} className={cls(x.id === sel?.id && "on")} onClick={() => pick(x)} tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && pick(x)}
                      aria-selected={x.id === sel?.id} data-testid="sg-row" data-id={x.id}>
                      <td>{page * PER + i + 1}</td><td><span className="sg-ic">{ICON[x.strategyId] ?? "◆"}</span>{x.strategyId}</td><td>{x.symbol}</td><td>{x.tf ?? "—"}</td>
                      <td><Dir d={x.direction} /></td><td>{x.strength != null ? `${Math.round(x.strength)}/100` : "N/A"}</td>
                      <td>{fmt(x.entry, x.entry != null && Math.abs(x.entry) < 500 ? 3 : 2)}</td><td>{fmt(x.sl, x.sl != null && Math.abs(x.sl) < 500 ? 3 : 2)}</td>
                      <td>{fmt(x.targets[0], 2)}</td><td>{fmt(x.targets[1], 2)}</td><td>{x.rr != null ? `1 : ${fmt(x.rr, 2)}` : "N/A"}</td>
                      <td><span className={cls("sg-st", `l-${x.lifecycle.toLowerCase()}`)}>{x.lifecycle}</span></td><td className="tw-dim">{x.kind}</td></tr>))}
                </tbody>
              </table>
              {!tableRows.length && <p className="tw-na">Brak {tableScope === "active" ? "aktywnych " : ""}sygnałów dla wybranych filtrów.</p>}
            </div>
            <div className="tw-row sg-pager">
              <button type="button" className="tw-btn sm" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Poprzednia strona">‹</button>
              <span className="tw-dim">strona {page + 1} / {pages}</span>
              <button type="button" className="tw-btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} aria-label="Następna strona">›</button>
              <span className="tw-grow" />
              {sel && <Timeline sel={sel} det={detOk} />}
            </div>
          </section>)}
        </div>

        {/* ------------------------------------------------ models / metrics */}
        <div className="sg-right">
          <section className="tw-card sg-models" id="sg-models" data-testid="sg-models" aria-label="Ocena modeli AI – sygnał">
            <header className="tw-card-h"><h2><span className="tw-ico">➜</span>OCENA MODELI AI — SYGNAŁ</h2>
              <span className="tw-card-r"><Src k={!asset ? "na" : preds.err ? "err" : (envK as any)}>{!asset ? "N/A" : historic ? "STAN BIEŻĄCY" : "LIVE"}</Src></span></header>
            {!asset ? <p className="tw-na">UNAVAILABLE – modele bota liczą tylko instrumenty {(s.assets?.allowed || []).join(" / ")}; {sel?.symbol ?? "ten symbol"} pochodzi ze skanera rynków.</p> : (
              <ul className="sg-mlist">
                {models.slice(0, 6).map((m) => (
                  <li key={m.key} className={cls(`st-${m.state.toLowerCase()}`)} title={`${m.task ?? ""}${m.reason ? ` · ${m.reason}` : ""}`} data-testid="sg-model">
                    <span className="sg-mi" aria-hidden="true">◈</span>
                    <div><b>{m.name}</b> <small>{m.version ? `v${String(m.version).slice(0, 10)}` : ""} {m.tf ?? ""}</small>
                      <em>{m.state} · {m.at ? hms(m.at) : "—"} · {m.scoreKind}</em></div>
                    <Dir d={m.bias ?? (m.state === "READY" ? "NEUTRAL" : "N/A")} />
                    <span className="sg-ms">{m.score != null ? `${Math.round(m.score)}/100` : "N/A"}<Meter value={m.score} label=" " /></span>
                  </li>))}
              </ul>)}
            {asset && !models.length && <p className="tw-na">{preds.err ?? "Brak predykcji modeli."}</p>}
            <div className="sg-cons" data-testid="sg-consensus">
              <span className="sg-mi big" aria-hidden="true">≋</span>
              <div><b>CONSENSUS ENGINE</b><small>głosowanie modeli READY z kierunkiem, wagi równe</small></div>
              <Dir d={cons.dir ?? "N/A"} />
              <span className="sg-ms"><b>{cons.active ? `${cons.agree}/${cons.active}` : "N/A"}</b><small>{cons.conflict ? "KONFLIKT modeli" : "zgodność kierunkowa"}</small></span>
            </div>
            {historic && <p className="tw-note">Sygnał historyczny ({dt(sel?.at)}): oceny modeli to stan BIEŻĄCY, nie ocena z chwili sygnału.</p>}
            <p className="tw-note">Wynik ≠ P(sukcesu). Procent prawdopodobieństwa pokazujemy tylko dla modeli oznaczonych jako skalibrowane.</p>
          </section>
          <Card title="METRYKI SYGNAŁU" icon="◉" testid="sg-metrics" id="sg-metrics">
            <div className="sg-metrics">
              <div><small>Siła sygnału</small><b>{sel?.strength != null ? `${Math.round(sel.strength)}/100` : "N/A"}</b><Meter value={sel?.strength} label=" " /></div>
              <div><small>Jakość setupu</small><b>{detOk?.summary ? `${detOk.summary.required_met}/${detOk.summary.required_total}` : "N/A"}</b>
                <Meter value={detOk?.summary ? (100 * detOk.summary.required_met) / Math.max(1, detOk.summary.required_total) : null} label=" " /></div>
              <div><small>Kontekst ryzyka</small><b className={cls(detOk?.sizing?.risk_gate === "PASS" ? "ok" : detOk?.sizing ? "warn" : "")}>{detOk?.sizing?.risk_gate ?? (sel?.kind === "BOT" ? (sel.raw.validation?.ok ? "WALIDACJA OK" : "ODRZUCONY") : "N/A")}</b>
                <small>{detOk?.rr?.net != null ? `RR netto ${fmt(detOk.rr.net, 2)}` : ""}</small></div>
              <div><small>Zgodność MTF</small><b>{mtfRows.length ? `${mtfRows.filter((r) => r.agreement === "ZGODNY").length}/${mtfRows.length}` : "N/A"}</b></div>
            </div>
          </Card>
          <Card title="ZBIEŻNOŚĆ TIMEFRAME (MTF ALIGNMENT)" icon="▤" testid="sg-mtf" id="sg-mtf">
            {mtfRows.length ? (
              <div className="sg-mtf">
                {mtfRows.map((r) => (
                  <span key={r.tf} className={cls(r.tf === sel?.tf && "on", r.agreement === "ZGODNY" ? "ok" : r.agreement === "KONFLIKT" ? "bad" : "na")} title={`${r.role ?? ""} · ${r.direction ?? "brak danych"} · ${r.agreement}`}>
                    {r.tf}<i>{r.agreement === "ZGODNY" ? "✓" : r.agreement === "KONFLIKT" ? "✗" : "–"}</i></span>))}
                <div className="sg-mtf-sum"><small>Zgodność</small><b>{mtfRows.filter((r) => r.agreement === "ZGODNY").length}/{mtfRows.length}</b></div>
              </div>) : <p className="tw-na">MTF dostępne dla scenariuszy silnika aktywnego instrumentu (tylko faktycznie analizowane TF). Dla tego sygnału: N/A.</p>}
          </Card>
          <a className="tw-link" href={href("lightning")}>Pełna historia i cykl życia sygnałów → PEPE$BANK</a>
        </div>
      </div>
    </TowerFrame>);
}

function ChartTools() {
  return <span className="tw-dim" title="przeciągnij = przesuń, kółko = zoom, celownik pokazuje OHLC">kółko = zoom · przeciągnij = przesuń</span>;
}

function VirtualList({ items, sel, onPick }: { items: Sig[]; sel: string | null; onPick: (x: Sig) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);
  const [h, setH] = useState(600);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setH(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const first = Math.max(0, Math.floor(top / ROW_H) - 3), last = Math.min(items.length, Math.ceil((top + h) / ROW_H) + 3);
  return (
    <div className="sg-list" ref={box} onScroll={(e) => setTop((e.target as HTMLDivElement).scrollTop)} role="listbox" aria-label="Sygnały" data-testid="sg-list" data-count={items.length}>
      <div style={{ height: items.length * ROW_H, position: "relative" }}>
        {items.slice(first, last).map((x, i) => (
          <button key={x.id} type="button" role="option" aria-selected={x.id === sel} className={cls("sg-item", x.id === sel && "on", `l-${x.lifecycle.toLowerCase()}`)}
            style={{ top: (first + i) * ROW_H }} onClick={() => onPick(x)} data-testid="sg-item" data-id={x.id}>
            <span className="sg-i-h"><span className="sg-ic" aria-hidden="true">{ICON[x.strategyId] ?? "◆"}</span><b>{x.strategyId}</b><small>{x.strategyName}</small><Dir d={x.direction} /></span>
            <span className="sg-i-m"><b>{x.symbol}</b><em>{x.tf ?? "—"}</em><time>{hms(x.at)}</time></span>
            <span className="sg-i-s"><small>{x.lifecycle === "WAIT" || x.lifecycle === "CANDIDATE" ? (x.reason ? x.reason.slice(0, 34) : x.statusRaw) : "Siła sygnału"}</small>
              <Meter value={x.strength} label=" " title="siła sygnału (heurystyka)" /><b>{x.strength != null ? `${Math.round(x.strength)}/100` : "N/A"}</b></span>
          </button>))}
      </div>
    </div>);
}

const COND_ICON: Record<Cond, string> = { MET: "✓", NOT_MET: "✗", PENDING: "◷", UNKNOWN: "?", INVALIDATED: "✗" };
function CondCard({ title, sub, icon, rows, testid, bad }: { title: string; sub: string; icon: string; rows: CondRow[]; testid: string; bad?: boolean }) {
  return (
    <Card title={<>{title} <small>{sub}</small></>} icon={icon} testid={testid} className={cls("sg-cond", bad && "inv")}>
      <ul className="sg-clist">
        {rows.slice(0, 7).map((r, i) => (
          <li key={i} className={`c-${r.state.toLowerCase()}`} title={[r.evidence, r.at ? `oceniono ${hms(r.at)}` : null].filter(Boolean).join(" · ")} data-state={r.state}>
            <i aria-label={r.state}>{bad && r.state === "PENDING" ? "⛨" : COND_ICON[r.state]}</i><span>{r.label}</span></li>))}
      </ul>
      {!rows.length && <p className="tw-na">N/A – brak reguł tej kategorii w danych sygnału.</p>}
      {rows.length > 7 && <p className="tw-note">+{rows.length - 7} kolejnych (najedź, aby zobaczyć dowód)</p>}
    </Card>);
}

function Timeline({ sel, det }: { sel: Sig; det: any }) {
  const st = [
    { k: "detected", at: sel.at, on: true },
    { k: "evaluated", at: det?.times?.checked_at ?? sel.updated, on: true },
    { k: "confirmed", at: ["CONFIRMED", "FILLED", "CLOSED"].includes(sel.lifecycle) ? sel.raw.filled_at ?? sel.updated : null, on: ["CONFIRMED", "FILLED", "CLOSED"].includes(sel.lifecycle) },
    { k: sel.lifecycle === "INVALIDATED" || sel.lifecycle === "REJECTED" ? "invalidated" : "closed", at: sel.raw.closed_at ?? (HIST.includes(sel.lifecycle) ? sel.updated : null), on: HIST.includes(sel.lifecycle) },
  ];
  return (
    <ol className="sg-tl" aria-label="Oś zdarzeń wybranego sygnału" data-testid="sg-timeline">
      {st.map((x) => <li key={x.k} className={cls(x.on && "on")}><b>{x.k}</b><small>{x.on ? hms(x.at) : "—"}</small></li>)}
    </ol>);
}

function AiEvaluation({ models, asset, err, sel }: { models: ReturnType<typeof modelRows>; asset: string | null; err: string | null; sel: Sig | null }) {
  return (
    <Card title={`AI EVALUATION — WSZYSTKIE MODELE ${asset ?? ""}`} icon="◈" testid="sg-ai-eval" className="sg-ai">
      {!asset ? <p className="tw-na">UNAVAILABLE dla {sel?.symbol ?? "tego symbolu"} – modele działają dla aktywnych instrumentów bota.</p> : (
        <div className="tw-scroll-x">
          <table className="tw-tbl">
            <thead><tr><th>Model</th><th>Wersja</th><th>TF</th><th>Stan</th><th>Inferencja</th><th>Kierunek</th><th>Wynik</th><th>Semantyka</th><th>Rola</th><th>Przyczyna</th></tr></thead>
            <tbody>{models.map((m) => (
              <tr key={m.key}><td><b>{m.name}</b><br /><small className="tw-dim">{m.task}</small></td><td>{m.version ?? "—"}</td><td>{m.tf ?? "—"}</td>
                <td><span className={cls("sg-st", `m-${m.state.toLowerCase()}`)}>{m.state}</span></td><td>{m.at ? hms(m.at) : "—"}</td><td><Dir d={m.bias ?? "N/A"} /></td>
                <td>{m.score != null ? fmt(m.score, 1) : "N/A"}</td><td className="tw-dim">{m.scoreKind}</td><td className="tw-dim">{m.role ?? "—"}</td><td className="tw-dim">{m.reason ?? "—"}</td></tr>))}</tbody>
          </table>
          {!models.length && <p className="tw-na">{err ?? "Brak zarejestrowanych predykcji."}</p>}
        </div>)}
    </Card>);
}

function Performance({ d }: { d: any }) {
  const st = d?.stats, by = d?.stats_by_ai || {};
  const cell = (x: any) => [x?.signals ?? 0, x?.closed ?? 0, x?.win_rate_pct != null ? `${fmt(x.win_rate_pct, 1)}%` : "N/A", x?.profit_factor_r ?? "N/A", x?.avg_r ?? "N/A", x?.total_r ?? "N/A"];
  return (
    <Card title="PERFORMANCE — SYGNAŁY BOTA (R BRUTTO)" icon="↗" testid="sg-performance" className="sg-perf">
      <div className="sg-metrics four">
        <div><small>Sygnały</small><b>{st?.signals ?? "N/A"}</b></div><div><small>Otwarte / zamknięte</small><b>{st ? `${st.open} / ${st.closed}` : "N/A"}</b></div>
        <div><small>Win rate (bez BE)</small><b>{st?.win_rate_pct != null ? `${fmt(st.win_rate_pct, 1)}%` : "N/A"}</b></div><div><small>Suma R</small><b>{st?.total_r ?? "N/A"}</b></div>
      </div>
      <table className="tw-tbl"><thead><tr><th>Ocena AI</th><th>Sygnały</th><th>Zamknięte</th><th>Win rate</th><th>PF (R)</th><th>Śr. R</th><th>Suma R</th></tr></thead>
        <tbody>{["ZGODA", "BRAK_ZGODY", "BRAK_OCENY"].map((k) => <tr key={k}><td>{k.replace("_", " ")}</td>{cell(by[k]).map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody></table>
      <p className="tw-note">{st?.note ?? ""} {d?.ai_note ?? ""}</p>
    </Card>);
}

function StrategiesTable({ all, catalogue, sources, onPick }: { all: Sig[]; catalogue: any[]; sources: string[]; onPick: (x: Sig) => void }) {
  const ids = [...new Set([...catalogue.map((x) => x.strategy_id), ...all.map((x) => x.strategyId)])];
  return (
    <section className="tw-card sg-table" id="sg-table" data-testid="sg-strategies" aria-label="Wszystkie strategie">
      <header className="tw-card-h"><h2><span className="tw-ico">➜</span>ALL STRATEGIES <small>(rejestr strategii bota)</small></h2><span className="tw-card-r tw-dim">źródła: {sources.join(", ")}</span></header>
      <div className="tw-scroll-x">
        <table className="tw-tbl sg-tbl">
          <thead><tr><th>Strategia</th><th>Nazwa</th><th>Sygnały</th><th>Aktywne</th><th>Ostatni</th><th>Kierunek</th><th>Siła</th><th>Status</th></tr></thead>
          <tbody>{ids.map((id) => {
            const xs = all.filter((x) => x.strategyId === id), last = xs[0];
            return (
              <tr key={id} onClick={() => last && onPick(last)} className={cls(!last && "dim")} tabIndex={last ? 0 : -1} onKeyDown={(e) => last && e.key === "Enter" && onPick(last)}>
                <td><span className="sg-ic">{ICON[id] ?? "◆"}</span>{id}</td><td>{catalogue.find((c) => c.strategy_id === id)?.name ?? last?.strategyName ?? "—"}</td>
                <td>{xs.length}</td><td>{xs.filter((x) => x.live).length}</td><td>{last ? hms(last.updated) : "—"}</td><td>{last ? <Dir d={last.direction} /> : "—"}</td>
                <td>{last?.strength != null ? `${Math.round(last.strength)}/100` : "N/A"}</td><td>{last ? <span className={cls("sg-st", `l-${last.lifecycle.toLowerCase()}`)}>{last.lifecycle}</span> : <span className="tw-dim">brak sygnałów</span>}</td></tr>);
          })}</tbody>
        </table>
      </div>
    </section>);
}
