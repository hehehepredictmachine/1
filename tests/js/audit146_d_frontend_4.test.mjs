// 1.46 audit (group D_frontend_4): React panels (licence generator / panel / gate, training centre, system drawer, TraderLifeGame), the store,
// Studio header and theme storage / colour parsing - rendered with the real react-dom/client into a minimal DOM stub (no browser).
// Usage: node --experimental-strip-types --no-warnings tests/js/audit146_d_frontend_4.test.mjs <case> [case ...]
// .ts/.tsx sources are transpiled with the project's own TypeScript; api.ts and telemetry.ts are replaced by in-memory mocks.
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

// ---------------------------------------------------------------- module hooks: TS/TSX transpile, CSS stub, api/telemetry mocks
const data = (src) => "data:text/javascript," + encodeURIComponent(src);
const MOCKS = {
  [path.join(SRC, "api.ts")]: data(`
    export class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
    export const initSession = (...a) => globalThis.__mock.initSession(...a);
    export const apiGet = (...a) => globalThis.__mock.apiGet(...a);
    export const apiSend = (...a) => globalThis.__mock.apiSend(...a);
    export const apiUpload = (...a) => globalThis.__mock.apiSend("UPLOAD", ...a);
    export const getCsrf = () => "csrf";
    export class LiveSocket { constructor(onMessage, onStatus) { this.onMessage = onMessage; this.onStatus = onStatus; globalThis.__mock.sockets.push(this); }
      start() { this.started = true; } stop() { this.stopped = true; } }`),
  [path.join(SRC, "telemetry.ts")]: data(`export const telemetry = { emit() {}, status() {}, subscribe() { return () => {}; } };`),
};
const EXT = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];
registerHooks({
  resolve(spec, ctx, next) {
    if (spec.endsWith(".css")) return { url: data("export default {};"), shortCircuit: true };
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

// ---------------------------------------------------------------- minimal DOM (only what react-dom/client touches here)
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
  click() { /* <input type=file> ref.click(): nothing to open in the stub */ }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
}
// inputs / textareas / selects keep `value` as an own data property (react-dom then skips its value tracker)
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
globalThis.__PMW_EDITION__ = "OWNER";
globalThis.location = { host: "127.0.0.1", hash: "#/menu", reload() {} };
globalThis.history = { replaceState(_s, _t, h) { globalThis.location.hash = h; } };
const store = new Map();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: (k) => { store.delete(k); },
  clear: () => store.clear() } });
const alerts = [];
globalThis.alert = (m) => { alerts.push(String(m)); };
const rejections = [];
process.on("unhandledRejection", (e) => { rejections.push(e); });

const React = req("react");
const { createRoot } = req("react-dom/client");
const { act } = React;
const imp = (rel) => import(pathToFileURL(path.join(SRC, rel)).href);

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
async function click(el) { assert.ok(el, "element to click not found"); await act(async () => { fire(el, "click"); }); await flush(); }
async function typeInto(el, v) {
  assert.ok(el, "input not found");
  el.value = v;
  await act(async () => { fire(el, el.tagName === "SELECT" ? "change" : "input"); });
  await flush();
}
function defer() { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); return { p, res, rej }; }
function mockApi({ get = {}, send = () => ({}) } = {}) {
  const calls = { get: [], send: [] };
  globalThis.__mock = {
    sockets: [], calls,
    initSession: async () => undefined,
    apiGet: async (p) => {
      calls.get.push(p);
      const h = Object.entries(get).find(([k]) => p === k || (k.endsWith("*") && p.startsWith(k.slice(0, -1))));
      if (!h) throw new Error("404 " + p);
      return typeof h[1] === "function" ? h[1](p) : JSON.parse(JSON.stringify(h[1]));
    },
    apiSend: async (m, p, body) => { calls.send.push({ m, p, body: body === undefined ? undefined : JSON.parse(JSON.stringify(body)), raw: body }); return send(m, p, body); },
  };
  return calls;
}

// ---------------------------------------------------------------- TraderLifeGame fixtures
const TLG_STATE = { profile: { username: "gracz", class: "Rookie", difficulty_name: "Łatwy", intro: "", milestone: 1, currency: "USD", milestone_note: "" },
  progress: { level: 1, rank: "R", xp: 0, xp_next_level: 100 }, balances: { trader_gold: 0 }, attributes: {} };
