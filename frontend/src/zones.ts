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

// PMW-UPD-06: time-bounded boxes / edge segments / event markers (session sweep boxes). Unlike ZonesPrimitive (to the right edge),
// every item has its own [from, to) in chart time; a segment with low == high is drawn as a line; markers carry their label.
export interface BoundedBox {
  from: number;
  to: number;
  low: number;
  high: number;
  color: string;
  border: string;
  label?: string;
  dashed?: boolean;
}
export interface BoxMarker { time: number; price: number; label: string; color: string; up: boolean }

export class BoundedBoxesPrimitive implements ISeriesPrimitive<Time> {
  private boxes: BoundedBox[] = [];
  private markers: BoxMarker[] = [];
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private view: IPrimitivePaneView;

  constructor() {
    const self = this;
    const xOf = (t: number, width: number): number | null => {
      const chart = self.chart!;
      const x = chart.timeScale().timeToCoordinate(t as Time);
      if (x !== null) return x as number;
      const vr = chart.timeScale().getVisibleRange();
      if (!vr) return null;
      if (t < (vr.from as number)) return 0;
      if (t > (vr.to as number)) return width;
      const lr = chart.timeScale().getVisibleLogicalRange();     // inside the range but between candles (gap): interpolate
      return lr ? null : null;
    };
    const renderer: IPrimitivePaneRenderer = {
      draw(target) {
        const chart = self.chart;
        const series = self.series;
        if (!chart || !series) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          for (const b of self.boxes) {
            const y1 = series.priceToCoordinate(b.high);
            const y2 = series.priceToCoordinate(b.low);
            const x1 = xOf(b.from, mediaSize.width);
            const x2 = xOf(b.to, mediaSize.width);
            if (y1 === null || y2 === null || x1 === null || x2 === null || x2 <= x1) continue;
            const top = Math.min(y1, y2);
            const h = Math.abs(y2 - y1);
            context.setLineDash(b.dashed ? [4, 3] : []);
            context.strokeStyle = b.border;
            context.lineWidth = 1;
            if (h < 1) {
              context.beginPath();
              context.moveTo(x1, top + 0.5);
              context.lineTo(x2, top + 0.5);
              context.stroke();
            } else {
              context.fillStyle = b.color;
              context.fillRect(x1, top, x2 - x1, h);
              context.strokeRect(x1 + 0.5, top + 0.5, x2 - x1 - 1, h - 1);
            }
            if (b.label && x2 - x1 > 30) {
              context.fillStyle = b.border;
              context.font = "10px Inter, system-ui, sans-serif";
              context.fillText(b.label, x1 + 3, top - 3 > 8 ? top - 3 : top + 10);
            }
          }
          context.setLineDash([]);
          for (const m of self.markers) {
            const x = chart.timeScale().timeToCoordinate(m.time as Time);
            const y = series.priceToCoordinate(m.price);
            if (x === null || y === null) continue;
            context.fillStyle = m.color;
            context.beginPath();
            const d = m.up ? -1 : 1;
            context.moveTo(x, y + d * 2);
            context.lineTo(x - 4, y + d * 9);
            context.lineTo(x + 4, y + d * 9);
            context.closePath();
            context.fill();
            context.font = "9px Inter, system-ui, sans-serif";
            context.fillText(m.label, x + 5, y + d * 10);
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

  set(boxes: BoundedBox[], markers: BoxMarker[] = []) {
    this.boxes = boxes;
    this.markers = markers;
    this.requestUpdate?.();
  }
}
