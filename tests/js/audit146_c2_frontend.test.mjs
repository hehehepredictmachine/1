// 1.46 audit (group C2_frontend, cross-file round): CHARTS data layer (chartsData.ts -> renderer view model), App.tsx (FOREX hand-off
// cancellation, retired OTC note, no dead onSettings prop), CinematicMenu props, Apollo23 labels on MODELS & BACKTEST and in Diagnostics,
// dead brand.ts export and the unread router.ts localStorage write - in Node, without a browser.
// Usage: node --experimental-strip-types --no-warnings tests/js/audit146_c2_frontend.test.mjs <case> [case ...]
// React components are rendered with the real react-dom/client into a minimal DOM stub (same stub as audit146_d_frontend_1); .ts/.tsx sources
// are transpiled with the project's own TypeScript; api.ts / telemetry.ts / store.tsx and the heavy children of App.tsx (CinematicMenu,
// ForexScene, TraderLifeGame, SystemBar, SystemDrawer, LicenseGate) are replaced by in-memory mocks.
// Every case prints "<case> OK" or "<case> FAIL: ..."; exit code 1 on any failure.
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire, registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FE = path.join(here, "..", "..", "frontend");
const SRC = path.join(FE, "src");
const req = createRequire(path.join(FE, "package.json"));
const ts = req("typescript");

// ---------------------------------------------------------------- module hooks: TS/TSX transpile, CSS / media stubs, mocks
const data = (src) => "data:text/javascript," + encodeURIComponent(src);
const MOCKS = {
  [path.join(SRC, "api.ts")]: data(`
    export class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
    export const initSession = (...a) => globalThis.__mock.initSession(...a);
    export const apiGet = (...a) => globalThis.__mock.apiGet(...a);
    export const apiSend = (...a) => globalThis.__mock.apiSend(...a);
    export const apiUpload = (...a) => globalThis.__mock.apiSend("UPLOAD", ...a);
    export class LiveSocket { constructor() {} start() {} stop() {} }`),
  [path.join(SRC, "telemetry.ts")]: data(`export const telemetry = { emit() {}, status() {}, subscribe() { return () => {}; } };`),
  [path.join(SRC, "store.tsx")]: data(`
    export const useStore = () => globalThis.__mock.store;
    export const StoreProvider = ({ children }) => children;`),
  // App.tsx children: only the props App passes matter here
  [path.join(SRC, "features", "cinematic", "CinematicMenu.tsx")]: data(`
    export default function CinematicMenu(p) { globalThis.__mock.cin = p; globalThis.__mock.cinRenders = (globalThis.__mock.cinRenders || 0) + 1; return null; }`),
  [path.join(SRC, "features", "forex", "ForexScene.tsx")]: data(`
    export const POSE_KEY = "pmw.forex.pose";
    export default function ForexScene(p) { globalThis.__mock.forex = p; return null; }`),
  [path.join(SRC, "features", "trader-life-game", "TraderLifeGame.tsx")]: data(`export default function TraderLifeGame() { return null; }`),
  [path.join(SRC, "features", "system", "SystemBar.tsx")]: data(`export function ExecStatus() { return null; } export function SystemIcons() { return null; }`),
  [path.join(SRC, "features", "system", "SystemDrawer.tsx")]: data(`export default function SystemDrawer(p) { globalThis.__mock.drawer = p; return null; }`),
  [path.join(SRC, "license", "LicenseGate.tsx")]: data(`
    export const useLicense = () => ({ st: null, refresh: async () => null, openActivation() {} });
    export const requireLicense = (a) => globalThis.__mock.requireLicense(a);`),
};
const EXT = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];
registerHooks({
  resolve(spec, ctx, next) {
    if (spec.endsWith(".css")) return { url: data("export default {};"), shortCircuit: true };
    if (/\.(mp4|png|gif|svg|webp|jpg)$/.test(spec)) return { url: data("export default 'asset.bin';"), shortCircuit: true };
    if ((spec.startsWith("./") || spec.startsWith("../")) && ctx.parentURL?.startsWith("file:")) {
      const base = path.resolve(path.dirname(fileURLToPath(ctx.parentURL)), spec);
      for (const e of EXT) {
        const f = base + e;
        if (fs.existsSync(f) && fs.statSync(f).isFile()) return MOCKS[f] ? { url: MOCKS[f], shortCircuit: true } : { url: pathToFileURL(f).href, shortCircuit: true };
      }
    }
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url.startsWith("file:") && /\.(ts|tsx)$/.test(url) && fileURLToPath(url).startsWith(SRC)) {
      const file = fileURLToPath(url);
      const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { fileName: file, compilerOptions: {
        module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, isolatedModules: true } });
      return { format: "module", source: out.outputText, shortCircuit: true };
    }
    return next(url, ctx);
  },
});

