// PMW-UPD-07 Structure Intelligence: MTF structure matrix (cells of the SAME parent MTF snapshot), Manual Trade Pad (explicit user
// actions through the shared gateway; LOCKED blocks real mutations), models / jobs (SHADOW pointer by hand), zone manager with revision
// check and the Black-76 calculator. The browser computes nothing analytical; every number comes from the server.
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { fmtNum, fmtTime } from "../util";

const ROLE_PL: Record<string, string> = {
  NECKLINE_BREAK: "wybicie neckline", RETEST_HOLD: "utrzymany retest", SWEEP_RECLAIM: "sweep i powrót", TREND_PULLBACK: "korekta w trendzie",
  COMPRESSION: "kompresja", BREAKOUT_FAILURE: "nieudane wybicie", MID_RANGE: "środek zakresu", STRUCTURE_ONLY: "tylko struktura", NO_STRUCTURAL_CONTEXT: "brak kontekstu",
};

export function StructureMatrix({ snap }: { snap: any }) {
  const si = snap?.structure_intelligence;
  if (!snap) return null;
  if (!si) return <div className="card" data-testid="mtf-structure"><h3>Struktura i świece</h3><p className="small muted">Warstwa struktury jeszcze nie policzona dla tego snapshotu.</p></div>;
  if (si.status === "ERROR") return <div className="card" data-testid="mtf-structure"><h3>Struktura i świece</h3><p className="small bad">Błąd warstwy struktury ({si.error}) – dashboard działa bez niej.</p></div>;
  const fc = si.forecast || {};
  return (
    <div className="card" data-testid="mtf-structure">
      <h3>Struktura, formacje, świece i MITP <span className="muted small">(parent {si.parent_snapshot_id} · {si.snapshot_id} · {si.build_ms} ms)</span></h3>
      <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>TF</th><th>HH/HL/LH/LL</th><th>Trend (wewn./nadrz.)</th><th>Ostatnie zdarzenie</th><th>Formacja</th>
        <th>Rola świecy</th><th>MITP (stan / głos)</th><th>Strefa</th></tr></thead>
        <tbody>{snap.timeframes.map((r: any) => {
          const c = r.structure || {};
          const s = c.structure || {};
          return <tr key={r.tf} data-tf={r.tf}><td><b>{r.tf}</b></td>
            {c.status !== "OK" ? <td colSpan={7} className="muted">{c.status ?? "—"}</td> : <>
              <td>{s.last_high?.label ?? "—"} / {s.last_low?.label ?? "—"}</td><td>{s.trend_internal} / {s.trend_major}</td>
              <td title={s.last_event?.label ?? ""}>{s.last_event ? `${s.last_event.kind} @ ${fmtNum(s.last_event.level, 2)} (${s.last_event.bar_t?.slice(11, 16)})` : "—"}</td>
              <td>{c.pattern ? `${c.pattern.type} · ${c.pattern.state} · ${c.pattern.geometry_quality}` : "—"}</td>
              <td title={(c.candle_role?.reason_codes || []).join(", ")}>{ROLE_PL[c.candle_role?.role] ?? c.candle_role?.role ?? "—"}{c.candle_role?.role_direction && c.candle_role.role_direction !== "NEUTRAL" ? ` (${c.candle_role.role_direction})` : ""}</td>
              <td>{c.mitp ? `${c.mitp.held_state ?? "—"} / ${c.mitp.current_vote ?? "—"}` : "—"}</td>
              <td>{c.zone ? `${c.zone.zone_id?.slice(-16)} · ${c.zone.distance_atr} ATR` : "—"}</td></>}
          </tr>;
        })}</tbody></table></div>
      <p className="small" data-testid="mtf-neutral-quotes">Neutralizacja ROC20: {si.neutralization?.raw != null ? `raw ${fmtNum(si.neutralization.raw, 5)} · ekspozycja ${fmtNum(si.neutralization.exposure, 5)} · reszta ${fmtNum(si.neutralization.residual, 5)}` : "—"} ({si.neutralization?.status ?? "—"})
        · Kwotowania Bid/Ask: faza {si.quotes?.phase ?? si.quotes?.status ?? "—"}{si.quotes?.clock ? ` (zegar ${si.quotes.clock})` : ""} <span className="muted">– hipotezy lokalnego modelu, nie sygnał</span></p>
      {si.divergences?.length > 0 && <ul className="small" data-testid="mtf-divergences">{si.divergences.map((d: string) => <li key={d}>{d}</li>)}</ul>}
      <div data-testid="mtf-forecast">{fc.forecast_status === "OK" ? <>
        <p className="small"><b>Prognoza ruchu M1</b> (model {fc.family} {fc.artifact_id}, rola {fc.role}, emisja {fmtTime(fc.as_of, true)}) – rozkład końca horyzontu, nie trajektoria; kierunek ≠ zlecenie.</p>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>h</th><th>DOWN</th><th>FLAT</th><th>UP</th><th>q10–q50–q90 (cena)</th><th>koniec</th><th>kalibracja</th></tr></thead>
          <tbody>{fc.heads.map((h: any) => <tr key={h.h_bars}><td>{h.h_bars} M1</td><td>{fmtNum(h.p_down * 100, 1)}%</td><td>{fmtNum(h.p_flat * 100, 1)}%</td><td>{fmtNum(h.p_up * 100, 1)}%</td>
            <td>{fmtNum(h.price_q10, 2)} – {fmtNum(h.price_q50, 2)} – {fmtNum(h.price_q90, 2)}</td><td>{h.expected_end?.slice(11, 16)}</td><td>{h.calibration}</td></tr>)}</tbody></table></div></>
        : <p className="small muted">Prognoza ruchu: brak ({fc.reason ?? fc.forecast_status ?? "—"}) – pokazana tylko analiza deterministyczna.</p>}</div>
    </div>);
}

