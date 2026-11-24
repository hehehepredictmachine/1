// 1.46 audit (group D_frontend_1): api.ts LiveSocket, Settings / Mode / Power dialogs, leverage limit, error boundary, 1.41 panels,
// appearance layer, cinematic menu (React wrapper + menuEngine) and menu shaders - in Node, without a browser.
// Usage: node --experimental-strip-types --no-warnings tests/js/audit146_d_frontend_1.test.mjs <case> [case ...]
// React components are rendered with the real react-dom/client into a minimal DOM stub; .ts/.tsx sources are transpiled with the project's own
// TypeScript; api.ts / telemetry.ts / store.tsx (and menuEngine.ts for the CinematicMenu wrapper only) are replaced by in-memory mocks.
// menuEngine.ts itself runs on a second, event-only element stub with the CPU renderer (or a failing WebGL context) and a manual RAF queue.
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

// ---------------------------------------------------------------- module hooks: TS/TSX transpile, CSS / media stubs, api/telemetry/store mocks
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
  [path.join(SRC, "features", "cinematic", "menuEngine.ts")]: data(`
    export const PREPARING_NOTE = "Tryb w przygotowaniu";
    export function mountMenu(el, opts) { globalThis.__mock.menu = { el, opts, disposed: false }; return () => { globalThis.__mock.menu.disposed = true; }; }`),
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

// ---------------------------------------------------------------- minimal DOM for react-dom/client (same stub as audit146_d_frontend_4)
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
  pause() { /* <video> of the CinematicMenu */ }
  load() { /* <video> of the CinematicMenu */ }
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
globalThis.location = { host: "127.0.0.1", hash: "#/menu", reload() { this.reloads = (this.reloads || 0) + 1; } };
globalThis.history = { replaceState(_s, _t, h) { globalThis.location.hash = h; } };
const store = new Map();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: (k) => { store.delete(k); },
  clear: () => store.clear() } });
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
  return { box, root, errors, unmount: async () => { await act(async () => root.unmount()); box.parentNode?.removeChild(box); } };
}
const q = (root, testid) => all(root).find((e) => e.getAttribute("data-testid") === testid) || null;
const byText = (root, tag, re) => all(root).find((e) => e.tagName === tag.toUpperCase() && re.test(e.textContent)) || null;
const props = (el) => el[Object.keys(el).find((k) => k.startsWith("__reactProps"))];
async function click(el) { assert.ok(el, "element to click not found"); await act(async () => { fire(el, "click"); }); await flush(); }
function mockApi({ get = {}, send = () => ({}), s = {} } = {}) {
  const calls = { get: [], send: [], refresh: 0 };
  globalThis.__mock = {
    calls,
    store: { s: { loaded: true, ...s }, refresh: async () => { calls.refresh += 1; } },
    initSession: async () => undefined,
    apiGet: async (p) => {
      calls.get.push(p);
      const h = Object.entries(get).find(([k]) => p === k || (k.endsWith("*") && p.startsWith(k.slice(0, -1))));
      if (!h) throw new Error("404 " + p);
      return typeof h[1] === "function" ? h[1](p) : JSON.parse(JSON.stringify(h[1]));
    },
    apiSend: async (m, p, body) => { calls.send.push({ m, p, body: body === undefined ? undefined : JSON.parse(JSON.stringify(body)) }); return send(m, p, body); },
  };
  return calls;
}
async function quiet(fn) {          // React / the engine log expected errors with console.error
  const ce = console.error, cw = console.warn; console.error = () => {}; console.warn = () => {};
  try { return await fn(); } finally { console.error = ce; console.warn = cw; }
}
const SIDS = Array.from({ length: 12 }, (_, i) => "S" + String(i + 1).padStart(2, "0"));
const CFG = (extra = {}) => ({ config: { first_run_completed: false, mt5: { symbol: "XAUUSD" }, agent: { model: null }, risk: {}, costs: {}, strategy: {},
  active: { profile: "ACTIVE", strategy_mode: "AUTO", manual_strategy_id: null, thresholds: {}, strategies: Object.fromEntries(SIDS.map((id) => [id, { scan: true, trade: true }])) },
  execution: {}, news: {}, telegram: {}, volatility: null, markets: null, signals: {}, ...extra }, secrets: {} });

