// 1.46 audit (group B_frontend_2): FOREX scene (static / context-lost mode, MODEL B), usePoll, SIGNALS / MODELS screens, CHARTS data hook,
// chart zone primitives (zones.ts) and dead code of the FOREX engine - React components rendered with the real react-dom/client into a
// minimal DOM stub (no browser). Usage: node --experimental-strip-types --no-warnings tests/js/audit146_b_frontend_2.test.mjs <case> [case ...]
// .ts/.tsx sources are transpiled with the project's own TypeScript; api.ts, store.tsx, router.ts and the heavy children of ForexScene are
// replaced by in-memory mocks. Every case prints "<case> OK" or "<case> FAIL: ..."; exit code 1 on any failure.
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire, registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FE = path.join(here, "..", "..", "frontend");
const SRC = path.join(FE, "src");
const FX = path.join(SRC, "features", "forex");
const req = createRequire(path.join(FE, "package.json"));
const ts = req("typescript");

// ---------------------------------------------------------------- module hooks: TS/TSX transpile, CSS stub, mocks
const data = (src) => "data:text/javascript," + encodeURIComponent(src);
const MOCKS = {
  [path.join(SRC, "api.ts")]: data(`
    export const ApiError = globalThis.__ApiError;
    export const apiGet = (...a) => globalThis.__mock.apiGet(...a);
    export const apiSend = (...a) => globalThis.__mock.apiSend(...a);
    export const apiUpload = (...a) => globalThis.__mock.apiSend("UPLOAD", ...a);
    export const initSession = async () => undefined;
    export const getCsrf = () => "csrf";`),
  [path.join(SRC, "store.tsx")]: data(`
    const R = globalThis.__React;
    export function useStore() { const s = R.useSyncExternalStore(globalThis.__store.sub, globalThis.__store.get); return { s, refresh: async () => undefined }; }
    export function StoreProvider({ children }) { return children; }`),
  [path.join(SRC, "router.ts")]: data(`
    export const FOREX_SCREENS = ["charts", "signals", "models", "roi"];
    export function navigate(page, opts = {}) { globalThis.__nav.push([page, opts.params || null]); }`),
  [path.join(SRC, "features", "cinematic", "introGate.ts")]: data(`export const prefersReducedMotion = () => true;`),
  [path.join(SRC, "features", "system", "SystemBar.tsx")]: data(`export const ExecStatus = () => null; export const SystemIcons = () => null;`),
  [path.join(SRC, "components", "Pmw141Panels.tsx")]: data(`export const ComponentsCards = () => null; export const TabICLCard = () => null;
    export const ResearchModulesPanel = () => null; export const BasketsPanel = () => null;`),
};
// children of ForexScene only (the screens themselves are tested directly)
const SCENE_MOCKS = {
  [path.join(FX, "engine", "forexEngine.ts")]: data(`
    export function mountForex(root, opts) {
      const g = globalThis.__eng; g.opts = opts; g.root = root; g.calls = [];
      if (g.noGl) opts.onNoWebGL && opts.onNoWebGL();
      const api = { state: () => ({ phase: "forex" }), nodeAt: () => undefined };
      return new Proxy(api, { get: (t, k) => (k in t ? t[k] : (...a) => { g.calls.push([k, ...a]); }) });
    }`),
  [path.join(FX, "screens", "charts", "ChartsScreen.tsx")]: data(`export default function ChartsScreen() { return null; }`),
  [path.join(FX, "screens", "SignalsScreen.tsx")]: data(`export default function S() { return globalThis.__React.createElement("section", { "data-testid": "stub-signals" }); }`),
  [path.join(FX, "screens", "ModelsScreen.tsx")]: data(`export default function S() { return globalThis.__React.createElement("section", { "data-testid": "stub-models" }); }`),
  [path.join(FX, "screens", "RoiScreen.tsx")]: data(`export default function S() { return globalThis.__React.createElement("section", { "data-testid": "stub-roi" }); }`),
};
const EXT = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];
registerHooks({
  resolve(spec, ctx, next) {
    if (spec.endsWith(".css")) return { url: data("export default {};"), shortCircuit: true };
    if ((spec.startsWith("./") || spec.startsWith("../")) && ctx.parentURL?.startsWith("file:")) {
      const parent = fileURLToPath(ctx.parentURL);
      const base = path.resolve(path.dirname(parent), spec);
      for (const e of EXT) {
        const f = base + e;
        if (fs.existsSync(f) && fs.statSync(f).isFile()) {
          if (parent.endsWith(path.join("forex", "ForexScene.tsx")) && SCENE_MOCKS[f]) return { url: SCENE_MOCKS[f], shortCircuit: true };
          return MOCKS[f] ? { url: MOCKS[f], shortCircuit: true } : { url: pathToFileURL(f).href, shortCircuit: true };
        }
      }
    }
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url.startsWith("file:") && /\.(ts|tsx)$/.test(url) && fileURLToPath(url).startsWith(SRC)) {
      const file = fileURLToPath(url);
      const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { fileName: file, compilerOptions: {
        module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, isolatedModules: true } });
      return { format: "module", source: out.outputText.replace(/import\.meta\.env/g, '({ MODE: "production", DEV: false, PROD: true })'), shortCircuit: true };
    }
    return next(url, ctx);
  },
});