// ---------------------------------------------------------------- minimal DOM for react-dom/client (same stub as audit146_d_frontend_1)
const HTML_NS = "http://www.w3.org/1999/xhtml";
class N0 {
  constructor(doc) { this.ownerDocument = doc; this.parentNode = null; this.childNodes = []; }
  get firstChild() { return this.childNodes[0] ?? null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] ?? null; }
  get nextSibling() { const p = this.parentNode; return p ? p.childNodes[p.childNodes.indexOf(this) + 1] ?? null : null; }
  get previousSibling() { const p = this.parentNode; return p ? p.childNodes[p.childNodes.indexOf(this) - 1] ?? null : null; }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(ref), 0, c); return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  addEventListener(t, f, o) { ((this.listeners ||= {})[t] ||= []).push({ f, cap: typeof o === "boolean" ? o : !!o?.capture }); }
  removeEventListener(t, f, o) {
    const cap = typeof o === "boolean" ? o : !!o?.capture; const a = this.listeners?.[t] || [];
    const i = a.findIndex((l) => l.f === f && l.cap === cap); if (i >= 0) a.splice(i, 1);
  }
}
class Txt extends N0 {
  constructor(doc, t, type = 3) { super(doc); this.nodeType = type; this.nodeName = type === 3 ? "#text" : "#comment"; this.nodeValue = String(t); }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : ""; }
  set textContent(v) { this.nodeValue = String(v); }
  get data() { return this.nodeValue; }
  set data(v) { this.nodeValue = String(v); }
}
class El extends N0 {
  constructor(doc, tag, ns = HTML_NS) {
    super(doc); this.nodeType = 1; this.namespaceURI = ns; this.localName = tag;
    this.tagName = this.nodeName = ns === HTML_NS ? tag.toUpperCase() : tag;
    this.attrs = new Map(); this.dataset = {}; const st = {}; st.setProperty = (k, v) => { st[k] = v; }; st.removeProperty = (k) => { delete st[k]; }; this.style = st;
    if (tag === "input") { this.type = "text"; this.value = ""; this.checked = false; }
    if (tag === "textarea" || tag === "select") this.value = "";
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  setAttributeNS(_ns, k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  removeAttributeNS(_ns, k) { this.attrs.delete(k); }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get id() { return this.getAttribute("id") || ""; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; if (v !== "" && v != null) this.appendChild(new Txt(this.ownerDocument, v)); }
  get options() { return all(this).filter((e) => e.tagName === "OPTION"); }
  get value() { return this.tagName === "OPTION" ? (this._v ?? this.getAttribute("value") ?? this.textContent) : this._v; }
  set value(v) { this._v = v; }
  focus() { this.ownerDocument.activeElement = this; }
  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body; }
  click() { /* nothing to open in the stub */ }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
}
function makeEl(doc, tag, ns) {
  const e = new El(doc, tag, ns);
  if (tag === "input" || tag === "textarea" || tag === "select") Object.defineProperty(e, "value", { value: "", writable: true, enumerable: true, configurable: true });
  return e;
}
function all(root) { const out = []; const walk = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { out.push(c); walk(c); } }; walk(root); return out; }
function makeDoc() {
  const doc = new N0(null);
  Object.assign(doc, { nodeType: 9, nodeName: "#document", oninput: null, onchange: null, onclick: null, defaultView: globalThis });
  doc.createElement = (t) => makeEl(doc, String(t).toLowerCase());
  doc.createElementNS = (ns, t) => makeEl(doc, t, ns);
  doc.createTextNode = (t) => new Txt(doc, t);
  doc.createComment = (t) => new Txt(doc, t, 8);
  doc.documentElement = makeEl(doc, "html"); doc.appendChild(doc.documentElement);
  doc.head = makeEl(doc, "head"); doc.body = makeEl(doc, "body");
  doc.documentElement.appendChild(doc.head); doc.documentElement.appendChild(doc.body);
  doc.activeElement = doc.body;
  doc.getElementById = (id) => all(doc).find((e) => e.getAttribute("id") === id) || null;
  doc.querySelector = () => null;
  doc.visibilityState = "visible";
  return doc;
}
const doc = makeDoc();
globalThis.window = globalThis;
globalThis.document = doc;
globalThis.HTMLIFrameElement = class HTMLIFrameElement {};
const winEvents = new N0(null);
globalThis.addEventListener = (t, f, o) => winEvents.addEventListener(t, f, o);
globalThis.removeEventListener = (t, f, o) => winEvents.removeEventListener(t, f, o);
globalThis.dispatchEvent = (ev) => { for (const l of [...(winEvents.listeners?.[ev.type] || [])]) l.f(ev); return true; };
globalThis.HashChangeEvent = class HashChangeEvent { constructor(type) { this.type = type; } };
globalThis.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });   // reduced motion: counters without RAF
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.location = { host: "127.0.0.1", hash: "#/menu", reload() {} };
globalThis.history = { replaceState(_s, _t, h) { globalThis.location.hash = h; } };
const mkStorage = () => { const m = new Map(); return { map: m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); },
  removeItem: (k) => { m.delete(k); }, clear: () => m.clear() }; };
