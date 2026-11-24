// Proceduralne tekstury (canvas): tkanina, dzianina kominiarki (z otworem na oczy), skóra.
import * as THREE from 'three';

function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
// mapa wysokości → normal map
function heightToNormal(H, w, h, strength) {
  const c = canvas(w, h), x = c.getContext('2d'), img = x.createImageData(w, h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const l = H[j * w + (i - 1 + w) % w], r = H[j * w + (i + 1) % w], u = H[((j - 1 + h) % h) * w + i], d = H[((j + 1) % h) * w + i];
    let nx = (l - r) * strength, ny = (d - u) * strength, nz = 1; const n = Math.hypot(nx, ny, nz); nx /= n; ny /= n; nz /= n;
    const k = (j * w + i) * 4; img.data[k] = (nx * .5 + .5) * 255; img.data[k + 1] = (ny * .5 + .5) * 255; img.data[k + 2] = (nz * .5 + .5) * 255; img.data[k + 3] = 255;
  }
  x.putImageData(img, 0, 0); return c;
}
function tex(c, { color = false, repeat = [1, 1] } = {}) {
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); t.anisotropy = 4;
  if (color) t.colorSpace = THREE.SRGBColorSpace; return t;
}
let F, K, L;
export function fabricMaps() {
  if (F) return F; const w = 256, h = 256, R = rng(7), H = new Float32Array(w * h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const weave = Math.sin(i * Math.PI / 2) * Math.sin(j * Math.PI / 2) * .5 + (((i >> 1) + (j >> 1)) % 2 ? .25 : -.25);
    H[j * w + i] = weave * .6 + (R() - .5) * .5;
  }
  // większe zagniecenia
  for (let k = 0; k < 40; k++) { const cx = R() * w, cy = R() * h, rr = 10 + R() * 30, a = R() * 3; for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const dx = i - cx, dy = j - cy, dd = (dx * Math.cos(a) + dy * Math.sin(a)); const q = Math.exp(-(dx * dx + dy * dy) / (rr * rr * 4)); H[j * w + i] += Math.sin(dd / rr * 3) * q * 1.2; } }
  F = { normal: tex(heightToNormal(H, w, h, 1.1), { repeat: [6, 6] }) }; return F;
}
export function leatherMaps() {
  if (L) return L; const w = 128, h = 128, R = rng(11), H = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) H[i] = R();
  for (let p = 0; p < 2; p++) { const G = H.slice(); for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { let s = 0; for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) s += G[((j + dj + h) % h) * w + (i + di + w) % w]; H[j * w + i] = s / 9; } }
  L = { normal: tex(heightToNormal(H, w, h, 6), { repeat: [8, 8] }) }; return L;
}
// UV głowy: u = 0.5 przód (kąt 0), v = wysokość (1.578 m → 0, 1.852 m → 1). Otwór na oczy: y 1.712–1.746, |x| ≤ ~0.062.
export const EYE_SLOT = { u0: .5 - .132, u1: .5 + .132, v0: .495, v1: .612 };
export function knitMaps() {
  if (K) return K; const w = 1024, h = 512, R = rng(3), H = new Float32Array(w * h);
  const cw = 6, ch = 7; // oczko dzianiny
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const ci = i % cw, cj = j % ch, half = ci < cw / 2 ? 1 : -1;
    const x = (ci - cw / 2 + .5) / (cw / 2), y = cj / ch;
    const vx = x - half * (-.5 + y * .9) * .55; // V-kształt
    const leg = Math.exp(-vx * vx * 6) * (.6 + .4 * Math.sin(y * Math.PI));
    const row = Math.floor(j / ch) % 2 ? .04 : 0;
    H[j * w + i] = leg + row + (R() - .5) * .18;
  }
  // brzeg otworu – pogrubiony ścieg
  const S = EYE_SLOT, ell = (u, v) => { const cu = (S.u0 + S.u1) / 2, cv = (S.v0 + S.v1) / 2, ru = (S.u1 - S.u0) / 2, rv = (S.v1 - S.v0) / 2; const du = (u - cu) / ru, dv = (v - cv) / rv; return Math.pow(Math.abs(du), 3) + Math.pow(Math.abs(dv), 3); };
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const e = ell(i / w, 1 - j / h); if (e > .7 && e < 1.9) H[j * w + i] += .8 * Math.exp(-Math.pow((e - 1.25) / .35, 2)); }
  // kolor
  const c = canvas(w, h), x = c.getContext('2d'), img = x.createImageData(w, h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const k = (j * w + i) * 4, v = H[j * w + i], n = .62 + v * .42;
    img.data[k] = Math.min(255, 112 * n + 6); img.data[k + 1] = Math.min(255, 9 * n + 2); img.data[k + 2] = Math.min(255, 12 * n + 3); img.data[k + 3] = 255;
  }
  x.putImageData(img, 0, 0);
  // alfa: otwór na oczy
  const a = canvas(w, h), ax = a.getContext('2d'); ax.fillStyle = '#fff'; ax.fillRect(0, 0, w, h);
  const ai = ax.getImageData(0, 0, w, h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (ell(i / w, 1 - j / h) < 1) { const k = (j * w + i) * 4; ai.data[k] = ai.data[k + 1] = ai.data[k + 2] = 0; }
  ax.putImageData(ai, 0, 0);
  const alpha = new THREE.CanvasTexture(a); alpha.flipY = true;
  const color = tex(c, { color: true }); color.wrapS = color.wrapT = THREE.ClampToEdgeWrapping;
  const normal = tex(heightToNormal(H, w, h, 2.2)); normal.wrapS = normal.wrapT = THREE.ClampToEdgeWrapping;
  // dzianina kafelkowana (bez otworu) – do siatki z SDF
  const tw = 128, th = 128, TH = new Float32Array(tw * th), R2 = rng(5);
  for (let j = 0; j < th; j++) for (let i = 0; i < tw; i++) { const ci = i % 8, cj = j % 8, half = ci < 4 ? 1 : -1; const x = (ci - 3.5) / 4, y = cj / 8; const vx = x - half * (-.5 + y * .9) * .55; TH[j * tw + i] = Math.exp(-vx * vx * 6) * (.6 + .4 * Math.sin(y * Math.PI)) + (R2() - .5) * .15; }
  const normalTile = tex(heightToNormal(TH, tw, th, 2.4));
  K = { color, normal, alpha, normalTile }; return K;
}