const SIM_VIEW = (id) => ({ id, symbol: "XAUUSD", tf: "H1", status: "ACTIVE", bars: [{ o: 1, h: 2, l: 0.5, c: 1.5 }, { o: 1.5, h: 2.5, l: 1, c: 2 }], trades: [],
  isolation: "SIMULATOR_ONLY", simulated_pnl: 0, virtual_balance: 10000 });
async function tlg(get, send) {
  const calls = mockApi({ get: { "/api/v1/tlg/state": TLG_STATE, "/api/v1/tlg/sim": { items: [] }, ...get }, send });
  const { default: TraderLifeGame } = await imp("features/trader-life-game/TraderLifeGame.tsx");
  const r = await render(React.createElement(TraderLifeGame, { onBack() {} }));
  return { ...r, calls };
}
const input = (root, near, ph) => {
  const sec = all(root).filter((e) => e.tagName === "SECTION").find((s) => near.test(s.textContent));
  assert.ok(sec, "section " + near + " not found");
  return all(sec).find((e) => e.tagName === "INPUT" && (ph == null || e.getAttribute("placeholder") === ph)) || null;
};

const CASES = {
  // chunk_48#0: a crafted PMW1 key with an object in "u" / a list in "hw" must not crash the whole app (object as a React child)
  async lic_check_object_user() {
    mockApi({ get: { "/api/v1/owner/license/state": { crypto_ok: true, has_key: true, public_key: "ab", key_path: "k", preset_days: [7, 30], hwid_format: "" },
      "/api/v1/owner/licenses": { licenses: [] } },
    send: () => ({ format_ok: false, signature_ok: false, user: { evil: 1 }, hwid: ["X"], iat_iso: null, exp_iso: null, perpetual: null, expired: null,
      valid: false, errors: ["pole u: oczekiwano tekstu"], this_computer: null }) });
    const { default: Panel } = await imp("features/system/LicenseGeneratorPanel.tsx");
    const r = await render(React.createElement(Panel));
    await typeInto(q(r.box, "lic-check-in"), "PMW1-AAAA");
    await click(q(r.box, "lic-check-btn"));
    assert.deepEqual(r.errors.map(String), []);
    const out = q(r.box, "lic-check-out");
    assert.ok(out, "check result not rendered");
    assert.match(out.textContent, /Użytkownik—/);
    assert.match(out.textContent, /HWID—/);
    await r.unmount();
  },
  // chunk_48#1: risk exercise answer typed with a decimal comma; empty / invalid answer is not sent
  async tlg_risk_comma() {
    const t = await tlg({ "/api/v1/tlg/academy": { levels: [], source: "src" }, "/api/v1/tlg/academy/risk": { question: "Konto 7000", exercise_id: "e1" } },
      () => ({ correct: true, expected: 7.7778, reward: null }));
    await click(q(t.box, "tlg-tab-academy"));
    const inp = input(t.box, /Ćwiczenie z ryzyka/);
    const btn = () => byText(t.box, "button", /^Sprawdź$/);
    await typeInto(inp, "");
    await click(btn());
    assert.equal(t.calls.send.filter((c) => c.p === "/api/v1/tlg/academy/risk").length, 0, "empty answer must not be sent");
    await typeInto(inp, "abc");
    await click(btn());
    assert.equal(t.calls.send.filter((c) => c.p === "/api/v1/tlg/academy/risk").length, 0, "invalid answer must not be sent");
    await typeInto(inp, "7,78");
    await click(btn());
    const s = t.calls.send.filter((c) => c.p === "/api/v1/tlg/academy/risk");
    assert.equal(s.length, 1);
    assert.equal(s[0].body.answer, 7.78);
    await t.unmount();
  },
  // chunk_48#2: simulator SL/TP typed with a comma reach the backend; an invalid SL blocks the order instead of opening it without SL
  async tlg_sim_sl_comma() {
    const t = await tlg({}, (m, p) => (p === "/api/v1/tlg/sim" || p.startsWith("/api/v1/tlg/sim/") ? SIM_VIEW(5) : {}));
    await click(q(t.box, "tlg-tab-simulator"));
    await click(byText(t.box, "button", /Start sesji/));
    await typeInto(input(t.box, /Symulator historyczny/, "SL"), "2400,5");
    await typeInto(input(t.box, /Symulator historyczny/, "TP"), "2410.25");
    await click(byText(t.box, "button", /^BUY/));
    let o = t.calls.send.filter((c) => c.p === "/api/v1/tlg/sim/5/open");
    assert.equal(o.length, 1);
    assert.equal(o[0].body.sl, 2400.5);
    assert.equal(o[0].body.tp, 2410.25);
    await typeInto(input(t.box, /Symulator historyczny/, "SL"), "24OO");
    await click(byText(t.box, "button", /^SELL/));
    o = t.calls.send.filter((c) => c.p === "/api/v1/tlg/sim/5/open");
    assert.equal(o.length, 1, "an order with an unreadable SL must not be opened without SL");
    assert.match(t.box.textContent, /SL/);
    await t.unmount();
  },
  // chunk_48#3: act() swallows errors - a failed save must not close the journal form / clear the coach text / drop the simulator session
  async tlg_act_failure_keeps_form() {
    const fail = (p) => { throw new Error(p.includes("journal") ? "INVALID_REVIEW_SCORE" : p.includes("coach") ? "SECRET_NOT_ALLOWED" : "SESSION_NOT_ACTIVE"); };
    const t = await tlg({
      "/api/v1/tlg/journal": { source: "MT5", items: [{ ref: "r1", position_id: 1, symbol: "XAUUSD", side: "BUY", status: "CLOSED", net_pnl: 1, annotation: null }] },
      "/api/v1/tlg/coach": { persona: "Coach", mode: "m", ai: "a", greeting: "g", daily_plan: [], observations: [], disclaimer: "d", memory: [] },
    }, (m, p) => {
      if (m === "PUT" || p === "/api/v1/tlg/coach/memory" || p.endsWith("/finish")) fail(p);
      return p.startsWith("/api/v1/tlg/sim") ? SIM_VIEW(9) : {};
    });
    await click(q(t.box, "tlg-tab-journal"));
    await click(byText(t.box, "button", /^opisz$/));
    const setup = () => all(byText(t.box, "label", /^setup/)).find((e) => e.tagName === "INPUT");
    await typeInto(setup(), "pin bar");
    await click(byText(t.box, "button", /^Zapisz$/));
    assert.ok(byText(t.box, "b", /Wpis: r1/), "journal form closed after a failed save");
    assert.equal(setup().value, "pin bar");
    await click(q(t.box, "tlg-tab-coach"));
    const ci = all(q(t.box, "tlg-coach")).find((e) => e.tagName === "INPUT");
    await typeInto(ci, "handluję tylko Londyn");
    await click(byText(t.box, "button", /^Zapamiętaj$/));
    assert.equal(all(q(t.box, "tlg-coach")).find((e) => e.tagName === "INPUT").value, "handluję tylko Londyn", "coach text cleared after a failed save");
    await click(q(t.box, "tlg-tab-simulator"));
    await click(byText(t.box, "button", /Start sesji/));
    await click(byText(t.box, "button", /Zakończ sesję/));
    assert.ok(byText(t.box, "button", /Zakończ sesję/), "simulator session dropped from the view although /finish failed");
    assert.match(q(t.box, "tlg-msg").textContent, /SESSION_NOT_ACTIVE/);
    await t.unmount();
  },
  // chunk_48#4: "—" in "Zgodnie z regułami" clears the stored value (null is sent; undefined was dropped by JSON and the old value stayed)
  async tlg_rule_compliance_clear() {
    const t = await tlg({ "/api/v1/tlg/journal": { source: "MT5", items: [{ ref: "r1", position_id: 1, symbol: "XAUUSD", side: "BUY", status: "CLOSED", net_pnl: 1,
      annotation: { rule_compliance: true } }] } }, () => ({ ref: "r1" }));
    await click(q(t.box, "tlg-tab-journal"));
    await click(byText(t.box, "button", /^opisz$/));
    const sel = all(byText(t.box, "label", /Zgodnie z regułami/)).find((e) => e.tagName === "SELECT");
    await typeInto(sel, "");
    await click(byText(t.box, "button", /^Zapisz$/));
    const put = t.calls.send.find((c) => c.m === "PUT");
    assert.ok(put, "no PUT sent");
    assert.ok(Object.prototype.hasOwnProperty.call(put.body, "rule_compliance"), "rule_compliance missing from the JSON body");
    assert.equal(put.body.rule_compliance, null);
    await t.unmount();
  },
  // chunk_48#5: an ACTIVE simulator session survives a tab switch (it can be resumed instead of being abandoned on the server)
  async tlg_sim_resume() {
    const t = await tlg({ "/api/v1/tlg/sim": { items: [{ id: 7, symbol: "XAUUSD", tf: "H1", status: "ACTIVE", cursor: 50 }] }, "/api/v1/tlg/sim/7": SIM_VIEW(7) });
    await click(q(t.box, "tlg-tab-simulator"));
    const b = byText(t.box, "button", /Wznów/);
    assert.ok(b, "no resume button for the ACTIVE session");
    await click(b);
    assert.ok(t.calls.get.includes("/api/v1/tlg/sim/7"));
    assert.match(q(t.box, "tlg-sim").textContent, /odsłonięte świece: 2/);
    await t.unmount();
  },
  // chunk_48#6: /tlg/meta failing on character creation shows an error with a retry instead of an empty page
  async tlg_meta_error() {
    let ok = false;
    const META = { classes: { THE_ROOKIE: { name: "Rookie", specialization: "s", description: "d" } }, difficulties: { EASY: { name: "Łatwy", milestone: 1 } }, milestone_note: "n" };
    const t = await tlg({ "/api/v1/tlg/state": { profile: null, needs_character: true },
      "/api/v1/tlg/meta": () => { if (!ok) throw new Error("402: licencja wymagana"); return META; } });
    assert.match(t.box.textContent, /402: licencja wymagana/);
    ok = true;
    await click(byText(t.box, "button", /Spróbuj ponownie/));
    assert.ok(q(t.box, "tlg-create"), "character form not shown after retry");
    await t.unmount();
  },
  // chunk_43#4: a /api/v1/state snapshot older than the WS events already applied must not roll those keys back
  async store_full_not_older() {
    mockApi({ get: { "/api/v1/state": { seq: 10, boot_id: "b1", mode: { v: "A" }, prefs: { x: 1 } } } });
    const { StoreProvider, useStore } = await imp("store.tsx");
    const seen = {};
    const Probe = () => { const { s } = useStore(); seen.mode = s.mode?.v; seen.prefs = s.prefs?.x; return null; };
    const r = await render(React.createElement(StoreProvider, null, React.createElement(Probe)));
    const sock = globalThis.__mock.sockets[0];
    assert.ok(sock?.started, "LiveSocket not started");
    await act(async () => { sock.onMessage({ seq: 11, boot_id: "b1", type: "mode", data: { v: "B" } }); });
    const d = defer();
    globalThis.__mock.apiGet = () => d.p;
    let done;
    await act(async () => { done = globalThis.__mqRefresh(); });
    await act(async () => { sock.onMessage({ seq: 12, boot_id: "b1", type: "mode", data: { v: "C" } }); });
    await act(async () => { d.res({ seq: 11, boot_id: "b1", mode: { v: "B" }, prefs: { x: 2 } }); await done; });
    await flush();
    assert.equal(seen.mode, "C", "older snapshot rolled back a newer WS event");
    assert.equal(seen.prefs, 2, "keys not touched by newer events must still come from the snapshot");
    globalThis.__mock.apiGet = async () => ({ seq: 20, boot_id: "b1", mode: { v: "D" }, prefs: { x: 3 } });
    await act(async () => { await globalThis.__mqRefresh(); });
    await flush();
    assert.equal(seen.mode, "D", "a newer snapshot must apply");
    globalThis.__mock.apiGet = async () => ({ seq: 15, boot_id: "b1", mode: { v: "E" }, prefs: { x: 4 } });
    await act(async () => { await globalThis.__mqRefresh(); });
    await flush();
    assert.equal(seen.mode, "D", "a snapshot older than the one already applied must be skipped");
    assert.equal(seen.prefs, 3);
    globalThis.__mock.apiGet = async () => ({ seq: 2, boot_id: "b2", mode: { v: "F" }, prefs: { x: 5 } });
    await act(async () => { await globalThis.__mqRefresh(); });
    await flush();
    assert.equal(seen.mode, "F", "a snapshot of a new backend boot always applies");
    await r.unmount();
  },
  // chunk_43#5: one failed start (initSession / first /state) is retried; the UI recovers and the LiveSocket starts
  async store_startup_retry() {
    const realST = globalThis.setTimeout;
    globalThis.setTimeout = (f, ms, ...a) => realST(f, ms >= 500 ? Math.ceil(ms / 50) : ms, ...a);
    try {
      mockApi({ get: { "/api/v1/state": { seq: 1, boot_id: "b", mode: { v: "A" } } } });
      let n = 0;
      globalThis.__mock.initSession = async () => { n += 1; if (n === 1) throw new Error("HTTP 500"); };
      const { StoreProvider } = await imp("store.tsx");
      const r = await render(React.createElement(StoreProvider, null, React.createElement("p", { "data-testid": "app" }, "APP")));
      assert.ok(byText(r.box, "p", /Nie można połączyć się/), "first failure not shown");
      for (let i = 0; i < 40 && !q(r.box, "app"); i++) await act(async () => { await tick(25); });
      assert.ok(q(r.box, "app"), "UI stuck on the error screen after a transient start failure");
      assert.ok(globalThis.__mock.sockets.some((s) => s.started), "LiveSocket not started after recovery");
      await r.unmount();
    } finally { globalThis.setTimeout = realST; }
  },
  // chunk_48#8: "Sprawdzono licencję." only when the check really succeeded
  async license_panel_refresh_fail() {
    mockApi();
    const { LicenseCtx } = await imp("license/LicenseGate.tsx");
    const { default: LicensePanel } = await imp("features/system/LicensePanel.tsx");
    const st = { edition: "CLIENT", required: true, valid: true, code: "OK", message: "", hwid: "AAAAA-BBBBB-CCCCC-DDDDD", user: "jan", perpetual: true };
    let result = null;
    const value = { st, refresh: async () => result, openActivation() {} };
    const r = await render(React.createElement(LicenseCtx.Provider, { value }, React.createElement(LicensePanel)));
    await click(byText(r.box, "button", /SPRAWDŹ PONOWNIE/));
    assert.doesNotMatch(r.box.textContent, /Sprawdzono licencję\./, "success shown although the check failed");
    assert.match(r.box.textContent, /Nie udało się sprawdzić licencji/);
    result = st;
    await click(byText(r.box, "button", /SPRAWDŹ PONOWNIE/));
    assert.match(r.box.textContent, /Sprawdzono licencję\./);
    await r.unmount();
  },
  // chunk_48#7: removing a queued training reports ok=false (already started) and network errors instead of an unhandled rejection
  async training_remove_feedback() {
    let mode = "notqueued";
    mockApi({ get: { "/api/v1/pepe-training": { units: [], queue: [{ id: "q1", name: "Model A" }], current: null, history: [], demo: false, instruments: [] } },
      send: (m, p) => { if (p.endsWith("/remove")) { if (mode === "err") throw new Error("HTTP 500"); return { ok: mode === "ok" }; } return {}; } });
    const { default: Panel } = await imp("features/system/TrainingCenterPanel.tsx");
    const r = await render(React.createElement(Panel));
    const x = () => all(r.box).find((e) => e.getAttribute("aria-label") === "Usuń z kolejki: Model A");
    const before = rejections.length;
    await click(x());
    assert.match(r.box.textContent, /wystartował/, "ok=false not reported");
    mode = "err";
    await click(x());
    await tick(5);
    assert.equal(rejections.length, before, "unhandled rejection on a failed remove");
    assert.match(r.box.textContent, /BŁĄD: HTTP 500/);
    mode = "ok";
    await click(x());
    assert.match(r.box.textContent, /Usunięto z kolejki/);
    await r.unmount();
  },
  // chunk_43#8: first screen after start uses the display name (Apollo23), not PEPEMARKETWIZARD
  async license_gate_brand() {
    mockApi();
    globalThis.__mock.apiGet = () => new Promise(() => {});
    const { default: LicenseGate } = await imp("license/LicenseGate.tsx");
    const r = await render(React.createElement(LicenseGate, null, React.createElement("p", null, "APP")));
    const t = r.box.textContent;
    assert.doesNotMatch(t, /PEPEMARKETWIZARD/i);
    assert.match(t, /APOLLO23 · sprawdzanie licencji/);
    await r.unmount();
  },
  // focus_X5#6: system drawer tab label without the old brand
  async system_drawer_label() {
    mockApi({ get: { "/api/v1/pepe-training": { units: [], queue: [], current: null, history: [], demo: false, instruments: [] } } });
    const { default: SystemDrawer } = await imp("features/system/SystemDrawer.tsx");
    const r = await render(React.createElement(SystemDrawer, { panel: "training", onPanel() {}, onClose() {} }));
    const tabs = all(r.box).filter((e) => e.getAttribute("role") === "tab").map((e) => e.textContent);
    assert.ok(tabs.some((x) => /^CENTRUM TRENINGOWE/.test(x)), "training tab missing: " + tabs.join("|"));
    assert.ok(!tabs.some((x) => /PEPE/.test(x)), "old brand in a tab label: " + tabs.join("|"));
    assert.doesNotMatch(r.box.textContent, /PEPE/);
    await r.unmount();
  },
  // chunk_43#9: Studio header uses the display name
  async studio_brand() {
    globalThis.fetch = () => new Promise(() => {});
    const box = makeEl(doc, "div"); box.setAttribute("id", "studio-root"); doc.body.appendChild(box);
    await act(async () => { await imp("studio/main.tsx"); });
    const h1 = all(box).find((e) => e.tagName === "H1");
    assert.ok(h1, "no header");
    assert.doesNotMatch(h1.textContent, /Pepe/);
    assert.match(h1.textContent, /^Apollo23\b.*Data & Training Studio$/);
    assert.equal(doc.title, "Apollo23 Data & Training Studio");
  },
  // chunk_44#4: the 1.29 gold -> three towers migration is persisted (it used to apply for one start only)
  async theme_gold_migration_persisted() {
    const T = await imp("theme.tsx");
    store.clear();
    localStorage.setItem("mq.theme.v1", JSON.stringify({ version: 1, preset: "gold", tokens: { ...T.PRESETS.gold.tokens }, custom: {}, overrides: {} }));
    const seen = [];
    let cur = null;
    const Probe = () => { cur = T.useTheme().stored.preset; return null; };
    for (let i = 0; i < 3; i++) {                                   // three app starts on the same localStorage
      const r = await render(React.createElement(T.ThemeProvider, null, React.createElement(Probe))); seen.push(cur); await r.unmount();
    }
    assert.deepEqual(seen, ["wieze", "wieze", "wieze"], "later start went back to gold: " + seen.join(","));
    assert.equal(JSON.parse(localStorage.getItem("mq.theme.v1")).preset, "wieze");
  },
  // chunk_44#5: missing tokens of a stored theme come from that theme's preset, not from MATRIX
  async theme_missing_tokens_from_preset() {
    const T = await imp("theme.tsx");
    store.clear();
    const tokens = { ...T.PRESETS.light.tokens }; delete tokens.text;
    localStorage.setItem("mq.theme.v1", JSON.stringify({ version: 1, preset: "light", tokens, custom: {}, overrides: {} }));
    let got = null;
    const Probe = () => { got = T.useTheme().stored; return null; };
    const r = await render(React.createElement(T.ThemeProvider, null, React.createElement(Probe)));
    await r.unmount();
    assert.equal(got.preset, "light");
    assert.equal(got.tokens.text, T.PRESETS.light.tokens.text);
    // an unknown preset name keeps the earlier base (MATRIX) - nothing changes for custom names
    localStorage.setItem("mq.theme.v1", JSON.stringify({ version: 1, preset: "moj", tokens, custom: {}, overrides: {} }));
    const r2 = await render(React.createElement(T.ThemeProvider, null, React.createElement(Probe)));
    await r2.unmount();
    assert.equal(got.tokens.text, T.PRESETS.matrix.tokens.text);
  },
  // chunk_44#6: hsl() with an unreadable hue is rejected; hue > 360 wraps
  async theme_parse_color_hsl() {
    const T = await imp("theme.tsx");
    assert.equal(T.parseColor("hsl(1.2.3, 50%, 50%)"), null);
    assert.equal(T.parseColor("hsl(., 50%, 50%)"), null);
    assert.equal(T.toHex(T.parseColor("hsl(400, 100%, 50%)")), "#ffaa00");
    assert.equal(T.toHex(T.parseColor("hsl(40, 100%, 50%)")), "#ffaa00");
    assert.equal(T.toHex(T.parseColor("hsl(360, 100%, 50%)")), "#ff0000");
    assert.equal(T.toHex(T.parseColor("rgb(1, 2, 3)")), "#010203");
  },
  // chunk_44#7 (hidden bug in the kept import API): chart_overrides: null is a validation error, not a TypeError
  async theme_parse_file_null_overrides() {
    const T = await imp("theme.tsx");
    const r = T.parseThemeFile(JSON.stringify({ schema: T.SCHEMA, version: T.VERSION, name: "x", tokens: {}, chart_overrides: null }));
    assert.ok(r.errors.includes("chart_overrides: oczekiwano obiektu"), r.errors.join("; "));
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