// ---------------------------------------------------------------- event-only element stub for menuEngine.ts (no React)
class EE {
  constructor(env, tag = "div", parent = null) {
    this.env = env; this.tagName = tag.toUpperCase(); this.nodeType = 1; this.parentNode = parent; this.hidden = false; this.dataset = {}; this.attrs = {};
    this.listeners = {}; this.textContent = ""; this.innerHTML = ""; this.inert = false;
    const st = { setProperty(k, v) { st[k] = v; }, removeProperty(k) { delete st[k]; } }; this.style = st;
    const cl = new Set(); this.classList = { add: (c) => cl.add(c), remove: (c) => cl.delete(c), contains: (c) => cl.has(c) };
    env?.els.push(this);
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f, o) {
    const a = (this.listeners[t] ||= []); const rec = { f }; a.push(rec);
    o?.signal?.addEventListener("abort", () => { const i = a.indexOf(rec); if (i >= 0) a.splice(i, 1); });
  }
  removeEventListener(t, f) { const a = this.listeners[t] || []; const i = a.findIndex((r) => r.f === f); if (i >= 0) a.splice(i, 1); }
  dispatch(t, extra = {}) {
    const ev = { type: t, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
    for (const l of [...(this.listeners[t] || [])]) l.f(ev);
    return ev;
  }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  focus() { if (this.env) this.env.doc.activeElement = this; }
  setPointerCapture() {} hasPointerCapture() { return false; } releasePointerCapture() {}
}
// Sets the browser globals menuEngine.ts uses, mounts it and returns helpers; restore() puts the React stub globals back.
async function engine({ webgl = null, ctx2d = true, video = {}, ...opts } = {}) {
  const env = { els: [] };
  const saved = { document: globalThis.document, add: globalThis.addEventListener, rem: globalThis.removeEventListener, raf: globalThis.requestAnimationFrame,
    caf: globalThis.cancelAnimationFrame, iw: globalThis.innerWidth, ih: globalThis.innerHeight, dpr: globalThis.devicePixelRatio, loc: globalThis.location };
  const edoc = new EE(env, "#document"); env.doc = edoc;
  edoc.hidden = false; edoc.fullscreenElement = null; edoc.documentElement = new EE(env, "html"); edoc.body = new EE(env, "body", edoc.documentElement); edoc.activeElement = edoc.body;
  edoc.querySelector = (sel) => { const m = /^\[([\w-]+)="([^"]*)"\]$/.exec(sel); return m ? env.els.find((e) => e.attrs[m[1]] === m[2]) || null : null; };
  const win = new EE(null, "window");
  const raf = new Map(); let rafId = 0;
  globalThis.document = edoc;
  globalThis.addEventListener = win.addEventListener.bind(win); globalThis.removeEventListener = win.removeEventListener.bind(win);
  globalThis.requestAnimationFrame = (f) => { raf.set(++rafId, f); return rafId; };
  globalThis.cancelAnimationFrame = (id) => { raf.delete(id); };
  globalThis.innerWidth = 40; globalThis.innerHeight = 30; globalThis.devicePixelRatio = 1;
  globalThis.location = { host: "127.0.0.1", hash: "#/menu", reload() { this.reloads = (this.reloads || 0) + 1; } };
  const root = new EE(env, "div"); root.dataset.state = "boot";
  const mk = (tag = "div") => new EE(env, tag, root);
  const canvas = mk("canvas");
  canvas.getContext = (kind) => (kind === "2d" ? (ctx2d ? { createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }), putImageData() {} } : null) : webgl);
  const v = mk("video");
  const vcalls = { play: 0, release: 0, dispose: 0 };
  Object.assign(v, { currentTime: 0, duration: 10, muted: false, readyState: 4, paused: true,
    play() { vcalls.play += 1; const p = video.play ? video.play(vcalls.play) : Promise.resolve(); this.paused = false; return p; },
    pause() { this.paused = true; }, load() {}, release() { vcalls.release += 1; }, dispose() { vcalls.dispose += 1; } });
  const el = { root, canvas, video: v, cinema: mk(), menu: mk("main"), selected: mk("section"), selectedName: mk("h2"), selectedNote: mk("p"), returnBtn: mk("button"),
    skip: mk("button"), videoStart: mk("button"), progress: mk(), progressBar: mk("span"), notice: mk(), announcer: mk(), rendererError: mk(), rendererMessage: mk("p"),
    rendererRetry: mk("button"), buttons: [mk("button"), mk("button"), mk("button")], replay: mk("button"), sound: mk("button"), motion: mk("button"), fullscreen: mk("button") };
  el.rendererError.hidden = true; el.videoStart.hidden = true;
  const { mountMenu, PREPARING_NOTE } = await import(pathToFileURL(path.join(SRC, "features", "cinematic", "menuEngine.ts")).href);
  const dispose = await quiet(() => mountMenu(el, { playIntro: false, reduced: false, ...opts }));
  const frames = (n = 1, stepMs = 300) => { for (let i = 0; i < n; i++) { const cbs = [...raf.values()]; raf.clear(); const now = performance.now() + stepMs; for (const f of cbs) f(now); } };
  const key = (k, code, extra = {}) => edoc.dispatch("keydown", { key: k, code, ctrlKey: false, metaKey: false, altKey: false, target: edoc.body, ...extra });
  const restore = () => {
    try { dispose(); } catch { /* already failed */ }
    Object.assign(globalThis, { document: saved.document, addEventListener: saved.add, removeEventListener: saved.rem, requestAnimationFrame: saved.raf,
      cancelAnimationFrame: saved.caf, innerWidth: saved.iw, innerHeight: saved.ih, devicePixelRatio: saved.dpr, location: saved.loc });
  };
  return { env, el, edoc, win, raf, frames, key, vcalls, dispose, restore, PREPARING_NOTE, mkOutside: (tag = "div", parent = null) => new EE(env, tag, parent) };
}
const failingWebGL = () => ({ VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, createShader() { throw new Error("GL_CONTEXT_LOST_ON_CREATE"); }, getExtension() { return null; } });

