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

export { fmt, sgn, pnc, tzLabel, fmtTime, ts, chanceLabel } from "./format";
