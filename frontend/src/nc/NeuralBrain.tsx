// Neural System – a brain silhouette built from neurons (glowing somata + curved dendrites), animated and mouse-interactive.
// Style after the user's reference images (deep navy, violet/cyan glowing neurons). Two layers, clearly separated:
//  * DECORATIVE network (hundreds of neurons, travelling signal pulses, cursor glow / synapses) - an animation, it does NOT
//    represent model inference and says so in the legend;
//  * MODULE neurons (one per component of the bot's model registry): position, colour and links come ONLY from the registry
//    (ready / SHADOW / not trained / error, participation in the SH decision). Hover/click shows the real registry entry.
import { useEffect, useMemo, useRef, useState } from "react";

type Mod = { id: string; name: string; kind: string; group: string; status: string; readiness: string; blockers?: string[]; SCALPING?: any; HEDGING?: any };
type N = { x: number; y: number; r: number; z: number; ph: number };
type E = { a: number; b: number; cx: number; cy: number };

function rng(seed: number) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

// brain side view in a unit box: cerebrum (frontal..occipital), temporal lobe, cerebellum, brain stem
function inside(x: number, y: number): boolean {
  const e = (cx: number, cy: number, rx: number, ry: number) => ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1;
  const cerebrum = e(0.47, 0.43, 0.39, 0.29) || e(0.25, 0.47, 0.17, 0.2) || e(0.62, 0.38, 0.25, 0.24);
  const temporal = e(0.47, 0.62, 0.25, 0.12);
  const cerebellum = e(0.73, 0.71, 0.13, 0.085);
  const stem = x > 0.56 && x < 0.64 && y > 0.62 && y < 0.93 && Math.abs(x - (0.6 - (y - 0.62) * 0.12)) < 0.04;
  return cerebrum || temporal || cerebellum || stem;
}
const LOBES: [number, number][] = [[0.27, 0.40], [0.42, 0.25], [0.62, 0.24], [0.76, 0.40], [0.48, 0.62], [0.73, 0.71], [0.35, 0.52], [0.58, 0.47], [0.20, 0.55], [0.66, 0.58]];

