// CHARTS 1:1 – czyste adaptery API → model widoku (D1 §3), bez Reacta; testy: tests/js/charts_adapters.test.mjs.
export type Candle = { t: number; o: number; h: number; l: number; c: number; v: number; closed: boolean };
export type Sig = {
  sid: string; src: "BASKET" | "LEGACY" | "SH"; tf: string; t: number; sd: 1 | -1; e: number; sl: number; tp: number[];
  res: string; hit: string[]; et: number | null; inv?: number | null; rg?: string | null; ro?: boolean | null; ev?: string | null;
  tb?: string | string[] | null; to?: number | null; sc?: number | null; why?: string[]; miss?: string[]; trg?: string | null;
  sh?: number[] | null; rr?: number | null; be?: string | null; hz?: number | null;
};
export type Zone = { ty: string; lo: number; up: number; st: string; t0: number; t1: number | null; q: number | null; why: string | null; v: 0 | 1 };
export type Prob = { name: string; task: string; v: number | null; state: string; cal: string; src: string };

const ms = (x: unknown): number | null => {
  if (x == null || x === "") return null;
  if (typeof x === "number") return x > 1e12 ? x : x * 1000;
  const v = Date.parse(String(x));
  return Number.isNaN(v) ? null : v;
};
const num = (x: unknown): number | null => (x == null || x === "" || !Number.isFinite(Number(x)) ? null : Number(x));

/** GET /api/v1/candles (bars[]: open_utc, o, h, l, c, tv, closed) albo /api/v1/market-zones/bars (BTC przy innym symbolu MT5). */
export function candlesVM(resp: any): Candle[] {
  const bars: any[] = resp?.bars || [];
  const out: Candle[] = [];
  for (const b of bars) {
    const t = ms(b.open_utc);
    if (t == null || [b.o, b.h, b.l, b.c].some((x) => num(x) == null)) continue;
    out.push({ t, o: +b.o, h: +b.h, l: +b.l, c: +b.c, v: num(b.tv) ?? 0, closed: b.closed !== false });
  }
  return out.sort((a, b) => a.t - b.t);
}

/** Koszyki FX (GET /api/v1/baskets/signals): plan = PositionPlan, wynik z ledgera (status + outcome_kind). */
export function basketSignalVM(x: any): Sig | null {
  const pl = x?.plan || {}, su = x?.setup || {};
  const e = num(pl.entry_ref), sl = num(pl.sl);
  if (x?.profile_id && x.profile_id !== "FOREX_MT5") return null;
  if (pl.plan_type && pl.plan_type !== "PositionPlan") return null;
  if (e == null || sl == null) return null;
  const tp = (pl.targets || []).map((t: any) => num(t?.price)).filter((v: number | null): v is number => v != null);
  const ok = x.outcome_kind as string | null;
  const res = x.status === "ACTIVE" ? "OTWARTY" : ok && ["SL", "TP1", "TP2", "TIMEOUT"].includes(ok) ? ok : (ok || x.status || "—");
  const hit = res === "TP1" ? ["TP1"] : res === "TP2" ? ["TP1", "TP2"] : [];
  return {
    sid: x.strategy_id, src: "BASKET", tf: x.tf, t: ms(x.bar_t) as number, sd: pl.side === "SHORT" ? -1 : 1, e, sl, tp, res, hit,
    et: ms(x.outcome_at), inv: num(su.invalidation), rg: su.regime?.regime ?? su.regime?.state ?? (typeof su.regime === "string" ? su.regime : null), ro: typeof x.routed_auto === "boolean" ? x.routed_auto : (typeof su.routed_auto === "boolean" ? su.routed_auto : null),
    ev: su.event?.type ?? null, tb: su.target != null ? "STRUKTURA" : "R", to: num(pl.timeout_bars),
  };
}

