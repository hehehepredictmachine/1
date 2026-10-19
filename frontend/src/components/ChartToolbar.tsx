// Chart options of one page (each page keeps its own set; the defaults of "Analiza AI" are a clean price chart).
import type { ChartOpts } from "./ChartPanel";
import { usePersisted } from "../router";
import type { TimeZoneMode } from "../util";

const BASE: ChartOpts = { showRsi: false, showMacd: false, showStructure: false, showZones: false, showVol: false, syncCrosshair: false, tz: "LOCAL",
  showPatterns: false, showAiLevels: true, showSar: false, showExtInd: false, showSessions: false, showHeatmap: false };

/** Per-page chart options. `legacy` = the 1.9 key (one set for the whole monitor) used once as the starting point. */
export function useChartOpts(page: string, defaults: Partial<ChartOpts>, legacy?: string): [ChartOpts, (k: keyof ChartOpts, v: any) => void] {
  let init: ChartOpts = { ...BASE, ...defaults };
  if (legacy) {
    try {
      const raw = localStorage.getItem("mq." + legacy);
      if (raw && !localStorage.getItem(`mq.chartopts.${page}`)) init = { ...init, ...JSON.parse(raw), showVol: JSON.parse(raw).showVol !== false };
    } catch { /* corrupted storage: defaults */ }
  }
  const [o, setO] = usePersisted<ChartOpts>(`chartopts.${page}`, init, (v) => v && typeof v === "object" && typeof v.tz === "string");
  const opts = { ...BASE, ...defaults, ...o };
  return [opts, (k, v) => setO({ ...opts, [k]: v })];
}

const LABELS: [keyof ChartOpts, string, string][] = [
  ["showAiLevels", "Poziomy AI", "poziomy zaproponowane przez AI – oznaczone „AI:”, osobno od planu silnika"],
  ["showPatterns", "Walls / zakres / formacje", "snapshot walls (HV_PROXY lub IV – źródło na etykiecie), zakres M5 i strefy M1, formacje, pivoty, dowody świecowe"],
  ["showSar", "SAR", "Parabolic SAR (profil MQ_SAR_WILDER_PROFILE_V1, step/max z profilu) – punkty zamkniętych świec; flip potwierdza zamknięta świeca"],
  ["showExtInd", "IQ / PAL", "poziomy IQ Gold Gann / IQ Star Lines z zatwierdzonego mappingu eksportera (wersja znana teraz); brak źródła = brak linii"],
  ["showSessions", "Boksy sesji", "Session Sweep Boxes – wspólny silnik sesji (profil z ustawień); FINAL tylko przy kompletnych danych okna; zdarzenia sweep / wybicie z czasem potwierdzenia"],
  ["showHeatmap", "Heatmapa likwidacji", "szacowane poziomy likwidacji dostawcy (CoinGlass model1) – osobny panel z osią ceny źródła; brak źródła = brak mapy"],
  ["showStructure", "BOS/CHoCH", "struktura rynku"],
  ["showZones", "FVG/OB", "strefy FVG i order block"],
  ["showVol", "Walls dzienne / Daily", "pasma zmienności dnia (źródło: HV_PROXY = przybliżenie z historii brokera, IV tylko z importu) i daily open/high/low"],
  ["showRsi", "RSI", "panel RSI"],
  ["showMacd", "MACD", "panel MACD"],
  ["syncCrosshair", "Wspólny celownik", "celownik na wszystkich wykresach tej strony"],
];

export default function ChartToolbar({ opts, set, show = LABELS.map((x) => x[0]), extra }: {
  opts: ChartOpts; set: (k: keyof ChartOpts, v: any) => void; show?: (keyof ChartOpts)[]; extra?: React.ReactNode;
}) {
  return (
    <div className="chart-toolbar" role="group" aria-label="Opcje wykresów">
      {extra}
      <div className="toggles">
        {LABELS.filter(([k]) => show.includes(k)).map(([k, l, t]) => (
          <label key={k} title={t}><input type="checkbox" checked={opts[k] !== false && !!opts[k]} onChange={(e) => set(k, e.target.checked)} />{l}</label>
        ))}
        <select value={opts.tz} onChange={(e) => set("tz", e.target.value as TimeZoneMode)} aria-label="Strefa czasu na wykresach" title="Strefa czasu na wykresach (dane zawsze w UTC)">
          <option value="LOCAL">Czas lokalny</option><option value="UTC">UTC</option><option value="SERVER">Czas serwera</option>
        </select>
      </div>
    </div>
  );
}
