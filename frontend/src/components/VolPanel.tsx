// Daily volatility levels (backend engine/volzones.py): HV, 1-day contract pricing (Black-76) and IV walls.
import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { useStore } from "../store";
import { cls, fmtNum } from "../util";

const pct = (x: any, d = 1) => (x == null ? "—" : `${Number(x).toFixed(d)}%`);

export default function VolPanel() {
  const { s } = useStore();
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => apiGet("/api/v1/volatility").then((d) => alive && (setV(d), setErr(null))).catch((e) => alive && setErr(String(e.message || e)));
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [s.analysisSeq]);
  const ok = v?.status === "OK";
  const day = v?.day || {};
  const c = v?.contract || {};
  return (
    <div className="panel vol-panel" data-testid="vol-panel">
      <div className="panel-head">
        <span className="ptitle">ZMIENNOŚĆ DZIENNA · IV WALLS</span>
        <span className="psub">{v?.model ?? ""}</span>
        <span className="spacer" />
        <span className={cls("badge", ok ? "ok" : v?.status === "DISABLED" ? "muted" : "warn")}
          title={v?.status === "INSUFFICIENT_HISTORY" ? `Potrzeba ${v.required_d1} zamkniętych świec D1, jest ${v.closed_d1}` : ""}>
          {v?.status ?? "…"}
        </span>
        {day.state === "NEXT_SESSION_PROJECTION" && <span className="badge muted" title="Rynek zamknięty – poziomy od ostatniego zamknięcia">projekcja na następną sesję</span>}
      </div>
      {err && <div className="muted pad">Błąd: {err}</div>}
      {ok && (
        <div className="vol-body">
          <div className="kv vol-kv">
            <div><label>Daily Open</label><b>{fmtNum(day.open)}</b></div>
            <div><label>High / Low dnia</label><b>{fmtNum(day.high)} / {fmtNum(day.low)}</b></div>
            <div><label>Daily High (IV 1σ)</label><b>{fmtNum(v.expected_high)}</b></div>
            <div><label>Daily Low (IV 1σ)</label><b>{fmtNum(v.expected_low)}</b></div>
            <div><label>Oczekiwany ruch 1σ</label><b>±{fmtNum(v.expected_move_1s)}</b></div>
            <div><label>Wykorzystany zakres</label><b>{pct(day.range_used_pct, 0)}</b></div>
            <div><label>PDH / PDL</label><b>{fmtNum(v.previous_day?.high)} / {fmtNum(v.previous_day?.low)}</b></div>
            <div><label>HV{v.window} ({v.estimator === "parkinson" ? "Parkinson" : "close-close"})</label><b>{pct(v.hv_annual_pct, 2)}</b>
              <span className="muted small"> · percentyl 1R {v.hv_percentile_1y == null ? "—" : `${v.hv_percentile_1y}`}</span></div>
            <div><label>IV do wyceny ({v.iv_source === "MANUAL" ? "ręcznie" : "= HV"})</label><b>{pct(v.iv_annual_pct, 2)}</b></div>
            <div><label>Straddle ATM (1 dzień)</label><b>{fmtNum(c.straddle)}</b>
              <span className="muted small"> · BE {fmtNum(c.breakeven_down)} – {fmtNum(c.breakeven_up)}</span></div>
          </div>
          <table className="vol-walls">
            <thead><tr><th>IV wall</th><th>Poziom</th><th>Strefa</th><th>Opcja</th><th>Premia</th><th>Delta</th><th>P(zamknięcie za)</th><th>P(dotknięcie)</th><th>Dziś</th></tr></thead>
            <tbody>
              {(v.walls || []).map((w: any) => (
                <tr key={`${w.side}${w.sigma}`} className={w.side === "UP" ? "up" : "down"}>
                  <td>{w.side === "UP" ? "+" : "−"}{w.sigma}σ</td><td>{fmtNum(w.level)}</td><td>{fmtNum(w.zone_low)} – {fmtNum(w.zone_high)}</td>
                  <td>{w.option}</td><td>{fmtNum(w.premium)}</td><td>{w.delta}</td><td>{pct(100 * w.p_close_beyond)}</td><td>{pct(100 * w.p_touch)}</td>
                  <td>{w.reached ? <span className="badge warn">osiągnięty</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted small vol-note">
            {v.iv_note} Wycena: {c.model}. Poziomy modelu (rozkład lognormalny, stała zmienność) – to nie są zlecenia, open interest ani prognoza;
            realne ruchy mają grube ogony.
          </div>
        </div>
      )}
    </div>
  );
}
