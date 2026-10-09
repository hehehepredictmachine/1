// Per-chart view state, keyed by chart_id + symbol + timeframe (two panels with the same TF stay independent).
// Versioned localStorage; only user actions (wheel, drag, pinch, buttons) change it - data refreshes never do.

export type SyncGroup = "" | "A" | "B";
export type ChartView = {
  follow: boolean;                 // right edge follows the newest candle
  from?: number;                   // visible time range (chart time, seconds) when not following
  to?: number;
  width?: number;                  // visible logical width (bars) - zoom level, also used while following
  rightGap?: number;               // empty bars to the right of the last candle while following
  autoScale: boolean;              // price axis auto-scale
  group: SyncGroup;                // optional time-range sync group (default: none)
};

const KEY = "mq.chartview.v1";
export const DEFAULT_VIEW: ChartView = { follow: true, autoScale: true, group: "", width: 150, rightGap: 6 };

function readAll(): Record<string, ChartView> {
  try {
    const j = JSON.parse(localStorage.getItem(KEY) || "{}");
    return j && j.version === 1 && typeof j.views === "object" ? j.views : {};
  } catch {
    return {};
  }
}

export function viewKey(chartId: string, symbol: string, tf: string): string {
  return `${chartId}|${symbol}|${tf}`;
}

export function loadView(key: string): ChartView {
  const v = readAll()[key];
  return v ? { ...DEFAULT_VIEW, ...v } : { ...DEFAULT_VIEW };
}

let pending: Record<string, ChartView> = {};
let timer: ReturnType<typeof setTimeout> | null = null;

export function saveView(key: string, v: ChartView): void {
  pending[key] = v;
  if (timer) return;
  timer = setTimeout(() => {
    timer = null;
    try {
      const all = { ...readAll(), ...pending };
      pending = {};
      localStorage.setItem(KEY, JSON.stringify({ version: 1, views: all }));
    } catch {
      /* storage unavailable: state lives for this session only */
    }
  }, 250);
}

// cross-chart bus: crosshair (global toggle) and time range (only inside the same group)
export type SyncMsg = { src: string; kind: "crosshair" | "range"; group?: SyncGroup; time?: number | null; from?: number; to?: number };
export const SYNC = new EventTarget();