const LS = mkStorage();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: LS });
Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: mkStorage() });
const rejections = [];
process.on("unhandledRejection", (e) => { rejections.push(e); });

const React = req("react");
const { createRoot } = req("react-dom/client");
const { act } = React;
const imp = (rel) => import(pathToFileURL(path.join(SRC, rel)).href);
const srcOf = (rel) => fs.readFileSync(path.join(SRC, rel), "utf8");

function fire(el, type, extra = {}) {
  const pathUp = []; for (let n = el; n; n = n.parentNode) pathUp.push(n);
  const ev = { type, target: el, srcElement: el, bubbles: true, cancelable: true, defaultPrevented: false, isTrusted: true, timeStamp: Date.now(),
    button: 0, detail: 1, _stop: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this._stop = true; },
    stopImmediatePropagation() { this._stop = true; }, ...extra };
  for (const n of [...pathUp].reverse()) { for (const l of (n.listeners?.[type] || []).filter((x) => x.cap)) { ev.currentTarget = n; l.f.call(n, ev); } if (ev._stop) return ev; }
  for (const n of pathUp) { for (const l of (n.listeners?.[type] || []).filter((x) => !x.cap)) { ev.currentTarget = n; l.f.call(n, ev); } if (ev._stop) return ev; }
  return ev;
}
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const flush = async (n = 3) => { for (let i = 0; i < n; i++) await act(async () => { await tick(0); }); };
async function render(el) {
  const box = makeEl(doc, "div"); doc.body.appendChild(box);
  const errors = [];
  const root = createRoot(box, { onUncaughtError: (e) => errors.push(e), onCaughtError: (e) => errors.push(e), onRecoverableError: (e) => errors.push(e) });
  await act(async () => { root.render(el); });
  await flush();
  return { box, root, errors, rerender: async (e2) => { await act(async () => { root.render(e2); }); await flush(); },
    unmount: async () => { await act(async () => root.unmount()); box.parentNode?.removeChild(box); } };
}
const q = (root, testid) => all(root).find((e) => e.getAttribute("data-testid") === testid) || null;
async function click(el) { assert.ok(el, "element to click not found"); await act(async () => { fire(el, "click"); }); await flush(); }
function defer() { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); return { p, res, rej }; }
function mockApi({ get = {}, send = () => ({}), s = {} } = {}) {
  const calls = { get: [], send: [] };
  globalThis.__mock = {
    calls,
    store: { s: { loaded: true, first_run_completed: true, ...s }, refresh: async () => undefined },
    initSession: async () => undefined,
    requireLicense: async () => true,
    apiGet: async (p) => {
      calls.get.push(p);
      const h = Object.entries(get).find(([k]) => p === k || (k.endsWith("*") && p.startsWith(k.slice(0, -1))));
      if (!h) throw new Error("404 " + p);
      return typeof h[1] === "function" ? h[1](p) : JSON.parse(JSON.stringify(h[1]));
    },
    apiSend: async (m, p, body) => { calls.send.push({ m, p, body }); return send(m, p, body); },
  };
  return calls;
}
async function quiet(fn) {          // React logs expected errors with console.error
  const ce = console.error, cw = console.warn; console.error = () => {}; console.warn = () => {};
  try { return await fn(); } finally { console.error = ce; console.warn = cw; }
}

