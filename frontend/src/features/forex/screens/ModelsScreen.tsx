// 03 MODELS & BACKTEST (E5, S3 §4). Rejestr: GET /api/v1/models/catalog?instrument=XAUUSD|BTC (stan 1:1 z katalogu). Wersje i metryki:
// /api/v1/trainhub/registry (holdout, walk-forward, ocena po kosztach – tylko z raportu). TRENING: /api/v1/trainhub/status (jobs, queue,
// data, defaults) + te same akcje co Centrum treningu 1.41 (POST /api/v1/trainhub/jobs, /activate, /rollback, /jobs/{id}/cancel).
// BACKTEST: /api/v1/sh/validation (VERIFIED_REPLAY / NOT_RUN per ścieżka). MONTE CARLO: /api/v1/montecarlo/status + raport przebiegu
// GET /api/v1/montecarlo/validations/{run_id}/report (1.42). Brak raportu -> NOT_RUN. Animacje lewego panelu: klasy REF_B 1:1.
import { useEffect, useMemo, useRef, useState } from "react";
import { apiSend } from "../../../api";
import { BRAND } from "../../../brand";
import { ComponentsCards, ResearchModulesPanel, TabICLCard } from "../../../components/Pmw141Panels";
import { fmt, fmtTime, usePoll } from "../data";
import type { ScreenProps } from "../ForexScene";

const ST_PL: Record<string, string> = { READY: "GOTOWY", RULE: "REGUŁA", NOT_TRAINED: "NIEWYTRENOWANY", TRAINING: "TRENING", DISABLED: "WYŁĄCZONY", STALE: "NIEAKTUALNY",
  ERROR: "BŁĄD", INCOMPATIBLE: "NIEZGODNY", BLOCKED_DATA: "BRAK DANYCH", EXTERNAL: "ZEWNĘTRZNY" };
// 1.46: registry model_key = "<MODEL_ID>_<BASE_TF>_H<h>" (TH_LOGREG_M5_H6) while the catalog id is lower case (th_logreg) - the case-sensitive
// startsWith never matched (no SKILL on the list, no HOLDOUT / BRIER / ECE and "NOT_RUN" in the detail although the report exists); the whole key
// form is matched so mm_breakout does not take MM_BREAKOUT_ZONES_* versions
const versionsOf = (id: unknown, versions: any[]) => {
  const re = new RegExp("^" + String(id ?? "").toUpperCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "_[A-Z0-9]+_H\\d+$");
  return versions.filter((v) => re.test(String(v?.model_key ?? "").toUpperCase()));
};
const TRAIN_DEFAULT = { models: ["TH_BASELINE", "TH_LOGREG", "TH_HGB"], base_tf: "M5", horizon: 6, k_atr: 0.25, mode: "incremental", timeframes: ["M1", "M5", "M15", "M30"], lookback_days: 90 };

