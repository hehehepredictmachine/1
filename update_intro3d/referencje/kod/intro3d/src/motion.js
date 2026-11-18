// Ruch postaci: chód, zatrzymanie, oddech, sięgnięcie ręką (IK CCD) – wszystko funkcją czasu (deterministycznie).
import * as THREE from 'three';
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const smooth = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const e = new THREE.Euler(), q = new THREE.Quaternion();

function setRot(F, name, x, y, z, order = 'XYZ') {
  const b = F.bones[name], r = F.rest[name]; e.set(x, y, z, order); q.setFromEuler(e); b.quaternion.copy(r.q).multiply(q);
}
// profil prędkości: pełny chód do tStop, potem hamowanie przez dur → s∈[0,1]
export function speedAt(t, tStop, dur) { return 1 - smooth((t - tStop) / dur); }
// całka prędkości (dystans) i faza kroku liczone numerycznie (stały krok – identyczny wynik przy przewijaniu)
export function makeTrack({ tStop, dur, speed = 1.32, cadence = 1.86, phase0 = 0, T = 30 }) {
  const N = Math.ceil(T * 240), dist = new Float32Array(N + 1), ph = new Float32Array(N + 1);
  for (let i = 1; i <= N; i++) { const t = i / 240, s = speedAt(t, tStop, dur); dist[i] = dist[i - 1] + speed * s / 240; ph[i] = ph[i - 1] + 2 * Math.PI * cadence * (.35 + .65 * s) * s / 240; }
  return t => { const k = clamp(t * 240, 0, N), i = Math.floor(k), f = k - i, j = Math.min(i + 1, N); return { d: dist[i] + (dist[j] - dist[i]) * f, phase: phase0 + ph[i] + (ph[j] - ph[i]) * f, s: speedAt(t, tStop, dur) }; };
}

export function pose(F, { phase, s, t, lean = 0, look = [0, 0], breathe = 1, seed = 0 }) {
  const S = Math.sin(phase), C = Math.cos(phase), a = s;
  // biodra
  const hips = F.bones.hips; hips.position.copy(F.rest.hips.p);
  hips.position.y += -.022 * a * (1 - Math.cos(2 * phase)) * .5 - .012 * a;
  hips.position.x += .022 * a * S;
  setRot(F, 'hips', .04 * a, .11 * a * S, .045 * a * C);
  const br = Math.sin(t * 1.55 + seed) * .012 * breathe, sway = Math.sin(t * .6 + seed * 2) * .012 * (1 - a);
  hips.position.x += sway;
  setRot(F, 'spine', .03 * a + lean * .4 + br * .5, -.07 * a * S, -.02 * a * C + sway * .6);
  setRot(F, 'chest', .02 * a + lean * .6 - br, -.05 * a * S, -.015 * a * C);
  setRot(F, 'neck', -.03 * a - lean * .3 + look[0] * .4, look[1] * .4 + .03 * a * S, 0);
  setRot(F, 'head', -.02 * a + look[0] * .6 - br * .3, look[1] * .6 + .03 * a * S, 0);
  // nogi
  for (const [side, ph] of [['L', phase], ['R', phase + Math.PI]]) {
    const s1 = Math.sin(ph), c1 = Math.cos(ph);
    const thigh = -.40 * a * s1 - .04 * a;
    const knee = a * (.10 + .95 * Math.pow(Math.max(0, c1), 2) + .12 * Math.max(0, -s1)) + .03 * (1 - a);
    const ankle = -(thigh + knee) * .82 + a * (.16 * Math.max(0, s1) * Math.max(0, -c1) - .18 * Math.max(0, -s1) * Math.max(0, c1));
    const spread = side === 'L' ? .025 : -.025;
    setRot(F, 'upLeg_' + side, thigh, 0, spread * (1 - a * .5) + (side === 'L' ? 1 : -1) * .01);
    setRot(F, 'leg_' + side, knee, 0, 0);
    setRot(F, 'foot_' + side, ankle, 0, 0);
  }
  // ręce (wg wzoru chodu: wymach ~0,35 rad, łokieć mocno zgięty przy wymachu w przód)
  for (const [side, ph] of [['L', phase + Math.PI], ['R', phase]]) {
    const s1 = Math.sin(ph), sx = side === 'L' ? 1 : -1, fwd = Math.max(0, -s1);
    setRot(F, 'upperArm_' + side, -.34 * a * s1 + .05, -sx * .06 * a * s1, sx * (.015 + br * .5));
    setRot(F, 'foreArm_' + side, -.2 - a * (.12 + .62 * Math.pow(fwd, 1.3)), sx * .12, 0);
    setRot(F, 'hand_' + side, -.1 - .15 * a * fwd, sx * .15, 0);
  }
}

// ---- sięgnięcie: CCD na ramieniu + orientacja dłoni (dłoń w dół, palce od ciała) ----
const wp = new THREE.Vector3(), tp = new THREE.Vector3(), jp = new THREE.Vector3(), v1 = new THREE.Vector3(), v2 = new THREE.Vector3();
const qa = new THREE.Quaternion(), qp = new THREE.Quaternion(), qw = new THREE.Quaternion(), m = new THREE.Matrix4();
export function reach(F, side, target, w, palmTwist = 0) {
  if (w <= 0) return;
  const chain = ['foreArm_' + side, 'upperArm_' + side].map(n => F.bones[n]);
  const hand = F.bones['hand_' + side];
  const saved = chain.map(b => b.quaternion.clone());
  F.group.updateMatrixWorld(true);
  for (let it = 0; it < 14; it++) for (const b of chain) {
    hand.getWorldPosition(wp); b.getWorldPosition(jp);
    v1.subVectors(wp, jp).normalize(); v2.subVectors(target, jp).normalize();
    qa.setFromUnitVectors(v1, v2);
    b.parent.getWorldQuaternion(qp); b.getWorldQuaternion(qw);
    qw.premultiply(qa); b.quaternion.copy(qp.invert().multiply(qw)); b.updateMatrixWorld(true);
  }
  // łokieć nie może zginać się do tyłu – prosta kontrola: wymuszamy zgięcie forearm w zakresie
  chain.forEach((b, i) => b.quaternion.copy(saved[i].slerp(b.quaternion, w)));
  // dłoń: palce do przodu, wnętrze dłoni w dół (z kierunków spoczynkowych tej postaci)
  const R = F.hand[side];
  const want = basisRot(R.fingers, R.palm, new THREE.Vector3(0, -.2, 1).normalize(), new THREE.Vector3(0, -1, -.2).normalize());
  F.group.getWorldQuaternion(qw); want.premultiply(qw);
  hand.parent.updateMatrixWorld(true); hand.parent.getWorldQuaternion(qp);
  const local = qp.invert().multiply(want);
  hand.quaternion.slerp(local, w);
}
// obrót przenoszący parę (f0, p0) na (f1, p1)
function basisRot(f0, p0, f1, p1) {
  const mk = (f, p) => { const x = f.clone().normalize(), y = p.clone().sub(x.clone().multiplyScalar(p.dot(x))).normalize(), z = new THREE.Vector3().crossVectors(x, y); return new THREE.Matrix4().makeBasis(x, y, z); };
  const m0 = mk(f0, p0), m1 = mk(f1, p1);
  return new THREE.Quaternion().setFromRotationMatrix(m1.multiply(m0.transpose()));
}
