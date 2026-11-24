import type {
  IChartApi,
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  Logical,
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

// 1.46: x of a chart time that is not exactly a candle open. timeToCoordinate() hits only exact time points (LWC 5.2.1 timeToIndex(t, false)),
// so live FVG / OB zones (start = observed close time, e.g. 10:05:01.73), M5 session boxes / markers on M15 / H1 and live known_at edges were
// dropped although they lay in the visible range. x is interpolated between the neighbouring candles by time (after the last candle: that
// candle; before the first one: the first candle, or null with beforeFirst = false - a marker has no candle there); null without time points.
function timeX(chart: IChartApi, t: number, beforeFirst = true): number | null {
  const ts = chart.timeScale();
  const x = ts.timeToCoordinate(t as Time);
  if (x !== null) return x as number;
  const i = ts.timeToIndex(t as Time, true);                     // first candle at / after t (the last one when t is after the end)
  if (i === null) return null;
  const xb = ts.logicalToCoordinate(i as unknown as Logical);
  if (xb === null) return null;
  const tb = Number(ts.coordinateToTime(xb));
  if (!(tb > t)) return xb as number;
  if ((i as unknown as number) <= 0) return beforeFirst ? (xb as number) : null;
  const xa = ts.logicalToCoordinate(((i as unknown as number) - 1) as Logical);
  const ta = xa === null ? NaN : Number(ts.coordinateToTime(xa));
  if (xa === null || !Number.isFinite(ta) || !(tb > ta)) return xb as number;
  return (xa as number) + ((xb as number) - (xa as number)) * (t - ta) / (tb - ta);
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
            const x1 = timeX(chart, z.from);                       // 1.46: also between candles (was: dropped unless left of the view)
            if (x1 === null) continue;
            const x = Math.max(0, x1);
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
      return timeX(chart, t);       // 1.46: inside the range but between candles - interpolated (a dead stub returned null and dropped the box)
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
            const x = timeX(chart, m.time, false);                   // 1.46: event bar of another TF (M5 on H1) - interpolated, not dropped
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
