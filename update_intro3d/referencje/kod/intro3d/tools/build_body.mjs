// Generator bryły postaci w garniturze (SDF → Surface Nets → rzut na powierzchnię → wagi kości, materiały).
// Wynik: src/assets/body.bin.gz (pozycje uint16, normalne int8, kości uint8×4, wagi uint8×4, materiał uint8, indeksy uint32).
// Uruchom: node tools/build_body.mjs [krok_m=0.0045]
import fs from 'node:fs'; import zlib from 'node:zlib'; import path from 'node:path';
import iso from 'isosurface';

const STEP = +(process.argv[2] || 0.0045);
// ---------- matematyka SDF ----------
const len = (x, y, z) => Math.sqrt(x * x + y * y + z * z);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function smin(a, b, k) { if (k <= 0) return Math.min(a, b); const h = clamp(.5 + .5 * (b - a) / k, 0, 1); return b * (1 - h) + a * h - k * h * (1 - h); }
function smax(a, b, k) { return -smin(-a, -b, k); }
const sEll = (c, r) => (p) => { const x = (p[0] - c[0]) / r[0], y = (p[1] - c[1]) / r[1], z = (p[2] - c[2]) / r[2]; const k0 = len(x, y, z); const k1 = len(x / r[0], y / r[1], z / r[2]); return k0 * (k0 - 1) / (k1 || 1e-9); };
// stożek zaokrąglony a(ra) → b(rb)
const sRC = (a, b, ra, rb) => (p) => {
  const bx = b[0] - a[0], by = b[1] - a[1], bz = b[2] - a[2], l2 = bx * bx + by * by + bz * bz, rr = ra - rb, a2 = l2 - rr * rr, il2 = 1 / l2;
  const px = p[0] - a[0], py = p[1] - a[1], pz = p[2] - a[2], y = px * bx + py * by + pz * bz, z = y - l2;
  const qx = px * l2 - bx * y, qy = py * l2 - by * y, qz = pz * l2 - bz * y, x2 = qx * qx + qy * qy + qz * qz, y2 = y * y * l2, z2 = z * z * l2;
  const k = Math.sign(rr) * rr * rr * x2;
  if (Math.sign(z) * a2 * z2 > k) return Math.sqrt(x2 + z2) * il2 - rb;
  if (Math.sign(y) * a2 * y2 < k) return Math.sqrt(x2 + y2) * il2 - ra;
  return (Math.sqrt(x2 * a2 * il2) + y * rr) * il2 - ra;
};
const sCap = (a, b, r) => sRC(a, b, r, r);
// eliptyczny przekrój: skala osi Z
const sZ = (f, kz) => (p) => f([p[0], p[1], p[2] * kz]) / Math.max(1, kz);
const sBox = (c, h, r = 0, rotY = 0, rotX = 0) => (p) => {
  let x = p[0] - c[0], y = p[1] - c[1], z = p[2] - c[2];
  if (rotY) { const cs = Math.cos(rotY), sn = Math.sin(rotY); [x, z] = [cs * x - sn * z, sn * x + cs * z]; }
  if (rotX) { const cs = Math.cos(rotX), sn = Math.sin(rotX); [y, z] = [cs * y - sn * z, sn * y + cs * z]; }
  const qx = Math.abs(x) - h[0] + r, qy = Math.abs(y) - h[1] + r, qz = Math.abs(z) - h[2] + r;
  return len(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - r;
};
const sTorusY = (c, R, r, sx = 1, sz = 1) => (p) => { const x = (p[0] - c[0]) / sx, z = (p[2] - c[2]) / sz, y = p[1] - c[1]; const q = Math.hypot(x, z) - R; return Math.hypot(q, y) - r; };

// ---------- szkielet (pozycje stawów w pozie spoczynkowej) ----------
const A = 0.17; // odwiedzenie ramion od tułowia (rad)
const J = {};
J.hips = [0, 1.0, 0]; J.spine = [0, 1.12, 0]; J.chest = [0, 1.30, 0]; J.neck = [0, 1.54, -0.012]; J.head = [0, 1.64, -0.004];
for (const [s, sx] of [['L', 1], ['R', -1]]) {
  J['upperArm_' + s] = [sx * 0.19, 1.488, -0.018];
  J['foreArm_' + s] = [J['upperArm_' + s][0] + sx * Math.sin(A) * 0.295, J['upperArm_' + s][1] - Math.cos(A) * 0.295, -0.02];
  J['hand_' + s] = [J['foreArm_' + s][0] + sx * Math.sin(A * 0.8) * 0.255, J['foreArm_' + s][1] - Math.cos(A * 0.8) * 0.255, -0.006];
  J['upLeg_' + s] = [sx * 0.094, 0.935, 0.0]; J['leg_' + s] = [sx * 0.1, 0.5, 0.008]; J['foot_' + s] = [sx * 0.104, 0.085, -0.02];
}
const PARENT = { hips: 'root', spine: 'hips', chest: 'spine', neck: 'chest', head: 'neck' };
for (const s of ['L', 'R']) Object.assign(PARENT, { ['upperArm_' + s]: 'chest', ['foreArm_' + s]: 'upperArm_' + s, ['hand_' + s]: 'foreArm_' + s, ['upLeg_' + s]: 'hips', ['leg_' + s]: 'upLeg_' + s, ['foot_' + s]: 'leg_' + s });
const BONES = ['root', 'hips', 'spine', 'chest', 'neck', 'head', 'upperArm_L', 'foreArm_L', 'hand_L', 'upperArm_R', 'foreArm_R', 'hand_R', 'upLeg_L', 'leg_L', 'foot_L', 'upLeg_R', 'leg_R', 'foot_R'];
const BI = Object.fromEntries(BONES.map((b, i) => [b, i]));
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k], lerp3 = (a, b, t) => add(a, mul(add(b, mul(a, -1)), t));