// ---------------------------------------------------------------- CHARTS: fake renderer api (the methods chartsData.ts calls)
function fakeRenderer(sel) {
  const r = { vms: [], listeners: [], unsubs: 0, sel: () => ({ ...sel }),
    onSelect(f) { r.listeners.push(f); return () => { r.unsubs += 1; const i = r.listeners.indexOf(f); if (i >= 0) r.listeners.splice(i, 1); }; },
    setTimeframes() {}, setSymbol() {}, setQuote() {}, setStatus() {}, liveBar() {}, setKronos() {}, setVM(vm) { r.vms.push(vm); } };
  return r;
}
const BARS = [{ open_utc: "2026-11-20T08:00:00Z", o: 2650.1, h: 2652.3, l: 2649.8, c: 2651.7, tv: 120, closed: true },
  { open_utc: "2026-11-20T08:15:00Z", o: 2651.7, h: 2653.0, l: 2650.9, c: 2652.4, tv: 98, closed: true }];
async function chartsRun({ sel = { asset: "XAUUSD", tf: "M15", kr: "M5" }, clock, info, btc = null } = {}) {
  mockApi({ get: {
    "/api/v1/timeframes": { timeframes: [] },
    "/api/v1/candles?tf=*": { tf: sel.tf, symbol: "XAUUSD", bars: BARS, ...(clock === undefined ? {} : { clock }) },
    "/api/v1/market-zones/bars?*": btc ?? { status: "OK", symbol: "BTCUSD", tf: sel.tf, bars: BARS },
  } });
  const { useChartsData } = await imp("features/forex/screens/charts/chartsData.ts");
  const fr = fakeRenderer(sel);
  const ref = { current: fr };
  const s = { connection: { state: "CONNECTED" }, symbol: { symbol: "XAUUSD", status: "OK", ...(info === undefined ? {} : { info }) } };
  function H({ active }) { useChartsData(ref, active, s); return null; }
  const r = await render(React.createElement(H, { active: true }));
  await flush(4);
  return { fr, r, H, last: () => fr.vms[fr.vms.length - 1] };
}

