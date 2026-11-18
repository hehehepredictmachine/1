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
    et: ms(x.outcome_at), inv: num(su.invalidation), rg: su.regime?.state ?? su.regime ?? null, ro: typeof x.routed_auto === "boolean" ? x.routed_auto : (typeof su.routed_auto === "boolean" ? su.routed_auto : null),
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
    sid: x.strategy_id, src: "LEGACY", tf: x.timeframe, t: ms(x.created_at) as number, sd: x.action === "SELL" ? -1 : 1, e, sl,
    tp: (x.take_profits || []).map(num).filter((v: number | null): v is number => v != null), res, hit, et: ms(x.closed_at),
    inv: num(d.invalidation_level), rg: d.regime ?? null, tb: d.exit_rules ?? null, sc: num(x.setup_score),
    why: d.reason_codes || [], miss: d.missing_confirmations || [], trg: x.trigger ?? null,
  };
}

/** Strefy bota tylko z wybranego TF (GET /api/v1/market-zones → timeframes[tf]); v = 1 dla stref wybranych przez silnik. */
export function zonesVM(resp: any, tf: string): Zone[] | null {
  const T = resp?.timeframes?.[tf];
  if (!T) return null;
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
    : (resp?.target?.reason || status?.status_pl || "BRAK PROGNOZY").toString().toUpperCase();
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

