// Czyste helpery formatowania / etykiet ekranów FOREX 1.42 (bez React i bez API – testowane w Node: tests/js/forex_format.test.mjs).
const nf = (d: number) => new Intl.NumberFormat("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d });
export function fmt(v: number | null | undefined, d = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return nf(d).format(v).replace("-", "−");
}
export function sgn(v: number | null | undefined, d = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return (v > 0 ? "+" : "") + fmt(v, d);
}
export const pnc = (v: number | null | undefined) => (v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
export function tzLabel(): string {
  const o = -new Date().getTimezoneOffset() / 60;
  return "UTC" + (o >= 0 ? "+" : "") + o;
}
export function fmtTime(t: string | number | null | undefined, withDate = false): string {
  if (t == null) return "—";
  const d = typeof t === "number" ? new Date(t > 1e12 ? t : t * 1000) : new Date(t);
  if (isNaN(d.getTime())) return "—";
  const hm = d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  return (withDate ? d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" }) + " " : "") + hm;
}
export function ts(t: string | number | null | undefined): number {
  if (t == null) return 0;
  if (typeof t === "number") return t > 1e12 ? t : t * 1000;
  const v = Date.parse(t);
  return isNaN(v) ? 0 : v;
}

/** Szansa % tylko z prawdopodobieństwa skalibrowanego modelu (S3 §0); inaczej opis (score / niekalibrowany / brak). */
export function chanceLabel(p: any): { pct: number | null; label: string } {
  if (!p) return { pct: null, label: "brak modelu" };
  const cal = p.calibration?.status;
  const v = p.result?.probability ?? p.result?.p ?? p.result?.p_event_raw ?? null;
  if (p.unit === "probability" && (cal === "CALIBRATED_DEV" || cal === "CALIBRATED") && typeof v === "number") return { pct: v, label: "prawdopodobieństwo (skalibrowane)" };
  if (p.unit === "probability") return { pct: null, label: "niekalibrowany – score" };
  return { pct: null, label: p.unit ? `${p.unit} – nie szansa` : "score" };
}
