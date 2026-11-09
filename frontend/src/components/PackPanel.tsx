// 1.38 PMW-SH-PACK-2: the 20 SH variants (PMW_SC01–SC10 / PMW_HG01–HG10) inside the existing strategy page. Names, TFs, parameters,
// readiness and validation come from the backend catalog (/api/v1/sh/strategies) – no second list of names lives here. Levels, RR and
// hedge conditions come from the plan contract PMW-PLAN-2 (/api/v1/plans/chart?layer=PACK) – the panel never solves TP/SL itself.
// A WAIT / NO_TRADE evaluation is never drawn as an entry; the score is a heuristic, probabilities stay "brak" without a calibrated model.
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet } from "../api";
import { fmtNum } from "../util";

const TONE: Record<string, string> = { READY: "ok", WAIT: "warn", NO_TRADE: "bad", INVALIDATED: "bad", EXPIRED: "muted", ACTIVE: "ok", CLOSED: "muted",
  NOT_VALIDATED: "warn", VALIDATED: "ok", INSUFFICIENT_EVIDENCE: "warn", PASS: "ok", FAIL: "bad", BLOCK: "bad", PROCEED: "ok" };
const B = ({ s, t }: { s?: string | null; t?: string }) => <span className={`badge ${TONE[s || ""] || ""}`} title={t}>{s || "—"}</span>;
const SEC: Record<string, number> = { M1: 60, M3: 180, M5: 300, M15: 900, H1: 3600 };
const CHART_TFS = ["M1", "M3", "M5", "M15"];
const tsec = (v: any) => (typeof v === "number" ? v : Math.floor(Date.parse(String(v)) / 1000));