// ---------------------------------------------------------------- minimal DOM (what react-dom/client and the tested code touch)
const HTML_NS = "http://www.w3.org/1999/xhtml";
const kebab = (s) => s.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
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
  querySelectorAll(sel) { return all(this).filter((e) => matches(e, sel, this)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
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
    this.attrs = new Map(); const st = {}; st.setProperty = (k, v) => { st[k] = v; }; st.removeProperty = (k) => { delete st[k]; }; this.style = st;
    const self = this;
    this.dataset = new Proxy({}, { get: (_t, k) => (typeof k === "string" ? self.getAttribute("data-" + kebab(k)) ?? undefined : undefined),
      set: (_t, k, v) => { self.setAttribute("data-" + kebab(String(k)), v); return true; },
      deleteProperty: (_t, k) => { self.removeAttribute("data-" + kebab(String(k))); return true; } });
    this.classList = { add: (...c) => { const s = new Set(this.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); this.className = [...s].join(" "); },
      remove: (...c) => { this.className = this.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(" "); },
      contains: (c) => this.className.split(/\s+/).includes(c) };
    this.offsetWidth = 0;
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  setAttributeNS(_ns, k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  removeAttributeNS(_ns, k) { this.attrs.delete(k); }
  get inert() { return this.hasAttribute("inert"); }
  set inert(v) { if (v) this.setAttribute("inert", ""); else this.removeAttribute("inert"); }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get id() { return this.getAttribute("id") || ""; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; if (v !== "" && v != null) this.appendChild(new Txt(this.ownerDocument, v)); }
  get value() { return this._v; }
  set value(v) { this._v = v; }
  focus() { this.ownerDocument.activeElement = this; }
  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body; }
  click() {}
  getContext() { return null; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
}
function makeEl(doc, tag, ns) {
  const e = new El(doc, tag, ns);
  if (tag === "input" || tag === "textarea" || tag === "select") Object.defineProperty(e, "value", { value: "", writable: true, enumerable: true, configurable: true });
  return e;
}
function all(root) { const out = []; const walk = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { out.push(c); walk(c); } }; walk(root); return out; }
// selectors: groups (,), descendant combinator (space), compound of tag / #id / .class / [attr] / [attr=value]
function simple(e, part) {
  const re = /([#.]?[\w-]+|\[[^\]]+\])/g; let m;
  while ((m = re.exec(part))) {
    const t = m[1];
    if (t[0] === "#") { if (e.getAttribute("id") !== t.slice(1)) return false; }
    else if (t[0] === ".") { if (!e.className.split(/\s+/).includes(t.slice(1))) return false; }
    else if (t[0] === "[") {
      const [k, v] = t.slice(1, -1).split("=");
      if (!e.hasAttribute(k)) return false;
      if (v != null && e.getAttribute(k) !== v.replace(/^["']|["']$/g, "")) return false;
    } else if (e.localName !== t.toLowerCase()) return false;
  }
  return true;
}
function matches(e, sel, scope) {
  return sel.split(",").some((g) => {
    const parts = g.trim().split(/\s+/);
    if (!simple(e, parts[parts.length - 1])) return false;
    let n = e.parentNode;
    for (let i = parts.length - 2; i >= 0; i--) {
      while (n && n !== scope && !(n.nodeType === 1 && simple(n, parts[i]))) n = n.parentNode;
      if (!n || n === scope) return false;
      n = n.parentNode;
    }
    return true;
  });
}
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
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.location = { host: "127.0.0.1", hash: "#/forex", reload() {} };
globalThis.history = { replaceState(_s, _t, h) { globalThis.location.hash = h; } };
globalThis.innerWidth = 1280; globalThis.innerHeight = 800; globalThis.devicePixelRatio = 1;
globalThis.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
const mkStorage = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); },
  removeItem: (k) => { m.delete(k); }, clear: () => m.clear() }; };
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: mkStorage() });
Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: mkStorage() });
// setInterval under test control (React's scheduler does not use it): intervals run only when a case calls runIntervals()
const intervals = new Map(); let ivId = 0;
globalThis.setInterval = (fn, ms) => { ivId++; intervals.set(ivId, { fn, ms }); return ivId; };
globalThis.clearInterval = (id) => { intervals.delete(id); };
const realNow = Date.now; let clockOffset = 0;
Date.now = () => realNow() + clockOffset;

class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
globalThis.__ApiError = ApiError;
const React = req("react");
globalThis.__React = React;
const { createRoot } = req("react-dom/client");
const { act } = React;
const imp = (abs) => import(pathToFileURL(abs).href);

function fire(el, type, extra = {}) {
  const pathUp = []; for (let n = el; n; n = n.parentNode) pathUp.push(n);
  const ev = { type, target: el, srcElement: el, bubbles: true, cancelable: true, defaultPrevented: false, isTrusted: true, timeStamp: Date.now(),
    button: 0, detail: 1, _stop: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this._stop = true; },
    stopImmediatePropagation() { this._stop = true; }, ...extra };
  for (const n of [...pathUp].reverse()) { for (const l of (n.listeners?.[type] || []).filter((x) => x.cap)) { ev.currentTarget = n; l.f.call(n, ev); } if (ev._stop) return ev; }
  for (const n of pathUp) { for (const l of (n.listeners?.[type] || []).filter((x) => !x.cap)) { ev.currentTarget = n; l.f.call(n, ev); } if (ev._stop) return ev; }
  return ev;
}
const fireWindow = (type, extra = {}) => { const ev = { type, target: doc.body, preventDefault() {}, stopPropagation() {}, ...extra };
  for (const l of [...(winEvents.listeners?.[type] || [])]) l.f(ev); };
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const flush = async (n = 4) => { for (let i = 0; i < n; i++) await act(async () => { await tick(0); }); };
async function runIntervals(filter = () => true) { await act(async () => { for (const iv of [...intervals.values()]) if (filter(iv)) iv.fn(); }); await flush(); }
async function render(el) {
  const box = makeEl(doc, "div"); doc.body.appendChild(box);
  const errors = [];
  const root = createRoot(box, { onUncaughtError: (e) => errors.push(e), onCaughtError: (e) => errors.push(e), onRecoverableError: (e) => errors.push(e) });
  await act(async () => { root.render(el); });
  await flush();
  return { box, root, errors, rerender: async (el2) => { await act(async () => { root.render(el2); }); await flush(); },
    unmount: async () => { await act(async () => root.unmount()); box.parentNode?.removeChild(box); } };
}
const q = (root, testid) => all(root).find((e) => e.getAttribute("data-testid") === testid) || null;
const byId = (root, id) => all(root).find((e) => e.getAttribute("id") === id) || null;
const byText = (root, tag, re) => all(root).find((e) => e.tagName === tag.toUpperCase() && re.test(e.textContent)) || null;
async function click(el) { assert.ok(el, "element to click not found"); await act(async () => { fire(el, "click"); }); await flush(); }
function defer() { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); p.catch(() => undefined); return { p, res, rej }; }
function mockApi(get = {}) {
  const calls = { get: [] };
  globalThis.__mock = {
    calls,
    apiGet: async (p) => {
      calls.get.push(p);
      const h = Object.entries(get).find(([k]) => p === k || (k.endsWith("*") && p.startsWith(k.slice(0, -1))));
      if (!h) throw new ApiError(404, "404 " + p);
      const v = typeof h[1] === "function" ? await h[1](p) : h[1];
      if (v instanceof Error) throw v;
      return v && typeof v === "object" ? JSON.parse(JSON.stringify(v)) : v;
    },
    apiSend: async () => ({}),
  };
  return calls;
}
function setStore(s) {
  const st = globalThis.__store ||= { s: {}, subs: new Set(), get: () => globalThis.__store.s, sub: (f) => { globalThis.__store.subs.add(f); return () => globalThis.__store.subs.delete(f); } };
  st.s = s; st.subs.forEach((f) => f());
}
async function updateStore(patch) { await act(async () => { setStore({ ...globalThis.__store.s, ...patch }); }); await flush(); }
const nowSec = () => Math.floor(Date.now() / 1000);

