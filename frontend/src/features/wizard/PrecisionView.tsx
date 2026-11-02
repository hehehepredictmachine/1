// Precision – charts and market analysis: the existing chart grid (1 / 4 / 6 charts, interval per chart, zoom, pan, crosshair,
// analysis layers: zones H/L, FVG/OB, BOS/CHoCH, walls, SAR, sessions, RSI/MACD) on candles from /api/v1/candles + the live bars of
// the single WebSocket, plus the source status, regime per interval from the engine and the zone map status. No screenshots, no
// second price source.
import { useEffect, useState } from "react";
import { apiGet } from "../../api";
import { useStore } from "../../store";
import { cls, fmtNum, fmtTime } from "../../util";
import MarketCharts from "../trading-intelligence/components/MarketCharts";
import ViewHeader from "./ViewHeader";

const REG_PL: Record<string, string> = { TREND_UP: "trend wzrostowy", TREND_DOWN: "trend spadkowy", RANGE: "konsolidacja", TRANSITION: "przejście",
  EXPANSION: "ekspansja", COMPRESSION: "kompresja", HIGH_VOL: "wysoka zmienność" };

export function usePoll<T = any>(path: string, every: number): { d: T | null; err: string | null } {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => apiGet(path).then((x: any) => { if (alive) { setD(x); setErr(null); } }).catch((e: any) => { if (alive) setErr(String(e?.message || e)); });
    load();
    const t = setInterval(load, every);
    return () => { alive = false; clearInterval(t); };
  }, [path, every]);
  return { d, err };
}

export default function PrecisionView() {
  const { s } = useStore();
  const [layers, setLayers] = useState(false);
  const zones = usePoll<any>("/api/v1/zones/status", 20000);
  const perTf = s.auto?.regime?.per_tf || {};
  const q = s.quote || {};
  const digits = s.symbol?.info?.digits ?? 2;
  const zs = zones.d;
  return (
    <div className="wz-view wz-precision" data-testid="page-precision">
      <ViewHeader tower="precision">
        <button className="wz-btn" aria-pressed={layers} onClick={() => setLayers(!layers)} data-testid="wz-layers">Warstwy analizy</button>
      </ViewHeader>
      <div className="wz-view-grid">
        <div className="wz-panel wz-panel-charts">
          <MarketCharts modeOpen={layers} onModeClose={() => setLayers(false)} />
        </div>
        <aside className="wz-panel wz-side-info" aria-label="Stan danych i analiz">
          <h2>Notowania</h2>
          <dl className="wz-kv" data-testid="wz-quote">
            <dt>Bid / Ask</dt><dd>{q.bid != null ? `${fmtNum(q.bid, digits)} / ${fmtNum(q.ask, digits)}` : "—"}</dd>
            <dt>Spread</dt><dd>{q.bid != null && q.ask != null ? fmtNum(q.ask - q.bid, digits) : "—"}</dd>
            <dt>Wiek ticka</dt><dd>{q.age_seconds != null ? `${fmtNum(q.age_seconds, 1)} s` : "—"}</dd>
            <dt>Jakość danych</dt><dd>{s.decision?.data_quality ?? "—"}{s.decision?.market_state ? ` · rynek ${s.decision.market_state}` : ""}</dd>
          </dl>
          <h2>Reżim per interwał <span className="wz-dim">(silnik, zamknięte świece)</span></h2>
          {Object.keys(perTf).length === 0 ? <p className="wz-dim">Silnik nie podał jeszcze reżimu.</p> : (
            <table className="wz-table" data-testid="wz-regime">
              <thead><tr><th>TF</th><th>Stan</th><th>Kierunek</th><th>Świeca</th></tr></thead>
              <tbody>{Object.entries(perTf).map(([tf, r]: [string, any]) => (
                <tr key={tf}><td>{tf}</td><td>{REG_PL[r.state] ?? r.state}</td>
                  <td className={cls(r.direction === "UP" && "wz-pos", r.direction === "DOWN" && "wz-neg")}>{r.direction ?? "—"}</td>
                  <td className="wz-dim">{fmtTime(r.as_of_bar)}</td></tr>))}</tbody>
            </table>)}
          <h2>Strefy High/Low</h2>
          {zones.err ? <p className="wz-bad">Brak odpowiedzi modułu stref: {zones.err}</p> : !zs ? <p className="wz-dim">Ładowanie…</p> : (
            <dl className="wz-kv" data-testid="wz-zones">
              <dt>Stan</dt><dd>{zs.status ?? "—"}{zs.restored ? " (odtworzona z bazy – nieaktualna)" : ""}</dd>
              <dt>Instrument</dt><dd>{zs.instrument ?? "—"}</dd>
              {zs.summary && <>
                <dt>Cena</dt><dd>{zs.summary.price != null ? fmtNum(zs.summary.price, 2) : "—"}</dd>
                <dt>Najbliższe wsparcie</dt><dd>{zoneText(zs.summary.nearest_support)}</dd>
                <dt>Najbliższy opór</dt><dd>{zoneText(zs.summary.nearest_resistance)}</dd>
                <dt>Strefy</dt><dd>{zs.summary.zones ?? "—"}{zs.summary.provisional ? ` (wstępne: ${zs.summary.provisional})` : ""}</dd>
              </>}
              <dt>Uwaga</dt><dd className="wz-dim">{zs.note ?? "—"}</dd>
            </dl>)}
          <p className="wz-note">Warstwy (strefy H/L, FVG/OB, BOS/CHoCH, walls, sesje, SAR, RSI/MACD) włączysz przyciskiem „Warstwy analizy”. Zoom: kółko,
            przesuwanie: przeciągnięcie, krzyż celowniczy: ruch kursora.</p>
        </aside>
      </div>
    </div>);
}

/** A zone of the summary in one line: type, price band, status and confluence score (not a probability). */
function zoneText(z: any): string {
  if (!z) return "brak strefy po tej stronie ceny";
  const band = z.lower_price != null && z.upper_price != null ? `${fmtNum(z.lower_price, 2)}–${fmtNum(z.upper_price, 2)}` : "—";
  return `${z.zone_type ?? "strefa"} ${band} · ${z.status ?? "—"}${z.confluence_score != null ? ` · konfluencja ${fmtNum(z.confluence_score, 1)}` : ""}`;
}