const CASES = {
  // chunk_47#0: the measured MT5 server clock offset (VERIFIED only) reaches the renderer as vm.serverOff; no verified offset -> null, never +2
  async charts_server_offset() {
    const a = await chartsRun({ clock: { offset_seconds: 10800, offset_hours: 3, status: "VERIFIED", samples: 12 } });
    try {
      const vm = a.last();
      assert.ok(vm, "setVM not called");
      assert.ok("serverOff" in vm, "chartsData does not pass serverOff - CZAS SERWERA stays a hard-coded UTC+2 in the renderer");
      assert.equal(vm.serverOff, 3);
    } finally { await a.r.unmount(); }
    for (const clock of [{ offset_seconds: 7200, offset_hours: 2, status: "STORED_UNVERIFIED" }, { offset_seconds: null, offset_hours: null, status: "MEASURING" },
      { offset_seconds: 7200, status: "INCONSISTENT" }, undefined]) {
      const b = await chartsRun({ clock });
      try {
        const vm = b.last();
        assert.ok("serverOff" in vm, "serverOff missing in the view model (the renderer would keep a stale offset)");
        assert.equal(vm.serverOff, null, "unverified clock " + JSON.stringify(clock) + " used as server offset");
      } finally { await b.r.unmount(); }
    }
    // BTC bars come from the same MT5 terminal (market-zones/bars -> bridge.symbol_bars): same broker clock
    const c = await chartsRun({ sel: { asset: "BTC", tf: "M5", kr: "M5" }, clock: { offset_seconds: 7200, status: "VERIFIED" } });
    try { assert.equal(c.last().asset, "BTC"); assert.equal(c.last().serverOff, 2); } finally { await c.r.unmount(); }
    const { serverOffVM } = await imp("features/forex/screens/charts/chartsData.ts");
    assert.equal(serverOffVM(null), null);
    assert.equal(serverOffVM({ clock: { status: "VERIFIED", offset_seconds: -3600 } }), -1);
    assert.equal(serverOffVM({ clock: { status: "VERIFIED", offset_seconds: null } }), null, "missing offset turned into 0 (UTC)");
  },
  // chunk_47#9: tick_size / digits of the engine symbol reach the renderer (SVP grid, bin label, price format); missing -> null, never 0.01 / 0
  async charts_symbol_tick_digits() {
    const a = await chartsRun({ clock: { offset_seconds: 7200, status: "VERIFIED" }, info: { name: "XAUUSD", point: 0.001, digits: 3, trade_tick_size: 0.001 } });
    try {
      const vm = a.last();
      assert.ok("tick" in vm && "digits" in vm, "chartsData does not pass tick / digits - session SVP assumes tick 0.01 and 2 digits");
      assert.equal(vm.tick, 0.001);
      assert.equal(vm.digits, 3);
    } finally { await a.r.unmount(); }
    // trade_tick_size 0 -> point (the same fallback as the backend VISIBLE profile, svp/service._ctx)
    const b = await chartsRun({ info: { point: 0.01, digits: 2, trade_tick_size: 0 } });
    try { assert.equal(b.last().tick, 0.01); assert.equal(b.last().digits, 2); } finally { await b.r.unmount(); }
    // no symbol info (terminal not connected yet): null, not a guessed 0.01 / 0 digits
    const c = await chartsRun({ info: null });
    try {
      const vm = c.last();
      assert.ok("tick" in vm && "digits" in vm);
      assert.equal(vm.tick, null); assert.equal(vm.digits, null, "missing digits became 0");
    } finally { await c.r.unmount(); }
    // BTC (market-zones/bars carries no symbol spec): the XAUUSD engine symbol spec must not be applied to BTC
    const d = await chartsRun({ sel: { asset: "BTC", tf: "M5", kr: "M5" }, info: { point: 0.001, digits: 3, trade_tick_size: 0.001 } });
    try { assert.equal(d.last().asset, "BTC"); assert.equal(d.last().tick, null); assert.equal(d.last().digits, null); } finally { await d.r.unmount(); }
    const { symbolSpecVM } = await imp("features/forex/screens/charts/chartsData.ts");
    assert.deepEqual(symbolSpecVM({ digits: "3", trade_tick_size: "abc" }), { tick: null, digits: null });
    assert.deepEqual(symbolSpecVM({ digits: 5, trade_tick_size: 0.00001 }), { tick: 0.00001, digits: 5 });
  },
  // chunk_47#14: one onSelect listener per entry into CHARTS - leaving the screen unregisters it (already in chartsData.ts at HEAD)
  async charts_onselect_unsubscribe() {
    const a = await chartsRun({ clock: { offset_seconds: 7200, status: "VERIFIED" } });
    try {
      assert.equal(a.fr.listeners.length, 1);
      for (let i = 0; i < 3; i++) {
        await a.r.rerender(React.createElement(a.H, { active: false }));
        await a.r.rerender(React.createElement(a.H, { active: true }));
      }
      assert.equal(a.fr.listeners.length, 1, "listeners accumulate on every entry into CHARTS");
      assert.equal(a.fr.unsubs, 3);
    } finally { await a.r.unmount(); }
    assert.equal(a.fr.listeners.length, 0);
  },
  // chunk_45#1: a FOREX hand-off cancelled while the licence check runs (POWRÓT / Esc / intro / unmount) must not navigate to #/forex
  async app_forex_handoff_cancel() {
    mockApi();
    const lic = [];
    globalThis.__mock.requireLicense = (a) => { const d = defer(); lic.push({ a, d }); return d.p; };
    globalThis.location.hash = "#/menu";
    const { default: App } = await imp("App.tsx");
    const r = await render(React.createElement(App));
    try {
      const cin = globalThis.__mock.cin;
      assert.ok(cin && typeof cin.onForexReady === "function", "CinematicMenu not rendered on #/menu");
      const ac = new AbortController();
      await act(async () => { cin.onForexReady({ x: 1, y: 2, r: 3 }, ac.signal); });
      assert.equal(lic.length, 1); assert.equal(lic[0].a, "FOREX");
      ac.abort();                                                  // POWRÓT while the licence check is still running
      await act(async () => { lic[0].d.res(true); await tick(0); });
      await flush();
      assert.equal(globalThis.location.hash, "#/menu", "cancelled FOREX hand-off still navigated to " + globalThis.location.hash);
      assert.equal(globalThis.__mock.forex, undefined, "ForexScene rendered after the user went back");
      // a hand-off that was not cancelled still opens FOREX
      const ac2 = new AbortController();
      await act(async () => { globalThis.__mock.cin.onForexReady({ x: 4, y: 5, r: 6 }, ac2.signal); });
      await act(async () => { lic[1].d.res(true); await tick(0); });
      await flush();
      assert.equal(globalThis.location.hash, "#/forex?from=menu");
      assert.ok(globalThis.__mock.forex, "ForexScene not rendered");
      assert.equal(globalThis.sessionStorage.getItem("pmw.forex.pose"), JSON.stringify({ x: 4, y: 5, r: 6 }));
    } finally { await r.unmount(); globalThis.location.hash = "#/menu"; }
  },
  // focus_X5#10: #/otc keeps redirecting to #/menu?retired=otc (1.45 TASK 020 contract) and the menu now tells the user why
  async app_otc_retired_note() {
    mockApi();
    globalThis.location.hash = "#/otc-gold";
    const { default: App } = await imp("App.tsx");
    const r = await render(React.createElement(App));
    try {
      assert.equal(globalThis.location.hash, "#/menu?retired=otc", "redirect contract changed");
      const note = q(r.box, "otc-retired-note");
      assert.ok(note, "retired=otc is not read - the user gets no notice that OTC was retired");
      assert.match(note.textContent, /Strategie OTC zostały wycofane \(Apollo23, TASK 020\)\. Historia zostaje tylko do odczytu\./);
      assert.equal(note.getAttribute("role"), "status");
      await click(q(r.box, "otc-retired-ok"));
      assert.equal(q(r.box, "otc-retired-note"), null, "OK does not close the note");
      assert.equal(globalThis.location.hash, "#/menu?retired=otc");
    } finally { await r.unmount(); }
    globalThis.location.hash = "#/menu";
    const r2 = await render(React.createElement(App));
    try { assert.equal(q(r2.box, "otc-retired-note"), null, "note shown on a plain #/menu"); } finally { await r2.unmount(); }
  },
  // chunk_45#6: App no longer passes the unused onSettings prop and CinematicMenu no longer declares it
  async app_cinematic_no_onsettings() {
    mockApi();
    globalThis.location.hash = "#/menu";
    const { default: App } = await imp("App.tsx");
    const r = await render(React.createElement(App));
    try {
      const cin = globalThis.__mock.cin;
      assert.ok(cin, "CinematicMenu not rendered");
      assert.equal("onSettings" in cin, false, "App still passes the unused onSettings prop");
      for (const k of ["onMenuReady", "onForexReady", "onGameReady"]) assert.equal(typeof cin[k], "function", k);
    } finally { await r.unmount(); }
    assert.doesNotMatch(srcOf("features/cinematic/CinematicMenu.tsx"), /onSettings\s*\??\s*\(/, "CinematicMenu Props still declare onSettings");
    assert.doesNotMatch(srcOf("App.tsx"), /onSettings=/);
  },
  // focus_X5#6 (frontend part): MODELS & BACKTEST button and the Diagnostics resources line show the Apollo23 brand, ids / API fields unchanged
  async labels_apollo23() {
    mockApi();
    const { default: ModelsScreen } = await imp("features/forex/screens/ModelsScreen.tsx");
    const opened = [];
    const r = await quiet(() => render(React.createElement(ModelsScreen, { engine: null, onSystem: (p) => opened.push(p) })));
    try {
      const b = q(r.box, "open-training-center");
      assert.ok(b, "open-training-center button missing (data-testid must stay)");
      assert.equal(b.textContent.trim(), "CENTRUM TRENINGOWE APOLLO23");
      assert.doesNotMatch(r.box.textContent, /PEPE/);
      await click(b);
      assert.deepEqual(opened, ["training"]);
    } finally { await r.unmount(); }
    mockApi({ get: { "/api/v1/resources": { level: "OK", level_pl: "w normie", system: { used_pct: 41, total_mb: 16384 }, pmw_total_mb: 812, profile: "AUTO",
      profiles: {}, processes: {} } }, s: { connection: { state: "CONNECTED" } } });
    const { default: DiagnosticsPanel } = await imp("features/system/DiagnosticsPanel.tsx");
    const d = await render(React.createElement(DiagnosticsPanel));
    try {
      const res = q(d.box, "diag-resources");
      assert.ok(res);
      assert.match(res.textContent, /procesy Apollo23 812 MB/);
      assert.doesNotMatch(res.textContent, /PMW/, "old PMW brand in the resources line");
    } finally { await d.unmount(); }
  },
  // chunk_43#17 (brand.ts / router.ts part): no unused LEGACY_PRODUCT export, no write-only localStorage "mq.lastHash"
  async dead_brand_and_last_hash() {
    const B = await imp("brand.ts");
    assert.equal(B.LEGACY_PRODUCT, undefined, "unused LEGACY_PRODUCT still exported");
    assert.equal(B.BRAND, "Apollo23"); assert.equal(typeof B.GAME_BRAND, "string");
    const { useRoute, navigate } = await imp("router.ts");
    LS.clear();
    globalThis.location.hash = "#/forex?s=charts";
    let seen = null;
    function H() { seen = useRoute(); return null; }
    const r = await render(React.createElement(H));
    try {
      assert.equal(seen.page, "forex");
      await act(async () => { navigate("menu", { replace: true }); });
      await flush();
      assert.equal(seen.page, "menu", "router no longer follows hashchange");
      assert.equal(LS.getItem("mq.lastHash"), null, "router still writes the unread mq.lastHash on every route change");
    } finally { await r.unmount(); globalThis.location.hash = "#/menu"; }
    // existing user value is left alone (rule 4: nothing deletes it)
    LS.setItem("mq.lastHash", "#/forex?s=roi");
    const r2 = await render(React.createElement(H));
    try { assert.equal(LS.getItem("mq.lastHash"), "#/forex?s=roi"); } finally { await r2.unmount(); }
    assert.doesNotMatch(srcOf("router.ts"), /setItem\(\s*LAST|const LAST\b/);
  },
};

const want = process.argv.slice(2).filter((a) => !a.startsWith("--"));
let bad = 0;
for (const name of want.length ? want : Object.keys(CASES)) {
  const fn = CASES[name];
  if (!fn) { console.log(`${name} FAIL: unknown case`); bad++; continue; }
  try { await fn(); console.log(`${name} OK`); } catch (e) { bad++; console.log(`${name} FAIL: ${e?.stack || e}`); }
}
if (rejections.length) console.log("unhandled rejections: " + rejections.map((e) => String(e?.message || e)).join(" | "));
process.exit(bad ? 1 : 0);
