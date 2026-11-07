// Precision → „XAUUSD × DXY i wskaźniki” (1.33, PMW-IND-1): relation to DXY on H1 (no forward fill), AVWAP sesji/zdarzenia, spread
// względem sesji, semiwariancja, mikrostruktura (OFI/arkusz) i profil. Wartości z backendu; wskaźniki same nie blokują strategii.
import { useMemo, useState } from "react";
import { apiSend } from "../../api";
import { cls, fmtTime } from "../../util";
import { num, STATUS_PL, tone, usePoll } from "./usePoll";
import "./pmw133.css";

function Badge({ st, reason }: { st?: string | null; reason?: string | null }) {
  return <span className={cls("badge", tone(st))} title={reason ?? ""}>{STATUS_PL[st ?? ""] ?? st ?? "—"}</span>;
}

function DxyChart({ series }: { series: any[] }) {
  const W = 640, H = 180;
  const pts = (series || []).filter((p) => typeof p.xau_cum === "number" && typeof p.dxy_cum === "number");
  if (pts.length < 2) return <p className="pmw-na">Za mało wspólnych godzin XAUUSD i DXY do wykresu.</p>;
  const all = pts.flatMap((p) => [p.xau_cum, p.dxy_cum]);
  const lo = Math.min(...all), hi = Math.max(...all), sp = hi - lo || 1;
  const x = (i: number) => (i / (pts.length - 1)) * (W - 20) + 10;
  const y = (v: number) => H - 10 - ((v - lo) / sp) * (H - 20);
  const path = (k: string) => pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ");
  return (
    <svg className="pmw-dxy-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Skumulowane log-zwroty XAUUSD i DXY (H1, wspólne godziny)" data-testid="dxy-chart">
      <line x1="10" x2={W - 10} y1={y(0)} y2={y(0)} className="zero" />
      <path d={path("xau_cum")} className="xau" /><path d={path("dxy_cum")} className="dxy" />
      <text x="14" y="16" className="lg xau">XAUUSD</text><text x="90" y="16" className="lg dxy">DXY</text>
      <text x={W - 12} y="16" textAnchor="end" className="lg">{fmtTime(pts[0].t, true)} – {fmtTime(pts[pts.length - 1].t, true)}</text>
    </svg>);
}