const CASES = {
  // chunk_43#6: LiveSocket.stop() during the reconnect back-off must not open an orphan WebSocket later
  async live_socket_stop_cancels_reconnect() {
    const sockets = [];
    class FakeWS {
      constructor(url) { this.url = url; sockets.push(this); }
      send() {}
      close() { if (this.closed) return; this.closed = true; queueMicrotask(() => this.onclose?.({ code: 1000 })); }
    }
    const timers = new Map(); let tid = 0;
    const saved = { ws: globalThis.WebSocket, st: globalThis.setTimeout, ct: globalThis.clearTimeout, loc: globalThis.location };
    globalThis.WebSocket = FakeWS;
    globalThis.setTimeout = (f, ms) => { timers.set(++tid, { f, ms }); return tid; };
    globalThis.clearTimeout = (id) => { timers.delete(id); };
    globalThis.location = { host: "127.0.0.1:8781", reload() { this.reloads = (this.reloads || 0) + 1; } };
    try {
      const { LiveSocket } = await import(pathToFileURL(path.join(SRC, "api.ts")).href);
      const st = [];
      const s = new LiveSocket(() => {}, (x) => st.push(x));
      s.start();
      assert.equal(sockets.length, 1);
      sockets[0].closed = true; sockets[0].onclose({ code: 1006 });        // connection dropped -> reconnect scheduled (back-off)
      assert.equal(timers.size, 1, "reconnect not scheduled");
      s.stop();                                                             // StoreProvider unmounted (licence screen) during the back-off
      await new Promise((r) => saved.st(r, 0));
      for (const [id, t] of [...timers]) { timers.delete(id); t.f(); }
      assert.equal(sockets.length, 1, "stop() did not cancel the scheduled reconnect - an orphan WebSocket was opened");
      // a fresh start() still connects (stop/start of the same instance)
      s.start();
      assert.equal(sockets.length, 2);
      s.stop();
    } finally {
      Object.assign(globalThis, { WebSocket: saved.ws, setTimeout: saved.st, clearTimeout: saved.ct, location: saved.loc });
    }
  },
  // chunk_43#17 (api.ts part): getCsrf() had no caller; LEGACY_PRODUCT (brand.ts) / mq.lastHash (router.ts) are outside this group
  async api_dead_exports() {
    const M = await import(pathToFileURL(path.join(SRC, "api.ts")).href);
    assert.equal(M.getCsrf, undefined, "unused getCsrf() still exported");
    for (const k of ["initSession", "apiGet", "apiSend", "apiUpload", "LiveSocket", "ApiError"]) assert.equal(typeof M[k], "function", k);
  },
  // chunk_43#2: "Zakończ konfigurację" must not close the window when PUT /api/v1/config was rejected
  async settings_finish_failed_keeps_open() {
    let fail = true;
    const calls = mockApi({ get: { "/api/v1/config": CFG() }, send: (m, p, body) => {
      if (p === "/api/v1/config" && fail) throw new Error("INVALID_CONFIG: risk.max_drawdown_pct");
      return { config: { ...CFG().config, ...body, first_run_completed: true } };
    } });
    const { SettingsModal } = await imp("components/Dialogs.tsx");
    let closed = 0;
    const r = await render(React.createElement(SettingsModal, { onClose: () => { closed += 1; } }));
    await click(byText(r.box, "button", /^Zakończ konfigurację$/));
    assert.equal(calls.send.filter((c) => c.p === "/api/v1/config").length, 1);
    assert.equal(closed, 0, "the first-run window closed although the configuration was NOT saved");
    assert.match(r.box.textContent, /Błąd: INVALID_CONFIG/);
    fail = false;
    await click(byText(r.box, "button", /^Zakończ konfigurację$/));
    assert.equal(closed, 1, "a successful save must close the window");
    await r.unmount();
  },
  // chunk_43#3: a failed STOP (403 CSRF / 402 / 500) must say so; a successful one refreshes the state (button label)
  async power_stop_failure_reported() {
    let fail = true;
    const calls = mockApi({ s: { mode: { kill_switch: false } }, send: (m, p) => { if (p === "/api/v1/kill" && fail) throw new Error("CSRF_INVALID"); return { ok: true }; } });
    const { PowerDialog } = await imp("components/Dialogs.tsx");
    const r = await render(React.createElement(PowerDialog, { onClose() {} }));
    rejections.length = 0;
    await click(byText(r.box, "button", /STOP nowych wejść/));
    await flush();
    assert.deepEqual(rejections.map(String), [], "unhandled promise rejection from the STOP button");
    assert.match(r.box.textContent, /STOP NIE (został )?wykonany.*CSRF_INVALID/);
    assert.doesNotMatch(r.box.textContent, /Nowe wejścia zatrzymane/);
    fail = false;
    await click(byText(r.box, "button", /STOP nowych wejść/));
    assert.match(r.box.textContent, /Nowe wejścia zatrzymane/);
    assert.ok(calls.refresh >= 1, "state not refreshed after a successful STOP (button label stays stale)");
    await r.unmount();
  },
  // chunk_43#7: RĘCZNIE - the value shown in the <select> is the value that is saved (no hidden 30 behind a visible 1:1)
  async leverage_select_matches_saved() {
    const calls = mockApi({ s: { account: { login: 1 } }, get: { "/api/v1/prefs": { leverage: { mode: "AUTO", limit: null }, exposure: { account_leverage: 20, limit: 20 },
      leverage_choices: [1, 2, 5, 10, 20, 30, 50, 100], account_key: "1@srv" } }, send: () => ({ leverage: { mode: "MANUAL", limit: 20 }, exposure: { account_leverage: 20, limit: 20 } }) });
    const { LeverageSettings } = await imp("components/LeverageSettings.tsx");
    const r = await render(React.createElement(LeverageSettings));
    const manual = all(byText(r.box, "label", /RĘCZNIE/)).find((e) => e.tagName === "INPUT");
    manual.checked = true;
    await click(manual);
    const sel = q(r.box, "lev-select");
    assert.ok(sel, "manual select not shown");
    const opts = sel.options.map((o) => String(o.value));
    assert.deepEqual(opts, ["1", "2", "5", "10", "20"]);
    const shown = String(props(sel).value);
    assert.ok(opts.includes(shown), `select value ${shown} is not one of its options ${opts.join(",")} (the browser shows the first option instead)`);
    await click(q(r.box, "lev-save"));
    const s = calls.send.filter((c) => c.p === "/api/v1/prefs/leverage");
    assert.equal(s.length, 1);
    assert.equal(String(s[0].body.limit), shown, "saved limit differs from the option shown in the select");
    assert.ok(s[0].body.limit <= 20);
    await r.unmount();
  },
  // chunk_45#0: renderer failure (setup error / context lost) keeps STOP and the system icons visible; retry falls back to the CPU renderer
  async menu_renderer_error_state() {
    let e = await engine({ webgl: failingWebGL(), playIntro: true });
    try {
      assert.equal(e.el.rendererError.hidden, false, "renderer error overlay not shown");
      assert.equal(e.el.root.dataset.state, "error", "data-state stays '" + e.el.root.dataset.state + "' - CSS hides .sys-icons (STOP) in boot/enter");
      e.el.cinema.dispatch("click"); e.win.dispatch("pointermove", { clientX: 1, clientY: 1 });
      e.frames(2);                                           // no tick on a missing renderer (gl!.clear on null)
      e.el.replay.dispatch("click");
      assert.equal(e.el.root.dataset.state, "error", "'Odtwórz intro' left the error state (hides STOP again)");
      e.el.rendererRetry.dispatch("click");
      assert.equal(globalThis.location.reloads, 1);
      assert.match(globalThis.location.hash, /^#\/menu\?renderer=cpu$/, "retry reloads the same (failing) WebGL configuration");
    } finally { e.restore(); }
    // the CPU renderer itself failed: plain reload (no loop to the same parameter)
    e = await engine({ webgl: null, ctx2d: false, forceSoftware: true });
    try {
      assert.equal(e.el.root.dataset.state, "error");
      e.el.rendererRetry.dispatch("click");
      assert.equal(globalThis.location.reloads, 1);
      assert.equal(globalThis.location.hash, "#/menu");
    } finally { e.restore(); }
    // context lost during the intro (boot): error state, the watchdog must not move it to enter
    e = await engine({ forceSoftware: true, playIntro: true });
    try {
      assert.equal(e.el.root.dataset.state, "boot");
      await quiet(() => e.el.canvas.dispatch("webglcontextlost"));
      assert.equal(e.el.root.dataset.state, "error");
      e.el.video.dispatch("ended");
      assert.equal(e.el.root.dataset.state, "error");
      e.el.canvas.dispatch("webglcontextrestored");
      assert.equal(e.el.root.dataset.state, "menu", "restored context returns to the menu");
      assert.equal(e.el.rendererError.hidden, true);
    } finally { e.restore(); }
  },
  // chunk_45#1 (engine part): FOREX hand-off gets an AbortSignal that POWRÓT / Esc / replay / dispose cancel; the note says what is happening
  async menu_forex_handoff_cancel() {
    const got = [];
    const e = await engine({ forceSoftware: true, reduced: true, onForexReady: (...a) => got.push(a) });
    try {
      assert.equal(e.el.root.dataset.state, "menu");
      e.el.buttons[0].dispatch("click");
      e.frames(3);
      assert.equal(e.el.root.dataset.state, "selected");
      assert.equal(got.length, 1, "onForexReady not called");
      const sig = got[0][1];
      assert.ok(sig && typeof sig.aborted === "boolean", "onForexReady got no AbortSignal - App cannot tell that the user went back");
      assert.equal(sig.aborted, false);
      assert.notEqual(e.el.selectedNote.textContent, e.PREPARING_NOTE, "FOREX shows 'Tryb w przygotowaniu' while the licence is being checked");
      assert.match(e.el.selectedNote.textContent, /licencj/i);
      e.key("Escape", "Escape");                            // POWRÓT while the licence check is still running
      assert.equal(e.el.root.dataset.state, "returning");
      assert.equal(sig.aborted, true, "going back did not cancel the pending FOREX hand-off");
      e.frames(3);
      assert.equal(e.el.root.dataset.state, "menu");
      e.el.buttons[0].dispatch("click"); e.frames(3);
      assert.equal(got.length, 2);
      assert.equal(got[1][1].aborted, false);
      e.dispose();
      assert.equal(got[1][1].aborted, true, "dispose did not cancel the hand-off");
    } finally { e.restore(); }
  },
  // chunk_45#2: R / Ctrl+Alt+B / Space only act on the menu itself - not under the open system drawer or on a focused button
  async menu_shortcuts_scoped() {
    const e = await engine({ forceSoftware: true });
    try {
      assert.equal(e.el.root.dataset.state, "menu");
      const drawer = e.mkOutside("aside"); drawer.setAttribute("role", "dialog"); drawer.setAttribute("aria-modal", "true");
      const stopBtn = e.mkOutside("button", drawer);
      e.key("r", "KeyR", { target: stopBtn });
      assert.equal(e.el.root.dataset.state, "menu", "'r' typed in the system drawer replayed the intro (and hid STOP)");
      e.key("b", "KeyB", { ctrlKey: true, altKey: true, target: e.edoc.body });
      assert.equal(e.el.root.dataset.state, "menu", "Ctrl+Alt+B replayed the intro under an open modal drawer");
      e.key("r", "KeyR", { target: e.el.buttons[1], defaultPrevented: true });
      assert.equal(e.el.root.dataset.state, "menu", "an already handled key must be ignored");
      const field = e.mkOutside("input");
      drawer.removeAttribute("aria-modal");                  // drawer closed
      e.key("r", "KeyR", { target: field });
      assert.equal(e.el.root.dataset.state, "menu", "'r' typed in a field");
      const sysIcon = e.mkOutside("button");                 // the drawer returns focus to the system icon that opened it: R still works
      e.key("r", "KeyR", { target: sysIcon });
      assert.equal(e.el.root.dataset.state, "boot");
      const ev = e.key(" ", "Space", { target: e.el.sound });
      assert.equal(ev.defaultPrevented, false, "Space on a focused button must activate the button");
      assert.equal(e.el.root.dataset.state, "boot");
      e.key(" ", "Space", { target: e.edoc.body });
      assert.equal(e.el.root.dataset.state, "enter", "Space (nothing focused) must still skip the intro");
    } finally { e.restore(); }
  },
  // chunk_45#3: a play() promise aborted by skipping must not show "URUCHOM INTRO" over the menu; the button does nothing outside the intro
  async menu_visibility_abort() {
    let rej = null;
    const e = await engine({ forceSoftware: true, playIntro: true, video: { play: (n) => (n === 1 ? Promise.resolve() : new Promise((_r, j) => { rej = j; })) } });
    try {
      assert.equal(e.el.root.dataset.state, "boot");
      e.edoc.hidden = true; e.edoc.dispatch("visibilitychange");
      e.edoc.hidden = false; e.edoc.dispatch("visibilitychange");
      assert.equal(e.vcalls.play, 2);
      e.el.skip.dispatch("click");
      assert.equal(e.el.root.dataset.state, "enter");
      rej(Object.assign(new Error("The play() request was interrupted by a call to pause()."), { name: "AbortError" }));
      await tick(0); await tick(0);
      assert.equal(e.el.videoStart.hidden, true, "'URUCHOM INTRO' shown over the menu after an AbortError");
      e.el.videoStart.dispatch("click");
      assert.equal(e.vcalls.play, 2, "'URUCHOM INTRO' started the film outside the intro (sound in the hidden cinema)");
    } finally { e.restore(); }
  },
  // chunk_45#9 / chunk_45#10: no intro-3D release/dispose calls, no data-forex marker, no onMotionChange option
  async menu_dead_state_removed() {
    let motion = 0;
    const e = await engine({ forceSoftware: true, reduced: true, onForexReady() {}, onMotionChange: () => { motion += 1; } });
    try {
      e.el.buttons[0].dispatch("click"); e.frames(3);
      assert.equal(e.el.root.dataset.state, "selected");
      assert.equal(e.el.root.dataset.forex, undefined, "data-forex marker without any consumer");
      e.el.motion.dispatch("click");
      assert.equal(motion, 0, "onMotionChange option is still called (no consumer)");
      e.dispose();
      assert.deepEqual([e.vcalls.release, e.vcalls.dispose], [0, 0], "intro-3D release()/dispose() still called on the <video>");
      const src = srcOf("features/cinematic/menuEngine.ts");
      assert.doesNotMatch(src, /state\.time \+=/);
      assert.doesNotMatch(src, /release\?\(\)|dispose\?\(\)/);
    } finally { e.restore(); }
  },
  // chunk_45#4 / chunk_45#8: no pow() with a possibly negative base in the shaders; the third orb is TraderLifeGame, not OTC
  async menu_shaders_no_negative_pow() {
    const S = await imp("features/cinematic/menuShaders.ts");
    const all3 = [S.vertexShared, S.starVert, S.particleFrag, S.meshFrag, S.starFrag, S.streakVert, S.streakFrag].join("\n");
    assert.doesNotMatch(all3, /pow\(sin\(/, "pow(sin(..),8.) is undefined for a negative base in GLSL ES (NaN on ANGLE/D3D)");
    assert.doesNotMatch(all3, /pow\(\(p\.y/, "pow(x,2.) with a negative x in starVert");
    assert.match(S.vertexShared, /pow\(abs\(sin\(lat\*37\.\+l2\)\),8\.\)/);
    assert.doesNotMatch(all3, /OTC/);
    assert.match(S.vertexShared, /TraderLifeGame/);
  },
  // chunk_43#11: the unrendered appearance layer does not download / decode the background GIFs at every start; a consumer still gets them
  async appearance_no_eager_fetch() {
    const calls = mockApi({ get: { "/api/v1/appearance/assets": { frog: { source: "BUILTIN", animated_available: true, animated_url: "/f.gif", static_url: "/f.png" } } } });
    const M = await imp("appearance.tsx");
    const r = await render(React.createElement(M.AppearanceProvider, null, React.createElement("span", null, "ok")));
    assert.match(r.box.textContent, /ok/);
    assert.deepEqual(calls.get.filter((p) => p.includes("appearance")), [], "GET /api/v1/appearance/assets at start-up although nothing renders the layer");
    await r.unmount();
    assert.doesNotMatch(srcOf("components/Dialogs.tsx"), /LookTab|useAppearance/, "unreachable 'look' Settings tab still in Dialogs.tsx");
    let src = null;                                         // the (archived 1.41) consumers keep working: the first one loads the assets once
    const Probe = () => { src = M.useAppearance().frogSrc; return null; };
    const r2 = await render(React.createElement(M.AppearanceProvider, null, React.createElement(Probe), React.createElement(Probe)));
    assert.equal(calls.get.filter((p) => p === "/api/v1/appearance/assets").length, 1);
    assert.ok(src === "/f.gif" || src === "/f.png", "consumer got no asset: " + src);
    await r2.unmount();
  },
  // chunk_43#13: GET /api/v1/config failing shows an error with a retry (not "Ładowanie…" forever); models / test errors are reported
  async settings_load_error_retry() {
    let ok = false;
    mockApi({ get: { "/api/v1/config": () => { if (!ok) throw new Error("HTTP 500"); return CFG(); }, "/api/v1/agent/models": () => { throw new Error("HTTP 403 CSRF"); } },
      send: (m, p) => { if (p === "/api/v1/agent/test") throw new Error("HTTP 502"); return {}; } });
    const { SettingsModal } = await imp("components/Dialogs.tsx");
    rejections.length = 0;
    const r = await render(React.createElement(SettingsModal, { onClose() {} }));
    await flush();
    assert.match(r.box.textContent, /Błąd.*HTTP 500/, "load error not shown");
    const retry = byText(r.box, "button", /Ponów|Spróbuj ponownie/);
    assert.ok(retry, "no retry button");
    ok = true;
    await click(retry);
    assert.ok(byText(r.box, "button", /^Agent Claude$/), "settings form not shown after retry");
    await click(byText(r.box, "button", /^Agent Claude$/));
    await click(byText(r.box, "button", /Pobierz listę modeli/));
    assert.match(r.box.textContent, /Błąd: HTTP 403 CSRF/);
    await click(byText(r.box, "button", /Testuj połączenie/));
    assert.match(r.box.textContent, /HTTP 502/);
    await flush();
    assert.deepEqual(rejections.map(String), [], "unhandled promise rejections");
    await r.unmount();
  },
  // chunk_43#14: the MANUAL strategy list comes from the configuration (S01-S12), a configured S11 is shown, not an empty choice
  async settings_manual_strategy_options() {
    const cfg = CFG(); cfg.config.active.strategy_mode = "MANUAL"; cfg.config.active.manual_strategy_id = "S11";
    mockApi({ get: { "/api/v1/config": cfg } });
    const { SettingsModal } = await imp("components/Dialogs.tsx");
    const r = await render(React.createElement(SettingsModal, { onClose() {} }));
    await click(byText(r.box, "button", /^AUTO \/ ACTIVE$/));
    const sel = all(byText(r.box, "label", /Strategia w trybie MANUAL/)).find((e) => e.tagName === "SELECT");
    const opts = sel.options.map((o) => String(o.value));
    assert.ok(opts.includes("S11") && opts.includes("S12"), "S11/S12 missing: " + opts.join(","));
    assert.equal(String(props(sel).value), "S11");
    assert.doesNotMatch(r.box.textContent, /10 strategii S01–S10/);
    assert.match(r.box.textContent, /12 strategii S01–S12/);
    await r.unmount();
  },
  // chunk_43#16: "Menu główne" on the crash screen of #/menu clears the error (no hashchange when the hash does not change)
  async error_boundary_menu_reset() {
    mockApi();
    const { default: ErrorBoundary } = await imp("components/ErrorBoundary.tsx");
    let boom = true;
    const Child = () => { if (boom) throw new Error("render failed"); return React.createElement("p", null, "menu ok"); };
    globalThis.location.hash = "#/menu";
    const r = await quiet(() => render(React.createElement(ErrorBoundary, null, React.createElement(Child))));
    assert.match(r.box.textContent, /Ten ekran napotkał błąd/);
    boom = false;
    await click(byText(r.box, "button", /^Menu główne$/));
    assert.equal(globalThis.location.hash, "#/menu");
    assert.match(r.box.textContent, /menu ok/, "the 'Menu główne' button does nothing when the error happened on #/menu");
    await r.unmount();
  },
  // chunk_43#12 / focus_X2#20: the unused BasketsPanel with active OTC controls is gone; the used panels stay
  async baskets_otc_removed() {
    const M = await imp("components/Pmw141Panels.tsx");
    assert.equal(M.BasketsPanel, undefined, "dead BasketsPanel (OTC profile button, OTC payout/payoff, Gold OTC declaration) still exported");
    for (const k of ["ResearchModulesPanel", "TabICLCard", "ComponentsCards"]) assert.equal(typeof M[k], "function", k);
    const src = srcOf("components/Pmw141Panels.tsx");
    assert.doesNotMatch(src, /OTC_GOLD_POCKETOPTION|\/api\/v1\/baskets\/otc|9 baskets|90 strategies/);
  },
  // chunk_43#15: no loop data (503 / before the first read) is shown as unavailable, never as "0 cykli, błędy 0"
  async research_loop_unavailable() {
    mockApi({ get: { "/api/v1/research-modules": () => { throw new Error("503 moduły badawcze niedostępne"); } } });
    const { ResearchModulesPanel } = await imp("components/Pmw141Panels.tsx");
    const r = await render(React.createElement(ResearchModulesPanel));
    assert.match(r.box.textContent, /moduły badawcze niedostępne/);
    assert.doesNotMatch(r.box.textContent, /błędy 0|0 cykli/, "missing loop data shown as zeros");
    assert.match(r.box.textContent, /pętla: brak danych/);
    await r.unmount();
    mockApi({ get: { "/api/v1/research-modules": { semantics: "s", activation_policy: "p", loop: { cycles: 0, errors: 0 }, modules: {} } } });
    const r2 = await render(React.createElement(ResearchModulesPanel));
    assert.match(r2.box.textContent, /pętla: 0 cykli, błędy 0/, "real zeros from the backend are still shown");
    await r2.unmount();
  },
  // chunk_45#5 / #6 / #7 (+ chunk_45#1 wiring): CinematicMenu forwards the hand-off signal, has no E2 placeholder, no onChoose no-op, no OTC class
  async cinematic_menu_wrapper() {
    mockApi({ s: { app_version: "1.46" } });
    const { default: CinematicMenu } = await imp("features/cinematic/CinematicMenu.tsx");
    const got = [];
    const r = await render(React.createElement(CinematicMenu, { onForexReady: (...a) => got.push(a) }));
    const m = globalThis.__mock.menu;
    assert.ok(m, "mountMenu not called");
    assert.equal(m.opts.onChoose, undefined, "empty onChoose callback still passed to mountMenu");
    const ac = new AbortController();
    m.opts.onForexReady({ x: 1, y: 2, r: 3 }, ac.signal);
    assert.equal(got.length, 1);
    assert.deepEqual(got[0][0], { x: 1, y: 2, r: 3 });
    assert.equal(got[0][1], ac.signal, "the hand-off AbortSignal is not forwarded to App");
    const tlg = q(r.box, "menu-tlg");
    assert.ok(tlg);
    assert.doesNotMatch(tlg.className, /cin-mode-otc/);
    assert.match(tlg.className, /cin-mode-tlg/);
    const src = srcOf("features/cinematic/CinematicMenu.tsx");
    assert.doesNotMatch(src, /etapie E2|tymczasowo do E2/);
    assert.doesNotMatch(src, /FOREX \/ CRYPTO \/ OTC|CRYPTO \/ OTC/);
    await r.unmount();
    assert.equal(m.disposed, true);
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
