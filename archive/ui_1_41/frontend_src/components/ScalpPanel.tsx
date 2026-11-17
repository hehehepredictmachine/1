// Scalp profile (1.12): M5 Range -> M1 Sweep/Reclaim -> Retest + hedge controller, SHADOW only. Six views: MTF, Setup,
// Indicators, Forecasts, Hedge/risk, Training. UNKNOWN / missing data is never shown as green; a BUY label never replaces
// the execution status - EXECUTION_AUTHORIZED is always false in this release.
import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const TABS = [["mtf", "MTF"], ["setup", "Setup"], ["ind", "Wskaźniki"], ["fc", "Prognozy"], ["hedge", "Hedge / ryzyko"], ["train", "Trening"]] as const;
const STATE_PL: Record<string, string> = {
  WARMUP: "rozgrzewka danych", SEARCH_RANGE: "szukam zakresu M5", RANGE_ARMED: "zakres zamrożony", WAIT_SWEEP: "czekam na sweep + reclaim",
  WAIT_RETEST: "czekam na retest", ENTRY_CANDIDATE: "kandydat wejścia", READY_SHADOW: "gotowy (SHADOW – bez zlecenia)", READY_EXECUTION: "gotowy do wykonania",
  EXPIRED: "wygasł", INVALIDATED: "unieważniony", MISSED: "przegapiony (bez gonienia)", BLOCKED: "zablokowany", COOLDOWN: "postój", ERROR_RECOVERY: "odtwarzanie po błędzie",
};

function badgeFor(v: boolean | null | undefined) {
  return v === true ? "ok" : v === false ? "bad" : "warn";
}

function Kv({ k, v }: { k: string; v: any }) {
  return <><dt>{k}</dt><dd>{v ?? "—"}</dd></>;
}

