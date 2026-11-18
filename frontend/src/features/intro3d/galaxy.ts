// @ts-nocheck
// Port 1:1 z update_intro3d/referencje/kod/intro3d/src/galaxy.js (wzorzec REF_C, three.js 0.187.0): liczby, kolejność wywołań, shadery, ziarna – bez zmian.
// Zmiany: wyłącznie ścieżki importów.
// Otoczenie: galaktyka spiralna, pole gwiazd, mgławice – proceduralnie, deterministycznie.
import * as THREE from 'three';
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const gauss = r => { let u = 0, v = 0; while (!u) u = r(); v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(6.2832 * v); };

const STAR_VS = `
attribute float aSize; attribute vec3 aCol; uniform float uPx, uB, uT, uTw;
varying vec3 vC; varying float vA;
void main(){ vec4 mv = modelViewMatrix*vec4(position,1.); gl_Position = projectionMatrix*mv;
  float tw = 1. + uTw*sin(uT*2.3 + position.x*13.1 + position.y*7.7);
  gl_PointSize = max(1.2, aSize*uPx/(-mv.z)); vC = aCol*uB*tw; vA = clamp(aSize*uPx/(-mv.z)/1.2,.15,1.); }`;
const STAR_FS = `uniform float uK; varying vec3 vC; varying float vA; void main(){ vec2 d=gl_PointCoord-.5; float r=length(d)*2.; float a=exp(-r*r*4.); gl_FragColor=vec4(vC*a*vA*uK,1.); }`;
const pts = (P, S, C, uniforms, k = 1) => { uniforms = { ...uniforms, uK: { value: k } }; const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); g.setAttribute('aSize', new THREE.Float32BufferAttribute(S, 1)); g.setAttribute('aCol', new THREE.Float32BufferAttribute(C, 3));
  const m = new THREE.ShaderMaterial({ vertexShader: STAR_VS, fragmentShader: STAR_FS, uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
  const o = new THREE.Points(g, m); o.frustumCulled = false; return o; };

function cloudTexture(seed, size = 256) {
  const r = rng(seed), c = document.createElement('canvas'); c.width = c.height = size; const x = c.getContext('2d'), img = x.createImageData(size, size);
  const N = 32, grid = Array.from({ length: N * N }, () => r());
  const noise = (u, v) => { const i = Math.floor(u), j = Math.floor(v), fu = u - i, fv = v - j; const g = (a, b) => grid[((b % N + N) % N) * N + ((a % N + N) % N)]; const s = t => t * t * (3 - 2 * t);
    return g(i, j) * (1 - s(fu)) * (1 - s(fv)) + g(i + 1, j) * s(fu) * (1 - s(fv)) + g(i, j + 1) * (1 - s(fu)) * s(fv) + g(i + 1, j + 1) * s(fu) * s(fv); };
  for (let j = 0; j < size; j++) for (let i = 0; i < size; i++) {
    const u = i / size * 6, v = j / size * 6; let f = 0, a = .5, k = 1; for (let o = 0; o < 5; o++) { f += a * noise(u * k + o * 7.1, v * k + o * 3.3); a *= .5; k *= 2; }
    const dx = i / size - .5, dy = j / size - .5, fall = Math.max(0, 1 - Math.sqrt(dx * dx + dy * dy) * 2); const val = Math.pow(Math.max(0, f - .38) * 1.9, 1.6) * fall * fall;
    const q = (j * size + i) * 4; img.data[q] = img.data[q + 1] = img.data[q + 2] = 255; img.data[q + 3] = Math.min(255, val * 255);
  }
  x.putImageData(img, 0, 0); return new THREE.CanvasTexture(c);
}

export function createGalaxy() {
  const root = new THREE.Group(), U = { uPx: { value: 800 }, uB: { value: 0 }, uT: { value: 0 }, uTw: { value: .25 } };
  // pole gwiazd (sfera)
  { const r = rng(21), P = [], S = [], C = []; for (let i = 0; i < 9000; i++) { const u = r() * 2 - 1, a = r() * 6.2832, k = Math.sqrt(1 - u * u), R = 140 + r() * 60; P.push(k * Math.cos(a) * R, u * R * .9 + 10, k * Math.sin(a) * R - 20);
      const m = Math.pow(r(), 7); S.push(.25 + m * 1.6); const w = r(); C.push(.75 + w * .25, .8 + w * .15, 1); }
    root.add(pts(P, S, C, U)); }
  // galaktyka spiralna – rdzeń za postaciami jako źródło światła konturowego
  const gal = new THREE.Group(); gal.position.set(-52, 40, -185); gal.rotation.set(1.05, .2, -.5); gal.scale.setScalar(.62); root.add(gal);
  { const r = rng(42), P = [], S = [], C = [], arms = 2, R0 = 70;
    for (let i = 0; i < 70000; i++) {
      const t = Math.pow(r(), .65), rad = t * R0, arm = (i % arms) * Math.PI, sp = 2.2 * Math.log(1 + rad / 6);
      const ang = arm + sp + gauss(r) * (.18 + .25 * (1 - t)), th = gauss(r) * (1.2 + 3.2 * Math.exp(-rad / 8));
      const x = Math.cos(ang) * rad + gauss(r) * 1.2, z = Math.sin(ang) * rad + gauss(r) * 1.2; P.push(x, th, z);
      const core = Math.exp(-rad / 9), pink = r() < .03 * t ? 1 : 0;
      S.push((.45 + Math.pow(r(), 6) * 2.0) * (1 + core * .6));
      C.push(lerp(.55, 1.0, core) + pink * .5, lerp(.62, .86, core) + pink * .05, lerp(1.0, .62, core) + pink * .25);
    }
    // zgrubienie centralne
    for (let i = 0; i < 16000; i++) { const R = Math.abs(gauss(r)) * 6.5, u = r() * 2 - 1, a = r() * 6.2832, k = Math.sqrt(1 - u * u); P.push(k * Math.cos(a) * R, u * R * .55, k * Math.sin(a) * R); S.push(.5 + r() * .6); C.push(.75, .62, .46); }
    gal.add(pts(P, S, C, U, .085)); }
  // poświata rdzenia i mgławice
  const glowT = (() => { const c = document.createElement('canvas'); c.width = c.height = 256; const x = c.getContext('2d'); const g = x.createRadialGradient(128, 128, 0, 128, 128, 128); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(.18, 'rgba(255,255,255,.42)'); g.addColorStop(.5, 'rgba(255,255,255,.08)'); g.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = g; x.fillRect(0, 0, 256, 256); return new THREE.CanvasTexture(c); })();
  const sprite = (tex, col, s, pos, op) => { const m = new THREE.SpriteMaterial({ map: tex, color: col, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false }); const o = new THREE.Sprite(m); o.scale.set(s[0], s[1], 1); o.position.set(...pos); o.userData.op = op; return o; };
  const neb = [];
  neb.push(sprite(glowT, 0xffd9a8, [44, 32], [-52, 40, -184], .1));
  neb.push(sprite(glowT, 0x8fa8ff, [130, 60], [-48, 38, -188], .08));
  const cols = [0x6a4cff, 0x2f6dff, 0xff4fa0, 0x8a5cff, 0x2fa6ff, 0xc04cff];
  for (let i = 0; i < 7; i++) { const r = rng(300 + i); neb.push(sprite(cloudTexture(77 + i), cols[i % cols.length], [80 + r() * 90, 50 + r() * 50], [(r() - .5) * 220, 6 + r() * 34, -130 - r() * 60], .1 + r() * .1)); }
  neb.forEach(n => root.add(n));
  return { root, U, gal, neb };
}
const lerp = (a, b, t) => a + (b - a) * t;
