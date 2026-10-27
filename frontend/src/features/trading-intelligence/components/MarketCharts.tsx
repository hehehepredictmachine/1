// Market overview: 1 / 4 / 6 charts of the active instrument, interval per chart, enlarge, chart mode (overlays), saved layout. Each
// chart is the existing ChartPanel (candles from /api/v1/candles + live bars of the single WebSocket) - no separate price source.
import { useEffect, useRef, useState } from "react";
import ChartPanel from "../../../components/ChartPanel";
import ChartToolbar, { useChartOpts } from "../../../components/ChartToolbar";
import { usePersisted } from "../../../router";
import { useStore } from "../../../store";
import { cls } from "../../../util";

export const TI_TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
type Saved = { n: 1 | 4 | 6; tfs: string[] };
const DEFAULT: Saved = { n: 4, tfs: ["M5", "M15", "H1", "H4", "M30", "D1"] };
const valid = (v: any) => v && [1, 4, 6].includes(v.n) && Array.isArray(v.tfs) && v.tfs.length === 6 && v.tfs.every((t: any) => TI_TFS.includes(t));

export default function MarketCharts({ modeOpen, onModeClose }: { modeOpen: boolean; onModeClose: () => void }) {
  const { s } = useStore();
  const [saved, setSaved] = usePersisted<Saved>("ti.layout", DEFAULT, valid);
  const [draft, setDraft] = useState<Saved>(saved);
  const [full, setFull] = useState<number | null>(null);
  const [opts, setOpt] = useChartOpts("ti", { showAiLevels: true, showVol: false });
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const meta = s.tf_meta || {};
  const toolRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!modeOpen) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onModeClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [modeOpen, onModeClose]);
  const setTf = (i: number, tf: string) => setDraft({ ...draft, tfs: draft.tfs.map((t, j) => (j === i ? tf : t)) });
  const slots = draft.tfs.slice(0, draft.n);
  return (
    <section className="t-card t-market" aria-labelledby="ti-market-h" data-testid="ti-market">
      <header className="t-card-head">
        <h2 id="ti-market-h">Przegląd rynku <span className="t-dim">· {s.symbol?.symbol ?? "—"}</span></h2>
        <span className="t-dim">Świece z terminala MT5{s.synthetic ? " (symulator)" : ""}</span>
      </header>
      <div className="t-row t-layout-row" role="group" aria-label="Układ wykresów">
        <span>Układ wykresów</span>
        <div className="t-seg-switch">
          {([1, 4, 6] as const).map((n) => (
            <button key={n} className={cls(draft.n === n && "on")} aria-pressed={draft.n === n} onClick={() => { setDraft({ ...draft, n }); setFull(null); }}
              data-testid={`ti-layout-${n}`}>{n}</button>))}
        </div>
        <button className="t-btn t-btn-acc" disabled={!dirty} onClick={() => setSaved(draft)} data-testid="ti-layout-save">Zapisz</button>
        {dirty && <span className="t-dim" data-testid="ti-layout-dirty">niezapisane zmiany układu</span>}
      </div>
      {modeOpen && (
        <div className="t-chart-mode" ref={toolRef} role="dialog" aria-label="Tryb wykresów" data-testid="ti-chart-mode">
          <ChartToolbar opts={opts} set={setOpt} />
          <button className="t-btn" onClick={onModeClose}>Zamknij</button>
        </div>)}
      <div className={cls("t-charts", `n${draft.n}`)} data-testid="ti-charts" data-n={draft.n}>
        {slots.map((tf, i) => (
          <div key={i} className={cls("t-chart-cell", full === i && "full")} data-testid="ti-chart" data-tf={tf}>
            <div className="t-chart-bar">
              <select value={tf} onChange={(e) => setTf(i, e.target.value)} aria-label={`Interwał wykresu ${i + 1}`} data-testid="ti-chart-tf">
                {TI_TFS.map((t) => (
                  <option key={t} value={t} disabled={meta[t] ? meta[t].loaded === false : false}>{t}{meta[t] && !meta[t].loaded ? " (brak danych)" : ""}</option>))}
              </select>
            </div>
            <ChartPanel tf={tf} index={i} chartId={`ti${i}`} opts={opts} variant="compact" fullscreen={full === i}
              onFullscreen={() => setFull(full === i ? null : i)} />
          </div>))}
      </div>
    </section>);
}
