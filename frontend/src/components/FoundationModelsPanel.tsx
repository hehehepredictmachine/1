// 1.37 "Modele prognoz": trzy przetrenowane modele liczone lokalnie, każdy we własnym procesie – Kronos-base (istniejący serwis),
// Chronos-2 (amazon/chronos-2) i FinCast (Vincent05R/FinCast v1). Ten panel tylko pokazuje i porównuje ich prognozy na tych samych
// zamkniętych świecach; nie wymyśla wartości, nie uśrednia modeli i nie zamienia regresji na prawdopodobieństwo.
// Rola w strategiach (OBSERVE / ASSIST / REQUIRED) zmienia się wyłącznie przez serwer, po pozytywnej walidacji i potwierdzeniu.
import { useEffect, useMemo, useRef, useState } from "react";
import { ColorType, createChart, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const MODELS = [
  { id: "kronos", name: "Kronos-base", color: "#a878ff" },
  { id: "chronos2", name: "Chronos-2", color: "#2fa6de" },
  { id: "fincast", name: "FinCast", color: "#e0a030" },
] as const;
const TSFM = ["chronos2", "fincast"] as const;
const PATHS = ["ACTIVE", "SCALPING", "HEDGING"] as const;
const USE_PL: Record<string, string> = { OBSERVE: "obserwacja", ASSIST: "wspomaga (może wstrzymać)", REQUIRED: "warunek wymagany" };
const ST_TONE: Record<string, string> = { READY: "ok", STARTING: "warn", LOADING: "warn", INSTALLING: "warn", NOT_INSTALLED: "warn", NO_WEIGHTS: "warn",
  RESOURCE_LIMIT: "bad", INCOMPATIBLE: "bad", DISABLED: "muted", ERROR: "bad" };
const DIR_TONE: Record<string, string> = { UP: "ok", DOWN: "bad", FLAT: "muted" };

const WRAP = { whiteSpace: "normal", minWidth: 200, maxWidth: 380 } as const;        // long reasons wrap instead of squeezing the other columns

function sec(iso: string) { return Math.floor(Date.parse(iso) / 1000) as Time; }
function store(k: string, d: string) { try { return localStorage.getItem(k) || d; } catch { return d; } }
function save(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* prywatne okno */ } }

type Line = { id: string; name: string; color: string; current: boolean; pts: { t: string; v: number }[]; q10?: number[]; q90?: number[] };

function CompareChart({ context, lines, digits }: { context: { t: string; c: number }[]; lines: Line[]; digits: number }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, attributionLogo: true },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 2 },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC",
        priceFormatter: (p: number) => p.toFixed(digits) },
    });
    const real = c.addSeries(LineSeries, { color: "#9aa", lineWidth: 2, title: "zamknięcia MT5", priceLineVisible: false });
    real.setData(context.map((b) => ({ time: sec(b.t), value: b.c })));
    for (const l of lines) {
      if (!l.pts.length) continue;
      const style = l.current ? LineStyle.Solid : LineStyle.Dotted;
      const s = c.addSeries(LineSeries, { color: l.color, lineWidth: 2, lineStyle: style, priceLineVisible: false,
        title: `${l.name}${l.current ? "" : " – NIEAKTUALNA"}` });
      s.setData(l.pts.map((p) => ({ time: sec(p.t), value: p.v })));
      for (const [k, q] of [["q10", l.q10], ["q90", l.q90]] as const) {
        if (!q || q.length !== l.pts.length || q.some((x) => x == null)) continue;
        const b = c.addSeries(LineSeries, { color: l.color, lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false,
          title: `${l.name} ${k} (nieskalibr.)` });
        b.setData(l.pts.map((p, i) => ({ time: sec(p.t), value: q[i] })));
      }
    }
    c.timeScale().fitContent();
    return () => c.remove();
  }, [context, lines, digits]);
  return <div ref={box} className="kronos-chart" style={{ height: 300 }} data-testid="fm-chart" />;
}

