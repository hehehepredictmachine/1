// @ts-nocheck
// Port 1:1 z update_intro3d/referencje/kod/intro3d/src/intro.js (wzorzec REF_C, three.js 0.187.0): scena, oś czasu TL, światła, kamera,
// postprocessing, shadery i liczby bez zmian. Zmiany (SC3 / I1): ścieżki importów, eksport ES zamiast window.PMW_Intro3D, zdarzenie 'error' przy
// utracie kontekstu WebGL, pełne dispose() (render targety composera / bloom / lustra, mapy cieni, tekstury, nasłuch resize, forceContextLoss).
// PepeMarketWizard – animacja startowa 3D (three.js). Cała scena jest funkcją czasu t: seek(t) daje zawsze tę samą klatkę.
// API podobne do <video>: play(), pause(), currentTime, duration, muted, readyState, zdarzenia 'ended' / 'error'.
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { Reflector } from 'three/examples/jsm/objects/Reflector.js';
import { createFigure } from './figure';
import { createGalaxy } from './galaxy';
import { makeTrack, pose, reach } from './motion';
import { createPlanets } from './planets';

const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const smooth = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const ease = x => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const lerp = (a, b, t) => a + (b - a) * t;
const win = (t, a, b) => clamp((t - a) / (b - a));

// ---------- scenariusz (sekundy) ----------
export const TL = Object.freeze({
  duration: 13.8,
  fadeIn: [0, 2.4],          // z czerni
  stop: { mid: [5.7, 1.5], left: [5.5, 1.45], right: [5.85, 1.5] }, // [start hamowania, czas hamowania]
  planetsIn: [7.0, 8.7],     // pojawienie się 3 planet
  gather: [8.7, 10.0],       // planety zbliżają się pod dłoń
  reach: [8.5, 10.2],        // ręka środkowej postaci
  touch: 10.2,               // dłoń na planetach
  push: [10.5, 13.3],        // najazd kamery
  flash: [12.7, 13.8],       // błysk → menu
});
const START = { mid: [0, -15.3], left: [-1.08, -15.85], right: [1.1, -15.75] };

