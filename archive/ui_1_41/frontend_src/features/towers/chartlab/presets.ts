// WTC PEPE 2.1 Chart Lab presets: versioned schema, strict validation (an invalid / foreign JSON never reaches the chart), local storage
// with several named presets, JSON import / export, reset to the default.
import type { Session } from "./calc";

export const LAB_SCHEMA = "PMW-CHARTLAB-1";
export type ChartType = "CANDLES" | "HOLLOW" | "HEIKIN_ASHI" | "LINE" | "AREA";
export type Theme = "NEON" | "DARK" | "CLASSIC" | "LIGHT";
export type IndKey = "ema1" | "ema2" | "vwap" | "bb" | "rsi" | "macd" | "atr" | "svp" | "smc";
export type Ind = { on: boolean; period: number; color: string; width: number };
export type LabCfg = {
  schema: typeof LAB_SCHEMA; theme: Theme; type: ChartType; up: string; down: string; grid: boolean; lineWidth: number;
  ind: Record<IndKey, Ind>; svp: { session: Session; bins: number; va: number; impulse: 3 | 5 | 8 | 12; showImpulse: boolean };
};
export const CHART_TYPES: [ChartType, string][] = [["CANDLES", "Candles"], ["HOLLOW", "Hollow"], ["HEIKIN_ASHI", "Heikin Ashi"], ["LINE", "Line"], ["AREA", "Area"]];
export const THEMES: Record<Theme, { label: string; bg: string; text: string; grid: string }> = {
  NEON: { label: "Neon Pepe", bg: "#040b10", text: "#b8f5d8", grid: "rgba(57,255,143,.07)" },
  DARK: { label: "Dark", bg: "#0d1117", text: "#c9d1d9", grid: "rgba(139,148,158,.12)" },
  CLASSIC: { label: "Classic", bg: "#131722", text: "#d1d4dc", grid: "rgba(42,46,57,.9)" },
  LIGHT: { label: "Light", bg: "#ffffff", text: "#131722", grid: "rgba(42,46,57,.08)" },
};
export const IND_META: Record<IndKey, { label: string; pane: "price" | "osc"; hasPeriod: boolean; min: number; max: number }> = {
  ema1: { label: "EMA (szybka)", pane: "price", hasPeriod: true, min: 2, max: 400 }, ema2: { label: "EMA (wolna)", pane: "price", hasPeriod: true, min: 2, max: 400 },
  vwap: { label: "VWAP (dzienny, UTC)", pane: "price", hasPeriod: false, min: 0, max: 0 }, bb: { label: "Bollinger Bands (2σ)", pane: "price", hasPeriod: true, min: 5, max: 200 },
  rsi: { label: "RSI", pane: "osc", hasPeriod: true, min: 2, max: 100 }, macd: { label: "MACD (12/26/9)", pane: "osc", hasPeriod: false, min: 0, max: 0 },
  atr: { label: "ATR", pane: "osc", hasPeriod: true, min: 2, max: 100 }, svp: { label: "Session Volume Profile", pane: "price", hasPeriod: false, min: 0, max: 0 },
  smc: { label: "SMC – swingi, BOS / CHoCH", pane: "price", hasPeriod: true, min: 1, max: 6 },
};
export const DEFAULT_LAB: LabCfg = {
  schema: LAB_SCHEMA, theme: "NEON", type: "CANDLES", up: "#39ff8f", down: "#ff5d6c", grid: true, lineWidth: 2,
  ind: {
    ema1: { on: true, period: 21, color: "#5fe3ff", width: 2 }, ema2: { on: true, period: 50, color: "#b46bff", width: 2 },
    vwap: { on: false, period: 0, color: "#ffcf5c", width: 2 }, bb: { on: false, period: 20, color: "#8aa4ff", width: 1 },
    rsi: { on: true, period: 14, color: "#c18cff", width: 2 }, macd: { on: false, period: 0, color: "#5fe3ff", width: 2 },
    atr: { on: false, period: 14, color: "#ffb35c", width: 2 }, svp: { on: true, period: 0, color: "#39ff8f", width: 1 },
    smc: { on: false, period: 2, color: "#ff8fd8", width: 1 },
  },
  svp: { session: "ALL", bins: 48, va: 0.7, impulse: 5, showImpulse: true },
};
const HEX = /^#[0-9a-fA-F]{6}$/;
const clampN = (v: any, a: number, b: number, d: number) => (Number.isFinite(Number(v)) ? Math.min(b, Math.max(a, Math.round(Number(v)))) : d);

/** Validates / normalises any object into a LabCfg; throws on a foreign schema. */
export function sanitizeLab(raw: any): LabCfg {
  if (!raw || typeof raw !== "object" || raw.schema !== LAB_SCHEMA) throw new Error(`To nie jest preset Chart Lab (${LAB_SCHEMA})`);
  const d = DEFAULT_LAB;
  const ind = {} as Record<IndKey, Ind>;
  for (const k of Object.keys(d.ind) as IndKey[]) {
    const x = raw.ind?.[k] || {}, m = IND_META[k], dd = d.ind[k];
    ind[k] = { on: typeof x.on === "boolean" ? x.on : dd.on, period: m.hasPeriod ? clampN(x.period, m.min, m.max, dd.period) : dd.period,
      color: HEX.test(x.color) ? x.color : dd.color, width: clampN(x.width, 1, 4, dd.width) };
  }
  return {
    schema: LAB_SCHEMA, theme: raw.theme in THEMES ? raw.theme : d.theme, type: CHART_TYPES.some(([t]) => t === raw.type) ? raw.type : d.type,
    up: HEX.test(raw.up) ? raw.up : d.up, down: HEX.test(raw.down) ? raw.down : d.down, grid: typeof raw.grid === "boolean" ? raw.grid : d.grid,
    lineWidth: clampN(raw.lineWidth, 1, 4, d.lineWidth), ind,
    svp: { session: ["ALL", "ASIA", "LONDON", "NEWYORK"].includes(raw.svp?.session) ? raw.svp.session : d.svp.session,
      bins: clampN(raw.svp?.bins, 12, 120, d.svp.bins), va: Math.min(0.9, Math.max(0.5, Number(raw.svp?.va) || d.svp.va)),
      impulse: [3, 5, 8, 12].includes(Number(raw.svp?.impulse)) ? Number(raw.svp.impulse) as 3 | 5 | 8 | 12 : d.svp.impulse,
      showImpulse: typeof raw.svp?.showImpulse === "boolean" ? raw.svp.showImpulse : d.svp.showImpulse },
  };
}

const CUR = "mq.wtc.chartlab.current";
const LIST = "mq.wtc.chartlab.presets";
export function loadCurrent(): LabCfg {
  try { const r = localStorage.getItem(CUR); return r ? sanitizeLab(JSON.parse(r)) : structuredClone(DEFAULT_LAB); } catch { return structuredClone(DEFAULT_LAB); }
}
export function saveCurrent(c: LabCfg) { try { localStorage.setItem(CUR, JSON.stringify(c)); } catch { /* storage unavailable */ } }
export function loadPresets(): Record<string, LabCfg> {
  try {
    const r = JSON.parse(localStorage.getItem(LIST) || "{}"); const out: Record<string, LabCfg> = {};
    for (const [k, v] of Object.entries(r || {})) { try { out[String(k).slice(0, 40)] = sanitizeLab(v); } catch { /* skip a broken preset */ } }
    return out;
  } catch { return {}; }
}
export function savePresets(p: Record<string, LabCfg>) { try { localStorage.setItem(LIST, JSON.stringify(p)); } catch { /* storage unavailable */ } }