export default function FoundationModelsPanel() {
  const { s } = useStore();
  const [st, setSt] = useState<any>(null);
  const [inst, setInst] = useState(() => store("fm.inst", "XAUUSD"));
  const [tf, setTf] = useState(() => store("fm.tf", "M5"));
  const [on, setOn] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(store("fm.lines", "{}")); } catch { return {}; }
  });
  const [fcs, setFcs] = useState<Record<string, any>>({});
  const [cmp, setCmp] = useState<any>(null);
  const [val, setVal] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = (s as any).tsfm;
  const load = () => {
    apiGet("/api/v1/models/foundation").then(setSt).catch((e) => setMsg(String(e?.message || e)));
    apiGet(`/api/v1/models/foundation/compare?instrument=${inst}&tf=${tf}`).then(setCmp).catch(() => setCmp(null));
    apiGet(`/api/v1/models/foundation/validation?instrument=${inst}&tf=${tf}`).then((r) => setVal(r.report)).catch(() => setVal(null));
    Promise.all([
      apiGet(`/api/v1/kronos/forecast?instrument=${inst}&tf=${tf}`).catch(() => null),
      ...TSFM.map((m) => apiGet(`/api/v1/models/foundation/forecast?model=${m}&instrument=${inst}&tf=${tf}`).catch(() => null)),
    ]).then(([k, c2, fc]) => setFcs({ kronos: k, chronos2: c2, fincast: fc }));
  };
  useEffect(() => { save("fm.inst", inst); save("fm.tf", tf); load(); }, [inst, tf, live?.updated_at, (s as any).kronos?.updated_at]);
  useEffect(() => {
    const jobs = st ? [...Object.values(st.models || {}).flatMap((m: any) => Object.values(m.jobs || {})), st.jobs?.validation] : [];
    if (!jobs.some((j: any) => j && j.state === "RUNNING")) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [st]);

  const act = async (path: string, body: any, ok?: string) => {
    setBusy(true);
    try {
      const r: any = await apiSend("POST", path, body);
      setMsg(ok || (r?.ok === false ? r.reason : "OK"));
    } catch (e: any) {
      setMsg(String(e?.message || e));
    } finally {
      setBusy(false);
      load();
    }
  };
  const shown = (id: string) => on[id] !== false;
  const toggle = (id: string) => { const n = { ...on, [id]: !shown(id) }; setOn(n); save("fm.lines", JSON.stringify(n)); };

  const lines: Line[] = useMemo(() => MODELS.filter((m) => shown(m.id)).map((m) => {
    const d = fcs[m.id];
    const fc = d?.forecast;
    if (!fc) return { id: m.id, name: m.name, color: m.color, current: false, pts: [] };
    if (m.id === "kronos") {
      const q = fc.uncertainty?.close_quantiles;
      return { id: m.id, name: m.name, color: m.color, current: !!d.target?.forecast_current, pts: fc.pred.map((p: any) => ({ t: p.t_utc, v: p.c })),
        q10: q?.q10, q90: q?.q90 };
    }
    return { id: m.id, name: `${m.name} (${fc.point_kind === "median" ? "mediana" : "średnia"})`, color: m.color, current: !!d.is_current,
      pts: fc.path.map((p: any) => ({ t: p.t_utc, v: p.point })), q10: fc.path.map((p: any) => p["q0.1"]), q90: fc.path.map((p: any) => p["q0.9"]) };
  }), [fcs, on]);
  const context = useMemo(() => {
    const t = fcs.chronos2?.context?.length ? fcs.chronos2.context : fcs.fincast?.context?.length ? fcs.fincast.context : (fcs.kronos?.context || []);
    return t.map((b: any) => ({ t: b.t, c: b.c }));
  }, [fcs]);
  const digits = fcs.chronos2?.forecast?.digits ?? fcs.fincast?.forecast?.digits ?? fcs.kronos?.forecast?.digits ?? 2;
  const synthetic = st?.data_kind === "SYNTHETIC";
  const ms = st?.models || {};
  const insts: string[] = Array.from(new Set(["XAUUSD", ...TSFM.flatMap((m) => ms[m]?.instruments || [])]));
  const tfs: string[] = Array.from(new Set(["M5", "M15", ...TSFM.flatMap((m) => ms[m]?.timeframes || [])]));

  return (
    <div className="kronos-panel" data-testid="fm-panel">
      <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
        <span className="badge" title="Prognozy nie wywołują zleceń i nie zmieniają uprawnień innych modułów">tryb: SHADOW – zgoda na zlecenia: NIE</span>
        {synthetic && <span className="badge warn" data-testid="fm-synthetic">DANE SYNTETYCZNE (symulator) – nie notowania rynku</span>}
        {st?.memory_note && <span className="small muted">{st.memory_note}</span>}
        {msg && <span className="small muted" data-testid="fm-msg">{msg}</span>}
      </div>
      {st?.settings_error && <p className="small warn">{st.settings_error}</p>}

      <div className="table-wrap"><table className="tbl small" data-testid="fm-status">
        <thead><tr><th>Model</th><th>Checkpoint</th><th>Status</th><th>Urządzenie / ładowanie</th><th>Czas prognozy</th><th>Akcje</th></tr></thead>
        <tbody>
          {st?.kronos && (
            <tr data-testid="fm-row-kronos"><td><b>{st.kronos.name}</b> <span className="muted">({st.kronos.params_upstream})</span></td>
              <td style={WRAP}><code>{st.kronos.repo}@{String(st.kronos.revision).slice(0, 10)}</code><div className="muted">{st.kronos.largest_public_note}</div></td>
              <td style={WRAP}><span className={cls("badge", ST_TONE[st.kronos.status] || "muted")}>{st.kronos.status}</span>{st.kronos.reason && <div className="muted">{st.kronos.reason}</div>}</td>
              <td>{st.kronos.load ? `${st.kronos.load.device} · ${fmtNum(st.kronos.load.load_ms, 0)} ms` : "—"}</td>
              <td>{fcs.kronos?.forecast ? `${fmtNum(fcs.kronos.forecast.compute_ms, 0)} ms` : "—"}</td>
              <td className="muted" style={WRAP}>instalacja i walidacja: sekcja „Kronos AI Forecast”</td></tr>)}
          {TSFM.map((m) => {
            const x = ms[m];
            if (!x) return null;
            const job = (n: string) => x.jobs?.[`${n}_${m}`];
            return (
              <tr key={m} data-testid={`fm-row-${m}`}><td><b>{x.name}</b> <span className="muted">({x.params_upstream})</span><div className="muted">{x.license}</div></td>
                <td style={WRAP}><code>{x.repo}@{String(x.revision).slice(0, 10)}</code><div className="muted">profil {x.profile} · kontekst {x.context_len}</div></td>
                <td style={WRAP}><span className={cls("badge", ST_TONE[x.status] || "muted")} data-testid={`fm-status-${m}`}>{x.status_pl}</span>
                  {x.reason && x.status !== "READY" && <div className="muted">{x.reason}</div>}
                  {(["install", "verify"] as const).map((n) => job(n) && <div key={n} className="muted" data-testid={`fm-job-${n}-${m}`}>
                    {n === "install" ? "instalacja" : "sprawdzenie"}: <b>{job(n).state}</b>{job(n).step ? ` (${job(n).step}/${job(n).total})` : ""} – {job(n).message}</div>)}</td>
                <td>{x.load ? `${x.load.device} · ${fmtNum(x.load.load_ms, 0)} ms${x.load.rss_mb ? ` · ${fmtNum(x.load.rss_mb, 0)} MB RAM` : ""}` : "—"}</td>
                <td>{x.timing?.n ? `p50 ${fmtNum(x.timing.p50_ms, 0)} ms · p95 ${fmtNum(x.timing.p95_ms, 0)} ms (n=${x.timing.n})` : "—"}</td>
                <td><div className="row wrap" style={{ gap: 4 }}>
                  <button className="btn" disabled={busy || job("install")?.state === "RUNNING"} data-testid={`fm-install-${m}`}
                    onClick={() => { if (confirm(`Zainstalować ${x.name}? Zostanie utworzone osobne środowisko (PyTorch CPU ok. 250 MB) i pobrane oficjalne wagi z Hugging Face (${m === "fincast" ? "ok. 4 GB; ładowanie wymaga ok. 8 GB RAM" : "ok. 0,5 GB"}).`)) act("/api/v1/models/foundation/install", { model: m }, "instalacja uruchomiona"); }}>
                    Zainstaluj</button>
                  <button className="btn ghost" disabled={busy || job("verify")?.state === "RUNNING"} data-testid={`fm-verify-${m}`}
                    onClick={() => act("/api/v1/models/foundation/verify", { model: m }, "sprawdzanie uruchomione")}>Sprawdź</button>
                  <button className="btn ghost" disabled={busy || !x.enabled} data-testid={`fm-refresh-${m}`}
                    onClick={() => act("/api/v1/models/foundation/refresh", { model: m, instrument: inst, tf }, "prognoza w kolejce")}>Odśwież</button>
                </div></td></tr>);
          })}
        </tbody>
      </table></div>

      <div className="row wrap" style={{ gap: 8, marginTop: 8, alignItems: "center" }}>
        <label>Instrument <select value={inst} onChange={(e) => setInst(e.target.value)} data-testid="fm-inst">{insts.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Interwał <select value={tf} onChange={(e) => setTf(e.target.value)} data-testid="fm-tf">{tfs.map((x) => <option key={x}>{x}</option>)}</select></label>
        {MODELS.map((m) => (
          <label key={m.id} className="small" style={{ color: m.color }}>
            <input type="checkbox" checked={shown(m.id)} onChange={() => toggle(m.id)} data-testid={`fm-toggle-${m.id}`} /> {m.name}</label>))}
      </div>
      {lines.some((l) => l.pts.length) ? <CompareChart context={context} lines={lines} digits={digits} />
        : <p className="muted" data-testid="fm-no-forecast">Brak prognoz dla {inst} {tf} – stan modeli i przyczyny w tabeli powyżej.</p>}
      {lines.filter((l) => l.pts.length && !l.current).map((l) => (
        <p key={l.id} className="small warn" data-testid={`fm-stale-${l.id}`}>{l.name}: prognoza NIEAKTUALNA (linia kropkowana) – {fcs[l.id]?.stale_note || "nie dotyczy ostatniej zamkniętej świecy"}</p>))}
      <p className="small muted">Linie: Chronos-2 – mediana (kwantyl 0,5), FinCast – średnia, Kronos – średnia ścieżek próbkowanych; przerywane – kwantyle 0,1 i 0,9
        (nieskalibrowane na danych brokera). Prognozowane jest tylko zamknięcie, nie świece OHLC.</p>

      <h4>Porównanie modeli – ta sama świeca, interwał i horyzont</h4>
      {cmp && (
        <>
          <div className="table-wrap"><table className="tbl small" data-testid="fm-compare">
            <thead><tr><th>Model</th><th>Punkt</th><th>Cena po H</th><th>Zmiana</th><th>Kierunek</th><th>q10 / q90 po H</th><th>Porównywalna</th></tr></thead>
            <tbody>{(cmp.rows || []).map((r: any) => (
              <tr key={r.model} data-testid={`fm-cmp-${r.model}`}><td>{r.name}</td><td>{r.point_kind ?? "—"}</td>
                <td>{r.pred_close_h != null ? fmtNum(r.pred_close_h, digits) : "—"}</td>
                <td>{r.delta_price != null ? `${r.delta_price >= 0 ? "+" : ""}${fmtNum(r.delta_price, digits)}` : "—"}</td>
                <td>{r.direction ? <span className={cls("badge", DIR_TONE[r.direction])}>{r.direction}</span> : "—"}</td>
                <td>{r.q10_h != null && r.q90_h != null ? `${fmtNum(r.q10_h, digits)} / ${fmtNum(r.q90_h, digits)}` : "—"}</td>
                <td style={WRAP}>{r.comparable ? "tak" : <span className="muted">nie{r.reason ? ` – ${r.reason}` : !r.available ? " – brak prognozy" : !r.current ? " – nieaktualna" : ""}</span>}</td></tr>))}</tbody>
          </table></div>
          <p className="small" data-testid="fm-compare-summary">{cmp.summary ? cmp.summary.text : "Brak co najmniej jednej aktualnej prognozy dla tej samej świecy – nie ma czego porównać."}
            {cmp.summary?.conflict && <b className="warn"> Modele wskazują przeciwne kierunki.</b>}</p>
          <p className="small muted">{cmp.rule}. Świeca: {cmp.last_bar_open_utc ? fmtTime(cmp.last_bar_open_utc, true) : "—"}, horyzont {cmp.horizon_bars} świec.</p>
        </>)}

      <h4>Walidacja walk-forward: Kronos-base, Chronos-2 i FinCast vs prognoza „ostatnia cena” i momentum</h4>
      <div className="row wrap" style={{ gap: 6, alignItems: "center" }}>
        <button className="btn" disabled={busy || st?.jobs?.validation?.state === "RUNNING"} data-testid="fm-validate"
          onClick={() => act("/api/v1/models/foundation/validate", { instrument: inst, tf, max_origins: 200 }, "walidacja uruchomiona (procesy modeli)")}>
          Uruchom walidację {inst} {tf}</button>
        {st?.jobs?.validation && <span className="small" data-testid="fm-validation-job">{st.jobs.validation.state}{st.jobs.validation.step ? ` (${st.jobs.validation.step}/${st.jobs.validation.total})` : ""}: {st.jobs.validation.message}</span>}
      </div>
      {val ? (
        <div className="card small" data-testid="fm-validation">
          <p>Raport <code>{val.report_id}</code> · {val.data_source} · {val.status}{val.reason ? ` – ${val.reason}` : ""}
            {val.evaluated ? ` · punkty startu: DEV ${val.evaluated.dev}, TEST ${val.evaluated.test} (wspólne ${val.evaluated.common_test})` : ""}
            {val.duration_s != null ? ` · ${fmtNum(val.duration_s, 0)} s` : ""}</p>
          {val.models && Object.keys(val.models).length > 0 && (
            <div className="table-wrap"><table className="tbl">
              <thead><tr><th>Model</th><th>n</th><th>MAE</th><th>MAE ostatnia cena</th><th>RMSE</th><th>Kierunek (momentum)</th><th>p</th><th>Pinball / pokrycie 80%</th><th>Werdykt</th></tr></thead>
              <tbody>{Object.entries(val.models).map(([k, v]: any) => {
                const o = v.test_own || {};
                return (
                  <tr key={k}><td>{k}</td><td>{o.n}</td><td>{o.mae != null ? fmtNum(o.mae, digits) : "—"}</td><td>{o.mae_naive_last_price != null ? fmtNum(o.mae_naive_last_price, digits) : "—"}</td>
                    <td>{o.rmse != null ? fmtNum(o.rmse, digits) : "—"}</td>
                    <td>{o.direction_accuracy != null ? `${fmtNum(100 * o.direction_accuracy, 1)}% (${o.momentum_accuracy_same_cases != null ? fmtNum(100 * o.momentum_accuracy_same_cases, 1) + "%" : "—"}) z ${o.direction_n}` : "—"}</td>
                    <td>{o.binomial_p_vs_50pct != null ? fmtNum(o.binomial_p_vs_50pct, 4) : "—"}</td>
                    <td>{o.pinball != null ? `${fmtNum(o.pinball, digits)} / ${fmtNum(100 * o.coverage_80, 1)}%` : "—"}</td>
                    <td style={WRAP}><b>{v.verdict?.positive ? "pozytywny" : "niepozytywny"}</b> – {v.verdict?.reason}</td></tr>);
              })}</tbody>
            </table></div>)}
          {val.combination && <p className="muted">Łączenie: {val.combination}</p>}
          <p className="muted">{val.caveat}</p>
        </div>) : <p className="small muted">Brak raportu walidacji dla {inst} {tf}.</p>}

      <h4>Rola w strategiach</h4>
      <div className="table-wrap"><table className="tbl small" data-testid="fm-use">
        <thead><tr><th>Model</th>{PATHS.map((p) => <th key={p}>{p}</th>)}</tr></thead>
        <tbody>{TSFM.map((m) => ms[m] && (
          <tr key={m}><td>{ms[m].name}</td>{PATHS.map((p) => {
            const u = ms[m].use?.[p] || {};
            return (
              <td key={p} data-testid={`fm-use-${m}-${p}`}>{USE_PL[u.use] ?? u.use} ({u.timeframe}){u.validation_report ? <div className="muted">raport {u.validation_report}</div> : null}
                <div className="row wrap" style={{ gap: 4 }}>
                  {u.use !== "OBSERVE" && <button className="btn ghost" disabled={busy} onClick={() => act("/api/v1/models/foundation/use", { model: m, path: p, use: "OBSERVE" })}>obserwacja</button>}
                  {(["ASSIST", "REQUIRED"] as const).filter((x) => x !== u.use).map((x) => (
                    <button key={x} className="btn ghost" disabled={busy} onClick={() => {
                      if (confirm(`${ms[m].name} ${u.timeframe} jako ${x} dla ${p}?\n\nModel może tylko wstrzymać setup (${x === "REQUIRED" ? "brak modelu, nieaktualna prognoza lub brak zgodnego kierunku = brak wejścia" : "aktualna prognoza przeciwna = czekaj"}). Nie otwiera pozycji i nie zmienia ryzyka, limitów, TP/SL, Execution Lock ani STOP. Serwer wymaga pozytywnej walidacji walk-forward na danych rzeczywistych dla bieżącego checkpointu.`))
                        act("/api/v1/models/foundation/use", { model: m, path: p, use: x, timeframe: u.timeframe, confirm: true });
                    }}>{x}…</button>))}
                </div></td>);
          })}</tr>))}</tbody>
      </table></div>
      <p className="small muted">Kronos-base ma osobne ustawienia roli w sekcji „Kronos AI Forecast”. Modele widzą wyłącznie zamknięte świece (Chronos-2 opcjonalnie OHLC + tick volume
        jako przeszłe zmienne) – nie znają newsów, spreadu, prowizji, poślizgu ani pozycji. Zgodność modeli liczących na tych samych świecach nie jest niezależnym potwierdzeniem.
        Licencje: Chronos-2 – Apache-2.0 (Amazon), FinCast – Apache-2.0 (wg karty modelu Vincent05R/FinCast).</p>
    </div>
  );
}
