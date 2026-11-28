// CHARTS 1:1 – warstwa danych (D1). Czyste adaptery odpowiedzi API → model widoku = struktury czytane przez kod wzorca (D1 §3),
// ten sam kształt co fixtures testu 1:1. Brak pola w API = stan pusty (null / []), nigdy wartość zgadywana. Tylko GET.
// Ten plik nie importuje Reacta w adapterach – testy w Node: tests/js/charts_adapters.test.mjs.
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { apiGet } from "../../../../api";
import { barCloseStep, basketMetaVM, basketSignalVM, candlesVM, cardProbsVM, chartStatus, iprofVM, kronosVM, legacyMetaVM, legacySignalVM, planProbsVM, sameInstrument,
  shMetaVM, shSignalVM, statesVM, zonesMsgVM, zonesVM, type BarCloses, type Meta, type Sig } from "./chartsAdapters";
export * from "./chartsAdapters";

/** Hook danych ekranu CHARTS (K2): świece + profil wskaźników silnika, tiki na żywo ze store, Kronos. Tylko GET; ponowne pobranie po
 *  bar_closed wybranego TF, w tle najwyżej co 30 s (D1 §2). Wyniki trafiają do renderera przez api.setVM / liveBar / setKronos. */
const g = (u: string) => apiGet<any>(u).catch(() => null);
let metaCache: Meta | null = null;

/** Warstwy bota dla instrumentu (K3, tylko GET): meta strategii (raz), stany koszyków, sygnały koszyków / S01–S12 / SH. Szanse w karcie
 *  liczone per wybrany plan (planSel poniżej; 1.46 I0328 – lista /models/predictions instrumentu nie ma zadań planu).
 *  Szczegóły sygnału S01–S12 (cele, powody, czas świecy) są w rekordzie listy /bot-signals (detail, take_profits – SignalStore._public). */
async function botLayers(asset: string, engineSymbol?: string, assetSymbol?: string | null) {
  const [cat, auto, shc, bk, bs, ls, ss] = await Promise.all([
    metaCache ? null : g("/api/v1/baskets/catalog"), metaCache ? null : g("/api/v1/strategy/auto"), metaCache ? null : g("/api/v1/sh/config"),
    g("/api/v1/baskets"), g("/api/v1/baskets/signals?limit=300"),
    asset === "XAUUSD" ? g(`/api/v1/bot-signals?limit=100&rejected=false${engineSymbol ? "&symbol=" + encodeURIComponent(engineSymbol) : ""}`) : null,
    asset === "XAUUSD" ? g("/api/v1/sh/signals?limit=200") : null]);
  if (!metaCache && cat && auto && shc) metaCache = { ...basketMetaVM(cat), LEGACY: legacyMetaVM(auto), SH: shMetaVM(shc) };
  // 1.46: the list record already carries detail + take_profits (the same _public as GET /bot-signals/{id}) - the per-signal GET (up to 40 per
  // refresh) and the module-level cache that grew for the whole life of the window are gone; signals without a fetched detail are no longer hidden
  const rows: any[] = (ls?.items || []).filter((x: any) => /^S\d{2}$/.test(String(x.strategy_id || "")));
  const signals: Sig[] = [
    ...(bs?.signals || []).filter((x: any) => sameInstrument(x.instrument, asset, assetSymbol)).map(basketSignalVM),
    ...rows.map((x) => legacySignalVM(x)),
    ...(ss?.items || []).filter((x: any) => sameInstrument(x.instrument, asset, assetSymbol)).map(shSignalVM),
  ].filter((x): x is Sig => !!x && Number.isFinite(x.t)).sort((a, b) => a.t - b.t);
  return { meta: metaCache || undefined, signals, states: statesVM(bk, asset, assetSymbol), probs: cardProbsVM() };
}