// materiały
const M = { SUIT: 0, SHIRT: 1, TIE: 2, LAPEL: 3, GLOVE: 4, SHOE: 5, MASK: 6, SKIN: 7, PANTS: 8 };

// ---------- prymitywy: [sdf, kość, materiał] w grupach (gładko łączone w grupie, ostro między grupami) ----------
const G = [];
const grp = (k, list) => G.push({ k, list });
// TUŁÓW + MARYNARKA
grp(0.045, [
  [sEll([0, 1.345, 0.008], [0.168, 0.15, 0.106]), 'chest', M.SUIT],
  [sCap([-0.168, 1.462, -0.02], [0.168, 1.462, -0.02], 0.064), 'chest', M.SUIT],
  [sEll([0, 1.16, -0.004], [0.15, 0.16, 0.09]), 'spine', M.SUIT],
  [sEll([0, 0.985, -0.008], [0.166, 0.13, 0.098]), 'hips', M.SUIT],
  [sZ(sRC([0, 0.95, -0.006 * 1.45], [0, 0.805, -0.004 * 1.45], 0.165, 0.16), 1.45), 'hips', M.SUIT],      // poła marynarki (przekrój eliptyczny)
  [sEll([0, 0.94, -0.045], [0.14, 0.09, 0.06]), 'hips', M.SUIT],                    // pośladki pod marynarką
]);
// BARKI (watowanie marynarki)
for (const [s, sx] of [['L', 1], ['R', -1]]) grp(0.03, [[sEll([sx * 0.196, 1.45, -0.016], [0.064, 0.05, 0.068]), 'upperArm_' + s, M.SUIT], [sEll([sx * 0.15, 1.458, -0.016], [0.06, 0.046, 0.068]), 'chest', M.SUIT]]);
// RĘKAWY + MANKIETY + RĘKAWICE
for (const [s, sx] of [['L', 1], ['R', -1]]) {
  const sh = J['upperArm_' + s], el = J['foreArm_' + s], wr = J['hand_' + s];
  const dir = mul(add(wr, mul(el, -1)), 1 / 0.255);
  grp(0.02, [
    [sRC(add(sh, [0, -0.01, 0]), el, 0.062, 0.051), 'upperArm_' + s, M.SUIT],
    [sRC(el, add(wr, mul(dir, -0.028)), 0.051, 0.044), 'foreArm_' + s, M.SUIT],
  ]);
  grp(0.004, [[sRC(add(wr, mul(dir, -0.04)), add(wr, mul(dir, -0.004)), 0.0405, 0.039), 'foreArm_' + s, M.SHIRT]]);
  // dłoń w rękawicy: śródręcze + palce złączone lekko zgięte + kciuk (dłoń zwrócona do ciała)
  const fw = dir, side = [sx, 0, 0], fwd = [0, 0, 1];
  const hand = [];
  hand.push([sBox(add(wr, mul(fw, 0.052)), [0.017, 0.05, 0.042], 0.015, 0, 0), 'hand_' + s, M.GLOVE]);
  hand.push([sRC(add(wr, mul(fw, 0.006)), add(wr, mul(fw, 0.03)), 0.034, 0.03), 'hand_' + s, M.GLOVE]);
  const fz = [0.028, 0.009, -0.01, -0.027], fl = [0.075, 0.085, 0.081, 0.064];
  fz.forEach((z, i) => { const b0 = add(add(wr, mul(fw, 0.098)), [0, 0, z]); const b1 = add(add(b0, mul(fw, fl[i] * 0.6)), [-sx * 0.012, 0, 0]); const b2 = add(add(b1, mul(fw, fl[i] * 0.4)), [-sx * 0.022, 0, 0]);
    hand.push([sRC(b0, b1, 0.0105, 0.0095), 'hand_' + s, M.GLOVE]); hand.push([sRC(b1, b2, 0.0095, 0.0085), 'hand_' + s, M.GLOVE]); });
  hand.push([sRC(add(add(wr, mul(fw, 0.03)), [-sx * 0.012, 0, 0.034]), add(add(wr, mul(fw, 0.085)), [-sx * 0.03, 0, 0.05]), 0.013, 0.0105), 'hand_' + s, M.GLOVE]);
  grp(0.008, hand);
}
// SPODNIE
for (const [s, sx] of [['L', 1], ['R', -1]]) {
  const hp = J['upLeg_' + s], kn = J['leg_' + s], an = J['foot_' + s];
  grp(0.03, [
    [sRC(add(hp, [0, 0.03, 0]), kn, 0.092, 0.064), 'upLeg_' + s, M.PANTS],
    [sRC(kn, [an[0], 0.115, an[2] - 0.004], 0.062, 0.058), 'leg_' + s, M.PANTS],
    [sEll([sx * 0.08, 0.86, 0.0], [0.09, 0.09, 0.1]), 'hips', M.PANTS],
  ]);
  // BUT (oxford): obcas → czubek, płaska podeszwa
  const shoeA = sRC([an[0], 0.045, -0.07], [an[0], 0.04, 0.155], 0.045, 0.034), shoeB = sEll([an[0], 0.07, -0.005], [0.046, 0.06, 0.06]);
  const shoe = (p) => { const d = smin(shoeA(p), shoeB(p), 0.03); return smax(d, -(p[1] - 0.002), 0.004); };
  grp(0.012, [[shoe, 'foot_' + s, M.SHOE]]);
}
// SZYJA + GŁOWA (kominiarka) – materiał MASK; otwór na oczy wycinany niżej
const headParts = [
  [sCap([0, 1.5, -0.012], [0, 1.65, -0.002], 0.06), 'neck', M.MASK],
  [sEll([0, 1.728, -0.006], [0.081, 0.1, 0.097]), 'head', M.MASK],
  [sEll([0, 1.66, 0.026], [0.066, 0.064, 0.072]), 'head', M.MASK],     // żuchwa
  [sEll([0, 1.622, 0.05], [0.036, 0.024, 0.04]), 'head', M.MASK],      // broda
  [sEll([0, 1.692, 0.098], [0.016, 0.026, 0.019]), 'head', M.MASK],    // nos
  [sEll([0, 1.752, 0.075], [0.06, 0.018, 0.03]), 'head', M.MASK],      // łuki brwiowe
  [sEll([0.079, 1.7, -0.006], [0.012, 0.03, 0.02]), 'head', M.MASK], [sEll([-0.079, 1.7, -0.006], [0.012, 0.03, 0.02]), 'head', M.MASK], // uszy
];
grp(0.03, headParts);

