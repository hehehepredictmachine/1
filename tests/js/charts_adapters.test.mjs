// CHARTS 1:1 – K1: adaptery API → model widoku (D1 §3) na kształtach odpowiedzi z K0 (dane syntetyczne, bez danych rachunku).
import assert from "node:assert/strict";
import { candlesVM, basketSignalVM, legacySignalVM, zonesVM, probVM, kronosVM, iprofVM, chartStatus, basketMetaVM, legacyMetaVM, shMetaVM, statesVM, shSignalVM, cardProbsVM } from "../../frontend/src/features/forex/screens/charts/chartsAdapters.ts";

// /api/v1/candles
const c = candlesVM({ bars: [
  { t_raw: 1795016400, open_utc: "2026-11-18T12:40:00Z", o: 3459.6, h: 3460.1, l: 3459.1, c: 3459.9, tv: 120, closed: false },
  { t_raw: 1795016100, open_utc: "2026-11-18T12:35:00Z", o: 3459.5, h: 3460.0, l: 3459.1, c: 3459.5, tv: 835, closed: true },
  { open_utc: null, o: 1, h: 1, l: 1, c: 1 }, { open_utc: "2026-11-18T12:30:00Z", o: "x", h: 1, l: 1, c: 1 } ] });
assert.equal(c.length, 2);                                               // bez czasu / bez liczby → odrzucona, nigdy zgadywana
assert.deepEqual(c[0], { t: Date.parse("2026-11-18T12:35:00Z"), o: 3459.5, h: 3460.0, l: 3459.1, c: 3459.5, v: 835, closed: true });
assert.equal(c[1].closed, false);
assert.deepEqual(candlesVM(null), []); assert.deepEqual(candlesVM({ status: "NO_SYMBOL", bars: [] }), []);

// /api/v1/baskets/signals
const bk = { signal_id: "EV-1|FX_SCALP_02", event_id: "EV-1", strategy_id: "FX_SCALP_02", basket_id: "FX_SCALP", profile_id: "FOREX_MT5", tf: "M5", side: "LONG",
  created_at: 1794747910, bar_t: 1794747900, status: "CLOSED", role: "PRIMARY", outcome_kind: "TP1", outcome_at: 1794750300,
  plan: { plan_type: "PositionPlan", side: "LONG", entry_ref: 4054.93, sl: 4053.67, targets: [{ price: 4056.6, weight: .5 }, { price: 4059.0, weight: .5 }], timeout_bars: 8 },
  setup: { invalidation: 4053.8, event: { type: "BB_REENTRY" }, target: 4056.6, regime: { state: "RANGE" } }, scores: {} };
const b = basketSignalVM(bk);
assert.deepEqual([b.sid, b.src, b.tf, b.t, b.sd, b.e, b.sl, b.tp, b.res, b.hit, b.et, b.inv, b.rg, b.ev, b.tb, b.to],
  ["FX_SCALP_02", "BASKET", "M5", 1794747900000, 1, 4054.93, 4053.67, [4056.6, 4059.0], "TP1", ["TP1"], 1794750300000, 4053.8, "RANGE", "BB_REENTRY", "STRUKTURA", 8]);
assert.equal(b.ro, null);                                                // brak w API → null (K3 dopisze zapis)
assert.equal(basketSignalVM({ ...bk, status: "ACTIVE", outcome_kind: null }).res, "OTWARTY");
assert.equal(basketSignalVM({ ...bk, profile_id: "CRYPTO_FOMO_PERPS" }), null);
assert.equal(basketSignalVM({ ...bk, plan: { ...bk.plan, plan_type: "FixedExpiryPlan" } }), null);
assert.equal(basketSignalVM({ ...bk, routed_auto: true }).ro, true);

// /api/v1/bot-signals (S01–S12)
const lg = { signal_id: "x", created_at: "2026-11-13T16:15:00Z", strategy_id: "S11", timeframe: "M15", action: "BUY", entry_price: 4018.52, stop_loss: 4016.79,
  take_profits: [4022.86], status: "WIN", tp_hit: 1, closed_at: "2026-11-13T17:45:00Z", setup_score: 95, trigger: "zamknięcie świecy",
  detail: { invalidation_level: 4016.79, regime: "TREND_UP", reason_codes: ["EMA20>EMA50"], missing_confirmations: ["EXTRA"], exit_rules: ["RR_2.5"] } };