export default function ModelsScreen({ engine, onSystem }: ScreenProps) {
  const [inst, setInst] = useState<"XAUUSD" | "BTC">("XAUUSD");
  const [tab, setTab] = useState("obs");
  const cat = usePoll<any>(`/api/v1/models/catalog?instrument=${inst}`, 30000);
  const st = usePoll<any>("/api/v1/trainhub/status", 10000);
  const reg = usePoll<any>(`/api/v1/trainhub/registry?instrument=${inst}`, 30000);
  const items: any[] = cat.data?.items || [];
  const [sel, setSel] = useState<string | null>(null);
  const [hl, setHl] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const screenRef = useRef<HTMLElement>(null);
  const groups = useMemo(() => [...new Set(items.map((m) => m.group || m.category))], [items]);
  const versions: any[] = reg.data?.versions || [];
  const stOf = (m: any) => (m.state === "READY" && (m.category === "RULE" || m.category === "INDICATOR") ? "RULE" : m.state);
  const cur = items.find((m) => m.id === sel) || items[0] || null;
  const job = (st.data?.jobs || []).find((j: any) => j.status === "RUNNING");
  // intro panelu: przy wejściu i zmianie instrumentu, nie przy kliknięciu
  useEffect(() => { const sc = screenRef.current; if (!sc || !items.length) return; sc.classList.remove("mb-intro"); void sc.offsetWidth; sc.classList.add("mb-intro");
    const t = setTimeout(() => sc.classList.remove("mb-intro"), 4200); return () => clearTimeout(t); }, [inst, items.length > 0]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    engine?.setScreenData(2, { jobProgress: job ? job.progress || 0 : null, groups: groups.map((g) => ({ name: String(g).slice(0, 22),
      models: items.filter((m) => (m.group || m.category) === g).map((m) => ({ id: m.id, bright: m.state === "READY" ? 1 : 0.15, training: m.state === "TRAINING", sel: cur?.id === m.id, hl: hl === m.id })) })) });
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = [[items.length, "MODELI"], [items.filter((m) => m.state === "READY").length, "GOTOWE"], [items.filter((m) => m.state === "TRAINING").length, "TRENING"],
    [items.filter((m) => m.state === "NOT_TRAINED").length, "NIEWYTRENOWANE"], [items.filter((m) => m.category === "RULE").length, "REGUŁY"]];
  const data = st.data?.data?.[inst];
  const notice = (t: string) => { setToast(t); setTimeout(() => setToast(null), 3600); };
  return (
    <section id="models-screen" aria-label="MODELS & BACKTEST" ref={screenRef} data-testid="forex-models">
      <div id="mb-head" className="ci">
        <div id="mb-title" aria-hidden="true"><span className="n">03</span>MODELS &amp; BACKTEST</div><span className="ch-sep" />
        <div id="mb-asset" className="segb" role="group" aria-label="Instrument (trenowane osobno)">{(["XAUUSD", "BTC"] as const).map((a) =>
          <button key={a} type="button" aria-pressed={inst === a} onClick={() => setInst(a)}>{a}</button>)}</div><span className="ch-sep" />
        <div id="mb-tabs" className="segb" role="group" aria-label="Widok">{[["obs", "OBSERWATORIUM"], ["train", "TRENING"], ["bt", "BACKTEST"], ["mc", "MONTE CARLO"]].map(([k, l]) =>
          <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)} data-testid={"models-tab-" + k}>{l}</button>)}</div>
        <button type="button" className="mb-ptc" data-testid="open-training-center" onClick={() => onSystem("training")}>
          {`CENTRUM TRENINGOWE ${BRAND.toUpperCase()}`}</button>{/* 1.46: marka Apollo23 zamiast starej „PEPE” (data-testid i panel „training” bez zmian) */}
        <div className="gates-sum"><span>HISTORIA MT5<b>{data?.timeframes && Object.keys(data.timeframes).length ? Object.keys(data.timeframes).join(" ") + " · " + (data.data_kind ?? "") : "BRAK EKSPORTU"}</b></span>
          <span>WORKER<b>{st.data?.queue?.running ? "PRACUJE" : (st.data?.queue?.queued ?? 0) + " W KOLEJCE"}</b></span><span>AKTYWACJA<b>RĘCZNA</b></span></div>
      </div>
      <div className="sg-wrap mb-wrap">
        <div id="mb-left" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div id="mb-sum">{counts.map(([v, l]) => <span key={l as string}><Count v={v as number} /> {l}</span>)}</div>
          <div id="mb-list" role="list" aria-label="Rejestr modeli" data-testid="models-list">
            {cat.err && <p className="empty">BŁĄD: {cat.err}</p>}
            {!cat.err && !items.length && <p className="empty">BRAK DANYCH</p>}
            {(() => { let ri = 0; return groups.map((g) => (<div key={g} style={{ display: "contents" }}>
              <div className="mbg" style={{ ["--i" as any]: ri++ }}><span>{g}</span><i /></div>
              {items.filter((m) => (m.group || m.category) === g).map((m) => { const vs = versionsOf(m.id, versions); const sk = vs.find((v) => v.active)?.holdout?.skill_vs_baseline;
                return (
                <button key={m.id} type="button" className="mbr" data-id={m.id} data-st={stOf(m)} aria-pressed={cur?.id === m.id} style={{ ["--i" as any]: ri++, ["--w" as any]: `${sk != null ? Math.max(0, Math.min(100, sk * 20)) : m.state === "TRAINING" ? Math.round((job?.progress || 0) * 100) : 0}%` }}
                  onClick={() => setSel(m.id)} onPointerEnter={() => setHl(m.id)} onPointerLeave={() => setHl(null)} {...(ri === 2 ? { "data-autofocus": "" } : {})}>
                  <span className="nm"><i className="dot" />{m.name}</span><span className="chip">{ST_PL[stOf(m)] ?? m.state_pl ?? m.state}</span><span className="sub">{m.id} · {m.category}</span>
                  <span className="sk">{sk != null ? (sk > 0 ? "+" : "") + fmt(sk * 100, 1) + "%" : ""}</span><span className="bar"><i /></span><span className="sweep" /></button>); })}</div>)); })()}
          </div>
        </div>
        <div id="mb-center" className="ci" data-alt={tab === "obs" ? "0" : "1"}>
          <div id="mb-obs" aria-label="Obserwatorium modeli: gromady = grupy, jasność = stan" onClick={(e) => { const id = engine?.nodeAt(2, e.clientX, e.clientY); if (id) setSel(id); }} />
          <div id="mb-alt">{tab === "train" && <Train st={st} inst={inst} versions={versions} reg={reg} notice={notice} />}{tab === "bt" && <Backtest inst={inst} />}{tab === "mc" && <MonteCarlo />}</div>
        </div>
        <div id="mb-right" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div id="mb-detail" data-testid="models-detail">{cur ? <ModelDetail m={cur} st={stOf(cur)} versions={versionsOf(cur.id, versions)} /> : <p className="empty">Wybierz model.</p>}</div>
        </div>
      </div>
      <div id="mb-toast" role="status" className={toast ? "show" : ""}>{toast}</div>
    </section>);
}

