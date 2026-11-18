// PMW intro – postać w garniturze: bryła wygenerowana z SDF (tools/build_body.mjs), skórowana, materiały wg stref.
import * as THREE from 'three';
import { gunzipSync } from 'fflate';
import BODY_GZ from './assets/body.bin.gz';
import SKEL from './assets/skeleton.json';
import { fabricMaps, knitMaps, leatherMaps } from './textures.js';

export const MAT = { SUIT: 0, SHIRT: 1, TIE: 2, LAPEL: 3, GLOVE: 4, SHOE: 5, MASK: 6, SKIN: 7, PANTS: 8 };
let BASE = null;
function decode() {
  if (BASE) return BASE;
  const raw = gunzipSync(BODY_GZ), buf = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
  let o = 0; const take = (T, n) => { const a = new T(buf, o, n); o += a.byteLength; o = (o + 3) & ~3; return a; };
  const head = take(Uint32Array, 3), nv = head[1], nt = head[2];
  const bounds = take(Float32Array, 6); take(Float32Array, SKEL.bones.length * 3);
  const pos = take(Uint16Array, nv * 3), nor = take(Int8Array, nv * 3), si = take(Uint8Array, nv * 4), sw = take(Uint8Array, nv * 4), mat = take(Uint8Array, nv), idx = take(Uint32Array, nt * 3);
  const P = new Float32Array(nv * 3), N = new Float32Array(nv * 3), UV = new Float32Array(nv * 2), SI = new Uint16Array(nv * 4), SW = new Float32Array(nv * 4);
  for (let i = 0; i < nv; i++) {
    for (let k = 0; k < 3; k++) { P[i * 3 + k] = bounds[k] + pos[i * 3 + k] / 65535 * bounds[3 + k]; N[i * 3 + k] = nor[i * 3 + k] / 127; }
    for (let k = 0; k < 4; k++) { SI[i * 4 + k] = si[i * 4 + k]; SW[i * 4 + k] = sw[i * 4 + k] / 255; }
    const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2];
    if (mat[i] === MAT.MASK || mat[i] === MAT.SKIN) { UV[i * 2] = (Math.atan2(x, z) / Math.PI + 1) * 3.2; UV[i * 2 + 1] = y * 11; }
    else { UV[i * 2] = (x + z * .7) * 6; UV[i * 2 + 1] = y * 6; }
  }
  // trójkąty wg materiału (większość wierzchołków)
  const buckets = Array.from({ length: 9 }, () => []);
  for (let t = 0; t < nt; t++) {
    const a = idx[t * 3], b = idx[t * 3 + 1], c = idx[t * 3 + 2], ma = mat[a], mb = mat[b], mc = mat[c];
    const m = (mb === mc) ? mb : ma;
    // kierunek ściany zgodny z normalną
    const ax = P[a * 3], ay = P[a * 3 + 1], az = P[a * 3 + 2];
    const ux = P[b * 3] - ax, uy = P[b * 3 + 1] - ay, uz = P[b * 3 + 2] - az, vx = P[c * 3] - ax, vy = P[c * 3 + 1] - ay, vz = P[c * 3 + 2] - az;
    const fx = uy * vz - uz * vy, fy = uz * vx - ux * vz, fz = ux * vy - uy * vx;
    const dot = fx * (N[a * 3] + N[b * 3] + N[c * 3]) + fy * (N[a * 3 + 1] + N[b * 3 + 1] + N[c * 3 + 1]) + fz * (N[a * 3 + 2] + N[b * 3 + 2] + N[c * 3 + 2]);
    if (dot >= 0) buckets[m].push(a, b, c); else buckets[m].push(a, c, b);
  }
  const index = [], groups = [];
  buckets.forEach((l, m) => { if (l.length) { groups.push([index.length, l.length, m]); for (const v of l) index.push(v); } });
  BASE = { P, N, UV, SI, SW, index: new Uint32Array(index), groups };
  return BASE;
}