const l = legacySignalVM(lg);
assert.deepEqual([l.src, l.sd, l.res, l.hit, l.sc, l.why, l.miss, l.trg, l.tp], ["LEGACY", 1, "TP1", ["TP1"], 95, ["EMA20>EMA50"], ["EXTRA"], "zamknięcie świecy", [4022.86]]);
assert.equal(legacySignalVM({ ...lg, status: "LOSS", tp_hit: 1 }).res, "SL_PO_TP1");
assert.equal(legacySignalVM({ ...lg, status: "LOSS", tp_hit: 0 }).res, "SL");
assert.equal(legacySignalVM({ ...lg, status: "TIMEOUT", tp_hit: 2 }).res, "TIMEOUT_PO_TP2");
assert.equal(legacySignalVM({ ...lg, status: "OPEN" }).res, "OTWARTY");
assert.equal(legacySignalVM({ ...lg, strategy_id: "SH_SCALPING" }), null);      // nie S01–S12

// /api/v1/market-zones → tylko wybrany TF
const zr = { timeframes: { M5: { zones: [{ id: "z1", type: "FVG_BULL", lower: 4048.5, upper: 4051.0, state: "ACTIVE", origin_time: "2026-11-17T14:10:00Z",
  invalidated_at: null, expired_at: null, quality: { score: 76.3 }, reason: "luka" }, { id: "z2", type: "SR_SUPPORT", lower: 1, upper: 2, state: "INVALIDATED",
  origin_time: "2026-11-17T10:00:00Z", invalidated_at: "2026-11-17T11:00:00Z", quality: {}, reason: null }], visible: ["z1"] } } };
const z = zonesVM(zr, "M5");
assert.deepEqual(z[0], { ty: "FVG_BULL", lo: 4048.5, up: 4051.0, st: "ACTIVE", t0: Date.parse("2026-11-17T14:10:00Z"), t1: null, q: 76.3, why: "luka", v: 1 });
assert.equal(z[1].v, 0); assert.equal(z[1].q, null); assert.equal(z[1].t1, Date.parse("2026-11-17T11:00:00Z"));
assert.equal(zonesVM(zr, "H1"), null);                                  // H1: brak stref – nic z innego TF

// szanse modeli – % tylko skalibrowane prawdopodobieństwo
assert.equal(probVM({ unit: "probability", calibration: { status: "CALIBRATED_DEV" }, result: { probability: .58 }, state: "READY", task: "T" }, "A").v, .58);
assert.equal(probVM({ unit: "probability", calibration: { status: "UNCALIBRATED" }, result: { probability: .9 }, state: "READY" }, "A").v, null);
assert.equal(probVM({ unit: "price", calibration: { status: "CALIBRATED" }, result: { probability: .9 } }, "A").v, null);
assert.equal(probVM(null, "A").state, "NO_DATA");

// Kronos – brak prognozy = stan, nie symulacja
const k0 = kronosVM({ target: { state: "BLOCK" }, forecast: null }, "M5");
assert.deepEqual([k0.state, k0.forecast, k0.candles], ["BLOCK", null, []]);
const k1 = kronosVM({ is_current: true, context: [{ open_utc: "2026-11-18T10:00:00Z", o: 1, h: 2, l: .5, c: 1.5, tv: 3 }],
  forecast: { direction: "UP", last_close: 1.5, pred_close_h: 2, delta_price: .5, delta_pct: 33, neutral_band: .1, horizon_bars: 12, created_at: "2026-11-18T10:05:00Z" } }, "M5");
assert.deepEqual([k1.state, k1.forecast.horizon, k1.forecast.paths, k1.forecast.is_current, k1.candles.length], ["READY", 12, [], true, 1]);

// K2: Kronos – rola, interwały pracy, stan „niezainstalowany” (bez symulacji)
const kNI = kronosVM(null, "M5", { status: "NOT_INSTALLED" });
assert.deepEqual([kNI.state, kNI.forecast, kNI.emptyTxt], ["NOT_INSTALLED", null, "KRONOS NIEZAINSTALOWANY – 33_KRONOS_INSTALUJ.bat"]);
assert.equal(kronosVM(null, "H4", { status: "READY" }).emptyTxt, "TIMEFRAME_NOT_ALLOWED");
const kA = kronosVM({ forecast: null }, "M5", { status: "READY", decision_use: { M5: "ASSIST" }, settings: { timeframes: ["M5", "M15"] } });
assert.ok(kA.role.startsWith("ASSIST")); assert.deepEqual(kA.on, { M1: false, M5: true, M15: true, M30: false, H1: false });
assert.ok(kronosVM({ forecast: null }, "M5", { status: "READY" }).role.startsWith("SHADOW"));