function Count({ v }: { v: number }) {
  const [n, setN] = useState(0);
  useEffect(() => { if (document.querySelector("[data-motion='reduced']") || matchMedia("(prefers-reduced-motion: reduce)").matches) { setN(v); return; }
    const t0 = performance.now(); let raf = 0; const st = () => { const k = Math.min(1, (performance.now() - t0) / 900); setN(Math.round(v * (1 - Math.pow(1 - k, 3)))); if (k < 1) raf = requestAnimationFrame(st); };
    raf = requestAnimationFrame(st); return () => cancelAnimationFrame(raf); }, [v]);
  return <b>{n}</b>;
}

function ModelDetail({ m, st, versions }: { m: any; st: string; versions: any[] }) {
  const act = versions.find((v) => v.active) || versions[0];
  const H = act?.holdout;
  return (<>
    <div className="dh"><span className="ic">✦</span><div><b>{m.name}</b><small>{m.id} · {m.group} · {m.category} · {m.location}</small></div><span className="lchip" data-st={st}>{ST_PL[st] ?? m.state_pl ?? m.state}</span></div>
    {H ? <div className="big"><div><b className={H.skill_vs_baseline > 0 ? "" : "na"}>{H.skill_vs_baseline != null ? (H.skill_vs_baseline > 0 ? "+" : "") + fmt(H.skill_vs_baseline * 100, 1) + "%" : "—"}</b><span>SKILL VS BAZOWY · HOLDOUT</span></div>
      <div><b>{fmt(H.brier, 4)}</b><span>BRIER</span></div><div><b>{fmt(H.ece, 4)}</b><span>BŁĄD KALIBRACJI (ECE)</span></div></div> : null}
    <div className="sec"><span>OPIS</span><span>{m.training}</span></div>
    <div className="lv2"><span>CEL</span><b>{m.purpose ?? "—"}</b><span>WEJŚCIE</span><b>{m.input ?? "—"}</b><span>WYJŚCIE</span><b>{m.output ?? "—"}</b><span>DANE</span><b>{m.required_data ?? "—"}</b>
      <span>WERSJA</span><b>{act?.version ?? "—"}</b><span>TRENOWANY</span><b>{act ? fmtTime(act.created_at, true) : "—"}</b></div>
    {m.reason && <div className="why">{m.reason}</div>}
    {act?.walk_forward ? <><div className="sec"><span>WALK-FORWARD · LOG LOSS</span><span>{act.walk_forward.folds_beating_baseline ?? ""} LEPSZE OD BAZOWEGO</span></div>
      <div className="lv2"><span>ŚREDNIO</span><b>{fmt(act.walk_forward.mean_log_loss, 4)} ± {fmt(act.walk_forward.std_log_loss, 4)}</b></div></> : <div className="why">NOT_RUN – brak raportu walidacji dla tego modelu (trening w zakładce TRENING).</div>}
    {H && <><div className="sec"><span>HOLDOUT — JEDNA OCENA</span><span /></div><div className="lv2"><span>LOG LOSS</span><b>{fmt(H.log_loss, 4)} ({fmt(H.baseline_log_loss, 4)})</b>
      <span>ACCURACY</span><b>{fmt(H.accuracy, 3)}</b><span>BAL. ACC</span><b>{fmt(H.balanced_accuracy, 3)}</b></div></>}
    {act?.trading_eval_holdout && <><div className="sec"><span>OCENA TRADINGOWA · ATR PO KOSZTACH</span><span /></div><div className="lv2"><span>SYGNAŁY</span><b>{act.trading_eval_holdout.trades ?? "—"}</b>
      <span>ŚR. NETTO</span><b>{fmt(act.trading_eval_holdout.mean_net_atr, 3)} ATR</b><span>MAX DD</span><b>{fmt(act.trading_eval_holdout.max_drawdown_atr, 2)} ATR</b></div></>}
    <div className="note">Trafność ≠ rentowność. Aktywacja zawsze ręczna (zakładka TRENING).</div></>);
}

