// 01 CHARTS 1:1 (pakiet update_charts, K1). Znaczniki = update_charts/referencje/kod/charts_wzorzec/charts.html (te same id, klasy,
// role, aria-*). Zawartość #ch-asset, #ch-tf, #kr-tf, #mc-read, #sig-card, #opt-body tworzy renderer (chartsRender.ts, kod wzorca) –
// React nie zarządza dziećmi tych elementów. Ekran tylko odczytuje dane (GET); żadnych zleceń ani zapisów w backendzie.
import { useEffect, useRef } from "react";
import { useStore } from "../../../../store";
import { createCharts } from "./chartsRender";
import { svpVisibleVM, useChartsData } from "./chartsData";
import { apiGet } from "../../../../api";
import "./charts.css";

export type ChartsApi = ReturnType<typeof createCharts>;

export default function ChartsScreen({ register, active, testMode }: { register: (api: ChartsApi | null) => void; active: boolean; testMode?: boolean }) {
  const { s } = useStore();
  const api = useRef<ChartsApi | null>(null);
  useEffect(() => {
    const a = createCharts({ announce: (t) => { const el = document.getElementById("fx-announcer"); if (el) el.textContent = t; },
      // K5: profil widocznego zakresu z API (GET, bez zapisu); w trybie testowym brak → port 1:1
      visible: testMode ? undefined : (q) => apiGet<any>(`/api/v1/svp/visible?tf=${q.tf}&t0=${new Date(q.t0).toISOString()}&t1=${new Date(q.t1).toISOString()}&bin_ticks=${q.bin}&va_pct=${q.va}`)
        .then(svpVisibleVM) });
    api.current = a;
    register(a);
    return () => { a.dispose(); api.current = null; register(null); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useChartsData(api, active && !testMode, s);
  const synthetic = !!s.synthetic && !testMode;
  return (
    <section id="charts-screen" aria-label="CHARTS" inert data-testid="forex-charts">
      <canvas id="chart" aria-hidden="true" />
      <div id="ch-head" className="ci">
        <div id="ch-title" aria-hidden="true"><span className="n">01</span>CHARTS</div><span className="ch-sep" />
        <div id="ch-asset" className="segb" role="group" aria-label="Aktywny instrument" /><span className="ch-sep" />
        <div id="ch-tf" className="segb" role="group" aria-label="Interwał" data-testid="charts-tf" />
        <div id="ch-right"><span id="ch-quote" />
          <select id="ch-tz" aria-label="Strefa czasu wykresu" defaultValue="LOCAL"><option value="LOCAL">CZAS LOKALNY</option><option value="UTC">UTC</option><option value="SERVER">CZAS SERWERA</option></select>
          <div id="ch-status" data-s="loading" role="status"><i /><span className="t">ŁADOWANIE</span></div>
          <span className="demo-tag" title="Dane syntetyczne – symulator terminala, nie notowania rynku" hidden={!synthetic} data-testid="badge-charts-synthetic">SYNTETYCZNE</span></div>
      </div>
      <div className="cs-wrap">
        <div className="cs-win main ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div className="wh"><span className="ttl" id="mc-title">XAUUSD- · M15</span><span>WYKRES GŁÓWNY</span><span className="sp">PRZECIĄGNIJ · KÓŁKO = ZOOM · 2× KLIK = TERAZ</span></div>
          <div id="mc-read" /><div id="sig-card" className="ci" aria-live="polite" /><div id="mc-plot" tabIndex={0} aria-label="Wykres główny. Strzałki przesuwają, plus i minus przybliżają." />
        </div>
        <div className="cs-side">
          <div className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
            <div className="wh"><span className="ttl">◈ KRONOS</span><div id="kr-tf" className="segb" role="group" aria-label="Interwał Kronos" /><span className="sp">TRYB <span id="kr-mode">AUTO</span></span><button type="button" id="kr-refresh">PRZELICZ</button></div>
            <div id="kr-plot" aria-label="Wykres Kronos: świece rzeczywiste i prognozowana ścieżka" />
            <div id="kr-foot"><span id="kr-dir">—</span><span id="kr-delta" /><span id="kr-read" /><span id="kr-meta" /></div>
          </div>
          <div className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
            <div id="opt-tabs" role="tablist" aria-label="Warstwy wykresu"><button type="button" role="tab" data-t="ind" aria-selected="true">WSKAŹNIKI</button><button type="button" role="tab" data-t="strat" aria-selected="false">STRATEGIE</button><button type="button" role="tab" data-t="zones" aria-selected="false">STREFY</button><button type="button" role="tab" data-t="vp" aria-selected="false">VOLUME PROFILE</button><button type="button" role="tab" data-t="models" aria-selected="false">PLAN · MODELE</button><button type="button" role="tab" data-t="chart" aria-selected="false">WYKRES</button></div>
            <div id="opt-body" />
          </div>
        </div>
      </div>
    </section>);
}
