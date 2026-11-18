// CHARTS 1:1 – warstwa danych (D1). Czyste adaptery odpowiedzi API → model widoku = struktury czytane przez kod wzorca (D1 §3),
// ten sam kształt co fixtures testu 1:1. Brak pola w API = stan pusty (null / []), nigdy wartość zgadywana. Tylko GET.
// Ten plik nie importuje Reacta w adapterach – testy w Node: tests/js/charts_adapters.test.mjs.
import { useEffect, useRef, type MutableRefObject } from "react";
import { apiGet } from "../../../../api";
import { chartStatus } from "./chartsAdapters";
export * from "./chartsAdapters";

/** Hook danych (K1: interwały z rejestru, kwotowania i status ze store; świece i warstwy bota – K2–K5). Polling ≥ 5 s, tylko GET. */
export function useChartsData(api: MutableRefObject<any>, active: boolean, s: any) {
  const tfDone = useRef(false);
  useEffect(() => {
    if (!active || tfDone.current) return;
    apiGet<any>("/api/v1/timeframes").then((r) => { tfDone.current = true; api.current?.setTimeframes(r?.timeframes || []); }).catch(() => undefined);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!active) return;
    api.current?.setSymbol("XAUUSD", s?.symbol?.symbol);
    const n = (x: unknown) => (x == null || !Number.isFinite(Number(x)) ? null : Number(x));
    api.current?.setQuote(s?.quote ? { bid: n(s.quote.bid), ask: n(s.quote.ask), spread: n(s.quote.spread) } : null);
    api.current?.setStatus(chartStatus(s));
  }, [active, s?.quote, s?.connection?.state, s?.dq?.status, s?.symbol?.symbol]); // eslint-disable-line react-hooks/exhaustive-deps
}