/** S01–S12 (GET /api/v1/bot-signals): status OPEN / WIN / LOSS / TIMEOUT + tp_hit (liczba osiągniętych celów). */
export function legacySignalVM(x: any): Sig | null {
  if (!/^S\d{2}$/.test(String(x?.strategy_id || ""))) return null;
  const e = num(x.entry_price), sl = num(x.stop_loss);
  if (e == null || sl == null) return null;
  const n = Number(x.tp_hit || 0), hit = Array.from({ length: n }, (_, k) => "TP" + (k + 1));
  const st = String(x.status || "");
  const res = st === "OPEN" ? "OTWARTY" : st === "WIN" ? "TP" + Math.max(1, n) : st === "LOSS" ? (n ? "SL_PO_TP" + n : "SL")
    : st === "TIMEOUT" ? (n ? "TIMEOUT_PO_TP" + n : "TIMEOUT") : st || "—";
  const d = x.detail || {};
  return {
    sid: x.strategy_id, src: "LEGACY", tf: x.timeframe, t: ms(x.detail?.source_time ?? x.created_at) as number, sd: x.action === "SELL" ? -1 : 1, e, sl,
    tp: (x.take_profits || []).map(num).filter((v: number | null): v is number => v != null), res, hit, et: ms(x.closed_at),
    inv: num(d.invalidation_level), rg: d.regime ?? null, tb: d.exit_rules ?? null, sc: num(x.setup_score),
    why: d.reason_codes || [], miss: d.missing_confirmations || [], trg: x.trigger ?? null,
  };
}

/** Strefy bota tylko z wybranego TF (GET /api/v1/market-zones → timeframes[tf]); v = 1 dla stref wybranych przez silnik. */
export function zonesVM(resp: any, tf: string): Zone[] | null {
  const T = resp?.timeframes?.[tf];
  if (!T || T.computed === false) return null;
  const vis = new Set<string>(T.visible || []);
  return (T.zones || []).map((z: any) => ({
    ty: z.type, lo: +z.lower, up: +z.upper, st: z.state, t0: ms(z.origin_time) as number, t1: ms(z.invalidated_at ?? z.expired_at),
    q: num(z.quality?.score), why: z.reason ?? null, v: vis.has(z.id) ? 1 : 0,
  }));
}

/** Szanse modeli (PMW-PRED): % tylko unit=probability + CALIBRATED_*; inaczej v = null (karta pokaże stan, nie liczbę). */
export function probVM(p: any, name: string): Prob {
  if (!p) return { name, task: "—", v: null, state: "NO_DATA", cal: "NOT_APPLICABLE", src: "brak modelu w API" };
  const cal = p.calibration?.status || "NOT_APPLICABLE";
  const raw = p.result?.probability ?? p.result?.p ?? null;
  const ok = p.unit === "probability" && /^CALIBRATED/.test(cal) && typeof raw === "number";
  return { name, task: p.task || "—", v: ok ? raw : null, state: p.state || "NO_DATA", cal, src: p.model_name || p.source || "—" };
}

/** Kronos (GET /api/v1/kronos/forecast + GET /api/v1/kronos): forecast.* bez symulacji. API podaje kwantyle, nie pojedyncze ścieżki
 *  niepewności → paths = [] (wachlarz nie jest rysowany, stopka: „BRAK ŚCIEŻEK NIEPEWNOŚCI”). Kontekst = ostatnie zamknięte świece modelu. */
