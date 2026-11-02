// Centrum treningu (1.28): MT5 export -> dataset -> training -> evaluation -> packages, per instrument (XAUUSD and BTC separately).
// Every heavy step runs as a queued job (training in a separate process); this page only submits, watches, cancels and activates.
// Training never activates a model: activation is an explicit click with a compatibility + prediction test (refused otherwise).
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { telemetry } from "../../telemetry";
import { cls, fmtNum, fmtTime } from "../../util";
import "./training-center.css";

const INSTS = ["XAUUSD", "BTC"];
const TFS = ["M1", "M5", "M15", "M30"];
const ST_TONE: Record<string, string> = { SUCCEEDED: "ok", RUNNING: "info", QUEUED: "muted", FAILED: "bad", CANCELLED: "warn", INTERRUPTED: "warn" };
const MS_TONE: Record<string, string> = { READY: "ok", TRAINING: "info", NOT_TRAINED: "muted", DISABLED: "muted", ERROR: "bad", INCOMPATIBLE: "bad" };

export default function TrainingCenterPage() {
  const [inst, setInst] = useState("XAUUSD");
  const [st, setSt] = useState<any>(null);
  const [reg, setReg] = useState<any>(null);
  const [cat, setCat] = useState<any>(null);
  const [preds, setPreds] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<any>(null);
  const [exp, setExp] = useState({ mode: "incremental", start: "", end: "", tfs: TFS, lookback_days: 90 });
  const [tr, setTr] = useState({ models: ["TH_BASELINE", "TH_LOGREG", "TH_HGB"], base_tf: "M5", horizon: 6, k_atr: 0.25, start: "", end: "" });
  const [logJob, setLogJob] = useState<string | null>(null);
  const [log, setLog] = useState("");
  const [cmp, setCmp] = useState<string[]>([]);
  const [catFilter, setCatFilter] = useState("");

  const reload = useCallback(async () => {
    try {
      const [a, b, c, d] = await Promise.all([apiGet("/api/v1/trainhub/status"), apiGet(`/api/v1/trainhub/registry?instrument=${inst}`),
        apiGet(`/api/v1/models/catalog?instrument=${inst}`), apiGet(`/api/v1/models/predictions?instrument=${inst}`)]);
      setSt(a); setReg(b); setCat(c); setPreds(d); setErr(null);
    } catch (e: any) { setErr(String(e?.message || e)); }
  }, [inst]);
  useEffect(() => { void reload(); }, [reload]);
  const busy = (st?.jobs || []).some((j: any) => ["QUEUED", "RUNNING"].includes(j.status));
  useEffect(() => { const t = setInterval(() => void reload(), busy ? 1500 : 10000); return () => clearInterval(t); }, [busy, reload]);
  useEffect(() => telemetry.subscribe((m: any) => { if (m?.type === "trainhub") void reload(); }), [reload]);
  useEffect(() => {
    if (!logJob) return;
    let alive = true;
    const pull = () => apiGet(`/api/v1/trainhub/jobs/${logJob}`).then((j) => alive && setLog(j.log_tail || "")).catch(() => undefined);
    void pull();
    const t = setInterval(pull, 1500);
    return () => { alive = false; clearInterval(t); };
  }, [logJob]);

  const submit = async (kind: string, params: any) => {
    setMsg(null);
    try {
      const r = await apiSend("POST", "/api/v1/trainhub/jobs", { kind, instrument: inst, params });
      setMsg({ ok: true, text: `${r.kind_pl}: ${r.deduplicated ? "takie zadanie już jest w kolejce – " : ""}${r.id}` });
      setLogJob(r.id);
      await reload();
    } catch (e: any) { setMsg({ ok: false, text: String(e?.message || e) }); }
  };
  const trainParams = () => ({ models: tr.models, base_tf: tr.base_tf, horizon: Number(tr.horizon), k_atr: Number(tr.k_atr),
    start: tr.start || undefined, end: tr.end || undefined });
  const expParams = () => ({ mode: exp.mode, start: exp.start || undefined, end: exp.end || undefined, timeframes: exp.tfs, lookback_days: Number(exp.lookback_days) });
  const act = async (path: string, body: any, what: string) => {
    setMsg(null);
    try {
      const r = await apiSend("POST", path, body);
      setMsg({ ok: !!r.ok, text: `${what}: ${r.status}${r.reason ? " – " + r.reason : ""}${r.prediction_test ? ` (test predykcji: różnica ${r.prediction_test.max_abs_diff ?? "?"})` : ""}`,
        detail: r.compatibility?.checks });
      await reload();
    } catch (e: any) { setMsg({ ok: false, text: String(e?.message || e) }); }
  };
  const data = st?.data?.[inst];
  const versions: any[] = reg?.versions || [];
  const byKey = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const v of versions) (m[v.model_key] ||= []).push(v);
    return m;
  }, [versions]);
  const cmpRows = versions.filter((v) => cmp.includes(v.version + v.model_key));

  return (
    <main className="page tc-page" data-testid="page-trening">
      <section className="panel tc-head">
        <div className="panel-head"><h2>Centrum treningu</h2>
          <span className="muted small">eksport MT5 → walidacja → cechy → etykiety → podział czasowy → trening → ocena → paczka → ręczna aktywacja.
            Trening działa w osobnym procesie; panel i inferencja działają dalej.</span></div>
        <div className="tc-insts" role="tablist">{INSTS.map((i) => (
          <button key={i} role="tab" aria-selected={inst === i} className={cls("btn", inst === i && "on")} onClick={() => setInst(i)} data-testid={`tc-inst-${i}`}>
            {i}{st?.data?.[i]?.symbol ? ` (${st.data[i].symbol})` : ""}</button>))}
          <span className="muted small">XAUUSD i BTC są trenowane i oceniane osobno.</span></div>
        {err && <p className="bad small" role="alert">{err}</p>}
        {msg && <div className={cls("tc-msg", msg.ok ? "ok" : "bad")} data-testid="tc-msg">{msg.text}
          {msg.detail && <ul>{msg.detail.map((c: any) => <li key={c.check} className={c.ok ? "ok" : "bad"}>{c.ok ? "✓" : "✗"} {c.check}{c.detail ? ` – ${c.detail}` : ""}</li>)}</ul>}</div>}
      </section>

      <section className="panel" data-testid="tc-data">
        <div className="panel-head"><b>1. Dane {inst}</b>
          {data?.data_kind && <span className={cls("chip", data.data_kind === "REAL_USER_DATA" ? "ok" : "warn")}><i className="dot" />{data.data_kind === "REAL_USER_DATA" ? "dane rzeczywiste" : "dane SYNTETYCZNE (test mechaniki)"}</span>}
          <span className="muted small">{data?.updated_at ? `aktualizacja ${fmtTime(data.updated_at, true)}` : "brak danych – wyeksportuj"} · {data?.parquet || ""}</span></div>
        <table className="tc-table"><thead><tr><th>Interwał</th><th>Świece</th><th>Od</th><th>Do</th><th>Dni</th><th>Jakość</th><th>Luki: weekend / sesja / brak ticków / BRAKI</th></tr></thead>
          <tbody>{TFS.map((tf) => { const r = data?.timeframes?.[tf]; return (
            <tr key={tf}><td><b>{tf}</b></td><td>{r?.rows ?? "—"}</td><td>{fmtTime(r?.first_utc, true) || "—"}</td><td>{fmtTime(r?.last_utc, true) || "—"}</td>
              <td>{r?.trading_days ?? "—"}</td><td className={r?.status === "OK" ? "ok" : r ? "bad" : ""}>{r?.status ?? "—"}</td>
              <td>{r?.gaps ? `${r.gaps.WEEKEND} / ${r.gaps.SESSION_BREAK} / ${r.gaps.NO_TICKS_SHORT} / ${r.gaps.MISSING} (${r.gaps.missing_bars} świec)` : "—"}</td></tr>); })}</tbody></table>
        {data?.costs && <p className="small muted">Koszty: spread – {data.costs.spread?.status} (z świec, nie historyczny bid/ask); prowizja – {data.costs.commission?.source}
          {data.costs.commission?.commission_per_lot_side != null ? ` ${data.costs.commission.commission_per_lot_side}/lot/stronę` : ""}; poślizg – założenie {data.costs.slippage?.value_points ?? "—"} pkt.
          Czas: {data.time_model?.model} (offset {data.time_model?.offset_seconds} s, {data.time_model?.offset_basis}).</p>}
        <div className="tc-form">
          <label>Tryb <select value={exp.mode} onChange={(e) => setExp({ ...exp, mode: e.target.value })} data-testid="tc-exp-mode">
            <option value="incremental">przyrostowy (od ostatniej świecy)</option><option value="historical">historyczny (od–do)</option></select></label>
          <label>Od (UTC) <input type="date" value={exp.start} onChange={(e) => setExp({ ...exp, start: e.target.value })} /></label>
          <label>Do (UTC) <input type="date" value={exp.end} onChange={(e) => setExp({ ...exp, end: e.target.value })} /></label>
          <label>Pierwszy eksport: dni wstecz <input type="number" min={1} max={1500} value={exp.lookback_days} onChange={(e) => setExp({ ...exp, lookback_days: Number(e.target.value) })} /></label>
          <span className="tc-tfs">{TFS.map((tf) => (
            <label key={tf}><input type="checkbox" checked={exp.tfs.includes(tf)} onChange={(e) => setExp({ ...exp, tfs: e.target.checked ? TFS.filter((x) => exp.tfs.includes(x) || x === tf) : exp.tfs.filter((x) => x !== tf) })} />{tf}</label>))}</span>
          <button className="btn" onClick={() => void submit("EXPORT", expParams())} data-testid="tc-export">Eksportuj dane</button>
          <a className="btn ghost" href={`/api/v1/trainhub/dataset.zip?instrument=${inst}&base_tf=${tr.base_tf}&horizon=${tr.horizon}`} data-testid="tc-dataset-zip">Eksportuj dataset (zip)</a>
        </div>
      </section>

      <section className="panel" data-testid="tc-train">
        <div className="panel-head"><b>2. Trening {inst}</b><span className="muted small">zadanie: klasa ruchu zamknięcia za H świec po kosztach (DOWN/FLAT/UP); walk-forward z purgingiem i embargo, nietknięty zbiór końcowy</span></div>
        <div className="tc-form">
          <span className="tc-models">{Object.entries(st?.models || {}).map(([k, m]: any) => (
            <label key={k} title={m.available ? "" : "biblioteka niedostępna"} className={m.available ? "" : "muted"}>
              <input type="checkbox" disabled={!m.available} checked={tr.models.includes(k)} data-testid={`tc-model-${k}`}
                onChange={(e) => setTr({ ...tr, models: e.target.checked ? [...tr.models, k] : tr.models.filter((x) => x !== k) })} />{m.name}</label>))}</span>
          <label>Interwał bazowy <select value={tr.base_tf} onChange={(e) => setTr({ ...tr, base_tf: e.target.value })}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label>Horyzont H (świece) <input type="number" min={1} max={96} value={tr.horizon} onChange={(e) => setTr({ ...tr, horizon: Number(e.target.value) })} /></label>
          <label>Próg k×ATR <input type="number" step={0.05} min={0} max={3} value={tr.k_atr} onChange={(e) => setTr({ ...tr, k_atr: Number(e.target.value) })} /></label>
          <label>Od <input type="date" value={tr.start} onChange={(e) => setTr({ ...tr, start: e.target.value })} /></label>
          <label>Do <input type="date" value={tr.end} onChange={(e) => setTr({ ...tr, end: e.target.value })} /></label>
        </div>
        <div className="tc-actions">
          <button className="btn" onClick={() => void submit("DATASET", trainParams())} data-testid="tc-dataset">Przygotuj dataset</button>
          <button className="btn" disabled={!tr.models.length} onClick={() => void submit("TRAIN", trainParams())} data-testid="tc-train-btn">Trenuj</button>
          <button className="btn" disabled={cmpRows.length !== 1} title="zaznacz jedną wersję w tabeli wersji"
            onClick={() => cmpRows[0] && void submit("EVALUATE", { model_key: cmpRows[0].model_key, version: cmpRows[0].version })} data-testid="tc-evaluate">Oceń zaznaczoną wersję</button>
          <button className="btn" disabled={!tr.models.length} onClick={() => void submit("FULL", { ...trainParams(), ...expParams() })} data-testid="tc-full">Uruchom cały proces</button>
        </div>
      </section>

      <section className="panel" data-testid="tc-jobs">
        <div className="panel-head"><b>3. Zadania</b><span className="muted small">{st?.queue?.note}</span></div>
        <table className="tc-table"><thead><tr><th>Zadanie</th><th>Instrument</th><th>Status</th><th>Etap</th><th>Postęp</th><th>Czas</th><th /></tr></thead>
          <tbody>{(st?.jobs || []).slice(0, 15).map((j: any) => (
            <tr key={j.id} data-testid="tc-job" data-status={j.status} data-kind={j.kind}>
              <td title={j.id}>{j.kind_pl}<br /><span className="muted small">{fmtTime(j.created_at_iso, true)}</span></td><td>{j.instrument}</td>
              <td><span className={cls("chip", ST_TONE[j.status] || "muted")}><i className="dot" />{j.status_pl}</span></td>
              <td className="small">{j.stage}{j.error ? <div className="bad">{j.error}</div> : null}</td>
              <td><div className="tc-progress"><i style={{ width: `${Math.round((j.progress || 0) * 100)}%` }} /></div></td>
              <td>{j.duration_s != null ? `${fmtNum(j.duration_s, 1)} s` : "—"}</td>
              <td className="tc-row-actions"><button className="btn tiny ghost" onClick={() => setLogJob(logJob === j.id ? null : j.id)}>Log</button>
                {["QUEUED", "RUNNING"].includes(j.status) && <button className="btn tiny danger" onClick={() => void apiSend("POST", `/api/v1/trainhub/jobs/${j.id}/cancel`, {}).then(reload)} data-testid="tc-cancel">Anuluj</button>}</td>
            </tr>))}</tbody></table>
        {logJob && <pre className="tc-log" data-testid="tc-log">{log || "(log pusty)"}</pre>}
      </section>

      <section className="panel" data-testid="tc-versions">
        <div className="panel-head"><b>4. Wersje modeli {inst}</b><span className="muted small">metryki ze zbioru końcowego (holdout); wagi i progi dobrane bez niego. Zaznacz 2 wersje, aby porównać.</span></div>
        {Object.keys(byKey).length === 0 && <p className="muted small">Brak wytrenowanych wersji.</p>}
        {Object.entries(byKey).map(([key, vs]) => (
          <div key={key} className="tc-model">
            <div className="tc-model-head"><b>{key}</b> {reg?.active?.[key] ? <span className="chip ok"><i className="dot" />aktywna {reg.active[key]}</span> : <span className="chip muted"><i className="dot" />brak aktywnej</span>}
              <button className="btn tiny ghost" disabled={!reg?.active?.[key]} onClick={() => void act("/api/v1/trainhub/rollback", { instrument: inst, model_key: key }, "Rollback")} data-testid="tc-rollback">Rollback</button>
              <button className="btn tiny ghost" disabled={!reg?.active?.[key]} onClick={() => void act("/api/v1/trainhub/deactivate", { instrument: inst, model_key: key }, "Wyłączenie")}>Wyłącz</button></div>
            <table className="tc-table"><thead><tr><th /><th>Wersja</th><th>Dane</th><th>Log loss (bazowy)</th><th>Skill</th><th>Brier</th><th>ECE</th><th>WF &gt; bazowy</th><th>Ocena po kosztach</th><th /></tr></thead>
              <tbody>{vs.map((v: any) => (
                <tr key={v.version} className={v.active ? "active" : ""} data-testid="tc-version" data-active={v.active ? "1" : "0"}>
                  <td><input type="checkbox" checked={cmp.includes(v.version + key)} onChange={(e) => setCmp(e.target.checked ? [...cmp, v.version + key] : cmp.filter((x) => x !== v.version + key))} /></td>
                  <td>{v.version}<br /><span className="muted small">{fmtTime(v.created_at, true)}</span></td>
                  <td className={v.data_kind === "REAL_USER_DATA" ? "ok" : "warn"}>{v.data_kind === "REAL_USER_DATA" ? "rzeczywiste" : "syntetyczne"}</td>
                  <td>{v.holdout?.log_loss} ({v.holdout?.baseline_log_loss})</td><td>{v.holdout?.skill_vs_baseline}</td><td>{v.holdout?.brier}</td><td>{v.holdout?.ece}</td>
                  <td>{v.walk_forward?.folds_beating_baseline}</td>
                  <td className="small">{v.trading_eval_holdout?.trades ? `${v.trading_eval_holdout.trades} sygn., śr. ${v.trading_eval_holdout.mean_net_atr} ATR netto` : "brak sygnałów"}</td>
                  <td className="tc-row-actions">
                    <button className="btn tiny" disabled={v.active} onClick={() => void act("/api/v1/trainhub/activate", { instrument: inst, model_key: key, version: v.version }, "Aktywacja")} data-testid="tc-activate">Aktywuj</button>
                    <a className="btn tiny ghost" href={`/api/v1/trainhub/package.zip?instrument=${inst}&model_key=${key}&version=${v.version}`}>Paczka</a></td>
                </tr>))}</tbody></table>
          </div>))}
        {cmpRows.length === 2 && <div className="tc-compare" data-testid="tc-compare"><b>Porównanie</b>
          <table className="tc-table"><thead><tr><th>Metryka</th>{cmpRows.map((v) => <th key={v.version}>{v.model_key}<br />{v.version}</th>)}</tr></thead>
            <tbody>{[["log loss (holdout)", (v: any) => v.holdout?.log_loss], ["bazowy log loss", (v: any) => v.holdout?.baseline_log_loss], ["skill", (v: any) => v.holdout?.skill_vs_baseline],
              ["Brier", (v: any) => v.holdout?.brier], ["ECE", (v: any) => v.holdout?.ece], ["accuracy", (v: any) => v.holdout?.accuracy], ["balanced accuracy", (v: any) => v.holdout?.balanced_accuracy],
              ["WF log loss ± std", (v: any) => `${v.walk_forward?.mean_log_loss} ± ${v.walk_forward?.std_log_loss}`], ["WF lepszy od bazowego", (v: any) => v.walk_forward?.folds_beating_baseline],
              ["skill dev (wagi)", (v: any) => v.walk_forward?.dev_skill_vs_baseline], ["ocena po kosztach: śr. ATR", (v: any) => v.trading_eval_holdout?.mean_net_atr],
              ["max obsunięcie ATR", (v: any) => v.trading_eval_holdout?.max_drawdown_atr]].map(([lab, f]: any) => (
              <tr key={lab}><td>{lab}</td>{cmpRows.map((v) => <td key={v.version}>{String(f(v) ?? "—")}</td>)}</tr>))}</tbody></table>
          <p className="muted small">Trafność ≠ rentowność. Wynik na danych syntetycznych nie mówi nic o rynku.</p></div>}
      </section>

      <section className="panel" data-testid="tc-predictions">
        <div className="panel-head"><b>5. Predykcje aktywnych paczek (wspólny kontrakt PMW-PRED-1)</b><span className="muted small">tylko informacja – nie otwierają pozycji, nie głosują w strategiach (OBSERVATION)</span></div>
        {(preds?.items || []).length === 0 ? <p className="muted small">Brak aktywnych paczek albo czekam na pierwszą zamkniętą świecę.</p> :
          <table className="tc-table"><thead><tr><th>Model</th><th>Stan</th><th>Dane do</th><th>P(DOWN / FLAT / UP)</th><th>Kalibracja</th><th>Powód niedostępności</th></tr></thead>
            <tbody>{preds.items.map((p: any) => (
              <tr key={p.model_key} data-testid="tc-pred" data-state={p.state}><td>{p.model_key}<br /><span className="muted small">{p.model_version}</span></td>
                <td><span className={cls("chip", MS_TONE[p.state] || "muted")}><i className="dot" />{p.state_pl}</span></td><td>{fmtTime(p.data_time, true) || "—"}</td>
                <td>{p.result ? `${fmtNum(p.result.DOWN, 3)} / ${fmtNum(p.result.FLAT, 3)} / ${fmtNum(p.result.UP, 3)}` : "—"}</td>
                <td className="small">{p.calibration?.status}</td><td className="small">{p.unavailable_reason || ""}</td></tr>))}</tbody></table>}
      </section>

      <section className="panel" data-testid="tc-catalog">
        <div className="panel-head"><b>6. Rejestr modeli i modułów ({cat?.items?.length || 0})</b>
          <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)} aria-label="Kategoria"><option value="">wszystkie kategorie</option>
            {Object.keys(cat?.counts_by_category || {}).map((c) => <option key={c} value={c}>{c} ({cat.counts_by_category[c]})</option>)}</select>
          <span className="muted small">{Object.entries(cat?.counts_by_state || {}).filter(([, n]) => n).map(([k, n]) => `${cat.states[k]}: ${n}`).join(" · ")}</span></div>
        <div className="tc-table-wrap"><table className="tc-table"><thead><tr><th>Moduł</th><th>Kategoria</th><th>Stan</th><th>Wynik / cel</th><th>Dane</th><th>Trening</th><th>Lokalizacja</th><th>Uzasadnienie stanu</th></tr></thead>
          <tbody>{(cat?.items || []).filter((r: any) => !catFilter || r.category === catFilter).map((r: any) => (
            <tr key={r.id} data-testid="tc-cat-row" data-state={r.state}><td><b>{r.name}</b><br /><span className="muted small">{r.id}</span></td><td>{r.category}</td>
              <td><span className={cls("chip", MS_TONE[r.state] || "muted")}><i className="dot" />{r.state_pl}</span></td><td className="small">{r.purpose}</td>
              <td className="small">{r.required_data}</td><td className="small">{r.training}</td><td className="small">{r.location}</td><td className="small">{r.reason}</td></tr>))}</tbody></table></div>
        <p className="muted small">{cat?.note}</p>
      </section>
    </main>);
}
