// Node check of frontend/src/features/towers/chartlab/calc.ts (run: node --experimental-strip-types tests/js/chartlab_calc.test.mjs)
import assert from "node:assert/strict";
const C = await import("../../frontend/src/features/towers/chartlab/calc.ts");
const t0 = Date.UTC(2026, 10, 9, 0, 0) / 1000;
const raw = [];
let p = 100;
for (let i = 0; i < 300; i++) {                      // M5 bars over 25 hours, deterministic walk with one strong impulse
  const d = i >= 150 && i < 155 ? 3 : Math.sin(i / 7) * 0.4;
  const o = p, c = p + d;
  raw.push({ open_utc: new Date((t0 + i * 300) * 1000).toISOString(), o, h: Math.max(o, c) + 0.2, l: Math.min(o, c) - 0.2, c, tv: 10 + (i % 5), rv: 0, closed: true });
  p = c;
}
raw.push({ open_utc: null, o: 1, h: 1, l: 1, c: 1, tv: 1 });  // no UTC time -> skipped
const bars = C.toBars(raw);
assert.equal(bars.length, 300);
assert.equal(C.volumeSource(raw), "tick_volume");
// Heikin Ashi: close = OHLC/4, open = average of the previous HA body
const ha = C.heikinAshi(bars);
assert.ok(Math.abs(ha[5].c - (bars[5].o + bars[5].h + bars[5].l + bars[5].c) / 4) < 1e-9);
assert.ok(Math.abs(ha[5].o - (ha[4].o + ha[4].c) / 2) < 1e-9);
// EMA first value = SMA of the first n closes; causal (prefix gives the same values)
const e = C.ema(bars, 10), e2 = C.ema(bars.slice(0, 100), 10);
assert.ok(Math.abs(e[0].value - bars.slice(0, 10).reduce((s, b) => s + b.c, 0) / 10) < 1e-9);
assert.deepEqual(e.slice(0, e2.length), e2);
// RSI in 0..100, causal
const r = C.rsi(bars, 14);
assert.ok(r.every((x) => x.value >= 0 && x.value <= 100));
assert.deepEqual(r.slice(0, 50), C.rsi(bars.slice(0, 64), 14).slice(0, 50));
// ATR > 0; BB upper > mid > lower
assert.ok(C.atr(bars, 14).every((x) => x.value > 0));
const bb = C.bollinger(bars, 20); assert.ok(bb.up.every((x, i) => x.value >= bb.mid[i].value && bb.mid[i].value >= bb.lo[i].value));
// MACD histogram = macd - signal
const m = C.macd(bars); const sig = new Map(m.signal.map((x) => [x.time, x.value]));
for (const h of m.hist) assert.ok(Math.abs(h.value - (m.macd.find((x) => x.time === h.time).value - sig.get(h.time))) < 1e-9);
// VWAP resets at 00:00 UTC
const vw = C.vwapDaily(bars); const nextDay = bars.findIndex((b) => b.time >= t0 + 86400);
assert.ok(Math.abs(vw[nextDay].value - (bars[nextDay].h + bars[nextDay].l + bars[nextDay].c) / 3) < 1e-9);
// sessions: London 07-16 UTC of the LAST day with London bars
const lon = C.lastSessionBars(bars, "LONDON");
assert.ok(lon.length > 0 && lon.every((b) => { const h = new Date(b.time * 1000).getUTCHours(); return h >= 7 && h < 16; }));
assert.ok(lon.every((b) => Math.floor(b.time / 86400) === Math.floor(lon[0].time / 86400)));
assert.equal(C.lastSessionBars(bars, "ALL").length, 300);
// volume profile: total volume conserved, POC inside VA, VA holds >= 70 %
const pr = C.volumeProfile(bars, 48, 0.7);
const tot = bars.reduce((s, b) => s + b.v, 0);
assert.ok(Math.abs(pr.bins.reduce((s, b) => s + b.vol, 0) - tot) < 1e-6 && Math.abs(pr.total - tot) < 1e-6);
assert.ok(pr.val <= pr.poc && pr.poc <= pr.vah);
const inVa = pr.bins.filter((b) => b.lo >= pr.val - 1e-9 && b.hi <= pr.vah + 1e-9).reduce((s, b) => s + b.vol, 0);
assert.ok(inVa >= tot * 0.7 - 1e-6);
assert.ok(pr.bins.every((b) => Math.abs(b.up + b.down - b.vol) < 1e-9));
assert.equal(C.volumeProfile(bars.slice(0, 1)), null);
// biggest impulse: the forced +3/bar run at 150..154 is found for n=5
const imp = C.biggestImpulse(bars, 5);
assert.equal(imp.dir, "BUY"); assert.equal(imp.from, bars[150].time); assert.equal(imp.to, bars[154].time);
assert.ok(Math.abs(imp.delta - 15) < 1e-9);
for (const n of [3, 8, 12]) { const x = C.biggestImpulse(bars, n); assert.ok(x && x.from <= bars[154].time && x.to >= bars[150].time, n); }
assert.equal(C.biggestImpulse(bars.slice(0, 2), 3), null);
// SMC: BOS / CHoCH only after a confirmed swing, event level = a swing that existed before the event
const s = C.smc(bars, 2);
assert.ok(s.events.length > 0);
for (const ev of s.events) assert.ok([...s.highs, ...s.lows].some((q) => q.value === ev.level && q.time < ev.time));
console.log("chartlab calc OK:", { bars: bars.length, poc: pr.poc.toFixed(2), events: s.events.length });
