// Three procedural 3D towers on one platform with a magic circle (three.js). Authored geometry inspired by the reference images -
// no reconstruction from a photo. Precision: slender observatory, crystal, rotating measurement rings. Dyscypline: massive citadel,
// buttresses, rune rings, energy gate. Profits: vault tower, gold bands, energy orb with orbiting particles, emerald crystals.
// Performance: 5 lights, no shadows, instancing for repeated parts and particles, adaptive pixel ratio, render loop paused when the
// canvas is hidden or off-screen, every GPU resource released in dispose(). The scene only reports hover / selection - navigation
// is done by the page; nothing here talks to the bot.
import * as THREE from "three";
import type { TowerId } from "./assets";

export type Anchor = { x: number; y: number; top: number; visible: boolean };
export type SceneOpts = {
  onHover: (id: TowerId | null) => void;
  onSelect: (id: TowerId) => void;
  onAnchors: (a: Record<TowerId, Anchor>) => void;
  /** Called when the scene stays below MIN_FPS even at the lowest resolution (software rendering without a GPU): the menu then
   *  switches to the buttons without 3D so the bot on the same computer keeps its CPU. Not called when 3D is forced. */
  onTooSlow?: (fps: number) => void;
  reduced: boolean;
};

const MIN_FPS = 5;