/** 1.46: licznik zamknięć świec TF z barTick (barCloseStep) – zależność efektów zamiast chwilowego closed/seq (gubionego przy batchowaniu). */
function useBarCloses(barTick: any, tf: string): number {
  const r = useRef<{ tf: string; st: BarCloses | null }>({ tf, st: null });
  if (r.current.tf !== tf) r.current = { tf, st: null };
  const tick = barTick?.[tf];
  if (tick) r.current.st = barCloseStep(r.current.st, tick);
  return r.current.st?.n ?? 0;
}

// 1.46: CZAS SERWERA na wykresie był stałym UTC+2 (renderer nie dostawał vm.serverOff) – teraz zmierzony offset zegara serwera MT5 z odpowiedzi
// /api/v1/candles (clock z mt5/clock.py), wyłącznie gdy status = VERIFIED; inaczej null (renderer pokazuje UTC z dopiskiem NIEZWERYFIKOWANY)
export function serverOffVM(cx: any): number | null {
  const c = cx?.clock;
  const sec = c?.offset_seconds == null ? NaN : Number(c.offset_seconds);
  return c?.status === "VERIFIED" && Number.isFinite(sec) ? sec / 3600 : null;
}
// 1.46: profile SVP / etykieta binu zakładały tick 0.01 i 2 cyfry – tick_size i digits symbolu silnika (symbol.info ze store; jak svp/service._ctx:
// trade_tick_size, potem point); brak = null (renderer: „tick 0.01 NIEZWERYFIKOWANY”), nigdy 0
export function symbolSpecVM(info: any): { tick: number | null; digits: number | null } {
  const tk = Number(info?.trade_tick_size || info?.point);
  return { tick: Number.isFinite(tk) && tk > 0 ? tk : null, digits: Number.isInteger(info?.digits) && info.digits >= 0 ? info.digits : null };
}

/** 1.46: /market-zones/bars (świece BTC) przyjmuje tylko TF stref (400 INVALID_TF dla H1 i wyżej) – to nie jest rozłączenie terminala. */
const tfUnsupported = (e: any) => e?.status === 400 && /INVALID_TF/.test(String(e?.message || ""));

/** 1.46 (I0328): szanse wybranego planu – SH: zapis sygnału (GET /api/v1/sh/signals/{signal_id}, tylko odczyt); S01–S12 i koszyki bez zapytania
 *  (GET /api/v1/ml/predict zapisuje predykcję do próby driftu ML – panel go nie woła). Wynik do renderera: setPlanProbs(klucz planu, szanse). */
export function planProbsFor(plan: { key: string; src: string; ref?: string | null } | null, get: (u: string) => Promise<any> = g): Promise<Record<string, any>> {
  if (!plan || plan.src !== "SH" || !plan.ref) return Promise.resolve(planProbsVM(plan as any));
  return get(`/api/v1/sh/signals/${encodeURIComponent(plan.ref)}`).then((d) => planProbsVM(plan as any, d), () => planProbsVM(plan as any, null));
}

