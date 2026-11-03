// 1.29: per-chart appearance settings (§3 of the update package). Each chart keeps its own set, keyed like the view state:
// chart id + symbol + timeframe (two charts, two instruments or two TFs never share settings). Stored locally (localStorage of the
// app window - kept across restarts of the desktop app), versioned, validated on read; corrupted storage falls back to defaults.
// Templates are named copies of a settings set the user can apply to any chart. Pure presentation: nothing here reaches the engine.
import type { TimeZoneMode } from "./util";

export type LayerId = "FVG" | "OB" | "SD" | "SR" | "LIQ";
export const LAYERS: [LayerId, string, string][] = [
  ["FVG", "FVG", "luki wartości godziwej (Fair Value Gap)"],
  ["OB", "OB", "bloki zleceń – obszary wyznaczone z OHLC, nie zmierzone zlecenia"],
  ["SD", "Popyt / podaż", "strefy popytu i podaży"],
  ["SR", "Wsparcie / opór", "strefy wsparcia i oporu ze swingów"],
  ["LIQ", "Płynność (hipoteza)", "EQH / EQL – równe szczyty/dołki z OHLC; hipoteza płynności, nie zmierzona płynność"],
];

export type ZoneStyle = { up: string; down: string; opacity: number };
export type ChartPrefs = {
  v: 1;
  upColor: string | null;          // null = colour of the active theme
  downColor: string | null;
  wickUp: string | null;
  wickDown: string | null;
  background: string | null;
  gridColor: string | null;
  textColor: string | null;
  fontSize: number;                // 9..16 px
  showGrid: boolean;
  showVolume: boolean;
  tz: "PAGE" | TimeZoneMode;       // PAGE = the page's time-zone choice
  layers: Record<LayerId, boolean>;
  labels: boolean;                 // zone labels
  zones: Record<LayerId, ZoneStyle>;
  marketZones: boolean;            // market zones (M1/M5/M15/M30) on this chart
};

export const DEFAULT_ZONES: Record<LayerId, ZoneStyle> = {
  FVG: { up: "#2bff88", down: "#ff4d5e", opacity: 0.13 },
  OB: { up: "#4da3ff", down: "#ff9f43", opacity: 0.13 },
  SD: { up: "#36d399", down: "#f87272", opacity: 0.12 },
  SR: { up: "#9be7c4", down: "#ffb3ba", opacity: 0.10 },
  LIQ: { up: "#ffcc4d", down: "#ffcc4d", opacity: 0.10 },
};

export const DEFAULT_PREFS: ChartPrefs = {
  v: 1, upColor: null, downColor: null, wickUp: null, wickDown: null, background: null, gridColor: null, textColor: null,
  fontSize: 10, showGrid: true, showVolume: true, tz: "PAGE",
  layers: { FVG: true, OB: true, SD: true, SR: true, LIQ: true }, labels: true, zones: DEFAULT_ZONES, marketZones: true,
};

const KEY = "mq.chartprefs.v1";
const TPL = "mq.charttemplates.v1";
const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
const TZS = ["PAGE", "LOCAL", "UTC", "SERVER"];

const col = (x: unknown): string | null => (typeof x === "string" && HEX.test(x) ? x : null);
const bool = (x: unknown, d: boolean) => (typeof x === "boolean" ? x : d);
const num = (x: unknown, lo: number, hi: number, d: number) => (typeof x === "number" && isFinite(x) ? Math.min(hi, Math.max(lo, x)) : d);

/** Validated copy: unknown keys dropped, bad values replaced by defaults (a hand-edited or corrupted entry never breaks a chart). */
export function sanitize(raw: any): ChartPrefs {
  const r = raw && typeof raw === "object" ? raw : {};
  const layers = { ...DEFAULT_PREFS.layers };
  const zones = { ...DEFAULT_ZONES };
  for (const [id] of LAYERS) {
    layers[id] = bool(r.layers?.[id], true);
    const z = r.zones?.[id] || {};
    zones[id] = { up: col(z.up) ?? DEFAULT_ZONES[id].up, down: col(z.down) ?? DEFAULT_ZONES[id].down, opacity: num(z.opacity, 0.02, 0.6, DEFAULT_ZONES[id].opacity) };
  }
  return {
    v: 1, upColor: col(r.upColor), downColor: col(r.downColor), wickUp: col(r.wickUp), wickDown: col(r.wickDown), background: col(r.background),
    gridColor: col(r.gridColor), textColor: col(r.textColor), fontSize: Math.round(num(r.fontSize, 9, 16, 10)),
    showGrid: bool(r.showGrid, true), showVolume: bool(r.showVolume, true), tz: TZS.includes(r.tz) ? r.tz : "PAGE",
    layers, labels: bool(r.labels, true), zones, marketZones: bool(r.marketZones, true),
  };
}

function readAll(key: string): Record<string, any> {
  try {
    const j = JSON.parse(localStorage.getItem(key) || "{}");
    return j && j.version === 1 && j.items && typeof j.items === "object" ? j.items : {};
  } catch {
    return {};
  }
}

function writeAll(key: string, items: Record<string, any>): void {
  try {
    localStorage.setItem(key, JSON.stringify({ version: 1, items }));
  } catch {
    /* storage unavailable: settings live for this session only */
  }
}

export const prefsKey = (chartId: string, symbol: string, tf: string) => `${chartId}|${symbol}|${tf}`;

export function loadPrefs(key: string): ChartPrefs {
  const v = readAll(KEY)[key];
  return v ? sanitize(v) : sanitize({});
}

export function savePrefs(key: string, p: ChartPrefs): void {
  writeAll(KEY, { ...readAll(KEY), [key]: sanitize(p) });
  window.dispatchEvent(new CustomEvent("mq:chartprefs", { detail: key }));
}

export function resetPrefs(key: string): ChartPrefs {
  const all = readAll(KEY);
  delete all[key];
  writeAll(KEY, all);
  window.dispatchEvent(new CustomEvent("mq:chartprefs", { detail: key }));
  return sanitize({});
}

export function listTemplates(): Record<string, ChartPrefs> {
  const out: Record<string, ChartPrefs> = {};
  for (const [k, v] of Object.entries(readAll(TPL))) out[k] = sanitize(v);
  return out;
}

export function saveTemplate(name: string, p: ChartPrefs): void {
  const n = name.trim().slice(0, 40);
  if (!n) return;
  writeAll(TPL, { ...readAll(TPL), [n]: sanitize(p) });
}

export function deleteTemplate(name: string): void {
  const all = readAll(TPL);
  delete all[name];
  writeAll(TPL, all);
}

/** Layer of a market-zone type (zones/market.py) or of an engine overlay. */
export function layerOf(type: string): LayerId | null {
  if (type.startsWith("FVG")) return "FVG";
  if (type.startsWith("OB")) return "OB";
  if (type === "DEMAND" || type === "SUPPLY") return "SD";
  if (type.startsWith("SR_")) return "SR";
  if (type === "EQH" || type === "EQL") return "LIQ";
  return null;
}

/** rgba() of a #rrggbb colour with the given opacity. */
export function rgba(hex: string, a: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex);
  if (!m) return hex;
  return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})`;
}
