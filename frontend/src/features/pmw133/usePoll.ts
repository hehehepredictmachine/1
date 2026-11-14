// Small polling hook for the 1.33 panels: GET a backend endpoint every `ms` (null url = off). Errors are shown, never invented as data.
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";

export function usePoll<T = any>(url: string | null, ms: number): { data: T | null; err: string | null; reload: () => Promise<void> } {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(true);
  const gen = useRef(0);                                     // 1.38: generation token - an answer for an older URL (TF / strategy change) is dropped
  const reload = useCallback(async () => {
    if (!url) return;
    const g = gen.current;
    try {
      const d = await apiGet<T>(url);
      if (alive.current && g === gen.current) { setData(d); setErr(null); }
    } catch (e: any) {
      if (alive.current && g === gen.current) setErr(String(e?.message || e));
    }
  }, [url]);
  useEffect(() => {
    alive.current = true;
    gen.current += 1;
    if (!url) { setData(null); return; }
    void reload();
    const t = setInterval(() => void reload(), ms);
    return () => { alive.current = false; clearInterval(t); };
  }, [url, ms, reload]);
  return { data, err, reload };
}

export const STATUS_PL: Record<string, string> = {
  OK: "OK", READY: "gotowy", WARMUP: "rozgrzewanie", NO_DATA: "brak danych", DISABLED: "wyłączony", STALE: "nieaktualny", ERROR: "błąd",
  NOT_CONFIGURED: "nieskonfigurowany", UNAVAILABLE: "niedostępny", BLOCKED_DATA: "brak wymaganych danych", NOT_TRAINED: "niewytrenowany",
  TRAINING: "trening", INCOMPATIBLE: "niezgodny", INSUFFICIENT: "za mało danych",
};
export const tone = (st?: string | null) => st === "OK" || st === "READY" ? "ok" : st === "ERROR" || st === "INCOMPATIBLE" ? "bad" :
  st === "DISABLED" || st === "NOT_TRAINED" || st == null ? "muted" : "warn";
export const num = (v: any, d = 2) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—");
