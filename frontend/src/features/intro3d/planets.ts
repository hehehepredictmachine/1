// @ts-nocheck
// Port 1:1 z update_intro3d/referencje/kod/intro3d/src/planets.js (wzorzec REF_C, three.js 0.187.0): liczby, kolejność wywołań, shadery, ziarna – bez zmian.
// Zmiany: wyłącznie ścieżki importów.
// Trzy małe planety (FOREX, CRYPTO, OTC) – rzeźby z cząstek w stylu menu głównego.
import * as THREE from 'three';
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

const VS = `
attribute vec3 aStart; attribute float aSeed; attribute float aSize;
uniform float uK, uTime, uSize, uPx, uSpin, uPulse;
varying float vA; varying float vGlow;
mat2 rot(float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c);}
void main(){
  float k = smoothstep(0., 1., clamp(uK*1.25 - aSeed*.25, 0., 1.));
  vec3 p = position;
  p.xz = rot(uTime*uSpin)*p.xz;
  vec3 q = mix(aStart, p, k);
  q += normalize(p+1e-4)*uPulse*.012*sin(aSeed*40.+uTime*9.);
  vec4 mv = modelViewMatrix*vec4(q,1.);
  gl_Position = projectionMatrix*mv;
  gl_PointSize = uSize*aSize*uPx/(-mv.z);
  vA = k*(.55+.45*fract(aSeed*7.3)); vGlow = aSize;
}`;
const FS = `
uniform vec3 uColor; uniform float uOpacity, uPulse;
varying float vA; varying float vGlow;
void main(){
  vec2 d = gl_PointCoord-.5; float r = length(d)*2.;
  float a = smoothstep(1.,0.,r); a*=a;
  gl_FragColor = vec4(uColor*(.55+uPulse*.45)*(.5+.5*vGlow), a*vA*uOpacity*.5);
}`;

function points(kind, R) {
  const r = rng(101 + kind * 17), P = [], S = [], seed = [], size = [];
  const add = (x, y, z, s = 1) => { P.push(x, y, z); const th = r() * 6.283, ph = Math.acos(2 * r() - 1), d = R * (6 + r() * 10); S.push(Math.sin(ph) * Math.cos(th) * d, Math.cos(ph) * d * .6, Math.sin(ph) * Math.sin(th) * d); seed.push(r()); size.push(s); };
  const sph = (n, rad, s = 1, jitter = 0) => { for (let i = 0; i < n; i++) { const u = r() * 2 - 1, a = r() * 6.283, k = Math.sqrt(1 - u * u), j = 1 + (r() - .5) * jitter; add(k * Math.cos(a) * rad * j, u * rad * j, k * Math.sin(a) * rad * j, s); } };
  if (kind === 0) { // FOREX: kula + pierścień + 4 księżyce
    sph(2200, R, .9, .04);
    const tilt = .3; for (let i = 0; i < 1500; i++) { const a = r() * 6.283, rr = R * (1.45 + r() * .32); const y = Math.sin(a) * rr * Math.sin(tilt) * .25; add(Math.cos(a) * rr, y + (r() - .5) * R * .02, Math.sin(a) * rr * Math.cos(tilt), .7); }
    for (let m = 0; m < 4; m++) { const a = m * 1.57 + .4, rr = R * 2.05; const cx = Math.cos(a) * rr, cz = Math.sin(a) * rr, cy = (m % 2 ? 1 : -1) * R * .28; for (let i = 0; i < 90; i++) { const u = r() * 2 - 1, b = r() * 6.283, k = Math.sqrt(1 - u * u); add(cx + k * Math.cos(b) * R * .14, cy + u * R * .14, cz + k * Math.sin(b) * R * .14, 1.1); } }
  } else if (kind === 1) { // CRYPTO: sieć bloków + łańcuch
    const g = 5; for (let i = 0; i < 2600; i++) { let x = r() * 2 - 1, y = r() * 2 - 1, z = r() * 2 - 1; if (x * x + y * y + z * z > 1) { i--; continue; } const q = v => Math.round(v * g) / g; const f = r() < .7; add((f ? q(x) : x) * R, (f ? q(y) : y) * R, (f ? q(z) : z) * R, f ? 1 : .6); }
    for (let b = 0; b < 20; b++) { const a = b / 20 * 6.283, rr = R * 1.6; const cx = Math.cos(a) * rr, cz = Math.sin(a) * rr, cy = Math.sin(a * 3) * R * .18; for (let i = 0; i < 40; i++) add(cx + (r() - .5) * R * .16, cy + (r() - .5) * R * .16, cz + (r() - .5) * R * .16, .9); }
  } else { // OTC: rdzeń + powłoka południków
    sph(1300, R * .56, 1.1, .1);
    for (let m = 0; m < 9; m++) { const a0 = m / 9 * 3.1416; for (let i = 0; i < 170; i++) { const t = r() * 6.283; const x = Math.cos(t) * R * 1.02, y = Math.sin(t) * R * 1.02; add(x * Math.cos(a0), y, x * Math.sin(a0), .75); } }
    for (let i = 0; i < 600; i++) { const t = r() * 6.283; add(Math.cos(t) * R * 1.02, (r() - .5) * R * .02, Math.sin(t) * R * 1.02, .7); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); g.setAttribute('aStart', new THREE.Float32BufferAttribute(S, 3));
  g.setAttribute('aSeed', new THREE.Float32BufferAttribute(seed, 1)); g.setAttribute('aSize', new THREE.Float32BufferAttribute(size, 1));
  return g;
}
const COLORS = [new THREE.Color(.62, .74, 1.0), new THREE.Color(.74, .68, 1.0), new THREE.Color(1.0, .95, .88)];
export function createPlanets(R = .045) {
  const group = new THREE.Group(), items = [];
  const glowTex = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d'); const g = x.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(.2, 'rgba(255,255,255,.35)'); g.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = g; x.fillRect(0, 0, 128, 128); const t = new THREE.CanvasTexture(c); return t; })();
  for (let k = 0; k < 3; k++) {
    const mat = new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uK: { value: 0 }, uTime: { value: 0 }, uSize: { value: .006 }, uPx: { value: 800 }, uSpin: { value: .5 + k * .12 }, uPulse: { value: 0 }, uColor: { value: COLORS[k].clone() }, uOpacity: { value: 1 } } });
    const pts = new THREE.Points(points(k, R), mat); pts.frustumCulled = false;
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: COLORS[k], transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
    glow.scale.setScalar(R * 5);
    const node = new THREE.Group(); node.add(pts, glow); group.add(node);
    items.push({ node, pts, glow, mat });
  }
  const light = new THREE.PointLight(0xbcd0ff, 0, 3.5, 2); group.add(light);
  return { group, items, light, R };
}