// KOŁNIERZYK koszuli + węzeł krawata
grp(0.006, [[sTorusY([0, 1.52, 0.004], 0.064, 0.013, 1.0, 0.95), 'chest', M.SHIRT], [sEll([0, 1.488, 0.088], [0.017, 0.021, 0.013]), 'chest', M.TIE]]);

// ---------- pole odległości ----------
const NP = G.reduce((a, g) => a + g.list.length, 0);
const tmpD = new Float64Array(NP);
function field(p, out) {
  let total = 1e9, idx = 0, best = 1e9, bestI = 0;
  for (const g of G) {
    let gd = 1e9;
    for (const [f] of g.list) { const d = f(p); tmpD[idx] = d; if (d < best) { best = d; bestI = idx; } gd = gd === 1e9 ? d : smin(gd, d, g.k); idx++; }
    total = Math.min(total, gd);
  }
  // pola V marynarki: koszula/krawat zagłębione, klapy uniesione (tylko z przodu tułowia)
  const [x, y, z] = p; let d = total;
  if (z > 0.04 && y > 1.1 && y < 1.53) {
    const vw = 0.012 + (y - 1.12) * 0.24;                // szerokość wycięcia V
    const ax = Math.abs(x);
    if (ax < vw) d += 0.0065 * clamp((vw - ax) / 0.01, 0, 1) * clamp((1.52 - y) / 0.02, 0, 1);  // koszula w głębi
    const lapIn = vw, lapOut = vw + 0.05 + (y - 1.2) * 0.05;
    if (y > 1.18 && ax > lapIn && ax < lapOut) d -= 0.0032 * clamp((ax - lapIn) / 0.004, 0, 1) * clamp((lapOut - ax) / 0.004, 0, 1); // klapy
  }
  // otwór na oczy w kominiarce – płytkie wgłębienie (skóra widoczna w szczelinie)
  if (z > 0.05 && y > 1.7 && y < 1.76) { const q = (Math.abs(x) / 0.064) ** 4 + ((y - 1.728) / 0.0175) ** 4; if (q < 1.6) d += 0.0045 * clamp((1.6 - q) / 0.6, 0, 1); }
  if (out) { out.best = bestI; out.dist = tmpD; }
  return d;
}
// materiał wg pozycji (korekty na przodzie marynarki)
function material(p, base) {
  const [x, y, z] = p;
  if ((base === M.SUIT) && z > 0.04 && y > 1.1 && y < 1.53) {
    const vw = 0.012 + (y - 1.12) * 0.24, ax = Math.abs(x);
    const tie = 0.009 + (1.48 - y) * 0.045;
    if (ax < vw) return ax < tie && y < 1.485 ? M.TIE : M.SHIRT;
    if (y > 1.18 && ax < vw + 0.05 + (y - 1.2) * 0.05) return M.LAPEL;
  }
  if (base === M.SHIRT && y > 1.49 && y < 1.56 && z < 0.035) return M.SUIT;   // z tyłu kołnierz marynarki
  if (base === M.MASK) {
    const ex = Math.abs(x), slot = ((ex / 0.064) ** 4 + ((y - 1.728) / 0.0175) ** 4) < 1 && z > 0.05;
    if (slot) return M.SKIN;
  }
  return base;
}
// ---------- siatka ----------
const B = [[-0.42, -0.01, -0.2], [0.42, 1.88, 0.27]];
const dims = [Math.ceil((B[1][0] - B[0][0]) / STEP), Math.ceil((B[1][1] - B[0][1]) / STEP), Math.ceil((B[1][2] - B[0][2]) / STEP)];
console.log('siatka', dims.join('×'), 'prymitywów', NP);
let t0 = Date.now();
const mesh = iso.surfaceNets(dims, (x, y, z) => field([x, y, z]), B);
console.log('surface nets', mesh.positions.length, 'wierzch.', mesh.cells.length, 'trójk.', (Date.now() - t0) / 1000 + 's');
// rzut na powierzchnię + normalne z gradientu
const P = mesh.positions, N = [], e = 0.0012;
const grad = (p) => { const dx = field([p[0] + e, p[1], p[2]]) - field([p[0] - e, p[1], p[2]]), dy = field([p[0], p[1] + e, p[2]]) - field([p[0], p[1] - e, p[2]]), dz = field([p[0], p[1], p[2] + e]) - field([p[0], p[1], p[2] - e]); const l = len(dx, dy, dz) || 1; return [dx / l, dy / l, dz / l]; };
for (const p of P) { for (let it = 0; it < 3; it++) { const d = field(p), g = grad(p); p[0] -= g[0] * d; p[1] -= g[1] * d; p[2] -= g[2] * d; } N.push(grad(p)); }
// wagi kości i materiał
const BW = [], MAT = []; const info = {};
const flat = G.flatMap(g => g.list);
for (const p of P) {
  field(p, info); const dmin = Math.min(...info.dist);
  const w = new Map();
  info.dist.forEach((d, i) => { const dd = d - dmin; if (dd < 0.05) { const b = flat[i][1]; w.set(b, (w.get(b) || 0) + Math.exp(-dd / 0.011)); } });
  const arr = [...w.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4); const s = arr.reduce((a, x) => a + x[1], 0);
  BW.push(arr.map(([b, v]) => [BI[b], v / s]));
  MAT.push(material(p, flat[info.best][2]));
}
// pakowanie
const nv = P.length, nt = mesh.cells.length;
const lo = B[0], sc = [B[1][0] - B[0][0], B[1][1] - B[0][1], B[1][2] - B[0][2]];
const head = new Uint32Array([0x504d5731, nv, nt]);
const pos = new Uint16Array(nv * 3), nor = new Int8Array(nv * 3), si = new Uint8Array(nv * 4), sw = new Uint8Array(nv * 4), mat = new Uint8Array(nv), idx = new Uint32Array(nt * 3);
P.forEach((p, i) => { for (let k = 0; k < 3; k++) { pos[i * 3 + k] = Math.round(clamp((p[k] - lo[k]) / sc[k], 0, 1) * 65535); nor[i * 3 + k] = Math.round(N[i][k] * 127); }
  let acc = 0; BW[i].forEach(([b, v], k) => { si[i * 4 + k] = b; const q = k === BW[i].length - 1 ? 255 - acc : Math.round(v * 255); sw[i * 4 + k] = q; acc += q; }); mat[i] = MAT[i]; });
