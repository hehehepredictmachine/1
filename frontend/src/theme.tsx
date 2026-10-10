// Theme system (presentation only - never touches trading mode, account or orders).
//
// * every visible colour is a token: app tokens become CSS variables, chart tokens are applied to
//   Lightweight Charts with applyOptions() (no chart re-creation, zoom/scroll kept);
// * per-chart overrides (chart_id -> partial chart tokens) on top of the global theme;
// * draft = live preview while the "Wygląd" dialog is open; Zastosuj / Anuluj / Przywróć domyślne;
// * versioned persistence in localStorage ("mq.theme.v1") - there are no user profiles in this app;
// * import/export JSON with schema, key and value validation (unknown keys are rejected, so an imported
//   file can never carry settings like execution mode or account).
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Tokens = Record<string, string | number>;
export type TokenDef = { key: string; label: string; group: string; css?: string; kind: "color" | "number"; min?: number; max?: number; step?: number };

const C = (key: string, label: string, group: string, css?: string): TokenDef => ({ key, label, group, css, kind: "color" });
const N = (key: string, label: string, group: string, min: number, max: number, step: number, css?: string): TokenDef =>
  ({ key, label, group, kind: "number", min, max, step, css });

export const GROUPS = ["Tło i panele", "Teksty i liczby", "Ramki i akcenty", "Przyciski", "Statusy", "Wykres", "Świece i wolumen", "Wskaźniki",
  "Poziomy i strefy", "Checklista", "Dekoracje (GIF)"];

