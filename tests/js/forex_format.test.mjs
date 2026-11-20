// 1.42 E8 §5(h): adaptery / etykiety ekranów FOREX dla pustych i niepełnych odpowiedzi API -> stany puste, nigdy liczba wymyślona.
import assert from "node:assert/strict";
import { fmt, sgn, pnc, fmtTime, ts, chanceLabel } from "../../frontend/src/features/forex/format.ts";

for (const v of [null, undefined, NaN, Infinity]) { assert.equal(fmt(v), "—"); assert.equal(sgn(v), "—"); }
assert.equal(pnc(null), ""); assert.equal(pnc(0), ""); assert.equal(pnc(2), "pos"); assert.equal(pnc(-1), "neg");
assert.equal(fmt(-1.5, 1).startsWith("−"), true);
assert.equal(sgn(2, 0), "+2");
assert.equal(fmtTime(null), "—"); assert.equal(fmtTime("nie-data"), "—");
assert.equal(ts(null), 0); assert.equal(ts("x"), 0); assert.equal(ts(1700000000), 1700000000000);
// % tylko ze skalibrowanego prawdopodobieństwa
assert.deepEqual(chanceLabel(null), { pct: null, label: "brak modelu" });
assert.equal(chanceLabel({ unit: "probability", calibration: { status: "UNCALIBRATED" }, result: { probability: 0.7 } }).pct, null);
assert.equal(chanceLabel({ unit: "probability", calibration: { status: "CALIBRATED" }, result: {} }).pct, null);
assert.equal(chanceLabel({ unit: "price", result: { probability: 0.9 } }).pct, null);
assert.equal(chanceLabel({ unit: "probability", calibration: { status: "CALIBRATED_DEV" }, result: { probability: 0.62 } }).pct, 0.62);
console.log("forex format OK");