export function useChartsData(api: MutableRefObject<any>, active: boolean, s: any) {
  const tfDone = useRef(false);
  const btcSym = useRef<string | null>(null);
  const [sel, setSel] = useState<{ asset: string; tf: string; kr: string; n: number }>({ asset: "XAUUSD", tf: "M15", kr: "M5", n: 0 });
  const [krN, setKrN] = useState(0);
  const planSel = (p: any) => { if (p?.key) planProbsFor(p).then((pr) => api.current?.setPlanProbs?.(p.key, pr)); };
  useEffect(() => {
    if (!active) return;
    const a = api.current;
    if (!a) return;
    const cur = a.sel();
    setSel((x) => ({ ...x, ...cur }));
    const off = a.onSelect((e: any) => {
      if (e.what === "plan") { planSel(e.plan); return; }                  // 1.46 (I0328): wybór planu nie przeładowuje świec
      if (e.what === "kronos") { setSel((x) => ({ ...x, kr: e.kr })); setKrN((n) => n + 1); } else setSel((x) => ({ ...x, asset: e.asset, tf: e.tf, kr: e.kr, n: x.n + 1 }));
    });
    return () => { if (typeof off === "function") off(); };     // 1.46: one listener per entry into CHARTS (they accumulated before)
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
  const closedN = useBarCloses(s?.barTick, sel.tf);
  const [poll, setPoll] = useState(0);
  useEffect(() => { if (!active) return; const t = setInterval(() => setPoll((x) => x + 1), 30000); return () => clearInterval(t); }, [active]);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const xau = apiGet<any>(`/api/v1/candles?tf=${sel.tf}`);
    const src = sel.asset === "BTC" ? apiGet<any>(`/api/v1/market-zones/bars?instrument=BTC&tf=${sel.tf}&count=600`)
      .catch((e) => { if (tfUnsupported(e)) return { status: "TIMEFRAME_NOT_SUPPORTED", bars: [] }; throw e; }) : xau;
    const mz = apiGet<any>(`/api/v1/market-zones?instrument=${sel.asset}&all=true`).catch(() => null);
    Promise.all([xau.catch(() => null), src, mz, botLayers(sel.asset, s?.symbol?.symbol, sel.asset === "BTC" ? btcSym.current : s?.symbol?.symbol)]).then(([cx, r, z, B]) => {
      if (!alive) return;
      const candles = candlesVM(r);
      if (r?.symbol && sel.asset === "BTC") { api.current?.setSymbol("BTC", r.symbol); btcSym.current = r.symbol; }
      const zt = zonesVM(z, sel.tf);                                   // K4: wyłącznie wybrany TF – nic z innego interwału
      const noTf = r?.status === "TIMEFRAME_NOT_SUPPORTED";
      // 1.46: offset serwera (ten sam terminal MT5 dla XAUUSD i BTC) oraz tick / cyfry symbolu silnika – BTC (market-zones/bars) ich nie podaje -> null
      const spec = symbolSpecVM(sel.asset === "XAUUSD" ? s?.symbol?.info : null);
      api.current?.setVM({ asset: sel.asset, tf: sel.tf, candles, serverOff: serverOffVM(cx), tick: spec.tick, digits: spec.digits, iprof: iprofVM(cx), ...B,
        zones: zt ? { [sel.tf]: zt } : {},
        zoneMsg: noTf ? `Świece ${sel.asset} ${sel.tf}: TIMEFRAME_NOT_SUPPORTED – API świec ${sel.asset} (market-zones/bars) obsługuje tylko interwały stref M1–M30. Wybierz M1, M5, M15 albo M30.`
          : zonesMsgVM(z, sel.tf),
        status: candles.length || noTf ? chartStatus(s) : (r?.status === "NO_SYMBOL" ? "offline" : "loading") });
    }).catch(() => alive && api.current?.setStatus("offline"));
    return () => { alive = false; };
  }, [active, sel.asset, sel.tf, sel.n, closedN, poll]); // eslint-disable-line react-hooks/exhaustive-deps
  // świeca w budowie na żywo (store, tylko instrument silnika)
  const tick = s?.barTick?.[sel.tf];
  useEffect(() => {
    if (!active || !tick?.bar || tick.closed || sel.asset !== "XAUUSD") return;
    const b = candlesVM({ bars: [{ ...tick.bar, closed: false }] })[0];
    if (b) api.current?.liveBar(b);
  }, [active, tick?.seq]); // eslint-disable-line react-hooks/exhaustive-deps
  // Kronos: stan + prognoza wybranego TF Kronos (PRZELICZ = ponowny GET)
  const krClosed = useBarCloses(s?.barTick, sel.kr);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    Promise.all([apiGet<any>("/api/v1/kronos").catch(() => null), apiGet<any>(`/api/v1/kronos/forecast?instrument=${sel.asset}&tf=${sel.kr}`).catch(() => null)])
      .then(([st, fc]) => { if (alive) api.current?.setKronos(kronosVM(fc, sel.kr, st)); });
    return () => { alive = false; };
  }, [active, sel.asset, sel.kr, krN, krClosed, poll]); // eslint-disable-line react-hooks/exhaustive-deps
}
