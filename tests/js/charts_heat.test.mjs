// CHARTS · HEATMAPA – adaptery API → model widoku i skala kolorów (bez przeglądarki). Uruchamiane przez tests/test_charts_heatmap.py.
import assert from "node:assert/strict";
import { heatVM, heatFromWorkspace, heatError, heatRef } from "../../frontend/src/features/forex/screens/charts/chartsAdapters.ts";
import { heatLevel, heatLut } from "../../frontend/src/features/forex/screens/charts/chartsHeat.ts";

// GET /api/v1/orderflow/mt5/heatmap – czasy w s → ms, komórki bez liczby / ≤ 0 odrzucone, kolumna bez komórek odrzucona
const r = { status: "READY", reason: null, symbol: "XAUUSD-", t0: 1000, t1: 1060, now: 1058.5, cols: 20, step_s: 3, row_size: 0.1, snapshots: 5,
  columns: [{ t: 1003, t1: 1006, n: 3, bid: 3460.1, ask: 3460.2, cells: [[3460.0, 2], [3460.1, "x"], [3460.2, 0], [3460.3, 4]] },
            { t: 1000, t1: 1003, n: 2, bid: 3460.0, ask: 3460.1, cells: [[3459.9, 1]] }, { t: 1009, t1: 1012, n: 1, bid: null, ask: null, cells: [] }],
  dom: { t: 1058, age_s: 0.5, fresh: true, bids: [[3460.0, 1], [3460.1, 3]], asks: [[3460.3, 2], [3460.2, 5]] },
  bars: [{ open_utc: "2026-11-24T15:40:00Z", o: 1, h: 2, l: 0.5, c: 1.5, tv: 40, closed: true }],
  trades: { status: "NOT_AVAILABLE", reason: "brak taśmy" }, source: "MT5_MARKET_BOOK(broker)", quality: "SAMPLED(1s)" };
const v = heatVM(r);
assert.equal(v.src, "MT5"); assert.equal(v.status, "READY");
assert.deepEqual(v.cols.map((c) => c.t), [1000000, 1003000]);                     // posortowane, pusta kolumna usunięta (przerwa, nie zero)
assert.deepEqual(v.cols[1].cells, [[3460.0, 2], [3460.3, 4]]);
assert.equal(v.step, 3000); assert.equal(v.ncols, 20); assert.equal(v.row, 0.1); assert.equal(v.now, 1058500); assert.equal(v.fill, 1);
assert.deepEqual(v.dom.bids, [[3460.1, 3], [3460.0, 1]]); assert.deepEqual(v.dom.asks, [[3460.2, 5], [3460.3, 2]]);   // najlepszy poziom pierwszy
assert.equal(v.bars.length, 1); assert.equal(v.bars[0].v, 40);
assert.equal(v.trades.status, "NOT_AVAILABLE"); assert.deepEqual(v.bubbles, []);              // arkusz brokera: bez bąbli
assert.equal(v.ref, 2);                                                            // [1, 2, 4] → indeks floor(0.97 · 2) = 1
const e = heatVM({ status: "NO_DATA", reason: "market_book_add odrzucone – brak DOM dla symbolu", columns: [] });
assert.equal(e.status, "NO_DATA"); assert.match(e.reason, /brak DOM/); assert.equal(heatVM(null).status, "NO_DATA");
assert.equal(heatVM({ status: "READY", columns: [] }).status, "NO_DATA");                      // READY bez kolumn nie udaje danych

// 97. percentyl – jedna ściana nie gasi skali
assert.equal(heatRef([{ cells: [...Array(99)].map((_, i) => [i, 1]).concat([[100, 500]]) }]), 1);
assert.equal(heatRef([]), null);

// BTC: workspace = jeden arkusz; kolumny składane, ten sam kubełek = średnia (brak poziomu = 0), stare poza oknem odpadają
const ws = (cells, bubbles = [], verified = false) => ({ instrument_id: "BTC", dom: { bids: [[100, 1]], asks: [[110, 2]] }, heatmap: { row_size: 10, columns: [{ t: 0, cells }] },
  bubbles, side_semantics: { status: verified ? "VERIFIED" : "NOT_VERIFIED" } });
let h = heatFromWorkspace(null, ws({ "100.0": 4, "110.0": 2 }), 1_000_000, 300);
assert.equal(h.src, "CRYPTO"); assert.equal(h.step, 2000); assert.equal(h.ncols, 150); assert.equal(h.fill, 2);   // kubełek ≥ okres odpytywania 2 s
assert.equal(h.cols.length, 1); assert.deepEqual(h.cols[0].cells, [[100, 4], [110, 2]]); assert.equal(h.cols[0].bid, 100);
h = heatFromWorkspace(h, ws({ "100.0": 2 }), 1_000_500, 300);                      // ten sam kubełek 2 s
assert.equal(h.cols.length, 1); assert.equal(h.cols[0].n, 2); assert.deepEqual(h.cols[0].cells, [[100, 3], [110, 1]]);
h = heatFromWorkspace(h, ws({ "120.0": 1 }), 1_002_100, 300);
assert.equal(h.cols.length, 2);
h = heatFromWorkspace(h, ws({ "120.0": 1 }), 1_400_000, 300);                      // > 5 min później – poprzednie kolumny poza oknem
assert.equal(h.cols.length, 1); assert.equal(h.snapshots, 1);
const tr = [{ ts: 1399.5, price: 105, size: 2, aggressor: "BUY" }, { ts: 1000, price: 105, size: 9, aggressor: "SELL" }, { ts: 1399.9, price: 105, size: 0, aggressor: "SELL" }];
const nv = heatFromWorkspace(null, ws({ "100.0": 1 }, tr), 1_400_000, 300);
assert.deepEqual(nv.bubbles, [{ t: 1_399_500, p: 105, q: 2, side: "UNKNOWN" }]);   // niezweryfikowana strona → neutralne; poza oknem / zero – odrzucone
assert.equal(nv.trades.status, "NEUTRAL");
assert.equal(heatFromWorkspace(null, ws({ "100.0": 1 }, tr, true), 1_400_000, 300).bubbles[0].side, "BUY");
assert.equal(heatFromWorkspace(null, ws({}), 1_400_000, 300).status, "NO_DATA");

// błąd GET → powód z API
const er = heatError(new Error('{"detail":"UNKNOWN_INSTRUMENT: BTC"}'), "CRYPTO");
assert.equal(er.status, "ERROR"); assert.equal(er.reason, "Hyperliquid: UNKNOWN_INSTRUMENT: BTC"); assert.deepEqual(er.cols, []);
assert.equal(heatError(new Error("HTTP 503"), "MT5").reason, "HTTP 503");

// skala: q / ref · kontrast, obcięta do 0..1; palety z końcami jak w specyfikacji
assert.equal(heatLevel(2, 4, 1), 0.5); assert.equal(heatLevel(8, 4, 1), 1); assert.equal(heatLevel(2, 4, 1.6), 0.8); assert.equal(heatLevel(0, 4, 1), 0);
const lc = heatLut("classic"), la = heatLut("apollo");
assert.deepEqual([...lc.slice(0, 3)], [8, 20, 48]); assert.deepEqual([...lc.slice(765, 768)], [235, 55, 35]);
assert.deepEqual([...la.slice(765, 768)], [236, 214, 150]);
console.log("charts heat OK");