export function ManualPadCard() {
  const { s } = useStore();
  const [f, setF] = useState<any>({ side: "BUY", sl: "", tp: "", sizing_mode: "RISK_PCT", risk_pct: "0.5", lots: "", risk_basis: "equity" });
  const [plan, setPlan] = useState<any>(null);
  const [intent, setIntent] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rev, setRev] = useState(1);
  const run = async (fn: () => Promise<any>) => { setErr(null); try { return await fn(); } catch (e: any) { setErr(String(e?.message || e)); return null; } };
  const doPlan = () => run(async () => { const p = await apiSend("POST", "/api/v1/manual/plan", f); setPlan(p); setIntent(null); setRes(null); });
  const doIntent = () => run(async () => setIntent(await apiSend("POST", "/api/v1/manual/intents", { plan_id: plan.plan_id })));
  const doExec = () => run(async () => setRes(await apiSend("POST", `/api/v1/manual/intents/${intent.intent_id}/execute`, { action_revision: 1 })));
  const manage = (action: string, extra: any = {}) => run(async () => { setRes(await apiSend("POST", `/api/v1/manual/intents/${intent.intent_id}/manage`, { action, action_revision: rev, ...extra })); setRev(rev + 1); });
  const lock = s.execution_lock ?? "LOCKED";
  return (
    <div className="card" data-testid="manual-pad">
      <h3>Manual Trade Pad <span className="muted small">(jawne akcje użytkownika; tryb {s.mode?.mode ?? "—"}; Execution Lock: {lock})</span></h3>
      <p className="small muted">Plan → intencja → wykonanie przez wspólny gateway. LOCKED blokuje każdą rzeczywistą zmianę rachunku; PAPER używa silnika PAPER. Brak ukrytego „ponów”.</p>
      <div className="form-row">
        <select aria-label="Strona" value={f.side} onChange={(e) => setF({ ...f, side: e.target.value })}><option>BUY</option><option>SELL</option></select>
        <input aria-label="SL (cena)" placeholder="SL" value={f.sl} onChange={(e) => setF({ ...f, sl: e.target.value })} inputMode="decimal" />
        <input aria-label="TP (cena)" placeholder="TP" value={f.tp} onChange={(e) => setF({ ...f, tp: e.target.value })} inputMode="decimal" />
        <select aria-label="Tryb wielkości" value={f.sizing_mode} onChange={(e) => setF({ ...f, sizing_mode: e.target.value })}><option value="RISK_PCT">ryzyko %</option><option value="FIXED">stały lot</option></select>
        {f.sizing_mode === "RISK_PCT" ? <input aria-label="Ryzyko %" value={f.risk_pct} onChange={(e) => setF({ ...f, risk_pct: e.target.value })} inputMode="decimal" />
          : <input aria-label="Loty" placeholder="loty" value={f.lots} onChange={(e) => setF({ ...f, lots: e.target.value })} inputMode="decimal" />}
        <button className="btn" onClick={doPlan} data-testid="pad-plan">Plan</button>
      </div>
      {err && <p className="bad small" data-testid="pad-error">{err}</p>}
      {plan && <div className="small" data-testid="pad-plan-out">
        <p className="mono">{plan.side} {plan.lots} lot · wejście {plan.entry} · SL {plan.sl} (żądany {plan.sl_requested}) · TP {plan.tp ?? "—"} · ryzyko brutto {fmtNum(plan.loss_at_sl_gross, 2)} · netto {plan.risk_net ?? "nieznane"}
          · RR brutto {plan.rr_gross ?? "—"} / netto {plan.rr_net ?? "—"} · prowizja {plan.commission_round_turn ?? "NIEZNANA"} ({plan.commission_source}) · wygasa {plan.expires_at?.slice(11, 19)}</p>
        {plan.reason_codes.length > 0 && <p className="warn">Blokady planu: {plan.reason_codes.join(", ")}</p>}
        {!intent ? <button className="btn" onClick={doIntent} disabled={!plan.execution_eligible} data-testid="pad-intent">Utwórz intencję</button>
          : <p>Intencja <code>{intent.intent_id}</code> <button className="btn" onClick={doExec} data-testid="pad-exec">Wykonaj ({s.mode?.mode})</button>{" "}
            <button className="btn ghost" onClick={() => manage("BREAK_EVEN", { offset_points: 0 })}>BE (cena wejścia)</button>{" "}
            <button className="btn ghost" onClick={() => manage("PARTIAL_CLOSE", { volume: plan.volume_limits[0] })}>Częściowe zamknięcie</button>{" "}
            <button className="btn ghost" onClick={() => manage("CLOSE")}>Zamknij pozycje intencji</button></p>}
      </div>}
      {res && <p className="small mono" data-testid="pad-result">{res.status} {res.reason ?? ""} {res.ticket ? `ticket ${res.ticket}` : ""} {res.items ? JSON.stringify(res.items) : ""}</p>}
    </div>);
}