// ---------------------------------------------------------------- fixtures
const sig = (o) => ({ signal_id: "B1", strategy_id: "S01", strategy_name: "Trend", timeframe: "M15", action: "BUY", status: "OPEN", created_at: nowSec() - 120,
  entry_price: 2000, stop_loss: 1995, take_profits: [2005], ...o });
async function signals(get) {
  mockApi({ "/api/v1/bot-signals?limit=200": { items: [] }, "/api/v1/setups": { items: [] }, "/api/v1/sh/signals?limit=200": { items: [] },
    "/api/v1/decision": null, "/api/v1/models/catalog?instrument=XAUUSD": { items: [] }, "/api/v1/models/predictions?instrument=XAUUSD": { items: [] }, ...get });
  setStore({ quote: { bid: 2001 }, symbol: { symbol: "XAUUSD" }, mode: {} });
  const { default: SignalsScreen } = await imp(path.join(FX, "screens", "SignalsScreen.tsx"));
  const r = await render(React.createElement(SignalsScreen, { engine: null, active: true, onSystem() {} }));
  assert.deepEqual(r.errors.map(String), []);
  return r;
}
const rowsOf = (box) => all(q(box, "signals-detail")).filter((e) => e.className.split(" ").includes("mr"));
const listLc = (box) => all(q(box, "signals-list")).filter((e) => e.tagName === "BUTTON").map((e) => e.getAttribute("data-lc"));
const tabBtn = (box, label) => all(byId(box, "sg-tabs")).find((e) => e.tagName === "BUTTON" && e.textContent === label);

async function models(get) {
  mockApi({ "/api/v1/models/catalog?instrument=XAUUSD": { items: [] }, "/api/v1/trainhub/status": { jobs: [], queue: {} },
    "/api/v1/trainhub/registry?instrument=XAUUSD": { versions: [], active: {} }, ...get });
  setStore({});
  const { default: ModelsScreen } = await imp(path.join(FX, "screens", "ModelsScreen.tsx"));
  const r = await render(React.createElement(ModelsScreen, { engine: null, active: true, onSystem() {} }));
  assert.deepEqual(r.errors.map(String), []);
  return r;
}

async function scene({ noGl, screen = null, store = {}, get = {} }) {
  globalThis.__eng = { noGl };
  globalThis.__nav = [];
  mockApi({ "/api/v1/baskets/settings": { active_profile: "FOREX_MT5" }, "/api/v1/models/predictions?instrument=XAUUSD": { items: [] },
    "/api/v1/bot-signals?limit=1": { items: [] }, ...get });
  setStore({ ws: "OPEN", barTick: {}, ...store });
  const { default: ForexScene } = await imp(path.join(FX, "ForexScene.tsx"));
  const props = (scr) => ({ screen: scr, fromMenu: false, onSystem() {}, testMode: false });
  const r = await render(React.createElement(ForexScene, props(screen)));
  assert.deepEqual(r.errors.map(String), []);
  return { ...r, page: () => q(r.box, "page-forex"), show: (scr) => r.rerender(React.createElement(ForexScene, props(scr))) };
}

// CHARTS data hook driven by a fake renderer api
function fakeCharts(sel = { asset: "XAUUSD", tf: "M15", kr: "M5" }) {
  const listeners = [];
  const log = { vm: [], status: [], tf: [] };
  const api = { sel: () => ({ ...sel }), onSelect(f) { listeners.push(f); return () => { const i = listeners.indexOf(f); if (i >= 0) listeners.splice(i, 1); }; },
    setTimeframes: (x) => log.tf.push(x), setSymbol() {}, setQuote() {}, setStatus: (s) => log.status.push(s), setVM: (vm) => log.vm.push(vm),
    liveBar() {}, setKronos() {} };
  return { ref: { current: api }, listeners, log };
}
async function chartsHook(fc, s, active = true) {
  const { useChartsData } = await imp(path.join(FX, "screens", "charts", "chartsData.ts"));
  function H({ a, st }) { useChartsData(fc.ref, a, st); return null; }
  const r = await render(React.createElement(H, { a: active, st: s }));
  assert.deepEqual(r.errors.map(String), []);
  return { ...r, set: (a, st) => r.rerender(React.createElement(H, { a, st })) };
}
const CHART_GET = { "/api/v1/candles*": { bars: [{ open_utc: "2026-11-24T10:00:00Z", o: 1, h: 2, l: 0.5, c: 1.5, tv: 1, closed: true }] }, "/api/v1/market-zones?*": null,
  "/api/v1/baskets/catalog": null, "/api/v1/strategy/auto": null, "/api/v1/sh/config": null, "/api/v1/baskets": null, "/api/v1/baskets/signals*": null,
  "/api/v1/bot-signals?*": { items: [] }, "/api/v1/sh/signals*": { items: [] }, "/api/v1/models/predictions*": { items: [] }, "/api/v1/timeframes": { timeframes: [] },
  "/api/v1/kronos": null, "/api/v1/kronos/forecast*": null };
const bar = (t_raw, closed, seq) => ({ bar: { t_raw, open_utc: new Date(t_raw * 1000).toISOString(), o: 1, h: 2, l: 0.5, c: 1.5, tv: 1, closed }, closed, seq });