function Train({ st, inst, versions, reg, notice }: { st: any; inst: string; versions: any[]; reg: any; notice(t: string): void }) {
  const [busy, setBusy] = useState(false);
  const jobs: any[] = st.data?.jobs || [];
  const call = async (path: string, body: any, what: string) => {
    setBusy(true);
    try { const r: any = await apiSend("POST", path, body); notice(`${what}: ${r.status ?? r.kind_pl ?? "OK"}${r.reason ? " – " + r.reason : ""}${r.id ? " · " + r.id : ""}`); st.reload(); reg.reload(); }
    catch (e: any) { notice(`${what}: BŁĄD – ${String(e?.message || e).slice(0, 200)}`); } finally { setBusy(false); }
  };
  const full = () => { if (!confirm(`Uruchomić cały proces treningu ${inst} (eksport historii MT5 → dane → trening → ocena) z profilem domyślnym? Zadanie działa w osobnym procesie; nie aktywuje modelu.`)) return;
    void call("/api/v1/trainhub/jobs", { kind: "FULL", instrument: inst, params: TRAIN_DEFAULT }, "Cały proces"); };
  const byKey: Record<string, any[]> = {};
  for (const v of versions) (byKey[v.model_key] ||= []).push(v);
  return (
    <div className="btc" data-testid="models-train">
      <div className="pipe">{["EKSPORT HISTORII MT5", "WALIDACJA DANYCH", "CECHY", "ETYKIETY", "PODZIAŁ CHRONOLOGICZNY", "WALK-FORWARD + EMBARGO", "KALIBRACJA", "HOLDOUT (1×)", "PACZKA", "AKTYWACJA RĘCZNA"].map((s, i) => {
        const run = jobs.find((j) => j.status === "RUNNING"); return <div key={s} className="ps" data-s={run ? (String(run.stage || "").toUpperCase().includes(s.split(" ")[0]) ? "run" : "todo") : "todo"}><i /><b>{String(i + 1).padStart(2, "0")}</b><span>{s}</span></div>; })}</div>
      <div className="acts"><button type="button" className="act" disabled={busy} onClick={full} data-testid="models-train-full">TRENUJ · CAŁY PROCES ({inst})</button></div>
      <div className="sec"><span>KOLEJKA ZADAŃ</span><span>{st.data?.queue?.note ?? "PROCES OSOBNY"}</span></div>
      {jobs.length ? <table className="jobs"><thead><tr><th>ZADANIE</th><th>INSTRUMENT</th><th>STAN</th><th>ETAP</th><th>POSTĘP</th><th /></tr></thead><tbody>
        {jobs.slice(0, 12).map((j) => <tr key={j.id}><td>{j.kind_pl ?? j.kind}</td><td>{j.instrument}</td><td>{j.status_pl ?? j.status}</td><td>{j.stage ?? ""}{j.error ? " · " + j.error : ""}</td>
          <td><span className="pb"><i style={{ width: `${Math.round((j.progress || 0) * 100)}%` }} /></span></td>
          <td>{["QUEUED", "RUNNING"].includes(j.status) && <button type="button" className="act" onClick={() => void call(`/api/v1/trainhub/jobs/${j.id}/cancel`, {}, "Anulowanie")}>ANULUJ</button>}</td></tr>)}</tbody></table>
        : <p className="empty">Brak zadań.</p>}
      <div className="sec"><span>WERSJE MODELI {inst}</span><span>METRYKI Z HOLDOUT</span></div>
      {Object.keys(byKey).length ? Object.entries(byKey).map(([key, vs]) => (
        <div key={key}><div className="sec"><span>{key} {reg.data?.active?.[key] ? "· aktywna " + reg.data.active[key] : "· brak aktywnej"}</span>
          <button type="button" className="act" disabled={busy || !reg.data?.active?.[key]} onClick={() => void call("/api/v1/trainhub/rollback", { instrument: inst, model_key: key }, "Rollback")}>ROLLBACK</button></div>
          <table className="jobs"><tbody>{vs.map((v) => <tr key={v.version}><td>{v.version}</td><td>{v.data_kind === "REAL_USER_DATA" ? "rzeczywiste" : "syntetyczne"}</td>
            <td>skill {fmt(v.holdout?.skill_vs_baseline, 3)}</td><td>Brier {fmt(v.holdout?.brier, 4)}</td>
            <td><button type="button" className="act" disabled={busy || v.active} onClick={() => void call("/api/v1/trainhub/activate", { instrument: inst, model_key: key, version: v.version }, "Aktywacja")}>{v.active ? "AKTYWNA" : "AKTYWUJ"}</button></td></tr>)}</tbody></table></div>))
        : <p className="empty">NOT_TRAINED – brak wytrenowanych wersji.</p>}
      <div className="sec"><span>MODUŁY 1.41 · SDFORMERFLOW · ETC · TABICL</span><span /></div>
      <div className="legacy-embed"><ComponentsCards /><TabICLCard /><ResearchModulesPanel /></div>
    </div>);
}