function Black76Card() {
  const [f, setF] = useState({ forward: "2000", strike: "2000", sigma: "0.2", t_years: "0.02", rate: "0" });
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => { setErr(null); try { setR(await apiSend("POST", "/api/v1/black76/price", Object.fromEntries(Object.entries(f).map(([k, v]) => [k, +v])))); } catch (e: any) { setErr(String(e?.message || e)); } };
  return (
    <div className="card" data-testid="black76">
      <h3>Black-76 (PMW-BLACK76-2.0.0)</h3>
      <p className="small muted">Czysta wycena modelowa. N(d2) to prawdopodobieństwo w mierze Q modelu – nie prognoza CFD ani P(zysk); p_touch nie jest szacowane. Stopa jako ułamek (0.05 = 5%).</p>
      <div className="form-row">{(Object.keys(f) as (keyof typeof f)[]).map((k) => <input key={k} aria-label={k} placeholder={k} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} inputMode="decimal" />)}
        <button className="btn" onClick={go}>Wyceń</button></div>
      {err && <p className="bad small">{err}</p>}
      {r && <p className="small mono">call {fmtNum(r.call, 4)} · put {fmtNum(r.put, 4)} · Δc {fmtNum(r.delta_call, 4)} · Γ {r.gamma == null ? r.gamma_reason : fmtNum(r.gamma, 6)} · vega {fmtNum(r.vega, 4)}
        · Q(F&gt;K) {fmtNum(r.p_above_strict, 4)} · parity {r.parity_residual?.toExponential(2)}{r.degenerate ? " · przypadek zdegenerowany (v=0)" : ""}</p>}
    </div>);
}