export function kronosVM(resp: any, tf: string, status?: any) {
  const f = resp?.forecast;
  const st = String(status?.status || "");
  const role = Object.values(status?.decision_use || {}).includes("ASSIST") ? "ASSIST – może tylko wstrzymać wejście, bez zleceń" : "SHADOW, bez zleceń";
  const tfs: string[] = status?.settings?.timeframes || status?.timeframes || [];
  const on = Object.fromEntries(["M1", "M5", "M15", "M30", "H1"].map((t) => [t, tfs.length ? tfs.includes(t) : true]));
  const notInstalled = st === "NOT_INSTALLED" || st === "NO_WEIGHTS";
  const emptyTxt = notInstalled ? "KRONOS NIEZAINSTALOWANY – 33_KRONOS_INSTALUJ.bat" : !["M1", "M5", "M15", "M30", "H1"].includes(tf) ? "TIMEFRAME_NOT_ALLOWED"
    : ((resp?.target?.reason || status?.status_pl || "BRAK PROGNOZY").toString()
      + (/Memory Governor/.test(String(resp?.target?.reason || "")) ? " – zajętość pamięci: Diagnostyka → Zasoby" : "")).toUpperCase();
  const candles = (resp?.context || []).map((b: any) => ({ t: ms(b.t ?? b.open_utc) as number, o: +b.o, h: +b.h, l: +b.l, c: +b.c, v: 0, closed: true }))
    .filter((b: any) => b.t != null);
  if (!f) return { tf, on, role, state: notInstalled ? "NOT_INSTALLED" : (resp?.target?.state || st || "NO_DATA"), emptyTxt, candles, forecast: null };
  const pred = (f.pred || []).map((b: any) => ({ t: ms(b.t_utc ?? b.open_utc ?? b.t) as number, o: +b.o, h: +b.h, l: +b.l, c: +b.c }));
  return {
    tf, on, role, state: "READY", emptyTxt, candles,
    forecast: { pred, paths: [] as number[][], last_close: num(f.last_close), pred_close_h: num(f.pred_close_h), delta: num(f.delta_price),
      delta_pct: num(f.delta_pct), direction: f.direction, neutral_band: num(f.neutral_band), horizon: num(f.horizon_bars),
      created_at: ms(f.created_at), is_current: !!resp.is_current, atr: num(f.atr14) },
  };
}

/** Profil wskaźników silnika (M02I) dla TF z GET /api/v1/candles → indicators: okresy EMA, okres RSI, średnia sygnału MACD. */
export function iprofVM(resp: any): { ema: (number | null)[]; rsi: number; sig: "SMA" | "EMA" } | null {
  const I = resp?.indicators;
  if (!I) return null;
  const ema = (I.lines || []).filter((l: any) => /^EMA\d+$/.test(String(l.id))).map((l: any) => +String(l.id).slice(3)).slice(0, 2);
  return { ema: [ema[0] ?? 20, ema[1] ?? null], rsi: +(I.panels?.rsi?.period || 14), sig: I.panels?.macd?.signal_ma === "EMA" ? "EMA" : "SMA" };
}

/** Status MT5 w nagłówku wzorca: live / loading / offline / stale. */
export function chartStatus(s: any): "live" | "loading" | "offline" | "stale" {
  const st = s?.connection?.state;
  if (st === "CONNECTED") return s?.dq?.status === "STALE" ? "stale" : "live";
  return st === "CONNECTING" || st == null ? "loading" : "offline";
}


/* ---------------- K3: strategie, sygnały, karta planu ---------------- */
export type Meta = Record<string, any[]>;
const FX_BK = ["FX_SMC", "FX_SCALP", "FX_HEDGE"];
const SH_FAM = ["SCALPING", "HEDGING"];

/** Katalog koszyków FX (GET /api/v1/baskets/catalog) → SMETA koszyków (D1 §3.4). Profil FOREX_MT5. */
export function basketMetaVM(cat: any): Meta {
  const out: Meta = { FX_SMC: [], FX_SCALP: [], FX_HEDGE: [] };
  for (const s of cat?.strategies || []) {
    if (!FX_BK.includes(s.basket_id)) continue;
    const ps = s.parameter_schema || {};
    out[s.basket_id].push({
      id: s.strategy_id, nm: s.name, tf: s.signal_timeframe, ctx: s.context_timeframes || [], fam: s.family_id, grp: s.correlation_group,
      setup: s.setup_rule ?? null, trig: s.trigger_rule ?? null, cancel: s.cancellation_rule ?? null, exit: s.exit_policy_or_expiry_policy ?? null,
      plan: s.plan_type, tp_r: Array.isArray(ps.tp_r) ? ps.tp_r : null, need: s.required_inputs || [], kind: s.kind,
    });
  }
  return out;
}

