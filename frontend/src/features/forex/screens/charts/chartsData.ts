// CHARTS 1:1 – warstwa danych (D1). Czyste adaptery odpowiedzi API → model widoku = struktury czytane przez kod wzorca (D1 §3),
// ten sam kształt co fixtures testu 1:1. Brak pola w API = stan pusty (null / []), nigdy wartość zgadywana. Tylko GET.
// Ten plik nie importuje Reacta w adapterach – testy w Node: tests/js/charts_adapters.test.mjs.
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { apiGet } from "../../../../api";
import { basketMetaVM, basketSignalVM, candlesVM, cardProbsVM, chartStatus, heatError, heatFromWorkspace, heatVM, iprofVM, kronosVM, legacyMetaVM, legacySignalVM, sameInstrument, shMetaVM,
  shSignalVM, statesVM, zonesMsgVM, zonesVM, type HeatVM, type Meta, type Sig } from "./chartsAdapters";
export * from "./chartsAdapters";

/** Hook danych ekranu CHARTS (K2): świece + profil wskaźników silnika, tiki na żywo ze store, Kronos. Tylko GET; ponowne pobranie po
 *  bar_closed wybranego TF, w tle najwyżej co 30 s (D1 §2). Wyniki trafiają do renderera przez api.setVM / liveBar / setKronos. */
const g = (u: string) => apiGet<any>(u).catch(() => null);
let metaCache: Meta | null = null;
const legacyDetail = new Map<string, any>();

/** Warstwy bota dla instrumentu (K3, tylko GET): meta strategii (raz), stany koszyków, sygnały koszyków / S01–S12 / SH, szanse w karcie.
 *  Szczegóły sygnału S01–S12 (cele, powody, czas świecy) – GET /bot-signals/{id} raz na sygnał; stan / wynik zawsze z listy. */
async function botLayers(asset: string, engineSymbol?: string, assetSymbol?: string | null) {
  const [cat, auto, shc, bk, bs, ls, ss, pred] = await Promise.all([
    metaCache ? null : g("/api/v1/baskets/catalog"), metaCache ? null : g("/api/v1/strategy/auto"), metaCache ? null : g("/api/v1/sh/config"),
    g("/api/v1/baskets"), g("/api/v1/baskets/signals?limit=300"),
    asset === "XAUUSD" ? g(`/api/v1/bot-signals?limit=100&rejected=false${engineSymbol ? "&symbol=" + encodeURIComponent(engineSymbol) : ""}`) : null,
    asset === "XAUUSD" ? g("/api/v1/sh/signals?limit=200") : null, g(`/api/v1/models/predictions?instrument=${asset}`)]);
  if (!metaCache && cat && auto && shc) metaCache = { ...basketMetaVM(cat), LEGACY: legacyMetaVM(auto), SH: shMetaVM(shc) };
  const rows: any[] = (ls?.items || []).filter((x: any) => /^S\d{2}$/.test(String(x.strategy_id || "")));
  await Promise.all(rows.filter((x) => !legacyDetail.has(x.signal_id)).slice(0, 40).map((x) =>
    g(`/api/v1/bot-signals/${encodeURIComponent(x.signal_id)}`).then((d) => { if (d) legacyDetail.set(x.signal_id, d); })));
  const signals: Sig[] = [
    ...(bs?.signals || []).filter((x: any) => sameInstrument(x.instrument, asset, assetSymbol)).map(basketSignalVM),
    ...rows.filter((x) => legacyDetail.has(x.signal_id)).map((x) => legacySignalVM({ ...legacyDetail.get(x.signal_id), ...x })),
    ...(ss?.items || []).filter((x: any) => sameInstrument(x.instrument, asset, assetSymbol)).map(shSignalVM),
  ].filter((x): x is Sig => !!x && Number.isFinite(x.t)).sort((a, b) => a.t - b.t);
  return { meta: metaCache || undefined, signals, states: statesVM(bk, asset, assetSymbol), probs: cardProbsVM(pred) };
}

export function useChartsData(api: MutableRefObject<any>, active: boolean, s: any) {
  const tfDone = useRef(false);
  const btcSym = useRef<string | null>(null);
  const [sel, setSel] = useState<{ asset: string; tf: string; kr: string; n: number; view: string; hw: number }>({ asset: "XAUUSD", tf: "M15", kr: "M5", n: 0, view: "chart", hw: 900 });
  const [krN, setKrN] = useState(0);
  useEffect(() => {
    if (!active) return;
    const a = api.current;
    if (!a) return;
    const cur = a.sel();
    setSel((x) => ({ ...x, ...cur }));
    a.onSelect((e: any) => { if (e.what === "kronos") { setSel((x) => ({ ...x, kr: e.kr })); setKrN((n) => n + 1); }
      else if (e.what === "heat") setSel((x) => ({ ...x, view: e.view, hw: e.hw }));
      else setSel((x) => ({ ...x, asset: e.asset, tf: e.tf, kr: e.kr, view: e.view ?? x.view, hw: e.hw ?? x.hw, n: x.n + 1 })); });
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
    const mz = apiGet<any>(`/api/v1/market-zones?instrument=${sel.asset}&all=true`).catch(() => null);
    Promise.all([xau.catch(() => null), src, mz, botLayers(sel.asset, s?.symbol?.symbol, sel.asset === "BTC" ? btcSym.current : s?.symbol?.symbol)]).then(([cx, r, z, B]) => {
      if (!alive) return;
      const candles = candlesVM(r);
      if (r?.symbol && sel.asset === "BTC") { api.current?.setSymbol("BTC", r.symbol); btcSym.current = r.symbol; }
      const zt = zonesVM(z, sel.tf);                                   // K4: wyłącznie wybrany TF – nic z innego interwału
      api.current?.setVM({ asset: sel.asset, tf: sel.tf, candles, iprof: iprofVM(cx), ...B, zones: zt ? { [sel.tf]: zt } : {}, zoneMsg: zonesMsgVM(z, sel.tf),
        status: candles.length ? chartStatus(s) : (r?.status === "NO_SYMBOL" ? "offline" : "loading") });
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
  // HEATMAPA (styl Bookmap): XAUUSD = archiwum arkusza MT5 bota (GET co 2 s, okno ≥ 1 h co 5 s); BTC = bieżący arkusz + transakcje
  // dostawcy (GET co 2 s), kolumny składane od otwarcia widoku. Tylko gdy widok HEATMAPA jest włączony i ekran aktywny.
  useEffect(() => {
    if (!active || sel.view !== "heat") return;
    let alive = true, busy = false, prev: HeatVM | null = null;
    const src = sel.asset === "BTC" ? "CRYPTO" : "MT5";
    const run = () => {
      if (busy) return;
      busy = true;
      const req = src === "MT5" ? apiGet<any>(`/api/v1/orderflow/mt5/heatmap?seconds=${sel.hw}&cols=240`).then(heatVM)
        : apiGet<any>("/api/v1/orderflow/CRYPTO/workspace?instrument=BTC").then((r) => (prev = heatFromWorkspace(prev, r, Date.now(), sel.hw)));
      req.then((vm) => { if (alive) api.current?.setHeat(vm); }).catch((e) => { if (alive) api.current?.setHeat(prev && prev.cols.length ? prev : heatError(e, src)); })
        .finally(() => { busy = false; });
    };
    run();
    const t = setInterval(run, src === "MT5" && sel.hw >= 3600 ? 5000 : 2000);
    return () => { alive = false; clearInterval(t); };
  }, [active, sel.view, sel.hw, sel.asset]); // eslint-disable-line react-hooks/exhaustive-deps
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
