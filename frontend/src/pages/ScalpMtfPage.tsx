// PMW-UPD-05 Scalping MTF dashboard (#/scalp-mtf). One backend MTFContextSnapshot drives the bar, the TF matrix, the five charts and
// the setup checklist (same snapshot_id everywhere); the 1 s heartbeat (scalp_dashboard_health) only changes freshness, it never
// rewrites the analysis. Presets / pause / inspection are presentation only - the backend keeps working and nothing here sends orders.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../api";
import MtfChart from "../components/MtfChart";
import { href, usePersisted } from "../router";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const STATUS_PL: Record<string, string> = { OK: "OK", STALE: "nieaktualne", DISCONNECTED: "rozłączone", MISSING: "brak danych", WARMING_UP: "rozgrzewka",
  NOT_APPLICABLE: "nie dotyczy", MET: "spełniony", MISSING_C: "brakuje", CONFLICT: "sprzeczny", UNKNOWN: "nieznany", DEGRADED: "częściowo" };
const STATE_PL: Record<string, string> = { WARMUP: "rozgrzewka", SEARCH_RANGE: "szukanie zakresu", RANGE_ARMED: "zakres uzbrojony", WAIT_SWEEP: "oczekiwanie na sweep/reclaim",
  WAIT_RETEST: "oczekiwanie na retest", CANDIDATE: "kandydat", READY_SHADOW: "wynik SHADOW (warunki spełnione – analiza)", BLOCKED: "zablokowany", MISSED: "pominięty",
  EXPIRED: "wygasł", COOLDOWN: "cooldown" };
const PRESETS = [["full", "Pełne MTF"], ["entry", "Wejście"], ["context", "Kontekst"], ["focus", "Focus"]] as const;
const TFS = ["H1", "M30", "M15", "M5", "M1"];

function useWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [w, setW] = useState(1200);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(e[0].contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export default function ScalpMtfPage({ params }: { params?: URLSearchParams }) {
  const { s } = useStore();
  const asset = s.assets?.active;
  const tick = (s as any).scalp_dashboard?.seq;
  const healthEv = (s as any).scalp_dashboard_health;
  const [d, setD] = useState<any>(null);
  const [paused, setPaused] = useState(false);
  const [inspect, setInspect] = useState<string | null>(params?.get("snapshot") || null);
  const [preset, setPreset] = usePersisted<string>("mtf.preset", "full", (x) => PRESETS.some((p) => p[0] === x));
  const [focusTf, setFocusTf] = usePersisted<string>("mtf.focusTf", "M1", (x) => TFS.includes(x));
  const [setupSel, setSetupSel] = useState<string | null>(params?.get("setup") || null);
  const [evidence, setEvidence] = useState<number | null>(null);
  const [archive, setArchive] = useState<any[]>([]);
  const [showJournal, setShowJournal] = useState(false);
  const req = useRef(0);
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);
  const narrow = width < 760;

  const load = (sid?: string | null) => {
    if (!asset) return;
    const id = ++req.current;
    apiGet(`/api/v1/scalp/dashboard?asset=${asset}${sid ? `&snapshot_id=${sid}` : ""}`).then((r) => {
      if (id !== req.current || r.asset !== asset) return;                       // stale answer / fast asset switch
      setD((old: any) => (!sid && old?.snapshot && r.snapshot && old.asset === r.asset && old.snapshot.session_epoch === r.snapshot.session_epoch
        && r.snapshot.seq < old.snapshot.seq ? old : r));
    }).catch(() => undefined);
  };
  useEffect(() => { setD(null); setSetupSel(null); load(inspect); }, [asset]);
  useEffect(() => { if (!paused && !inspect) load(null); }, [tick]);
  useEffect(() => { if (inspect) load(inspect); }, [inspect]);
  useEffect(() => { apiGet("/api/v1/scalp/dashboard/snapshots?limit=30").then((r) => r.asset === asset && setArchive(r.rows)).catch(() => undefined); }, [asset, tick]);

  const snap = d?.snapshot;
  const health = (healthEv && healthEv.asset === asset ? healthEv : d?.health) || {};
  const setups: any[] = snap?.setups || [];
  const setup = setups.find((x) => x.setup_id === setupSel) || setups[0] || null;
  const live = !paused && !inspect;
  const hRows = Object.fromEntries((health.timeframes || []).map((r: any) => [r.tf, r]));
  const machine = snap?.machine;
  const epoch = String(snap?.session_epoch ?? "");
  const shown = narrow ? [focusTf] : preset === "entry" ? ["M5", "M1"] : preset === "context" ? ["H1", "M30", "M15"] : preset === "focus" ? [focusTf] : TFS;
  const chartH = (tf: string) => (shown.length === 1 ? 460 : ["M5", "M1"].includes(tf) ? (preset === "entry" && tf === "M1" ? 420 : 340) : 200);

  if (!asset) return null;
  if (d && d.status === "UNSUPPORTED_STRATEGY_PROFILE") return <div className="lab-page"><h2>Scalping MTF – {asset}</h2><p>UNSUPPORTED_STRATEGY_PROFILE: brak profilu scalp dla {asset}.</p></div>;
  return (
    <div className="lab-page mtf-page" data-testid="page-scalp-mtf" ref={wrap}>
      <div className="card mtf-bar small" data-testid="mtf-bar">
        <b>{asset}</b> <span className="mono">{snap?.broker_symbol ?? "—"}</span> · profil <span className="mono">{snap?.profile_id ?? "—"}</span> · tryb SHADOW
        · <span className={cls("chip", health.overall === "OK" ? "ok" : "bad")} data-testid="mtf-health">dane: {STATUS_PL[health.overall] ?? health.overall ?? "—"}</span>
        · MT5 {health.connection ?? "—"} · Bid {fmtNum(health.quote?.bid, snap?.digits ?? 2)} / Ask {fmtNum(health.quote?.ask, snap?.digits ?? 2)} (spread {fmtNum(health.quote?.spread, snap?.digits ?? 2)}, wiek {health.quote?.age_s ?? "—"} s / TTL {health.quote?.ttl_s} s)
        · sesja: {health.market_session_status ?? "—"} · serwer {health.server_now ? health.server_now.slice(11, 19) + " UTC" : "—"} (lokalnie {new Date().toLocaleTimeString()})
        · Execution Lock: <b>{s.execution_lock ?? "—"}</b>
        {snap?.data_mode === "DANE SYNTETYCZNE" && <span className="chip bad"> DANE SYNTETYCZNE</span>}
        <br />Analiza: as-of <b>{snap?.as_of ? snap.as_of.slice(11, 16) + " UTC" : "—"}</b>, policzona {snap ? fmtTime(snap.computed_at, true) : "—"}, snapshot <span className="mono" data-testid="mtf-snapshot-id">{snap?.snapshot_id ?? "—"}</span>
        {" "}{health.analysis_valid === false && live ? <span className="chip bad">analiza nieważna wg heartbeat (bez przeliczenia)</span> : null}
        {snap?.archived && <span className="chip"> ARCHIWUM</span>}
        <span className="mtf-actions">
          {PRESETS.map(([k, l]) => <button key={k} className={cls("chip", preset === k && "on")} aria-pressed={preset === k} onClick={() => setPreset(k)}>{l}</button>)}
          <button className="btn ghost" onClick={() => setPaused(!paused)} aria-pressed={paused}>{paused ? "Wznów widok" : "Pauza widoku"}</button>
          {(inspect || paused) && <button className="btn" data-testid="mtf-live" onClick={() => { setInspect(null); setPaused(false); load(null); }}>LIVE</button>}
          <select aria-label="Inspekcja zapisanego snapshotu" value={inspect || ""} onChange={(e) => setInspect(e.target.value || null)}>
            <option value="">inspekcja: (bieżący)</option>
            {archive.map((a) => <option key={a.snapshot_id} value={a.snapshot_id}>{a.as_of?.slice(5, 16)} {a.setup_ids ? `· ${a.setup_ids}` : ""}</option>)}</select></span>
      </div>
      {d?.status === "ARCHIVE_SNAPSHOT_UNAVAILABLE" && <p className="card">ARCHIVE_SNAPSHOT_UNAVAILABLE – brak zapisanego snapshotu {d.snapshot_id}; nie podstawiono bieżącego.</p>}
      {!snap && d && d.status !== "ARCHIVE_SNAPSHOT_UNAVAILABLE" && <p className="card muted">Brak snapshotu: {d.scalp_status} {d.scalp_reason ?? ""} (czekam na zamknięcie M1 z MT5).</p>}

      {snap && <div className="card" data-testid="mtf-matrix">
        <h3>Macierz MTF <span className="muted small">(zgodność kilku TF ≠ pewność zysku; filtr profilu: tryb {snap.context_filter?.BUY?.mode})</span></h3>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>TF</th><th>Rola</th><th>Dane (analiza / teraz)</th><th>Świece</th><th>Reżim (wyświetl.)</th><th>Wskaźniki</th><th>LONG</th><th>SHORT</th></tr></thead>
          <tbody>{snap.timeframes.map((r: any) => {
            const now = hRows[r.tf];
            const c = Object.fromEntries((r.context_conditions || []).map((x: any) => [x.side, x]));
            return (
              <tr key={r.tf} data-tf={r.tf} className={cls(focusTf === r.tf && "sel")} tabIndex={0} onClick={() => setFocusTf(r.tf)} onKeyDown={(e) => e.key === "Enter" && setFocusTf(r.tf)}>
                <td><b>{r.tf}</b></td><td title={r.use}>{r.label}{r.required ? " · wymagany" : ""}</td>
                <td>{STATUS_PL[r.data_status] ?? r.data_status} / <span data-testid={`mtf-now-${r.tf}`}>{STATUS_PL[now?.data_status] ?? now?.data_status ?? "—"}</span>
                  <div className="muted">ost. zamknięcie {r.last_closed_close?.slice(11, 16) ?? "—"}; następne {now?.expected_next_close?.slice(11, 16) ?? "—"}</div></td>
                <td>{r.bars_count}/{r.required_bars}</td><td title={r.regime_note}>{r.regime_display ?? "—"}</td>
                <td className="mono">{r.indicators ? Object.entries(r.indicators).filter(([k]) => k !== "status").map(([k, v]) => `${k} ${v ?? "—"}`).join(" · ") : "—"}</td>
                {["BUY", "SELL"].map((sd) => <td key={sd} title={c[sd]?.detail}>{c[sd] ? `${STATUS_PL[c[sd].status] ?? c[sd].status}${c[sd].participates ? "" : " (info)"}` : "—"}</td>)}
              </tr>);
          })}</tbody></table></div>
        <p className="small">Filtr kontekstu strategii (jak w silniku): LONG {snap.context_filter?.BUY?.status} – {snap.context_filter?.BUY?.detail}; SHORT {snap.context_filter?.SELL?.status} – {snap.context_filter?.SELL?.detail}.
          Stan maszyny: <b>{STATE_PL[machine?.state] ?? machine?.state ?? "—"}</b>{machine?.range ? ` · zakres ${machine.range.range_id} L ${fmtNum(machine.range.L, 2)} H ${fmtNum(machine.range.H, 2)} (ważny do ${machine.range.ttl_end?.slice(11, 16)})` : ""}</p>
      </div>}

      {snap && <div className={cls("mtf-grid", !narrow && "with-side")}>
        <div className={cls("mtf-charts", `n${shown.length}`)}>
          {narrow && <div className="chips-row" role="tablist">{TFS.map((t) => <button key={t} role="tab" aria-selected={focusTf === t} className={cls("chip", focusTf === t && "on")} onClick={() => setFocusTf(t)}>{t}</button>)}</div>}
          {shown.map((tf) => <MtfChart key={tf} tf={tf} chartId={`mtf-${tf}`} workspace="scalp-mtf" instrument={asset} epoch={epoch} snapshotId={snap.snapshot_id}
            setupId={setup?.setup_id} height={chartH(tf)} focusTime={["M1", "M5"].includes(tf) ? evidence : null} onExpired={() => load(null)}
            title={`${tf} · ${snap.timeframes.find((r: any) => r.tf === tf)?.label ?? ""}`} />)}
        </div>
        <div className="card mtf-side" data-testid="mtf-setup">
          <h3>Setup</h3>
          {!setups.length ? <p className="small muted">Brak ocenionych kandydatów tego instrumentu. Etap: {STATE_PL[machine?.state] ?? machine?.state ?? "—"} – {machine?.directions ? Object.entries(machine.directions).map(([k, v]: [string, any]) => `${k}: ${STATE_PL[v.state] ?? v.state}${v.reason ? ` (${v.reason})` : ""}`).join("; ") : ""}</p> : <>
            <select aria-label="Oglądany setup" value={setup?.setup_id || ""} onChange={(e) => setSetupSel(e.target.value)}>
              {setups.map((x) => <option key={x.setup_id} value={x.setup_id}>{x.setup_id} · {x.side} · {STATE_PL[x.state] ?? x.state}</option>)}</select>
            <p className="small">{setup.side} · {STATE_PL[setup.state] ?? setup.state} · sygnał {setup.signal_time?.slice(11, 16)} UTC
              · <a href={href("warunki", { setupId: setup.setup_id })}>Warunki setupu</a></p>
            <p className="small"><b>{setup.completeness.label}: {setup.completeness.met}/{setup.completeness.of}</b> · blokady: {setup.hard_gates.length ? setup.hard_gates.map((g: any) => g.name).join(", ") : "brak"}</p>
            <ul className="small mtf-conds">{setup.conditions.map((c: any) => (
              <li key={c.name} data-status={c.status}><span className={cls("chip", c.status === "MET" ? "ok" : "bad")}>{c.status === "MET" ? "✓ spełniony" : "✗ brakuje"}</span> {c.name}
                <span className="muted"> – {c.detail}</span>
                <button className="btn ghost" onClick={() => setEvidence(setup.signal_time ? Math.floor(Date.parse(setup.signal_time) / 1000) - 60 : null)} title="Pokaż dowód na M1/M5 w czasie sygnału">dowód</button></li>))}</ul>
            <p className="small">Trigger: {setup.trigger?.confirmation ?? "—"} · Unieważnienie: {setup.invalidation ? `${fmtNum(setup.invalidation.inval_lo, 2)} / ${fmtNum(setup.invalidation.inval_hi, 2)}` : "—"} · Wygaśnięcie: {setup.expiry?.slice(11, 16) ?? "—"}</p>
            <p className="small">Poziomy (hipotetyczne, SHADOW): {setup.levels.map((l: any) => `${l.kind} ${fmtNum(l.price, snap.digits ?? 2)}`).join(" · ") || "—"}</p>
            <h4>Modele</h4>
            <ul className="small" data-testid="mtf-models">{setup.models.map((m: any) => <li key={m.task_id}><b>{m.task_id}</b> – {m.target_definition}: {m.status}
              {m.calibrated_output != null ? ` · ${Array.isArray(m.calibrated_output) ? m.calibrated_output.map((x: number) => fmtNum(x * 100, 1) + "%").join(" / ") : fmtNum(m.calibrated_output * 100, 1) + "%"}` : ""}
              {m.expected_net_r != null ? ` · net_R ${fmtNum(m.expected_net_r, 3)} R` : ""}{m.role ? ` · rola ${m.role}` : ""}{m.note ? ` (${m.note})` : ""}</li>)}</ul>
            <p className="muted small">Różne zadania = różne wielkości; nie są uśredniane. Wykonanie: {snap.execution?.status}.</p>
          </>}
          <button className="btn ghost" onClick={() => setShowJournal(!showJournal)} aria-expanded={showJournal}>Dziennik ({machine?.journal?.length ?? 0})</button>
          {showJournal && <ul className="small" data-testid="mtf-journal">{(machine?.journal || []).slice().reverse().map((j: any, i: number) => <li key={i}>{typeof j === "string" ? j : `${j.t ?? j.time ?? ""} ${j.state ?? ""} ${j.reason ?? j.msg ?? ""}`}</li>)}</ul>}
        </div>
      </div>}
    </div>);
}
