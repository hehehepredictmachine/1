// @ts-nocheck - 1:1 port of the approved reference script (REFERENCJE/GALAXY_V2/PepeMarketWizard_GALAXY_FULL_NEURAL_MESH_V2.html):
// the same layout model, the same canvas renderers (stars, orbital scaffolding, the FULL K_n mesh - every pair of planets, bi-directional
// pulses -, side emitters with filaments / particles / branching lightning, the bottom electric band), the same live editor and JSON
// import / export. Changes against the reference (integration only, the visuals are untouched):
//   * DOM queries are scoped to the mounted root, every listener / rAF / observer / video is released on unmount;
//   * a planet opens the REAL screen of the bot (route), a planet without a route shows "Niepołączony moduł" (no mock section);
//   * the status pill shows the backend state (opts.status()) - never a fake "ONLINE";
//   * the editor can also choose the route of a planet; the layout key of the reference is kept (saved layouts keep working).
// Everything drawn here is a visual effect: it never reads model results and never claims model activity.
export type GalaxyOpts = {
  open: (route: string | null, name: string) => void;
  routes: { value: string; label: string }[];
  status: () => { text: string; tone: "ok" | "warn" | "bad" };
};

export const GALAXY_KEY = "PMW_GALAXY_LIVE_V1";
const A = "/assets/galaxy/";
const assets = { center: A + "center.webp", brain: A + "brain.webp", bank: A + "bank.webp", roi: A + "roi.webp", settings: A + "settings.webp",
  models: A + "models.webp", signals: A + "signals.webp" };
export const DEFAULT_PLANETS = [
  { id: "center", name: "WTC PEPE", x: .50, y: .49, scale: 1, color: "#ae5cff", image: "center", central: true, route: "pepe-wtc" },
  { id: "brain", name: "Brain Signal", x: .26, y: .22, scale: 1, color: "#9d6eff", image: "brain", route: "pepe-signal" },
  { id: "bank", name: "PEPE$BANK", x: .75, y: .22, scale: 1, color: "#25ffbb", image: "bank", route: "lightning" },
  { id: "roi", name: "PEPE$ROI", x: .115, y: .49, scale: 1, color: "#72ffb7", image: "roi", route: "profits" },
  { id: "settings", name: "Settings", x: .875, y: .50, scale: 1, color: "#2bc0ff", image: "settings", route: "ustawienia" },
  { id: "models", name: "Models", x: .27, y: .81, scale: 1, color: "#c275ff", image: "models", route: "modele" },
  { id: "signals", name: "Signals", x: .74, y: .82, scale: 1, color: "#26dfff", image: "signals", route: "sygnal" },
];
const defaults = { planets: DEFAULT_PLANETS, speed: 1, animate: true, connections: true, sides: true, lightning: true, stars: true, neuralIntensity: 1.35 };
const deepClone = (x) => JSON.parse(JSON.stringify(x));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const rand = (a, b) => a + Math.random() * (b - a);

export function sanitizeModel(raw, validRoutes?: Set<string>) {
  const p = (raw.planets || []).filter((x) => x && typeof x === "object").slice(0, 22).map((x, i) => {
    const def = DEFAULT_PLANETS.find((d) => d.id === x.id);
    let route = typeof x.route === "string" ? x.route : (def ? def.route : null);
    if (route && validRoutes && !validRoutes.has(route)) route = null;
    return { id: String(x.id || "p" + i).slice(0, 60), name: String(x.name || "Planet").slice(0, 28), x: clamp(Number(x.x) || .5, .03, .97),
      y: clamp(Number(x.y) || .5, .05, .95), scale: clamp(Number(x.scale) || 1, .55, 1.7), color: /^#[\da-fA-F]{6}$/.test(x.color) ? x.color : "#a56aff",
      image: assets[x.image] ? x.image : "models", central: !!x.central, route };
  });
  return { planets: p.length ? p : deepClone(DEFAULT_PLANETS), speed: clamp(Number(raw.speed ?? 1), 0, 2.5), animate: raw.animate !== false,
    connections: raw.connections !== false, sides: raw.sides !== false, lightning: raw.lightning !== false, stars: raw.stars !== false,
    neuralIntensity: clamp(Number(raw.neuralIntensity ?? 1.35), .6, 1.8) };
}

/** Number of links of the full mesh for n planets: n(n-1)/2 (7 -> 21). */
export const meshLinks = (n: number) => (n * (n - 1)) / 2;