// lightweight-charts time scale stub with the real 5.2.1 timeToIndex semantics (lower bound; nearest = first point >= t, last point after the end)
function fakeChart(times, { spacing = 10, width = 1000 } = {}) {
  const X = (i) => 20 + i * spacing;
  const idx = (t, nearest) => {
    if (!times.length) return null;
    if (t > times[times.length - 1]) return nearest ? times.length - 1 : null;
    let i = times.findIndex((x) => x >= t);
    if (t < times[i]) return nearest ? i : null;
    return i;
  };
  const tsApi = {
    timeToIndex: (t, nearest) => idx(Number(t), nearest),
    timeToCoordinate: (t) => { const i = idx(Number(t), false); return i === null ? null : X(i); },
    logicalToCoordinate: (l) => X(Number(l)),
    coordinateToLogical: (x) => (x - 20) / spacing,
    coordinateToTime: (x) => { const i = Math.round((x - 20) / spacing); return i >= 0 && i < times.length ? times[i] : null; },
    getVisibleRange: () => ({ from: times[0], to: times[times.length - 1] }),
    getVisibleLogicalRange: () => ({ from: 0, to: times.length - 1 }),
    width: () => width,
  };
  return { chart: { timeScale: () => tsApi }, series: { priceToCoordinate: (p) => 500 - p }, X, width };
}
function drawPrim(prim, fc) {
  prim.attached({ chart: fc.chart, series: fc.series, requestUpdate() {} });
  const ops = [];
  const ctx = new Proxy({}, { get: (t, k) => (k in t ? t[k] : (...a) => { ops.push([k, ...a]); }), set: (t, k, v) => { t[k] = v; return true; } });
  for (const v of prim.paneViews()) v.renderer().draw({ useMediaCoordinateSpace: (cb) => cb({ context: ctx, mediaSize: { width: fc.width, height: 600 } }) });
  return ops;
}