// K2: profil wskaźników silnika z /api/v1/candles
assert.deepEqual(iprofVM({ indicators: { lines: [{ id: "EMA9" }, { id: "EMA21" }, { id: "BB20_UP" }], panels: { rsi: { period: 9 }, macd: { signal_ma: "SMA" } } } }),
  { ema: [9, 21], rsi: 9, sig: "SMA" });
assert.deepEqual(iprofVM({ indicators: { lines: [{ id: "EMA20" }, { id: "BB_MID" }], panels: { rsi: { period: 14 }, macd: {} } } }), { ema: [20, null], rsi: 14, sig: "SMA" });
assert.equal(iprofVM({ indicators: { lines: [], panels: { macd: { signal_ma: "EMA" } } } }).sig, "EMA");
assert.equal(iprofVM(null), null);

// K3: meta strategii
const bm = basketMetaVM({ strategies: [{ strategy_id: "FX_SMC_01", name: "Sweep", basket_id: "FX_SMC", signal_timeframe: "M5", context_timeframes: ["M15"], family_id: "f",
  correlation_group: "G", setup_rule: "s", trigger_rule: "t", cancellation_rule: "c", exit_policy_or_expiry_policy: "x", plan_type: "PositionPlan",
  parameter_schema: { tp_r: [2, 3] }, required_inputs: ["bid_ask"], kind: "SMC" }, { strategy_id: "CP_SMC_01", basket_id: "CP_SMC" }] });
assert.deepEqual(bm.FX_SMC[0], { id: "FX_SMC_01", nm: "Sweep", tf: "M5", ctx: ["M15"], fam: "f", grp: "G", setup: "s", trig: "t", cancel: "c", exit: "x",
  plan: "PositionPlan", tp_r: [2, 3], need: ["bid_ask"], kind: "SMC" });
assert.equal(bm.FX_SCALP.length, 0); assert.ok(!bm.CP_SMC);
const lm = legacyMetaVM({ strategies: [{ strategy_id: "S01", name: "TREND_PULLBACK", family: "TREND", setup_tfs: ["M5", "M15"], validation_status: "V", trade: false }], funnel: { S01: { OK: 3 } } });
assert.deepEqual(lm[0], { id: "S01", nm: "TREND_PULLBACK", fam: "TREND", tfs: ["M5", "M15"], val: "V", notrade: true, funnel: { OK: 3 } });
const sm = shMetaVM({ instruments: { XAUUSD: { status: "ROBOCZE", SCALPING: { tp_usd: [2.5, 3, 5], shares: [.5, .3, .2], be_after: "TP2", sl_min_usd: 1.5, sl_max_usd: 4,
  horizon_minutes: 30, position_max_minutes: 90, allow_regimes: ["TREND"] } }, BTC: { status: "NIEZWERYFIKOWANE – x" } } });
assert.deepEqual([sm.length, sm[0].id, sm[0].be, sm[0].sl_usd, sm[0].status.BTC], [1, "SH_SCALPING", "TP2", [1.5, 4], "NIEZWERYFIKOWANE – x"]);
// K3: stany – powód niedostępności z API
const bkr = { baskets: [{ basket_id: "FX_SMC", data_status: { "-": { state: "WAITING_FOR_DATA", reason: "profil jeszcze nie odczytał danych" } },
  strategies: [{ strategy_id: "FX_SMC_01", enabled: true, states: {} }, { strategy_id: "FX_SMC_02", enabled: false, states: {} }] }] };