export default function ScalpPanel() {
  const { s } = useStore();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<string>("setup");
  const live = s.scalp;
  useEffect(() => {
    apiGet("/api/v1/scalp").then((r) => { setD(r); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  }, [live?.updated_at]);
  const f = { ...(d || {}), ...(live || {}) };
  const dig = s.symbol?.info?.digits ?? 2;
  const n = (x: any, k = dig) => (x == null ? "—" : fmtNum(x, k));
  const st = f.statuses || {};
  return (
    <div className="cf-panel sc-panel" data-testid="scalp-panel">
      <div className="cf-head">
        <span className={cls("badge", f.status === "SHADOW" ? "" : "warn")} data-testid="scalp-status">{f.status ?? "…"}</span>
        <span className="badge bad" title="MODE=SHADOW, LIVE_TRADING=false, ML_EXECUTION=false, HEDGE_EXECUTION=false">EXECUTION_AUTHORIZED: false</span>
        <span className="muted small">{f.profile_id} · {f.reason ?? ""}</span>
        {err && <span className="badge bad">{err}</span>}
      </div>
      <div className="sc-statuses" data-testid="scalp-validity">
        {["CODE_VALID", "DATA_VALID", "MODEL_VALID", "STRATEGY_VALID", "HEDGE_VALID", "EXECUTION_AUTHORIZED"].map((k) => (
          <span key={k} className={cls("badge", badgeFor(st[k]?.value))} title={st[k]?.basis}>{k}: {st[k] ? String(st[k].value) : "?"}</span>))}
      </div>
      <div className="tabs sc-tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={cls(tab === id && "on")} onClick={() => setTab(id)}
            data-testid={`scalp-tab-${id}`}>{label}</button>))}
      </div>
      {tab === "mtf" && (
        <div className="table-wrap"><table className="tbl" data-testid="scalp-mtf">
          <thead><tr><th>TF</th><th>Ostatnie zamknięcie</th><th>Wiek</th><th>Dane</th><th>Reżim</th><th>SAR</th><th>Nachylenie BB (ATR/bar)</th><th>BW pct</th></tr></thead>
          <tbody>{(f.mtf || []).map((m: any) => (
            <tr key={m.tf}><td><b>{m.tf}</b></td><td>{fmtTime(m.last_close_utc, true)}</td><td>{m.age_s != null ? `${m.age_s}s` : "—"}</td>
              <td><span className={cls("badge", m.status === "OK" ? "ok" : "warn")}>{m.status}</span></td><td>{m.regime ?? "UNKNOWN"}</td>
              <td>{m.sar_trend ?? "—"}</td><td>{m.slope_atr ?? "—"}</td><td>{m.bw_pct ?? "—"}</td></tr>))}</tbody>
        </table><p className="muted small">Dashboard pokazuje stan – nie jest dodatkowym głosem za wejściem.</p></div>)}
      {tab === "setup" && <SetupView f={f} n={n} />}
      {tab === "ind" && (
        <div className="cf-grid">
          {["M1", "M5"].map((tf) => {
            const x = f.indicators?.[tf];
            return (
              <div className="card" key={tf}><h4>{tf}</h4>
                <dl className="dr-dl">
                  <Kv k="ATR14" v={n(x?.atr14, 3)} />
                  <Kv k="BB basis / upper / lower" v={x?.bb ? `${n(x.bb.basis)} / ${n(x.bb.upper)} / ${n(x.bb.lower)}` : "WARMUP"} />
                  <Kv k="%B · BandWidth · pct100" v={x?.bb ? `${n(x.bb.pct_b, 3)} · ${n(x.bb.bandwidth, 5)} · ${x.bb.bandwidth_pct100 ?? "—"}` : "—"} />
                  <Kv k="Nachylenie basis" v={x?.bb?.slope_atr_per_bar != null ? `${n(x.bb.slope_atr_per_bar, 3)} ATR/bar` : "—"} />
                  <Kv k="SAR 0.02/0.2" v={x?.sar ? `${n(x.sar.sar)} (${x.sar.trend}${x.sar.flip ? ", flip" : ""})` : "—"} />
                </dl><p className="muted small">{x?.variant}</p></div>);
          })}
          <div className="card wide"><h4>Sesje (ukończone boxy, IANA DST)</h4>
            <ul className="small">{(f.sessions || []).map((b: any) => (
              <li key={b.session}><b>{b.session}</b> {b.status === "OK" ? `${n(b.low)} – ${n(b.high)} · ${b.state}${b.state_at ? " " + fmtTime(b.state_at, true) : ""} · znany od ${fmtTime(b.known_at, true)}` : b.status}</li>))}</ul></div>
          <div className="card wide" data-testid="scalp-adapters"><h4>Źródła zewnętrzne</h4>
            <div className="table-wrap"><table className="tbl"><thead><tr><th>Adapter</th><th>Status</th><th>Wartości</th><th>Powód / czego brakuje</th></tr></thead>
              <tbody>{(f.adapters || []).map((a: any) => (
                <tr key={a.adapter}><td title={a.title}>{a.adapter}</td>
                  <td><span className={cls("badge", a.status === "AVAILABLE" ? "ok" : a.status === "UNVALIDATED" ? "warn" : "bad")}>{a.status}</span></td>
                  <td>{a.values ? JSON.stringify(a.values) : "null"}</td>
                  <td className="small">{a.reason}{a.needs?.length ? <details><summary>potrzebne</summary><ul>{a.needs.map((x: string) => <li key={x}>{x}</li>)}</ul></details> : null}</td></tr>))}</tbody>
            </table></div></div>
        </div>)}
      {tab === "fc" && (
        <div className="cf-grid">
          <div className="card wide" data-testid="scalp-forecast"><h4>Kierunek 1/3/5 min (zadanie A)</h4>
            {f.forecasts?.status === "SHADOW" ? (
              <div className="table-wrap"><table className="tbl"><thead><tr><th>h</th><th>P(spadek)</th><th>P(płasko)</th><th>P(wzrost)</th><th>q10 / q50 / q90</th><th>Model</th><th>Status</th></tr></thead>
                <tbody>{Object.entries(f.forecasts.horizons || {}).map(([h, x]: any) => (
                  <tr key={h}><td>{h} min</td><td>{n(x.p_down, 3)}</td><td>{n(x.p_flat, 3)}</td><td>{n(x.p_up, 3)}</td>
                    <td>{x.q10_q50_q90_price ? x.q10_q50_q90_price.map((v: number) => n(v)).join(" / ") : "—"}</td><td>{x.model}</td><td>{x.status}</td></tr>))}</tbody>
              </table></div>) : <p><span className="badge warn">{f.forecasts?.status ?? "UNAVAILABLE"}</span> {f.forecasts?.reason}</p>}
            <p className="muted small">P(wzrost) nie jest prawdopodobieństwem TP przed SL ani oczekiwanym wynikiem transakcji.</p></div>
          <div className="card wide"><h4>Ocena transakcji (zadanie B)</h4>
            <p><span className="badge warn">{f.forecasts?.trade_assessment?.status ?? "UNAVAILABLE"}</span> {f.forecasts?.trade_assessment?.reason}</p></div>
        </div>)}
      {tab === "hedge" && <HedgeView f={f} n={n} />}
      {tab === "train" && <TrainView f={f} />}
    </div>
  );
}