function Backtest({ inst }: { inst: string }) {
  const v = usePoll<any>(`/api/v1/sh/validation?instrument=${inst}`, 60000);
  const strats = v.data?.strategies || {};
  if (v.err) return <p className="empty">BŁĄD: {v.err}</p>;
  return (
    <div className="btc" data-testid="models-bt">{Object.entries(strats).map(([k, r]: any) => {
      // 1.46: /sh/validation = {status: VERIFIED_REPLAY, report: {metrics, variants (HEDGING), baseline, folds}} (sh/replay.report) - the table
      // waited for r.policies (never sent), so a verified replay showed "NOT_RUN – brak raportu replay"; NOT_RUN only for status NOT_RUN
      const rep = r?.report;
      const rows = (rep ? [...(rep.variants ? Object.entries(rep.variants) : [["STRATEGIA", rep.metrics]]), ["BAZOWY", rep.baseline]] : [])
        .filter(([, m]: any) => m && typeof m === "object") as [string, any][];
      return (
      <div key={k}><div className="sec"><span>REPLAY {k}</span><span>{r.status}</span></div>
        {r.status === "VERIFIED_REPLAY" && rows.length ? <table className="jobs"><thead><tr><th>WARIANT</th><th>N</th><th>WIN %</th><th>PF</th><th>WYNIK R</th><th>ŚR. R</th><th>MAX DD R</th></tr></thead>
          <tbody>{rows.map(([p, s]) => <tr key={p}><td>{p}</td><td>{s.n ?? "—"}</td><td>{s.win_rate != null ? fmt(s.win_rate * 100, 1) : "—"}</td><td>{fmt(s.profit_factor)}</td>
            <td className={s.total == null ? "" : s.total >= 0 ? "pos" : "neg"}>{fmt(s.total)}</td><td>{fmt(s.expectancy, 3)}</td><td>{fmt(s.max_drawdown)}</td></tr>)}</tbody></table>
          : r.status === "VERIFIED_REPLAY" ? <p className="note">VERIFIED_REPLAY – raport bez metryk</p>
          : <p className="note">{r.status === "ERROR" ? "BŁĄD" : r.status ?? "NOT_RUN"} – {r.reason ?? "brak raportu replay"}</p>}</div>); })}
      {!Object.keys(strats).length && <p className="empty">BRAK DANYCH</p>}
      <p className="note">Replay na zamkniętych świecach (świeca z TP i SL – SL pierwszy). Win % to częstość historyczna.</p></div>);
}