export default function DxyPage() {
  const snap = usePoll<any>("/api/v1/indicators/snapshot", 10000);
  const dxy = usePoll<any>("/api/v1/indicators/dxy", 30000);
  const st = usePoll<any>("/api/v1/indicators/status", 10000);
  const anchors = usePoll<any>("/api/v1/indicators/anchors", 30000);
  const [msg, setMsg] = useState<string | null>(null);
  const [anc, setAnc] = useState({ tf: "M5", source_time: "", label: "" });
  const s = snap.data;
  const d = dxy.data;
  const windows = useMemo(() => Object.entries(d?.windows || {}) as [string, any][], [d]);
  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); setMsg(ok); await Promise.all([snap.reload(), dxy.reload(), anchors.reload()]); } catch (e: any) { setMsg(String(e?.message || e)); }
  };
  return (
    <div className="pmw-page" data-testid="page-dxy">
      <header className="pmw-head">
        <h2>XAUUSD × DXY i wskaźniki PMW</h2>
        <span className="pmw-sub">Kontekst H1 i M1/M5 – informacja analityczna, nie sygnał wejścia. Pasma σ nie są przedziałami prawdopodobieństwa.</span>
        <span className="spacer" />
        <button className="btn" data-testid="ind-refresh" onClick={() => act(() => apiSend("POST", "/api/v1/indicators/refresh"), "Przeliczono wskaźniki.")}>Przelicz teraz</button>
      </header>
      {(snap.err || dxy.err) && <p className="pmw-err">Błąd: {snap.err || dxy.err}</p>}
      {msg && <p className="pmw-msg" role="status">{msg}</p>}
      <section className="pmw-card" data-testid="dxy-card">
        <h3>Relacja XAUUSD × DXY <Badge st={d?.status} reason={d?.reason} /></h3>
        {d?.status === "DISABLED" ? <p className="pmw-na">DXY wyłączony: {d?.reason === "DXY_SYMBOL_NOT_CONFIGURED" ? "ustaw symbol DXY brokera w Ustawieniach (pole „Symbol DXY (opcjonalnie)”)." : d?.reason}</p> : <>
          <table className="pmw-t"><thead><tr><th>Okno (h)</th><th>obs.</th><th>korelacja</th><th>beta</th><th>reszta z</th><th>stabilność</th><th>uwagi</th></tr></thead>
            <tbody>{windows.map(([w, x]) => (
              <tr key={w}><td>{w}</td><td>{x.n}</td><td>{num(x.corr)}</td><td>{num(x.beta)}</td><td>{num(x.resid_z)}</td>
                <td>{x.unstable == null ? "—" : x.unstable ? "niestabilna" : "stabilna"}</td><td>{x.reason ?? ""}</td></tr>))}</tbody></table>
          <p className="pmw-meta">Wspólne obserwacje: {d?.sample_count ?? "—"} · dane do: {fmtTime(d?.data_time, true)} · źródło: {d?.source} {d?.broker_symbol}
            {d?.dxy?.last_available_at ? ` · ostatni bar DXY: ${fmtTime(d.dxy.last_available_at, true)}` : ""}</p>
          <DxyChart series={d?.presentation?.series || []} />
          <p className="pmw-note">{d?.presentation?.note}</p></>}
      </section>
      <div className="pmw-grid">
        <section className="pmw-card" data-testid="avwap-card">
          <h3>AVWAP (sesja / zdarzenie)</h3>
          <table className="pmw-t"><thead><tr><th>linia</th><th>stan</th><th>AVWAP</th><th>σ</th><th>odl. ATR</th><th>odl. σ</th><th>nachyl.</th><th>strona</th><th>kotwica</th></tr></thead>
            <tbody>{Object.entries(s?.avwap || {}).map(([k, a]: [string, any]) => (
              <tr key={k}><td>{k.replace("_", " ")}</td><td><Badge st={a.status} reason={a.reason} /></td><td>{num(a.avwap)}</td><td>{num(a.sigma)}</td>
                <td>{num(a.distance_atr)}</td><td>{num(a.distance_sigma)}</td><td>{num(a.slope_atr, 3)}</td><td>{a.side ?? "—"}</td>
                <td>{a.anchor ?? "—"}{a.anchor_version ? ` v${a.anchor_version}` : ""}</td></tr>))}</tbody></table>
          <details className="pmw-det"><summary>Kotwice ręczne ({(anchors.data?.items || []).length})</summary>
            <div className="pmw-form">
              <select value={anc.tf} onChange={(e) => setAnc({ ...anc, tf: e.target.value })}>{["M1", "M5"].map((t) => <option key={t}>{t}</option>)}</select>
              <input placeholder="czas UTC, np. 2026-11-06T13:30:00Z" value={anc.source_time} onChange={(e) => setAnc({ ...anc, source_time: e.target.value })} />
              <input placeholder="opis" value={anc.label} onChange={(e) => setAnc({ ...anc, label: e.target.value })} />
              <button className="btn" onClick={() => act(() => apiSend("POST", "/api/v1/indicators/anchors", anc), "Dodano kotwicę.")}>Dodaj</button>
            </div>
            <ul>{(anchors.data?.items || []).map((a: any) => (
              <li key={a.anchor_id}>{a.tf} {fmtTime(a.source_time, true)} {a.label ?? ""} <button className="link" onClick={() => act(() => apiSend("DELETE", `/api/v1/indicators/anchors/${a.anchor_id}`), "Usunięto kotwicę.")}>usuń</button></li>))}</ul>
          </details>
        </section>
        <section className="pmw-card" data-testid="spread-card">
          <h3>Spread względem sesji <Badge st={s?.spread?.status} reason={s?.spread?.reason} /></h3>
          <dl className="pmw-dl"><dt>spread</dt><dd>{num(s?.spread?.spread_price, 3)} ({num(s?.spread?.spread_ticks, 0)} tick.)</dd>
            <dt>× ATR</dt><dd>{num(s?.spread?.spread_atr, 3)}</dd><dt>percentyl sesji</dt><dd>{num(s?.spread?.percentile, 0)}</dd>
            <dt>nietypowy</dt><dd>{s?.spread?.unusual ? "TAK" : "nie"}</dd><dt>próbki</dt><dd>{st.data?.spread_samples ?? "—"}</dd></dl>
        </section>
        <section className="pmw-card" data-testid="semivar-card">
          <h3>Semiwariancja <Badge st={s?.semivar?.status} reason={s?.semivar?.reason} /></h3>
          <dl className="pmw-dl"><dt>udział spadków 20</dt><dd>{num(s?.semivar?.downside_share_20)}</dd><dt>udział spadków 60</dt><dd>{num(s?.semivar?.downside_share_60)}</dd>
            <dt>RV 20</dt><dd>{num(s?.semivar?.rv_20, 5)}</dd><dt>RV 60</dt><dd>{num(s?.semivar?.rv_60, 5)}</dd></dl>
        </section>
        <section className="pmw-card" data-testid="micro-card">
          <h3>Mikrostruktura (arkusz MT5) <Badge st={s?.microstructure?.status} reason={s?.microstructure?.reason} /></h3>
          <dl className="pmw-dl"><dt>nierównowaga best</dt><dd>{num(s?.microstructure?.best_imbalance, 3)}</dd><dt>nierównowaga głęb.</dt><dd>{num(s?.microstructure?.depth_imbalance, 3)}</dd>
            <dt>OFI okno</dt><dd>{num(s?.microstructure?.ofi_window, 2)}</dd><dt>microprice − mid</dt><dd>{num(s?.microstructure?.microprice_dev, 4)}</dd>
            <dt>tryb</dt><dd>{st.data?.book?.ofi?.mode ?? "—"}{st.data?.book?.ofi?.estimate ? " (estymata)" : ""}</dd></dl>
        </section>
        <section className="pmw-card" data-testid="profile-card">
          <h3>Profil sesji <Badge st={s?.profile?.status} reason={s?.profile?.reason} /></h3>
          <dl className="pmw-dl"><dt>odl. POC (ATR)</dt><dd>{num(s?.profile?.dev_dist_poc_atr)}</dd><dt>pozycja w VA</dt><dd>{s?.profile?.dev_va_position ?? "—"}</dd>
            <dt>wolumen względny</dt><dd>{num(s?.profile?.relative_volume)}</dd><dt>migracja POC</dt><dd>{s?.profile?.poc_migration_bins ?? "—"}</dd>
            <dt>kształt</dt><dd>{s?.profile?.dev_shape ?? "—"}</dd></dl>
        </section>
      </div>
      <p className="pmw-meta">Snapshot {s?.snapshot_id ?? "—"} · {fmtTime(s?.as_of, true)} · {st.data?.note}</p>
    </div>);
}