function SetupView({ f, n }: { f: any; n: (x: any, k?: number) => string }) {
  const su = f.setup || {};
  const r = su.range;
  const ld = su.last_detect || {};
  return (
    <div className="cf-grid" data-testid="scalp-setup">
      <div className="card"><h4>Zakres M5</h4>
        <p><b>{STATE_PL[su.state] ?? su.state ?? "—"}</b> <span className="muted small">({su.state})</span></p>
        {r ? (
          <dl className="dr-dl">
            <Kv k="L / MID / H" v={`${n(r.L)} / ${n(r.MID)} / ${n(r.H)}`} />
            <Kv k="Szerokość" v={`${n(r.W)} (${n(r.w_atr, 2)} ATR), ER10 ${n(r.er10, 2)}`} />
            <Kv k="Dotknięcia L/H" v={`${r.touches_low} / ${r.touches_high} (tol. ${n(r.tol, 2)})`} />
            <Kv k="Uzbrojony / TTL" v={`${fmtTime(r.armed_at, true)} → ${fmtTime(r.ttl_end, true)}`} />
            <Kv k="Unieważnienie" v={`2 zamknięcia M1 poza ${n(r.inval_lo)} – ${n(r.inval_hi)}`} />
          </dl>) : <p className="muted small">{ld.reason ?? "brak zakresu"}</p>}
      </div>
      {["BUY", "SELL"].map((dir) => {
        const x = su.directions?.[dir];
        const p = x?.plan;
        return (
          <div className="card" key={dir} data-testid={`scalp-dir-${dir}`}><h4>{dir === "BUY" ? "BUY – sekcja przy L" : "SELL – sekcja przy H (lustrzany)"}</h4>
            {x ? (<>
              <p><b>{STATE_PL[x.state] ?? x.state}</b> <span className="muted small">– {x.reason}</span></p>
              <dl className="dr-dl">
                <Kv k="Sekcja M1" v={x.zone ? `${n(x.zone.z_low)} – ${n(x.zone.z_high)} (znana od ${fmtTime(x.zone.known_at, true)})` : "—"} />
                <Kv k="Sweep" v={x.sweep_extreme != null ? `${n(x.sweep_extreme)} · ε ${n(x.eps, 3)} · tick vol ×${n(x.tv_ratio, 2)}` : "—"} />
                {p && <Kv k="SL / TP1 / TP2" v={`${n(p.sl)} / ${n(p.tp1)} / ${n(p.tp2)}`} />}
                {p?.economics && <Kv k="Koszt/TP1 · RR netto" v={`${n(p.economics.cost_to_tp1, 2)} · ${n(p.economics.weighted_net_rr, 2)}`} />}
                {p?.sizing && <Kv k="Wolumen (hipotetyczny)" v={p.sizing.ok ? `${p.sizing.lots} lot, ${p.sizing.exit_variant}` : p.sizing.reason} />}
                {p && <Kv k="Wejście" v={p.entry_mode === "LIMIT_EDGE" ? `limit ${n(p.limit_price)} (czeka ${p.limit_wait_m1} M1)` : "rynkowe (pierwsze świeże kwotowanie)"} />}
                {p?.model_b && <Kv k="P(TP1 przed SL) – model B" v={p.model_b.status === "SHADOW"
                  ? `${n(p.model_b.p, 3)} vs próg ${p.model_b.threshold ?? "brak"} → ${p.model_b.pass ? "przechodzi" : "odrzucony"}` : `${p.model_b.status}: ${p.model_b.reason}`} />}
              </dl>
              {p?.conditions && <ul className="small">{p.conditions.map((c: any) => <li key={c.name}>{c.ok ? "✔" : "✖"} {c.name}</li>)}</ul>}
            </>) : <p className="muted small">Kierunek nieuzbrojony. Brak BUY nie oznacza SELL.</p>}
          </div>);
      })}
      <div className="card wide"><h4>Ostatnie decyzje SHADOW</h4>
        <div className="table-wrap"><table className="tbl"><thead><tr><th>Czas</th><th>Kierunek</th><th>Status</th><th>Powody / bramki</th><th>Wynik hipotetyczny</th></tr></thead>
          <tbody>{(f.recent || []).map((r: any) => (
            <tr key={r.id}><td>{fmtTime(r.decision_time_utc, true)}</td><td>{r.direction}</td>
              <td><span className={cls("badge", r.status === "READY_SHADOW" ? "" : "warn")}>{r.status}</span></td>
              <td className="small">{(r.reasons || []).join("; ") || "wszystkie bramki SHADOW spełnione"}</td>
              <td>{r.outcome_status === "SETTLED" ? `${n(r.net_r, 2)} R (OHLC, przybliżony)` : r.outcome_status}</td></tr>))}</tbody>
        </table></div>
        <details className="small"><summary>Dziennik przejść ({(su.journal || []).length})</summary>
          <ul>{(su.journal || []).slice().reverse().map((j: any, i: number) => <li key={i}>{fmtTime(j.t, true)} · <b>{j.state}</b>{j.direction ? ` ${j.direction}` : ""} – {j.reason}</li>)}</ul>
        </details>
        <p className="muted small">Podsumowanie: {JSON.stringify(f.summary?.by_status || {})} · {f.summary?.note}</p>
      </div>
    </div>);
}

