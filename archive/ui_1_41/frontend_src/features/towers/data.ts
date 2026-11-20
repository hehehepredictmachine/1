// Data helpers of the tower interiors PEPE$WTC / PEPE$SIGNAL. Everything comes from the existing API of the bot; this file only merges
// and normalises it. Nothing is invented: a missing value stays null and the UI shows N/A / UNAVAILABLE with the reason.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";

export const TFS = ["M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1"];

/** GET with polling that keeps the last good answer, drops answers of an older request (path changed) and pauses when the tab is hidden. */
export function usePolled<T = any>(path: string | null, every = 0): { d: T | null; err: string | null; at: number | null; reload: () => void; stale: boolean } {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const seq = useRef(0);
  const cur = useRef(path);
  cur.current = path;
  const load = () => {
    if (!path) return;
    const my = ++seq.current;
    apiGet<T>(path).then((x) => { if (my === seq.current && cur.current === path) { setD(x); setErr(null); setAt(Date.now()); } })
      .catch((e: any) => { if (my === seq.current) setErr(String(e?.message || e)); });
  };
  useEffect(() => {
    setD(null); setErr(null); setAt(null);
    load();
    if (!every) return;
    const t = setInterval(() => { if (!document.hidden) load(); }, every);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, every]);
  return { d, err, at, reload: load, stale: !!every && at != null && Date.now() - at > every * 2.5 };
}

export const fmt = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? "N/A"
  : Number(v).toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d }));
export const fmtSigned = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? "N/A" : (Number(v) > 0 ? "+" : "") + fmt(v, d));
export const hms = (iso?: string | number | null) => {
  if (iso == null) return "—";
  const t = typeof iso === "number" ? iso * (iso < 1e12 ? 1000 : 1) : Date.parse(iso);
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
};
export const dt = (iso?: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
};

/** R:R with the correct denominator: |TP - entry| / |entry - SL|; null when a level is missing or the risk is zero / on the wrong side. */
export function rr(dir: string | null | undefined, entry: number | null | undefined, sl: number | null | undefined, tp: number | null | undefined): number | null {
  if (entry == null || sl == null || tp == null || !dir) return null;
  const long = dir === "BUY" || dir === "LONG";
  const risk = long ? entry - sl : sl - entry;
  const reward = long ? tp - entry : entry - tp;
  if (!(risk > 0) || !(reward > 0)) return null;
  return reward / risk;
}

/** MTF direction of one TF from the engine's own overview (closed candles) – UP / DOWN / FLAT / null (no data). */
export function mtfRows(s: any): { tf: string; direction: string | null; data: string; role: string | null; conflict: boolean; last: string | null }[] {
  const ov: any[] = s.decision?.tf_overview || [];
  return TFS.map((tf) => {
    const o = ov.find((x) => x.tf === tf);
    return { tf, direction: o?.direction ?? null, data: o?.data ?? "BRAK", role: o?.role ?? null, conflict: !!o?.conflict, last: o?.last_closed_utc ?? null };
  });
}

/** Model predictions of the bot (PMW-PRED-2 contract) for the instrument, normalised to the tower rows. */
export type ModelRow = {
  key: string; name: string; version: string | null; tf: string | null; state: string; statePl: string; bias: "BUY" | "SELL" | "NEUTRAL" | null;
  score: number | null; scoreKind: string; calibrated: boolean; at: number | null; reason: string | null; role: string | null; task: string | null;
};
const STATE_UI: Record<string, string> = { READY: "READY", RUNNING: "INFERENCING", INFERENCING: "INFERENCING", ERROR: "ERROR", DISABLED: "OFF", NOT_TRAINED: "OFF",
  BLOCKED_DATA: "STALE", STALE: "STALE", NOT_INSTALLED: "OFF", INCOMPATIBLE: "ERROR", TRAINING: "OFF" };

export function biasOf(r: any): "BUY" | "SELL" | "NEUTRAL" | null {
  const v = r?.direction ?? r?.bias ?? r?.side ?? r?.label ?? r?.class ?? null;
  if (typeof v === "string") {
    const u = v.toUpperCase();
    if (["UP", "BUY", "LONG", "BULLISH"].includes(u)) return "BUY";
    if (["DOWN", "SELL", "SHORT", "BEARISH"].includes(u)) return "SELL";
    if (["FLAT", "NEUTRAL", "HOLD", "NONE", "WAIT"].includes(u)) return "NEUTRAL";
  }
  if (typeof r?.delta_price === "number") return r.delta_price > 0 ? "BUY" : r.delta_price < 0 ? "SELL" : "NEUTRAL";
  return null;
}

export function modelRows(items: any[]): ModelRow[] {
  return (items || []).map((p) => {
    const r = p.result && typeof p.result === "object" ? p.result : null;
    const prob = typeof r?.probability === "number" ? r.probability : typeof r?.p === "number" ? r.p : typeof r?.p_up === "number" ? r.p_up : null;
    const cal = p.calibration?.status === "CALIBRATED" || p.calibration?.status === "OK";
    const score = typeof r?.score === "number" ? r.score : prob != null ? prob * 100 : null;
    return {
      key: p.model_key || p.canonical_id || `${p.model_name}:${p.task}:${p.timeframe}`, name: p.model_name || p.family || "model", version: p.model_version ?? p.run_id ?? null,
      tf: p.timeframe ?? p.horizon?.timeframe ?? null, state: STATE_UI[p.state] ?? p.state ?? "OFF", statePl: p.state_pl ?? p.state ?? "—",
      bias: r ? biasOf(r) : null, score: score != null && Number.isFinite(score) ? score : null,
      scoreKind: prob != null ? (cal ? "P (skalibrowane)" : "wynik modelu (nieskalibrowany – nie P)") : typeof r?.score === "number" ? "score modelu" : "—",
      calibrated: cal, at: p.computed_at ?? null, reason: p.unavailable_reason ?? p.eligibility?.reason ?? null, role: p.role ?? p.use ?? null, task: p.task ?? null,
    };
  });
}

/** Consensus over READY models with a direction: agreeing / active, conflict flag. Equal weights (no weights are configured in the bot). */
export function consensus(rows: ModelRow[]): { dir: "BUY" | "SELL" | "NEUTRAL" | null; agree: number; active: number; conflict: boolean } {
  const act = rows.filter((r) => r.state === "READY" && r.bias);
  if (!act.length) return { dir: null, agree: 0, active: 0, conflict: false };
  const buy = act.filter((r) => r.bias === "BUY").length, sell = act.filter((r) => r.bias === "SELL").length;
  const dir = buy > sell ? "BUY" : sell > buy ? "SELL" : "NEUTRAL";
  return { dir, agree: dir === "BUY" ? buy : dir === "SELL" ? sell : act.length - buy - sell, active: act.length, conflict: buy > 0 && sell > 0 };
}
