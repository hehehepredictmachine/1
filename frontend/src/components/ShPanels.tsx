// PMW-SH-1: SCALPING / HEDGING strategy panel and the training panel. Every value comes from the backend (/api/v1/sh*,
// /api/v1/training*); nothing is computed or invented here. A WAIT / NO_TRADE setup is never shown as an active signal; the score is
// labelled as a heuristic, a probability only appears when the backend marks it as calibrated for the strategy's own event.
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet, apiSend, getCsrf } from "../api";
import { useTheme } from "../theme";
import { fmtNum } from "../util";

const ST_TONE: Record<string, string> = { READY: "ok", WAIT: "warn", NO_TRADE: "bad", INVALIDATED: "bad", EXPIRED: "muted", PASS: "ok", BLOCK: "bad",
  PROCEED: "ok", FAIL: "bad" };
const ST_PL: Record<string, string> = { READY: "GOTOWY", WAIT: "CZEKA", NO_TRADE: "BRAK TRANSAKCJI", INVALIDATED: "UNIEWAŻNIONY", EXPIRED: "WYGASŁ",
  PASS: "OK", FAIL: "nie", PROCEED: "realizuj", BLOCK: "blokada" };
const tsl = (t?: number | null) => (t ? new Date(t * 1000).toISOString().slice(0, 19).replace("T", " ") + " UTC" : "—");
const age = (t?: number | null, now?: number) => (t && now ? Math.max(0, Math.round(now - t)) : null);
const Badge = ({ s, children }: { s?: string; children?: any }) => <span className={`badge ${ST_TONE[s || ""] || ""}`}>{children ?? ST_PL[s || ""] ?? s ?? "—"}</span>;