export const TOKENS: TokenDef[] = [
  C("bg", "Tło aplikacji", "Tło i panele", "--bg"), C("bgGlow", "Poświata tła", "Tło i panele", "--bg-glow"),
  C("gridLine", "Siatka tła", "Tło i panele", "--grid-line"), C("panel", "Panele", "Tło i panele", "--panel"),
  C("card", "Karty (BALANCE…)", "Tło i panele", "--card"), C("header", "Nagłówek", "Tło i panele", "--header-bg"),
  C("modal", "Okna dialogowe", "Tło i panele", "--modal-bg"), C("input", "Pola edycji", "Tło i panele", "--input-bg"),
  C("tableHead", "Nagłówki tabel", "Tło i panele", "--table-head"),
  C("text", "Tekst", "Teksty i liczby", "--text"), C("textStrong", "Tekst wyróżniony", "Teksty i liczby", "--text-strong"),
  C("textDim", "Tekst pomocniczy", "Teksty i liczby", "--text-dim"), C("muted", "Etykiety", "Teksty i liczby", "--muted"),
  C("muted2", "Przypisy", "Teksty i liczby", "--muted2"), C("number", "Liczby", "Teksty i liczby", "--number"),
  C("icon", "Ikony", "Teksty i liczby", "--icon"),
  C("line", "Ramki", "Ramki i akcenty", "--line"), C("line2", "Ramki aktywne", "Ramki i akcenty", "--line2"),
  C("accent", "Akcent", "Ramki i akcenty", "--neon"), C("accent2", "Akcent 2", "Ramki i akcenty", "--neon2"),
  C("accentInk", "Tekst na akcencie", "Ramki i akcenty", "--accent-ink"), C("info", "Informacja", "Ramki i akcenty", "--info"),
  C("btnBg", "Przycisk", "Przyciski", "--btn-bg"), C("btnHover", "Przycisk – najechanie", "Przyciski", "--btn-hover"),
  C("btnActive", "Przycisk – wciśnięty", "Przyciski", "--btn-active"), C("btnText", "Tekst przycisku", "Przyciski", "--btn-text"),
  C("btnDisabledBg", "Przycisk nieaktywny", "Przyciski", "--btn-disabled-bg"), C("btnDisabledText", "Tekst nieaktywny", "Przyciski", "--btn-disabled-text"),
  C("bad", "Błąd", "Statusy", "--bad"), C("warn", "Ostrzeżenie", "Statusy", "--warn"), C("badText", "Tekst błędu", "Statusy", "--bad-text"),
  C("warnText", "Tekst ostrzeżenia", "Statusy", "--warn-text"), C("badLine", "Ramka błędu", "Statusy", "--bad-line"),
  C("warnLine", "Ramka ostrzeżenia", "Statusy", "--warn-line"), C("pnlPos", "Zysk (PnL +)", "Statusy", "--pnl-pos"),
  C("pnlNeg", "Strata (PnL −)", "Statusy", "--pnl-neg"), C("connOk", "Połączenie OK", "Statusy", "--conn-ok"),
  C("connWarn", "Połączenie – uwaga", "Statusy", "--conn-warn"), C("connBad", "Brak połączenia", "Statusy", "--conn-bad"),
  C("chartBg", "Tło wykresu", "Wykres"), C("chartGrid", "Siatka wykresu", "Wykres"), C("chartAxis", "Osie (linie)", "Wykres"),
  C("chartLabels", "Opisy osi", "Wykres"), C("chartCrosshair", "Celownik", "Wykres"), C("chartSeparator", "Separator paneli", "Wykres"),
  C("upBody", "Świeca wzrostowa – korpus", "Świece i wolumen"), C("downBody", "Świeca spadkowa – korpus", "Świece i wolumen"),
  C("upWick", "Knot wzrostowy", "Świece i wolumen"), C("downWick", "Knot spadkowy", "Świece i wolumen"),
  C("upBorder", "Obrys wzrostowy", "Świece i wolumen"), C("downBorder", "Obrys spadkowy", "Świece i wolumen"),
  C("formingUp", "Świeca w trakcie ↑", "Świece i wolumen"), C("formingDown", "Świeca w trakcie ↓", "Świece i wolumen"),
  C("volUp", "Wolumen ↑", "Świece i wolumen"), C("volDown", "Wolumen ↓", "Świece i wolumen"),
  C("ind1", "Linia wskaźnika 1", "Wskaźniki"), C("ind2", "Linia wskaźnika 2", "Wskaźniki"), C("ind3", "Linia wskaźnika 3", "Wskaźniki"),
  C("ind4", "Linia wskaźnika 4", "Wskaźniki"), C("ind5", "Linia wskaźnika 5", "Wskaźniki"), C("ind6", "Linia wskaźnika 6", "Wskaźniki"),
  C("rsi", "RSI", "Wskaźniki"), C("rsiLevels", "RSI 30/70", "Wskaźniki"), C("macd", "MACD", "Wskaźniki"), C("macdSignal", "MACD sygnał", "Wskaźniki"),
  C("macdUp", "Histogram MACD +", "Wskaźniki"), C("macdDown", "Histogram MACD −", "Wskaźniki"),
  C("entry", "Wejście / strefa", "Poziomy i strefy"), C("sl", "Stop Loss", "Poziomy i strefy"), C("tp", "Take Profit", "Poziomy i strefy"),
  C("bos", "Znacznik BOS", "Poziomy i strefy"), C("choch", "Znacznik CHoCH", "Poziomy i strefy"), C("sweep", "Znacznik sweep", "Poziomy i strefy"),
  C("fvgBull", "FVG wzrostowa", "Poziomy i strefy"), C("fvgBear", "FVG spadkowa", "Poziomy i strefy"), C("ob", "Order block", "Poziomy i strefy"),
  C("ivWallUp", "IV wall ↑ (strefa)", "Poziomy i strefy"), C("ivWallDown", "IV wall ↓ (strefa)", "Poziomy i strefy"),
  C("dailyOpen", "Daily Open", "Poziomy i strefy"), C("expectedHL", "Daily High/Low (IV 1σ)", "Poziomy i strefy"),
  C("straddleBe", "Straddle – próg rentowności", "Poziomy i strefy"), C("pdhl", "PDH / PDL", "Poziomy i strefy"),
  C("dayHL", "High / Low dnia", "Poziomy i strefy"),
  C("checkMet", "Warunek spełniony", "Checklista", "--check-met"), C("checkMissing", "Warunek brakujący", "Checklista", "--check-missing"),
  C("checkNoData", "Brak danych", "Checklista", "--check-nodata"),
  C("overlay", "Kolor przyciemnienia GIF", "Dekoracje (GIF)", "--overlay-color"),
  N("overlayDim", "Przyciemnienie tła GIF", "Dekoracje (GIF)", 0, 0.95, 0.05), N("gifOpacity", "Widoczność tła GIF", "Dekoracje (GIF)", 0, 1, 0.05),
  N("frogOpacity", "Widoczność żaby", "Dekoracje (GIF)", 0, 1, 0.05),
];
export const TOKEN_MAP: Record<string, TokenDef> = Object.fromEntries(TOKENS.map((t) => [t.key, t]));
export const CHART_GROUPS = ["Wykres", "Świece i wolumen", "Wskaźniki", "Poziomy i strefy"];
export const CHART_KEYS = TOKENS.filter((t) => CHART_GROUPS.includes(t.group)).map((t) => t.key);

