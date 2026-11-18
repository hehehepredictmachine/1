// CHARTS 1:1 – K1: adaptery API → model widoku (D1 §3) na kształtach odpowiedzi z K0 (dane syntetyczne, bez danych rachunku).
import assert from "node:assert/strict";
import { candlesVM, basketSignalVM, legacySignalVM, zonesVM, probVM, kronosVM, chartStatus } from "../../frontend/src/features/forex/screens/charts/chartsAdapters.ts";

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

// status MT5
assert.equal(chartStatus({ connection: { state: "CONNECTED" } }), "live");
assert.equal(chartStatus({ connection: { state: "CONNECTED" }, dq: { status: "STALE" } }), "stale");
assert.equal(chartStatus({ connection: { state: "DISCONNECTED" } }), "offline");
assert.equal(chartStatus({}), "loading");
console.log("charts adapters OK");
