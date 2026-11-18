// CHARTS 1:1 – warstwa danych (D1). Czyste adaptery odpowiedzi API → model widoku = struktury czytane przez kod wzorca (D1 §3),
// ten sam kształt co fixtures testu 1:1. Brak pola w API = stan pusty (null / []), nigdy wartość zgadywana. Tylko GET.
// Ten plik nie importuje Reacta w adapterach – testy w Node: tests/js/charts_adapters.test.mjs.
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { apiGet } from "../../../../api";
import { candlesVM, chartStatus, iprofVM, kronosVM } from "./chartsAdapters";
export * from "./chartsAdapters";

/** Hook danych ekranu CHARTS (K2): świece + profil wskaźników silnika, tiki na żywo ze store, Kronos. Tylko GET; ponowne pobranie po
 *  bar_closed wybranego TF, w tle najwyżej co 30 s (D1 §2). Wyniki trafiają do renderera przez api.setVM / liveBar / setKronos. */
export function useChartsData(api: MutableRefObject<any>, active: boolean, s: any) {
  const tfDone = useRef(false);
  const [sel, setSel] = useState<{ asset: string; tf: string; kr: string; n: number }>({ asset: "XAUUSD", tf: "M15", kr: "M5", n: 0 });
  const [krN, setKrN] = useState(0);
  useEffect(() => {
    if (!active) return;
    const a = api.current;
    if (!a) return;
    const cur = a.sel();
    setSel((x) => ({ ...x, ...cur }));
    a.onSelect((e: any) => { if (e.what === "kronos") { setSel((x) => ({ ...x, kr: e.kr })); setKrN((n) => n + 1); } else setSel((x) => ({ ...x, asset: e.asset, tf: e.tf, kr: e.kr, n: x.n + 1 })); });
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!active || tfDone.current) return;
    apiGet<any>("/api/v1/timeframes").then((r) => { tfDone.current = true; api.current?.setTimeframes(r?.timeframes || []); }).catch(() => undefined);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!active) return;
    api.current?.setSymbol("XAUUSD", s?.symbol?.symbol);
    const n = (x: unknown) => (x == null || !Number.isFinite(Number(x)) ? null : Number(x));
    if (sel.asset === "XAUUSD") api.current?.setQuote(s?.quote ? { bid: n(s.quote.bid), ask: n(s.quote.ask), spread: n(s.quote.spread) } : null);
    api.current?.setStatus(chartStatus(s));
  }, [active, sel.asset, s?.quote, s?.connection?.state, s?.dq?.status, s?.symbol?.symbol]); // eslint-disable-line react-hooks/exhaustive-deps
  // świece: wybrany instrument / TF; po bar_closed tego TF; fallback co 30 s
  const closedSeq = s?.barTick?.[sel.tf]?.closed ? s.barTick[sel.tf].seq : null;
  const [poll, setPoll] = useState(0);
  useEffect(() => { if (!active) return; const t = setInterval(() => setPoll((x) => x + 1), 30000); return () => clearInterval(t); }, [active]);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const xau = apiGet<any>(`/api/v1/candles?tf=${sel.tf}`);
    const src = sel.asset === "BTC" ? apiGet<any>(`/api/v1/market-zones/bars?instrument=BTC&tf=${sel.tf}&count=600`) : xau;
    Promise.all([xau.catch(() => null), src]).then(([cx, r]) => {
      if (!alive) return;
      const candles = candlesVM(r);
      if (r?.symbol && sel.asset === "BTC") api.current?.setSymbol("BTC", r.symbol);
      api.current?.setVM({ asset: sel.asset, tf: sel.tf, candles, iprof: iprofVM(cx), status: candles.length ? chartStatus(s) : (r?.status === "NO_SYMBOL" ? "offline" : "loading") });
    }).catch(() => alive && api.current?.setStatus("offline"));
    return () => { alive = false; };
  }, [active, sel.asset, sel.tf, sel.n, closedSeq, poll]); // eslint-disable-line react-hooks/exhaustive-deps
  // świeca w budowie na żywo (store, tylko instrument silnika)
  const tick = s?.barTick?.[sel.tf];
  useEffect(() => {
    if (!active || !tick?.bar || tick.closed || sel.asset !== "XAUUSD") return;
    const b = candlesVM({ bars: [{ ...tick.bar, closed: false }] })[0];
    if (b) api.current?.liveBar(b);
  }, [active, tick?.seq]); // eslint-disable-line react-hooks/exhaustive-deps
  // Kronos: stan + prognoza wybranego TF Kronos (PRZELICZ = ponowny GET)
  const krClosed = s?.barTick?.[sel.kr]?.closed ? s.barTick[sel.kr].seq : null;
  useEffect(() => {
    if (!active) return;
    let alive = true;
    Promise.all([apiGet<any>("/api/v1/kronos").catch(() => null), apiGet<any>(`/api/v1/kronos/forecast?instrument=${sel.asset}&tf=${sel.kr}`).catch(() => null)])
      .then(([st, fc]) => { if (alive) api.current?.setKronos(kronosVM(fc, sel.kr, st)); });
    return () => { alive = false; };
  }, [active, sel.asset, sel.kr, krN, krClosed, poll]); // eslint-disable-line react-hooks/exhaustive-deps
}