/** S01–S12 (GET /api/v1/strategy/auto → strategies = registry.describe() + flaga trade, funnel). */
export function legacyMetaVM(auto: any): any[] {
  const fn = auto?.funnel || {};
  return (auto?.strategies || []).map((d: any) => ({
    id: d.strategy_id, nm: d.name, fam: d.family, tfs: d.setup_tfs || [], val: d.validation_status ?? null, notrade: d.trade === false,
    funnel: fn[d.strategy_id] || {},
  }));
}

/** SH (GET /api/v1/sh/config → instruments[inst][SCALPING|HEDGING]): TP w USD, udziały, BE, SL min–max, horyzont, status instrumentu. */
export function shMetaVM(cfg: any): any[] {
  const I = cfg?.instruments || {}, base = I.XAUUSD || {};
  return SH_FAM.filter((f) => base[f]).map((f) => {
    const p = base[f];
    return {
      id: "SH_" + f, nm: "SH · " + f, tp_usd: p.tp_usd || [], shares: p.shares || [], be: p.be_after ?? null, sl_usd: [p.sl_min_usd, p.sl_max_usd],
      hz: p.horizon_minutes ?? null, pos_max: p.position_max_minutes ?? null, regimes: p.allow_regimes || [],
      status: Object.fromEntries(Object.entries(I).map(([k, v]: [string, any]) => [k, v?.status ?? "—"])), counts: {},
    };
  });
}

/** Stany strategii dla instrumentu (D1 §3.3): koszyki – bieżący stan z /api/v1/baskets, `un` = powód z API, gdy profil nie ma danych. */
/** Instrument sygnału / kontekstu koszyka = nazwa aktywa albo jego symbol brokera MT5. */
export const sameInstrument = (inst: unknown, asset: string, symbol?: string | null) => inst === asset || (!!symbol && inst === symbol);

export function statesVM(baskets: any, asset: string, symbol?: string | null): Record<string, { st: Record<string, number>; un: string | null }> {
  const out: Record<string, { st: Record<string, number>; un: string | null }> = {};
  const key = (o: any) => (o && symbol && o[symbol] != null ? symbol : asset);       // kontekst profilu FOREX_MT5 = symbol brokera (np. XAUUSD-)
  for (const b of baskets?.baskets || []) {
    if (!FX_BK.includes(b.basket_id)) continue;
    const ds = b.data_status || {}, mine = ds[key(ds)];
    const un = mine ? (mine.state === "READY" ? null : mine.reason || mine.state) : (ds["-"] ? ds["-"].reason || ds["-"].state : `brak kontekstu ${asset} w profilu FOREX_MT5`);
    for (const s of b.strategies || []) {
      const cur = (s.states || {})[key(s.states)];
      out[s.strategy_id] = { st: cur?.state ? { [cur.state]: 1 } : {}, un: s.enabled === false ? "strategia wyłączona" : un };
    }
  }
  return out;
}

