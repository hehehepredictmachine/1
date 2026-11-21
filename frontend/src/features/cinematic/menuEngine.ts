// Menu główne 1.42 – port skryptu wzorca REF_A_menu_glowne_v1_1.html do modułu TS (E1).
// Zachowane 1:1: fazy boot → enter → menu → selecting → selected → returning, liczby cząsteczek (110k/94k/66k), gwiazdy, pył, smugi,
// okluzja siatką, renderer CPU (setupSoftware / swPlanet / swDepthMesh), przeciąganie, hover, klawiatura, contextlost/restored,
// visibilitychange, dispose przez AbortController. Zmiany względem wzorca:
//  * 1.44.1: intro = film Apollo23_intro_land.mp4 (<video>, pełny ekran z zachowaniem proporcji, bez kontrolek, z dźwiękiem); koniec filmu,
//    klik, Spacja, Esc i „Przejdź do menu” → enter() (wejście z czerni do menu, bez zmian); film nieodtwarzalny → od razu menu, bez błędu.
//  * 1.42.7 (pakiet update_intro3d, zastąpione w 1.44.1): intro = scena 3D (LazyIntro → Intro3D, kontrakt <video> jak REF_C), nie film; po wejściu do menu
//    scena jest zwalniana (release), przy odmontowaniu – także jej kontekst WebGL (dispose); przycisk dźwięku ukryty (intro bez dźwięku);
//  * stan fazy trafia do data-state kontenera .app-cinematic (nie do <body>), elementy przychodzą z komponentu React;
//  * wybór FOREX kończy się wywołaniem onForexReady(pose) zamiast ekranu „prezentacji”; CRYPTO/OTC – ekran „tryb w przygotowaniu”;
//  * PMW_PREVIEW zastąpiony hakiem window.__PMW_E2E__.menu dostępnym tylko w trybie testów; brak zdarzenia pmw:mode-preview-selected.
import { meshFrag, particleFrag, starFrag, starVert, streakFrag, streakVert, vertexShared } from "./menuShaders";
import { markIntroSeen, saveMotionChoice, testMode } from "./introGate";

export type Mode = "FOREX" | "CRYPTO" | "OTC";
export type Pose = { x: number; y: number; r: number };

/** Obiekt intro z kontraktem <video> (play / pause / currentTime / duration / muted / readyState / style, zdarzenia ended / error). */
export type IntroLike = EventTarget & { play(): Promise<void>; pause(): void; currentTime: number; readonly duration: number; muted: boolean;
  readyState: number; readonly style: CSSStyleDeclaration; release?(): void; dispose?(): void };

export type MenuElements = {
  root: HTMLElement; canvas: HTMLCanvasElement; video: IntroLike; cinema: HTMLElement; menu: HTMLElement; selected: HTMLElement;
  selectedName: HTMLElement; selectedNote: HTMLElement; returnBtn: HTMLButtonElement; skip: HTMLButtonElement; videoStart: HTMLButtonElement;
  progress: HTMLElement; progressBar: HTMLElement; notice: HTMLElement; announcer: HTMLElement; rendererError: HTMLElement; rendererMessage: HTMLElement;
  rendererRetry: HTMLButtonElement; buttons: [HTMLButtonElement, HTMLButtonElement, HTMLButtonElement];
  replay: HTMLButtonElement; sound: HTMLButtonElement; motion: HTMLButtonElement; fullscreen: HTMLButtonElement;
};

export type MenuOptions = {
  playIntro: boolean;
  reduced: boolean;
  forceSoftware?: boolean;
  onChoose?(mode: Mode): void;
  onForexReady?(pose: Pose): void;
  onMotionChange?(reduced: boolean): void;
  onMenuReady?(): void;                                    // pierwsze wejście do fazy menu (np. Ustawienia przy pierwszym uruchomieniu – po intro)
  audio?: boolean;                                         // 1.44.1: dźwięk filmu intro (domyślnie włączony; wybór użytkownika zapamiętany)
  onSoundChange?(on: boolean): void;
};

/** 1.44.1: kodek filmu intro (H.264 High + AAC LC). Brak obsługi = od razu menu (bez komunikatu o błędzie). */
export const INTRO_CODECS = 'video/mp4; codecs="avc1.640028, mp4a.40.2"';

const SVG_SOUND_ON = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M9 4 5 8H2v4h3l4 4zM13 7a5 5 0 0 1 0 6m2-9a8 8 0 0 1 0 12"/></svg>';
const SVG_SOUND_OFF = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M9 4 5 8H2v4h3l4 4zM13 7l5 6m0-6-5 6"/></svg>';
const SVG_PLAY = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 4 10 6-10 6z"/></svg>';
const SVG_PAUSE = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 4v12m6-12v12"/></svg>';
export const PREPARING_NOTE = "Tryb w przygotowaniu – ten tryb pracy bota nie ma jeszcze ekranu.";

