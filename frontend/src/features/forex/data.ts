// Wspólne helpery danych ekranów FOREX 1.42 (S3): polling GET (min. 5 s), formatowanie pl-PL, etykiety szansy / score.
// Komponenty widoku nie wołają fetch bezpośrednio – tylko przez usePoll / apiGet.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";

export type Poll<T> = { data: T | null; err: string | null; at: number | null; reload: () => void };

export function usePoll<T = any>(path: string | null, everyMs = 10000): Poll<T> {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const alive = useRef(true);
  const load = () => {
    if (!path) return;
    apiGet<T>(path).then((x) => { if (alive.current) { setData(x); setErr(null); setAt(Date.now()); } })
      .catch((e) => { if (alive.current) setErr(String(e?.message || e).slice(0, 300)); });
  };
  useEffect(() => {
    alive.current = true;
    setData(null);
    load();
    const t = path ? setInterval(load, Math.max(5000, everyMs)) : undefined;
    return () => { alive.current = false; if (t) clearInterval(t); };
  }, [path, everyMs]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, err, at, reload: load };
}

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
