import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { fmtNum } from "../util";

// PMW-MM: master models (XXX.rar bundle) – inventory with evidence-based statuses, SHADOW live view on closed bars, latest orchestrator run.
// Read-only: no control on this page can place, modify or close an order.
function usePoll<T = any>(path: string, ms: number): [T | null, string | null] {
  const [d, setD] = useState<T | null>(null);
  const [e, setE] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => apiGet<T>(path).then((r) => { if (alive) { setD(r); setE(null); } }).catch((x) => alive && setE(String(x?.message || x)));
    load();
    const t = setInterval(load, ms);
    return () => { alive = false; clearInterval(t); };
  }, [path, ms]);
  return [d, e];
}
const TONE: Record<string, string> = { OK: "g", SUCCEEDED: "g", DETERMINISTIC_OK: "g", VALIDATION_PASSED: "g", TRAINING_EXECUTED: "p", INTEGRATION_TESTED: "p",
  BLOCKED: "r", FAILED: "r", ERROR: "r", NOT_RUN: "y", DATA_MISSING: "y", UNAVAILABLE: "y", DEMO: "p", SYNTHETIC_TEST: "p" };
const S = ({ s }: { s: any }) => <span className={`nc-st ${TONE[String(s)] || "y"}`} data-status={s}>{String(s ?? "—")}</span>;
const Panel = ({ title, right, children, id }: { title: any; right?: any; children: any; id?: string }) => (
  <section className="nc-panel" data-testid={id}><div className="nc-ph"><span>{title}</span><div className="nc-ctrl">{right}</div></div><div className="nc-body">{children}</div></section>);
const Line = ({ a, b }: { a: any; b: any }) => <div className="nc-line"><span>{a}</span><strong>{b ?? "—"}</strong></div>;
const Note = ({ children }: { children: any }) => <div className="nc-note">{children}</div>;
const pct = (x: any) => (typeof x === "number" ? `${(x * 100).toFixed(1)}%` : "—");