const ACCENT: Record<TowerId, number> = { precision: 0x3fe6ff, dyscypline: 0xb46bff, profits: 0xffcf5c };
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function canvasTex(size: number, draw: (g: CanvasRenderingContext2D, s: number) => void, srgb = true): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  draw(c.getContext("2d")!, size);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function stoneTexture(): THREE.CanvasTexture {
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const t = canvasTex(256, (g, s) => {
    g.fillStyle = "#3a3f52";
    g.fillRect(0, 0, s, s);
    for (let i = 0; i < 2600; i++) {
      const v = 40 + rnd() * 50;
      g.fillStyle = `rgba(${v},${v + 4},${v + 18},${0.25 + rnd() * 0.3})`;
      g.fillRect(rnd() * s, rnd() * s, 1 + rnd() * 3, 1 + rnd() * 3);
    }
    g.strokeStyle = "rgba(10,10,20,0.85)";
    g.lineWidth = 2;
    const rows = 8;
    for (let r = 0; r <= rows; r++) {
      const y = (r * s) / rows;
      g.beginPath(); g.moveTo(0, y); g.lineTo(s, y); g.stroke();
      const off = r % 2 ? s / 8 : 0;
      for (let k = 0; k < 4; k++) {
        const x = off + (k * s) / 4;
        g.beginPath(); g.moveTo(x, y); g.lineTo(x, y + s / rows); g.stroke();
      }
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

function runeTexture(color: string): THREE.CanvasTexture {
  let seed = 3;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  return canvasTex(1024, (g, s) => {
    const c = s / 2;
    g.clearRect(0, 0, s, s);
    g.strokeStyle = color;
    g.shadowColor = color;
    g.shadowBlur = 12;
    for (const [r, w] of [[0.48, 3], [0.44, 1.5], [0.30, 2.5], [0.27, 1], [0.12, 2]] as const) {
      g.lineWidth = w;
      g.beginPath(); g.arc(c, c, r * s, 0, Math.PI * 2); g.stroke();
    }
    g.lineWidth = 1.6;
    for (let k = 0; k < 2; k++) {                                  // two overlapping triangles (hexagram)
      g.beginPath();
      for (let i = 0; i <= 3; i++) {
        const a = -Math.PI / 2 + k * Math.PI + (i * 2 * Math.PI) / 3;
        const x = c + Math.cos(a) * 0.43 * s, y = c + Math.sin(a) * 0.43 * s;
        if (i) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.stroke();
    }
    g.font = `${Math.round(s * 0.03)}px serif`;
    g.fillStyle = color;
    const glyphs = "ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ";
    for (let i = 0; i < 48; i++) {                                  // rune band between the two outer circles
      const a = (i / 48) * Math.PI * 2;
      g.save(); g.translate(c + Math.cos(a) * 0.46 * s, c + Math.sin(a) * 0.46 * s); g.rotate(a + Math.PI / 2);
      g.fillText(glyphs[Math.floor(rnd() * glyphs.length)], -s * 0.01, s * 0.01);
      g.restore();
    }
    for (let i = 0; i < 24; i++) {                                  // inner ticks
      const a = (i / 24) * Math.PI * 2;
      g.beginPath(); g.moveTo(c + Math.cos(a) * 0.30 * s, c + Math.sin(a) * 0.30 * s);
      g.lineTo(c + Math.cos(a) * (i % 3 ? 0.33 : 0.36) * s, c + Math.sin(a) * (i % 3 ? 0.33 : 0.36) * s); g.stroke();
    }
  });
}

type Tower = {
  id: TowerId;
  group: THREE.Group;
  glow: THREE.Material[];                  // emissive materials boosted on hover
  light: THREE.PointLight;
  spin: { obj: THREE.Object3D; axis: "x" | "y" | "z"; speed: number }[];
  anchorTop: THREE.Vector3;
  hover: number;                           // 0..1 smoothed
  baseLight: number;
  update?: (t: number, dt: number, h: number) => void;
};

export class TowerScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120);
  private towers = new Map<TowerId, Tower>();
  private hitList: THREE.Object3D[] = [];
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2(10, 10);
  private pointerIn = false;
  private hovered: TowerId | null = null;
  // reduced motion: a static scene rendered only when something changed (hover, focus, resize) - no continuous animation and
  // almost no CPU / GPU work while the menu is open
  private dirty = 3;
  private pointerMoved = false;
  private focused: TowerId | null = null;
  private raf = 0;
  private running = false;
  private visible = true;
  private last = performance.now();
  private t0 = performance.now();
  private disposed = false;
  private camBase = new THREE.Vector3();
  private lookBase = new THREE.Vector3(0, 3.3, 0);
  private camAnim: { from: THREE.Vector3; to: THREE.Vector3; lookFrom: THREE.Vector3; lookTo: THREE.Vector3; t0: number; dur: number; done: () => void } | null = null;
  private look = new THREE.Vector3(0, 3.3, 0);
  private dust!: THREE.Points;
  private circle!: THREE.Mesh;
  private frameMs: number[] = [];
  private slowWindows = 0;
  private maxDpr: number;
  private dpr: number;
  private io: IntersectionObserver | null = null;
  private lastAnchors = "";
  private textures: THREE.Texture[] = [];
  readonly stats = { fps: 0, dpr: 1, frames: 0 };

  constructor(private canvas: HTMLCanvasElement, private host: HTMLElement, private opts: SceneOpts) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.45;
    this.maxDpr = Math.min(window.devicePixelRatio || 1, 1.75);
    this.dpr = Math.min(this.maxDpr, 1.5);
    this.renderer.setPixelRatio(this.dpr);
    this.scene.fog = new THREE.FogExp2(0x080617, 0.028);
    this.build();
    this.resize();
    canvas.addEventListener("pointermove", this.onMove);
    canvas.addEventListener("pointerleave", this.onLeave);
    canvas.addEventListener("click", this.onClick);
    canvas.addEventListener("webglcontextlost", this.onLost);
    window.addEventListener("resize", this.resize);
    document.addEventListener("visibilitychange", this.onVisibility);
    this.io = new IntersectionObserver((e) => { this.visible = e[0]?.isIntersecting ?? true; this.syncRun(); });
    this.io.observe(host);
    this.syncRun();
  }

  // ------------------------------------------------------------------ construction
  private build() {
    const stoneMap = stoneTexture();
    this.textures.push(stoneMap);
    const stone = (rep: [number, number], tint = 0xa9aecb) => {
      const m = stoneMap.clone();
      m.repeat.set(rep[0], rep[1]);
      m.needsUpdate = true;
      this.textures.push(m);
      return new THREE.MeshStandardMaterial({ color: tint, map: m, bumpMap: m, bumpScale: 0.035, roughness: 0.88, metalness: 0.08 });
    };
    const darkMetal = new THREE.MeshStandardMaterial({ color: 0x1b1d2c, roughness: 0.45, metalness: 0.75 });

    this.scene.add(new THREE.HemisphereLight(0x8c80ff, 0x120a24, 1.25));
    const moon = new THREE.DirectionalLight(0xd2d6ff, 2.1);
    moon.position.set(-7, 12, 9);
    this.scene.add(moon);
    const rim = new THREE.DirectionalLight(0xa070ff, 1.6);              // back light: violet rim on the silhouettes
    rim.position.set(4, 6, -10);
    this.scene.add(rim);

    // platform + magic circle
    const plat = new THREE.Mesh(new THREE.CylinderGeometry(7.3, 7.8, 0.7, 72), stone([8, 1], 0x8a8fae));
    plat.position.y = -0.36;
    this.scene.add(plat);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(7.3, 0.05, 8, 120), new THREE.MeshStandardMaterial({ color: 0x2a1a55, emissive: 0x9b5cff, emissiveIntensity: 1.4 }));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.0;
    this.scene.add(ring);
    const runes = runeTexture("#b98bff");
    this.textures.push(runes);
    this.circle = new THREE.Mesh(new THREE.PlaneGeometry(14, 14),
      new THREE.MeshBasicMaterial({ map: runes, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false, color: 0xc7a8ff }));
    this.circle.rotation.x = -Math.PI / 2;
    this.circle.position.y = 0.02;
    this.scene.add(this.circle);

    this.addTower(this.buildPrecision(stone, darkMetal), -4.5, 0.7);
    this.addTower(this.buildDyscypline(stone, darkMetal, runes), 0, -0.8);
    this.addTower(this.buildProfits(stone), 4.5, 0.7);

    // dust / embers (one Points draw call)
    const n = 700;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const palette = [new THREE.Color(0xb46bff), new THREE.Color(0x3fe6ff), new THREE.Color(0x2fe6a0), new THREE.Color(0xffcf5c)];
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 22;
      pos[i * 3 + 1] = Math.random() * 11;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 12;
      const c = palette[i % palette.length];
      col.set([c.r, c.g, c.b], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    this.dust = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.055, vertexColors: true, transparent: true, opacity: 0.75,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    this.scene.add(this.dust);
  }

  private addTower(t: Tower, x: number, z: number) {
    t.group.position.set(x, 0, z);
    t.anchorTop.add(t.group.position);
    this.scene.add(t.group);
    this.towers.set(t.id, t);
    t.group.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.userData.tower = t.id;
        this.hitList.push(o);
      }
    });
  }

  private emissive(color: number, intensity: number, base = 0x10101c): THREE.MeshStandardMaterial {
    return new THREE.MeshStandardMaterial({ color: base, emissive: color, emissiveIntensity: intensity, roughness: 0.4, metalness: 0.2 });
  }

  private buildPrecision(stone: (r: [number, number], t?: number) => THREE.Material, darkMetal: THREE.Material): Tower {
    const gr = new THREE.Group();
    const cyan = ACCENT.precision;
    const glow: THREE.Material[] = [];
    const base = new THREE.Mesh(new THREE.CylinderGeometry(1.15, 1.4, 0.55, 28), stone([4, 1]));
    base.position.y = 0.27;
    gr.add(base);
    const prof = [[0.98, 0], [1.0, 0.25], [0.86, 0.5], [0.8, 1.6], [0.72, 2.8], [0.66, 4.0], [0.6, 5.0], [0.78, 5.15], [0.8, 5.35], [0.0, 5.36]]
      .map(([r, y]) => new THREE.Vector2(r, y));
    const shaft = new THREE.Mesh(new THREE.LatheGeometry(prof, 32), stone([5, 6], 0xa4abd2));
    shaft.position.y = 0.5;
    gr.add(shaft);
    for (const y of [1.9, 3.2, 4.5]) {
      const band = new THREE.Mesh(new THREE.TorusGeometry(0.76 - (y - 1.9) * 0.05, 0.045, 8, 48), darkMetal);
      band.rotation.x = Math.PI / 2;
      band.position.y = y;
      gr.add(band);
    }
    const winMat = this.emissive(cyan, 1.2, 0x062a33);
    glow.push(winMat);
    for (let i = 0; i < 10; i++) {                                  // spiral of windows
      const a = i * 1.15, y = 1.1 + i * 0.42, r = 0.83 - i * 0.022;
      const w = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.26, 0.05), winMat);
      w.position.set(Math.cos(a) * r, y, Math.sin(a) * r);
      w.lookAt(0, y, 0);
      gr.add(w);
    }
    const dome = new THREE.Mesh(new THREE.SphereGeometry(0.66, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0x9fdcff, transparent: true, opacity: 0.32, emissive: cyan, emissiveIntensity: 0.25, roughness: 0.1, metalness: 0.3 }));
    dome.position.y = 5.86;
    gr.add(dome);
    glow.push(dome.material as THREE.Material);
    const crystalMat = new THREE.MeshStandardMaterial({ color: 0xd4f8ff, emissive: cyan, emissiveIntensity: 2.6, roughness: 0.15, metalness: 0.1, flatShading: true });
    glow.push(crystalMat);
    const crystal = new THREE.Mesh(new THREE.OctahedronGeometry(0.34, 0), crystalMat);
    crystal.scale.set(1, 1.9, 1);
    crystal.position.y = 7.0;
    gr.add(crystal);
    const spin: Tower["spin"] = [{ obj: crystal, axis: "y", speed: 0.6 }];
    const ringMat = this.emissive(cyan, 1.6, 0x0a1622);
    const ringMat2 = this.emissive(0x8a7bff, 1.6, 0x100a22);
    glow.push(ringMat, ringMat2);
    [[0.85, ringMat, 0.0], [1.08, ringMat2, 0.9], [1.3, ringMat, -0.6]].forEach(([r, m, tilt], i) => {
      const holder = new THREE.Group();
      holder.position.y = 7.0;
      holder.rotation.x = Math.PI / 2 + (tilt as number);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(r as number, 0.018, 6, 96), m as THREE.Material);
      holder.add(ring);
      if (i === 0) {                                                 // measurement ticks (one instanced draw call)
        const ticks = new THREE.InstancedMesh(new THREE.BoxGeometry(0.02, 0.09, 0.02), m as THREE.Material, 48);
        const mtx = new THREE.Matrix4();
        for (let k = 0; k < 48; k++) {
          const a = (k / 48) * Math.PI * 2;
          mtx.makeRotationZ(a);
          mtx.setPosition(Math.cos(a) * (r as number), Math.sin(a) * (r as number), 0);
          ticks.setMatrixAt(k, mtx);
        }
        holder.add(ticks);
      }
      gr.add(holder);
      spin.push({ obj: holder, axis: "z", speed: (i % 2 ? -0.5 : 0.35) * (1 + i * 0.3) });
    });
    const needle = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.9, 8), darkMetal);
    needle.position.y = 6.35;
    gr.add(needle);
    const light = new THREE.PointLight(cyan, 3.0, 9, 1.6);
    light.position.y = 7.0;
    gr.add(light);
    return { id: "precision", group: gr, glow, light, spin, anchorTop: new THREE.Vector3(0, 8.4, 0), hover: 0, baseLight: 3.0 };
  }

  private buildDyscypline(stone: (r: [number, number], t?: number) => THREE.Material, darkMetal: THREE.Material, runes: THREE.Texture): Tower {
    const gr = new THREE.Group();
    const am = ACCENT.dyscypline, em = 0x2fe6a0;
    const glow: THREE.Material[] = [];
    const plinth = new THREE.Mesh(new THREE.CylinderGeometry(2.05, 2.35, 0.65, 8), stone([6, 1], 0x7c8098));
    plinth.position.y = 0.32;
    gr.add(plinth);
    const keep = new THREE.Mesh(new THREE.CylinderGeometry(1.35, 1.62, 4.3, 8), stone([6, 5], 0xa0a5c4));
    keep.position.y = 2.8;
    gr.add(keep);
    for (let i = 0; i < 8; i++) {                                    // buttresses on the octagon faces
      const a = (i / 8) * Math.PI * 2 + Math.PI / 8;
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.34, 2.9, 0.62), stone([1, 3], 0x777b94));
      b.position.set(Math.cos(a) * 1.72, 1.95, Math.sin(a) * 1.72);
      b.lookAt(0, 1.95, 0);
      b.rotateX(-0.12);
      gr.add(b);
    }
    const upper = new THREE.Mesh(new THREE.CylinderGeometry(1.02, 1.22, 1.7, 8), stone([4, 2], 0x8d92b0));
    upper.position.y = 5.8;
    gr.add(upper);
    const merlonGeo = new THREE.BoxGeometry(0.26, 0.3, 0.26);
    for (const [y, r, n] of [[5.08, 1.42, 24], [6.78, 1.08, 18]] as const) {    // crenellations, instanced
      const crown = new THREE.InstancedMesh(merlonGeo, stone([1, 1], 0x8d92b0), n);
      const mtx = new THREE.Matrix4();
      for (let k = 0; k < n; k++) {
        const a = (k / n) * Math.PI * 2;
        mtx.makeRotationY(-a);
        mtx.setPosition(Math.cos(a) * r, y, Math.sin(a) * r);
        crown.setMatrixAt(k, mtx);
      }
      gr.add(crown);
    }
    const slate = new THREE.MeshStandardMaterial({ color: 0x241d3a, roughness: 0.55, metalness: 0.35 });
    for (let i = 0; i < 4; i++) {                                    // corner turrets + spires
      const a = (i / 4) * Math.PI * 2 + Math.PI / 4;
      const tur = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.28, 1.1, 10), stone([1, 1]));
      tur.position.set(Math.cos(a) * 1.15, 6.75, Math.sin(a) * 1.15);
      gr.add(tur);
      const sp = new THREE.Mesh(new THREE.ConeGeometry(0.3, 1.3, 10), slate);
      sp.position.set(Math.cos(a) * 1.15, 7.95, Math.sin(a) * 1.15);
      gr.add(sp);
    }
    const spire = new THREE.Mesh(new THREE.ConeGeometry(0.72, 2.9, 8), slate);
    spire.position.y = 8.1;
    gr.add(spire);
    const tipMat = this.emissive(am, 3.0);
    glow.push(tipMat);
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 12), tipMat);
    tip.position.y = 9.65;
    gr.add(tip);
    // energy gate: stone arch + animated portal surface
    const archMat = this.emissive(am, 1.2, 0x2a2240);
    glow.push(archMat);
    const arch = new THREE.Mesh(new THREE.TorusGeometry(0.72, 0.13, 10, 32, Math.PI), archMat);
    arch.position.set(0, 1.55, 1.63);
    gr.add(arch);
    const portalMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uBoost: { value: 0 }, uA: { value: new THREE.Color(am) }, uB: { value: new THREE.Color(em) } },
      vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: `uniform float uTime; uniform float uBoost; uniform vec3 uA; uniform vec3 uB; varying vec2 vUv;
        void main(){ vec2 p = vUv*2.0-1.0; float r = length(p); float a = atan(p.y,p.x);
          float swirl = 0.5+0.5*sin(a*3.0 + r*9.0 - uTime*2.2);
          vec3 col = mix(uA, uB, swirl);
          float edge = smoothstep(1.0, 0.7, r);
          gl_FragColor = vec4(col*(0.55+0.9*uBoost)*(0.6+0.6*swirl), edge*(0.7+0.3*uBoost)); }`,
    });
    const portal = new THREE.Mesh(new THREE.CircleGeometry(0.62, 40), portalMat);
    portal.position.set(0, 1.0, 1.66);
    portal.scale.set(1, 1.55, 1);
    gr.add(portal);
    const gateFrame = new THREE.Mesh(new THREE.BoxGeometry(1.7, 2.1, 0.12), stone([1, 1], 0x6a6e86));
    gateFrame.position.set(0, 1.05, 1.56);
    gr.add(gateFrame);
    // rune rings around the keep (additive planes)
    const spin: Tower["spin"] = [];
    for (const [y, r, color, sp] of [[2.2, 2.35, am, 0.18], [4.25, 1.95, em, -0.26]] as const) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(r - 0.22, r, 96, 1),
        new THREE.MeshBasicMaterial({ map: runes, color, transparent: true, opacity: 0.85, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = y;
      gr.add(ring);
      glow.push(ring.material as THREE.Material);
      spin.push({ obj: ring, axis: "z", speed: sp });
    }
    const winMat = this.emissive(em, 0.9, 0x04261a);
    glow.push(winMat);
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      const w = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.34, 0.05), winMat);
      w.position.set(Math.cos(a) * 1.07, 5.9, Math.sin(a) * 1.07);
      w.lookAt(0, 5.9, 0);
      gr.add(w);
    }
    const light = new THREE.PointLight(am, 3.2, 10, 1.6);
    light.position.set(0, 1.6, 2.6);
    gr.add(light);
    const t: Tower = { id: "dyscypline", group: gr, glow, light, spin, anchorTop: new THREE.Vector3(0, 10.1, 0), hover: 0, baseLight: 3.2 };
    t.update = (time, _dt, h) => { portalMat.uniforms.uTime.value = time; portalMat.uniforms.uBoost.value = h; };
    void darkMetal;
    return t;
  }

  private buildProfits(stone: (r: [number, number], t?: number) => THREE.Material): Tower {
    const gr = new THREE.Group();
    const gold = ACCENT.profits, em = 0x2fe6a0;
    const glow: THREE.Material[] = [];
    const goldMat = new THREE.MeshStandardMaterial({ color: 0xd4a84a, roughness: 0.32, metalness: 1.0, emissive: 0x3a2808, emissiveIntensity: 0.6 });
    glow.push(goldMat);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(1.3, 1.5, 0.55, 28), stone([4, 1]));
    base.position.y = 0.27;
    gr.add(base);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.92, 1.12, 3.9, 28), stone([5, 5], 0xaaa7bc));
    shaft.position.y = 2.5;
    gr.add(shaft);
    for (const y of [1.0, 2.5, 4.0]) {
      const band = new THREE.Mesh(new THREE.TorusGeometry(1.08 - (y - 1) * 0.045, 0.07, 10, 56), goldMat);
      band.rotation.x = Math.PI / 2;
      band.position.y = y;
      gr.add(band);
    }
    const door = new THREE.Mesh(new THREE.CircleGeometry(0.42, 32), goldMat);
    door.position.set(0, 1.55, 1.07);
    gr.add(door);
    const doorCore = new THREE.Mesh(new THREE.CircleGeometry(0.14, 24), this.emissive(em, 2.4));
    doorCore.position.set(0, 1.55, 1.085);
    gr.add(doorCore);
    glow.push(doorCore.material as THREE.Material);
    const crown = new THREE.Mesh(new THREE.CylinderGeometry(1.22, 0.95, 0.42, 28), goldMat);
    crown.position.y = 4.65;
    gr.add(crown);
    const spikes = new THREE.InstancedMesh(new THREE.ConeGeometry(0.09, 0.5, 8), goldMat, 12);
    const mtx = new THREE.Matrix4();
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2;
      mtx.makeTranslation(Math.cos(a) * 1.12, 5.08, Math.sin(a) * 1.12);
      spikes.setMatrixAt(k, mtx);
    }
    gr.add(spikes);
    const orbMat = new THREE.MeshStandardMaterial({ color: 0xfff1c8, emissive: gold, emissiveIntensity: 1.6, transparent: true, opacity: 0.55, roughness: 0.1 });
    glow.push(orbMat);
    const orb = new THREE.Mesh(new THREE.SphereGeometry(0.78, 40, 28), orbMat);
    orb.position.y = 5.95;
    gr.add(orb);
    const coreMat = this.emissive(em, 3.2, 0x0a2016);
    glow.push(coreMat);
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.3, 1), coreMat);
    core.position.y = 5.95;
    gr.add(core);
    // orbiting particles (instanced)
    const n = 64;
    const motes = new THREE.InstancedMesh(new THREE.SphereGeometry(0.045, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff }), n);
    const c1 = new THREE.Color(gold), c2 = new THREE.Color(em);
    const orbit = Array.from({ length: n }, (_, i) => ({ r: 1.0 + (i % 4) * 0.18, tilt: (i % 7) * 0.45, ph: (i / n) * Math.PI * 2, sp: 0.6 + (i % 5) * 0.12 }));
    orbit.forEach((_, i) => motes.setColorAt(i, i % 3 ? c1 : c2));
    gr.add(motes);
    // emerald crystals at the foot
    const crystMat = new THREE.MeshStandardMaterial({ color: 0x9effd0, emissive: em, emissiveIntensity: 1.5, roughness: 0.15, flatShading: true });
    glow.push(crystMat);
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + 0.3;
      const cr = new THREE.Mesh(new THREE.OctahedronGeometry(0.2, 0), crystMat);
      cr.scale.set(1, 2.4 + (i % 3) * 0.6, 1);
      cr.position.set(Math.cos(a) * 1.65, 0.55, Math.sin(a) * 1.65);
      cr.rotation.z = (i % 2 ? 1 : -1) * 0.25;
      gr.add(cr);
    }
    const light = new THREE.PointLight(gold, 3.0, 9, 1.6);
    light.position.y = 5.95;
    gr.add(light);
    const tmp = new THREE.Object3D();
    const t: Tower = { id: "profits", group: gr, glow, light, spin: [{ obj: core, axis: "y", speed: 0.8 }], anchorTop: new THREE.Vector3(0, 7.4, 0), hover: 0, baseLight: 3.0 };
    t.update = (time, _dt, h) => {
      for (let i = 0; i < n; i++) {
        const o = orbit[i], a = o.ph + time * o.sp * (1 + h * 1.5);
        tmp.position.set(Math.cos(a) * o.r, 5.95 + Math.sin(a) * Math.sin(o.tilt) * o.r * 0.5, Math.sin(a) * o.r * Math.cos(o.tilt));
        tmp.updateMatrix();
        motes.setMatrixAt(i, tmp.matrix);
      }
      motes.instanceMatrix.needsUpdate = true;
    };
    return t;
  }

  // ------------------------------------------------------------------ interaction
  private onMove = (e: PointerEvent) => {
    const r = this.canvas.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.pointerIn = e.pointerType !== "touch";
    this.pointerMoved = true;
  };

  private onLeave = () => {
    this.pointerIn = false;
    this.setHovered(this.focused);
  };

  private onClick = (e: MouseEvent) => {
    const r = this.canvas.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const id = this.pick();
    if (id) this.opts.onSelect(id);                                 // touch: one tap opens the tower (no hover needed)
  };

  private onLost = (e: Event) => {
    e.preventDefault();
    this.stop();
    this.canvas.dispatchEvent(new CustomEvent("wz-webgl-lost", { bubbles: true }));
  };

  private onVisibility = () => this.syncRun();

  private pick(): TowerId | null {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.hitList, false)[0];
    return (hit?.object.userData.tower as TowerId) ?? null;
  }

  private setHovered(id: TowerId | null) {
    if (id === this.hovered) return;
    this.hovered = id;
    this.dirty = Math.max(this.dirty, 1);
    this.canvas.style.cursor = id ? "pointer" : "default";
    this.opts.onHover(id);
  }

  /** Keyboard focus of the HTML button of a tower = the same highlight as mouse hover. */
  setFocus(id: TowerId | null) {
    this.focused = id;
    if (!this.pointerIn) this.setHovered(id);
  }

  /** Short camera move towards the tower (~550 ms); resolves when done (immediately with reduced motion). */
  select(id: TowerId): Promise<void> {
    const t = this.towers.get(id);
    if (!t || this.opts.reduced || !this.running) return Promise.resolve();
    return new Promise((done) => {
      const target = t.group.position.clone();
      this.camAnim = {
        from: this.camera.position.clone(), to: new THREE.Vector3(target.x * 0.75, 4.2, target.z + 6.0),
        lookFrom: this.look.clone(), lookTo: new THREE.Vector3(target.x, 4.0, target.z), t0: performance.now(), dur: 560, done,
      };
    });
  }

  // ------------------------------------------------------------------ loop
  private syncRun() {
    const should = !this.disposed && this.visible && document.visibilityState === "visible";
    if (should && !this.running) {
      this.running = true;
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.frame);
    } else if (!should && this.running) {
      this.stop();
    }
  }

  private stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  resize = () => {
    const w = Math.max(1, this.host.clientWidth), h = Math.max(1, this.host.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // keep the three towers (with their spires) and the platform in view at any aspect. On wide screens the canvas spans the whole
    // menu behind the two map panels, so only the middle ~64 % of its width is free for the towers.
    const half = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const free = w >= 1000 && w / h > 1.75 ? 0.64 : 1;
    const dist = Math.max(7.9 / (half * this.camera.aspect * free), 6.6 / half) * 1.04;
    this.camBase.set(0, 4.3, dist);
    if (!this.camAnim) {
      this.camera.position.copy(this.camBase);
      this.look.copy(this.lookBase);
      this.camera.lookAt(this.look);
    }
    this.camera.updateProjectionMatrix();
    this.lastAnchors = "";
    this.dirty = Math.max(this.dirty, 2);
  };

  private frame = (now: number) => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    if (this.opts.reduced && !this.camAnim) {
      if (this.pointerIn && this.pointerMoved) {
        this.pointerMoved = false;
        this.setHovered(this.pick() ?? null);
      }
      if (this.dirty <= 0) {
        this.last = now;
        return;
      }
      this.dirty--;
    }
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.frameMs.push(now - this.last);
    this.last = now;
    const time = (now - this.t0) / 1000;
    const motion = this.opts.reduced ? 0.15 : 1;

    if (this.pointerIn && !this.camAnim && !this.opts.reduced) this.setHovered(this.pick() ?? null);
    for (const t of this.towers.values()) {
      const target = this.hovered === t.id ? 1 : 0;
      t.hover = this.opts.reduced ? target : t.hover + (target - t.hover) * Math.min(1, dt * 7);
      const s = 1 + 0.045 * t.hover;
      t.group.scale.setScalar(s);
      t.light.intensity = t.baseLight * (1 + 1.1 * t.hover) * (0.92 + 0.08 * Math.sin(time * 2.1 + t.group.position.x));
      for (const m of t.glow) {
        const mm = m as THREE.MeshStandardMaterial & { userData: { base?: number } };
        if (mm.emissiveIntensity !== undefined) {
          if (mm.userData.base === undefined) mm.userData.base = mm.emissiveIntensity;
          mm.emissiveIntensity = mm.userData.base * (1 + 0.8 * t.hover);
        } else if ((m as THREE.MeshBasicMaterial).opacity !== undefined) {
          const bm = m as THREE.MeshBasicMaterial & { userData: { base?: number } };
          if (bm.userData.base === undefined) bm.userData.base = bm.opacity;
          bm.opacity = Math.min(1, bm.userData.base * (1 + 0.5 * t.hover));
        }
      }
      for (const sp of t.spin) sp.obj.rotation[sp.axis] += sp.speed * dt * motion * (1 + 2.2 * t.hover);
      t.update?.(time * motion, dt, t.hover);
    }
    this.circle.rotation.z += dt * 0.03 * motion;
    const p = this.dust.geometry.getAttribute("position") as THREE.BufferAttribute;
    if (!this.opts.reduced) {
      for (let i = 0; i < p.count; i++) {
        let y = p.getY(i) + dt * (0.18 + (i % 5) * 0.05);
        if (y > 11) y = 0;
        p.setY(i, y);
      }
      p.needsUpdate = true;
    }

    if (this.camAnim) {
      const a = this.camAnim, k = Math.min(1, (now - a.t0) / a.dur), e = ease(k);
      this.camera.position.lerpVectors(a.from, a.to, e);
      this.look.lerpVectors(a.lookFrom, a.lookTo, e);
      if (k >= 1) { this.camAnim = null; a.done(); }
    } else if (!this.opts.reduced) {
      const px = this.pointerIn ? this.pointer.x : 0, py = this.pointerIn ? this.pointer.y : 0;   // gentle parallax of the camera
      this.camera.position.x += (this.camBase.x + px * 0.6 - this.camera.position.x) * Math.min(1, dt * 3);
      this.camera.position.y += (this.camBase.y + py * 0.3 - this.camera.position.y) * Math.min(1, dt * 3);
      this.camera.position.z += (this.camBase.z - this.camera.position.z) * Math.min(1, dt * 3);
      this.look.lerp(this.lookBase, Math.min(1, dt * 3));
    }
    this.camera.lookAt(this.look);
    this.renderer.render(this.scene, this.camera);
    this.stats.frames++;
    this.reportAnchors();
    this.adapt();
  };

  private reportAnchors() {
    const r = this.canvas.getBoundingClientRect();
    const out = {} as Record<TowerId, Anchor>;
    const v = new THREE.Vector3();
    for (const t of this.towers.values()) {
      v.copy(t.group.position).setY(0.05).project(this.camera);
      const x = ((v.x + 1) / 2) * r.width, y = ((1 - v.y) / 2) * r.height;
      v.copy(t.anchorTop).project(this.camera);
      out[t.id] = { x, y, top: ((1 - v.y) / 2) * r.height, visible: v.z < 1 };
    }
    const key = JSON.stringify(out, (_k, val) => (typeof val === "number" ? Math.round(val) : val));
    if (key !== this.lastAnchors) {
      this.lastAnchors = key;
      this.opts.onAnchors(out);
    }
  }

  /** Adaptive quality: lower the render resolution when frames are slow, raise it back when there is headroom. Evaluated every
   *  90 frames or every ~3 s, whichever comes first (a slow machine must not wait 90 slow frames for the first correction). */
  private adapt() {
    const total = this.frameMs.reduce((a, b) => a + b, 0);
    if (this.frameMs.length < 90 && (total < 3000 || this.frameMs.length < 4)) return;
    const ms = this.frameMs.slice(this.frameMs.length > 20 ? 5 : 1);
    this.frameMs = [];
    const avg = ms.reduce((a, b) => a + b, 0) / ms.length;
    this.stats.fps = Math.round((1000 / avg) * 10) / 10;
    let d = this.dpr;
    if (avg > 26 && d > 0.75) d = Math.max(0.75, d - 0.25);
    else if (avg < 13 && d < this.maxDpr) d = Math.min(this.maxDpr, d + 0.25);
    if (d !== this.dpr) {
      this.dpr = d;
      this.renderer.setPixelRatio(d);
      this.resize();
    }
    this.stats.dpr = this.dpr;
    this.host.dataset.fps = String(this.stats.fps);
    this.host.dataset.dpr = String(this.dpr);
    // already at the lowest resolution and still below MIN_FPS twice in a row -> too slow for 3D on this computer
    this.slowWindows = this.stats.fps < MIN_FPS && this.dpr <= 0.75 && d === this.dpr ? this.slowWindows + 1 : 0;
    if (this.slowWindows >= 2 && this.opts.onTooSlow) {
      this.slowWindows = 0;
      this.opts.onTooSlow(this.stats.fps);
    }
  }

  dispose() {
    this.disposed = true;
    this.stop();
    this.io?.disconnect();
    this.canvas.removeEventListener("pointermove", this.onMove);
    this.canvas.removeEventListener("pointerleave", this.onLeave);
    this.canvas.removeEventListener("click", this.onClick);
    this.canvas.removeEventListener("webglcontextlost", this.onLost);
    window.removeEventListener("resize", this.resize);
    document.removeEventListener("visibilitychange", this.onVisibility);
    const mats = new Set<THREE.Material>();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => mats.add(x));
      else if (mat) mats.add(mat);
    });
    mats.forEach((m) => m.dispose());
    this.textures.forEach((t) => t.dispose());
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