const CASES = {
  // chunk_46#10: static mode (no WebGL) - #forex-screen / #sub-screen must not stay inert, planets / return / Escape work, data-sub on for an open screen
  async forex_static_interactive() {
    const sc = await scene({ noGl: true });
    const root = sc.page();
    assert.equal(root.getAttribute("data-static"), "1");
    assert.equal(byId(root, "forex-screen").hasAttribute("inert"), false, "#forex-screen stays inert without WebGL - planets cannot be clicked");
    assert.equal(byId(root, "sub-screen").hasAttribute("inert"), false, "#sub-screen stays inert without WebGL");
    await click(q(root, "planet-signals"));
    assert.deepEqual(globalThis.__nav.pop(), ["forex", { s: "signals" }]);
    await sc.show("signals");
    assert.equal(root.getAttribute("data-sub"), "on", "open screen in static mode must enable its .ci interactions (data-sub=on)");
    assert.ok(q(root, "stub-signals"), "screen rendered");
    await act(async () => { fireWindow("keydown", { key: "Escape" }); });
    assert.deepEqual(globalThis.__nav.pop(), ["forex", null], "Escape on a screen returns to FOREX");
    await sc.show(null);
    assert.equal(root.getAttribute("data-sub"), "none");
    await act(async () => { fireWindow("keydown", { key: "Escape" }); });
    assert.deepEqual(globalThis.__nav.pop(), ["menu", null], "Escape on the FOREX screen returns to the menu");
    await sc.unmount();
    await act(async () => { fireWindow("keydown", { key: "Escape" }); });
    assert.equal(globalThis.__nav.length, 0, "keyboard listener removed on unmount");
  },
  // chunk_46#11: lost WebGL context -> the scene switches to the simplified (static) mode instead of freezing
  async forex_context_lost_static() {
    const sc = await scene({ noGl: false, screen: "models" });
    const root = sc.page();
    assert.equal(root.getAttribute("data-static"), null);
    assert.equal(typeof globalThis.__eng.opts.onContextLost, "function", "ForexScene does not pass onContextLost to the engine");
    const planet = q(root, "planet-charts");
    planet.style.pointerEvents = "none"; planet.style.opacity = "0"; planet.style.visibility = "hidden";   // as the engine left them
    byId(root, "fx-return").style.opacity = "0"; byId(root, "sub-screen").style.opacity = "0";
    const before = globalThis.__eng.calls.length;
    await act(async () => { globalThis.__eng.opts.onContextLost(); });
    await flush();
    assert.equal(root.getAttribute("data-static"), "1");
    assert.equal(byId(root, "forex-screen").hasAttribute("inert"), false);
    assert.equal(byId(root, "sub-screen").hasAttribute("inert"), false);
    assert.equal(root.getAttribute("data-sub"), "on");
    assert.ok(q(root, "stub-models"), "the open screen is still shown");
    assert.ok(!planet.style.pointerEvents && !planet.style.opacity && !planet.style.visibility, "inline styles from the dead engine must not block the static planets");
    assert.ok(!byId(root, "sub-screen").style.opacity && !byId(root, "fx-return").style.opacity);
    assert.ok(!globalThis.__eng.calls.slice(before).some((c) => c[0] === "openSub" || c[0] === "closeSub"), "the dead engine is not driven any more");
    await sc.unmount();
  },
  // chunk_46#12 (MODEL B): a bar close must be seen even when bar_closed and the next bar event are batched into one render; window = 2 x TF
  async forex_model_b_bar_close() {
    clockOffset = 0;
    const sc = await scene({ noGl: false, store: { barTick: { M5: bar(1000, false, 1), M1: bar(4940, false, 1) } } });
    const panelB = () => globalThis.__eng.calls.filter((c) => c[0] === "setPanel" && c[1] === 1).map((c) => c[2]).pop();
    assert.equal(panelB(), "idle");
    await updateStore({ barTick: { M5: bar(1300, false, 3), M1: bar(4940, false, 1) } });   // bar_closed (seq 2) + bar (seq 3) in one render
    await runIntervals((iv) => iv.ms === 10000);
    assert.equal(panelB(), "working", "batched bar_closed was lost - MODEL B stays OCZEKUJE");
    clockOffset = 11 * 60 * 1000;                                       // 11 min later, nothing closed: > 2 x M5
    await runIntervals((iv) => iv.ms === 10000);
    assert.equal(panelB(), "idle");
    await updateStore({ barTick: { M5: bar(1300, false, 3), M1: bar(4940, true, 4) } });  // non-batched close of M1
    await runIntervals((iv) => iv.ms === 10000);
    assert.equal(panelB(), "working");
    clockOffset += 3 * 60 * 1000;                                       // 3 min after an M1 close: > 2 x M1 (was a fixed 2 x 300 s)
    await runIntervals((iv) => iv.ms === 10000);
    assert.equal(panelB(), "idle", "window must be 2 x TF of the closed bar, not a fixed 2 x 300 s");
    clockOffset = 0;
    await sc.unmount();
  },
  // chunk_46#17: dead screenRef removed
  async forex_screenref_removed() {
    const src = fs.readFileSync(path.join(FX, "ForexScene.tsx"), "utf8");
    assert.ok(!/screenRef/.test(src), "screenRef is still in ForexScene.tsx");
  },
  // chunk_46#5: usePoll - a late answer of the previous path must not overwrite the data of the new path; err is reset on a path change
  async usepoll_stale_path() {
    const D = { A: defer(), B: defer(), C: defer(), E: defer() };
    mockApi({ "/a": () => D.A.p, "/b": () => D.B.p, "/c": () => D.C.p, "/e": () => D.E.p });
    const { usePoll } = await imp(path.join(FX, "data.ts"));
    let last = null;
    function P({ p }) { last = usePoll(p, 60000); return null; }
    const r = await render(React.createElement(P, { p: "/a" }));
    await r.rerender(React.createElement(P, { p: "/b" }));
    await act(async () => { D.B.res({ v: "B" }); }); await flush();
    assert.deepEqual(last.data, { v: "B" });
    await act(async () => { D.A.res({ v: "A" }); }); await flush();
    assert.deepEqual(last.data, { v: "B" }, "late response of the previous path overwrote the data of the current path");
    await r.rerender(React.createElement(P, { p: "/c" }));
    await act(async () => { D.C.rej(new Error("boom")); }); await flush();
    assert.equal(last.err, "boom");
    await r.rerender(React.createElement(P, { p: "/e" }));
    assert.equal(last.err, null, "error of the previous path is still shown for the new path");
    assert.equal(last.data, null);
    await act(async () => { D.E.res({ v: "E" }); }); await flush();
    assert.deepEqual(last.data, { v: "E" });
    await r.unmount();
  },
  // chunk_46#1: FLAT / neutral forecast is NEUTRAL for SELL (was counted as agreeing); DOWN agrees, UP disagrees
  async signals_agree_flat() {
    for (const [dir, want] of [["FLAT", "0"], ["NEUTRAL", "0"], ["DOWN", "1"], ["UP", "-1"]]) {
      const r = await signals({ "/api/v1/bot-signals?limit=200": { items: [sig({ action: "SELL" })] },
        "/api/v1/models/catalog?instrument=XAUUSD": { items: [{ id: "kronos", name: "Kronos", group: "G", category: "TRAINABLE", state: "READY" }] },
        "/api/v1/models/predictions?instrument=XAUUSD": { items: [{ model_name: "kronos", state: "READY", unit: "price", result: { direction: dir } }] } });
      const rows = rowsOf(r.box);
      assert.equal(rows.length, 1);
      assert.equal(rows[0].getAttribute("data-a"), want, `SELL vs ${dir}`);
      await r.unmount();
    }
  },
  // chunk_46#2: catalog ids (lower case) are matched with the model_name of /models/predictions (TH_LOGREG, Kronos-small, Chronos-2, Granite TTM, gold_candles)
  async signals_pred_match() {
    const ids = ["th_logreg", "kronos", "chronos2", "granite_ttm", "gold_forecast", "mm_breakout"];
    const names = ["TH_LOGREG", "Kronos-small", "Chronos-2", "Granite TTM", "gold_candles", "research:graph50:H3"];
    const r = await signals({ "/api/v1/bot-signals?limit=200": { items: [sig({ action: "BUY" })] },
      "/api/v1/models/catalog?instrument=XAUUSD": { items: ids.map((id) => ({ id, name: id, group: "G", category: "TRAINABLE", state: "READY" })) },
      "/api/v1/models/predictions?instrument=XAUUSD": { items: names.map((model_name) => ({ model_name, state: "READY", unit: "price", result: { direction: "UP" } })) } });
    const byId_ = Object.fromEntries(rowsOf(r.box).map((e) => [all(e).find((x) => x.className === "mn").getAttribute("title"), e.getAttribute("data-a")]));
    assert.deepEqual(byId_, { th_logreg: "1", kronos: "1", chronos2: "1", granite_ttm: "1", gold_forecast: "1", mm_breakout: "" });
    assert.match(q(r.box, "signals-detail").textContent, /5 ZGODNE/);
    await r.unmount();
  },
  // chunk_46#6: settled bot signals (WIN / LOSS / TIMEOUT) are history, SH READY is active, SH WAIT is not active, NO_TRADE is history
  async signals_status_sets() {
    const now = nowSec();
    const bot = ["OPEN", "WIN", "LOSS", "TIMEOUT", "REJECTED"].map((st, i) => sig({ signal_id: "B" + i, status: st, created_at: now - 60 * (i + 1) }));
    const sh = ["READY", "WAIT", "NO_TRADE", "EXPIRED"].map((st, i) => ({ signal_id: "H" + i, strategy: "SCALPING", strategy_id: "PMW_SC01", signal_tf: "M1",
      side: "BUY", status: st, created_at: now - 30 * (i + 1), levels: null, plan: null }));
    const r = await signals({ "/api/v1/bot-signals?limit=200": { items: bot }, "/api/v1/sh/signals?limit=200": { items: sh } });
    assert.match(byId(r.box, "sg-count").textContent, /2 AKTYWNYCH/);
    await click(tabBtn(r.box, "NA ŻYWO"));
    assert.deepEqual(listLc(r.box).sort(), ["OPEN", "READY"]);
    await click(tabBtn(r.box, "HISTORIA"));
    assert.deepEqual(listLc(r.box).sort(), ["EXPIRED", "LOSS", "NO_TRADE", "REJECTED", "TIMEOUT", "WIN"]);
    const labels = all(q(r.box, "signals-list")).filter((e) => e.className === "lc").map((e) => e.textContent);
    for (const raw of ["WIN", "LOSS", "TIMEOUT", "NO_TRADE"]) assert.ok(!labels.includes(raw), `${raw} has no Polish label: ${labels.join("|")}`);
    await r.unmount();
  },
  // chunk_46#7: the TRYB gate is computed from mode_gate (allowed / reason_codes), never "[object Object]"
  async signals_mode_gate() {
    const r = await signals({ "/api/v1/decision": { decision: "WAIT", data_quality: "OK", market_state: "OPEN", risk: { risk_gate: "PASS" }, execution_permission: "BLOCKED",
      agent_gate: { reason_codes: ["AGENT_NOT_RUNNING"] }, mode_gate: { mode: "AUTO_DEMO", allowed: false, auto_trading: true, kill_switch: false, reason_codes: ["NEW_ENTRIES_STOPPED"] } } });
    const g = q(r.box, "signals-gates");
    assert.ok(!/object Object/.test(g.textContent), g.textContent);
    const tryb = all(g).find((e) => e.className === "gt" && /TRYB/.test(e.textContent));
    assert.match(tryb.textContent, /BLOCKED/);
    assert.equal(tryb.getAttribute("data-st"), "BLOK");
    await r.unmount();
    const r2 = await signals({ "/api/v1/decision": { decision: "ENTER", mode_gate: { mode: "AUTO_DEMO", allowed: true, reason_codes: [] }, agent_gate: { status: "ALLOW" } } });
    const t2 = all(q(r2.box, "signals-gates")).find((e) => e.className === "gt" && /TRYB/.test(e.textContent));
    assert.match(t2.textContent, /ALLOWED/);
    assert.equal(t2.getAttribute("data-st"), "OK");
    await r2.unmount();
  },
  // chunk_46#8: SH signals read the /sh/signals shape (signal_tf, levels.entry / sl / targets, plan.r_multiple, strategy_id)
  async signals_sh_fields() {
    const sh = { signal_id: "H1", strategy: "SCALPING", strategy_id: "PMW_SC01", signal_tf: "M1", instrument: "XAUUSD", side: "SELL", status: "READY", created_at: nowSec() - 60,
      levels: { side: "SELL", entry: 2000, sl: 2004, targets: [{ name: "TP1", price: 1996, share: 0.5 }, { name: "TP2", price: 1992, share: 0.5 }], net_rr: 1.4 },
      plan: { plan_id: "P1", state: "CLOSED", tp_done: ["TP1"], close_reason: "TP2", closed_at: nowSec(), r_multiple: 1.25 } };
    const r = await signals({ "/api/v1/sh/signals?limit=200": { items: [sh] } });
    const d = q(r.box, "signals-detail");
    assert.match(d.textContent, /WEJŚCIE2000,00SL2004,00TP11996,00TP21992,00WYNIK1,25 R/);
    assert.match(byId(r.box, "sg-dh").textContent, /SC01/);
    assert.match(byId(r.box, "sg-dh").textContent, /M1 · maszyna SH/);
    await click(tabBtn(r.box, "WYNIKI"));
    assert.match(byId(r.box, "sg-alt").textContent, /1 ZAMKNIĘTYCH · SUMA \+1,25 R/);
    await r.unmount();
  },
  // chunk_46#3: registry versions (TH_LOGREG_M5_H6) belong to the catalog model th_logreg (case-insensitive, with the "_" separator)
  async models_versions_case() {
    const r = await models({
      "/api/v1/models/catalog?instrument=XAUUSD": { items: [{ id: "th_logreg", name: "TH LOGREG", group: "TH", category: "TRAINABLE", state: "READY" },
        { id: "mm_breakout", name: "MM", group: "MM", category: "INDICATOR", state: "DISABLED" }] },
      "/api/v1/trainhub/registry?instrument=XAUUSD": { active: { TH_LOGREG_M5_H6: "v1" }, versions: [{ model_key: "TH_LOGREG_M5_H6", version: "v1", active: true, created_at: "2026-11-20T10:00:00Z",
        holdout: { skill_vs_baseline: 0.05, brier: 0.2, ece: 0.01, log_loss: 1.0, baseline_log_loss: 1.05, accuracy: 0.4, balanced_accuracy: 0.39 },
        walk_forward: { mean_log_loss: 1.01, std_log_loss: 0.02, folds_beating_baseline: 3 } },
        { model_key: "MM_BREAKOUT_ZONES_M5_H6", version: "v9", active: true, holdout: { skill_vs_baseline: 0.5 } }] } });
    const det = q(r.box, "models-detail");
    assert.match(det.textContent, /SKILL VS BAZOWY/);
    assert.match(det.textContent, /WALK-FORWARD/);
    assert.ok(!/NOT_RUN/.test(det.textContent), det.textContent);
    const sk = all(q(r.box, "models-list")).filter((e) => e.className === "sk").map((e) => e.textContent);
    assert.deepEqual(sk, ["+5,0%", ""], "skill of th_logreg / nothing for mm_breakout (MM_BREAKOUT_ZONES_* is another model)");
    await r.unmount();
  },
  // chunk_46#4: BACKTEST reads the replay report (metrics / variants / baseline) of VERIFIED_REPLAY; NOT_RUN only for status NOT_RUN
  async models_backtest_report() {
    const m = (n, wr, pf, tot, exp, dd) => ({ n, win_rate: wr, profit_factor: pf, total: tot, expectancy: exp, max_drawdown: dd });
    const r = await models({ "/api/v1/sh/validation?instrument=XAUUSD": { instrument: "XAUUSD", strategies: {
      SCALPING: { status: "VERIFIED_REPLAY", report: { strategy: "SCALPING", metrics: m(40, 0.55, 1.3, 5.2, 0.13, 2.1), baseline: m(50, 0.4, 0.8, -3, -0.06, 6), folds: [] } },
      HEDGING: { status: "NOT_RUN", reason: "brak raportu walidacji" } } } });
    await click(q(r.box, "models-tab-bt"));
    const bt = q(r.box, "models-bt");
    assert.ok(bt, "backtest tab");
    const txt = bt.textContent;
    assert.match(txt, /REPLAY SCALPINGVERIFIED_REPLAY/);
    assert.match(txt, /STRATEGIA405?5,0/, txt);
    assert.match(txt, /1,30/);
    assert.match(txt, /5,20/);
    assert.match(txt, /BAZOWY5040,00?/, txt);
    assert.ok(!/NOT_RUN – brak raportu replay/.test(txt), txt);
    assert.match(txt, /NOT_RUN – brak raportu walidacji/);
    await r.unmount();
    const r2 = await models({ "/api/v1/sh/validation?instrument=XAUUSD": { strategies: { HEDGING: { status: "VERIFIED_REPLAY", report: { strategy: "HEDGING",
      variants: { NO_HEDGE: m(30, 0.5, 1.1, 1, 0.03, 2), REDUCE: m(30, 0.52, 1.2, 2, 0.06, 1.5), HEDGE: m(30, 0.53, 1.25, 3, 0.1, 1.2) },
      metrics: m(30, 0.53, 1.25, 3, 0.1, 1.2), baseline: { n: 0 } } }, SCALPING: { status: "ERROR", reason: "zły JSON" } } } });
    await click(q(r2.box, "models-tab-bt"));
    const t2 = q(r2.box, "models-bt").textContent;
    for (const v of ["NO_HEDGE", "REDUCE", "HEDGE", "BAZOWY"]) assert.ok(t2.includes(v), v + " missing: " + t2);
    assert.match(t2, /BŁĄD – zły JSON/);
    await r2.unmount();
  },
  // chunk_46#9: BTC on a TF the bars endpoint does not accept (400 INVALID_TF) - no ROZŁĄCZONO, layers still loaded, the reason is shown
  async charts_btc_tf_unsupported() {
    const fc = fakeCharts({ asset: "BTC", tf: "H1", kr: "M5" });
    const calls = mockApi({ ...CHART_GET, "/api/v1/market-zones/bars*": () => new ApiError(400, "INVALID_TF:H1") });
    const h = await chartsHook(fc, { connection: { state: "CONNECTED" }, barTick: {} });
    assert.ok(calls.get.some((p) => p.startsWith("/api/v1/market-zones/bars?instrument=BTC&tf=H1")));
    assert.ok(!fc.log.status.includes("offline"), "unsupported TF reported as ROZŁĄCZONO: " + fc.log.status.join(","));
    const vm = fc.log.vm.pop();
    assert.ok(vm, "view model not set - the whole load failed");
    assert.equal(vm.asset, "BTC"); assert.equal(vm.tf, "H1");
    assert.deepEqual(vm.candles, []);
    assert.notEqual(vm.status, "offline");
    assert.match(String(vm.zoneMsg), /H1/);
    assert.match(String(vm.zoneMsg), /TIMEFRAME_NOT_SUPPORTED/);
    await h.unmount();
    // a network failure of the bars request still means offline
    const fc2 = fakeCharts({ asset: "BTC", tf: "M5", kr: "M5" });
    mockApi({ ...CHART_GET, "/api/v1/market-zones/bars*": () => new TypeError("Failed to fetch") });
    const h2 = await chartsHook(fc2, { connection: { state: "CONNECTED" }, barTick: {} });
    assert.ok(fc2.log.status.includes("offline"));
    await h2.unmount();
  },
  // chunk_46#12 (CHARTS): one reload per bar close - batched bar_closed+bar triggers it, a non-batched pair does not trigger it twice
  async charts_bar_close_once() {
    const loads = (calls) => calls.get.filter((p) => p === "/api/v1/candles?tf=M15").length;
    const kr = (calls) => calls.get.filter((p) => p.startsWith("/api/v1/kronos/forecast")).length;
    const fc = fakeCharts();
    const calls = mockApi(CHART_GET);
    const s0 = { connection: { state: "CONNECTED" }, barTick: { M15: bar(9000, false, 1), M5: bar(9000, false, 1) } };
    const h = await chartsHook(fc, s0);
    const n0 = loads(calls), k0 = kr(calls);
    await h.set(true, { ...s0, barTick: { ...s0.barTick, M15: bar(9000, true, 2) } });      // bar_closed
    await h.set(true, { ...s0, barTick: { ...s0.barTick, M15: bar(9900, false, 3) } });     // bar of the new candle
    assert.equal(loads(calls) - n0, 1, "non-batched bar_closed + bar must reload once");
    await h.set(true, { ...s0, barTick: { ...s0.barTick, M15: bar(10800, false, 5) } });    // bar_closed (seq 4) batched away
    assert.equal(loads(calls) - n0, 2, "batched bar_closed must still reload the candles");
    await h.set(true, { ...s0, barTick: { ...s0.barTick, M15: bar(10800, false, 6) } });    // same candle ticking
    assert.equal(loads(calls) - n0, 2);
    await h.set(true, { ...s0, barTick: { M15: bar(10800, false, 6), M5: bar(9300, false, 7) } });   // Kronos TF M5: batched close
    assert.equal(kr(calls) - k0, 1, "Kronos must reload after a batched close of its TF");
    await h.unmount();
  },
  // chunk_46#13: the renderer listener is removed when CHARTS is left (no accumulation on re-entry)
  async charts_onselect_unsubscribe() {
    const fc = fakeCharts();
    mockApi(CHART_GET);
    const s = { connection: { state: "CONNECTED" }, barTick: {} };
    const h = await chartsHook(fc, s, true);
    await h.set(false, s); await h.set(true, s); await h.set(false, s); await h.set(true, s);
    assert.equal(fc.listeners.length, 1, "listeners accumulate: " + fc.listeners.length);
    await h.unmount();
    assert.equal(fc.listeners.length, 0);
  },
  // chunk_46#14: S01-S12 signals come from the list record (detail is in it) - no per-signal GET, no unbounded module cache
  async charts_legacy_from_list() {
    const fc = fakeCharts();
    const row = { signal_id: "L1", strategy_id: "S03", timeframe: "M15", action: "BUY", entry_price: 2000, stop_loss: 1995, take_profits: [2006], status: "OPEN",
      created_at: "2026-11-24T10:00:00Z", detail: { source_time: "2026-11-24T09:45:00Z", reason_codes: ["X"] } };
    const calls = mockApi({ ...CHART_GET, "/api/v1/bot-signals?*": { items: [row] }, "/api/v1/bot-signals/*": () => ({ ...row }) });
    const h = await chartsHook(fc, { connection: { state: "CONNECTED" }, barTick: {} });
    assert.equal(calls.get.filter((p) => /^\/api\/v1\/bot-signals\/[^?]/.test(p)).length, 0, "per-signal detail GET");
    const vm = fc.log.vm.pop();
    const lg = vm.signals.filter((x) => x.src === "LEGACY");
    assert.equal(lg.length, 1);
    assert.equal(lg[0].t, Date.parse("2026-11-24T09:45:00Z"));
    assert.deepEqual(lg[0].why, ["X"]);
    const src = fs.readFileSync(path.join(FX, "screens", "charts", "chartsData.ts"), "utf8");
    assert.ok(!/legacyDetail/.test(src), "module-level legacyDetail cache still present");
    await h.unmount();
  },
  // chunk_44#0: a zone whose start is not exactly a candle open (live FVG / OB at the observed close time) is drawn from the containing candle
  async zones_between_candles() {
    const { ZonesPrimitive } = await imp(path.join(SRC, "zones.ts"));
    const t0 = 1795000000 - (1795000000 % 300);
    const times = Array.from({ length: 40 }, (_, i) => t0 + i * 300);
    const fc = fakeChart(times);
    const z = new ZonesPrimitive();
    z.setZones([{ from: times[13] + 1.734211, low: 100, high: 110, color: "c", border: "b", label: "FVG" }, { from: times[5], low: 100, high: 110, color: "c", border: "b", label: "OB" }]);
    const rects = drawPrim(z, fc).filter((o) => o[0] === "fillRect");
    assert.equal(rects.length, 2, "zone with a start between candles skipped");
    const x = rects.map((o) => o[1]).sort((a, b) => a - b);
    assert.equal(x[0], fc.X(5));
    assert.ok(x[1] >= fc.X(13) && x[1] < fc.X(14), "from the containing candle: " + x[1]);
  },
  // chunk_44#1: bounded boxes / segments / markers between candles (M5 session geometry on an H1 chart) are interpolated, not dropped
  async boxes_between_candles() {
    const { BoundedBoxesPrimitive } = await imp(path.join(SRC, "zones.ts"));
    const t0 = 1795000000 - (1795000000 % 3600);
    const times = Array.from({ length: 30 }, (_, i) => t0 + i * 3600);
    const fc = fakeChart(times);
    const b = new BoundedBoxesPrimitive();
    const from = times[10] + 20 * 60, to = times[15] + 30 * 60;             // 13:20 - 18:30 on H1
    b.set([{ from, to, low: 100, high: 110, color: "c", border: "b", label: "NEW_YORK" }, { from: times[3], to: times[4] + 1, low: 105, high: 105, color: "c", border: "b" }],
      [{ time: times[20] + 25 * 60, price: 104, label: "SWEEP", color: "c", up: true }, { time: times[0] - 1800, price: 104, label: "OLD", color: "c", up: true }]);
    const ops = drawPrim(b, fc);
    const rect = ops.find((o) => o[0] === "fillRect");
    assert.ok(rect, "box between candles skipped");
    assert.ok(Math.abs(rect[1] - (fc.X(10) + 10 * (20 / 60))) < 1e-6, "x1 interpolated: " + rect[1]);
    assert.ok(Math.abs(rect[1] + rect[3] - (fc.X(15) + 10 * 0.5)) < 1e-6, "x2 interpolated");
    assert.ok(ops.some((o) => o[0] === "lineTo" && Math.abs(o[1] - (fc.X(4) + 10 / 3600)) < 1e-6), "segment ending between candles drawn");
    const mk = ops.find((o) => o[0] === "fillText" && o[1] === "SWEEP");
    assert.ok(mk, "marker between candles skipped");
    assert.ok(Math.abs(mk[2] - 5 - (fc.X(20) + 10 * (25 / 60))) < 1e-6, "marker x interpolated");
    assert.ok(!ops.some((o) => o[0] === "fillText" && o[1] === "OLD"), "a marker before the first candle has no candle to sit on");
    const src = fs.readFileSync(path.join(SRC, "zones.ts"), "utf8");
    assert.ok(!/lr \? null : null/.test(src), "dead interpolation stub still present");
  },
  // chunk_46#16: dead code of the FOREX engine removed; the module still parses and its no-WebGL stub works
  async engine_dead_code() {
    const src = fs.readFileSync(path.join(FX, "engine", "forexEngine.ts"), "utf8");
    for (const re of [/for\(const b of \[\]\)/, /function makeBolt/, /FIXED_DT/, /pmw:forex-section-selected/, /nie jest jeszcze zaprojektowany/, /focusDone/, /updatePanel\(p,dt,nowS\)/])
      assert.ok(!re.test(src), "dead code still present: " + re);
    const { mountForex } = await imp(path.join(FX, "engine", "forexEngine.ts"));
    const canvas = { getContext: () => null, addEventListener() {} };
    let no = false;
    const stub = mountForex({ querySelector: (s) => (s === "#c" ? canvas : null), querySelectorAll: () => [], dataset: {} }, { onNoWebGL: () => { no = true; } });
    assert.equal(no, true);
    assert.equal(typeof stub.setScreenData, "function");
  },
};

const want = process.argv.slice(2).filter((a) => !a.startsWith("--"));
let bad = 0;
for (const name of want.length ? want : Object.keys(CASES)) {
  const fn = CASES[name];
  if (!fn) { console.log(`${name} FAIL: unknown case`); bad++; continue; }
  try { await fn(); console.log(`${name} OK`); } catch (e) { bad++; console.log(`${name} FAIL: ${e?.stack || e}`); }
}
process.exit(bad ? 1 : 0);