// ------------------------------------------------------------------------------- presets
const MATRIX: Tokens = {
  bg: "#020805", bgGlow: "#0b3a20", gridLine: "#2bff8809", panel: "#04160deb", card: "#04160deb", header: "#021008ed", modal: "#03120a", input: "#031008",
  tableHead: "#041a0e", text: "#c9f7dc", textStrong: "#eafff2", textDim: "#a9dcc0", muted: "#6fa489", muted2: "#4f8a6b", number: "#b8ffd6", icon: "#9dffc9",
  line: "#0f5a31", line2: "#1d9b57", accent: "#2bff88", accent2: "#16e07a", accentInk: "#02130a", info: "#4dd0ff",
  btnBg: "#2bff8824", btnHover: "#2bff883d", btnActive: "#2bff8857", btnText: "#c9ffe0", btnDisabledBg: "#0a2015", btnDisabledText: "#4d7d63",
  bad: "#ff4d5e", warn: "#ffcc4d", badText: "#ffc1c8", warnText: "#ffe39a", badLine: "#7a1f2a", warnLine: "#6b5a1d", pnlPos: "#16e07a", pnlNeg: "#ff4d5e",
  connOk: "#2bff88", connWarn: "#ffcc4d", connBad: "#ff4d5e",
  chartBg: "#00000000", chartGrid: "#28ff8c10", chartAxis: "#124d2c", chartLabels: "#8fd8ad", chartCrosshair: "#7dffb6aa", chartSeparator: "#0f3d24",
  upBody: "#16e07a", downBody: "#ff4d5e", upWick: "#16e07a", downWick: "#ff4d5e", upBorder: "#16e07a", downBorder: "#ff4d5e",
  formingUp: "#16e07a73", formingDown: "#ff4d5e73", volUp: "#16e07a47", volDown: "#ff4d5e47",
  ind1: "#f5d76e", ind2: "#4dd0ff", ind3: "#c792ea", ind4: "#ff9f43", ind5: "#9cff57", ind6: "#ff6b9a",
  rsi: "#c792ea", rsiLevels: "#3b6b50", macd: "#4dd0ff", macdSignal: "#ff9f43", macdUp: "#16e07a99", macdDown: "#ff4d5e99",
  entry: "#d8ff7a", sl: "#ff4d5e", tp: "#16e07a", bos: "#7dffb6", choch: "#ffcc4d", sweep: "#c792ea", fvgBull: "#16e07a1a", fvgBear: "#ff4d5e1a", ob: "#4dd0ff12",
  ivWallUp: "#ff4d5e22", ivWallDown: "#16e07a22", dailyOpen: "#f5d76e", expectedHL: "#4dd0ff", straddleBe: "#c792ea", pdhl: "#ff9f43", dayHL: "#9aa7b0",
  checkMet: "#2bff88", checkMissing: "#ffcc4d", checkNoData: "#8aa39a", overlay: "#000000", overlayDim: 0.55, gifOpacity: 1, frogOpacity: 1,
};
const DARK: Tokens = {
  ...MATRIX, bg: "#0d1117", bgGlow: "#1c2433", gridLine: "#ffffff06", panel: "#161b22f2", card: "#161b22f2", header: "#0d1117f0", modal: "#161b22", input: "#0d1117",
  tableHead: "#1c2128", text: "#d6dde6", textStrong: "#ffffff", textDim: "#aab4c0", muted: "#8b949e", muted2: "#6e7681", number: "#e6edf3", icon: "#9ecbff",
  line: "#30363d", line2: "#58a6ff", accent: "#58a6ff", accent2: "#3fb950", accentInk: "#0d1117", info: "#79c0ff",
  btnBg: "#21262d", btnHover: "#30363d", btnActive: "#3d444d", btnText: "#e6edf3", btnDisabledBg: "#161b22", btnDisabledText: "#6e7681",
  bad: "#f85149", warn: "#d29922", badText: "#ffa198", warnText: "#e3b341", badLine: "#8e1519", warnLine: "#6b4e00", pnlPos: "#3fb950", pnlNeg: "#f85149",
  connOk: "#3fb950", connWarn: "#d29922", connBad: "#f85149",
  chartGrid: "#ffffff0d", chartAxis: "#30363d", chartLabels: "#aab4c0", chartCrosshair: "#9ecbffaa", chartSeparator: "#30363d",
  upBody: "#3fb950", downBody: "#f85149", upWick: "#3fb950", downWick: "#f85149", upBorder: "#3fb950", downBorder: "#f85149",
  formingUp: "#3fb95073", formingDown: "#f8514973", volUp: "#3fb95047", volDown: "#f8514947", tp: "#3fb950", sl: "#f85149", rsiLevels: "#484f58",
  checkMet: "#3fb950", checkMissing: "#d29922", checkNoData: "#8b949e", bos: "#9ecbff", overlayDim: 0.7,
};
const LIGHT: Tokens = {
  ...DARK, bg: "#f4f6f8", bgGlow: "#ffffff", gridLine: "#0000000a", panel: "#fffffff2", card: "#ffffff", header: "#ffffffee", modal: "#ffffff", input: "#ffffff",
  tableHead: "#eef1f4", text: "#1f2328", textStrong: "#000000", textDim: "#3d444d", muted: "#59636e", muted2: "#6e7781", number: "#0b1f33", icon: "#0550ae",
  line: "#d0d7de", line2: "#0969da", accent: "#0969da", accent2: "#1a7f37", accentInk: "#ffffff", info: "#0550ae",
  btnBg: "#f6f8fa", btnHover: "#eaeef2", btnActive: "#d0d7de", btnText: "#1f2328", btnDisabledBg: "#f6f8fa", btnDisabledText: "#8c959f",
  bad: "#cf222e", warn: "#9a6700", badText: "#a40e26", warnText: "#7d4e00", badLine: "#ff8182", warnLine: "#d4a72c", pnlPos: "#1a7f37", pnlNeg: "#cf222e",
  connOk: "#1a7f37", connWarn: "#9a6700", connBad: "#cf222e",
  chartBg: "#ffffff00", chartGrid: "#0000000d", chartAxis: "#d0d7de", chartLabels: "#3d444d", chartCrosshair: "#0969daaa", chartSeparator: "#d0d7de",
  upBody: "#1a7f37", downBody: "#cf222e", upWick: "#1a7f37", downWick: "#cf222e", upBorder: "#1a7f37", downBorder: "#cf222e",
  formingUp: "#1a7f3773", formingDown: "#cf222e73", volUp: "#1a7f3740", volDown: "#cf222e40", tp: "#1a7f37", sl: "#cf222e", entry: "#8250df",
  ind1: "#bf8700", ind2: "#0969da", ind3: "#8250df", ind4: "#bc4c00", ind5: "#1a7f37", ind6: "#bf3989", rsi: "#8250df", macd: "#0969da",
  checkMet: "#1a7f37", checkMissing: "#9a6700", checkNoData: "#6e7781", bos: "#0550ae", choch: "#9a6700", sweep: "#8250df",
  fvgBull: "#1a7f371a", fvgBear: "#cf222e1a", ob: "#0969da12", overlay: "#ffffff", overlayDim: 0.85,
  ivWallUp: "#cf222e1f", ivWallDown: "#1a7f371f", dailyOpen: "#9a6700", expectedHL: "#0550ae", straddleBe: "#8250df", pdhl: "#bc4c00", dayHL: "#57606a",
};
const CONTRAST: Tokens = {
  ...MATRIX, bg: "#000000", bgGlow: "#000000", gridLine: "#00000000", panel: "#000000", card: "#000000", header: "#000000", modal: "#000000", input: "#000000",
  tableHead: "#000000", text: "#ffffff", textStrong: "#ffffff", textDim: "#ffffff", muted: "#e0e0e0", muted2: "#d0d0d0", number: "#ffffff", icon: "#ffff00",
  line: "#ffffff", line2: "#ffff00", accent: "#ffff00", accent2: "#00ff00", accentInk: "#000000", info: "#00ffff",
  btnBg: "#000000", btnHover: "#333300", btnActive: "#666600", btnText: "#ffffff", btnDisabledBg: "#000000", btnDisabledText: "#a0a0a0",
  bad: "#ff3030", warn: "#ffff00", badText: "#ff8080", warnText: "#ffff80", badLine: "#ff3030", warnLine: "#ffff00", pnlPos: "#00ff00", pnlNeg: "#ff3030",
  connOk: "#00ff00", connWarn: "#ffff00", connBad: "#ff3030",
  chartBg: "#000000", chartGrid: "#ffffff22", chartAxis: "#ffffff", chartLabels: "#ffffff", chartCrosshair: "#ffff00", chartSeparator: "#ffffff",
  upBody: "#00ff00", downBody: "#ff3030", upWick: "#00ff00", downWick: "#ff3030", upBorder: "#00ff00", downBorder: "#ff3030",
  checkMet: "#00ff00", checkMissing: "#ffff00", checkNoData: "#c0c0c0", overlayDim: 0.9,
};
export const PRESETS: Record<string, { label: string; scheme: "dark" | "light"; tokens: Tokens }> = {
  matrix: { label: "Matrix zielony", scheme: "dark", tokens: MATRIX },
  dark: { label: "Ciemny", scheme: "dark", tokens: DARK },
  light: { label: "Jasny", scheme: "light", tokens: LIGHT },
  contrast: { label: "Wysoki kontrast", scheme: "dark", tokens: CONTRAST },
};