function ZonesCard({ asset }: { asset: string }) {
  const [d, setD] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => apiGet(`/api/v1/lab/zones?asset=${asset}`).then(setD).catch((e) => setMsg(String(e?.message || e)));
  useEffect(() => { load(); }, [asset]);
  const act = async (fn: () => Promise<any>) => { setMsg(null); try { await fn(); load(); } catch (e: any) { setMsg(String(e?.message || e)); } };
  return (
    <div className="card" data-testid="zones-manager">
      <h3>Strefy Supply/Demand – magazyn (as-of) <span className="muted small">snapshot: {d?.snapshot ?? "—"}</span></h3>
      {msg && <p className="bad small">{msg}</p>}
      <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Strefa</th><th>TF</th><th>Rodzaj</th><th>Zakres</th><th>Stan</th><th>Testy</th><th>Ocena</th><th>Rew.</th><th></th></tr></thead>
        <tbody>{(d?.zones || []).slice(-40).reverse().map((z: any) => <tr key={z.zone_id}><td className="mono">{z.zone_id.slice(-22)}</td><td>{z.tf}</td><td>{z.kind}</td>
          <td>{fmtNum(z.bottom, 2)}–{fmtNum(z.top, 2)}</td><td>{z.state}{z.flags?.length ? ` (${z.flags.join(",")})` : ""}</td><td>{z.touch_count}</td><td title="ocena regułowa, nie prawdopodobieństwo">{z.score?.rating ?? z.quality}</td><td>{z.revision}</td>
          <td><button className="link" onClick={() => act(() => apiSend("PATCH", `/api/v1/lab/zones/${encodeURIComponent(z.zone_id)}`, { expected_revision: z.revision, state: "ARCHIVED", reason: "UI" }))}>archiwizuj</button>{" "}
            <button className="link" onClick={() => act(() => apiSend("DELETE", `/api/v1/lab/zones/${encodeURIComponent(z.zone_id)}?expected_revision=${z.revision}`))}>usuń</button></td></tr>)}
          {!d?.zones?.length && <tr><td colSpan={9} className="muted">Brak stref w magazynie.</td></tr>}</tbody></table></div>
    </div>);
}

