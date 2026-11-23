// 1.46 audit (group D_frontend_3): CHARTS renderer (chartsRender.ts) driven through a minimal DOM stub (no browser needed).
// Usage: node --experimental-strip-types --no-warnings tests/js/audit146_d_frontend_3.test.mjs [case ...] [--render <path to chartsRender.ts>]
// Run with TZ=Europe/Warsaw (the Python wrapper sets it). Every case prints "<case> OK" or "<case> FAIL: ..."; exit code 1 on any failure.
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const ri = argv.indexOf("--render");
const RENDER = ri >= 0 ? path.resolve(argv[ri + 1]) : path.join(here, "..", "..", "frontend", "src", "features", "forex", "screens", "charts", "chartsRender.ts");
const only = argv.filter((a, i) => !a.startsWith("--") && (ri < 0 || i !== ri + 1));
const { createCharts } = await import(pathToFileURL(RENDER).href);
const SRC = fs.readFileSync(RENDER, "utf8");
const FIXTURES = path.join(here, "..", "..", "update_charts", "narzedzia", "charts_1do1", "fixtures");

// ---------------------------------------------------------------- DOM stub (only what the renderer touches)
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const dec = (s) => s.replace(/&quot;/g, '"').replace(/&amp;/g, "&");
class El {
  constructor(doc, tag = "div") {
    this.ownerDocument = doc; this.tagName = tag.toUpperCase(); this.attrs = {}; this.dataset = {}; this.listeners = {};
    this.style = { setProperty() {} }; this._html = ""; this._kids = null; this.textContent = ""; this.hidden = false; this.className = "";
    this.rect = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
  setAttribute(k, v) { v = String(v); this.attrs[k] = v; if (k.startsWith("data-")) this.dataset[camel(k.slice(5))] = v; if (k === "class") this.className = v; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  get innerHTML() { return this._html; }
  set innerHTML(h) { this._html = String(h); this._kids = null; }
  kids() { if (!this._kids) this._kids = parseHTML(this.ownerDocument, this._html); return this._kids; }
  querySelectorAll(sel) { const p = sel.trim().split(/\s+/); return this.kids().filter((e) => matches(e, p[p.length - 1])); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  contains(el) { return el === this || (!!el && this.kids().includes(el)); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  removeEventListener(t, f) { const a = this.listeners[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1); }
  dispatch(t, e = {}) { for (const f of [...(this.listeners[t] || [])]) f({ type: t, target: this, preventDefault() {}, ...e }); }
  click() { if (this.hasAttribute("disabled")) return; this.dispatch("click"); }
  focus() { this.ownerDocument.activeElement = this; }
  getBoundingClientRect() { return { ...this.rect }; }
  setPointerCapture() {}
}
function matches(e, sel) {
  const m = sel.match(/^([a-zA-Z][\w-]*)?(.*)$/);
  if (m[1] && e.tagName !== m[1].toUpperCase()) return false;
  const re = /#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g; let x;
  while ((x = re.exec(m[2]))) {
    if (x[1] && e.getAttribute("id") !== x[1]) return false;
    if (x[2] && !(" " + e.className + " ").includes(" " + x[2] + " ")) return false;
    if (x[3]) { if (!e.hasAttribute(x[3])) return false; if (x[4] != null && e.getAttribute(x[3]) !== x[4]) return false; }
  }
  return true;
}
function parseHTML(doc, html) {
  const out = []; const re = /<([a-zA-Z][\w-]*)((?:\s+[\w:-]+(?:\s*=\s*"[^"]*")?)*)\s*\/?>/g; let m;
  while ((m = re.exec(html))) {
    const e = new El(doc, m[1]); const ar = /([\w:-]+)(?:\s*=\s*"([^"]*)")?/g; let a;
    while ((a = ar.exec(m[2]))) e.setAttribute(a[1], a[2] == null ? "" : dec(a[2]));
    out.push(e);
  }
  return out;
}
function makeCtx(log) {
  return new Proxy({}, {
    get(o, p) {
      if (p in o) return o[p];
      if (p === "measureText") return (s) => ({ width: String(s).length * 6 });
      if (p === "createLinearGradient" || p === "createRadialGradient") return () => ({ addColorStop() {} });
      return (...a) => { log.push([p, ...a]); };
    },
    set(o, p, v) { o[p] = v; return true; },
  });
}
function makeDoc(log) {
  const doc = { activeElement: null, all: [] };
  const mk = (id, o = {}) => { const e = new El(doc, o.tag || "div"); if (id) e.setAttribute("id", id); if (o.cls) e.className = o.cls; if (o.html) e.innerHTML = o.html; if (o.rect) e.rect = o.rect; doc.all.push(e); return e; };
  const cv = mk("chart", { tag: "canvas" }); cv.width = 300; cv.height = 150; const ctx = makeCtx(log); cv.getContext = () => ctx;
  for (const id of ["ch-head", "ch-asset", "ch-tf", "ch-quote", "mc-title", "mc-read", "sig-card", "kr-tf", "kr-mode", "kr-refresh", "kr-dir", "kr-delta", "kr-read", "kr-meta", "opt-body"]) mk(id);
  const tz = mk("ch-tz", { tag: "select" }); tz.value = "LOCAL";
  mk("ch-status", { html: '<i></i><span class="t">ŁADOWANIE</span>' });
  mk("mc-plot", { rect: { left: 0, top: 40, right: 1000, bottom: 640, width: 1000, height: 600 } });
  mk("kr-plot", { rect: { left: 1020, top: 40, right: 1420, bottom: 300, width: 400, height: 260 } });
  mk(null, { cls: "cs-win main ci", rect: { left: 0, top: 0, right: 1010, bottom: 650, width: 1010, height: 650 } });
  mk(null, { cls: "cs-win ci" });
  mk("opt-tabs", { html: ["ind", "strat", "zones", "vp", "models", "chart"].map((t, i) => `<button type="button" role="tab" data-t="${t}" aria-selected="${i === 0}">${t}</button>`).join("") });
  doc.querySelectorAll = (s) => { const p = s.trim().split(/\s+/); const roots = doc.all.filter((e) => matches(e, p[0])); return p.length === 1 ? roots : roots.flatMap((r) => r.querySelectorAll(p.slice(1).join(" "))); };
  doc.querySelector = (s) => doc.querySelectorAll(s)[0] || null;
  doc.getElementById = (id) => doc.all.find((e) => e.getAttribute("id") === id) || null;
  return doc;
}
function mount(env = {}) {
  const log = []; const doc = makeDoc(log);
  globalThis.document = doc;
  const store = new Map();
  globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
  const api = createCharts(env);
  const S = { view: { w: 1440, h: 700, dpr: 1 }, reduced: false }, SUB = { state: "on", p: 1, pi: 0 };
  api.bind(S, SUB);
  const draw = (n = 1, dt = 0.1) => { for (let i = 0; i < n; i++) { log.length = 0; api.screen.draw(5000, dt); } };
  const $ = (s) => doc.querySelector(s);
  const tab = (t) => $(`#opt-tabs [data-t="${t}"]`).click();
  const texts = () => log.filter((c) => c[0] === "fillText").map((c) => String(c[1]));
  return { api, doc, log, S, SUB, draw, $, tab, texts };
}
const PROD_ENV = (extra = {}) => ({ visible: async () => null, announce: () => {}, ...extra });
// main plot geometry of the stub: R.l = 0, R.r = 1000 - 74, R.b = 640 - 22
const RL = 0, RR = 926, RB = 618;
function hoverIndex(m, i, n, view = 120) {   // pointer over candle i (offset 0)
  const cw = (RR - RL) / view, end = n; const x = RL + (i - (end - view) + 0.5) * cw;
  m.$("#mc-plot").dispatch("pointermove", { clientX: x, clientY: 300 });
}
const crossLabel = (m) => { const c = m.log.find((x) => x[0] === "fillText" && x[3] === RB + 11); return c ? String(c[1]) : null; };

// ---------------------------------------------------------------- data builders
function bars(t0, n, sec, { forming = false, v = (i) => 100 + (i % 7) * 10 } = {}) {
  const out = []; let pc = 4000;
  for (let i = 0; i < n; i++) {
    const c = 4000 + 5 * Math.sin(i / 7) + i * 0.1, o = pc;
    out.push({ t: t0 + i * sec * 1000, o, h: Math.max(o, c) + 0.5, l: Math.min(o, c) - 0.5, c, v: v(i), closed: !(forming && i === n - 1) });
    pc = c;
  }
  return out;
}
const META = {
  FX_SMC: [{ id: "FX_SMC_01", nm: "SMC test", tf: "M15", fam: "SMC", setup: "s", trig: "t", cancel: "c", exit: "e", tp_r: [1, 2] }],
  FX_SCALP: [], FX_HEDGE: [],
  LEGACY: [{ id: "S01", nm: "Legacy test", tf: "M15", fam: "LEG", val: "v" }],
  SH: [],
};
const basketSig = (t, extra = {}) => ({ sid: "FX_SMC_01", src: "BASKET", tf: "M15", t, sd: 1, e: 4000, sl: 3990, tp: [4010, 4020], res: "OTWARTY", hit: [], et: null,
  inv: null, rg: "TREND", ro: true, ev: null, tb: "R", to: 12, ...extra });
const legacySig = (t, extra = {}) => ({ sid: "S01", src: "LEGACY", tf: "M15", t, sd: 1, e: 4000, sl: 3990, tp: [4010, 4020], res: "OTWARTY", hit: [], et: null,
  inv: null, rg: null, tb: null, sc: 70, why: ["A"], miss: [], trg: "T", ...extra });
const vm = (o) => ({ asset: "XAUUSD", tf: "M15", meta: META, signals: [], zones: {}, states: {}, probs: null, status: "live", ...o });
function kronos(tf = "M5", created = "2026-11-20T10:00:00Z") {
  const candles = bars(Date.parse("2026-11-20T07:00:00Z"), 40, 300);
  const lc = candles[candles.length - 1].c;
  const pred = Array.from({ length: 12 }, (_, j) => ({ t: candles[candles.length - 1].t + (j + 1) * 300000, o: lc + j, h: lc + j + 1, l: lc + j - 1, c: lc + j + 0.5 }));
  return { tf, on: { M1: true, M5: true, M15: true, M30: true, H1: true }, role: "SHADOW, bez zleceń", state: "READY", emptyTxt: "BRAK PROGNOZY", candles,
    forecast: { created_at: created, horizon: 12, pred, paths: [pred.map((b) => b.c)], last_close: lc, neutral_band: 1, pred_close_h: lc + 11.5, direction: "UP",
      delta: 11.5, delta_pct: 0.29, is_current: true } };
}
const cardTime = (m) => (m.$("#sig-card").innerHTML.match(/<span>SYGNAŁ<\/span><span>([^<]*)</) || [])[1];
const sw = (m, k) => m.$(`#opt-body .sw[data-l="${k}"]`);

// ---------------------------------------------------------------- cases
const CASES = {
  // chunk_47#0: LOCAL uses the offset of each candle's own moment (DST), not today's offset
  time_local_per_candle() {
    for (const [iso, want] of [["2026-07-14T09:00:00Z", "14.07 11:00"], ["2026-11-20T09:00:00Z", "20.11 10:00"]]) {
      const m = mount(PROD_ENV()); const t = Date.parse(iso);
      const d = bars(t - 100 * 900000, 130, 900);
      m.api.setVM(vm({ candles: d, signals: [basketSig(t)] })); m.draw(2);
      assert.equal(cardTime(m), want, `card time for ${iso} (Europe/Warsaw)`);
    }
  },
  // chunk_47#0: a D1 candle is labelled with the broker's trading day (open 21:00Z = next server day); SERVER without measured offset is not +2
  time_d1_and_server() {
    const m = mount(PROD_ENV()); const t0 = Date.parse("2026-03-01T21:00:00Z");
    const d = bars(t0, 130, 86400); m.api.setVM(vm({ tf: "D1", candles: d })); m.draw(1);
    hoverIndex(m, 100, 130); m.draw(1);
    const want = new Date(d[100].t + 3 * 3600000); const lab = `${String(want.getUTCDate()).padStart(2, "0")}.${String(want.getUTCMonth() + 1).padStart(2, "0")}`;
    assert.equal(crossLabel(m), lab, "D1 crosshair date (LOCAL)");
    const tz = m.$("#ch-tz"); tz.value = "UTC"; tz.dispatch("change"); m.draw(1);
    assert.equal(crossLabel(m), lab, "D1 crosshair date (UTC)");
    const h = mount(PROD_ENV()); const th = Date.parse("2026-07-14T09:00:00Z");
    h.api.setVM(vm({ tf: "H1", candles: bars(th - 100 * 3600000, 130, 3600) })); const z = h.$("#ch-tz"); z.value = "SERVER"; z.dispatch("change");
    hoverIndex(h, 100, 130); h.draw(1);
    assert.equal(crossLabel(h), "14.07 09:00", "SERVER without a verified offset must not invent UTC+2");
    assert.match(h.$("#mc-title").textContent, /NIEZWERYFIKOWANY/, "SERVER without offset is marked");
    h.api.setVM(vm({ tf: "H1", candles: bars(th - 100 * 3600000, 130, 3600), serverOff: 3 })); hoverIndex(h, 100, 130); h.draw(1);
    assert.equal(crossLabel(h), "14.07 12:00", "SERVER with measured offset +3");
    assert.doesNotMatch(h.$("#mc-title").textContent, /NIEZWERYFIKOWANY/);
  },
  // chunk_47#1: production AVWAP = engine anchor (latest started session of the profile, closed bars, zero weights skipped); no NaN readout
  avwap_session_anchor() {
    const m = mount(PROD_ENV()); const t0 = Date.parse("2026-07-14T00:00:00Z");
    const d = bars(t0, 192, 300, { forming: true });                      // 00:00 .. 15:55Z, last bar forming
    m.api.setVM(vm({ tf: "M5", candles: d })); m.draw(1);
    const anchor = Date.parse("2026-07-14T12:20:00Z");                    // NEW_YORK 08:20 America/New_York (EDT) = latest started session
    let pv = 0, vv = 0; for (const b of d) if (b.closed && b.t >= anchor && b.v > 0) { const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; vv += b.v; }
    const got = (m.$("#mc-read").innerHTML.match(/AVWAP<b>([^<]*)</) || [])[1];
    assert.equal(got, (pv / vv).toFixed(2), "AVWAP at the forming bar = engine session AVWAP of closed bars");
    // reference mode (fixture test, no API): day anchor kept, but a zero-weight first bar gives '—' instead of NaN
    const r = mount({}); const dr = bars(Date.parse("2026-07-13T20:00:00Z"), 130, 300, { v: (i) => (i === 48 ? 0 : 100) });   // i=48 -> 00:00Z
    r.api.setVM(vm({ tf: "M5", candles: dr })); hoverIndex(r, 48, 130); r.draw(1);
    const gr = (r.$("#mc-read").innerHTML.match(/AVWAP<b>([^<]*)</) || [])[1];
    assert.equal(gr, "—", "zero weight at the day anchor -> no value, never NaN");
  },
  // chunk_47#2/#3/#4: local mock layers (walls HV_PROXY, AI levels, patterns, Granite) are NIEDOSTĘPNE in production from the first frame
  mock_layers_unavailable_in_prod() {
    const m = mount(PROD_ENV());
    const off = {};
    for (const [t, k] of [["ind", "ai"], ["zones", "walls"], ["zones", "patterns"], ["models", "granite"]]) {
      m.tab(t); const b = sw(m, k); assert.ok(b, k);
      off[k] = b.hasAttribute("disabled"); b.click();                      // a user click before the first API answer
    }
    assert.deepEqual(off, { ai: true, walls: true, patterns: true, granite: true }, "switches disabled in production before meta arrives");
    m.api.setVM(vm({ tf: "M15", candles: bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900) })); m.draw(2);
    const tx = m.texts();
    for (const s of ["GRANITE TTM · punkt", "AI: strefa wejścia", "WALL +1σ · HV_PROXY", "DAILY OPEN"]) assert.ok(!tx.includes(s), `drawn in production: ${s}`);
    assert.ok(!tx.some((s) => s.startsWith("◇ formacja")), "pattern mock drawn in production");
    // fixture test mode (1:1 with the reference): the same switches stay as in the reference
    const fx = JSON.parse(fs.readFileSync(path.join(FIXTURES, "K5_xau_m15_plan.json"), "utf8"));
    const r = mount({}); r.api.load(fx);
    for (const [t, k] of [["ind", "ai"], ["zones", "walls"], ["zones", "patterns"], ["models", "granite"]]) { r.tab(t); assert.ok(!sw(r, k).hasAttribute("disabled"), `test mode ${k}`); }
  },
  // chunk_47#5: the canvas bitmap follows a height-only resize
  canvas_height_follows_view() {
    const m = mount(PROD_ENV()); m.draw(1);
    assert.equal(m.$("#chart").height, 700);
    m.S.view.h = 820; m.draw(1);
    assert.equal(m.$("#chart").height, 820, "height-only resize");
  },
  // chunk_47#6: refreshes do not undo the user's Kronos switches / TF and do not restart the forecast animation
  kronos_user_choice_kept() {
    const m = mount(PROD_ENV()); const cs = bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900);
    m.api.setVM(vm({ candles: cs })); m.api.setKronos(kronos("M5")); m.draw(30);
    const lab = (x) => x.log.some((c) => c[0] === "fillText" && c[2] === 1420 - 64 + 7);   // Kronos pred_close_h axis label = animation finished
    assert.ok(lab(m), "forecast animation finished");
    m.api.setVM(vm({ candles: cs })); m.draw(1);
    assert.ok(lab(m), "refresh with the same forecast must not restart the animation");
    m.tab("models"); m.$('#opt-body .sw[data-k="M5"]').click();
    assert.equal(m.$('#opt-body .sw[data-k="M5"]').getAttribute("aria-pressed"), "false");
    m.api.setVM(vm({ candles: cs })); m.api.setKronos(kronos("M5"));
    assert.equal(m.$('#opt-body .sw[data-k="M5"]').getAttribute("aria-pressed"), "false", "user switch-off of Kronos M5 survives a refresh");
    m.$('#opt-body .sw[data-k="M5"]').click();                            // back on
    m.$('#kr-tf [data-k="H1"]').click();                                  // user picks Kronos H1; the M5 forecast is still the last VM
    m.api.setVM(vm({ candles: cs })); m.draw(2);
    assert.equal(m.$('#kr-tf [data-k="H1"]').getAttribute("aria-pressed"), "true");
    assert.equal(m.$("#kr-dir").textContent, "—", "M5 forecast must not come back under the H1 button");
    assert.ok(!m.texts().some((s) => s.startsWith("KRONOS M5")), "M5 forecast line on the main chart after switching to H1");
  },
  // chunk_47#7: the first TF buttons (before /timeframes answers) fetch the new TF and the buttons follow the TF of the data
  tf_buttons_initial() {
    const m = mount(PROD_ENV()); const ev = [];
    m.api.onSelect((e) => ev.push(e));
    m.api.setVM(vm({ candles: bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900) }));
    m.$('#ch-tf [data-tf="H1"]').click();
    assert.ok(ev.some((e) => e.what === "series" && e.tf === "H1"), "TF change reaches the data hook");
    assert.equal(m.api.state().candles, 0, "candles of the old TF are dropped");
    m.api.setVM(vm({ tf: "M15", candles: bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900) }));
    assert.equal(m.$('#ch-tf [data-tf="M15"]').getAttribute("aria-pressed"), "true");
    assert.equal(m.$('#ch-tf [data-tf="H1"]').getAttribute("aria-pressed"), "false");
  },
  // chunk_47#8: missing fields in the plan card are '—' / UNKNOWN, never "null" or a false statement
  card_null_fields() {
    const t = Date.parse("2026-11-20T09:00:00Z"), d = bars(t - 100 * 900000, 130, 900);
    const m = mount(PROD_ENV()); m.api.setVM(vm({ candles: d, signals: [basketSig(t, { rg: null, ro: null, to: null })] })); m.draw(1);
    const h = m.$("#sig-card").innerHTML;
    assert.ok(!/null/.test(h), "basket card prints null");
    assert.ok(!/poza routingiem AUTO/.test(h), "unknown routing shown as 'outside AUTO'");
    assert.match(h, /NIEZNANY/);
    const l = mount(PROD_ENV()); l.api.setVM(vm({ candles: d, signals: [legacySig(t, { sc: null })] })); l.draw(1);
    assert.ok(!/null/.test(l.$("#sig-card").innerHTML), "legacy card prints null");
  },
  // chunk_47#9: SVP bin / prices use the symbol tick and digits from the view model; without them production marks the tick unverified
  svp_tick_from_vm() {
    const m = mount(PROD_ENV()); const d = bars(Date.parse("2026-11-20T00:00:00Z"), 130, 300);
    m.api.setVM(vm({ tf: "M5", candles: d, tick: 0.001, digits: 3 })); m.tab("vp");
    assert.match(m.$("#opt-body").innerHTML, /bin = 0\.050</, "bin = 50 ticks x 0.001");
    const n = mount(PROD_ENV()); n.api.setVM(vm({ tf: "M5", candles: d })); n.tab("vp");
    assert.match(n.$("#opt-body").innerHTML, /NIEZWERYFIKOWANY/, "tick unknown in production");
  },
  // chunk_47#10: no closed candle (only the forming one) must not throw in setVM / draw
  svp_no_closed_candle() {
    const m = mount(PROD_ENV());
    assert.doesNotThrow(() => m.api.setVM(vm({ tf: "M5", candles: bars(Date.parse("2026-11-20T10:00:00Z"), 1, 300, { forming: true }) })));
    assert.doesNotThrow(() => m.draw(2));
  },
  // chunk_47#11: the delayed VISIBLE request uses the TF / bin / VA of its key and a failed request is not repeated every 1.2 s
  async vpa_request_params_and_backoff() {
    const T = new Map(); let id = 0; const st = globalThis.setTimeout, ct = globalThis.clearTimeout;
    globalThis.setTimeout = (f) => { T.set(++id, f); return id; }; globalThis.clearTimeout = (i) => { T.delete(i); };
    const fire = () => { const fs_ = [...T.values()]; T.clear(); fs_.forEach((f) => f()); };
    const calls = [];
    try {
      const m = mount(PROD_ENV({ visible: async (q) => { calls.push(q); return null; } }));
      m.api.setTimeframes([{ tf: "M15", seconds: 900, role: "SETUP", core: true }, { tf: "H1", seconds: 3600, role: "LOCAL_CONTEXT", core: true }]);
      m.api.setVM(vm({ candles: bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900) }));
      m.tab("vp"); sw(m, "vp").click(); m.draw(1);
      assert.equal(T.size, 1, "VISIBLE request scheduled");
      m.$('#ch-tf [data-tf="H1"]').click(); m.draw(1); fire();
      assert.ok(calls.every((q) => q.tf === "M15"), `request sent with another TF than its key: ${JSON.stringify(calls.map((q) => q.tf))}`);
      m.api.setVM(vm({ tf: "M15", candles: bars(Date.parse("2026-11-20T00:00:00Z"), 130, 900) })); m.draw(1);
      const n0 = calls.length; fire(); await new Promise((r) => st(r, 5));
      assert.equal(calls.length, n0 + 1, "request sent");
      m.draw(5);
      assert.equal(T.size, 0, "after a failed request no new request within the back-off");
    } finally { globalThis.setTimeout = st; globalThis.clearTimeout = ct; }
  },
  // chunk_47#12: a missing target is labelled with its own number
  tp_label_missing() {
    const t = Date.parse("2026-11-20T09:00:00Z"), d = bars(t - 100 * 900000, 130, 900);
    const m = mount(PROD_ENV()); m.api.setVM(vm({ candles: d, signals: [basketSig(t, { tp: [4010] })] })); m.draw(1);
    const h = m.$("#sig-card").innerHTML;
    assert.equal((h.match(/<span>TP3<\/span>/g) || []).length, 1, "TP3 row once");
    assert.match(h, /<span>TP2<\/span><span>—<\/span>/, "missing TP2 row");
    assert.ok(m.texts().includes("TP2–TP3 – brak w kontrakcie tej strategii"), m.texts().filter((s) => /TP/.test(s)).join(" | "));
  },
  // chunk_47#13: old signals loaded in later batches are not announced as new; a new one is
  announce_only_new() {
    const ann = []; const m = mount(PROD_ENV({ announce: (s) => ann.push(s) })); const now = Date.now();
    const d = bars(now - 130 * 900000, 130, 900), s1 = basketSig(d[100].t);
    m.api.setVM(vm({ candles: d, signals: [s1] }));
    m.api.setVM(vm({ candles: d, signals: [s1, legacySig(now - 5 * 3600000)] }));
    assert.deepEqual(ann, [], "old S01 loaded later announced as new");
    m.api.setVM(vm({ candles: d, signals: [s1, legacySig(now - 5 * 3600000), basketSig(now - 60000, { sid: "FX_SMC_01" })] }));
    assert.equal(ann.length, 1, "a new signal is announced");
    assert.match(ann[0], /Nowy sygnał FX_SMC_01/);
  },
  // chunk_47#14: onSelect returns an unsubscribe function
  onselect_unsubscribe() {
    const m = mount(PROD_ENV()); const ev = [];
    const off = m.api.onSelect((e) => ev.push(e));
    assert.equal(typeof off, "function");
    off();
    m.api.setTimeframes([{ tf: "M15", seconds: 900, role: "SETUP", core: true }, { tf: "H1", seconds: 3600, role: "LOCAL_CONTEXT", core: true }]);
    m.$('#ch-tf [data-tf="H1"]').click();
    assert.equal(ev.length, 0, "listener still called after unsubscribe");
  },
  // chunk_47#15: a data refresh keeps keyboard focus in the options panel and in the plan card
  focus_kept_on_refresh() {
    const t = Date.parse("2026-11-20T09:00:00Z"), d = bars(t - 100 * 900000, 130, 900);
    const m = mount(PROD_ENV()); m.api.setVM(vm({ candles: d, signals: [basketSig(t)] })); m.draw(1);
    sw(m, "ema").focus();
    m.api.setVM(vm({ candles: d, signals: [basketSig(t)] })); m.draw(1);
    const ae = m.doc.activeElement;
    assert.ok(m.$("#opt-body").contains(ae) && ae.getAttribute("data-l") === "ema", "focus lost in #opt-body");
    m.$("#sig-card .sh").focus();
    m.api.setVM(vm({ candles: d, signals: [basketSig(t)] })); m.draw(1);
    assert.ok(m.$("#sig-card").contains(m.doc.activeElement), "focus lost in the plan card");
  },
  // chunk_47#16: the "common crosshair" switch has no function - unavailable in production
  sync_unavailable_prod() {
    const m = mount(PROD_ENV()); m.tab("chart");
    assert.ok(sw(m, "sync").hasAttribute("disabled"));
    assert.match(m.$("#opt-body").innerHTML, /Wspólny celownik<small>NIEDOSTĘPNE/);
  },
  // chunk_47#17: dead code of the reference preview removed, header comment no longer claims local demo numbers
  dead_code_removed() {
    for (const s of ["function volProfile", "#ctl-chart", "STR.sel=STR.sel", "lastTick", "zmPrev", "hedge={entry", "Tu wszystkie liczby są generowane lokalnie"])
      assert.ok(!SRC.includes(s), `still in chartsRender.ts: ${s}`);
  },
};

let bad = 0;
for (const [name, fn] of Object.entries(CASES)) {
  if (only.length && !only.includes(name)) continue;
  try { await fn(); console.log(name, "OK"); } catch (e) { bad++; console.log(name, "FAIL:", (e && e.message) || e); }
}
if (bad) { console.log("FAILED", bad); process.exit(1); }
console.log("audit146 d_frontend_3 OK");
