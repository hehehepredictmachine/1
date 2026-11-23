// 1.46: silnik FOREX bez WebGL (atrapa) ma pełne API, którego używają ekrany SIGNALS / MODELS / ROI (setScreenData, nodeAt, setReduced ...).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mountForex } from "../../frontend/src/features/forex/engine/forexEngine.ts";

const canvas = { getContext: () => null, addEventListener() {} };
const root = { querySelector: (s) => (s === "#c" ? canvas : null), querySelectorAll: () => [], dataset: {} };
let noGl = false;
const stub = mountForex(root, { onNoWebGL: () => { noGl = true; } });
assert.equal(noGl, true);
// every method of the real API object (const api={...}) must exist on the stub
const src = readFileSync(new URL("../../frontend/src/features/forex/engine/forexEngine.ts", import.meta.url), "utf8");
const body = src.slice(src.indexOf("const api={"), src.indexOf("try{setup();resize();"));
const names = [...new Set([...body.matchAll(/(?:^|[,{\s])([a-zA-Z]+)(?:\(|:)/g)].map((m) => m[1]))].filter((n) =>
  ["dispose", "setPanel", "result", "stale", "openSub", "closeSub", "testSeek", "testSub", "surface", "setScreenData", "nodeAt", "setReduced", "state"].includes(n));
assert.ok(names.length >= 12, names.join(","));
for (const n of names) assert.equal(typeof stub[n], "function", `atrapa nie ma metody ${n}`);
stub.setScreenData(0, { nodes: [] });
assert.equal(stub.nodeAt(0, 1, 1), undefined);
stub.setReduced(true);
console.log("forex_engine_stub OK", names.length);