function NeutralCard({ asset }: { asset: string }) {
  const [d, setD] = useState<any>(null);
  useEffect(() => { const load = () => apiGet(`/api/v1/structure-intelligence/neutralization?asset=${asset}&limit=60`).then(setD).catch(() => undefined); load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [asset]);
  const l = d?.last;
  return (
    <div className="card" data-testid="neutral-card">
      <h3>Neutralizacja sygnału ({d?.profile ?? "SIGNAL_NEUTRALIZATION_ROLLING_V1"})</h3>
      <p className="small muted">{d?.note} Sygnał {d?.signal_id}; czynniki {(d?.factors || []).join(", ")}. Stary M08 = {d?.legacy_profile} (bez zmian).</p>
      {l ? <dl className="an-kv small"><dt>Status</dt><dd>{l.status}{l.eligible ? " · kwalifikowany" : " · niekwalifikowany"}</dd>
        <dt>Raw / ekspozycja / reszta</dt><dd>{fmtNum(l.raw, 6)} / {fmtNum(l.exposure, 6)} / {fmtNum(l.residual, 6)}</dd>
        <dt>z reszty / z raw</dt><dd>{l.z_residual == null ? "null" : fmtNum(l.z_residual, 2)} / {l.z_raw == null ? "null" : fmtNum(l.z_raw, 2)}</dd>
        <dt>Dopasowanie</dt><dd>beta {(l.beta || []).map((b: number) => fmtNum(b, 5)).join(", ")} · R² w oknie {fmtNum(l.r2_in_sample, 3)} · rank {l.rank} · cond {l.condition ? l.condition.toExponential(2) : "—"} · wiek {l.fit_age_s ?? "—"} s</dd>
        <dt>Poza oknem</dt><dd>corr(reszta, zmienność) {d?.diagnostics?.prequential_corr_residual_volatility == null ? "null" : fmtNum(d.diagnostics.prequential_corr_residual_volatility, 3)} · corr(raw, zmienność) {d?.diagnostics?.prequential_corr_raw_volatility == null ? "null" : fmtNum(d.diagnostics.prequential_corr_raw_volatility, 3)}</dd></dl>
        : <p className="small muted">Brak wyniku (rozgrzewka – wymaga zamkniętych świec M1).</p>}
    </div>);
}

function QuotesCard() {
  const [q, setQ] = useState<any>(null);
  const [qq, setQq] = useState<any>(null);
  useEffect(() => { const load = () => { apiGet("/api/v1/structure-intelligence/quotes").then(setQ).catch(() => undefined); apiGet("/api/v1/structure-intelligence/quote-quality").then(setQq).catch(() => undefined); };
    load(); const t = setInterval(load, 2000); return () => clearInterval(t); }, []);
  return (
    <div className="card wide" data-testid="quotes-card">
      <h3>Kinematyka Bid/Ask (MQ_NEWTONIAN_QUOTES_V2) – faza <b>{q?.phase ?? q?.status ?? "—"}</b></h3>
      <p className="small muted">{q?.note ?? "Brak danych tickowych."} Zegar: {q?.clock?.mode ?? "—"}; flagi: {(q?.flags || []).join(", ") || "brak"}; spread {q?.spread?.level != null ? fmtNum(q.spread.level, 3) : "—"} (efektywność {q?.spread?.efficiency == null ? "null" : fmtNum(q.spread.efficiency, 2)}).</p>
      {q?.sides && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Strona</th><th>Skala (n_eff)</th><th>Status</th><th>v [pkt/s]</th><th>a [pkt/s²]</th><th>z_v</th><th>z_a</th><th>span s</th><th>wiek s</th><th>punkt zwrotu</th></tr></thead>
        <tbody>{(["BID", "ASK"] as const).flatMap((sd) => Object.entries(q.sides[sd] || {}).map(([N, f]: [string, any]) => <tr key={sd + N}><td>{sd}</td><td>{N} ({fmtNum(f.n_eff, 1)})</td><td>{f.status}</td>
          <td>{fmtNum(f.velocity_points_s, 3)}</td><td>{fmtNum(f.acceleration_points_s2, 4)}</td><td>{f.z_v == null ? "—" : fmtNum(f.z_v, 2)}</td><td>{f.z_a == null ? "—" : fmtNum(f.z_a, 2)}</td>
          <td>{fmtNum(f.span_s, 1)}</td><td>{fmtNum(f.side_age_s, 1)}</td><td>{f.turning_status === "OK" ? `${fmtNum(f.turning_time_s, 1)} s ± ${fmtNum(f.turning_time_se, 1)}` : f.turning_status ?? "—"}</td></tr>))}</tbody></table></div>}
      <details className="small"><summary>Scoreboard prognoz (dojrzałe, poza próbą)</summary>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Strumień</th><th>n</th><th>UNSCORED_GAP</th><th>MAE</th><th>MAE persistence</th><th>R² vs persistence</th><th>pokrycie pasma</th></tr></thead>
          <tbody>{Object.entries(qq?.scoreboard || {}).map(([k, v]: [string, any]) => <tr key={k}><td>{k}</td><td>{v.n}</td><td>{v.unscored_gap}</td><td>{fmtNum(v.mae, 4)}</td><td>{fmtNum(v.mae_persistence, 4)}</td>
            <td>{v.r2_vs_persistence == null ? "null" : fmtNum(v.r2_vs_persistence, 3)}</td><td>{v.band_coverage == null ? "MODEL_BAND_UNCALIBRATED" : fmtNum(v.band_coverage, 2)}</td></tr>)}</tbody></table></div></details>
    </div>);
}

export function StructurePage() {
  const { s } = useStore();
  const asset = s.assets?.active || "XAUUSD";
  const [m, setM] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => apiGet(`/api/v1/structure-intelligence/models?asset=${asset}`).then(setM).catch((e) => setMsg(String(e?.message || e)));
  useEffect(() => { load(); }, [asset]);
  useEffect(() => {
    if (!job || job.status !== "RUNNING") return;
    const t = setInterval(() => apiGet(`/api/v1/structure-intelligence/jobs/${job.job_id}`).then((j) => { setJob(j); if (j.status !== "RUNNING") load(); }).catch(() => undefined), 1500);
    return () => clearInterval(t);
  }, [job?.job_id, job?.status]);
  const start = async (kind: string, extra: any = {}) => { setMsg(null); try { setJob(await apiSend("POST", "/api/v1/structure-intelligence/jobs", { kind, asset, ...extra })); } catch (e: any) { setMsg(String(e?.message || e)); } };
  const runs = Object.entries(m?.runs || {}).slice(-8).reverse() as [string, any][];
  return (
    <div data-testid="page-struktura">
      <div className="page-head"><h1>Structure Intelligence – {asset}</h1></div>
      <div className="an-grid">
        <div className="card wide" data-testid="si-models"><h3>Modele ruchu M1 (STRUCTURE_MOVE_M1_V1) i kontekstu setupu</h3>
          <p className="small muted">Profil wskaźników: {m?.indicator_profile?.version} ({m?.indicator_profile?.source}, hash {m?.indicator_profile?.hash}). SHADOW: {m?.shadow?.STRUCTURE_MOVE_M1_V1?.candidate_id ?? "brak"}.
            Wykonanie: {m?.execution}. Holdout otwierany wyłącznie przez evaluate-holdout (CLI), jednorazowo.</p>
          <p><button className="btn" onClick={() => start("dataset")}>Zbuduj dataset</button>{" "}<button className="btn" onClick={() => start("calibrate")}>Kalibruj wskaźniki (dev)</button>{" "}
            <button className="btn" onClick={() => start("train", { profile: "quick", families: ["LOGREG", "XGB", "MQ_RESNEXT1D_V2", "MQ_SEW_RESNET1D_V2", "MQ_SEW_RESNEXT_EB_V1"] })}>Trening quick (smoke)</button>{" "}
            <button className="btn" onClick={() => start("train", { profile: "standard", families: ["LOGREG", "XGB", "MQ_RESNEXT1D_V2", "MQ_SEW_RESNET1D_V2", "MQ_SEW_RESNEXT_EB_V1"] })}>Trening standard</button>{" "}
            <button className="btn ghost" onClick={async () => { await apiSend("POST", "/api/v1/structure-intelligence/models/rollback", { asset }).catch((e) => setMsg(String(e?.message || e))); load(); }}>Cofnij SHADOW</button></p>
          <p><button className="btn" onClick={() => start("train", { profile: "standard", families: ["MQ_SEW_RESNET1D_V2", "MQ_SEW_RESNEXT_EB_V1"], sew_operators: ["ADD", "AND", "IAND"] })}>Operatory SEW ADD/AND/IAND</button>{" "}
            <button className="btn" onClick={() => start("experiment", { experiment: "MQ_NEUTRAL_REACTION_V1", families: ["LOGREG", "XGB"], profile: "standard" })}>Eksperyment neutralizacji</button>{" "}
            <button className="btn" onClick={() => start("tick_export", { days: 7 })}>Eksport ticków (7 dni)</button>{" "}
            <button className="btn" onClick={() => start("tick_replay")}>Replay ticków</button>{" "}
            <button className="btn" onClick={() => start("experiment", { experiment: "MQ_QUOTE_CONTEXT_REACTION_V1", families: ["LOGREG", "XGB"], profile: "standard" })}>Eksperyment kontekstu kwotowań</button></p>
          {job && <p className="small" data-testid="si-job">Zadanie {job.job_id} ({job.kind}): <b>{job.status}</b> {job.error ?? ""} {job.status === "RUNNING" && <button className="link" onClick={() => apiSend("POST", `/api/v1/structure-intelligence/jobs/${job.job_id}/cancel`)}>Anuluj</button>}
            <br /><span className="muted">{(job.log || []).slice(-3).join(" · ")}</span></p>}
          {msg && <p className="bad small">{msg}</p>}
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Run</th><th>Zadanie</th><th>Status</th><th>Rola</th><th>Utworzony</th></tr></thead>
            <tbody>{runs.map(([rid, r]) => <tr key={rid}><td className="mono">{rid}</td><td>{r.task}</td><td>{r.status}</td><td>{r.role}</td><td>{fmtTime(r.created_at, true)}</td></tr>)}
              {!runs.length && <tr><td colSpan={5} className="muted">Brak runów – wymagany eksport REAL_USER_DATA (BLOCKED_NO_HISTORY bez danych).</td></tr>}</tbody></table></div>
        </div>
        <QuotesCard />
        <NeutralCard asset={asset} />
        <ZonesCard asset={asset} />
        <Black76Card />
      </div>
    </div>);
}