// ------------------------------------------------------------------------------- colour maths
export type RGBA = { r: number; g: number; b: number; a: number };
const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

export function parseColor(s: string): RGBA | null {
  if (typeof s !== "string") return null;
  const t = s.trim().toLowerCase();
  let m = t.match(/^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/);
  if (m) {
    let h = m[1];
    if (h.length <= 4) h = h.split("").map((c) => c + c).join("");
    const n = (i: number) => parseInt(h.slice(i, i + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
  }
  m = t.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/);
  if (m) {
    const a = m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
    const v = { r: +m[1], g: +m[2], b: +m[3], a };
    return [v.r, v.g, v.b].every((x) => x >= 0 && x <= 255) && a >= 0 && a <= 1 ? v : null;
  }
  m = t.match(/^hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%(?:[\s,/]+([\d.]+%?))?\s*\)$/);
  if (m) {
    const a = m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
    const { r, g, b } = hslToRgb(+m[1], +m[2] / 100, +m[3] / 100);
    return +m[2] <= 100 && +m[3] <= 100 && a >= 0 && a <= 1 ? { r, g, b, a } : null;
  }
  return null;
}
export function toHex(c: RGBA): string {
  const h = (x: number) => Math.round(clamp(x, 0, 255)).toString(16).padStart(2, "0");
  return "#" + h(c.r) + h(c.g) + h(c.b) + (c.a >= 0.999 ? "" : h(c.a * 255));
}
export function rgbToHsv({ r, g, b }: RGBA) {
  const R = r / 255, G = g / 255, B = b / 255;
  const mx = Math.max(R, G, B), mn = Math.min(R, G, B), d = mx - mn;
  let h = 0;
  if (d) h = mx === R ? ((G - B) / d) % 6 : mx === G ? (B - R) / d + 2 : (R - G) / d + 4;
  return { h: (h * 60 + 360) % 360, s: mx ? d / mx : 0, v: mx };
}
export function hsvToRgb(h: number, s: number, v: number) {
  const c = v * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return { r: (r + m) * 255, g: (g + m) * 255, b: (b + m) * 255 };
}
export function rgbToHsl({ r, g, b }: RGBA) {
  const R = r / 255, G = g / 255, B = b / 255;
  const mx = Math.max(R, G, B), mn = Math.min(R, G, B), l = (mx + mn) / 2, d = mx - mn;
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  const { h } = rgbToHsv({ r, g, b, a: 1 });
  return { h, s, l };
}
export function hslToRgb(h: number, s: number, l: number) {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return { r: Math.round((r + m) * 255), g: Math.round((g + m) * 255), b: Math.round((b + m) * 255) };
}
function over(fg: RGBA, bg: RGBA): RGBA {
  return { r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 };
}
function lum(c: RGBA) {
  const f = (x: number) => { const v = x / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}
export function contrast(fg: string, bgs: string[]): number | null {
  const base = { r: 0, g: 0, b: 0, a: 1 };
  let bg: RGBA = base;
  for (const s of bgs) { const c = parseColor(s); if (!c) return null; bg = over(c, bg); }
  const f = parseColor(fg);
  if (!f) return null;
  const a = lum(over(f, bg)), b = lum(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** WCAG contrast check of the most important pairs (composited over the app background). */
export function contrastWarnings(t: Tokens): string[] {
  const g = (k: string) => String(t[k]);
  const pairs: [string, string, string[], number][] = [
    ["Tekst / panel", g("text"), [g("bg"), g("panel")], 4.5], ["Liczby / panel", g("number"), [g("bg"), g("panel")], 4.5],
    ["Etykiety / panel", g("muted"), [g("bg"), g("panel")], 3], ["Liczby / karta", g("textStrong"), [g("bg"), g("card")], 4.5],
    ["Tekst przycisku / przycisk", g("btnText"), [g("bg"), g("panel"), g("btnBg")], 4.5], ["Tekst na akcencie", g("accentInk"), [g("bg"), g("accent")], 4.5],
    ["Opisy osi / tło wykresu", g("chartLabels"), [g("bg"), g("panel"), g("chartBg")], 4.5], ["Błąd / panel", g("bad"), [g("bg"), g("panel")], 3],
    ["Ostrzeżenie / panel", g("warn"), [g("bg"), g("panel")], 3], ["Warunek spełniony / panel", g("checkMet"), [g("bg"), g("panel")], 3],
    ["Warunek brakujący / panel", g("checkMissing"), [g("bg"), g("panel")], 3], ["Świeca ↑ / tło wykresu", g("upBody"), [g("bg"), g("panel"), g("chartBg")], 3],
    ["Świeca ↓ / tło wykresu", g("downBody"), [g("bg"), g("panel"), g("chartBg")], 3],
  ];
  const out: string[] = [];
  for (const [name, fg, bg, min] of pairs) {
    const c = contrast(fg, bg);
    if (c !== null && c < min) out.push(`${name}: kontrast ${c.toFixed(2)}:1 (zalecane ≥ ${min}:1)`);
  }
  return out;
}

// ------------------------------------------------------------------------------- validation & storage
export const SCHEMA = "masterquo-theme";
export const VERSION = 1;
const KEY = "mq.theme.v1";

export function validateTokens(obj: any, allowed: string[] = TOKENS.map((t) => t.key)): { tokens: Tokens; errors: string[] } {
  const errors: string[] = [];
  const tokens: Tokens = {};
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return { tokens, errors: ["tokens: oczekiwano obiektu"] };
  for (const [k, v] of Object.entries(obj)) {
    const d = TOKEN_MAP[k];
    if (!d || !allowed.includes(k)) { errors.push(`nieznany klucz: ${k}`); continue; }
    if (d.kind === "color") {
      const c = typeof v === "string" ? parseColor(v) : null;
      if (!c) errors.push(`${k}: niepoprawny kolor "${String(v).slice(0, 40)}"`);
      else tokens[k] = toHex(c);
    } else {
      const n = typeof v === "number" ? v : NaN;
      if (!Number.isFinite(n) || n < (d.min ?? -Infinity) || n > (d.max ?? Infinity)) errors.push(`${k}: wartość poza zakresem ${d.min}–${d.max}`);
      else tokens[k] = n;
    }
  }
  return { tokens, errors };
}

export function parseThemeFile(text: string): { name: string; tokens: Tokens; overrides: Record<string, Tokens>; errors: string[] } {
  const res = { name: "", tokens: {} as Tokens, overrides: {} as Record<string, Tokens>, errors: [] as string[] };
  if (text.length > 65536) { res.errors.push("plik za duży (max 64 KB)"); return res; }
  let j: any;
  try { j = JSON.parse(text); } catch { res.errors.push("to nie jest poprawny JSON"); return res; }
  if (!j || typeof j !== "object" || Array.isArray(j)) { res.errors.push("oczekiwano obiektu JSON"); return res; }
  const allowedTop = ["schema", "version", "name", "tokens", "chart_overrides"];
  for (const k of Object.keys(j)) if (!allowedTop.includes(k)) res.errors.push(`niedozwolone pole: ${k} (motyw może zawierać tylko kolory)`);
  if (j.schema !== SCHEMA) res.errors.push(`schema: oczekiwano "${SCHEMA}"`);
  if (j.version !== VERSION) res.errors.push(`version: oczekiwano ${VERSION}`);
  res.name = typeof j.name === "string" ? j.name.replace(/[^\p{L}\p{N} _.-]/gu, "").slice(0, 40) : "Import";
  const v = validateTokens(j.tokens);
  res.tokens = v.tokens;
  res.errors.push(...v.errors);
  if (j.chart_overrides !== undefined) {
    if (typeof j.chart_overrides !== "object" || Array.isArray(j.chart_overrides)) res.errors.push("chart_overrides: oczekiwano obiektu");
    else for (const [cid, ov] of Object.entries(j.chart_overrides)) {
      if (!/^panel[1-8]$/.test(cid)) { res.errors.push(`chart_overrides: nieznany wykres ${cid}`); continue; }
      const r = validateTokens(ov, CHART_KEYS);
      res.overrides[cid] = r.tokens;
      res.errors.push(...r.errors.map((e) => `${cid}.${e}`));
    }
  }
  return res;
}

type Stored = { version: number; preset: string; tokens: Tokens; custom: Record<string, Tokens>; overrides: Record<string, Tokens> };

function load(): Stored {
  const def: Stored = { version: VERSION, preset: "matrix", tokens: { ...MATRIX }, custom: {}, overrides: {} };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return def;
    const j = JSON.parse(raw);
    if (j?.version !== VERSION) return def;                   // future migrations go here
    const t = validateTokens(j.tokens).tokens;
    const custom: Record<string, Tokens> = {};
    for (const [n, v] of Object.entries(j.custom || {})) custom[n] = { ...MATRIX, ...validateTokens(v).tokens };
    const overrides: Record<string, Tokens> = {};
    for (const [n, v] of Object.entries(j.overrides || {})) if (/^panel[1-8]$/.test(n)) overrides[n] = validateTokens(v, CHART_KEYS).tokens;
    return { version: VERSION, preset: typeof j.preset === "string" ? j.preset : "matrix", tokens: { ...MATRIX, ...t }, custom, overrides };
  } catch {
    return def;
  }
}
function save(st: Stored) {
  try { localStorage.setItem(KEY, JSON.stringify(st)); } catch { /* storage unavailable: theme works for this session */ }
}

// ------------------------------------------------------------------------------- context
type Draft = { tokens: Tokens; overrides: Record<string, Tokens>; preset: string };
type Ctx = {
  stored: Stored;
  effective: Tokens;                                 // draft (preview) or saved tokens
  effectiveOverrides: Record<string, Tokens>;
  draft: Draft | null;
  beginEdit: () => void;
  setDraft: (d: Draft) => void;
  apply: () => void;
  cancel: () => void;
  resetDefaults: () => void;
  saveCustom: (name: string) => void;
  deleteCustom: (name: string) => void;
  chartTokens: (chartId: string) => Tokens;
};
const ThemeCtx = createContext<Ctx | null>(null);

function applyCss(t: Tokens, scheme: string) {
  const root = document.documentElement;
  for (const d of TOKENS) if (d.css && t[d.key] !== undefined) root.style.setProperty(d.css, String(t[d.key]));
  root.style.setProperty("color-scheme", scheme);
  root.dataset.theme = scheme;
}

export function schemeOf(t: Tokens): "dark" | "light" {
  const c = parseColor(String(t.bg));
  return c && lum(c) > 0.4 ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [stored, setStored] = useState<Stored>(load);
  const [draft, setDraftS] = useState<Draft | null>(null);
  const effective = draft?.tokens ?? stored.tokens;
  const effectiveOverrides = draft?.overrides ?? stored.overrides;
  useEffect(() => applyCss(effective, schemeOf(effective)), [effective]);
  const value = useMemo<Ctx>(() => ({
    stored, effective, effectiveOverrides, draft,
    beginEdit: () => setDraftS({ tokens: { ...stored.tokens }, overrides: JSON.parse(JSON.stringify(stored.overrides)), preset: stored.preset }),
    setDraft: (d) => setDraftS(d),
    apply: () => {
      if (!draft) return;
      const n = { ...stored, tokens: draft.tokens, overrides: draft.overrides, preset: draft.preset };
      setStored(n);
      save(n);
      setDraftS(null);
    },
    cancel: () => setDraftS(null),
    resetDefaults: () => setDraftS({ tokens: { ...MATRIX }, overrides: {}, preset: "matrix" }),
    saveCustom: (name) => {
      const n = { ...stored, custom: { ...stored.custom, [name]: { ...(draft?.tokens ?? stored.tokens) } } };
      setStored(n);
      save(n);
    },
    deleteCustom: (name) => {
      const c = { ...stored.custom };
      delete c[name];
      const n = { ...stored, custom: c };
      setStored(n);
      save(n);
    },
    chartTokens: (chartId) => ({ ...effective, ...(effectiveOverrides[chartId] || {}) }),
  }), [stored, draft, effective, effectiveOverrides]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Ctx {
  const c = useContext(ThemeCtx);
  if (!c) throw new Error("no theme");
  return c;
}

export function exportTheme(name: string, tokens: Tokens, overrides: Record<string, Tokens>): string {
  return JSON.stringify({ schema: SCHEMA, version: VERSION, name, tokens, chart_overrides: overrides }, null, 1);
}