assert.deepEqual(statesVM(bkr, "XAUUSD").FX_SMC_01, { st: {}, un: "profil jeszcze nie odczytał danych" });
assert.equal(statesVM(bkr, "XAUUSD").FX_SMC_02.un, "strategia wyłączona");
const bkr2 = { baskets: [{ basket_id: "FX_SMC", data_status: { XAUUSD: { state: "READY" } }, strategies: [{ strategy_id: "FX_SMC_01", states: { XAUUSD: { state: "NO_SETUP" } } }] }] };
assert.deepEqual(statesVM(bkr2, "XAUUSD").FX_SMC_01, { st: { NO_SETUP: 1 }, un: null });
const bkr3 = { baskets: [{ basket_id: "FX_SMC", data_status: { "XAUUSD-": { state: "READY" } }, strategies: [{ strategy_id: "FX_SMC_01", states: { "XAUUSD-": { state: "SIGNAL" } } }] }] };
assert.deepEqual(statesVM(bkr3, "XAUUSD", "XAUUSD-").FX_SMC_01, { st: { SIGNAL: 1 }, un: null });          // kontekst = symbol brokera
assert.equal(statesVM(bkr3, "BTC", "BTCUSD-").FX_SMC_01.un, "brak kontekstu BTC w profilu FOREX_MT5");
// K3: sygnał SH z poziomami zapisanymi w sygnale + wynik planu
const shr = { signal_id: "SH-1", strategy: "SCALPING", instrument: "XAUUSD", status: "READY", created_at: 1795009320, side: "BUY",
  levels: { side: "BUY", entry: 4050.5, sl: 4049, targets: [{ name: "TP1", price: 4053, share: .5 }, { name: "TP2", price: 4053.5, share: .3 }, { name: "TP3", price: 4055.5, share: .2 }],
    net_rr: 1.514, be_after: "TP2", horizon_minutes: 30 }, plan: null };
const sv = shSignalVM(shr);
assert.deepEqual([sv.sid, sv.src, sv.tf, sv.t, sv.sd, sv.e, sv.sl, sv.tp, sv.sh, sv.rr, sv.be, sv.hz, sv.res, sv.hit],
  ["SH_SCALPING", "SH", "M1", 1795009320000, 1, 4050.5, 4049, [4053, 4053.5, 4055.5], [.5, .3, .2], 1.514, "TP2", 30, "GOTOWY", []]);
assert.equal(shSignalVM({ ...shr, levels: null }), null);                       // stary zapis bez poziomów → brak markera
assert.equal(shSignalVM({ ...shr, plan: { state: "OPEN", tp_done: ["TP1"] } }).res, "OTWARTY");
assert.equal(shSignalVM({ ...shr, plan: { state: "CLOSED", tp_done: ["TP1", "TP2"], close_reason: "SL", closed_at: 1795010000 } }).res, "SL_PO_TP2");
assert.equal(shSignalVM({ ...shr, plan: { state: "CLOSED", tp_done: ["TP1", "TP2", "TP3"], close_reason: "TP3" } }).res, "TP3");
assert.equal(shSignalVM({ ...shr, status: "EXPIRED" }).res, "WYGASŁY");
// K3: szanse w karcie – tylko skalibrowane prawdopodobieństwo
const cp = cardProbsVM({ items: [{ task: "NET_R_POSITIVE_S01_S12", unit: "probability", calibration: { status: "CALIBRATED_DEV" }, result: { probability: .58 }, state: "READY", model_name: "champion" }] });
assert.equal(cp.win.v, .58); assert.deepEqual([cp.tp2.v, cp.tp2.state], [null, "NO_DATA"]);
assert.equal(cardProbsVM(null).win.state, "NO_DATA");
// K3: S01–S12 – czas świecy sygnału z detail.source_time; basket – reżim i routing AUTO z zapisu
assert.equal(legacySignalVM({ ...lg, detail: { ...lg.detail, source_time: "2026-11-13T16:00:00Z" } }).t, Date.parse("2026-11-13T16:00:00Z"));
const bro = basketSignalVM({ ...bk, setup: { ...bk.setup, regime: { regime: "TREND" }, routed_auto: false } });
assert.deepEqual([bro.rg, bro.ro], ["TREND", false]);

// status MT5
assert.equal(chartStatus({ connection: { state: "CONNECTED" } }), "live");
assert.equal(chartStatus({ connection: { state: "CONNECTED" }, dq: { status: "STALE" } }), "stale");
assert.equal(chartStatus({ connection: { state: "DISCONNECTED" } }), "offline");
assert.equal(chartStatus({}), "loading");
console.log("charts adapters OK");