const SH_STATE_PL: Record<string, string> = { READY: "GOTOWY", EXPIRED: "WYGASŁY", INVALIDATED: "UNIEWAŻNIONY", BLOCKED: "ZABLOKOWANY" };
/** SH (GET /api/v1/sh/signals → levels zapisane z sygnałem od K3, plan z wynikiem cyklu). Bez poziomów w zapisie → brak markera. */
export function shSignalVM(x: any): Sig | null {
  const L = x?.levels;
  if (!L || num(L.entry) == null || num(L.sl) == null) return null;
  const tg = (L.targets || []).filter((t: any) => num(t?.price) != null);
  const P = x.plan;
  const hit: string[] = P?.tp_done || [];
  const n = hit.length, why = String(P?.close_reason || "");
  let res: string;
  if (!P) res = SH_STATE_PL[x.status] || x.status || "—";
  else if (P.state !== "CLOSED") res = P.state === "REJECTED" || P.state === "ERROR_CLOSED" ? P.state : "OTWARTY";
  else if (/TP3/.test(why)) res = "TP3";
  else if (/SL|STOP|BE/.test(why)) res = n ? "SL_PO_TP" + n : "SL";
  else if (/TIME|MAX|HORIZON/.test(why)) res = n ? "TIMEOUT_PO_TP" + n : "TIMEOUT";
  else res = n ? "TP" + n : why || "ZAMKNIĘTY";
  const side = String(L.side || x.side || "");
  return {
    sid: "SH_" + x.strategy, src: "SH", tf: "M1", t: ms(x.created_at) as number, sd: /SELL|SHORT/.test(side) ? -1 : 1, e: +L.entry, sl: +L.sl,
    tp: tg.map((t: any) => +t.price), res, hit, et: ms(P?.closed_at ?? (x.status !== "READY" ? x.updated_at : null)),
    sh: tg.map((t: any) => num(t.share) ?? 0), rr: num(L.net_rr), be: L.be_after ?? "—", hz: num(L.horizon_minutes),
  };
}

/** Szanse w karcie planu (D1 §3.7): win = Legacy ML (NET_R_POSITIVE_S01_S12), tp2 = SH tp_model (TP2_BEFORE_SL_H) z /api/v1/models/predictions. */
export function cardProbsVM(pred: any): Record<string, Prob> {
  const items: any[] = pred?.items || [];
  const find = (re: RegExp) => items.find((p) => re.test(String(p.task || "")) || re.test(String(p.model_key || "")));
  return { win: probVM(find(/NET_R_POSITIVE/), "Legacy ML · P(cel przed SL)"), tp2: probVM(find(/TP2_BEFORE_SL/), "SH tp_model · P(TP2 przed SL)") };
}

/** K4: komunikat w zakładce STREFY, gdy bot nie ma stref wybranego TF M1–M30 (nie liczone / błąd / brak danych) – stan z API, bez zgadywania.
 *  Dla TF poza M1–M30 → null (komunikat wzorca). Strefy nieaktualne (odtworzone po restarcie, błąd danych) → ostrzeżenie obok stref. */
export function zonesMsgVM(resp: any, tf: string): string | null {
  const T = resp?.timeframes?.[tf];
  if (!resp) return `Strefy ${tf}: brak odpowiedzi API.`;
  if (!T) return null;
  const st = T.status || {};
  if (T.computed === false) {
    const why = st.status === "IDLE" || !st.status ? "bot nie liczył stref" : `${st.status_pl || st.status}${st.reason ? " – " + st.reason : ""}`;
    return `Strefy ${tf}: ${why}. Uruchom w Ustawieniach → Strefy rynkowe (Przelicz / LIVE). Nic nie jest przenoszone z innego interwału.`;
  }
  return T.stale ? `Strefy ${tf} nieaktualne (${st.status_pl || st.status || "odtworzone po restarcie"}) – przelicz w Ustawieniach → Strefy rynkowe.` : null;
}

/** K5: profil widocznego zakresu z GET /api/v1/svp/visible (PMW-SVP-1 VISIBLE) → kształt portu (hist = [indeks binu, waga], czasy w ms).
 *  RATE_LIMITED / błąd → null (renderer zostawia poprzedni wynik API dla tego samego zakresu albo nic nie rysuje). */
export function svpVisibleVM(r: any): any | null {
  if (!r || !r.contract || !Array.isArray(r.histogram) || !(r.bin_size > 0)) return null;
  const bin = +r.bin_size;
  return { ...r, start: ms(r.start), end: ms(r.end), as_of: ms(r.as_of), known_at: ms(r.known_at),
    hist: r.histogram.map((h: any) => [Math.round(+h.lo / bin), +h.weight] as [number, number]) };
}