export default function MasterModels({ inst, synthetic }: { inst: string; synthetic: boolean }) {
  const [st, e1] = usePoll<any>(`/api/v1/mm/status?instrument=${inst}`, 20000);
  const [lv, e2] = usePoll<any>(`/api/v1/mm/live?instrument=${inst}`, 15000);
  const inv: any[] = st?.inventory || [];
  const blocked = inv.filter((r) => r.status === "BLOCKED").length;
  const run = st?.latest_run;
  const dk = run?.snapshot?.data_kind;
  const g = lv?.gpr || {};
  return (<>
    <div className="nc-grid">
      <div className="nc-kpi"><div className="nc-small">MODUŁY W INWENTARZU</div><div className="nc-big cyan">{inv.length || "—"}</div><S s={inv.length ? "OK" : "NOT_RUN"} /></div>
      <div className="nc-kpi"><div className="nc-small">BRAK SPECYFIKACJI</div><div className="nc-big red">{blocked}</div><span className="nc-small">nie rekonstruowane z nazwy</span></div>
      <div className="nc-kpi"><div className="nc-small">OSTATNI PRZEBIEG</div><div className="nc-big purple">{run?.status || "NOT_RUN"}</div><S s={dk || "NOT_RUN"} /></div>
      <div className="nc-kpi"><div className="nc-small">TRYB</div><div className="nc-big gold">SHADOW</div><span className="nc-small">execution_allowed = false</span></div>
    </div>
    {(e1 || e2) && <Note>Błąd API: {e1 || e2}</Note>}
    <Panel id="nc-mm-live" title={<>SHADOW NA ŻYWO – zamknięte świece M5 {inst} <S s={lv?.status} /> {synthetic && <S s="DEMO" />}</>}>
      {lv?.status !== "OK" ? <Note>{lv?.reason || "brak danych"}</Note> : <>
        <div className="nc-scroll"><table className="nc-tbl" data-testid="nc-mm-align"><thead><tr><th>TF</th><th>Średnia ({lv.align_mean?.config_key})</th><th>Zamknięcie</th>
          <th>Odl. [pkt]</th><th>Odl. [ATR]</th><th>Status</th></tr></thead><tbody>
          {(lv.align_mean?.charts || []).map((c: any) => <tr key={c.tf}><td>{c.tf}</td><td>{fmtNum(c.mean, 2)}</td><td>{fmtNum(c.close, 2)}</td><td>{fmtNum(c.dist_points, 0)}</td>
            <td>{fmtNum(c.dist_atr, 2)}</td><td><S s={c.status} /></td></tr>)}</tbody></table></div>
        <Note>Jedna definicja średniej na wszystkich wykresach; odległość w ATR to kontekst, nie sygnał ani prawdopodobieństwo.</Note>
        <div className="nc-two nc-gap">
          <div>
            <Line a="P&L konta (MT5, tylko odczyt)" b={lv.pnl?.status === "OK" ? `equity ${fmtNum(lv.pnl.equity, 2)} · niezreal. ${fmtNum(lv.pnl.unrealized, 2)} ${lv.pnl.currency || ""}` : "UNAVAILABLE"} />
            <Line a="Kalman fast/slow" b={`${lv.kalman?.state} · K ${fmtNum(lv.kalman?.K_fast, 3)}/${fmtNum(lv.kalman?.K_slow, 3)}`} />
            <Line a="Breakout zones" b={lv.breakout?.panel?.text} />
            <Line a="Multi-Indicator (ostatnia zamknięta)" b={`${lv.multi_indicator?.decision} · L: ${(lv.multi_indicator?.long_reasons || []).join(",") || "OK"}`} />
            <Line a="SMC BoS/IDM/FVG" b={`trend ${lv.smc_fvg?.trend} · aktywne setupy ${(lv.smc_fvg?.live_setups || []).length} · próg ${lv.smc_fvg?.depth_min}`} />
            <Line a="Robust volatility (sorted / time-aware / path)" b={lv.robust_vol?.status === "OK" ? `${fmtNum(lv.robust_vol.sorted_dispersion * 1e4, 2)}e-4 / ${fmtNum(lv.robust_vol.time_aware_dispersion, 3)} / ${fmtNum(lv.robust_vol.path, 2)}` : lv.robust_vol?.status} />
          </div>
          <div data-testid="nc-mm-gpr">
            <Line a="GPR – średni log-zwrot (3×M5)" b={g.status && g.status !== "OK" && g.status !== "DEGRADED" ? g.status : `${fmtNum((g.mean_logret || 0) * 1e4, 2)} bp ± ${fmtNum((g.sd || 0) * 1e4, 2)} bp`} />
            <Line a="Pasmo 2σ (cena)" b={g.price ? `${fmtNum(g.price.lower2, 2)} – ${fmtNum(g.price.upper2, 2)}` : "—"} />
            <Line a="Kalibracja na żywo (ledger)" b={`n=${g.live_calibration?.n_scored ?? 0} · 1σ ${pct(g.live_calibration?.coverage_1sd)} · 2σ ${pct(g.live_calibration?.coverage_2sd)}${g.live_calibration?.inconclusive ? " (za mało)" : ""}`} />
            <Line a="Tablica dowodów" b={`UP ${lv.board?.directional?.UP ?? 0} / DOWN ${lv.board?.directional?.DOWN ?? 0}${lv.board?.directional?.disagreement ? " · NIEZGODNOŚĆ" : ""}`} />
            <Note>{lv.board?.independence}. Modele trenowane (HDC / event engine / STE) działają na żywo dopiero po artefakcie VALIDATED_SHADOW na danych rzeczywistych.</Note>
          </div>
        </div></>}
    </Panel>
    <Panel id="nc-mm-inventory" title="INWENTARZ MODUŁÓW (stan wg dowodów)">
      <div className="nc-scroll"><table className="nc-tbl"><thead><tr><th>#</th><th>Moduł</th><th>Kategoria</th><th>Status</th><th>Trening</th><th>Uwagi</th></tr></thead><tbody>
        {inv.map((r) => <tr key={r.id} data-mm={r.id}><td>{r.n}</td><td>{r.name}</td><td>{r.category}</td><td><S s={r.status} /></td><td>{r.training}</td>
          <td>{r.blocked || r.note || r.native || (r.last_job ? `${r.last_job.status}${r.last_job.data_kind ? " · " + r.last_job.data_kind : ""}` : "")}</td></tr>)}</tbody></table></div>
    </Panel>
    <Panel id="nc-mm-run" title={<>OSTATNI PRZEBIEG master_models {run?.run_id || ""} <S s={dk || "NOT_RUN"} /></>}>
      {!run ? <Note>Brak przebiegu – uruchom trening (zadanie master_models) w Neural Training.</Note> : <>
        <div className="nc-scroll"><table className="nc-tbl"><thead><tr><th>Zadanie</th><th>Status</th><th>Trening</th><th>Walidacja</th><th>Artefakt</th><th>Powód</th></tr></thead><tbody>
          {Object.values(run.jobs || {}).map((j: any) => <tr key={j.id}><td>{j.id}</td><td><S s={j.status} /></td><td>{j.training_executed ? "tak" : "—"}</td>
            <td>{j.validation_passed ? "PASS" : "—"}</td><td className="nc-small">{j.artifact_id || "—"}</td><td className="nc-small">{j.reason || ""}</td></tr>)}</tbody></table></div>
        {dk !== "REAL_USER_DATA" && <Note>Przebieg na danych {dk}: wyniki są testem technicznym; walidacja rynkowa wymaga danych z Twojego MT5.</Note>}</>}
    </Panel>
  </>);
}