const FINAL = {
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uFade: { value: 0 }, uFlash: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) }, uBars: { value: .1 } },
  vertexShader: `varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
  fragmentShader: `
  uniform sampler2D tDiffuse; uniform float uTime,uFade,uFlash,uBars; uniform vec2 uRes; varying vec2 vUv;
  float h(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
  void main(){
    vec2 uv=vUv, c=uv-.5; float d=dot(c,c);
    float ab=.0016+d*.006;
    vec3 col=vec3(texture2D(tDiffuse,uv+c*ab).r,texture2D(tDiffuse,uv).g,texture2D(tDiffuse,uv-c*ab).b);
    col*=1.-smoothstep(.12,.62,d)*.78;                          // winieta
    col+=(h(uv*uRes+fract(uTime*7.1)*91.)-.5)*.045;           // ziarno
    col*=uFade;
    col=mix(col,vec3(.86,.9,1.),uFlash);
    float bar=step(uv.y,uBars)+step(1.-uBars,uv.y); col*=1.-bar;   // pasy kinowe
    gl_FragColor=vec4(max(col,0.),1.);
  }`,
};

export class Intro3D extends EventTarget {
  constructor(canvas, { pixelRatioCap = 1.65, shadows = true, reflections = true } = {}) {
    super();
    this.canvas = canvas; this.style = canvas.style; this._t = 0; this._playing = false; this._raf = 0; this.muted = true; this.readyState = 0; this.duration = TL.duration;
    this.paused = true; this._cap = pixelRatioCap;
    const r = this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    r.setClearColor(0x000000, 1); r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05; r.outputColorSpace = THREE.SRGBColorSpace;
    r.shadowMap.enabled = shadows; r.shadowMap.type = THREE.PCFSoftShadowMap;
    const sc = this.scene = new THREE.Scene(); sc.background = new THREE.Color(0x000000); sc.fog = new THREE.FogExp2(0x03040a, .05);
    const cam = this.camera = new THREE.PerspectiveCamera(30, 16 / 9, .05, 600);
    // POSTACIE
    this.fig = {
      mid: createFigure({ variant: 'mid', bulk: 1.04, height: 1.0 }),
      left: createFigure({ variant: 'side', bulk: 1.0, height: .985 }),
      right: createFigure({ variant: 'side', bulk: 1.06, height: 1.01 }),
    };
    for (const k in this.fig) sc.add(this.fig[k].group);
    this.track = {
      mid: makeTrack({ tStop: TL.stop.mid[0], dur: TL.stop.mid[1], phase0: 0 }),
      left: makeTrack({ tStop: TL.stop.left[0], dur: TL.stop.left[1], phase0: 2.1, cadence: 1.82 }),
      right: makeTrack({ tStop: TL.stop.right[0], dur: TL.stop.right[1], phase0: 4.0, cadence: 1.9 }),
    };
    // PODŁOGA – mokre, ciemne lustro przygaszone półprzezroczystą warstwą
    if (reflections) {
      const refl = new Reflector(new THREE.PlaneGeometry(900, 900), { clipBias: .003, textureWidth: 1024, textureHeight: 1024, color: 0x7d8390 });
      refl.rotation.x = -Math.PI / 2; refl.position.y = -.001; sc.add(refl); this.refl = refl;
    }
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(900, 900), new THREE.MeshLambertMaterial({ color: 0x07080d, transparent: true, opacity: reflections ? .78 : 1 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; sc.add(floor);
    // ŚWIATŁA
    const back = (x, col, i) => { const s = new THREE.SpotLight(col, 0, 40, .42, .65, 1.6); s.position.set(x, 7.5, -24); s.target.position.set(x * .2, 0, -9); s.castShadow = shadows; s.shadow.mapSize.set(1024, 1024); s.shadow.bias = -.0004; s.shadow.camera.near = 8; s.shadow.camera.far = 40; sc.add(s, s.target); s.userData.base = i; return s; };
    this.backL = back(2.0, 0xffdcb0, 760); this.backR = back(-3.6, 0x9db4ff, 560);
    this.top = new THREE.SpotLight(0xcfd6e6, 0, 30, .55, .9, 1.5); this.top.position.set(0, 9, -6); this.top.target.position.set(0, 0, -7); this.top.userData.base = 30; sc.add(this.top, this.top.target);
    this.screen = new THREE.SpotLight(0xaebfdc, 0, 30, .32, 1, 2); this.screen.position.set(0, 1.3, .6); this.screen.target.position.set(0, 1.45, -8); this.screen.userData.base = 230; sc.add(this.screen, this.screen.target);
    this.redRim = new THREE.SpotLight(0xff3a2a, 0, 25, .07, .9, 1.8); this.redRim.position.set(4.5, 3.4, -12); this.redRim.target.position.set(0, 1.7, -6.8); this.redRim.userData.base = 70; sc.add(this.redRim, this.redRim.target);
    this.amb = new THREE.HemisphereLight(0x1b2233, 0x000000, .0); sc.add(this.amb);
    // GALAKTYKA
    this.gx = createGalaxy(); sc.add(this.gx.root);
    // PLANETY
    this.pl = createPlanets(.046); sc.add(this.pl.group);
    // pierścień dotyku
    this.ring = new THREE.Mesh(new THREE.RingGeometry(.97, 1, 128), new THREE.MeshBasicMaterial({ color: 0xcfdcff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, fog: false }));
    this.ring.rotation.x = -Math.PI / 2; sc.add(this.ring);
    // POSTPROCESSING
    this.composer = new EffectComposer(r);
    this.composer.addPass(new RenderPass(sc, cam));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), .45, .5, 1.0); this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
    this.final = new ShaderPass(FINAL); this.composer.addPass(this.final);
    this.resize(); this._onResize = () => this.resize(); addEventListener('resize', this._onResize);
    this._onLost = e => { e.preventDefault(); this.pause(); this.readyState = 0; this.dispatchEvent(new Event('error')); }; canvas.addEventListener('webglcontextlost', this._onLost);
    this.render(0); this.readyState = 4;
  }
  resize() {
    const w = this.canvas.clientWidth || innerWidth, h = this.canvas.clientHeight || innerHeight, dpr = Math.min(devicePixelRatio || 1, this._cap);
    this.renderer.setPixelRatio(dpr); this.renderer.setSize(w, h, false); this.composer.setPixelRatio(dpr); this.composer.setSize(w, h);
    this.camera.aspect = w / h; this.camera.fov = w / h < 1.5 ? 38 : 30; this.camera.updateProjectionMatrix();
    this.final.uniforms.uRes.value.set(w * dpr, h * dpr);
    const px = h * dpr / (2 * Math.tan(this.camera.fov * Math.PI / 360)); for (const it of this.pl.items) it.mat.uniforms.uPx.value = px; if (this.gx) this.gx.U.uPx.value = px;
    this.final.uniforms.uBars.value = w / h > 1.5 ? .085 : 0;
    if (!this._playing) this.render(this._t);
  }
  // ---------- klatka ----------
  update(t) {
    const F = this.fig, P = this.pl;
    // postacie: pozycja + chód
    const midZ = { v: 0 };
    for (const k of ['mid', 'left', 'right']) {
      const tr = this.track[k](t), st = START[k];
      F[k].group.position.set(st[0], 0, st[1] + tr.d); if (k === 'mid') midZ.v = st[1] + tr.d;
      const lookT = k === 'mid' ? 0 : smooth(win(t, 8.0, 9.4));
      const look = k === 'mid' ? [.42 * smooth(win(t, 8.2, 9.6)) + .08 * smooth(win(t, 6.6, 7.8)), 0] : [.3 * lookT, (k === 'left' ? -.32 : .32) * lookT];
      pose(F[k], { phase: tr.phase, s: tr.s, t, lean: k === 'mid' ? .14 * smooth(win(t, TL.reach[0], TL.reach[1])) : 0, look, seed: k === 'mid' ? 0 : k === 'left' ? 1.7 : 3.1 });
      F[k].group.rotation.y = k === 'mid' ? 0 : (k === 'left' ? .05 : -.05) * (1 - tr.s * .5);
    }
    // planety: pojawienie się w rzędzie, potem zbliżenie pod dłoń
    const cx = START.mid[0] - .04, cz = midZ.v + .5, cy = 1.2;
    const kIn = win(t, ...TL.planetsIn), kG = ease(win(t, ...TL.gather));
    const touch = smooth(win(t, TL.touch - .15, TL.touch + .25)), pulse = Math.exp(-Math.max(0, t - TL.touch) * 2.2) * (t > TL.touch ? 1 : 0);
    const spin = t * .55 * (1 - .6 * touch);
    P.items.forEach((it, i) => {
      const row = new THREE.Vector3(cx + (i - 1) * .3, cy + .1 + Math.sin(t * 1.3 + i) * .012, cz + .08);
      const a = spin + i * 2.094, tri = new THREE.Vector3(cx + Math.sin(a) * .06, cy, cz + Math.cos(a) * .06);
      it.node.position.lerpVectors(row, tri, kG);
      it.mat.uniforms.uK.value = kIn; it.mat.uniforms.uTime.value = t; it.mat.uniforms.uPulse.value = pulse + touch * .25;
      it.mat.uniforms.uOpacity.value = 1;
      it.glow.material.opacity = smooth(kIn) * (.05 + touch * .06 + pulse * .14);
    });
    P.light.position.set(cx, cy - .22, cz + .12); P.light.intensity = smooth(kIn) * .12 + touch * .3 + pulse * .9;
    this.ring.position.set(cx, cy, cz); const rk = clamp((t - TL.touch) / 1.3); this.ring.scale.setScalar(.04 + Math.pow(rk, .7) * .55); this.ring.material.opacity = t > TL.touch ? (1 - rk) * .22 : 0;
    // ręka środkowej postaci kładzie się na planetach
    const wR = ease(win(t, ...TL.reach));
    if (wR > 0) {
      const touchP = new THREE.Vector3(cx, cy + P.R + .004 - .006 * touch, cz);
      const fingers = new THREE.Vector3(0, -.18, 1).normalize();
      const hover = (1 - smooth(win(t, TL.reach[1] - .5, TL.reach[1]))) * .1;
      const wrist = touchP.clone().addScaledVector(fingers, -.075).add(new THREE.Vector3(.0, .028 + hover, 0));
      reach(F.mid, 'R', wrist, wR, 0);
    }
    for (const k in F) F[k].group.updateMatrixWorld(true);
    // światła
    const f = smooth(win(t, ...TL.fadeIn)), lights = smooth(win(t, .3, 3.2));
    this.backL.intensity = this.backL.userData.base * lights; this.backR.intensity = this.backR.userData.base * lights;
    this.top.intensity = this.top.userData.base * smooth(win(t, 2.5, 6));
    this.screen.intensity = this.screen.userData.base * smooth(win(t, 1.5, 6.5));
    this.redRim.intensity = this.redRim.userData.base * smooth(win(t, 3.5, 6.5));
    this.amb.intensity = .25 * lights;
    if (this.debugLight) { this.amb.intensity = 3; this.amb.color.set(0xffffff); this.amb.groundColor.set(0x888888); this.scene.fog.density = 0; }
    const G = this.gx; G.U.uB.value = smooth(win(t, .2, 3.4)); G.U.uT.value = t; G.gal.rotation.y = .18 + t * .006;
    G.neb.forEach(n => n.material.opacity = n.userData.op * smooth(win(t, .6, 4.2)));
    this.scene.fog.density = lerp(.07, .035, smooth(win(t, 0, 7)));
    // kamera: widz siedzący przed ekranem; lekki oddech, potem najazd na dłoń i planety
    const cam = this.camera, k = ease(win(t, ...TL.push));
    const base = new THREE.Vector3(Math.sin(t * .31) * .025, 1.12 + Math.sin(t * .47) * .012, 0);
    const near = new THREE.Vector3(cx + .12, cy + .06, cz + 1.75);
    cam.position.lerpVectors(base, near, k);
    const look0 = new THREE.Vector3(0, 1.55, -10), look1 = new THREE.Vector3(cx, cy + .2, cz - .1);
    cam.lookAt(new THREE.Vector3().lerpVectors(look0, look1, smooth(win(t, TL.push[0] - .4, TL.push[1] - .6))));
    if (this.debugCam) { cam.position.fromArray(this.debugCam[0]); cam.lookAt(new THREE.Vector3().fromArray(this.debugCam[1])); }
    cam.fov = lerp(innerWidth / innerHeight < 1.5 ? 38 : 30, 36, k); cam.updateProjectionMatrix();
    // post
    this.final.uniforms.uTime.value = t; this.final.uniforms.uFade.value = f;
    this.final.uniforms.uFlash.value = Math.pow(win(t, ...TL.flash), 2.2);
    this.bloom.strength = .4 + touch * .12 + pulse * .25;
    this.final.uniforms.uBars.value = (innerWidth / innerHeight > 1.5 ? .085 : 0) * (1 - smooth(win(t, TL.push[0], TL.push[1])));
  }
  render(t) { this.update(t); this.composer.render(); }
  // ---------- API jak <video> ----------
  get currentTime() { return this._t; }
  set currentTime(v) { this._t = clamp(v, 0, this.duration); if (!this._playing) this.render(this._t); }
  seek(t) { this.currentTime = t; }
  play() {
    if (this._playing) return Promise.resolve(); this._playing = true; this.paused = false; let last = performance.now();
    const loop = now => { if (!this._playing) return; const dt = Math.min((now - last) / 1000, .1); last = now; this._t = Math.min(this.duration, this._t + dt); this.render(this._t);
      if (this._t >= this.duration) { this._playing = false; this.paused = true; this.dispatchEvent(new Event('ended')); return; } this._raf = requestAnimationFrame(loop); };
    this._raf = requestAnimationFrame(loop); return Promise.resolve();
  }
  pause() { this._playing = false; this.paused = true; cancelAnimationFrame(this._raf); }
  dispose({ keepContext = false } = {}) {
    this.pause(); removeEventListener('resize', this._onResize); this.canvas.removeEventListener('webglcontextlost', this._onLost);
    this.scene.traverse(o => { o.geometry?.dispose?.(); const m = o.material; (Array.isArray(m) ? m : m ? [m] : []).forEach(x => { for (const k in x) x[k]?.isTexture && x[k].dispose(); if (x.uniforms) for (const k in x.uniforms) x.uniforms[k]?.value?.isTexture && x.uniforms[k].value.dispose(); x.dispose(); }); if (o.isLight) o.shadow?.map?.dispose?.(); });
    this.refl?.getRenderTarget?.().dispose();
    this.bloom?.dispose?.(); this.final?.dispose?.(); for (const p of this.composer.passes) p.dispose?.(); this.composer.dispose?.();
    this.scene.background = null; this.renderer.renderLists?.dispose?.(); this.renderer.dispose();
    if (!keepContext) this.renderer.forceContextLoss();
    this.readyState = 0;
  }
}