// ------------------------------------------------------------------------------------------------ chart with plan levels
function PlanChart({ bars, plan, setup, height = 320 }: { bars: any[]; plan?: any; setup?: any; height?: number }) {
  const theme = useTheme();
  const tk: any = theme.chartTokens("sh") || {};
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const ser = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10 },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6 },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC" } });
    chart.current = c;
    ser.current = c.addSeries(CandlestickSeries, {});
    return () => { c.remove(); chart.current = null; ser.current = null; lines.current = []; };
  }, []);
  useEffect(() => {
    ser.current?.applyOptions({ upColor: tk.upBody, downColor: tk.downBody, borderUpColor: tk.upBorder, borderDownColor: tk.downBorder, wickUpColor: tk.upWick,
      wickDownColor: tk.downWick });
    chart.current?.applyOptions({ layout: { textColor: tk.chartText }, grid: { vertLines: { color: tk.chartGrid }, horzLines: { color: tk.chartGrid } } });
  }, [JSON.stringify(tk)]);
  useEffect(() => {
    const s = ser.current;
    if (!s) return;
    const data = (bars || []).map((b: any) => ({ time: Math.floor(Date.parse(b.open_utc) / 1000) as Time, open: b.o, high: b.h, low: b.l, close: b.c }));
    s.setData(data);
    lines.current.forEach((l) => s.removePriceLine(l));
    lines.current = [];
    const add = (price: any, title: string, color: any, style = LineStyle.Solid) => {
      if (price === null || price === undefined || !isFinite(Number(price))) return;
      lines.current.push(s.createPriceLine({ price: Number(price), title, color: String(color || "#888"), lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
    };
    const pos = plan?.position;
    if (pos) {
      add(pos.entry, "wejście (fill)", tk.entry);
      add(pos.sl, pos.be_status === "SET" ? "SL = BE" : "SL", tk.sl);
      (pos.legs || []).forEach((l: any) => add(l.price, `${l.name}${l.status === "DONE" ? " ✓" : ""}`, tk.tp, l.status === "DONE" ? LineStyle.Dotted : LineStyle.Solid));
      if (pos.be_status !== "SET") add(pos.be_price, "BE (po TP2)", tk.entry, LineStyle.Dashed);
      const h = plan.basket?.hedge;
      if (h?.volume) add(h.entry, `hedge ${h.side} ${h.volume}`, tk.warn);
    } else if (setup && setup.status === "READY") {
      add(setup.entry_ref, "wejście (plan)", tk.entry, LineStyle.Dashed);
      add(setup.sl, "SL", tk.sl, LineStyle.Dashed);
      (setup.tps || []).forEach((t: any) => add(t.price, t.name, tk.tp, LineStyle.Dashed));
    }
    if (setup?.entry_zone) {
      add(setup.entry_zone[0], "strefa", tk.entry, LineStyle.Dotted);
      add(setup.entry_zone[1], "strefa", tk.entry, LineStyle.Dotted);
    }
    if (setup?.invalidation) add(setup.invalidation, "unieważnienie", tk.sl, LineStyle.Dotted);
  }, [bars, plan, setup, JSON.stringify(tk)]);
  return <div ref={box} style={{ height, width: "100%" }} data-testid="sh-chart" />;
}

// ------------------------------------------------------------------------------------------------ strategy page
export function StrategyPage() {
  const [st, setSt] = useState<any>(null);
  const [chart, setChart] = useState<any>(null);
  const [strat, setStrat] = useState<"SCALPING" | "HEDGING">(() => { try { return (localStorage.getItem("sh.strategy") as any) || "SCALPING"; } catch { return "SCALPING"; } });
  const [tf, setTf] = useState("M1");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => {
    apiGet("/api/v1/sh").then((r) => { setSt(r); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
    apiGet(`/api/v1/sh/chart?tf=${tf}&limit=240`).then(setChart).catch(() => undefined);
  };
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [tf]);
  useEffect(() => { try { localStorage.setItem("sh.strategy", strat); } catch { /* storage unavailable */ } }, [strat]);
  if (err && !st) return <div className="panel"><p className="bad-text">Panel strategii niedostępny: {err}</p></div>;
  if (!st) return <div className="panel"><p className="muted">Ładowanie stanu strategii…</p></div>;
  const ev = st.last_eval?.[strat];
  const plans: any[] = (st.open_plans || []).filter((p: any) => p.strategy === strat);
  const plan = plans[0];
  const cfg = st.config?.instruments?.[st.instrument]?.[strat] || {};
  const ic = st.config?.instruments?.[st.instrument] || {};
  const now = st.server_time;
  const evAge = age(ev?.created_at, now);
  const stale = evAge !== null && evAge > 150;
  const snap = st.snapshot || {};
  const dq = snap.data || {};
  const rows: any[] = (st.models?.rows || []);
  return (
    <div className="page-sh" data-testid="page-strategie">
      <div className="panel">
        <div className="chips-row">
          <b>Strategia:</b>
          {(["SCALPING", "HEDGING"] as const).map((k) => <button key={k} className={`btn ${strat === k ? "" : "ghost"}`} onClick={() => setStrat(k)} data-testid={`sh-sel-${k}`}>{k}</button>)}
          <span className="muted small">instrument <b>{st.instrument}</b> · symbol <span className="mono">{st.symbol || "—"}</span> · tryb <b data-testid="sh-mode">{st.mode}</b>
            {" "}· rachunek {st.account_margin_mode || "—"} · konfiguracja <span className="mono">{st.config?._hash}</span> (wersja {st.config?._override_version})</span>
        </div>
        {st.models?.mode === "OGRANICZONA" && <p className="small warn" data-testid="sh-limited">{st.models.mode_note}</p>}
        {strat === "HEDGING" && st.account_margin_mode && st.account_margin_mode !== "HEDGING" &&
          <p className="small bad-text" data-testid="sh-netting">Rachunek {st.account_margin_mode}: HEDGING zablokowany (brak cichej podmiany na inną strategię).</p>}
        {ic.enabled === false && <p className="small bad-text">Instrument {st.instrument} wyłączony: {ic.status}</p>}
        <p className="muted small">Cele TP to bezwzględny ruch ceny w USD od rzeczywistego wykonania (nie %, nie punkty, nie zysk rachunku). Ustawienia są parametrami
          roboczymi do walidacji – bez obietnicy wyniku. Stan: {st.status}{st.reason ? ` (${st.reason})` : ""} · aktualizacja {tsl(st.updated_at)}.</p>
      </div>

      <div className="grid-2">
        <div className="panel" data-testid="sh-setup">
          <h3>Setup {strat} <Badge s={ev?.status} /> {stale && <span className="tag warn" data-testid="sh-stale">nieaktualny ({evAge}s)</span>}</h3>
          {!ev && <p className="muted">Brak oceny – czekam na zamkniętą świecę M1.</p>}
          {ev && <>
            <p className="small">{ev.status_reason}</p>
            <p className="small">Tryb: <b>{ev.mode || "—"}</b> · kierunek: <b>{ev.side || "—"}</b> · ocena {tsl(ev.created_at)} · ważny do {tsl(ev.valid_until)}
              {" "}· <span title={ev.score?.definition}>score {fmtNum(ev.score?.value, 0)}/100 (heurystyka, nie prawdopodobieństwo)</span>
              {" "}· P(zdarzenia): {ev.probability?.status === "SKALIBROWANE" ? <b>{fmtNum(ev.probability.value * 100, 1)}% – {ev.probability.event}</b> :
                <span className="muted">{ev.probability?.status === "BRAK_MODELU_ZDARZENIA" ? "brak skalibrowanego modelu" : ev.probability?.status}</span>}</p>
            <ol className="checklist small" data-testid="sh-checklist">
              {(ev.checklist || []).map((c: any) => <li key={c.id} data-status={c.status}><Badge s={c.status} /> {c.label}: <span className="muted">{c.detail}</span></li>)}
            </ol>
            {ev.status === "READY" && <div className="tbl-wrap"><table className="tbl small" data-testid="sh-levels"><thead><tr><th>Poziom</th><th>Cena</th><th>Żądane (USD)</th>
              <th>Po zaokrągleniu do ticka</th><th>Różnica</th><th>Udział</th></tr></thead><tbody>
              <tr><td>Wejście (ref.)</td><td className="mono">{ev.entry_ref}</td><td colSpan={4} className="muted">{ev.side === "BUY" ? "Ask" : "Bid"}; cele liczone ponownie od rzeczywistego fill</td></tr>
              <tr><td>SL</td><td className="mono">{ev.sl}</td><td colSpan={4}>{fmtNum(Math.abs(ev.entry_ref - ev.sl), 2)} USD (z unieważnienia i zmienności; nigdy poszerzany)</td></tr>
              {(ev.tps || []).map((t: any) => <tr key={t.name}><td>{t.name}</td><td className="mono">{t.price}</td><td>{fmtNum(t.distance_requested, 2)}</td>
                <td>{fmtNum(t.distance_actual, 2)}</td><td>{fmtNum(t.rounding_diff, 4)}</td><td>{Math.round(t.share * 100)}%</td></tr>)}
            </tbody></table></div>}
            {ev.be && <p className="small">BE: po potwierdzonym {ev.be.after} – {ev.be.definition}{ev.be.offset_price ? ` (+${fmtNum(ev.be.offset_price, 3)} USD)` : ""}.
              <span className="muted"> {ev.be.note}.</span></p>}
            {ev.costs && <p className="small" data-testid="sh-costs">Koszt round-trip: {fmtNum(ev.costs.round_trip_price, 3)} USD (spread {fmtNum(ev.costs.spread, 3)})
              {!ev.costs.commission_known && <span className="warn"> · prowizja nieznana – koszt niepełny</span>} · RR netto całego cyklu {fmtNum(ev.net_rr, 2)}</p>}
            <div className="grid-2 small">
              <div><b>Za:</b><ul>{(ev.args_for || []).map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></div>
              <div><b>Przeciw:</b><ul>{(ev.args_against || []).map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></div>
            </div>
            {ev.coordination && <p className="small" data-testid="sh-coord">Koordynator: <Badge s={ev.coordination.decision} /> {ev.coordination.reason}</p>}
            {ev.risk && <div className="small" data-testid="sh-risk">Ryzyko: <Badge s={ev.risk.status} /> wolumen {ev.risk.volume} lot ({(ev.risk.legs || []).join(" / ")}),
              ryzyko {fmtNum(ev.risk.risk_money, 2)} ({fmtNum(ev.risk.risk_pct, 2)}%), ekspozycja po {fmtNum(ev.risk.gross_exposure_after, 2)} lot
              {(ev.risk.reasons || []).length > 0 && <ul>{ev.risk.reasons.map((r: string) => <li key={r} className="bad-text">{r}</li>)}</ul>}
              {(ev.risk.warnings || []).map((w: string) => <div key={w} className="warn">{w}</div>)}</div>}
          </>}
        </div>

        <div className="panel">
          <div className="chips-row"><h3>Wykres</h3>{["M1", "M5", "M15"].map((x) => <button key={x} className={`btn tiny ${tf === x ? "" : "ghost"}`} onClick={() => setTf(x)}>{x}</button>)}
            <span className="muted small">bid {chart?.quote?.bid ?? "—"} / ask {chart?.quote?.ask ?? "—"} · wiek notowania {fmtNum(chart?.quote?.age_s, 1)} s</span></div>
          <PlanChart bars={chart?.bars || []} plan={plan} setup={ev} />
          <p className="muted small">Linie: wejście, SL, TP1–TP3, BE, strefa i unieważnienie. Linie przerywane = plan (przed wejściem); ciągłe = otwarta pozycja.</p>
        </div>
      </div>

      <div className="panel" data-testid="sh-position">
        <h3>Pozycja / koszyk {strat}</h3>
        {!plan && <p className="muted">Brak otwartego planu {strat}.</p>}
        {plan && <PlanView p={plan} onClose={async () => {
          if (!confirm(`Zamknąć plan ${plan.plan_id} (wszystkie nogi)?`)) return;
          const r = await apiSend("POST", `/api/v1/sh/plans/${plan.plan_id}/close`).catch((e) => ({ ok: false, error: String(e?.message || e) }));
          setMsg(r.ok ? "Plan zamknięty." : `Nie zamknięto: ${r.error || r.state}`); load();
        }} />}
        {msg && <p className="small">{msg}</p>}
      </div>

        <div className="panel" data-testid="sh-models">
          <h3>Udział modeli ({st.models?.mode})</h3>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Moduł</th><th>Grupa korelacji</th><th>Rola</th><th>Udział</th><th>Status</th><th>Powód</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.id} data-use={r[strat]?.use}><td>{r.name}</td><td>{r.group}</td><td>{r[strat]?.role}</td><td><b>{r[strat]?.use}</b></td>
              <td><span className={`tag ${r.status === "READY" || r.status === "DETERMINISTIC_OK" ? "ok" : r.status === "ERROR" || r.status === "INCOMPATIBLE" ? "bad" : "warn"}`}>{r.status}</span></td>
              <td className="wrap-cell">{r.reason}</td></tr>)}</tbody></table></div>
          <p className="muted small">Grupa korelacji = jeden dowód. INFO/NONE nie wpływa na decyzję. Prawdopodobieństwo tylko z modelu zdarzenia READY.</p>
        </div>
      <div className="grid-2">
        <div className="panel" data-testid="sh-data">
          <h3>Dane i świeżość</h3>
          <p className="small">Jakość danych: <Badge s={dq.status === "OK" ? "PASS" : "BLOCK"}>{dq.status || "—"}</Badge> · notowanie {fmtNum(dq.quote_age_s, 1)} s · spread {fmtNum(dq.spread, 3)} (limit {ic.max_spread_usd})</p>
          <p className="small">Wiek ostatniej zamkniętej świecy: {Object.entries(dq.bar_age_s || {}).map(([k, v]) => `${k} ${v}s`).join(" · ") || "—"}</p>
          {(dq.issues || []).length > 0 && <ul className="small bad-text">{dq.issues.map((x: string) => <li key={x}>{x}</li>)}</ul>}
          <p className="small">Reżim M5: <b>{snap.regime?.state || snap.regime?.status || "—"}</b> · ATR M1 {fmtNum(snap.vol?.atr_m1, 2)} / M5 {fmtNum(snap.vol?.atr_m5, 2)} USD
            {" "}· struktura H1/M15/M5: {snap.structure_H1?.major || "—"} / {snap.structure_M15?.internal || "—"} / {snap.structure_M5?.internal || "—"}</p>
          <p className="small">Model zdarzenia: {Object.entries(st.tp_model?.per_strategy || {}).map(([k, v]: any) => `${k}: ${v.status}`).join(" · ") || st.tp_model?.status}</p>
          <ConfigEditor cfg={cfg} strat={strat} inst={st.instrument} onSaved={(m) => { setMsg(m); load(); }} />
        </div>
      </div>
    </div>);
}

function PlanView({ p, onClose }: { p: any; onClose: () => void }) {
  const pos = p.position || {};
  const b = p.basket;
  return (<>
    <p className="small"><span className="mono">{p.plan_id}</span> · {p.side} · stan <b data-testid="sh-plan-state">{p.state}</b> · tryb {p.exec_mode}
      {" "}· ticket {p.primary_ticket ?? "PAPER"}{p.hedge_ticket ? ` / hedge ${p.hedge_ticket}` : ""} · konfiguracja {p.config_hash}{" "}
      <button className="btn danger tiny" onClick={onClose} data-testid="sh-close">Zamknij plan</button></p>
    <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Część</th><th>Cena</th><th>Wolumen</th><th>Status</th><th>Fill</th></tr></thead>
      <tbody>{(pos.legs || []).map((l: any) => <tr key={l.name}><td>{l.name}</td><td className="mono">{l.price}</td><td>{l.volume}</td><td>{l.status}</td>
        <td>{l.fill_price ?? "—"}</td></tr>)}</tbody></table></div>
    <p className="small">Wejście {pos.entry} · pozostało {pos.remaining} lot · SL {pos.sl} · BE {pos.be_status} ({fmtNum(pos.be_price, 2)}) – {pos.be_definition}</p>
    {b && <div className="small" data-testid="sh-basket">
      <p>Koszyk: <b>{b.state}</b> · ochrona pozycji głównej: {b.primary?.protection} · aktywacje hedge {b.hedge?.activations}</p>
      <table className="tbl small"><thead><tr><th></th><th>Zrealizowane</th><th>Niezrealizowane</th><th>Wolumen</th></tr></thead><tbody>
        <tr><td>Pozycja główna</td><td>{fmtNum(b.primary?.realized, 2)}</td><td>{fmtNum(b.primary?.unrealized, 2)}</td><td>{b.primary?.remaining}</td></tr>
        <tr><td>Hedge</td><td>{fmtNum(b.hedge?.realized, 2)}</td><td>{fmtNum(b.hedge?.unrealized, 2)}</td><td>{b.hedge?.volume}</td></tr>
        <tr><td><b>Koszyk</b></td><td>{fmtNum(b.basket?.realized, 2)}</td><td>{fmtNum(b.basket?.unrealized, 2)}</td>
          <td>brutto {fmtNum(b.basket?.gross_exposure_lots, 2)} / netto {fmtNum(b.basket?.net_exposure_lots, 2)}</td></tr>
      </tbody></table>
      <p className="muted">{b.note}</p>
      <ul>{(b.transitions || []).slice(-6).map((t: any, i: number) => <li key={i}>{t.from} → {t.to}: {t.why}</li>)}</ul>
    </div>}
  </>);
}

function ConfigEditor({ cfg, strat, inst, onSaved }: { cfg: any; strat: string; inst: string; onSaved: (m: string) => void }) {
  const [tp3, setTp3] = useState<string>("");
  const [shares, setShares] = useState<string>("");
  useEffect(() => { setTp3(String(cfg?.tp_usd?.[2] ?? "")); setShares((cfg?.shares || []).map((x: number) => Math.round(x * 100)).join("/")); }, [JSON.stringify(cfg)]);
  const save = async () => {
    const sh = shares.split("/").map((x) => Number(x) / 100);
    const patch: any = { instruments: { [inst]: { [strat]: { shares: sh, tp_usd: [cfg.tp_usd[0], cfg.tp_usd[1], Number(tp3)] } } } };
    const r: any = await apiSend("POST", "/api/v1/sh/config", patch).catch((e) => ({ error: String(e?.message || e) }));
    onSaved(r.error ? `Odrzucono: ${r.error}` : `Zapisano wersję ${r._override_version} (hash ${r._hash}); otwarte pozycje zachowują swój plan.`);
  };
  const rollback = async () => {
    const r: any = await apiSend("POST", "/api/v1/sh/config/rollback").catch((e) => ({ error: String(e?.message || e) }));
    onSaved(r.error ? `Rollback: ${r.error}` : `Przywrócono poprzednią wersję (hash ${r._hash}).`);
  };
  return (<div className="small" data-testid="sh-config">
    <h4>Ustawienia {strat} (jedno źródło konfiguracji)</h4>
    <p>TP1 {cfg.tp_usd?.[0]} · TP2 {cfg.tp_usd?.[1]} · TP3{" "}
      {(cfg.tp3_choices || []).length ? <select aria-label="TP3" value={tp3} onChange={(e) => setTp3(e.target.value)} data-testid="sh-tp3">
        {(cfg.tp3_choices || []).map((x: number) => <option key={x} value={String(x)}>{x}</option>)}</select> :
        <input aria-label="TP3" value={tp3} onChange={(e) => setTp3(e.target.value)} size={4} />} USD
      {" "}· udziały % <input aria-label="Udziały" value={shares} onChange={(e) => setShares(e.target.value)} size={9} data-testid="sh-shares" /></p>
    <p>SL {cfg.sl_min_usd}–{cfg.sl_max_usd} USD · horyzont {cfg.horizon_minutes} min · TTL {cfg.setup_ttl_minutes} min · BE po {cfg.be_after} ({cfg.be_rule})
      {cfg.hedge && <> · hedge: ratio {cfg.hedge.ratio} (max {cfg.hedge.max_ratio}), aktywacje {cfg.hedge.max_activations}, wariant {cfg.hedge.variant}</>}</p>
    <button className="btn tiny" onClick={save} data-testid="sh-config-save">Zapisz</button>{" "}
    <button className="btn ghost tiny" onClick={rollback}>Przywróć poprzednią</button>
  </div>);
}

// ------------------------------------------------------------------------------------------------ training panel
const EX_PL: Record<string, string> = { NIE_URUCHOMIONE: "czeka", W_TOKU: "w toku", UKONCZONE: "ukończone", POMINIETE: "pominięte", BLAD_TECHNICZNY: "błąd",
  ANULOWANE: "anulowane" };
const RUN_PL: Record<string, string> = { PLANNED: "zaplanowany", RUNNING: "w toku", FINISHED: "zakończony", CANCELLED: "anulowany", UTRACONY_PROCES: "UTRACONY PROCES (proces treningu nie żyje)" };

export function TrainingPanel({ instrument }: { instrument?: string }) {
  const [inst, setInst] = useState(instrument || "XAUUSD");
  const [tab, setTab] = useState<"modele" | "start" | "postep" | "historia" | "pakiety">("modele");
  const [models, setModels] = useState<any>(null);
  const [cur, setCur] = useState<any>(null);
  const [ready, setReady] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [prof, setProf] = useState("PELNY_TRENING");
  const [months, setMonths] = useState("12");
  const [log, setLog] = useState<any>(null);
  const [cmp, setCmp] = useState<string[]>([]);
  const [cmpRes, setCmpRes] = useState<any>(null);
  const [exp, setExp] = useState<any>(null);
  const [scope, setScope] = useState("all");
  const load = () => {
    apiGet(`/api/v1/training/models?instrument=${inst}`).then(setModels).catch(() => undefined);
    apiGet("/api/v1/training").then(setCur).catch(() => undefined);
    apiGet("/api/v1/training/runs?limit=30").then((r) => setRuns(r.items)).catch(() => undefined);
  };
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [inst]);
  useEffect(() => { if (tab === "start") apiGet(`/api/v1/training/readiness?instrument=${inst}`).then(setReady).catch(() => undefined); }, [tab, inst]);
  const run = cur?.run;
  const pr = run?.progress;
  const status = run?.status_effective;
  const busy = status === "RUNNING";
  const allTasks: any[] = cur?.tasks || [];
  const trainTasks = allTasks.filter((t) => !["export", "quality", "activate", "bot", "scalp_B", "scalp_C"].includes(t.kind));
  const start = async (tasks?: string[]) => {
    const r: any = await apiSend("POST", "/api/v1/training/start", { instruments: [inst], profile: prof, months: Number(months) || undefined, tasks })
      .catch((e) => ({ started: false, reason: String(e?.message || e) }));
    setMsg(r.started ? `Uruchomiono (${tasks?.length ? tasks.join(", ") : "wszystkie modele"}) – osobny proces, postęp w zakładce Postęp.` : `Nie uruchomiono: ${r.reason}`);
    setTab("postep");
    setTimeout(load, 1500);
  };
  const act = async (path: string, body: any, ok: string) => {
    const r: any = await apiSend("POST", path, body).catch((e) => ({ ok: false, reason: String(e?.message || e) }));
    setMsg(r.ok === false || r.started === false ? `Odmowa: ${r.reason}` : ok);
    load();
  };
  const importFile = async (f: File) => {
    const r = await fetch("/api/v1/training/import", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/octet-stream", "X-MQ-CSRF": getCsrf() ?? "" },
      body: await f.arrayBuffer() });
    const j = await r.json().catch(() => ({}));
    setMsg(r.ok ? `Import: ${(j.imported || []).map((x: any) => `${x.strategy} ${x.run_id} ${x.imported ? "dodany jako kandydat" : x.reason} (${x.compatibility || ""})`).join("; ") || "brak modeli SH"}`
      + ((j.skipped || []).length ? ` · pominięte: ${j.skipped.join("; ")}` : "") + (j.reason ? ` · ${j.reason}` : "") : `Import odrzucony: ${j.detail || r.status}`);
    load();
  };
  return (
    <div className="panel" data-testid="training-panel">
      <div className="chips-row">
        <h3>Trening modeli</h3>
        <select aria-label="Instrument" value={inst} onChange={(e) => setInst(e.target.value)} data-testid="tp-inst"><option>XAUUSD</option><option>BTC</option></select>
        {(["modele", "start", "postep", "historia", "pakiety"] as const).map((k) => <button key={k} className={`btn tiny ${tab === k ? "" : "ghost"}`} onClick={() => setTab(k)}
          data-testid={`tp-tab-${k}`}>{({ modele: "Rejestr modeli", start: "Uruchom", postep: "Postęp", historia: "Historia", pakiety: "Eksport / import" })[k]}</button>)}
        {run && <span className="small">ostatni run <span className="mono">{run.run_id}</span>: <b data-testid="tp-run-status">{RUN_PL[status] ?? status}</b>
          {pr && <> · {pr.tasks_done}/{pr.tasks_total} zadań</>}</span>}
      </div>
      <p className="muted small">Trening działa w osobnym procesie, bez zleceń i bez zmiany trybu wykonania. Postęp to liczba ukończonych zadań i licznik raportowany przez trener –
        bez szacowania. Model w użyciu nigdy nie jest nadpisywany: promocja jest atomowa i odwracalna (rollback).</p>
      {msg && <p className="small" data-testid="tp-msg">{msg}</p>}

      {tab === "modele" && models && <>
        {models.mode === "OGRANICZONA" && <p className="small warn">{models.mode_note}</p>}
        <div className="tbl-wrap"><table className="tbl small" data-testid="tp-models"><thead><tr><th>Model</th><th>Rodzaj</th><th>Rola SCALPING / HEDGING</th><th>Grupa</th>
          <th>Status</th><th>Gotowość</th><th>Ostatni trening</th><th>Blokady</th><th></th></tr></thead>
          <tbody>{models.models.map((m: any) => <tr key={m.id} data-model={m.id} data-ready={m.readiness}>
            <td>{m.name}</td><td>{m.kind}</td><td>{m.SCALPING?.role} / {m.HEDGING?.role}</td><td>{m.group}</td>
            <td><span className="tag">{m.status}</span></td><td><b>{m.readiness}</b></td>
            <td className="wrap-cell">{m.requires_training ? (m.last_training ? `${m.last_training.run_id}: ${EX_PL[m.last_training.execution] ?? m.last_training.execution}, ${m.last_training.quality}` : "nigdy") : "nie wymaga treningu"}</td>
            <td className="wrap-cell">{(m.blockers || []).join("; ") || "—"}</td>
            <td>{m.requires_training && m.training && <button className="btn tiny ghost" disabled={busy} onClick={() => start([m.training])} data-testid={`tp-train-${m.id}`}>Trenuj</button>}</td>
          </tr>)}</tbody></table></div>
        {(() => { const sh = models.models.find((m: any) => m.id === "sh_tp_model"); if (!sh?.per_strategy) return null;
          return <div className="small" data-testid="tp-sh-model"><h4>Model zdarzenia SH – {sh.event}</h4>
            {Object.entries(sh.per_strategy).map(([k, v]: any) => <div key={k}><b>{k}</b>: {v.status.status} · aktywny <span className="mono">{v.active || "brak"}</span>
              {v.active_holdout && <> · holdout Brier {fmtNum(v.active_holdout.brier, 4)} vs bazowy {fmtNum(v.active_holdout.brier_base_rate, 4)}</>}
              {" "}· raport walidacji: {v.validation ? "jest" : "brak"}
              {v.active && <> <button className="btn tiny ghost" onClick={() => act("/api/v1/training/rollback", { instrument: inst, family: `sh:${k}` }, `Rollback ${k}`)}>Rollback</button></>}
              <ul>{(v.runs || []).slice().reverse().map((r: any) => <li key={r.run_id}><span className="mono">{r.run_id}</span> · {r.verdict} · n={r.n}{r.imported ? " · import" : ""}
                {r.verdict === "HOLDOUT_PASSED" && r.run_id !== v.active && <> <button className="btn tiny" onClick={() => act("/api/v1/training/sh/promote",
                  { instrument: inst, strategy: k, run_id: r.run_id }, `Promowano ${r.run_id}`)}>Promuj</button></>}</li>)}</ul></div>)}</div>; })()}
      </>}

      {tab === "start" && <div data-testid="tp-start">
        <h4>Gotowość ({inst}) {ready && <Badge s={ready.ready ? "PASS" : "BLOCK"}>{ready.ready ? "można uruchomić" : "blokada"}</Badge>}</h4>
        <ul className="small">{(ready?.checks || []).map((c: any) => <li key={c.id} data-check={c.id}><Badge s={c.ok ? "PASS" : c.blocking ? "BLOCK" : "WAIT"}>{c.ok ? "OK" : c.blocking ? "blokada" : "uwaga"}</Badge> {c.detail}</li>)}</ul>
        <div className="chips-row small">
          <select aria-label="Profil" value={prof} onChange={(e) => setProf(e.target.value)}>{Object.entries(cur?.profiles || {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}</select>
          <label>miesięcy <input aria-label="Miesiące" className="num" value={months} onChange={(e) => setMonths(e.target.value)} size={3} /></label>
        </div>
        <p className="small">Zadania (kolejność zależności: eksport → kontrola jakości → modele → aktywacja → przekazanie do bota; eksport i kontrola zawsze):</p>
        <div className="chips-row small">{trainTasks.map((t) => <label key={t.kind} className="chk"><input type="checkbox" checked={sel.includes(t.kind)}
          onChange={() => setSel(sel.includes(t.kind) ? sel.filter((x) => x !== t.kind) : [...sel, t.kind])} />{t.title}</label>)}</div>
        <button className="btn" disabled={busy || (ready && !ready.ready)} onClick={() => start(sel.length ? sel : undefined)} data-testid="tp-start-btn">
          {sel.length ? `Start wybranych (${sel.length})` : "Start wszystkich"}</button>{" "}
        {busy && <button className="btn ghost" onClick={() => act("/api/v1/training/cancel", {}, "Wysłano anulowanie (bieżące zadanie zostanie przerwane).")} data-testid="tp-cancel">Anuluj</button>}
        {!busy && run && run.status !== "FINISHED" && <button className="btn ghost" onClick={() => act("/api/v1/training/resume", { run_id: run.run_id }, "Wznowiono – ukończone zadania nie są powtarzane.")}
          data-testid="tp-resume">Wznów {run.run_id}</button>}
      </div>}

      {tab === "postep" && run && <div data-testid="tp-progress">
        <p className="small"><span className="mono">{run.run_id}</span> · {RUN_PL[status] ?? status} · profil {run.plan?.profile} · {run.plan?.synthetic ? "DANE SYNTETYCZNE (test)" : "dane z terminala"}
          {" "}· {pr?.tasks_done}/{pr?.tasks_total} zadań <progress max={pr?.tasks_total || 1} value={pr?.tasks_done || 0} />
          {pr?.current_task && <> · teraz: {pr.current_title} (od {pr.current_started_at})
            {pr.current_counter && <> · licznik {pr.current_counter.stage} {pr.current_counter.done}/{pr.current_counter.total} <progress max={pr.current_counter.total} value={pr.current_counter.done} /></>}</>}</p>
        {status === "UTRACONY_PROCES" && <p className="small bad-text">Proces treningu nie działa, a stan nie został zamknięty – użyj „Wznów” w zakładce Uruchom.</p>}
        {run.summary?.line && <p className="small">{run.summary.line}</p>}
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Instr.</th><th>Zadanie</th><th>Wykonanie</th><th>Jakość</th><th>Integracja</th><th>Czas</th><th>Szczegóły</th><th>Log</th></tr></thead>
          <tbody>{(run.tasks || []).map((t: any) => <tr key={t.id} data-exec={t.execution}><td>{t.instrument}</td><td>{t.title}</td><td>{EX_PL[t.execution] ?? t.execution}</td>
            <td>{t.quality}</td><td>{t.integration}</td><td>{t.seconds ? `${Math.round(t.seconds)} s` : ""}</td><td className="wrap-cell">{t.detail}</td>
            <td>{t.log && <button className="btn tiny ghost" onClick={() => apiGet(`/api/v1/training/runs/${run.run_id}/log?task=${encodeURIComponent(t.id)}`).then(setLog)}>log</button>}</td></tr>)}</tbody></table></div>
        {run.report_available && <p className="small"><a href={`/api/v1/training/runs/${run.run_id}/report`} target="_blank" rel="noreferrer">Raport HTML</a></p>}
        {log && <pre className="log small" data-testid="tp-log">{log.text || log.reason}</pre>}
      </div>}

      {tab === "historia" && <div data-testid="tp-history">
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th></th><th>Run</th><th>Start</th><th>Koniec</th><th>Status</th><th>Profil</th><th>Instr.</th><th>Ukończone / błędy / pominięte / anulowane</th></tr></thead>
          <tbody>{runs.map((r) => <tr key={r.run_id}><td><input type="checkbox" aria-label="porównaj" checked={cmp.includes(r.run_id)}
            onChange={() => setCmp(cmp.includes(r.run_id) ? cmp.filter((x) => x !== r.run_id) : [...cmp, r.run_id].slice(-2))} /></td>
            <td className="mono">{r.run_id}</td><td>{r.created_at}</td><td>{r.finished_at || "—"}</td><td>{RUN_PL[r.status] ?? r.status}</td><td>{r.profile}{r.synthetic ? " (synt.)" : ""}</td>
            <td>{(r.instruments || []).join(", ")}</td><td>{r.counts?.UKONCZONE} / {r.counts?.BLAD_TECHNICZNY} / {r.counts?.POMINIETE} / {r.counts?.ANULOWANE}</td></tr>)}</tbody></table></div>
        <button className="btn tiny" disabled={cmp.length !== 2} onClick={() => apiGet(`/api/v1/training/compare?a=${cmp[0]}&b=${cmp[1]}`).then(setCmpRes)} data-testid="tp-compare">Porównaj wersje</button>
        {cmpRes && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Zadanie</th><th>{cmpRes.a}</th><th>{cmpRes.b}</th><th>Zmiany</th></tr></thead>
          <tbody>{cmpRes.tasks.filter((t: any) => t.changed.length).map((t: any) => <tr key={t.task}><td>{t.title}</td>
            <td>{t.a.execution} / {t.a.quality} / {t.a.model_id || "—"}</td><td>{t.b.execution} / {t.b.quality} / {t.b.model_id || "—"}</td><td>{t.changed.join(", ")}</td></tr>)}</tbody></table>
          {!cmpRes.tasks.some((t: any) => t.changed.length) && <p className="muted small">Brak różnic w zadaniach.</p>}</div>}
      </div>}

      {tab === "pakiety" && <div data-testid="tp-packages">
        <p className="small">Pakiet zawiera: dane eksportu i ich jakość, pochodzenie, konfigurację (bez sekretów), plan i logi runu, rejestry i artefakty modeli, schematy cech,
          wersję kodu, manifest z sumami SHA-256 i polecenia odtworzenia. Brakujące elementy są wymienione w manifeście.</p>
        <div className="chips-row small">
          <select aria-label="Zakres" value={scope} onChange={(e) => setScope(e.target.value)} data-testid="tp-scope"><option value="all">cały pakiet</option>
            {(models?.models || []).filter((m: any) => m.requires_training).map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
          <button className="btn tiny" onClick={async () => { const r: any = await apiSend("POST", "/api/v1/training/export", { instrument: inst, scope }).catch((e) => ({ error: String(e?.message || e) }));
            setExp(r); }} data-testid="tp-export">Eksportuj</button>
          <label className="btn tiny ghost">Importuj pakiet<input type="file" accept=".zip" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} /></label>
        </div>
        {exp && (exp.error ? <p className="small bad-text">{exp.error}</p> : <div className="small" data-testid="tp-export-result">
          <a href={exp.download} data-testid="tp-download">{exp.file}</a> · {exp.files} plików · {Math.round(exp.bytes / 1024)} KB · sha256 <span className="mono">{exp.sha256?.slice(0, 16)}…</span>
          {exp.missing?.length > 0 && <ul className="warn">{exp.missing.map((m: string) => <li key={m}>brak: {m}</li>)}</ul>}</div>)}
      </div>}
    </div>);
}