function HedgeView({ f, n }: { f: any; n: (x: any, k?: number) => string }) {
  const h = f.hedge_risk || {};
  return (
    <div className="cf-grid" data-testid="scalp-hedge">
      <div className="card"><h4>Kontroler hedge</h4>
        <dl className="dr-dl">
          <Kv k="Polityka" v={`${h.policy} (HEDGE_EXECUTION=${String(h.hedge_execution)})`} />
          <Kv k="Tryb marży" v={<span className={cls("badge", h.margin_mode === "UNKNOWN" ? "warn" : "")}>{h.margin_mode}</span>} />
          <Kv k="Limity" v={h.limits ? `hedge ≤ ${h.limits.max_fraction_of_base}× base, ${h.limits.max_hedges_per_cycle} na cykl, TTL ${h.limits.ttl_m1} M1, ryzyko cyklu ${h.limits.cycle_risk_pct}%` : "—"} />
          <Kv k="Equity / wolna marża" v={`${n(h.equity, 2)} / ${n(h.free_margin, 2)}`} />
          <Kv k="Otwarty cykl" v={h.open_cycle ? JSON.stringify(h.open_cycle) : "brak (SHADOW – bez ticketów)"} />
        </dl>
        {h.netting_note && <p className="small">{h.netting_note}</p>}
        <p className="muted small">{h.note}</p></div>
      <div className="card"><h4>HEDGE_PARTIAL vs REDUCE (replay)</h4>
        {(() => { const r = f.training?.last_replay?.hedge_vs_reduce; return r ? (
          <dl className="dr-dl"><Kv k="Status" v={r.status} /><Kv k="Cykle / dni" v={`${r.cycles} / ${r.days ?? "—"}`} />
            <Kv k="Średnio (hedge − reduce)" v={r.mean_hedge_minus_reduce_r != null ? `${r.mean_hedge_minus_reduce_r} R` : "—"} />
            <Kv k="95% CI (bloki dni)" v={r.ci95_day_block ? r.ci95_day_block.join(" … ") : "—"} /></dl>)
          : <p><span className="badge warn">NOT_EVALUATED</span> brak replayu na rzeczywistej historii</p>; })()}
      </div>
    </div>);
}