/* ---------- CHARTS · HEATMAPA (mapa płynności w stylu Bookmap) – model widoku; tylko GET, brak danych = stan pusty ---------- */
export type HeatCol = { t: number; t1: number; n: number; bid: number | null; ask: number | null; cells: [number, number][] };
export type HeatBubble = { t: number; p: number; q: number; side: "BUY" | "SELL" | "UNKNOWN" };
export type HeatDom = { t: number; age: number | null; fresh: boolean; bids: [number, number][]; asks: [number, number][] };
export type HeatVM = {
  src: "MT5" | "CRYPTO"; status: "READY" | "STALE" | "NO_DATA" | "ERROR"; reason: string | null; symbol: string | null;
  t0: number; t1: number; now: number; step: number; ncols: number; fill: number; row: number; cols: HeatCol[]; ref: number | null; snapshots: number;
  dom: HeatDom | null; bars: Candle[]; bubbles: HeatBubble[]; trades: { status: string; reason: string | null }; source: string; quality: string;
};
const pairs = (a: any): [number, number][] => (Array.isArray(a) ? a : [])
  .map((x: any) => [num(x?.[0]), num(x?.[1])] as [number | null, number | null])
  .filter((x): x is [number, number] => x[0] != null && x[1] != null && x[1] > 0);
/** Wartość odniesienia jasności: 97. percentyl wielkości komórek w oknie (jedna wielka ściana nie gasi reszty mapy). */
export function heatRef(cols: HeatCol[]): number | null {
  const v = cols.flatMap((c) => c.cells.map((x) => x[1])).sort((a, b) => a - b);
  return v.length ? v[Math.floor(0.97 * (v.length - 1))] : null;
}
const domVM = (d: any): HeatDom | null => {
  const bids = pairs(d?.bids).sort((a, b) => b[0] - a[0]), asks = pairs(d?.asks).sort((a, b) => a[0] - b[0]);
  return bids.length || asks.length ? { t: ms(d?.t) ?? 0, age: num(d?.age_s), fresh: d?.fresh !== false, bids, asks } : null;
};
/** GET /api/v1/orderflow/mt5/heatmap – archiwum arkusza MT5 bota (czasy w s → ms). */
export function heatVM(r: any): HeatVM {
  const cols: HeatCol[] = (r?.columns || []).map((c: any) => ({ t: ms(c?.t), t1: ms(c?.t1), n: num(c?.n) ?? 0, bid: num(c?.bid), ask: num(c?.ask), cells: pairs(c?.cells) }))
    .filter((c: any) => c.t != null && c.t1 != null && c.cells.length).sort((a: HeatCol, b: HeatCol) => a.t - b.t);
  const st = ["READY", "STALE", "NO_DATA"].includes(r?.status) ? r.status : "NO_DATA";
  return { src: "MT5", status: cols.length ? st : "NO_DATA", reason: r?.reason ?? (cols.length ? null : "Brak danych arkusza"), symbol: r?.symbol ?? null,
    t0: ms(r?.t0) ?? 0, t1: ms(r?.t1) ?? 0, now: ms(r?.now ?? r?.t1) ?? 0, step: (num(r?.step_s) ?? 0) * 1000, ncols: num(r?.cols) ?? cols.length, fill: 1,
    row: num(r?.row_size) ?? 0, cols, ref: heatRef(cols), snapshots: num(r?.snapshots) ?? 0, dom: domVM(r?.dom), bars: candlesVM({ bars: r?.bars }), bubbles: [],
    trades: { status: r?.trades?.status || "NOT_AVAILABLE", reason: r?.trades?.reason ?? null }, source: r?.source || "MT5", quality: r?.quality || "" };
}
/** BTC: GET /api/v1/orderflow/CRYPTO/workspace daje JEDEN bieżący arkusz – kolumny składane w przeglądarce od otwarcia widoku
 *  (kubełek siatki = średnia, brak archiwum), bąble z ledgera transakcji; strona agresora bez weryfikacji = UNKNOWN (neutralne). */