export default function NeuralBrain({ models, mode, height }: { models: Mod[]; mode?: string; height: number }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const mouse = useRef<{ x: number; y: number; on: boolean }>({ x: 0, y: 0, on: false });
  const [hover, setHover] = useState<Mod | null>(null);
  const [pinned, setPinned] = useState<Mod | null>(null);
  const hoverRef = useRef<Mod | null>(null);
  const pinnedRef = useRef<Mod | null>(null);
  hoverRef.current = hover;
  pinnedRef.current = pinned;
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  // decorative network (deterministic): outline, cortical folds, cerebellum striations, hero neurons, background neurons
  const net = useMemo(() => {
    const R = rng(20261021);
    const nodes: N[] = [];
    const add = (x: number, y: number, z = R()) => { if (inside(x, y)) nodes.push({ x, y, r: 0.6 + R() * 1.6, z, ph: R() * Math.PI * 2 }); };
    // outline: polar scan from the centre
    const outline: [number, number][] = [];
    for (let k = 0; k < 360; k += 2) {
      const a = (k / 180) * Math.PI;
      let r = 0.62;
      while (r > 0.02 && !inside(0.5 + Math.cos(a) * r, 0.5 + Math.sin(a) * r)) r -= 0.003;
      outline.push([0.5 + Math.cos(a) * r, 0.5 + Math.sin(a) * r]);
    }
    outline.forEach(([x, y], i) => i % 2 === 0 && add(x, y, 0.55 + R() * 0.45));
    // cortical folds (gyri/sulci): meandering walks from the outline inwards
    const folds: [number, number][][] = [];
    for (let f = 0; f < 26; f++) {
      const [sx, sy] = outline[Math.floor(R() * outline.length)];
      if (sy > 0.66) continue;                                    // no folds on the stem / cerebellum edge
      let x = sx, y = sy, a = Math.atan2(0.45 - y, 0.47 - x) + (R() - 0.5) * 0.8;
      const pts: [number, number][] = [];
      const L = 18 + Math.floor(R() * 26);
      for (let i = 0; i < L; i++) {
        a += Math.sin(i * 0.55 + f) * 0.38 + (R() - 0.5) * 0.25;
        x += Math.cos(a) * 0.012; y += Math.sin(a) * 0.012;
        if (!inside(x, y) || (x > 0.6 && y > 0.6)) break;
        pts.push([x, y]);
        if (i % 3 === 0) add(x, y, 0.4 + R() * 0.6);
      }
      if (pts.length > 4) folds.push(pts);
    }
    // cerebellum striations
    for (let k = 0; k < 6; k++) {
      const pts: [number, number][] = [];
      for (let t = -1; t <= 1.001; t += 0.1) {
        const x = 0.73 + t * 0.11 * (1 - k * 0.05), y = 0.66 + k * 0.018 + (1 - t * t) * 0.02;
        if (inside(x, y)) pts.push([x, y]);
      }
      if (pts.length > 2) folds.push(pts);
    }
    while (nodes.length < 520) add(R(), R());
    // hero neurons: large somata with long branching dendrites (like the reference images)
    const heroes = [[0.36, 0.38], [0.58, 0.30], [0.28, 0.52], [0.40, 0.64], [0.70, 0.42], [0.44, 0.24], [0.74, 0.70], [0.20, 0.42]].map(([x, y]) => {
      const br: [number, number, number, number, number][] = [];          // x1,y1,x2,y2,width
      const grow = (x0: number, y0: number, a: number, len: number, w: number, depth: number) => {
        let x = x0, y = y0;
        const steps = 6;
        for (let i = 0; i < steps; i++) {
          a += (R() - 0.5) * 0.35;
          const nx = x + Math.cos(a) * len / steps, ny = y + Math.sin(a) * len / steps;
          br.push([x, y, nx, ny, w * (1 - i / (steps + 2))]);
          x = nx; y = ny;
          if (depth > 0 && i === 3 && R() < 0.8) grow(x, y, a + (R() < 0.5 ? 0.6 : -0.6), len * 0.55, w * 0.55, depth - 1);
        }
      };
      const n = 6 + Math.floor(R() * 4);
      for (let k = 0; k < n; k++) grow(x, y, (k / n) * Math.PI * 2 + R() * 0.4, 0.07 + R() * 0.09, 2.6, 1);
      return { x, y, br };
    });
    const edges: E[] = [];
    nodes.forEach((n, i) => {
      const near = nodes.map((m, j) => ({ j, d: Math.hypot(m.x - n.x, m.y - n.y) })).filter((o) => o.j !== i && o.d < 0.07).sort((p, q) => p.d - q.d).slice(0, 3);
      near.forEach(({ j }) => {
        if (j < i) return;
        const m = nodes[j];
        const mx = (n.x + m.x) / 2, my = (n.y + m.y) / 2, k = (R() - 0.5) * 0.06;
        edges.push({ a: i, b: j, cx: mx - (m.y - n.y) * k * 8, cy: my + (m.x - n.x) * k * 8 });
      });
    });
    return { nodes, edges, outline, folds, heroes };
  }, []);

  // module neurons: grouped by correlation group into lobes (positions deterministic, data from the registry)
  const mods = useMemo(() => {
    const groups = Array.from(new Set(models.map((m) => m.group)));
    return models.map((m) => {
      const g = groups.indexOf(m.group), [lx, ly] = LOBES[g % LOBES.length];
      const inG = models.filter((x) => x.group === m.group), k = inG.indexOf(m);
      const a = k * 2.399, rr = 0.025 + 0.022 * Math.sqrt(k);
      let x = lx + Math.cos(a) * rr, y = ly + Math.sin(a) * rr * 0.8;
      if (!inside(x, y)) { x = lx; y = ly; }
      return { m, x, y };
    });
  }, [models]);
  const hub = { x: 0.52, y: 0.5 };
  const col = (m: Mod) => (m.readiness === "READY" || m.readiness === "DETERMINISTIC_OK" ? [70, 226, 182] : m.readiness === "SHADOW" ? [118, 220, 252] :
    m.status === "ERROR" || m.status === "INCOMPATIBLE" ? [255, 129, 159] : [150, 135, 210]);

  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const g = c.getContext("2d")!;
    const stat = document.createElement("canvas");
    let W = 0, H = 0, S = 1, Kf = 1, SX = 1, SY = 1, ox = 0, oy = 0, dpr = 1, raf = 0;
    const P = (x: number, y: number) => [ox + x * SX, oy + y * SY] as const;
    const layout = () => {
      const r = c.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = r.width; H = r.height;
      c.width = W * dpr; c.height = H * dpr;
      SY = Math.min(H * 1.02, W * 0.8); SX = Math.min(W * 0.96, SY * 1.32); S = Math.min(SX, SY);
      Kf = Math.min(1.4, Math.max(0.45, S / 760));                       // glow/size factor (smaller on phones)
      ox = (W - SX) / 2; oy = (H - SY * 0.95) / 2;
      // static layer: dendrites + somata of the decorative network
      stat.width = c.width; stat.height = c.height;
      const s = stat.getContext("2d")!;
      s.setTransform(dpr, 0, 0, dpr, 0, 0);
      s.clearRect(0, 0, W, H);
      s.globalCompositeOperation = "lighter";
      const path = (pts: [number, number][], close = false) => {
        s.beginPath();
        pts.forEach(([x, y], i) => { const [X, Y] = P(x, y); if (i === 0) s.moveTo(X, Y); else s.lineTo(X, Y); });
        if (close) s.closePath();
      };
      s.shadowColor = "rgba(170,150,255,0.9)"; s.shadowBlur = 14 * Kf;
      s.strokeStyle = "rgba(190,175,255,0.55)"; s.lineWidth = 2.2; path(net.outline, true); s.stroke();          // brain outline
      s.shadowBlur = 8 * Kf;
      net.folds.forEach((f) => { s.strokeStyle = "rgba(170,160,255,0.32)"; s.lineWidth = 1.3; path(f); s.stroke(); });   // folds
      s.shadowBlur = 10 * Kf; s.shadowColor = "rgba(120,170,255,0.8)";
      net.heroes.forEach((h) => h.br.forEach(([x1, y1, x2, y2, w]) => {                                              // hero dendrites
        const [a, b] = P(x1, y1), [c2, d] = P(x2, y2);
        s.strokeStyle = "rgba(170,185,255,0.55)"; s.lineWidth = Math.max(0.5, w * Kf); s.lineCap = "round";
        s.beginPath(); s.moveTo(a, b); s.lineTo(c2, d); s.stroke();
      }));
      net.heroes.forEach((h) => {
        const [X, Y] = P(h.x, h.y), rr = 13 * Kf;
        const gr = s.createRadialGradient(X, Y, 0, X, Y, rr * 2.6);
        gr.addColorStop(0, "rgba(245,240,255,0.95)"); gr.addColorStop(0.35, "rgba(170,160,255,0.65)"); gr.addColorStop(1, "rgba(90,100,255,0)");
        s.fillStyle = gr; s.beginPath(); s.arc(X, Y, rr * 2.6, 0, Math.PI * 2); s.fill();
      });
      s.shadowBlur = 0;
      net.edges.forEach((e) => {
        const a = net.nodes[e.a], b = net.nodes[e.b];
        const [x1, y1] = P(a.x, a.y), [x2, y2] = P(b.x, b.y), [cx, cy] = P(e.cx, e.cy);
        const z = (a.z + b.z) / 2;
        s.strokeStyle = `rgba(${120 + z * 60},${130 + z * 80},255,${0.10 + z * 0.16})`;
        s.lineWidth = 0.5 + z * 1.1;
        s.beginPath(); s.moveTo(x1, y1); s.quadraticCurveTo(cx, cy, x2, y2); s.stroke();
      });
      const R = rng(7);
      net.nodes.forEach((n) => {                              // short dendrite stubs for an organic look
        const [x, y] = P(n.x, n.y);
        for (let k = 0; k < 3; k++) {
          const a = R() * Math.PI * 2, l = (4 + R() * 12) * (0.5 + n.z);
          s.strokeStyle = `rgba(150,170,255,${0.08 + n.z * 0.12})`; s.lineWidth = 0.6;
          s.beginPath(); s.moveTo(x, y); s.quadraticCurveTo(x + Math.cos(a + 0.6) * l * 0.6, y + Math.sin(a + 0.6) * l * 0.6, x + Math.cos(a) * l, y + Math.sin(a) * l); s.stroke();
        }
        const rr = n.r * (1 + n.z) * Kf;
        const gr = s.createRadialGradient(x, y, 0, x, y, rr * 4);
        gr.addColorStop(0, `rgba(225,215,255,${0.55 + n.z * 0.4})`); gr.addColorStop(0.35, `rgba(150,140,255,${0.25 + n.z * 0.2})`); gr.addColorStop(1, "rgba(80,90,255,0)");
        s.fillStyle = gr; s.beginPath(); s.arc(x, y, rr * 4, 0, Math.PI * 2); s.fill();
      });
    };
    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(c);
    const pulses = net.edges.map((_, i) => ({ i, t: (i * 0.137) % 1, v: 0.0025 + ((i * 7) % 11) * 0.00045 }));
    const frame = (time: number) => {
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const bg = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.7);
      bg.addColorStop(0, "#1b1846"); bg.addColorStop(0.55, "#0b1030"); bg.addColorStop(1, "#05081a");
      g.fillStyle = bg; g.fillRect(0, 0, W, H);
      const mo = mouse.current;
      const px = mo.on ? (mo.x - W / 2) * -0.012 : 0, py = mo.on ? (mo.y - H / 2) * -0.012 : 0;   // parallax
      g.drawImage(stat, px * dpr, py * dpr, c.width, c.height, 0, 0, W, H);
      g.globalCompositeOperation = "lighter";
      // travelling signals (decorative)
      if (!reduce) pulses.forEach((p) => {
        p.t += p.v; if (p.t > 1) p.t -= 1;
        if (p.i % 3) return;
        const e = net.edges[p.i], a = net.nodes[e.a], b = net.nodes[e.b], t = p.t;
        const x = (1 - t) ** 2 * a.x + 2 * (1 - t) * t * e.cx + t * t * b.x, y = (1 - t) ** 2 * a.y + 2 * (1 - t) * t * e.cy + t * t * b.y;
        const [X, Y] = P(x, y);
        const gr = g.createRadialGradient(X - px, Y - py, 0, X - px, Y - py, 5);
        gr.addColorStop(0, "rgba(190,240,255,0.9)"); gr.addColorStop(1, "rgba(118,220,252,0)");
        g.fillStyle = gr; g.beginPath(); g.arc(X - px, Y - py, 5, 0, Math.PI * 2); g.fill();
      });
      // cursor: synapses to nearby neurons + glow
      if (mo.on) {
        let k = 0;
        for (const n of net.nodes) {
          const [x, y] = P(n.x, n.y);
          const d = Math.hypot(x - px - mo.x, y - py - mo.y);
          if (d < 130 && k < 24) {
            k++;
            g.strokeStyle = `rgba(160,200,255,${(1 - d / 130) * 0.55})`; g.lineWidth = 0.8;
            g.beginPath(); g.moveTo(mo.x, mo.y); g.lineTo(x - px, y - py); g.stroke();
            g.fillStyle = `rgba(230,240,255,${(1 - d / 130) * 0.9})`; g.beginPath(); g.arc(x - px, y - py, 1.6 + (1 - d / 130) * 2.4, 0, Math.PI * 2); g.fill();
          }
        }
        const cg = g.createRadialGradient(mo.x, mo.y, 0, mo.x, mo.y, 90);
        cg.addColorStop(0, "rgba(180,154,255,0.22)"); cg.addColorStop(1, "rgba(180,154,255,0)");
        g.fillStyle = cg; g.beginPath(); g.arc(mo.x, mo.y, 90, 0, Math.PI * 2); g.fill();
      }
      // module neurons (registry data) and their link to the decision hub
      const [hx, hy] = P(hub.x, hub.y);
      const pulse = reduce ? 1 : 0.75 + 0.25 * Math.sin(time / 600);
      mods.forEach(({ m, x, y }) => {
        const [X, Y] = P(x, y);
        const [r, gg, b] = col(m);
        const use = m.SCALPING?.use || "NONE";
        if (use !== "NONE") {
          g.strokeStyle = `rgba(${r},${gg},${b},${use === "INFO" ? 0.25 : 0.5})`; g.lineWidth = use === "INFO" ? 0.8 : 1.4;
          g.beginPath(); g.moveTo(X - px * 0.5, Y - py * 0.5); g.quadraticCurveTo((X + hx) / 2, (Y + hy) / 2 - 30, hx, hy); g.stroke();
        }
        const ready = m.readiness === "READY" || m.readiness === "DETERMINISTIC_OK";
        const rad = (m.kind === "TRAINED" ? 9 : 7) * (ready ? pulse : 0.8) * Math.max(0.6, Kf);
        const gr = g.createRadialGradient(X - px * 0.5, Y - py * 0.5, 0, X - px * 0.5, Y - py * 0.5, rad * 3.2);
        gr.addColorStop(0, `rgba(255,255,255,0.95)`); gr.addColorStop(0.25, `rgba(${r},${gg},${b},0.9)`); gr.addColorStop(1, `rgba(${r},${gg},${b},0)`);
        g.fillStyle = gr; g.beginPath(); g.arc(X - px * 0.5, Y - py * 0.5, rad * 3.2, 0, Math.PI * 2); g.fill();
        if (hoverRef.current?.id === m.id || pinnedRef.current?.id === m.id) {
          g.strokeStyle = "rgba(255,255,255,0.9)"; g.lineWidth = 1.5; g.beginPath(); g.arc(X - px * 0.5, Y - py * 0.5, rad * 2, 0, Math.PI * 2); g.stroke();
        }
      });
      const hg = g.createRadialGradient(hx, hy, 0, hx, hy, 34 * Kf * pulse);
      hg.addColorStop(0, "rgba(255,255,255,1)"); hg.addColorStop(0.3, "rgba(180,154,255,0.9)"); hg.addColorStop(1, "rgba(180,154,255,0)");
      g.fillStyle = hg; g.beginPath(); g.arc(hx, hy, 34 * Kf * pulse, 0, Math.PI * 2); g.fill();
      g.globalCompositeOperation = "source-over";
      g.fillStyle = "#e7edff"; g.font = "11px system-ui"; g.textAlign = "center"; g.fillText("DECYZJA SH", hx, hy + 30);
      if (mode) { g.fillStyle = "#94a3bf"; g.font = "10px system-ui"; g.fillText(`tryb ${mode}`, hx, hy + 44); }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    const pick = (ev: PointerEvent) => {
      const r = c.getBoundingClientRect();
      const x = ev.clientX - r.left, y = ev.clientY - r.top;
      mouse.current = { x, y, on: true };
      const hit = mods.find(({ x: mx, y: my }) => Math.hypot(ox + mx * SX - x, oy + my * SY - y) < 16);
      if ((hit?.m.id || null) !== (hoverRef.current?.id || null)) setHover(hit ? hit.m : null);
      c.style.cursor = hit ? "pointer" : "crosshair";
    };
    const leave = () => { mouse.current.on = false; setHover(null); };
    const click = () => setPinned((p) => (hoverRef.current && p?.id !== hoverRef.current.id ? hoverRef.current : null));
    c.addEventListener("pointermove", pick);
    c.addEventListener("pointerleave", leave);
    c.addEventListener("click", click);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); c.removeEventListener("pointermove", pick); c.removeEventListener("pointerleave", leave); c.removeEventListener("click", click); };
  }, [net, mods, mode]);
  const show = hover || pinned;
  return (
    <div className="nc-brain-wrap">
      <canvas ref={cv} className="nc-brain" style={{ height }} aria-label="Neural System: sieć neuronów w kształcie mózgu; jasne węzły to moduły bota z rejestru modeli" />
      <div className="nc-brain-info" data-testid="nc-brain-info">{show ? <>
        <b>{show.name}</b> · {show.kind} · grupa {show.group}<br />status <b>{show.status}</b> · gotowość <b>{show.readiness}</b>
        <br />SCALPING: {show.SCALPING?.role}/{show.SCALPING?.use} · HEDGING: {show.HEDGING?.role}/{show.HEDGING?.use}
        {(show.blockers || []).length > 0 && <><br />blokady: {show.blockers!.join("; ")}</>}{pinned && <><br /><i>kliknij ponownie, aby odpiąć</i></>}</> :
        <>Najedź na jasny neuron – moduł bota; kliknij, aby przypiąć opis.</>}</div>
      <div className="nc-brain-legend">
        <span><i style={{ background: "#46e2b6" }} />gotowy</span><span><i style={{ background: "#76dcfc" }} />SHADOW</span>
        <span><i style={{ background: "#9687d2" }} />nieprzetrenowany / niepodłączony</span><span><i style={{ background: "#ff819f" }} />błąd</span>
        <span className="nc-small">Tło i impulsy to animacja – nie przedstawiają inferencji. Stan modułów pochodzi wyłącznie z rejestru modeli.</span>
      </div>
    </div>);
}
