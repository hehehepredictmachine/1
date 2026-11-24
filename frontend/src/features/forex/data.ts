// Wspólne helpery danych ekranów FOREX 1.42 (S3): polling GET (min. 5 s), formatowanie pl-PL, etykiety szansy / score.
// Komponenty widoku nie wołają fetch bezpośrednio – tylko przez usePoll / apiGet.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";

export type Poll<T> = { data: T | null; err: string | null; at: number | null; reload: () => void };

export function usePoll<T = any>(path: string | null, everyMs = 10000): Poll<T> {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null);
  // 1.46: one shared alive flag was set back to true by the next effect run, so a late answer of the PREVIOUS path (PAPER -> AUTO_LIVE,
  // XAUUSD -> BTC) overwrote the data of the current one; now every effect run has its own generation and only the current path is accepted
  const live = useRef<{ gen: number; path: string | null }>({ gen: 0, path });
  const load = () => {
    if (!path || live.current.path !== path) return;
    const gen = live.current.gen;
    const cur = () => live.current.gen === gen && live.current.path === path;
    apiGet<T>(path).then((x) => { if (cur()) { setData(x); setErr(null); setAt(Date.now()); } })
      .catch((e) => { if (cur()) setErr(String(e?.message || e).slice(0, 300)); });
  };
  useEffect(() => {
    live.current = { gen: live.current.gen + 1, path };
    setData(null);
    setErr(null);                                    // 1.46: the error of the previous path is not shown for the new one
    load();
    const t = path ? setInterval(load, Math.max(5000, everyMs)) : undefined;
    return () => { live.current = { gen: live.current.gen + 1, path: null }; if (t) clearInterval(t); };
  }, [path, everyMs]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, err, at, reload: load };
}

export { fmt, sgn, pnc, tzLabel, fmtTime, ts, chanceLabel } from "./format";