mesh.cells.forEach((c, i) => { idx[i * 3] = c[0]; idx[i * 3 + 1] = c[1]; idx[i * 3 + 2] = c[2]; });
const bounds = new Float32Array([...lo, ...sc]);
const joints = new Float32Array(BONES.flatMap(b => b === 'root' ? [0, 0, 0] : J[b]));
const parts = [head, bounds, joints, pos, nor, si, sw, mat, idx].map(a => Buffer.from(a.buffer, a.byteOffset, a.byteLength));
const pad = b => b.length % 4 ? Buffer.concat([b, Buffer.alloc(4 - b.length % 4)]) : b;
const raw = Buffer.concat(parts.map(pad));
const gz = zlib.gzipSync(raw, { level: 9 });
fs.mkdirSync('src/assets', { recursive: true }); fs.writeFileSync('src/assets/body.bin.gz', gz);
fs.writeFileSync('src/assets/skeleton.json', JSON.stringify({ bones: BONES, parent: PARENT, joints: Object.fromEntries(BONES.map(b => [b, b === 'root' ? [0, 0, 0] : J[b]])) }));
console.log('zapisano', (raw.length / 1e6).toFixed(2), 'MB →', (gz.length / 1e6).toFixed(2), 'MB gz', (Date.now() - t0) / 1000 + 's');