function TrainView({ f }: { f: any }) {
  const t = f.training || {};
  const reg = f.registry || {};
  return (
    <div className="cf-grid" data-testid="scalp-training">
      <div className="card"><h4>Stan</h4>
        {t.blocked && <p><span className="badge bad">BLOCKED</span> {t.blocked}</p>}
        <dl className="dr-dl">
          <Kv k="Eksporty historii" v={(t.history_exports || []).join(", ") || "brak"} />
          <Kv k="Plik statusu" v={t.status_file ? `${t.status_file.status} (${t.status_file.run_id ?? "—"})` : "brak"} />
          <Kv k="Aktywny model" v={reg.active ?? "brak (NO_MODEL)"} />
          <Kv k="Ostatni trening" v={t.last_run ? `A ${t.last_run.overall_task_A}, B ${t.last_run.task_B}, C ${t.last_run.task_C} (${t.last_run.data_kind})` : "nie uruchomiono"} />
        </dl></div>
      <div className="card wide" data-testid="scalp-variants"><h4>Warianty poprawy win ratio (replay po kosztach)</h4>
        {t.last_variants ? (<>
          <div className="table-wrap"><table className="tbl"><thead><tr><th>Wariant</th><th>Opis</th><th>Dev: cykle</th><th>Dev: win %</th><th>Dev: E[R]</th>
            <th>Test: cykle</th><th>Test: win %</th><th>Test: E[R]</th></tr></thead>
            <tbody>{t.last_variants.rows.map((r: any) => (
              <tr key={r.id} className={cls(r.id === t.last_variants.chosen && "chosen")}><td><b>{r.id}</b>{r.id === t.last_variants.chosen ? " ✔" : ""}</td>
                <td className="small">{r.desc}</td><td>{r.development.cycles}</td>
                <td>{r.development.win_rate != null ? (r.development.win_rate * 100).toFixed(1) : "—"}</td><td>{r.development.expectancy_r ?? "—"}</td>
                <td>{r.test.cycles}</td><td>{r.test.win_rate != null ? (r.test.win_rate * 100).toFixed(1) : "—"}</td><td>{r.test.expectancy_r ?? "—"}</td></tr>))}</tbody>
          </table></div>
          <p className="small">Wybór: <b>{t.last_variants.chosen ?? "brak"}</b> – {t.last_variants.chosen_reason}. Dane: {t.last_variants.data_kind}.</p></>)
          : <p className="muted">Brak porównania – uruchom 19_REPLAY_SCALP.bat po eksporcie historii.</p>}
        <p className="muted small">Wybór po expectancy (R po kosztach) w okresie development; win ratio jest pokazane obok, ale nie decyduje. Test oceniany raz.</p></div>
      <div className="card wide" data-testid="scalp-model-b"><h4>Filtr modelu jakości setupu (B)</h4>
        {t.last_task_b ? (<dl className="dr-dl">
          <Kv k="Status" v={t.last_task_b.status} /><Kv k="Model / próg" v={`${t.last_task_b.selected ?? "—"} / ${t.last_task_b.threshold ?? "brak"}`} />
          <Kv k="Holdout bez filtra" v={t.last_task_b.holdout_unfiltered ? `${t.last_task_b.holdout_unfiltered.cycles} cykli, win ${t.last_task_b.holdout_unfiltered.win_rate ?? "—"}, E[R] ${t.last_task_b.holdout_unfiltered.expectancy_r ?? "—"}` : "—"} />
          <Kv k="Holdout z filtrem" v={t.last_task_b.holdout_filtered ? `${t.last_task_b.holdout_filtered.cycles} cykli, win ${t.last_task_b.holdout_filtered.win_rate ?? "—"}, E[R] ${t.last_task_b.holdout_filtered.expectancy_r ?? "—"}` : "—"} />
          <Kv k="Powód" v={t.last_task_b.reason ?? t.last_task_b.note} /></dl>) : <p className="muted">Nie trenowano.</p>}</div>
      <div className="card"><h4>Replay strategii (OOS, po kosztach)</h4>
        {t.last_replay ? (<dl className="dr-dl">
          <Kv k="Dane" v={t.last_replay.data_kind} /><Kv k="Status" v={t.last_replay.strategy?.status} />
          <Kv k="Cykle / dni" v={`${t.last_replay.strategy?.cycles} / ${t.last_replay.strategy?.days}`} />
          <Kv k="Win ratio" v={t.last_replay.strategy?.win_rate != null ? `${(t.last_replay.strategy.win_rate * 100).toFixed(1)}% (śr. zysk ${t.last_replay.strategy.avg_win_r} R, śr. strata ${t.last_replay.strategy.avg_loss_r} R)` : "—"} />
          <Kv k="Expectancy (R)" v={`${t.last_replay.strategy?.expectancy_r ?? "—"} (CI ${(t.last_replay.strategy?.expectancy_ci95_day_block || []).join(" … ") || "—"})`} />
          <Kv k="Powód" v={t.last_replay.strategy?.reason} /></dl>) : <p className="muted">Brak replayu.</p>}
        <p className="muted small">Bramka badawcza: ≥30 dni i ≥200 niezależnych cykli OOS, dolny kraniec 95% CI expectancy &gt; 0, max DD ≤ 5%, dodatni wynik przy kosztach +50%.</p></div>
    </div>);
}
