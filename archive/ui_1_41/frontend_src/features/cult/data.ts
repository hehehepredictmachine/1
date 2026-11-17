// Data layer of the CULT panels: every value comes from the existing API / the single WebSocket store, and every value carries its
// KIND, so the panels can tell real data from demo, missing, stale and sync-error data (§12 of the brief):
//   REAL  - account confirmed REAL by the terminal          DEMO  - MT5 demo / contest account
//   SIM   - terminal simulator (synthetic data, shown as DEMO) NONE - not available (no data / not computed / no such module)
//   STALE - last value older than its refresh window         ERROR - the request failed (sync error)
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";
import { useStore } from "../../store";
import { useTerminalContext } from "../shell/useTerminalContext";

export type Kind = "REAL" | "DEMO" | "SIM" | "NONE" | "STALE" | "ERROR";
export const KIND_LABEL: Record<Kind, string> = {
  REAL: "REAL", DEMO: "DEMO", SIM: "DEMO · symulator", NONE: "brak danych", STALE: "nieaktualne", ERROR: "błąd synchronizacji",
};

/** Kind of account-derived data (balance, P/L, win rate, positions) for the current terminal. */
export function useEnvKind(): Kind {
  const ctx = useTerminalContext();
  if (ctx.backend !== "OPEN") return "STALE";
  return ctx.env === "LIVE" ? "REAL" : ctx.env === "DEMO" ? "DEMO" : ctx.env === "SYNTHETIC" ? "SIM" : "NONE";
}

export type Got<T> = { d: T | null; err: string | null; at: number | null; load: () => void; stale: boolean };

/** GET with polling; `stale` when the last good answer is older than 2.5 x the interval (or the request keeps failing). */
export function useGet<T = any>(path: string | null, every = 0): Got<T> {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const [, tick] = useState(0);
  const alive = useRef(true);
  const load = () => {
    if (!path) return;
    apiGet<T>(path).then((x) => { if (alive.current) { setD(x); setErr(null); setAt(Date.now()); } })
      .catch((e: any) => { if (alive.current) setErr(String(e?.message || e)); });
  };
  useEffect(() => {
    alive.current = true;
    load();
    const t = every ? setInterval(load, every) : 0;
    const s = every ? setInterval(() => tick((n) => n + 1), Math.max(2000, every / 2)) : 0;
    return () => { alive.current = false; if (t) clearInterval(t); if (s) clearInterval(s); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, every]);
  const stale = !!every && at != null && Date.now() - at > every * 2.5;
  return { d, err, at, load, stale };
}

/** Kind of a polled value: request error > stale > missing > the environment kind. */
export function kindOf(g: { d: any; err: string | null; stale?: boolean }, env: Kind, present = true): Kind {
  if (g.err && !g.d) return "ERROR";
  if (g.stale || (g.err && g.d)) return "STALE";
  if (!g.d || !present) return "NONE";
  return env;
}

/** Round trip of the local API (ms), measured by the panel every 10 s - shown as LATENCY. */
export function useLatency(): number | null {
  const [ms, setMs] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    const ping = async () => {
      const t0 = performance.now();
      try {
        await fetch("/api/v1/health", { cache: "no-store" });
        if (alive) setMs(Math.round(performance.now() - t0));
      } catch {
        if (alive) setMs(null);
      }
    };
    ping();
    const t = setInterval(ping, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return ms;
}

export const pct = (v: any, d = 1) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v).toFixed(d).replace(".", ",")} %`);
export const num = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? "—"
  : Number(v).toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d }));
export const signed = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? "—" : (Number(v) > 0 ? "+" : "") + num(v, d));
export const money = (v: any, cur?: string | null) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${num(v, 2)}${cur ? " " + cur : ""}`);
export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(s)) return "—";
  return s < 60 ? `${Math.max(0, Math.round(s))} s temu` : s < 3600 ? `${Math.round(s / 60)} min temu` : `${Math.round(s / 3600)} h temu`;
}
export const hhmm = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" }) : "—");

/** System status of the left panel: ONLINE only when the backend link is open, MT5 connected and the engine without error. */
export function useSystemStatus(): { state: "ONLINE" | "DEGRADED" | "OFFLINE"; detail: string } {
  const { s } = useStore();
  const ctx = useTerminalContext();
  if (ctx.backend !== "OPEN") return { state: "OFFLINE", detail: "brak połączenia z silnikiem bota" };
  if (ctx.mt5 !== "CONNECTED") return { state: "DEGRADED", detail: `MT5: ${ctx.mt5State ?? "brak statusu"}` };
  if (s.engine?.last_error) return { state: "DEGRADED", detail: "błąd silnika" };
  return { state: "ONLINE", detail: ctx.freshnessDetail };
}

/** Models of the catalog grouped like the approved panels (XGBoost / Random Forest / ML-NN / Monte Carlo) - REAL catalog ids only. */
export const MODEL_FAMILIES: { key: "xgb" | "rf" | "nn" | "mc"; label: string; ids: string[]; none?: string }[] = [
  { key: "xgb", label: "XGBoost", ids: ["legacy_ml", "ml_scalp", "th_xgb"] },
  { key: "rf", label: "Random Forest", ids: [], none: "bot nie ma modelu Random Forest (najbliższe: drzewo decyzyjne w legacy ML, HGB w Centrum treningu)" },
  { key: "nn", label: "ML Engine (NN)", ids: ["nss", "lab", "si_move", "scalp_A", "mm_event_engine"] },
  { key: "mc", label: "Monte Carlo", ids: ["monte_carlo"] },
];

export function familyState(cat: any, ids: string[]): { ready: number; total: number; items: any[]; state: string } {
  const items = (cat?.items || []).filter((x: any) => ids.includes(x.id));
  const ready = items.filter((x: any) => x.state === "READY").length;
  const state = !items.length ? "BRAK" : ready ? "READY" : items.some((x: any) => x.state === "TRAINING") ? "TRAINING" : items[0].state;
  return { ready, total: items.length, items, state };
}
