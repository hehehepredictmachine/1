import type {
  IChartApi,
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

export interface Zone {
  from: number; // chart time (already shifted)
  low: number;
  high: number;
  color: string;
  border: string;
  label: string;
}

// Draws rectangular zones (FVG / OB candidates) from their confirmation time to the right edge.
export class ZonesPrimitive implements ISeriesPrimitive<Time> {
  private zones: Zone[] = [];
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private view: IPrimitivePaneView;

  constructor() {
    const self = this;
    const renderer: IPrimitivePaneRenderer = {
      draw(target) {
        const chart = self.chart;
        const series = self.series;
        if (!chart || !series) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          for (const z of self.zones) {
            const y1 = series.priceToCoordinate(z.high);
            const y2 = series.priceToCoordinate(z.low);
            if (y1 === null || y2 === null) continue;
            let x1 = chart.timeScale().timeToCoordinate(z.from as Time);
            if (x1 === null) {
              const vr = chart.timeScale().getVisibleRange();
              if (vr && (vr.from as number) > z.from) x1 = 0 as any;
              else continue;
            }
            const x = Math.max(0, x1 as number);
            const w = mediaSize.width - x;
            const top = Math.min(y1, y2);
            const h = Math.max(1, Math.abs(y2 - y1));
            context.fillStyle = z.color;
            context.fillRect(x, top, w, h);
            context.strokeStyle = z.border;
            context.lineWidth = 1;
            context.strokeRect(x + 0.5, top + 0.5, w - 1, h - 1);
            if (h >= 9) {
              context.fillStyle = z.border;
              context.font = "10px Inter, system-ui, sans-serif";
              context.fillText(z.label, x + 4, top + Math.min(h - 2, 11));
            }
          }
        });
      },
    };
    this.view = { renderer: () => renderer, zOrder: () => "bottom" };
  }

  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi;
    this.series = p.series as ISeriesApi<SeriesType>;
    this.requestUpdate = p.requestUpdate;
  }

  detached() {
    this.chart = null;
    this.series = null;
  }

  paneViews() {
    return [this.view];
  }

  setZones(z: Zone[]) {
    this.zones = z;
    this.requestUpdate?.();
  }
}