let MATS = null;
function materials() {
  if (MATS) return MATS;
  const fab = fabricMaps(), knit = knitMaps(), lea = leatherMaps();
  const wool = c => new THREE.MeshPhysicalMaterial({ color: c, roughness: .74, normalMap: fab.normal, normalScale: new THREE.Vector2(.18, .18), sheen: .55, sheenColor: new THREE.Color(0x5a6378), sheenRoughness: .42 });
  const knitM = (c, sheen) => { const m = new THREE.MeshPhysicalMaterial({ color: c, roughness: .9, normalMap: knit.normalTile, normalScale: new THREE.Vector2(.65, .65), sheen: .6, sheenColor: new THREE.Color(sheen), sheenRoughness: .5 }); return m; };
  MATS = {
    suit: wool(0x15161a), pants: wool(0x131418),
    shirt: new THREE.MeshPhysicalMaterial({ color: 0x9da2ad, roughness: .68, sheen: .25, sheenColor: new THREE.Color(0xdfe4ee) }),
    tie: new THREE.MeshPhysicalMaterial({ color: 0x0b0b0e, roughness: .32, sheen: .8, sheenColor: new THREE.Color(0x6c7488), sheenRoughness: .3 }),
    lapel: new THREE.MeshPhysicalMaterial({ color: 0x0e0e11, roughness: .28, clearcoat: .25, clearcoatRoughness: .3, sheen: .6, sheenColor: new THREE.Color(0x7a8296) }),
    glove: new THREE.MeshPhysicalMaterial({ color: 0x0b0b0c, roughness: .38, normalMap: lea.normal, normalScale: new THREE.Vector2(.25, .25), clearcoat: .4, clearcoatRoughness: .3 }),
    shoe: new THREE.MeshPhysicalMaterial({ color: 0x050506, roughness: .45, clearcoat: .3, clearcoatRoughness: .3 }),
    maskRed: knitM(0x8a0c10, 0xd8382c), maskBlack: knitM(0x0d0d0f, 0x464c5c),
    skin: new THREE.MeshStandardMaterial({ color: 0x4a3128, roughness: .55 }),
    eye: new THREE.MeshPhysicalMaterial({ color: 0x0a0806, roughness: .05, clearcoat: 1, clearcoatRoughness: .02 }),
  };
  return MATS;
}

export function createFigure({ variant = 'mid', bulk = 1, height = 1 } = {}) {
  const D = decode(), M = materials();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(D.P, 3)); g.setAttribute('normal', new THREE.BufferAttribute(D.N, 3)); g.setAttribute('uv', new THREE.BufferAttribute(D.UV, 2));
  g.setAttribute('skinIndex', new THREE.BufferAttribute(D.SI, 4)); g.setAttribute('skinWeight', new THREE.BufferAttribute(D.SW, 4));
  g.setIndex(new THREE.BufferAttribute(D.index, 1));
  const byId = [M.suit, M.shirt, M.tie, M.lapel, M.glove, M.shoe, variant === 'mid' ? M.maskRed : M.maskBlack, M.skin, M.pants];
  const mats = []; D.groups.forEach(([start, count, m]) => { g.addGroup(start, count, mats.length); mats.push(byId[m]); });
  // oczy – osobne kule na kości głowy (doklejone do tej samej siatki skórowanej)
  const bones = {}, arr = [];
  for (const n of SKEL.bones) { const b = new THREE.Bone(); b.name = n; const p = SKEL.parent[n]; const w = SKEL.joints[n], pw = p ? SKEL.joints[p] : [0, 0, 0]; b.position.set(w[0] - pw[0], w[1] - pw[1], w[2] - pw[2]); bones[n] = b; arr.push(b); if (p) bones[p].add(b); }
  const mesh = new THREE.SkinnedMesh(g, mats);
  mesh.add(bones.root); mesh.bind(new THREE.Skeleton(arr));
  mesh.castShadow = mesh.receiveShadow = true; mesh.frustumCulled = false;
  const eyes = new THREE.Group();
  for (const sx of [1, -1]) { const e = new THREE.Mesh(new THREE.SphereGeometry(.0118, 16, 12), M.eye); e.position.set(sx * .031 - SKEL.joints.head[0], 1.728 - SKEL.joints.head[1], .0835 - SKEL.joints.head[2]); e.scale.z = .85; eyes.add(e); }
  bones.head.add(eyes);
  const group = new THREE.Group(); group.add(mesh); group.scale.set(height * bulk, height, height * (1 + (bulk - 1) * .7));
  const rest = Object.fromEntries(arr.map(b => [b.name, { p: b.position.clone(), q: b.quaternion.clone() }]));
  // kierunki dłoni w pozie spoczynkowej (do ustawienia dłoni przy sięgnięciu)
  const hand = {};
  for (const [s, sx] of [['L', 1], ['R', -1]]) { const w = SKEL.joints['hand_' + s], e = SKEL.joints['foreArm_' + s]; const f = new THREE.Vector3(w[0] - e[0], w[1] - e[1], w[2] - e[2]).normalize(); hand[s] = { fingers: f, palm: new THREE.Vector3(-sx, 0, 0) }; }
  return { group, mesh, bones, rest, variant, hand };
}