export function mountMenu(el: MenuElements, opts: MenuOptions): () => void {
  const { canvas, video, cinema, root } = el;
  const clamp = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
  const smooth = (x: number) => { x = clamp(x); return x * x * (3 - 2 * x); };
  const ease = (x: number) => { x = clamp(x); return 1 - Math.pow(1 - x, 4); };
  const config = Object.freeze({ counts: [110000, 94000, 66000], starCount: 1500, dustCount: 11000, pixelRatioCap: 1.65, entrySeconds: 3.0, selectSeconds: 1.85, returnSeconds: 1.35 });
  const state: any = { phase: "boot", phaseT: 0, time: 0, rotationTime: 0, hidden: false, reduced: opts.reduced, pointer: [0, 0], pointerTarget: [0, 0], selected: -1, hover: -1,
    focus: -1, drag: null, raf: 0, disposed: false, contextLost: false, frame: 0, last: 0, noticeTimer: 0, watchdog: 0, quality: "full", audio: opts.audio ?? true, slowSince: 0, frameAvg: 16 };
  const modes: Mode[] = ["FOREX", "CRYPTO", "OTC"];
  const orbs: any[] = modes.map((name, i) => ({ name, button: el.buttons[i], kind: i, angles: [0.11 + i * 0.24, -0.22 + i * 1.8], velocity: [0, 0], hover: 0, mouse: [0, 0],
    layout: { x: 0, y: 0, r: 0 }, buffer: null, count: config.counts[i] }));
  let gl: WebGLRenderingContext | null = null;
  let program: any, starProgram: any, meshProgram: any, streakProgram: any, particleLoc: any, starLoc: any, streakLoc: any, meshLoc: any;
  let starBuffer: any, dustBuffer: any, streakBuffer: any, meshBuffer: any, meshIndex: any, meshIndexCount = 0;
  let view = { w: innerWidth, h: innerHeight, dpr: 1 };
  let buffers: WebGLBuffer[] = [], programs: WebGLProgram[] = [], glShaders: WebGLShader[] = [];
  let software: any = null;

  function prng(seed: number) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function announce(text: string) { el.announcer.textContent = text; }
  function notice(text: string) { el.notice.textContent = text; el.notice.classList.add("show"); clearTimeout(state.noticeTimer); state.noticeTimer = setTimeout(() => el.notice.classList.remove("show"), 4000); }
  let menuReadyFired = false;
  function setPhase(phase: string) {
    if (phase === "menu" && !menuReadyFired) { menuReadyFired = true; setTimeout(() => { if (!state.disposed) opts.onMenuReady?.(); }, 0); }
    state.phase = phase; state.phaseT = 0; root.dataset.state = phase;
    (el.menu as any).inert = phase !== "menu"; (el.selected as any).inert = phase !== "selected";
    el.skip.hidden = phase !== "boot"; el.videoStart.hidden = true;
  }
  function matrix(rx: number, ry: number) { const sx = Math.sin(rx), cx = Math.cos(rx), sy = Math.sin(ry), cy = Math.cos(ry); return new Float32Array([cy, sy * sx, -sy * cx, 0, cx, sx, sy, -cy * sx, cy * cx]); }
  function compile(type: number, source: string) { const g = gl!; const s = g.createShader(type)!; glShaders.push(s); g.shaderSource(s, source); g.compileShader(s); if (!g.getShaderParameter(s, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(s) || "shader"); return s; }
  function link(v: string, f: string) { const g = gl!; const p = g.createProgram()!; programs.push(p); g.attachShader(p, compile(g.VERTEX_SHADER, v)); g.attachShader(p, compile(g.FRAGMENT_SHADER, f)); g.linkProgram(p); if (!g.getProgramParameter(p, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(p) || "program"); return p; }
  function locations(p: WebGLProgram, names: string[]) { const g = gl!; const l: any = { pos: g.getAttribLocation(p, "aPos"), info: g.getAttribLocation(p, "aInfo") }; for (const n of names) l[n] = g.getUniformLocation(p, "u" + n); return l; }
  function makeBuffer(data: ArrayBufferView, target?: number) { const g = gl!; target = target ?? g.ARRAY_BUFFER; const b = g.createBuffer()!; buffers.push(b); g.bindBuffer(target, b); g.bufferData(target, data as any, g.STATIC_DRAW); return b; }
  function sphereData(count: number, seed: number) { const out = new Float32Array(count * 6), r = prng(seed), golden = Math.PI * (3 - Math.sqrt(5)); for (let i = 0; i < count; i++) { const z = 1 - 2 * (i + 0.5) / count; const rad = Math.sqrt(1 - z * z), a = i * golden + (r() - 0.5) * 0.008, k = i * 6; out[k] = Math.cos(a) * rad; out[k + 1] = Math.sin(a) * rad; out[k + 2] = z; out[k + 3] = r(); out[k + 4] = r(); out[k + 5] = r(); } return out; }
  function starData(count: number, seed: number) { const out = new Float32Array(count * 6), r = prng(seed); for (let i = 0; i < count; i++) { const k = i * 6; out[k] = r() * 2 - 1; out[k + 1] = r() * 2 - 1; out[k + 2] = r(); out[k + 3] = r(); out[k + 4] = r(); out[k + 5] = r(); } return out; }
  function bind(b: WebGLBuffer, l: any) { const g = gl!; g.bindBuffer(g.ARRAY_BUFFER, b); if (l.pos >= 0) { g.enableVertexAttribArray(l.pos); g.vertexAttribPointer(l.pos, 3, g.FLOAT, false, 24, 0); } if (l.info >= 0) { g.enableVertexAttribArray(l.info); g.vertexAttribPointer(l.info, 3, g.FLOAT, false, 24, 12); } }
  function makeMesh() { const cols = 144, rows = 80, verts: number[] = [], inds: number[] = []; for (let y = 0; y <= rows; y++) { const p = y / rows * Math.PI; for (let x = 0; x <= cols; x++) { const a = x / cols * Math.PI * 2; verts.push(Math.sin(p) * Math.cos(a), Math.sin(p) * Math.sin(a), Math.cos(p), 0.5, 0.5, 0.5); } } for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) { const k = y * (cols + 1) + x; inds.push(k, k + 1, k + cols + 1, k + 1, k + cols + 2, k + cols + 1); } meshBuffer = makeBuffer(new Float32Array(verts)); meshIndex = makeBuffer(new Uint16Array(inds), gl!.ELEMENT_ARRAY_BUFFER); meshIndexCount = inds.length; }

  /* Renderer CPU (bez WebGL): te same 270 000 cząsteczek, równania deformacji, rzut 3D, obroty, siatka głębi i interakcje. */
  function setupSoftware() {
    const ctx = canvas.getContext("2d", { alpha: false }); if (!ctx) throw new Error("No graphics context");
    software = { ctx, image: null, px: null, words: null, depth: null, points: [], stars: starData(config.starCount, 12), dust: starData(config.dustCount, 78), mesh: [], indices: [] };
    orbs.forEach((o, i) => { const points = sphereData(o.count, 8419 + i * 7351), angles = new Float32Array(o.count * 2); for (let k = 0; k < o.count; k++) { angles[k * 2] = Math.atan2(points[k * 6 + 1], points[k * 6]); angles[k * 2 + 1] = Math.acos(clamp(points[k * 6 + 2], -1, 1)); } software.points.push({ points, angles }); });
    const cols = 144, rows = 80; for (let y = 0; y <= rows; y++) { const ph = y / rows * Math.PI; for (let x = 0; x <= cols; x++) { const a = x / cols * Math.PI * 2; software.mesh.push([Math.sin(ph) * Math.cos(a), Math.sin(ph) * Math.sin(a), Math.cos(ph), a, ph]); } } for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) { const k = y * (cols + 1) + x; software.indices.push(k, k + 1, k + cols + 1, k + 1, k + cols + 2, k + cols + 1); }
    resize();
  }
  const swPoint = new Float64Array(3), swG = { A: 1, Sat: 0, Aux: 0 };
  const fr = (x: number) => x - Math.floor(x), h1 = (x: number) => fr(Math.sin(x * 127.1) * 43758.5453), sstep = (a: number, b: number, x: number) => { x = clamp((x - a) / (b - a)); return x * x * (3 - 2 * x); };
  function rotXp(x: number, y: number, z: number, a: number, out: Float64Array) { const c = Math.cos(a), s = Math.sin(a); out[0] = x; out[1] = y * c - z * s; out[2] = y * s + z * c; return out; }
  function swPlanet(n0: number, n1: number, n2: number, i0: number, i1: number, i2: number, t: number, kind: number, out: Float64Array) {
    const lat = Math.asin(clamp(n1, -1, 1)), lon = Math.atan2(n2, n0); swG.A = 1; swG.Sat = 0; swG.Aux = 0; out[0] = n0; out[1] = n1; out[2] = n2;
    if (kind === 0) {
      if (i0 < 0.10) { swG.Aux = 1; const u = fr(i1 * 7.31), rr = 1.30 + 0.45 * u, gap = Math.abs(rr - 1.56) < 0.022 ? 0 : 1, ang = i2 * 6.2832 + t * 0.10 / Math.pow(rr, 1.5); rotXp(Math.cos(ang) * rr, (i1 - 0.5) * 0.012, Math.sin(ang) * rr, 0.30, out); swG.A = (0.5 + 0.6 * Math.pow(0.5 + 0.5 * Math.sin(rr * 46 + i1 * 3), 2)) * gap * 1.25; swG.Sat = 0.6; }
      else if (i0 < 0.124) { swG.Aux = 1; const id = Math.floor((i0 - 0.10) / 0.006), oa = id * 1.5708 + t * (0.17 + 0.035 * id), orr = 1.92 + 0.07 * id; rotXp(Math.cos(oa) * orr, 0, Math.sin(oa) * orr, 0.30 + 0.05 * id, out); const r = 0.085 + 0.012 * id; out[0] += n0 * r; out[1] += n1 * r; out[2] += n2 * r; swG.A = 0.95; swG.Sat = 0.15; }
      else { const l2 = lon + t * 0.05, b = Math.sin(lat * 18 + Math.sin(l2 * 2 + lat * 3) * 0.7), eq = Math.exp(-lat * lat * 28), k = 1 + 0.006 * b; out[0] = n0 * k; out[1] = n1 * k; out[2] = n2 * k; swG.A = 0.16 + 0.95 * Math.pow(b * b, 1.6) + 0.7 * eq * (0.6 + 0.4 * Math.sin(l2 * 6 - t * 0.4)) + 0.3 * Math.pow(Math.sin(lat * 37 + l2), 8); }
    } else if (kind === 1) {
      if (i0 < 0.11) { swG.Aux = 1; const k = Math.floor(i2 * 20); let x: number, z: number, y = 0;
        if (fr(i1 * 5) < 0.28) { const ang = (k + fr(i1 * 71)) / 20 * 6.2832 + t * 0.10; x = Math.cos(ang) * 1.62; z = Math.sin(ang) * 1.62; swG.A = 0.32; }
        else { const ang = (k + 0.5) / 20 * 6.2832 + t * 0.10; x = Math.cos(ang) * 1.62 + (fr(i1 * 13) - 0.5) * 0.12; y = (fr(i1 * 29) - 0.5) * 0.12; z = Math.sin(ang) * 1.62 + (fr(i1 * 47) - 0.5) * 0.12; const lit = h1(k + Math.floor(t * 0.5) * 7) >= 0.75 ? 1 : 0; swG.A = 0.7 + 0.9 * lit; swG.Sat = 0.5 * (1 - lit); }
        rotXp(x, y, z, 0.28, out); }
      else { const st = 0.2618, bd = Math.floor((lat + 1.5708) / st), dir = (bd % 2) < 0.5 ? 1 : -1, l2 = lon + t * 0.11 * dir, cu = l2 / st, cv = (lat + 1.5708) / st, fu = fr(cu), fv = fr(cv), e = Math.min(Math.min(fu, 1 - fu) * Math.cos(lat), Math.min(fv, 1 - fv)), ln = 1 - sstep(0, 0.07, e);
        const id = Math.floor(((cu % 24) + 24) % 24) + bd * 37, lit = h1(id + Math.floor(t * 0.6 + h1(id) * 5) * 13) >= 0.88 ? 1 : 0, k = 1 + 0.028 * lit * (1 - ln); out[0] = n0 * k; out[1] = n1 * k; out[2] = n2 * k; swG.A = 0.10 + 0.95 * ln + 0.75 * lit * (1 - ln); swG.Sat = 0.45 * lit; }
    } else {
      if (i0 < 0.40) { out[0] = n0 * 0.56; out[1] = n1 * 0.56; out[2] = n2 * 0.56; swG.A = 0.30 + 0.75 * Math.pow(0.5 + 0.5 * Math.sin(lat * 9 - t * 0.8 + Math.sin(lon * 3) * 1.2), 4); swG.Sat = 0.1; }
      else { const sec = 6.2832 / 9, lm = lon + t * 0.05, dm = Math.abs(fr(lm / sec + 0.5) - 0.5) * sec * Math.cos(lat), seam = 1 - sstep(0, 0.03, dm), sid = Math.floor(lm / sec + 0.5), pulse = Math.pow(0.5 + 0.5 * Math.sin(lat * 2.5 - t * 1.5 + sid * 1.9), 14), eq = 1 - sstep(0, 0.02, Math.abs(lat)), k = 1 + 0.015 * Math.sin(t * 0.5);
        out[0] = n0 * k; out[1] = n1 * k; out[2] = n2 * k; swG.A = 0.035 + seam * (0.45 + 1.1 * pulse) + eq * 0.55; swG.Sat = 0.55 * seam * (1 - pulse); }
    }
    return out;
  }
  function swProject(p: Float64Array, o: any, m: Float32Array, burst: number, seed: number, mesh = false, noRot = false) {
    let x = p[0], y = p[1], z = p[2]; if (mesh) { x *= 0.985; y *= 0.985; z *= 0.985; }
    let px = noRot ? x : m[0] * x + m[6] * z, py = noRot ? y : m[1] * x + m[4] * y + m[7] * z, pz = noRot ? z : m[2] * x + m[5] * y + m[8] * z;
    const dx = px - o.mouse[0], dy = py - o.mouse[1], dist = Math.sqrt(dx * dx + dy * dy), ripple = Math.exp(-dist * dist * 2.8) * o.hover;
    px += dx * 0.045 * ripple; py += dy * 0.045 * ripple; pz += 0.13 * ripple * Math.sin(dist * 8 - (state.rotationTime + o.kind * 8.2) * 1.7);
    const s = 1 + o.hover * 0.035; px *= s; py *= s; pz *= s;
    if (burst) { const norm = Math.sqrt(px * px + py * py + pz * pz) || 1, b = (Math.sin(seed * 6.283 + state.rotationTime + o.kind * 8.2) * 0.04 + 1) * burst; px += px / norm * b; py += py / norm * b; pz += pz / norm * b; }
    p[0] = px; p[1] = py; p[2] = pz; return p;
  }
  function swDot(x: number, y: number, size: number, alpha: number, red: number, green: number, blue: number, z: number, depthTest: boolean) {
    const { px, depth } = software, w = canvas.width, h = canvas.height, half = Math.max(0.68, size * 0.5), x0 = Math.max(0, Math.floor(x - half)), x1 = Math.min(w - 1, Math.ceil(x + half)), y0 = Math.max(0, Math.floor(y - half)), y1 = Math.min(h - 1, Math.ceil(y + half));
    for (let yy = y0; yy <= y1; yy++) { const dy = (yy + 0.5 - y) / half; for (let xx = x0; xx <= x1; xx++) { const d = (xx + 0.5 - x) / half, r = d * d + dy * dy; if (r > 1) continue; const p = yy * w + xx; if (depthTest && z > depth[p] + 0.001) continue; const a = Math.exp(-r * 2.8) * alpha * 255, k = p * 4; px[k] += red * a; px[k + 1] += green * a; px[k + 2] += blue * a; } }
  }
  function swDepthMesh(o: any, pose: Pose, m: Float32Array, burst: number) {
    const { mesh, indices, depth } = software; depth.fill(100); const v = new Float64Array(mesh.length * 3), dpr = view.dpr, w = canvas.width, h = canvas.height;
    for (let i = 0; i < mesh.length; i++) { const n = mesh[i], q = o.kind === 2 ? 0.5635 : 1; swPoint[0] = n[0] * q; swPoint[1] = n[1] * q; swPoint[2] = n[2] * q; const p = swProject(swPoint, o, m, burst, 0.5, true), pr = 3.7 / (3.7 - p[2] * 0.55), k = i * 3; v[k] = (pose.x + p[0] * pose.r * pr) * dpr; v[k + 1] = (pose.y - p[1] * pose.r * pr) * dpr; v[k + 2] = -p[2] * 0.25; }
    for (let j = 0; j < indices.length; j += 3) { const ia = indices[j] * 3, ib = indices[j + 1] * 3, ic = indices[j + 2] * 3; const ax = v[ia], ay = v[ia + 1], az = v[ia + 2], bx = v[ib], by = v[ib + 1], bz = v[ib + 2], cx = v[ic], cy = v[ic + 1], cz = v[ic + 2], den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy); if (Math.abs(den) < 0.0001) continue; const minX = Math.max(0, Math.floor(Math.min(ax, bx, cx))), maxX = Math.min(w - 1, Math.ceil(Math.max(ax, bx, cx))), minY = Math.max(0, Math.floor(Math.min(ay, by, cy))), maxY = Math.min(h - 1, Math.ceil(Math.max(ay, by, cy))); for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) { const a = ((by - cy) * (x + 0.5 - cx) + (cx - bx) * (y + 0.5 - cy)) / den, b = ((cy - ay) * (x + 0.5 - cx) + (ax - cx) * (y + 0.5 - cy)) / den, c = 1 - a - b; if (a >= 0 && b >= 0 && c >= 0) { const z = a * az + b * bz + c * cz, k = y * w + x; if (z < depth[k]) depth[k] = z; } } }
  }
  function swDrawOrb(o: any, pose: Pose, opacity: number, burst: number) {
    if (opacity < 0.001) return; const data = software.points[o.kind], a = data.points, m = matrix(o.angles[0], o.angles[1]), t = state.rotationTime + o.kind * 8.2, dpr = view.dpr;
    swDepthMesh(o, pose, m, burst);
    for (let i = 0; i < o.count; i++) { const k = i * 6, n0 = a[k], n1 = a[k + 1], n2 = a[k + 2]; swPlanet(n0, n1, n2, a[k + 3], a[k + 4], a[k + 5], t, o.kind, swPoint); const aux = swG.Aux > 0.5, p = swProject(swPoint, o, m, burst, a[k + 5], false, aux); const px = p[0], py = p[1], pz = p[2], norm = Math.sqrt(px * px + py * py + pz * pz) || 1, rim = Math.pow(1 - Math.abs(pz / norm), 1.65), light = clamp(((-0.65 * px + 0.8 * py + 1.1 * pz) / (norm * 1.507481)) * 0.5 + 0.5);
      let alpha = aux ? swG.A * (0.50 + 0.55 * light) : (0.12 + rim * 0.70 + light * 0.34) * swG.A * (o.kind === 2 ? 1.35 : 1); alpha *= opacity * (1 + o.hover * 0.45);
      const col = light * 0.8 + rim * 0.2, sat = swG.Sat, pr = 3.7 / (3.7 - pz * 0.55), sx = (pose.x + px * pose.r * pr) * dpr, sy = (pose.y - py * pose.r * pr) * dpr; let size = (0.6 + 0.52 * fr(a[k + 4] * 3.7)) * (aux ? 1.1 : 1) * dpr * pr * (1 + o.hover * 0.08); size = clamp(size, 0.65, 4);
      swDot(sx, sy, size, alpha, lerp(lerp(0.77, 0.98, col), 0.70, sat), lerp(lerp(0.80, 0.985, col), 0.66, sat), lerp(lerp(0.87, 1, col), 1, sat), -pz * 0.25, true);
    }
  }
  function swDrawStars(opacity: number, warp: number) {
    const draw = (a: Float32Array, dust: boolean) => { for (let k = 0; k < a.length; k += 6) { const z = a[k + 2], t = state.rotationTime; let x = ((a[k] + t * 0.00035 * (z + 0.15) + 1) % 2) - 1, y = ((a[k + 1] + t * 0.00010 * (z + 0.1) + 1) % 2) - 1; x += state.pointer[0] * (z * 0.012 + 0.002); y += state.pointer[1] * (z * 0.012 + 0.002); x *= 1 + warp * (0.1 + z * 0.8); y *= 1 + warp * (0.1 + z * 0.8); let size = (a[k + 3] * 0.9 + 0.45) * view.dpr * (0.7 + z * 0.45) * (1 + warp * 0.6), alpha = (0.085 + Math.pow(a[k + 3], 6) * 0.65) * (0.65 + 0.35 * Math.sin(t * (a[k + 4] * 0.4 + 0.2) + a[k + 5] * 25)) * opacity; if (dust) { alpha *= Math.exp(-Math.pow((y + x * 0.17 + 0.38) * 3.9, 2)) * 0.11; size *= 0.65; } const col = a[k + 4], sx = (x * 0.5 + 0.5) * canvas.width, sy = (-y * 0.5 + 0.5) * canvas.height; swDot(sx, sy, size, alpha, lerp(0.53, 0.95, col), lerp(0.62, 0.95, col), lerp(0.83, 0.93, col), 0, false);
      if (warp > 0.01 && !dust) { const tx = (sx - canvas.width * 0.5) * warp * 0.45, ty = (sy - canvas.height * 0.5) * warp * 0.45, steps = Math.min(50, Math.ceil(Math.hypot(tx, ty) / 2)); for (let j = 1; j < steps; j++) { const q = j / steps; swDot(sx + tx * q, sy + ty * q, view.dpr, warp * 0.10 * (1 - q), 0.65, 0.76, 1, 0, false); } } } };
    draw(software.stars, false); draw(software.dust, true);
  }
  function setup() {
    gl = opts.forceSoftware ? null : (canvas.getContext("webgl", { alpha: false, antialias: false, depth: true, premultipliedAlpha: false, powerPreference: "high-performance", preserveDrawingBuffer: false }) as WebGLRenderingContext | null);
    if (!gl) { setupSoftware(); return; }
    program = link(vertexShared, particleFrag); meshProgram = link(vertexShared, meshFrag); starProgram = link(starVert, starFrag); streakProgram = link(streakVert, streakFrag);
    const uniformNames = ["Time", "Kind", "Hover", "Dpr", "Opacity", "Radius", "Burst", "Mesh", "Resolution", "Center", "Mouse", "Rotation"];
    particleLoc = locations(program, uniformNames); meshLoc = locations(meshProgram, uniformNames); starLoc = locations(starProgram, ["Resolution", "Pointer", "Time", "Dpr", "Opacity", "Warp", "Dust"]); streakLoc = locations(streakProgram, ["Warp", "Opacity"]);
    orbs.forEach((o, i) => o.buffer = makeBuffer(sphereData(o.count, 8419 + i * 7351)));
    starBuffer = makeBuffer(starData(config.starCount, 12)); dustBuffer = makeBuffer(starData(config.dustCount, 78));
    const r = prng(765), st: number[] = []; for (let i = 0; i < 500; i++) { const x = r() * 2 - 1, y = r() * 2 - 1, z = r(); for (let j = 0; j < 2; j++) st.push(x, y, z, j, 0, 0); } streakBuffer = makeBuffer(new Float32Array(st));
    makeMesh(); gl.clearColor(0, 0, 0, 1); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); resize();
  }
  function resize() {
    const cap = state.quality === "low" ? 1 : config.pixelRatioCap;
    view = { w: innerWidth, h: innerHeight, dpr: Math.min(devicePixelRatio || 1, cap) };
    canvas.width = Math.round(view.w * view.dpr); canvas.height = Math.round(view.h * view.dpr); if (gl) gl.viewport(0, 0, canvas.width, canvas.height);
    if (software) { software.image = software.ctx.createImageData(canvas.width, canvas.height); software.px = software.image.data; software.words = new Uint32Array(software.px.buffer); software.depth = new Float32Array(canvas.width * canvas.height); }
    const { w, h } = view, narrow = w < 700, short = h < 620 && w >= 700;
    const baseR = narrow ? Math.min(w * 0.202, h * 0.142) : Math.min(h * (short ? 0.142 : 0.166), w * 0.118);
    const layouts = narrow ? [{ x: 0.5 * w, y: 0.346 * h, r: baseR * 1.08 }, { x: 0.754 * w, y: 0.655 * h, r: baseR * 0.86 }, { x: 0.246 * w, y: 0.655 * h, r: baseR * 0.86 }] : [{ x: 0.5 * w, y: 0.369 * h, r: baseR * 1.04 }, { x: 0.767 * w, y: 0.654 * h, r: baseR }, { x: 0.233 * w, y: 0.654 * h, r: baseR }];
    orbs.forEach((o, i) => { o.layout = layouts[i]; const b = o.button; b.style.setProperty("--x", o.layout.x + "px"); b.style.setProperty("--y", o.layout.y + "px"); b.style.setProperty("--hit", o.layout.r * 2.38 + "px"); });
  }
  function commonUniforms(l: any, o: any, pose: Pose, opacity: number, burst = 0, mesh = 0) { const g = gl!; g.uniform1f(l.Time, state.rotationTime + o.kind * 8.2); g.uniform1f(l.Kind, o.kind); g.uniform1f(l.Hover, o.hover); g.uniform1f(l.Dpr, view.dpr); g.uniform1f(l.Opacity, opacity); g.uniform1f(l.Radius, pose.r); g.uniform1f(l.Burst, burst); g.uniform1f(l.Mesh, mesh); g.uniform2f(l.Resolution, view.w, view.h); g.uniform2f(l.Center, pose.x, pose.y); g.uniform2fv(l.Mouse, o.mouse); g.uniformMatrix3fv(l.Rotation, false, matrix(o.angles[0], o.angles[1])); }
  function drawOrb(o: any, pose: Pose, opacity = 1, burst = 0) {
    if (software) { swDrawOrb(o, pose, opacity, burst); return; } if (opacity < 0.001) return; const g = gl!;
    g.clear(g.DEPTH_BUFFER_BIT); g.useProgram(meshProgram); bind(meshBuffer, meshLoc); g.bindBuffer(g.ELEMENT_ARRAY_BUFFER, meshIndex); commonUniforms(meshLoc, o, pose, opacity, burst, 1); g.enable(g.DEPTH_TEST); g.depthMask(true); g.depthFunc(g.LEQUAL); g.drawElements(g.TRIANGLES, meshIndexCount, g.UNSIGNED_SHORT, 0);
    g.useProgram(program); bind(o.buffer, particleLoc); commonUniforms(particleLoc, o, pose, opacity, burst, 0); g.depthMask(false); g.blendFunc(g.ONE, g.ONE); g.drawArrays(g.POINTS, 0, o.count); g.depthMask(true); g.disable(g.DEPTH_TEST); g.blendFunc(g.ONE, g.ONE_MINUS_SRC_ALPHA);
  }
  function drawStars(opacity: number, warp: number) {
    if (software) { swDrawStars(opacity, warp); return; } const g = gl!;
    g.disable(g.DEPTH_TEST); g.blendFunc(g.ONE, g.ONE); g.useProgram(starProgram); g.uniform2f(starLoc.Resolution, view.w, view.h); g.uniform2fv(starLoc.Pointer, state.pointer); g.uniform1f(starLoc.Time, state.rotationTime); g.uniform1f(starLoc.Dpr, view.dpr); g.uniform1f(starLoc.Opacity, opacity); g.uniform1f(starLoc.Warp, warp); g.uniform1f(starLoc.Dust, 0); bind(starBuffer, starLoc); g.drawArrays(g.POINTS, 0, config.starCount); g.uniform1f(starLoc.Dust, 1); bind(dustBuffer, starLoc); g.drawArrays(g.POINTS, 0, config.dustCount);
    if (warp > 0.005) { g.useProgram(streakProgram); g.uniform1f(streakLoc.Warp, warp); g.uniform1f(streakLoc.Opacity, opacity); bind(streakBuffer, streakLoc); g.drawArrays(g.LINES, 0, 1000); }
    g.blendFunc(g.ONE, g.ONE_MINUS_SRC_ALPHA);
  }
  function orbitalPose(o: any): Pose { return { x: o.layout.x + state.pointer[0] * (o.kind === 0 ? 5 : 8), y: o.layout.y + state.pointer[1] * (o.kind === 0 ? 3 : 5) + (state.reduced ? 0 : Math.sin(state.rotationTime * 0.26 + o.kind * 2) * 2.4), r: o.layout.r }; }
  function selectPose(): Pose { return { x: view.w * 0.5, y: view.h * 0.43, r: Math.min(view.h * 0.23, view.w * 0.29) }; }
  function mixPose(a: Pose, b: Pose, t: number): Pose { return { x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), r: lerp(a.r, b.r, t) }; }
  function quality(dt: number) {           // S1 §3.7: średnia klatka > 28 ms przez 3 s -> DPR 1
    state.frameAvg = lerp(state.frameAvg, dt * 1000, 0.08);
    if (state.quality === "full" && state.frameAvg > 28) { state.slowSince += dt; if (state.slowSince > 3) { state.quality = "low"; resize(); } } else state.slowSince = 0;
  }
  function tick(now: number) {
    state.raf = 0; if (state.disposed || state.hidden || state.contextLost) return;
    const dt = Math.min((now - (state.last || now)) / 1000, 0.25); state.last = now; state.time += dt; state.phaseT += dt; state.frame++;
    if (dt > 0) quality(dt);
    if (!state.reduced) state.rotationTime += dt;
    state.pointer = state.pointer.map((p: number, i: number) => lerp(p, state.reduced ? 0 : state.pointerTarget[i], 1 - Math.exp(-dt * 4)));
    orbs.forEach((o, i) => { const active = state.hover === i || state.focus === i || state.drag?.index === i; o.hover = state.reduced ? 0 : lerp(o.hover, active && state.phase === "menu" ? 1 : 0, 1 - Math.exp(-dt * 4)); if (!state.drag || state.drag.index !== i) { if (!state.reduced) { o.angles[0] += o.velocity[0] * dt; o.angles[1] += o.velocity[1] * dt + dt * (0.065 + i * 0.008); } const decay = Math.exp(-dt * 2.2); o.velocity = state.reduced ? [0, 0] : o.velocity.map((v: number) => v * decay); } o.angles[0] = clamp(o.angles[0], -1.8, 1.8); });
    if (software) software.words.fill(0xff000000); else gl!.clear(gl!.COLOR_BUFFER_BIT | gl!.DEPTH_BUFFER_BIT);
    const { phase } = state; const p = state.phaseT;
    if (phase === "boot") {
      el.progressBar.style.transform = "scaleX(" + ((video.duration ? video.currentTime / video.duration : 0)) + ")";
    } else if (phase === "enter") {
      const dur = state.reduced ? 0.3 : config.entrySeconds, k = clamp(p / dur), move = ease(clamp((k - 0.10) / 0.88)), fade = smooth(k / 0.56);
      cinema.style.opacity = String(1 - fade); video.style.transform = "scale(" + (1 + ease(k) * 1.25) + ")"; video.style.filter = "blur(" + (k * 9) + "px)";
      drawStars(smooth((k - 0.08) / 0.7), state.reduced ? 0 : Math.sin(k * Math.PI) * 0.72);
      const start = { x: view.w / 2, y: view.h / 2, r: Math.min(view.w * 0.34, view.h * 0.39) };
      orbs.forEach((o, i) => { const op = i === 0 ? smooth(k / 0.52) : smooth((k - 0.26) / 0.65); const startPos = i === 0 ? start : { x: view.w / 2 + (i === 1 ? 1 : -1) * view.w * 0.07, y: view.h * 0.54, r: o.layout.r * 0.28 }; drawOrb(o, mixPose(startPos, orbitalPose(o), move), op * (i === 0 ? 1 : 0.95), state.reduced ? 0 : (1 - move) * 0.12); });
      root.style.setProperty("--reveal", String(smooth((k - 0.6) / 0.4)));
      if (k >= 1) finishEnter();
    } else if (phase === "menu") {
      drawStars(1, 0); orbs.forEach((o) => drawOrb(o, orbitalPose(o)));
    } else if (phase === "selecting" || phase === "returning") {
      const duration = state.reduced ? 0.26 : (phase === "selecting" ? config.selectSeconds : config.returnSeconds), k = clamp(p / duration), progress = phase === "selecting" ? ease(k) : 1 - ease(k);
      drawStars(1 - progress * 0.3, state.reduced ? 0 : Math.sin(k * Math.PI) * 0.25);
      orbs.forEach((o, i) => { if (i !== state.selected) drawOrb(o, orbitalPose(o), 1 - smooth(progress / 0.7), progress * 0.13); });
      const o = orbs[state.selected]; drawOrb(o, mixPose(orbitalPose(o), selectPose(), progress), 1, 0);
      if (k >= 1) {
        if (phase === "selecting") {
          if (o.name === "FOREX" && opts.onForexReady) { setPhase("selected"); root.dataset.forex = "1"; opts.onForexReady(selectPose()); }
          else { setPhase("selected"); el.returnBtn.focus({ preventScroll: true }); announce("Wybrano tryb " + o.name + ". " + PREPARING_NOTE); }
        } else { setPhase("menu"); orbs[state.selected].button.focus({ preventScroll: true }); }
      }
    } else if (phase === "selected") {
      drawStars(0.7, 0); drawOrb(orbs[state.selected], selectPose());
    }
    if (software) software.ctx.putImageData(software.image, 0, 0);
    if (!state.reduced || !["menu", "selected"].includes(state.phase)) state.raf = requestAnimationFrame(tick);
  }
  function finishEnter() { cinema.hidden = true; cinema.style.opacity = "0"; video.pause(); video.release?.(); el.progress.hidden = true; setPhase("menu"); announce("Wybierz tryb pracy bota: FOREX, CRYPTO lub OTC."); }
  function enter() { if (state.phase !== "boot") return; video.pause(); clearTimeout(state.watchdog); setPhase("enter"); el.progress.hidden = true; wake(); }
  function skipToMenu() { clearTimeout(state.watchdog); video.pause(); video.release?.(); cinema.hidden = true; el.progress.hidden = true; root.style.setProperty("--reveal", "1"); setPhase("menu"); announce("Wybierz tryb pracy bota: FOREX, CRYPTO lub OTC."); wake(); }
  // 1.44.1: intro = film (Apollo23_intro_land.mp4). Film, którego nie da się odtworzyć (brak pliku, brak kodeka), nie pokazuje błędu –
  // od razu zaczyna się wejście do menu (ta sama ścieżka enter() co po końcu filmu).
  function introUnplayable(why: string) { if (state.phase !== "boot") return; console.warn("[intro] " + why + " – od razu menu"); enter(); }
  function soundUI(on: boolean) {
    el.sound.setAttribute("aria-pressed", String(on)); el.sound.setAttribute("aria-label", on ? "Wycisz intro" : "Włącz dźwięk intro");
    el.sound.dataset.label = on ? "Wycisz intro" : "Włącz dźwięk intro"; el.sound.innerHTML = on ? SVG_SOUND_ON : SVG_SOUND_OFF;
  }
  function startVideo(allowMutedRetry: boolean) {
    const pl = video.play();
    if (!pl || !pl.catch) return;
    pl.catch((err: any) => {
      if (state.phase !== "boot" || err?.name === "AbortError") return;           // przerwane pominięciem / pauzą
      if (err?.name === "NotAllowedError") {
        if (!video.muted && allowMutedRetry) {                                    // przeglądarka blokuje autoodtwarzanie z dźwiękiem
          video.muted = true; soundUI(false); notice("Przeglądarka wstrzymała dźwięk intro – kliknij głośnik, aby go włączyć."); startVideo(false); return;
        }
        el.videoStart.hidden = false; announce("Naciśnij Uruchom intro, aby rozpocząć."); return;
      }
      introUnplayable("odtwarzanie niemożliwe: " + (err?.name || err));
    });
  }
  function playIntro() {
    if (state.contextLost) return; clearTimeout(state.watchdog); state.hover = -1; state.focus = -1; state.drag = null; setPhase("boot"); markIntroSeen();
    cinema.hidden = false; cinema.style.opacity = "1"; video.style.transform = "scale(1)"; video.style.filter = "none"; el.progress.hidden = false;
    video.currentTime = 0; video.muted = !state.audio; soundUI(state.audio);
    if (state.reduced) { enter(); return; }
    const can = (video as any).canPlayType;
    if (typeof can === "function" && can.call(video, INTRO_CODECS) === "") { introUnplayable("brak kodeka H.264/AAC"); return; }
    startVideo(true);
    state.watchdog = setTimeout(() => { if (state.phase === "boot" && video.readyState < 3) introUnplayable("film nie wczytał się w 8 s"); }, 8000);
    wake();
  }
  function choose(i: number) {
    if (state.phase !== "menu" || state.drag) return; state.selected = i; orbs.forEach((o, j) => o.button.setAttribute("aria-pressed", String(j === i)));
    el.selectedName.textContent = orbs[i].name; el.selectedNote.textContent = PREPARING_NOTE; delete root.dataset.forex; setPhase("selecting"); opts.onChoose?.(orbs[i].name);
  }
  function goBack() { if (state.phase === "selected" || state.phase === "selecting") { delete root.dataset.forex; setPhase("returning"); wake(); } }
  function pointerXY(e: PointerEvent, o: any) { return [(e.clientX - o.layout.x) / o.layout.r, -(e.clientY - o.layout.y) / o.layout.r]; }
  function wake() { if (!state.raf && !state.hidden && !state.disposed && !state.contextLost) { state.last = performance.now(); state.raf = requestAnimationFrame(tick); } }
  const controller = new AbortController();
  const listen = (target: EventTarget, type: string, fn: (e: any) => void, o: AddEventListenerOptions = {}) => target.addEventListener(type, (event) => { fn(event); if (type !== "pointermove" || state.drag) wake(); }, { ...o, signal: controller.signal });
  orbs.forEach((o, i) => {
    let suppressClick = false;
    listen(o.button, "pointerenter", () => { state.hover = i; }); listen(o.button, "pointerleave", () => { if (state.hover === i) state.hover = -1; });
    listen(o.button, "focus", () => { state.focus = i; }); listen(o.button, "blur", () => { if (state.focus === i) state.focus = -1; });
    listen(o.button, "pointerdown", (e: PointerEvent) => { if (state.phase !== "menu" || (e.pointerType === "mouse" && e.button !== 0)) return; suppressClick = false; state.drag = { index: i, id: e.pointerId, startX: e.clientX, startY: e.clientY, x: e.clientX, y: e.clientY, last: performance.now(), moved: false }; o.velocity = [0, 0]; o.button.setPointerCapture(e.pointerId); });
    listen(o.button, "pointermove", (e: PointerEvent) => { o.mouse = pointerXY(e, o); const d = state.drag; if (!d || d.index !== i || d.id !== e.pointerId) return; const dx = e.clientX - d.x, dy = e.clientY - d.y, dts = Math.max((performance.now() - d.last) / 1000, 0.008); if (Math.hypot(e.clientX - d.startX, e.clientY - d.startY) > 6) d.moved = true; if (d.moved) { o.angles[0] += dy * 0.006; o.angles[1] += dx * 0.006; o.velocity = [clamp(dy * 0.006 / dts, -2, 2), clamp(dx * 0.006 / dts, -3, 3)]; } d.x = e.clientX; d.y = e.clientY; d.last = performance.now(); });
    const end = (e: PointerEvent) => { const d = state.drag; if (!d || d.index !== i || d.id !== e.pointerId) return; suppressClick = d.moved || e.type === "pointercancel"; state.drag = null; if (o.button.hasPointerCapture(e.pointerId)) o.button.releasePointerCapture(e.pointerId); };
    listen(o.button, "pointerup", end); listen(o.button, "pointercancel", end); listen(o.button, "lostpointercapture", (e: PointerEvent) => { if (state.drag?.id === e.pointerId) { suppressClick = true; state.drag = null; } });
    listen(o.button, "click", () => { if (suppressClick) { suppressClick = false; return; } choose(i); });
    listen(o.button, "keydown", (e: KeyboardEvent) => { if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); const direction = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1; orbs[(i + direction + 3) % 3].button.focus(); } });
  });
  listen(window, "pointermove", (e: PointerEvent) => { state.pointerTarget = [e.clientX / view.w * 2 - 1, e.clientY / view.h * 2 - 1]; });
  listen(window, "blur", () => { state.pointerTarget = [0, 0]; state.hover = -1; state.drag = null; });
  listen(window, "resize", resize); listen(video, "ended", enter); listen(video, "error", () => introUnplayable("błąd wczytania filmu"));
  listen(cinema, "click", () => { if (state.phase === "boot") enter(); });       // 1.44.1: klik w film pomija intro
  listen(el.skip, "click", enter); listen(el.videoStart, "click", () => { video.play().then(() => { el.videoStart.hidden = true; }).catch(() => notice("Odtwarzanie jest zablokowane. Możesz przejść do menu.")); });
  listen(el.replay, "click", () => { if (["enter", "selecting", "returning"].includes(state.phase)) return; playIntro(); }); listen(el.returnBtn, "click", goBack);
  listen(el.sound, "click", () => { state.audio = video.muted; video.muted = !state.audio; soundUI(state.audio); opts.onSoundChange?.(state.audio); });
  function updateMotionUI() { root.dataset.motion = state.reduced ? "reduced" : "full"; el.motion.setAttribute("aria-pressed", String(state.reduced)); el.motion.setAttribute("aria-label", state.reduced ? "Włącz pełny ruch" : "Ogranicz ruch"); el.motion.dataset.label = state.reduced ? "Włącz pełny ruch" : "Ogranicz ruch"; el.motion.innerHTML = state.reduced ? SVG_PLAY : SVG_PAUSE; }
  listen(el.motion, "click", () => { state.reduced = !state.reduced; saveMotionChoice(state.reduced); opts.onMotionChange?.(state.reduced); orbs.forEach((o) => o.velocity = [0, 0]); updateMotionUI(); if (state.reduced && state.phase === "boot") enter(); notice(state.reduced ? "Ruch ograniczony. Obracanie i wybór kul pozostają dostępne." : "Pełne animacje włączone."); });
  listen(el.fullscreen, "click", async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen(); else notice("Pełny ekran uruchomisz klawiszem F11 w przeglądarce."); } catch { notice("Przeglądarka zablokowała pełny ekran. Użyj F11."); } });
  listen(document, "fullscreenchange", () => { el.fullscreen.setAttribute("aria-label", document.fullscreenElement ? "Opuść pełny ekran" : "Pełny ekran"); });
  listen(document, "keydown", (e: KeyboardEvent) => {
    if (e.key === "Escape") { if (state.phase === "boot") enter(); else if (state.phase === "selected") goBack(); }
    if ((e.code === "Space" || e.key === " ") && state.phase === "boot") { e.preventDefault(); enter(); }     // 1.44.1: Spacja pomija intro
    const replayKey = (e.code === "KeyR" && !e.ctrlKey && !e.metaKey && !e.altKey) || (e.code === "KeyB" && e.ctrlKey && e.altKey);
    if (replayKey && ["menu", "selected"].includes(state.phase)) { const t = e.target as HTMLElement | null; if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return; e.preventDefault(); playIntro(); }
  });
  listen(document, "visibilitychange", () => { state.hidden = document.hidden; if (state.hidden) { cancelAnimationFrame(state.raf); state.raf = 0; if (state.phase === "boot") video.pause(); } else { state.last = 0; if (state.phase === "boot" && !state.reduced) video.play().catch(() => { el.videoStart.hidden = false; }); if (!state.raf && !state.contextLost) state.raf = requestAnimationFrame(tick); } });
  function rendererError(message?: string) { el.rendererError.hidden = false; if (message) el.rendererMessage.textContent = message; video.pause(); el.skip.hidden = true; }
  listen(canvas, "webglcontextlost", (e: Event) => { e.preventDefault(); state.contextLost = true; cancelAnimationFrame(state.raf); state.raf = 0; rendererError("Utracono kontekst renderowania 3D. Kliknij „Spróbuj ponownie”, aby odtworzyć scenę."); });
  listen(canvas, "webglcontextrestored", () => { try { buffers = []; programs = []; glShaders = []; setup(); state.contextLost = false; el.rendererError.hidden = true; cinema.hidden = true; setPhase("menu"); state.last = 0; state.raf = requestAnimationFrame(tick); } catch (err) { console.error(err); rendererError(); } });
  listen(el.rendererRetry, "click", () => location.reload());

  function dispose() {
    state.disposed = true; cancelAnimationFrame(state.raf); clearTimeout(state.watchdog); clearTimeout(state.noticeTimer); video.pause(); video.dispose?.(); controller.abort();
    if (gl && !state.contextLost) {
      for (const b of buffers) gl.deleteBuffer(b); for (const p of programs) gl.deleteProgram(p); for (const s of glShaders) gl.deleteShader(s);
      gl.getExtension("WEBGL_lose_context")?.loseContext();      // kontekst zwolniony od razu (nasłuchy już odpięte) – bez kumulacji przy wejściach/wyjściach
    }
    buffers = []; programs = []; glShaders = []; gl = null; software = null;
    if (hook) delete (window as any).__PMW_E2E__?.menu;
  }
  // hak testowy – tylko w trybie testów; bez danych rynkowych, bez wpływu na produkcję
  const hook = testMode();
  if (hook) {
    const w = window as any; w.__PMW_E2E__ = w.__PMW_E2E__ || {};
    w.__PMW_E2E__.menu = Object.freeze({ getState: () => ({ phase: state.phase, selected: state.selected < 0 ? null : modes[state.selected], reducedMotion: state.reduced,
      particleCounts: config.counts, frame: state.frame, frameAvgMs: state.frameAvg, viewport: { ...view }, renderer: software ? "CPU full geometry" : "WebGL", webgl: !!gl, quality: state.quality }),
      choose: (m: Mode) => choose(modes.indexOf(m)), skip: () => enter() });
  }
  try {
    setup(); updateMotionUI(); soundUI(state.audio);
    if (opts.playIntro) playIntro(); else skipToMenu();          // obie ścieżki budzą pętlę (wake) – jedna klatka RAF naraz
  } catch (err) { console.error("PMW renderer:", err); rendererError(); }
  return dispose;
}