export function heatFromWorkspace(prev: HeatVM | null, r: any, nowMs: number, winSec: number, maxCols = 240, pollMs = 2000): HeatVM {
  const step = Math.max((winSec * 1000) / maxCols, pollMs), ncols = Math.round((winSec * 1000) / step);   // kubełek ≥ okres odpytywania
  const row = num(r?.heatmap?.row_size) ?? 0, t0 = nowMs - winSec * 1000;
  const keep = prev && prev.src === "CRYPTO" && prev.row === row && prev.step === step ? prev.cols.filter((c) => c.t1 > t0) : [];
  const dom = domVM({ ...(r?.dom || {}), t: nowMs / 1000, age_s: 0 });
  const raw = (r?.heatmap?.columns || [])[0]?.cells || {};
  const cells = Object.entries(raw).map(([p, q]) => [num(p), num(q)] as [number | null, number | null])
    .filter((x): x is [number, number] => x[0] != null && x[1] != null && x[1] > 0).sort((a, b) => a[0] - b[0]);
  let cols = keep.slice();
  if (cells.length && row > 0) {
    const i = Math.floor(nowMs / step), last = cols[cols.length - 1];
    const col: HeatCol = { t: i * step, t1: (i + 1) * step, n: 1, bid: dom?.bids[0]?.[0] ?? null, ask: dom?.asks[0]?.[0] ?? null, cells };
    if (last && last.t === col.t) {                                       // ten sam kubełek: średnia (brak poziomu = 0)
      const m = new Map<number, number>(last.cells.map(([p, q]) => [p, q * last.n]));
      for (const [p, q] of cells) m.set(p, (m.get(p) ?? 0) + q);
      cols[cols.length - 1] = { ...col, n: last.n + 1, cells: [...m.entries()].map(([p, s]) => [p, s / (last.n + 1)] as [number, number]).sort((a, b) => a[0] - b[0]) };
    } else cols.push(col);
  }
  const verified = r?.side_semantics?.status === "VERIFIED";
  const bubbles: HeatBubble[] = (r?.bubbles || []).map((b: any) => ({ t: ms(b?.ts), p: num(b?.price), q: num(b?.size),
    side: verified && (b?.aggressor === "BUY" || b?.aggressor === "SELL") ? b.aggressor : "UNKNOWN" }))
    .filter((b: any) => b.t != null && b.p != null && b.q != null && b.q > 0 && b.t >= t0);
  return { src: "CRYPTO", status: cols.length ? "READY" : "NO_DATA", reason: cols.length ? null : "Brak arkusza dostawcy", symbol: r?.instrument_id ?? null,
    t0, t1: nowMs + step, now: nowMs, step, ncols, fill: 2, row, cols, ref: heatRef(cols), snapshots: cols.reduce((a, c) => a + c.n, 0), dom, bars: [], bubbles,
    trades: { status: bubbles.length ? (verified ? "READY" : "NEUTRAL") : "NO_DATA", reason: verified ? null : "strona agresora niezweryfikowana u dostawcy – bąble neutralne" },
    source: "HYPERLIQUID · " + (r?.instrument_id || "BTC") + " (nie symbol MT5)", quality: "arkusz odpytywany co 2 s · historia od otwarcia widoku (bez archiwum)" };
}
/** Błąd GET → stan z powodem z API (detail), nigdy pusta mapa udająca brak płynności. */
export function heatError(e: any, src: "MT5" | "CRYPTO"): HeatVM {
  let reason = String(e?.message || e || "błąd");
  try { const j = JSON.parse(reason); reason = j?.detail || j?.error || reason; } catch { /* tekst */ }
  if (src === "CRYPTO") reason = "Hyperliquid: " + reason;
  return { src, status: "ERROR", reason: reason.slice(0, 200), symbol: null, t0: 0, t1: 0, now: 0, step: 0, ncols: 0, fill: 1, row: 0, cols: [], ref: null, snapshots: 0,
    dom: null, bars: [], bubbles: [], trades: { status: "NO_DATA", reason: null }, source: src, quality: "" };
}