export function mountGalaxy(root: HTMLElement, opts: GalaxyOpts): () => void {
  const validRoutes = new Set(opts.routes.map((r) => r.value));
  let model = deepClone(defaults);
  try { const saved = JSON.parse(localStorage.getItem(GALAXY_KEY)); if (saved && Array.isArray(saved.planets) && saved.planets.length > 0) model = sanitizeModel(saved, validRoutes); } catch (e) { /* storage unavailable */ }
  let edit = false, paused = !!window.matchMedia("(prefers-reduced-motion: reduce)").matches, selectedId = "center", time = 0, last = 0, screenW = 1000, screenH = 600, dpr = 1, starfield = [], leftSparks = [], rightSparks = [];
  let alive = true, raf = 0, hidden = false;
  // 1.40 adaptive quality: the real cost of drawing a frame is measured; above ~12 ms (slow GPU / software rendering) the effects are
  // simplified (fewer filaments, no glow blur, fewer particles) and the loop runs at 30 FPS; it goes back up when the cost falls.
  let quality = 1, frameGap = 16, lastDraw = 0, lowSince = 0, retries = 0, booting = false;
  const $ = (s) => root.querySelector(s), $$ = (s) => [...root.querySelectorAll(s)];
  const space = $("#space"), layer = $("#planetLayer");
  const canvases = { galaxy: $("#galaxyCanvas"), left: $("#leftCanvas"), right: $("#rightCanvas"), lightning: $("#lightningCanvas") };
  const ctx = {}; for (const k in canvases) ctx[k] = canvases[k].getContext("2d");
  // 1.40: glow by shadowBlur is the main raster cost (CPU / weak GPU: ~400 blurred strokes per frame). In the simplified quality every
  // shadowBlur write becomes 0 - the layered strokes of the reference keep the look, the blur is dropped.
  const SB = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, "shadowBlur");
  for (const k in ctx) Object.defineProperty(ctx[k], "shadowBlur", { configurable: true, get() { return SB.get.call(this); }, set(v) { SB.set.call(this, quality === 1 ? v : 0); } });
  const cleanups: (() => void)[] = [];
  const on = (el, ev, fn, o?) => { el.addEventListener(ev, fn, o); cleanups.push(() => el.removeEventListener(ev, fn, o)); };

  function save() { try { localStorage.setItem(GALAXY_KEY, JSON.stringify(model)); } catch (e) { /* storage unavailable */ } }
  function toast(txt) { const el = $("#toast"); el.textContent = txt; el.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 2200); }
  function planetSize(p) { const base = (p.central ? Math.min(330, screenW * .30, screenH * .54) : Math.min(218, screenW * .203, screenH * .36)); return Math.max(p.central ? 125 : 72, base) * p.scale; }
  function actualXY(p, i) {
    const x = p.x * screenW, y = p.y * screenH;
    if (!model.animate || edit || paused) return { x, y };
    const t = time * .00029, phase = i * 1.87;
    const scale = p.central ? .23 : 1;
    const rx = Math.min(14, screenW * .014) * scale, ry = Math.min(12, screenH * .023) * scale;
    return { x: x + Math.cos(t + phase) * rx + Math.sin(t * .41 + phase) * rx * .22, y: y + Math.sin(t * .86 + phase) * ry + Math.cos(t * .37 + phase) * ry * .27 };
  }
  const elements = new Map(); let hoveredId = null; let dragState = null;
  function escapeHTML(s) { return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function renderPlanets() {
    layer.innerHTML = ""; elements.clear();
    model.planets.forEach((p, i) => {
      const btn = document.createElement("button"); btn.className = "planet" + (p.central ? " central" : ""); btn.type = "button"; btn.style.setProperty("--c", p.color);
      btn.setAttribute("aria-label", "Otwórz " + p.name); btn.title = p.name; btn.dataset.testid = "gx-planet"; btn.setAttribute("data-testid", "gx-planet-" + p.id);
      btn.innerHTML = '<img class="image" alt="" draggable="false"><span class="planet-title"></span><span class="planet-hint">Otwórz: ' + escapeHTML(p.name) + '</span><i class="orbit-dot"></i>';
      btn.querySelector("img").src = assets[p.image] || assets.models; btn.querySelector(".planet-title").textContent = p.name;
      btn.style.zIndex = p.central ? 6 : 5; btn.dataset.id = p.id;
      btn.addEventListener("pointerenter", () => hoveredId = p.id); btn.addEventListener("pointerleave", () => { if (hoveredId === p.id) hoveredId = null; });
      btn.addEventListener("pointerdown", (e) => { if (edit) { selectedId = p.id; updateSelection(); btn.setPointerCapture(e.pointerId); dragState = { id: p.id, x: e.clientX, y: e.clientY, px: p.x, py: p.y, moved: false }; btn.classList.add("dragging"); e.preventDefault(); } });
      btn.addEventListener("pointermove", (e) => { if (!dragState || dragState.id !== p.id) return; const dx = (e.clientX - dragState.x) / screenW, dy = (e.clientY - dragState.y) / screenH; if (Math.abs(dx) + Math.abs(dy) > .004) dragState.moved = true; p.x = clamp(dragState.px + dx, .04, .96); p.y = clamp(dragState.py + dy, .06, .94); syncInspectorValues(); save(); });
      btn.addEventListener("pointerup", () => { if (dragState && dragState.id === p.id) { const moved = dragState.moved; dragState = null; btn.classList.remove("dragging"); if (!moved) updateSelection(); } });
      btn.addEventListener("pointercancel", () => { dragState = null; btn.classList.remove("dragging"); });
      btn.addEventListener("click", () => { if (edit) { selectedId = p.id; updateSelection(); } else openSection(p); });
      layer.append(btn); elements.set(p.id, btn);
    });
    updatePlanetPositions(); refreshSelect(); updateMeshStatus();
  }
  function updatePlanetPositions() {
    // 1.40: position by transform only (compositor) - left / top every frame forced a layout of the whole menu; width / colour / class only on change
    model.planets.forEach((p, i) => {
      const el = elements.get(p.id); if (!el) return;
      const xy = actualXY(p, i), s = Math.round(planetSize(p));
      if (el._w !== s) { el.style.width = s + "px"; el._w = s; }
      if (!el._init) { el.style.left = "0px"; el.style.top = "0px"; el._init = true; }
      el.style.transform = `translate3d(${xy.x.toFixed(1)}px, ${xy.y.toFixed(1)}px, 0) translate(-50%,-50%)`;
      const sel = edit && selectedId === p.id;
      if (el._sel !== sel) { el.classList.toggle("selected", sel); el._sel = sel; }
      if (el._c !== p.color) { el.style.setProperty("--c", p.color); el._c = p.color; }
    });
  }
  function refreshSelect() {
    const el = $("#selectPlanet"); el.innerHTML = "";
    model.planets.forEach((p) => { const opt = document.createElement("option"); opt.value = p.id; opt.textContent = p.name; el.appendChild(opt); });
    if (!model.planets.some((p) => p.id === selectedId)) selectedId = model.planets[0]?.id || ""; el.value = selectedId; syncInspectorValues();
  }
  const selected = () => model.planets.find((p) => p.id === selectedId);
  function syncInspectorValues() {
    const p = selected(); if (!p) return;
    $("#selectPlanet").value = p.id; $("#planetName").value = p.name; $("#planetColor").value = p.color; $("#planetRoute").value = p.route || "";
    $("#planetSize").value = Math.round(p.scale * 100); $("#planetX").value = Math.round(p.x * 100); $("#planetY").value = Math.round(p.y * 100);
    $("#sizeValue").textContent = Math.round(p.scale * 100) + "%"; $("#xValue").textContent = Math.round(p.x * 100) + "%"; $("#yValue").textContent = Math.round(p.y * 100) + "%";
  }
  function updateSelection() { updatePlanetPositions(); refreshSelect(); }
  function setupInspector() {
    const rs = $("#planetRoute");
    rs.innerHTML = '<option value="">— brak (Niepołączony moduł) —</option>' + opts.routes.map((r) => `<option value="${escapeHTML(r.value)}">${escapeHTML(r.label)}</option>`).join("");
    const bind = (key, fn) => on($(key), "input", (e) => { const p = selected(); if (!p) return; fn(p, e.target.value); const el = elements.get(p.id); if (el) { el.querySelector(".planet-title").textContent = p.name; el.setAttribute("aria-label", "Otwórz " + p.name); el.title = p.name; } refreshSelect(); save(); });
    bind("#planetName", (p, v) => p.name = v.slice(0, 28)); bind("#planetColor", (p, v) => p.color = v); bind("#planetSize", (p, v) => p.scale = Number(v) / 100);
    bind("#planetX", (p, v) => p.x = Number(v) / 100); bind("#planetY", (p, v) => p.y = Number(v) / 100);
    on(rs, "change", (e) => { const p = selected(); if (!p) return; p.route = e.target.value || null; save(); toast(p.route ? `${p.name} → ${p.route}` : `${p.name}: niepołączony moduł`); });
    on($("#selectPlanet"), "change", (e) => { selectedId = e.target.value; updateSelection(); });
    space.classList.toggle("no-motion", !model.animate);
    $("#speedRange").value = Math.round(model.speed * 100); $("#speedValue").textContent = Math.round(model.speed * 100) + "%";
    on($("#speedRange"), "input", (e) => { model.speed = Number(e.target.value) / 100; $("#speedValue").textContent = e.target.value + "%"; save(); });
    $("#neuralIntensity").value = Math.round(model.neuralIntensity * 100); $("#neuralIntensityValue").textContent = Math.round(model.neuralIntensity * 100) + "%";
    on($("#neuralIntensity"), "input", (e) => { model.neuralIntensity = Number(e.target.value) / 100; $("#neuralIntensityValue").textContent = e.target.value + "%"; save(); });
    [["animateToggle", "animate"], ["connectionsToggle", "connections"], ["sidesToggle", "sides"], ["lightningToggle", "lightning"], ["starsToggle", "stars"]].forEach(([id, k]) => {
      const a = $("#" + id); a.checked = model[k];
      on(a, "change", () => { model[k] = a.checked; if (k === "animate") space.classList.toggle("no-motion", !model.animate); if (k === "connections") updateMeshStatus(); if (k === "sides") syncSideVideos(); save(); });
    });
    $("#addPlanet").onclick = () => { const newId = "planet_" + Date.now(); model.planets.push({ id: newId, name: "Nowa planeta", x: rand(.32, .67), y: rand(.3, .7), scale: .8, color: "#8e72ff", image: "models", route: null }); selectedId = newId; renderPlanets(); save(); toast("Nowa planeta dodana — edytuj jej nazwę i sekcję"); };
    $("#deletePlanet").onclick = () => { if (model.planets.length === 1) return toast("Zachowaj co najmniej jedną planetę"); const p = selected(); if (!p) return; model.planets = model.planets.filter((x) => x.id !== p.id); selectedId = model.planets[0].id; renderPlanets(); save(); toast("Planeta usunięta"); };
    $("#resetBtn").onclick = () => { if (!confirm("Przywrócić początkową galaktykę? Zmiany projektu zostaną zastąpione.")) return; model = deepClone(defaults); selectedId = "center"; renderPlanets(); syncSettings(); save(); toast("Przywrócono projekt początkowy"); };
    $("#exportBtn").onclick = () => { download("PepeMarketWizard_Galaxy_Projekt.json", JSON.stringify(model, null, 2), "application/json"); toast("Wyeksportowano projekt JSON"); };
    $("#importBtn").onclick = () => $("#importInput").click();
    $("#importInput").onchange = async (e) => { const f = e.target.files?.[0]; if (!f) return; try { model = sanitizeModel(JSON.parse(await f.text()), validRoutes); selectedId = model.planets[0].id; renderPlanets(); syncSettings(); save(); toast("Zaimportowano projekt — podgląd aktualny"); } catch (err) { toast("Plik JSON nie jest prawidłowy"); } e.target.value = ""; };
  }
  function syncSettings() {
    space.classList.toggle("no-motion", !model.animate); const a = $("#speedRange"); a.value = Math.round(model.speed * 100); $("#speedValue").textContent = Math.round(model.speed * 100) + "%";
    $("#neuralIntensity").value = Math.round(model.neuralIntensity * 100); $("#neuralIntensityValue").textContent = Math.round(model.neuralIntensity * 100) + "%"; syncSideVideos(); updateMeshStatus();
    [["animateToggle", "animate"], ["connectionsToggle", "connections"], ["sidesToggle", "sides"], ["lightningToggle", "lightning"], ["starsToggle", "stars"]].forEach(([id, k]) => $("#" + id).checked = model[k]);
  }
  function download(name, text, mime) { const b = new Blob([text], { type: mime }); const u = URL.createObjectURL(b), a = document.createElement("a"); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1500); }
  function setEdit(next) { edit = next; root.classList.toggle("editing", edit); $("#inspector").classList.toggle("show", edit); $("#editBtn").classList.toggle("active", edit); $("#editBtn").setAttribute("aria-pressed", edit); $("#caption").textContent = edit ? "Przeciągnij planetę lub użyj inspektora" : "Wybierz planetę, aby otworzyć sekcję"; updatePlanetPositions(); }
  $("#editBtn").onclick = () => setEdit(!edit); $("#editorFloatBtn").onclick = () => setEdit(!edit); $("#closeEditor").onclick = () => setEdit(false); $("#exitEdit").onclick = () => setEdit(false);
  function setPause(v) { paused = v; syncSideVideos(); root.classList.toggle("paused", paused); $("#playBtn").textContent = paused ? "▶" : "Ⅱ"; $("#pauseEdit").textContent = paused ? "▶ Wznów" : "Ⅱ Animacja"; toast(paused ? "Animacje wstrzymane" : "Animacje uruchomione"); }
  $("#playBtn").onclick = () => setPause(!paused); $("#pauseEdit").onclick = () => setPause(!paused);
  $("#fullBtn").onclick = async () => { try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen(); } catch (err) { toast("Pełny ekran nie jest dostępny"); } };
  $("#centerBtn").onclick = () => { const initial = deepClone(DEFAULT_PLANETS); for (let i = 0; i < model.planets.length; i++) { const original = initial.find((q) => q.id === model.planets[i].id); if (original) { model.planets[i].x = original.x; model.planets[i].y = original.y; } } save(); syncInspectorValues(); toast("Przywrócono rozmieszczenie planet"); };
  function openSection(p) {
    if (edit) { toast("Zakończ tryb edycji, aby otwierać sekcje"); return; }
    if (p.route && validRoutes.has(p.route)) { opts.open(p.route, p.name); return; }
    $("#modalTitle").textContent = p.name;
    $("#modalDesc").textContent = "Niepołączony moduł – ta planeta nie ma przypisanej sekcji bota. Przypisz ją w edytorze (✎ → Sekcja bota).";
    $("#modalCards").innerHTML = ""; $("#sectionModal").classList.add("show"); $("#sectionModal").setAttribute("aria-hidden", "false"); $("#closeModal").focus();
  }
  function closeSection() { $("#sectionModal").classList.remove("show"); $("#sectionModal").setAttribute("aria-hidden", "true"); }
  $("#closeModal").onclick = closeSection; $("#backToGalaxy").onclick = closeSection;
  on($("#sectionModal"), "click", (e) => { if (e.target.id === "sectionModal") closeSection(); });
  $("#neuralCityBtn").onclick = () => { setEdit(false); opts.open("neural-city", "Neural City"); };
  $$(".nav [data-route]").forEach((b) => b.onclick = () => { const r = b.dataset.route; if (r === "home") { closeSection(); return; } opts.open(r, b.textContent.trim()); });
  on(document, "keydown", (e) => { if (e.key === "Escape") { closeSection(); if (edit) setEdit(false); } if (e.key === " " && e.target === document.body) { e.preventDefault(); setPause(!paused); } });
  on(document, "visibilitychange", () => { hidden = document.hidden; syncSideVideos(); });
  function updateMeshStatus() { const possible = meshLinks(model.planets.length); const current = model.connections ? possible : 0; $("#meshCount").textContent = current + " / " + possible; root.dataset.meshLinks = String(current); root.dataset.meshPossible = String(possible); }
  function resize() { dpr = Math.min(window.devicePixelRatio || 1, 1.25); const r = space.getBoundingClientRect(); screenW = r.width; screenH = r.height; for (const [k, c] of Object.entries(canvases)) { const rr = c.getBoundingClientRect(); c.width = Math.max(1, Math.floor(rr.width * dpr)); c.height = Math.max(1, Math.floor(rr.height * dpr)); ctx[k].setTransform(dpr, 0, 0, dpr, 0, 0); } makeStars(); makeSideSparks(); updatePlanetPositions(); }
  function makeStars() { starfield = Array.from({ length: Math.floor(clamp(screenW * screenH / 2100, 120, 350)) }, () => ({ x: Math.random(), y: Math.random(), a: rand(.1, .65), r: rand(.25, 1.4), phase: rand(0, 6.28), g: Math.random() < .4 })); }
  function makeSideSparks() { leftSparks = Array.from({ length: 235 }, () => ({ x: Math.random(), y: Math.random(), speed: rand(.025, .17), rad: rand(.4, 1.95), phase: rand(0, 6.28) })); rightSparks = Array.from({ length: 235 }, () => ({ x: Math.random(), y: Math.random(), speed: rand(.025, .17), rad: rand(.4, 1.95), phase: rand(0, 6.28) })); }
  function rgb(hex) { const s = (hex || "#aa77ff").replace("#", ""); return [parseInt(s.slice(0, 2), 16) || 0, parseInt(s.slice(2, 4), 16) || 0, parseInt(s.slice(4, 6), 16) || 0]; }
  let drawnLinks = 0;
  function drawGalaxy() {
    const c = ctx.galaxy, w = screenW, h = screenH;
    c.clearRect(0, 0, w, h); c.save(); c.globalCompositeOperation = "screen";
    if (model.stars) {
      for (const s of starfield) { const op = .45 + .5 * Math.sin(time * .002 + s.phase); c.fillStyle = s.g ? `rgba(35,250,167,${s.a * op})` : `rgba(201,181,255,${s.a * op})`; c.beginPath(); c.arc(s.x * w + Math.sin(time * .00015 + s.phase) * 1.5, s.y * h, s.r, 0, 6.283); c.fill(); }
    }
    const center = model.planets.find((p) => p.central) || model.planets[0];
    if (!center) { c.restore(); return; }
    const ci = model.planets.indexOf(center), o = actualXY(center, ci);
    drawnLinks = 0;
    if (model.connections) {
      for (let j = 0; j < 5; j++) { c.save(); c.translate(o.x, o.y); c.rotate(time * .000009 * (j % 2 === 0 ? 1 : -1) + j * .85); c.beginPath(); c.ellipse(0, 0, w * (.31 + j * .021), h * (.25 + j * .014), -.17, 0, 6.283); c.strokeStyle = j % 2 === 0 ? "rgba(126,82,250,.15)" : "rgba(36,202,232,.12)"; c.lineWidth = 1.2; c.stroke(); c.restore(); }
      const nodes = model.planets.map((p, i) => ({ p, i, pos: actualXY(p, i) }));
      const pairs = [];
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) { const a = nodes[i], b = nodes[j]; pairs.push({ a, b, primary: !!(a.p.central || b.p.central) }); }
      pairs.sort((a, b) => Number(a.primary) - Number(b.primary));
      const intensity = model.neuralIntensity || 1.35;
      for (const edge of pairs) {
        const { a, b, primary } = edge;
        const dx = b.pos.x - a.pos.x, dy = b.pos.y - a.pos.y, d = Math.max(1, Math.hypot(dx, dy)), ux = dx / d, uy = dy / d, nx = -uy, ny = ux;
        const apad = Math.min(planetSize(a.p) * .39, d * .23), bpad = Math.min(planetSize(b.p) * .39, d * .23);
        const x0 = a.pos.x + ux * apad, y0 = a.pos.y + uy * apad, x1 = b.pos.x - ux * bpad, y1 = b.pos.y - uy * bpad;
        const curveSign = ((a.i * 13 + b.i * 7) % 4 < 2) ? 1 : -1;
        const sag = curveSign * Math.min(primary ? 70 : 90, d * (primary ? .16 : .19));
        const mx = (x0 + x1) * .5 + nx * sag, my = (y0 + y1) * .5 + ny * sag;
        const ca = rgb(a.p.color), cb = rgb(b.p.color), mix = ca.map((v, k) => Math.round(v * .49 + cb[k] * .51));
        const focus = (hoveredId && (hoveredId === a.p.id || hoveredId === b.p.id)) || (edit && (selectedId === a.p.id || selectedId === b.p.id));
        const alpha = (primary ? .33 : .24) * (focus ? 1.75 : 1) * Math.min(1.18, intensity);
        c.beginPath(); c.moveTo(x0, y0); c.quadraticCurveTo(mx, my, x1, y1);
        c.strokeStyle = `rgba(${mix.join(",")},${alpha * .62})`; c.lineWidth = primary ? 3.4 : 2.1; c.shadowBlur = primary ? 18 : 12; c.shadowColor = `rgb(${mix.join(",")})`; c.stroke(); c.shadowBlur = 0;
        const strands = Math.max(quality < 1 ? 2 : 4, Math.round((primary ? 11 : 8) * intensity * quality));
        for (let strand = 0; strand < strands; strand++) {
          const spread = (strand - (strands - 1) / 2) * (primary ? 3.3 : 2.4);
          const speed = time * .0014 * (strand % 2 ? 1 : -.7);
          const brightness = (strand % 4 === 0 ? 1.55 : .85);
          c.strokeStyle = `rgba(${mix.join(",")},${Math.min(.83, alpha * brightness)})`; c.lineWidth = strand % 4 === 0 ? 1.35 : .68;
          if (strand % 5 === 0 && quality === 1) { c.shadowBlur = 9; c.shadowColor = `rgb(${mix.join(",")})`; }
          c.beginPath();
          for (let k = 0; k <= 26; k++) {
            const t = k / 26, inv = 1 - t;
            const baseX = inv * inv * x0 + 2 * inv * t * mx + t * t * x1, baseY = inv * inv * y0 + 2 * inv * t * my + t * t * y1;
            const wave = Math.sin(t * Math.PI) * (Math.sin(t * 23 + speed + strand * .85 + a.i * .6 + b.i * .2) * 5.2 + Math.sin(t * 41 - speed * 1.22 + strand) * 2.4 + spread);
            const x = baseX + nx * wave, y = baseY + ny * wave;
            if (k === 0) c.moveTo(x, y); else c.lineTo(x, y);
          }
          c.stroke(); c.shadowBlur = 0;
        }
        for (let pulse = 0; pulse < 3; pulse++) {
          const reverse = pulse === 1;
          const v = (time * .00018 * (1 + (.23 * ((a.i + b.i) % 4))) + pulse * .34 + a.i * .117 + b.i * .061) % 1;
          const t = reverse ? 1 - v : v, inv = 1 - t;
          const x = inv * inv * x0 + 2 * inv * t * mx + t * t * x1, y = inv * inv * y0 + 2 * inv * t * my + t * t * y1;
          const power = .54 + .42 * Math.sin(t * Math.PI);
          c.beginPath(); c.arc(x, y, (primary ? 2.1 : 1.8) * (pulse === 0 ? 1.25 : .85), 0, 6.283);
          c.fillStyle = `rgba(230,242,255,${power * (focus ? 1 : .77)})`; c.shadowColor = pulse === 1 ? "#50fbe7" : "#ba8bff"; c.shadowBlur = 16; c.fill(); c.shadowBlur = 0;
        }
        drawnLinks++;
      }
    }
    root.dataset.drawnLinks = String(drawnLinks);
    c.restore();
  }
  function drawSide(which, arr) {
    const canvas = canvases[which], c = ctx[which], w = canvas.width / dpr, h = canvas.height / dpr;
    c.clearRect(0, 0, w, h); if (!model.sides) return;
    c.save(); c.globalCompositeOperation = "screen";
    const t = time * .001, side = which === "left" ? 1 : -1, phase = which === "left" ? 0 : 2.23;
    for (let filament = 0; filament < 13; filament++) {
      const u = filament / 13, ph = phase + filament * .74;
      const col = filament % 4 === 0 ? "99,218,255" : filament % 3 === 0 ? "170,110,255" : "36,255,152";
      c.beginPath();
      for (let s = 0; s <= 54; s++) { const yy = (s / 54) * h; const spiral = Math.sin(yy * .013 + t * (.63 + (filament % 3) * .16) * side + ph) * w * (.23 + u * .05); const secondary = Math.sin(yy * .034 - t * .46 + ph) * w * .065; const xx = w * .5 + spiral + secondary + (u - .5) * w * .22; if (s === 0) c.moveTo(xx, yy); else c.lineTo(xx, yy); }
      c.strokeStyle = `rgba(${col},${.13 + .13 * (.5 + .5 * Math.sin(t * 1.4 + ph))})`; c.lineWidth = filament % 4 === 0 ? 1.6 : .74;
      if (filament % 4 === 0) { c.shadowColor = "#62fff3"; c.shadowBlur = 10; }
      c.stroke(); c.shadowBlur = 0;
    }
    const nShow = quality === 1 ? arr.length : Math.floor(arr.length * quality);
    for (let pi = 0; pi < nShow; pi++) { const p = arr[pi]; const yy = ((p.y - (t * p.speed) % 1 + 1) % 1) * h; const xx = (.5 + Math.sin(yy * .015 + t * 1.28 * side + p.phase) * .34) * w + (p.x - .5) * w * .31; const a = (.24 + .58 * Math.sin(t * 2.5 + p.phase) ** 2); c.fillStyle = p.x > .25 ? `rgba(41,255,158,${a})` : `rgba(111,174,255,${a})`; c.beginPath(); c.arc(xx, yy, p.rad, 0, 6.283); c.fill(); }
    for (let n = 0; n < 9; n++) { const y = h * (n + .52) / 9, x = w * (.5 + .31 * Math.sin(t * .94 + phase + n * .82)); const radius = 2.4 + 2 * Math.sin(t * 2 + n); c.beginPath(); c.arc(x, y, radius, 0, 6.283); c.fillStyle = "rgba(174,255,246,.38)"; c.shadowColor = "#50ffdf"; c.shadowBlur = 15; c.fill(); c.shadowBlur = 0; }
    const tick = Math.floor(time / 145), onBolt = Math.sin(tick * 12.51 + phase) > -.45;
    if (onBolt) {
      for (let bolt = 0; bolt < 3; bolt++) {
        const seed = tick * 17 + bolt * 47 + phase * 23;
        let x = w * (.25 + .5 * randHash(seed)); const py = h * .035; const pts = [[x, py]];
        for (let j = 1; j <= 24; j++) { const y = h * (.045 + j * .037); x = clamp(x + (randHash(seed + j * 1.74) - .5) * w * .26, w * .06, w * .94); pts.push([x, y]); }
        for (const [lw, alpha, col, blur] of [[6, .12, "25,115,255", 22], [2.8, .33, "45,153,255", 15], [.95, .77, "206,245,255", 7]]) { c.beginPath(); pts.forEach(([xx, yy], i) => i ? c.lineTo(xx, yy) : c.moveTo(xx, yy)); c.lineWidth = lw; c.strokeStyle = `rgba(${col},${alpha})`; c.shadowColor = "#36adff"; c.shadowBlur = blur; c.stroke(); }
        c.shadowBlur = 0;
        for (let branch = 0; branch < 4; branch++) { const j = 3 + Math.floor(randHash(seed + branch * 6.9) * 16); const from = pts[j], dir = randHash(seed + branch * 2.51) > .5 ? 1 : -1; c.beginPath(); c.moveTo(from[0], from[1]); for (let s = 1; s <= 5; s++) c.lineTo(from[0] + dir * s * w * .038 + (randHash(seed + s + branch) - .5) * w * .09, from[1] + s * h * .016); c.strokeStyle = "rgba(137,217,255,.49)"; c.lineWidth = .85; c.shadowColor = "#4bbaff"; c.shadowBlur = 9; c.stroke(); c.shadowBlur = 0; }
      }
    }
    c.restore();
  }
  function drawLightning() {
    const el = canvases.lightning, c = ctx.lightning, w = el.width / dpr, h = el.height / dpr;
    c.clearRect(0, 0, w, h); if (!model.lightning) return;
    c.save(); c.globalCompositeOperation = "screen";
    const t = time * .001;
    for (let wave = 0; wave < 5; wave++) { const y = h * (.31 + wave * .135); c.beginPath(); for (let j = 0; j <= 100; j++) { const x = j * w / 100; const yy = y + Math.sin(x * .016 + t * (1.1 + wave * .12) + wave * 1.5) * h * .035 + Math.sin(x * .051 - t * .67 + wave) * h * .014; j ? c.lineTo(x, yy) : c.moveTo(x, yy); } c.lineWidth = wave % 2 ? 1.2 : 2.4; c.strokeStyle = `rgba(${wave % 2 ? "111,98,255" : "67,194,255"},${.16 + .14 * Math.sin(t + wave) ** 2})`; c.shadowColor = "#3976ff"; c.shadowBlur = 9; c.stroke(); c.shadowBlur = 0; }
    const tick = Math.floor(time / 175), segments = quality === 1 ? 26 : 14;
    for (let i = 0; i < segments; i++) {
      const seed = tick * 23 + i * 31.7;
      if (randHash(seed) < .28) continue;
      const x = (i + .5) / segments * w + (randHash(seed + 2) - .5) * w * .024;
      const reach = h * (.40 + .51 * randHash(seed + 3)), origin = h * .88;
      const pts = [[x, origin]]; let xx = x;
      for (let j = 1; j <= 12; j++) { xx = x + (randHash(seed + j * .83) - .5) * w * .022 + Math.sin(j * 2.33 + seed) * w * .006; pts.push([xx, origin - reach * j / 12]); }
      const strength = .4 + .55 * randHash(seed + 1);
      for (const [lw, alpha, col, blur] of [[8, .095, "40,116,255", 19], [3.7, .28, "38,126,255", 12], [1.4, .72, "196,241,255", 7]]) { c.beginPath(); pts.forEach(([px, py], k) => k ? c.lineTo(px, py) : c.moveTo(px, py)); c.lineWidth = lw; c.strokeStyle = `rgba(${col},${alpha * strength})`; c.shadowColor = "#459fff"; c.shadowBlur = blur; c.stroke(); }
      for (let b = 0; b < 3; b++) { const j = 2 + Math.floor(randHash(seed + b * 12.7) * 8), from = pts[j], dir = randHash(seed + b * 2.71) > .5 ? 1 : -1; c.beginPath(); c.moveTo(from[0], from[1]); for (let s = 1; s <= 5; s++) c.lineTo(from[0] + dir * s * w * .0037 + (randHash(seed + b * 9 + s) - .5) * w * .008, from[1] - s * h * .035); c.strokeStyle = `rgba(139,214,255,${strength * .43})`; c.lineWidth = .9; c.shadowBlur = 10; c.stroke(); }
      c.shadowBlur = 0;
      c.fillStyle = `rgba(119,233,255,${strength * .7})`; c.beginPath(); c.arc(x, origin, 1.7, 0, 6.283); c.fill();
    }
    for (let j = 0; j < 95; j++) { const ph = randHash(j * 1.74), speed = .008 + .015 * randHash(j * 3.47); const x = ((ph + t * speed) % 1) * w, y = h * (.54 + .38 * randHash(j * 4.19)); c.fillStyle = `rgba(122,201,255,${.16 + .43 * Math.sin(t * 2 + j) ** 2})`; c.fillRect(x, y, 1.4, 1.3); }
    c.restore();
  }
  const sideVideos = [$("#sideVideoLeft"), $("#sideVideoRight")];
  for (const v of sideVideos) { v.src = A + "side_models.mp4"; v.muted = true; v.loop = true; v.playsInline = true; on(v, "error", () => { v.style.display = "none"; }); }
  on(sideVideos[1], "loadedmetadata", () => { try { sideVideos[1].currentTime = Math.min(3.35, sideVideos[1].duration * .4); } catch (e) { /* ignore */ } }, { once: true });
  function syncSideVideos() { for (const v of sideVideos) { v.style.opacity = model.sides ? ".58" : "0"; if (paused || hidden || !model.sides || !alive || quality < 1 || booting) v.pause(); else v.play().catch(() => { /* autoplay refused - the canvas effect still runs */ }); } }
  function randHash(n) { return (Math.sin(n * 12.9898) * 43758.5453) % 1 < 0 ? 1 + ((Math.sin(n * 12.9898) * 43758.5453) % 1) : ((Math.sin(n * 12.9898) * 43758.5453) % 1); }
  function setQuality(q, t) {
    quality = q; lowSince = t; frameGap = q === 1 ? 16 : frameGap;
    root.dataset.quality = q === 1 ? "high" : "low";
    root.classList.toggle("gx-lite", q < 1);                       // decorative CSS animations + side films off (measured costs)
    syncSideVideos();
  }
  function frame(t) {
    if (!alive) return;
    const b = !!document.getElementById("pmwBoot");               // START intro on top: films + CSS animations of the menu paused too
    if (b !== booting) { booting = b; root.classList.toggle("gx-under-boot", b); syncSideVideos(); }
    const delta = last ? Math.min(45, t - last) : 16; last = t;
    const minGap = quality < 1 ? 31 : 0;                          // 30 FPS when simplified
    if (!hidden && !document.getElementById("pmwBoot") && t - lastDraw >= minGap) {   // the START intro covers the menu: no drawing under it
      if (!paused) time += (lastDraw ? Math.min(66, t - lastDraw) : delta) * model.speed;
      lastDraw = t;
      drawGalaxy(); drawSide("left", leftSparks); drawSide("right", rightSparks); drawLightning(); updatePlanetPositions();
      // real frame interval (includes raster / compositing, which JS timing does not see)
      frameGap = frameGap * 0.85 + Math.min(1000, delta) * 0.15;
      if (quality === 1 && frameGap > 40) setQuality(0.4, t);
      else if (quality < 1 && retries < 2 && t - lowSince > 20000 && frameGap < 40) { retries++; setQuality(1, t); }
    }
    raf = requestAnimationFrame(frame);
  }
  function status() { try { const s = opts.status(); const el = $("#gxStatus"); el.querySelector("span").textContent = s.text; el.dataset.tone = s.tone; } catch (e) { /* ignore */ } }
  const statusTimer = setInterval(status, 1000); status();
  const observer = new ResizeObserver(resize); observer.observe(space); observer.observe($("#bottom")); observer.observe($("#sideLeft")); observer.observe($("#sideRight"));
  root.dataset.quality = "high";
  setupInspector(); renderPlanets(); syncSettings(); resize(); syncSideVideos(); raf = requestAnimationFrame(frame);
  return () => {
    alive = false; cancelAnimationFrame(raf); clearInterval(statusTimer); clearTimeout(toast.t); observer.disconnect();
    cleanups.forEach((f) => f());
    for (const v of sideVideos) { try { v.pause(); v.removeAttribute("src"); v.load(); } catch (e) { /* ignore */ } }
  };
}
