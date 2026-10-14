// "Świece i prognozy" (1.11): gold_candles analytics in SHADOW - closed M5/M30, patterns, price forecasts 5/15/30 min with
// q10/q50/q90, model/run/validation per horizon, training status, and the Double Retest v2 research checklist. Nothing here
// is an execution signal: the backend always sends execution_permission=false and EXECUTION_STATE=BLOCKED.
import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const H_STATUS_PL: Record<string, string> = { SHADOW_VALIDATED: "zwalidowany (jakość ceny) – SHADOW", SHADOW_UNVALIDATED: "niezwalidowany – SHADOW",
  REJECTED: "odrzucony (gorszy od baseline)", INSUFFICIENT_DATA: "za mało danych" };
const P_PL: Record<string, string> = { UP: "wzrost", FLAT: "płasko", DOWN: "spadek" };

function ageS(iso?: string | null) {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
}

function SetupSide({ side, st, dig }: { side: string; st: any; dig: number }) {
  const a = st?.active;
  const n = (x: any) => (x == null ? "—" : fmtNum(x, dig));
  return (
    <div className="card dr-side" data-testid={`dr-${side}`}>
      <h4>{side === "BUY" ? "Kierunek BUY (lustrzany)" : "Kierunek SELL (lustrzany)"}</h4>
      <p><b>{st?.state_pl ?? "—"}</b> <span className="muted small">({st?.state ?? "?"})</span></p>
      <p className="small">Kontekst M30: <b>{st?.context ?? "?"}</b>{st?.context_reason ? ` – ${st.context_reason}` : ""}{st?.m30_slope_atr != null ? ` · nachylenie ${st.m30_slope_atr}` : ""}</p>
      {a ? (
        <dl className="dr-dl">
          <dt>Poziom L</dt><dd>{n(a.L)} <small>({a.location.trace} {n(a.location.trace_price)}, tolerancja {fmtNum(a.location.tolerance, 2)})</small></dd>
          <dt>Strefa głęboka</dt><dd>{n(a.deep_zone[0])} – {n(a.deep_zone[1])}</dd>
          <dt>Epizody</dt><dd>{a.episodes.length}/2 {a.episodes.map((e: any, i: number) => <small key={i}> · #{i + 1} {fmtTime(e.confirmed_at, true)}</small>)}</dd>
          <dt>Reclaim / retest</dt><dd>{a.reclaim ? `reclaim ${fmtTime(a.reclaim.at, true)}` : "—"}{a.retest ? ` · retest ${fmtTime(a.retest.contact_at, true)}` : ""}</dd>
          <dt>Następne zdarzenie</dt><dd>{a.next_required_event ?? "—"}</dd>
          <dt>Unieważnienie</dt><dd className="small">{a.invalidation}</dd>
          <dt>Cele (hipotetyczne)</dt><dd>{a.targets_hypothetical.map(n).join(" / ")} <small>– bez wolumenu i kosztów</small></dd>
        </dl>
      ) : <p className="muted small">Brak aktywnego setupu.</p>}
      {(st?.recent || []).length > 0 && (
        <details className="small"><summary>Ostatnie zakończone ({st.recent.length})</summary>
          <ul>{st.recent.map((r: any) => <li key={r.setup_id}>{fmtTime(r.ended_at, true)} · L {n(r.L)} · <b>{r.state}</b> – {r.end_reason}
            {r.trigger ? ` · trigger ${r.trigger.family}` : ""}</li>)}</ul>
        </details>)}
    </div>
  );
}

export default function CandleForecastPanel() {
  const { s } = useStore();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const live = s.forecast;
  useEffect(() => {
    apiGet("/api/v1/forecast").then((r) => { setD(r); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  }, [live?.updated_at]);
  const f = { ...(d || {}), ...(live || {}) };
  const rep = f.report || {};
  const fc = rep.forecast || {};
  const probs = fc.probabilities || null;
  const m5 = rep.candle_analysis?.M5;
  const m30 = rep.candle_analysis?.M30;
  const dig = s.symbol?.info?.digits ?? 2;
  const hs = f.model?.horizon_status || {};
  const sum = f.shadow_summary || d?.shadow_summary || {};
  return (
    <div className="cf-panel" data-testid="candle-forecast" data-status={f.status}>
      <div className="cf-head">
        <span className={cls("badge", f.status === "SHADOW" ? "warn" : "muted")} data-testid="cf-status">{f.status ?? "…"}</span>
        <span>{f.status_pl}</span>
        <span className="badge bad" title="moduł prognoz nigdy nie zezwala na zlecenie">EXECUTION LOCK: BLOCKED · tylko obserwacja</span>
      </div>
      {f.reason && <p className="small warn" data-testid="cf-reason">Powód: {f.reason}</p>}
      {err && <p className="small bad">Błąd odczytu: {err}</p>}
      <div className="cf-grid">
        <div className="card">
          <h4>Zamknięte świece (sesja bota)</h4>
          <p className="small">M5: {f.bars?.m5_last_open_utc ? `${fmtTime(f.bars.m5_last_open_utc, true)} (otwarcie) · ${f.bars.m5} świec` : "—"}
            {rep.data_age_seconds != null ? ` · wiek ${Math.round(rep.data_age_seconds)} s od zamknięcia` : ""}</p>
          <p className="small">M30: {f.bars?.m30_last_open_utc ? `${fmtTime(f.bars.m30_last_open_utc, true)} · ${f.bars.m30} świec` : "—"} · źródło M30: BROKER_M30</p>
          <p className="small">Formacje M5: {(m5?.patterns || []).map((p: any) => `${p.name} (${p.family})`).join(", ") || "brak"} · hipoteza morfologii: <b>{m5?.morphology_hypothesis ?? "—"}</b></p>
          <p className="small">Formacje M30: {(m30?.patterns || []).map((p: any) => p.name).join(", ") || "brak"}</p>
          <p className="muted small">Formacja to opis zamkniętej świecy, nie sygnał „kup/sprzedaj teraz”. Tick volume = aktywność feedu brokera.</p>
        </div>
        <div className="card wide">
          <h4>Prognozy ceny (SHADOW)</h4>
          {probs ? (
            <div className="table-wrap"><table className="tbl" data-testid="cf-table">
              <thead><tr><th>Horyzont</th><th>P(spadek / płasko / wzrost)</th><th>q10 / q50 / q90 close</th><th>Status modelu</th><th>Sesja</th></tr></thead>
              <tbody>{Object.values(probs).map((h: any) => (
                <tr key={h.horizon_minutes} data-h={h.horizon_minutes}>
                  <td>{h.horizon_minutes} min<br /><small>do {fmtTime(h.target_time_utc, true)}</small></td>
                  <td>{["DOWN", "FLAT", "UP"].map((k) => `${P_PL[k]} ${Math.round(100 * h.probabilities[k])}%`).join(" · ")}</td>
                  <td>{fmtNum(h.close_price_quantiles.q10, dig)} / {fmtNum(h.close_price_quantiles.q50, dig)} / {fmtNum(h.close_price_quantiles.q90, dig)}</td>
                  <td>{H_STATUS_PL[hs[String(h.horizon_minutes / 5)]] ?? hs[String(h.horizon_minutes / 5)] ?? "—"}</td>
                  <td className={h.session_check === "BLOCKED_SESSION_BREAK" ? "bad" : "muted"}>{h.session_check === "BLOCKED_SESSION_BREAK" ? "przerwa rynku – niedopuszczalna" : "sesje brokera niezweryfikowane"}</td>
                </tr>))}</tbody>
            </table></div>
          ) : <p className="muted" data-testid="cf-noforecast">Brak prognozy: {f.status === "NO_MODEL" ? "brak wytrenowanego modelu" : f.status_pl ?? "—"}. Prawdopodobieństwa = null (nie zgadujemy).</p>}
          <p className="muted small">UP/FLAT/DOWN = przyszłe zamknięcie względem ±0,20×ATR14 M5. To nie jest P(TP przed SL), win rate ani EV transakcji.</p>
        </div>
        <div className="card">
          <h4>Model i trening</h4>
          <p className="small">Aktywny run: <b>{f.model?.run_id ?? d?.registry?.active ?? "brak"}</b>{f.model?.data_kind ? ` · ${f.model.data_kind}` : ""}</p>
          {f.model && <p className="small">Wiedza do: {fmtTime(f.model.knowledge_cutoff_utc, true)} · trening {f.model.train_range_utc?.map((x: string) => fmtTime(x, true)).join(" – ")} · status {f.model.overall_status}</p>}
          <p className="small">Eksport historii: {d?.training?.latest_export ? `${d.training.latest_export.range_utc?.join(" – ")} (${d.training.latest_export.data_kind})` : <b className="warn">{d?.training?.blocked ?? "—"}</b>}</p>
          <p className="small">Proces analityki: {f.worker ? `PID ${f.worker.pid}, ${f.worker.versions?.python ?? ""}, pandas ${f.worker.versions?.pandas ?? ""}, scikit-learn ${f.worker.versions?.scikit_learn ?? ""}` : "nie działa"}
            {f.latency_ms ? ` · czas analizy ${f.latency_ms.worker} ms (całość ${f.latency_ms.round_trip} ms)` : ""}</p>
          <p className="small">Ocena SHADOW na żywo: {["5", "15", "30"].map((h) => `${h} min: ${sum[h]?.scored ?? 0} ocenionych${sum[h]?.brier != null ? `, Brier ${sum[h].brier}` : ""} (${sum[h]?.pending ?? 0} czeka)`).join(" · ")}</p>
        </div>
      </div>
      <h4>Setup v2 – MasterQUO Gold Double Retest 5/10/15 (badawczy)</h4>
      <p className="small muted">{f.setup_v2?.note ?? ""} Walidacja strategii: {f.setup_v2?.VALIDATION_STATE ?? "—"} · wykonanie: <b>{f.setup_v2?.EXECUTION_STATE ?? "BLOCKED"}</b></p>
      <div className="cf-grid two">
        <SetupSide side="BUY" st={f.setup_v2?.states?.BUY} dig={dig} />
        <SetupSide side="SELL" st={f.setup_v2?.states?.SELL} dig={dig} />
      </div>
      {f.updated_at && <p className="muted small">Aktualizacja {fmtTime(f.updated_at, true)} ({ageS(f.updated_at)} s temu) – po każdej nowej zamkniętej M5.</p>}
    </div>
  );
}
