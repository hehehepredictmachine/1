// "Kronos AI Forecast": przetrenowany model NeoQuasar/Kronos-small (+ Kronos-Tokenizer-base) liczony lokalnie w osobnym procesie
// (.venv_kronos) na ZAMKNIĘTYCH świecach z MT5. Domyślnie SHADOW (obserwacja): prognoza nie wywołuje zleceń i nie zmienia ustawień.
// Nic tu nie jest wymyślane: brak modelu / danych / aktualności = komunikat z przyczyną, nigdy pozorna prognoza.
import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineSeries, LineStyle, type IChartApi, type Time } from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const TFS = ["M1", "M5", "M15", "M30", "H1"];
const INSTS = ["XAUUSD", "BTC"];
const USE_PL: Record<string, string> = { OBSERVE: "obserwacja (SHADOW)", REQUIRED: "warunek wymagany" };
const ST_TONE: Record<string, string> = { READY: "ok", STARTING: "warn", LOADING: "warn", INSTALLING: "warn", NOT_INSTALLED: "warn", NO_WEIGHTS: "warn",
  DISABLED: "muted", ERROR: "bad" };

function sec(iso: string) { return Math.floor(Date.parse(iso) / 1000) as Time; }

function KronosChart({ context, fc, digits }: { context: any[]; fc: any; digits: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, attributionLogo: true },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 2 },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC",
        priceFormatter: (p: number) => p.toFixed(digits) },
    });
    chart.current = c;
    const real = c.addSeries(CandlestickSeries, { title: "zamknięte świece MT5" });
    real.setData(context.map((b) => ({ time: sec(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    if (fc) {
      const pred = c.addSeries(CandlestickSeries, { upColor: "rgba(168,120,255,.35)", downColor: "rgba(168,120,255,.15)", borderVisible: true,
        borderUpColor: "#a878ff", borderDownColor: "#a878ff", wickUpColor: "#a878ff", wickDownColor: "#a878ff", lastValueVisible: true,
        priceLineVisible: false, title: "PROGNOZA Kronos (nie notowania)" });
      pred.setData(fc.pred.map((p: any) => ({ time: sec(p.t_utc), open: p.o, high: Math.max(p.h, p.o, p.c), low: Math.min(p.l, p.o, p.c), close: p.c })));
      createSeriesMarkers(pred, [{ time: sec(fc.pred[0].t_utc), position: "aboveBar", color: "#a878ff", shape: "arrowDown", text: "start prognozy" }]);
      const q = fc.uncertainty?.close_quantiles;
      if (q) {
        for (const k of ["q10", "q90"]) {
          const l = c.addSeries(LineSeries, { color: "#a878ff", lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false,
            title: k === "q10" ? "q10 ścieżek (nieskalibr.)" : "q90 ścieżek (nieskalibr.)" });
          l.setData(fc.pred.map((p: any, i: number) => ({ time: sec(p.t_utc), value: q[k][i] })));
        }
      }
      real.createPriceLine({ price: fc.last_close, color: "#888", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: "ostatnie zamknięcie" });
    }
    c.timeScale().fitContent();
    return () => { c.remove(); chart.current = null; };
  }, [context, fc, digits]);
  return <div ref={box} className="kronos-chart" style={{ height: 300 }} data-testid="kronos-chart" />;
}

export default function KronosForecastPanel() {
  const { s } = useStore();
  const [st, setSt] = useState<any>(null);
  const [inst, setInst] = useState(() => localStorage.getItem("kronos.inst") || "XAUUSD");
  const [tf, setTf] = useState(() => localStorage.getItem("kronos.tf") || "M5");
  const [fd, setFd] = useState<any>(null);
  const [hist, setHist] = useState<any[]>([]);
  const [val, setVal] = useState<any>(null);
  const [cands, setCands] = useState<any[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = s.kronos;
  const load = () => {
    apiGet("/api/v1/kronos").then(setSt).catch((e) => setMsg(String(e?.message || e)));
    apiGet(`/api/v1/kronos/forecast?instrument=${inst}&tf=${tf}`).then(setFd).catch(() => setFd(null));
    apiGet(`/api/v1/kronos/history?instrument=${inst}&tf=${tf}&limit=20`).then((r) => setHist(r.items || [])).catch(() => setHist([]));
    apiGet(`/api/v1/kronos/validation?instrument=${inst}&tf=${tf}`).then((r) => setVal(r.report)).catch(() => setVal(null));
  };
  useEffect(() => { localStorage.setItem("kronos.inst", inst); localStorage.setItem("kronos.tf", tf); load(); }, [inst, tf, live?.updated_at]);
  useEffect(() => {
    const running = st && Object.values(st.jobs || {}).some((j: any) => j && j.state === "RUNNING");
    if (!running) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [st]);
  const tgt = fd?.target;
  useEffect(() => {
    if (tgt?.state === "NO_SYMBOL") apiGet(`/api/v1/assets/${inst}/candidates`).then((r) => setCands(r.candidates || r.items || [])).catch(() => setCands(null));
    else setCands(null);
  }, [tgt?.state, inst]);

  const act = async (method: "POST" | "PUT", path: string, body?: any, ok?: string) => {
    setBusy(true);
    try {
      const r: any = await apiSend(method, path, body);
      setMsg(ok || (r?.ok === false ? r.reason : "OK"));
    } catch (e: any) {
      setMsg(String(e?.message || e));
    } finally {
      setBusy(false);
      load();
    }
  };
  const fc = fd?.forecast;
  const settings = st?.settings;
  const digits = fc?.digits ?? (inst === "BTC" ? 2 : 2);
  const tfOn = settings ? settings.timeframes.includes(tf) : true;
  const instOn = settings ? settings.instruments.includes(inst) : true;
  const job = (n: string) => st?.jobs?.[n];
  const synthetic = (fc?.data_kind || st?.data_kind) === "SYNTHETIC";
  const sc = fd?.scorecard || {};
  const dirCls = fc ? (fc.direction === "UP" ? "ok" : fc.direction === "DOWN" ? "bad" : "muted") : "muted";
  const horizonValue = settings?.horizon_bars?.[tf];
  const [hz, setHz] = useState<number | null>(null);
  useEffect(() => { setHz(horizonValue ?? null); }, [horizonValue, tf]);
  const ctxBars = useMemo(() => fd?.context || [], [fd?.context]);

  return (
    <div className="kronos-panel" data-testid="kronos-panel">
      <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
        <span className={cls("badge", ST_TONE[st?.status] || "muted")} data-testid="kronos-status">{st?.status_pl ?? "…"}</span>
        <span className="badge" data-testid="kronos-mode" title="Prognoza nie wywołuje zleceń i nie zmienia uprawnień innych modułów">
          tryb: SHADOW (obserwacja) – zgoda na zlecenia: NIE</span>
        {settings && Object.entries(settings.strategy_use || {}).map(([k, v]: any) => (
          <span key={k} className={cls("badge", v.use === "REQUIRED" ? "warn" : "muted")} data-testid={`kronos-use-${k}`}>
            {k}: {USE_PL[v.use]} ({v.timeframe})</span>))}
        {synthetic && <span className="badge warn" data-testid="kronos-synthetic">DANE SYNTETYCZNE (symulator) – nie notowania rynku</span>}
        {st?.load && <span className="small muted">urządzenie: <b>{st.load.device}</b>{st.load.device_note ? ` (${st.load.device_note})` : ""} · ładowanie {fmtNum(st.load.load_ms, 0)} ms</span>}
      </div>
      {st?.reason && st?.status !== "READY" && <p className="small warn" data-testid="kronos-reason">{st.reason}</p>}
      {st?.settings_error && <p className="small warn">{st.settings_error}</p>}

      <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
        <button className="btn" disabled={busy || job("install")?.state === "RUNNING"} data-testid="kronos-install"
          onClick={() => { if (confirm("Zainstalować Kronos? Zostanie utworzone .venv_kronos (PyTorch CPU ok. 250 MB) i pobrane oficjalne wagi z Hugging Face (ok. 120 MB).")) act("POST", "/api/v1/kronos/install", {}, "instalacja uruchomiona"); }}>
          Zainstaluj model Kronos</button>
        <button className="btn" disabled={busy || job("verify")?.state === "RUNNING"} data-testid="kronos-verify"
          onClick={() => act("POST", "/api/v1/kronos/verify", undefined, "sprawdzanie uruchomione")}>Sprawdź instalację</button>
        <button className="btn ghost" disabled={busy || !settings} data-testid="kronos-toggle"
          onClick={() => act("POST", "/api/v1/kronos/enable", { on: !settings?.enabled })}>{settings?.enabled ? "Wyłącz" : "Włącz"}</button>
        <button className="btn ghost" disabled={busy || !tfOn || !instOn} data-testid="kronos-refresh"
          onClick={() => act("POST", "/api/v1/kronos/refresh", { instrument: inst, tf }, "prognoza w kolejce")}>Odśwież prognozę</button>
        {msg && <span className="small muted" data-testid="kronos-msg">{msg}</span>}
      </div>
      {(["install", "verify"] as const).map((n) => job(n) && (
        <details key={n} className="small" open={job(n).state === "RUNNING" || job(n).state === "FAILED"} data-testid={`kronos-job-${n}`}>
          <summary>{n === "install" ? "Instalacja" : "Sprawdzenie instalacji"}: <b>{job(n).state}</b>{job(n).step ? ` (${job(n).step}/${job(n).total})` : ""} – {job(n).message}</summary>
          <JobLog name={n} />
        </details>))}

      <div className="row wrap" style={{ gap: 8, marginTop: 8, alignItems: "center" }}>
        <label>Instrument <select value={inst} onChange={(e) => setInst(e.target.value)} data-testid="kronos-inst">{INSTS.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Interwał <select value={tf} onChange={(e) => setTf(e.target.value)} data-testid="kronos-tf">{TFS.map((x) => <option key={x}>{x}{settings && !settings.timeframes.includes(x) ? " (wył.)" : ""}</option>)}</select></label>
        <label>Horyzont (świece) <input type="number" min={1} max={64} value={hz ?? ""} style={{ width: 56 }} onChange={(e) => setHz(Number(e.target.value))} data-testid="kronos-horizon" /></label>
        <button className="btn ghost" disabled={busy || !hz || hz === horizonValue} onClick={() => act("PUT", "/api/v1/kronos/settings", { horizon_bars: { [tf]: hz } }, "horyzont zapisany – od następnej prognozy")}>Zapisz horyzont</button>
        {settings && !tfOn && <button className="btn" onClick={() => act("PUT", "/api/v1/kronos/settings", { timeframes: [...settings.timeframes, tf] }, `${tf} włączony`)} data-testid="kronos-enable-tf">Licz {tf}</button>}
        {settings && tfOn && settings.timeframes.length > 1 && <button className="btn ghost" onClick={() => act("PUT", "/api/v1/kronos/settings", { timeframes: settings.timeframes.filter((x: string) => x !== tf) }, `${tf} wyłączony`)}>Nie licz {tf}</button>}
        {settings && !instOn && <button className="btn" onClick={() => act("PUT", "/api/v1/kronos/settings", { instruments: [...settings.instruments, inst] })}>Licz {inst}</button>}
      </div>

      {tgt && (
        <p className={cls("small", tgt.state === "READY" ? "muted" : "warn")} data-testid="kronos-target">
          {inst} {tf}{tgt.symbol ? ` (${tgt.symbol})` : ""}: <b>{tgt.state_pl}</b>{tgt.reason ? ` – ${tgt.reason}` : ""}
          {tgt.quality && <> · dane: {tgt.quality.status}, {tgt.quality.n} zamkniętych świec, wolumen: {tgt.quality.volume_source_pl}</>}</p>)}
      {tgt?.state === "NO_SYMBOL" && (
        <div className="card small" data-testid="kronos-symbol-choice">
          <p>Wybierz symbol brokera dla {inst} w <a href="#/ustawienia">Ustawienia → Mapowanie instrumentów</a> (nazwa i sufiks zależą od brokera – bot ich nie zgaduje).</p>
          {cands && cands.length > 0 && <p>Kandydaci z terminala: {cands.map((c: any) => <code key={c.name || c.broker_symbol} style={{ marginRight: 6 }}>{c.name || c.broker_symbol}</code>)}</p>}
        </div>)}
      {fd?.stale_note && <p className="small warn" data-testid="kronos-stale">{fd.stale_note}</p>}

      {fc ? (
        <>
          <KronosChart context={ctxBars} fc={fc} digits={digits} />
          <div className="kronos-grid" data-testid="kronos-forecast">
            <div className="card">
              <h4>Prognoza {fc.instrument} {fc.timeframe} – {fc.horizon_bars} świec</h4>
              <p>Kierunek: <span className={cls("badge", dirCls)} data-testid="kronos-direction">{fc.direction_pl}</span> <span className="small muted">({fc.band_rule}; pasmo {fmtNum(fc.neutral_band, digits)})</span></p>
              <p>Zmiana: <b data-testid="kronos-delta">{fc.delta_price >= 0 ? "+" : ""}{fmtNum(fc.delta_price, digits)}</b> w jednostkach ceny ({fc.delta_pct >= 0 ? "+" : ""}{fmtNum(fc.delta_pct, 3)}%)
                <span className="small muted"> · {fmtNum(fc.last_close, digits)} → {fmtNum(fc.pred_close_h, digits)}</span></p>
              <p className="small muted">Odległość ceny to nie wynik transakcji: wynik pieniężny zależy od wolumenu, specyfikacji kontraktu, waluty rachunku, spreadu, prowizji i poślizgu.</p>
              <p className="small">{fc.note}</p>
              {fc.ohlc_inconsistent_steps > 0 && <p className="small warn">{fc.ohlc_inconsistent_steps} prognozowanych świec ma niespójne OHLC (model liczy kanały osobno) – wykres pokazuje je bez poprawiania wartości zamknięcia.</p>}
              {fc.uncertainty && <p className="small">Pasmo q10–q90 z {fc.uncertainty.n} niezależnych ścieżek – {fc.uncertainty.note} (koszt {fmtNum(fc.uncertainty.ms, 0)} ms).</p>}
            </div>
            <div className="card small">
              <h4>Pochodzenie</h4>
              <dl className="an-kv">
                <dt>Ostatnia świeca</dt><dd>{fmtTime(fc.last_bar_open_utc, true)} (zamknięta {fmtTime(fc.last_bar_close_utc, true)})</dd>
                <dt>Utworzono</dt><dd>{fmtTime(fc.created_at, true)}</dd>
                <dt>Źródło danych</dt><dd data-testid="kronos-source">{fc.data_source} · symbol {fc.symbol}</dd>
                <dt>Wolumen</dt><dd>{fc.quality.volume_source_pl}; {fc.quality.amount_source_pl}</dd>
                <dt>Jakość</dt><dd>{fc.quality.status}{fc.quality.gaps ? `, luki w sesji: ${fc.quality.gaps.missing_open_slots}` : ""}</dd>
                <dt>Kalendarz sesji</dt><dd>{fc.calendar?.status}{fc.calendar?.crosses_break ? " – horyzont przechodzi przez przerwę w notowaniach" : ""}</dd>
                <dt>Model</dt><dd>{fc.model?.repo} @{(fc.model?.revision || "").slice(0, 10)} · {fc.tokenizer?.repo} @{(fc.tokenizer?.revision || "").slice(0, 10)}</dd>
                <dt>Obliczenie</dt><dd data-testid="kronos-timing">{fc.device} · {fmtNum(fc.compute_ms, 0)} ms · kontekst {fc.context_bars} świec · T={fc.sampling?.T}, top_p={fc.sampling?.top_p}, ziarno {fc.seed}</dd>
              </dl>
            </div>
          </div>
        </>
      ) : <p className="muted" data-testid="kronos-no-forecast">Brak prognozy dla {inst} {tf}{tgt?.reason ? ` – ${tgt.reason}` : ""}.</p>}

      <h4>Porównanie z faktycznym ruchem (rozliczone prognozy)</h4>
      <div className="table-wrap"><table className="tbl small" data-testid="kronos-scorecard">
        <thead><tr><th>Dane</th><th>Rozliczone</th><th>Oczekujące</th><th>MAE Kronos (cena po H)</th><th>MAE „ostatnia cena”</th><th>Trafność kierunku</th></tr></thead>
        <tbody>{(["REAL", "SYNTHETIC"] as const).map((k) => sc[k] && (
          <tr key={k}><td>{k === "REAL" ? "MT5 (rzeczywiste)" : "SYNTETYCZNE"}</td><td>{sc[k].settled}</td><td>{sc[k].pending}</td>
            <td>{sc[k].mae_h != null ? fmtNum(sc[k].mae_h, digits) : "—"}</td><td>{sc[k].naive_mae_h != null ? fmtNum(sc[k].naive_mae_h, digits) : "—"}</td>
            <td>{sc[k].direction_hit_rate != null ? `${fmtNum(100 * sc[k].direction_hit_rate, 1)}% z ${sc[k].direction_evaluated}` : "—"}</td></tr>))}</tbody>
      </table></div>
      <p className="small muted">Liczone tylko z prawdziwych zamkniętych świec docelowych czasów; kolejne prognozy mają nakładające się horyzonty, więc nie są niezależnymi obserwacjami. To nie jest procent skuteczności strategii.</p>

      {hist.length > 0 && (
        <details className="small" data-testid="kronos-history"><summary>Historia prognoz ({hist.length})</summary>
          <div className="table-wrap"><table className="tbl">
            <thead><tr><th>Utworzono</th><th>Świeca</th><th>Kierunek</th><th>Δ</th><th>Status</th><th>Faktycznie</th><th>Błąd</th><th>Dane</th></tr></thead>
            <tbody>{hist.map((h) => (
              <tr key={h.id}><td>{fmtTime(h.created_at, true)}</td><td>{fmtTime(h.last_bar_open_utc, true)}</td><td>{h.direction}</td><td>{fmtNum(h.delta_price, digits)}</td>
                <td>{h.outcome_status}</td><td>{h.actual_close_h != null ? fmtNum(h.actual_close_h, digits) : "—"}</td><td>{h.abs_err_h != null ? fmtNum(h.abs_err_h, digits) : "—"}</td><td>{h.data_kind}</td></tr>))}</tbody>
          </table></div>
        </details>)}

      <h4>Walidacja walk-forward na Twoich świecach</h4>
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn" disabled={busy || job("validation")?.state === "RUNNING"} data-testid="kronos-validate"
          onClick={() => act("POST", "/api/v1/kronos/validate", { instrument: inst, tf, max_origins: 300 }, "walidacja uruchomiona (osobny proces modelu)")}>Uruchom walidację {inst} {tf}</button>
        {job("validation") && <span className="small">{job("validation").state}: {job("validation").message}</span>}
      </div>
      {val ? (
        <div className="card small" data-testid="kronos-validation">
          <p>Raport <code>{val.report_id}</code> · {val.data_source} · {val.status}{val.test ? ` · test: ${val.test.first} → ${val.test.last}` : ""}</p>
          {val.test && <p>MAE Kronos {fmtNum(val.test.mae_kronos, digits)} vs „ostatnia cena” {fmtNum(val.test.mae_naive_last_price, digits)} (n={val.test.n});
            kierunek {val.test.direction_accuracy != null ? `${fmtNum(100 * val.test.direction_accuracy, 1)}%` : "—"} z {val.test.direction_n} vs momentum {val.test.momentum_accuracy_same_cases != null ? `${fmtNum(100 * val.test.momentum_accuracy_same_cases, 1)}%` : "—"};
            p = {val.test.binomial_p_vs_50pct != null ? fmtNum(val.test.binomial_p_vs_50pct, 4) : "—"}</p>}
          <p><b>{val.verdict?.positive ? "Pozytywna" : "Niepozytywna"}</b>: {val.verdict?.reason}</p>
          <p className="muted">{val.caveat}</p>
        </div>) : <p className="small muted">Brak raportu walidacji dla {inst} {tf}.</p>}

      <h4>Użycie w strategiach</h4>
      <div className="table-wrap"><table className="tbl small" data-testid="kronos-strategy-use">
        <thead><tr><th>Strategia</th><th>Rola</th><th>Interwał</th><th>Akcja</th></tr></thead>
        <tbody>{settings && Object.entries(settings.strategy_use || {}).map(([k, v]: any) => (
          <tr key={k}><td>{k}</td><td>{USE_PL[v.use]}{v.validation_report ? ` (raport ${v.validation_report})` : ""}</td><td>{v.timeframe}</td>
            <td>{v.use === "OBSERVE" ? (
              <button className="btn ghost" disabled={busy} onClick={() => {
                if (confirm(`Ustawić Kronos ${v.timeframe} jako OBOWIĄZKOWY warunek wejścia ${k}?\n\nWarunek może tylko wstrzymać setup (brak modelu, nieaktualna prognoza, kierunek przeciwny = brak wejścia). Nie otwiera pozycji i nie zmienia ryzyka, limitów, TP/SL ani STOP. Wymaga pozytywnej walidacji walk-forward na danych rzeczywistych.`))
                  act("POST", "/api/v1/kronos/strategy-use", { strategy: k, use: "REQUIRED", timeframe: v.timeframe, confirm: true });
              }}>Ustaw jako warunek…</button>) : (
              <button className="btn ghost" disabled={busy} onClick={() => act("POST", "/api/v1/kronos/strategy-use", { strategy: k, use: "OBSERVE" })}>Wróć do obserwacji</button>)}</td></tr>))}</tbody>
      </table></div>
      <p className="small muted">Kronos widzi wyłącznie OHLC (+ tick volume) i czasy zamkniętych świec – nie zna poziomów likwidacji, newsów, spreadu, prowizji, poślizgu ani pozycji.
        Zgodność z innymi modelami liczącymi na tych samych świecach nie jest niezależnym potwierdzeniem. Gotowość do prognozowania ≠ potwierdzona przewaga handlowa.
        Licencja kodu: MIT (ShiYu, Kronos); wagi: wg kart modeli NeoQuasar.</p>
    </div>
  );
}

function JobLog({ name }: { name: string }) {
  const [j, setJ] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    const f = () => apiGet(`/api/v1/kronos/job/${name}`).then((r) => alive && setJ(r.job)).catch(() => {});
    f();
    const t = setInterval(f, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [name]);
  if (!j) return null;
  const res = j.result;
  return (
    <div>
      <pre className="kronos-log" data-testid={`kronos-log-${name}`}>{(j.log || []).join("\n")}</pre>
      {res?.selftest && <p>Prognoza testowa: {res.selftest.smoke.ok ? "OK" : "BŁĄD"} ({res.selftest.smoke.ms} ms, {res.selftest.smoke.device})
        {res.selftest.reference && <> · porównanie z wynikiem autorów: <b>{res.selftest.reference.status}</b> (max różnica względna {res.selftest.reference.rows.map((r: any) => r.max_rel_diff.toExponential(1)).join(" / ")})</>}</p>}
      {j.log_file && <p className="muted">log: {j.log_file}</p>}
    </div>
  );
}