function PackChart({ tf, plan }: { tf: string; plan: any }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const cs = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const [bars, setBars] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const fitted = useRef<string | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, attributionLogo: true },
      timeScale: { timeVisible: true, secondsVisible: false } });
    cs.current = c.addSeries(CandlestickSeries, {});
    chart.current = c;
    return () => { c.remove(); chart.current = null; cs.current = null; lines.current = []; };
  }, []);
  useEffect(() => {                                   // generation token: a late answer for an older TF is dropped
    let alive = true;
    setErr(null);
    const ok = SEC[tf] && CHART_TFS.includes(tf);
    if (!ok) { setBars([]); setErr(`TF ${tf} nie jest obsługiwany przez wykres SH – brak zastępczego M15`); return; }
    const load = () => apiGet(`/api/v1/sh/chart?tf=${tf}&limit=240`).then((d) => { if (alive) setBars((d.bars || []).filter((b: any) => b.open_utc)); })
      .catch((e) => { if (alive) setErr(String(e?.message || e)); });
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, Math.max(10000, SEC[tf] * 100));
    return () => { alive = false; clearInterval(t); };
  }, [tf]);
  useEffect(() => {
    const c = chart.current, s = cs.current;
    if (!c || !s) return;
    s.setData(bars.map((b) => ({ time: tsec(b.open_utc) as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
    lines.current.forEach((l) => { try { s.removePriceLine(l); } catch { /* recreated */ } });
    lines.current = [];
    const col: Record<string, string> = { SL: "#ff5470", TP1: "#2fe6a0", TP2: "#2fe6a0", ENTRY: "#e8fff3", ENTRY_FILL: "#5fe3ff", HEDGE_ACTIVATION: "#ffb347", HEDGE_ENTRY: "#ffb347" };
    const drawn = new Set<string>();
    if (plan && ["READY", "ACTIVE"].includes(plan.state)) {
      for (const l of plan.levels || []) {
        const k = l.key || `${l.name}|${l.price}`;
        if (drawn.has(k) || typeof l.price !== "number") continue;
        drawn.add(k);
        lines.current.push(s.createPriceLine({ price: l.price, color: col[l.name] || "#9aa", lineStyle: l.name === "ENTRY" || l.kind === "FILL" ? LineStyle.Solid : LineStyle.Dashed,
          lineWidth: 1, axisLabelVisible: true, title: `${l.label || l.name}${plan.signal_tf !== tf ? ` (TF ${plan.signal_tf})` : ""}` }));
      }
    }
    const marks: any[] = [];
    const a = plan?.arrow;
    if (a && bars.length) {
      const at = tsec(a.time);
      const bar = [...bars].reverse().find((b) => tsec(b.open_utc) <= at);
      if (bar) marks.push({ time: tsec(bar.open_utc) as Time, position: a.position, shape: a.kind === "CONFIRMED" ? (a.side === "SELL" ? "arrowDown" : "arrowUp") : "circle",
        color: a.kind === "CONFIRMED" ? (a.side === "SELL" ? "#ff5470" : "#2fe6a0") : "#9aa", text: a.kind === "CONFIRMED" ? a.label : `WATCH ${a.label}` });
    }
    const m = createSeriesMarkers(s, marks);
    const key = `${plan?.plan_key ?? "-"}|${tf}`;
    if (fitted.current !== key && bars.length) {             // centre on the signal only when the selection changes - polling keeps zoom/pan
      fitted.current = key;
      if (a) { const at = tsec(a.time); c.timeScale().setVisibleRange({ from: (at - SEC[tf] * 60) as Time, to: (at + SEC[tf] * 20) as Time }); }
      else c.timeScale().fitContent();
    }
    return () => { if (chart.current === c) m.detach(); };
  }, [bars, plan?.plan_key, tf]);                            // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="pack-chart-wrap"><div ref={box} style={{ height: 300 }} data-testid="pack-chart" data-tf={tf} />{err && <p className="small warn">{err}</p>}</div>;
}

export default function PackPanel() {
  const [cat, setCat] = useState<any>(null);
  const [fam, setFam] = useState<"ALL" | "SCALPING" | "HEDGING">(() => { try { return (localStorage.getItem("pack.fam") as any) || "ALL"; } catch { return "ALL"; } });
  const [sel, setSel] = useState<{ id: string; tf: string } | null>(null);
  const [plans, setPlans] = useState<any>(null);
  const [hist, setHist] = useState<any[]>([]);
  const [evl, setEvl] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => apiGet("/api/v1/sh/strategies").then((d) => { if (alive) { setCat(d); setErr(null); } }).catch((e) => alive && setErr(String(e?.message || e)));
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  useEffect(() => { try { localStorage.setItem("pack.fam", fam); } catch { /* storage unavailable */ } }, [fam]);
  useEffect(() => {
    if (!sel) { setPlans(null); setHist([]); setEvl(null); return; }
    let alive = true;
    const load = () => {
      apiGet(`/api/v1/sh/pack/evaluations?strategy_id=${sel.id}&tf=${sel.tf}`).then((d) => alive && setEvl((d.items || [])[0] ?? null)).catch(() => alive && setEvl(null));
      apiGet(`/api/v1/plans/chart?layer=PACK&strategy_id=${sel.id}&tf=${sel.tf}&history=10`).then((d) => alive && setPlans(d)).catch(() => alive && setPlans(null));
      apiGet(`/api/v1/sh/signals?strategy_id=${sel.id}&tf=${sel.tf}&limit=30`).then((d) => alive && setHist(d.items || [])).catch(() => alive && setHist([]));
    };
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [sel?.id, sel?.tf]);                                      // eslint-disable-line react-hooks/exhaustive-deps
  if (err && !cat) return <div className="panel"><p className="bad-text">Pakiet 20 strategii niedostępny: {err}</p></div>;
  if (!cat) return <div className="panel"><p className="muted">Ładowanie katalogu strategii…</p></div>;
  const live: Record<string, any> = {};
  for (const x of cat.live?.items || []) live[`${x.strategy_id}|${x.signal_tf}`] = x;
  const items = (cat.items || []).filter((v: any) => fam === "ALL" || v.family === fam);
  const plan = plans ? (plans.plans || []).find((p: any) => p.plan_key === plans.primary) : null;
  const ec = plan?.economics || {};
  return (
    <div className="panel" data-testid="sh-pack">
      <div className="chips-row">
        <h3>Pakiet 20 strategii XAUUSD ({cat.pack_version})</h3>
        {(["ALL", "SCALPING", "HEDGING"] as const).map((k) => <button key={k} className={`btn tiny ${fam === k ? "" : "ghost"}`} onClick={() => setFam(k)} data-testid={`pack-fam-${k}`}>
          {k === "ALL" ? "wszystkie" : k}</button>)}
        <span className="muted small">pip XAUUSD = {cat.pip?.XAUUSD?.pip_size} USD ({cat.pip?.XAUUSD?.pip_definition}) · cykl p50 {fmtNum(cat.live?.timing?.p50_ms, 1)} ms
          {" "}· hash <span className="mono">{cat.hash}</span></span>
      </div>
      <p className="muted small">{cat.note}. SC: TP1 ≥ 25 pips, RR planu netto ≥ 2; HG: TP1 ≥ 40 pips, RR koszyka netto ≥ 3 (scenariusz celu). Dokładnie dwa TP (50/50), bez BE.
        Status walidacji per wariant – bez danych MT5 użytkownika: NOT_VALIDATED.</p>
      <div className="tbl-wrap"><table className="tbl small" data-testid="pack-table">
        <thead><tr><th>ID</th><th>Strategia</th><th>Rodzina / klaster</th><th>TF sygnału</th><th>Stan (na TF)</th><th>Polityka</th><th>Walidacja</th></tr></thead>
        <tbody>{items.map((v: any) => (
          <tr key={v.strategy_id} data-testid={`pack-row-${v.strategy_id}`}>
            <td className="mono">{v.strategy_id}</td>
            <td title={v.description}>{v.name}</td>
            <td>{v.family} · <span className="muted">{v.cluster}</span></td>
            <td>{v.signal_tfs.join(", ")}<span className="muted"> (kontekst {v.context_tfs.join(", ")})</span></td>
            <td>{v.signal_tfs.map((tf: string) => { const l = live[`${v.strategy_id}|${tf}`]; return (
              <button key={tf} className={`btn tiny ${sel?.id === v.strategy_id && sel?.tf === tf ? "" : "ghost"}`} title={l?.reason || "brak oceny"}
                onClick={() => setSel({ id: v.strategy_id, tf })} data-testid={`pack-sel-${v.strategy_id}-${tf}`}>
                {tf}: <B s={l?.status} /> <span className="muted">{l?.reason_code}</span>{l?.side ? ` ${l.side}` : ""}</button>); })}</td>
            <td className="muted">{v.management_policy_id}</td>
            <td><B s={v.validation?.status} t={v.validation?.reason} /></td>
          </tr>))}</tbody>
      </table></div>
      {sel && (
        <div className="grid-2" data-testid="pack-detail">
          <div>
            <h4>{sel.id} / {sel.tf} – plan {plan ? <B s={plan.state} /> : <span className="muted">brak planu (WAIT/NO_TRADE nie rysuje wejścia)</span>}</h4>
            {!plan && <div className="small" data-testid="pack-eval">
              {evl ? <>Bieżąca ocena: <B s={evl.status} /> <span className="mono">{evl.pack?.reason_code}</span> – {evl.status_reason}
                <ol className="checklist small">{(evl.checklist || []).map((c: any, i: number) => <li key={i} data-status={c.status}><B s={c.status} /> {c.label} <span className="muted">{c.detail}</span></li>)}</ol></>
                : <span className="muted">Brak oceny – czekam na zamkniętą świecę {sel.tf} (cykl SH po każdej zamkniętej M1).</span>}</div>}
            {plan && <>
              <p className="small">{plan.name} · {plan.side} · {plan.state_reason || plan.reason_code} · sygnał {plan.signal_bar_close} (dostępny {plan.available_at})
                {" "}· wersja <span className="mono">{plan.strategy_version}</span> · zdarzenie <span className="mono">{plan.event_hash}</span></p>
              <div className="tbl-wrap"><table className="tbl small" data-testid="pack-levels"><thead><tr><th>Poziom</th><th>Cena</th><th>Odległość</th></tr></thead><tbody>
                {(plan.levels || []).map((l: any) => <tr key={l.key}><td>{l.label || l.name}</td><td className="mono">{l.price}</td>
                  <td>{l.distance_price != null ? `${fmtNum(l.distance_price, 2)} USD / ${l.distance_pips} pips` : ""}</td></tr>)}
              </tbody></table></div>
              <p className="small" data-testid="pack-rr">RR planu netto <b>{fmtNum(ec.rr_plan_net, 2)}</b>
                {ec.rr_basket_net_target != null && <> · RR koszyka (scenariusz celu) <b>{fmtNum(ec.rr_basket_net_target, 2)}</b></>}
                {" "}· RR brutto TP1 {fmtNum(ec.rr_tp1_gross, 2)} / TP2 {fmtNum(ec.rr_tp2_gross, 2)} (pojedynczy cel, nie wynik planu)
                {" "}· koszty: <B s={ec.cost_status === "KNOWN" ? "PASS" : "WAIT"} t={ec.cost_basis} /> {ec.cost_status} ({fmtNum(ec.c_round_trip, 3)} USD round trip)</p>
              {plan.hedge && <p className="small" data-testid="pack-hedge">Hedge ({plan.hedge.policy_id}): <B s={plan.hedge.status} /> aktywacja: {plan.hedge.activation_condition}
                {plan.hedge.activation_level_if_scalar != null ? ` (próg ${fmtNum(plan.hedge.activation_level_if_scalar, 2)})` : " (warunek dynamiczny – bez linii ceny)"};
                {" "}powrót: {plan.hedge.unwind_condition}; maks. {plan.hedge.max_hedge_minutes} min, baza {plan.hedge.base_max_minutes} min
                {plan.hedge.last_decision?.progress && <> · postęp: {plan.hedge.last_decision.progress}</>}
                {plan.hedge.leg && <> · noga {plan.hedge.leg.side} {plan.hedge.leg.volume} @ {plan.hedge.leg.entry}</>}
                {plan.hedge.basket_net != null && <> · koszyk netto {fmtNum(plan.hedge.basket_net, 2)}</>}</p>}
              <p className="small muted">Prawdopodobieństwa: {plan.models?.reason}. {plan.models?.legacy_tp_model}.</p>
              <ol className="checklist small">{(plan.checklist || []).map((c: any, i: number) => <li key={i} data-status={c.status}><B s={c.status} /> {c.label} <span className="muted">{c.detail}</span></li>)}</ol>
            </>}
          </div>
          <div>
            <PackChart tf={sel.tf} plan={plan} />
            <h4>Historia sygnałów {sel.id} / {sel.tf}</h4>
            <div className="tbl-wrap"><table className="tbl small" data-testid="pack-history"><thead><tr><th>Czas</th><th>Kierunek</th><th>Status</th><th>Powód</th></tr></thead><tbody>
              {hist.map((h: any) => <tr key={h.signal_id}><td>{new Date(h.created_at * 1000).toISOString().slice(5, 16).replace("T", " ")}</td><td>{h.side}</td><td><B s={h.status} /></td>
                <td className="wrap-cell">{h.status_reason}</td></tr>)}
              {!hist.length && <tr><td colSpan={4} className="muted">brak sygnałów READY tego wariantu (oceny WAIT nie trafiają do historii)</td></tr>}
            </tbody></table></div>
          </div>
        </div>)}
    </div>);
}