function MonteCarlo() {
  const s = usePoll<any>("/api/v1/montecarlo/status", 30000);
  const runs: any[] = s.data?.validations || [];
  const [rid, setRid] = useState<string | null>(null);
  const id = rid || runs[0]?.run_id || null;
  const rep = usePoll<any>(id ? `/api/v1/montecarlo/validations/${id}/report` : null, 600000);
  const r = rep.data?.report;
  const rel: [number, number][] = (r?.reliability || r?.test?.reliability || []).map((b: any) => [b.p_mean ?? b.pred ?? b[0], b.freq ?? b.obs ?? b[1]]).filter((x: any) => x[0] != null && x[1] != null);
  return (
    <div className="btc" data-testid="models-mc">
      <div className="sec"><span>MONTE CARLO · {s.data?.version ?? ""}</span><span>{s.data?.calibrated ? "SKALIBROWANY: " + s.data.active_calibration : "BEZ AKTYWNEGO KALIBRATORA"}</span></div>
      {!runs.length ? <p className="note">NOT_RUN – brak walidacji Monte Carlo. Uruchom ją w Centrum (montecarlo/validate) albo plikiem .bat walidacji MC.</p> : <>
        <div className="segb">{runs.map((x) => <button key={x.run_id} type="button" aria-pressed={x.run_id === id} onClick={() => setRid(x.run_id)}>{x.run_id.slice(3, 16)} · {x.verdict ?? x.status}</button>)}</div>
        {rep.err ? <p className="note">Raport niedostępny: {rep.err}</p> : !r ? <p className="empty">Ładowanie raportu…</p> :
          <div className="mcg"><div>{rel.length ? <Rel rel={rel} /> : <p className="note">Raport nie zawiera diagramu rzetelności.</p>}<small>DIAGRAM RZETELNOŚCI</small></div>
            <div className="lv2 mcl"><span>WARIANT</span><b>{r.chosen_variant ?? "—"}</b><span>WERDYKT</span><b>{r.verdict ?? "—"}</b><span>DANE</span><b>{r.data_kind ?? "—"}</b>
              <span>BRIER TEST</span><b>{fmt(r.test?.brier ?? r.brier, 4)}</b><span>BRIER BAZOWY</span><b>{fmt(r.test?.brier_baseline ?? r.brier_baseline, 4)}</b>
              <span>LOG LOSS</span><b>{fmt(r.test?.log_loss ?? r.log_loss, 4)}</b><span>PUNKTY</span><b>{r.test?.n ?? r.n ?? "—"}</b></div></div>}</>}
      <p className="note">{s.data?.note}</p></div>);
}

function Rel({ rel }: { rel: [number, number][] }) {
  const W = 220, H = 220, P = (v: number) => 8 + v * (W - 16), Q = (v: number) => H - 8 - v * (H - 16);
  return <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}><rect x="8" y="8" width={W - 16} height={H - 16} fill="none" stroke="#232834" />
    <line x1={P(0)} y1={Q(0)} x2={P(1)} y2={Q(1)} stroke="#3a4152" strokeDasharray="3 3" />
    <polyline fill="none" stroke="#e8ecff" strokeWidth="1.4" points={rel.map(([x, y]) => P(x) + "," + Q(y)).join(" ")} />
    {rel.map(([x, y], i) => <circle key={i} cx={P(x)} cy={Q(y)} r="2.2" fill="#b5a8ff" />)}</svg>;
}
