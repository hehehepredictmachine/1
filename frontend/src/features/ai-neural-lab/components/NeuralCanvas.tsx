// "Neural Universe" drawing: MLP layers, a Random Forest, an XGBoost tree cascade or Monte Carlo trajectories, in a rotatable 3-D
// view (drag = rotate, wheel = zoom). The shapes are ILLUSTRATIONS (labelled so in the page); only `inputs` may come from a model
// (the number of features in its registry entry). Pulses in "Przepływ" are an animation, not activations; "Ścieżka" walks one path
// node by node (replay of the drawing, no market data - nothing from the future can leak into it).
import { useEffect, useMemo, useRef } from "react";

export type Shape = "mlp" | "forest" | "xgb" | "mc";
export type ViewMode = "structure" | "flow" | "path";
type P3 = [number, number, number];
export interface Graph { nodes: { p: P3; label: string; layer: number }[]; edges: [number, number][]; path: number[]; lines?: P3[][] }

function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/** Deterministic geometry of each shape (the same drawing every time - no randomness that could look like data). */
export function buildGraph(shape: Shape, inputs: number | null): Graph {
  const nodes: Graph["nodes"] = [];
  const edges: [number, number][] = [];
  const path: number[] = [];
  if (shape === "mlp") {
    const inN = Math.max(3, Math.min(inputs ?? 8, 20));
    const layers = [inN, 10, 8, 6, 1];
    const idx: number[][] = [];
    layers.forEach((n, li) => {
      idx.push([]);
      for (let i = 0; i < n; i++) {
        const y = n === 1 ? 0 : (i / (n - 1) - 0.5) * 1.6;
        idx[li].push(nodes.length);
        nodes.push({ p: [(li / (layers.length - 1) - 0.5) * 2.2, y, Math.sin(i * 1.7 + li) * 0.25], label: li === 0 ? `wejście ${i + 1}` : li === layers.length - 1 ? "wyjście" : `warstwa ${li} · neuron ${i + 1}`, layer: li });
      }
    });
    for (let li = 0; li < layers.length - 1; li++) for (const a of idx[li]) for (const b of idx[li + 1]) edges.push([a, b]);
    idx.forEach((l, li) => path.push(l[(li * 3 + 1) % l.length]));
  } else if (shape === "forest" || shape === "xgb") {
    const trees = 5;
    const depth = shape === "forest" ? 3 : 2;
    const roots: number[] = [];
    for (let t = 0; t < trees; t++) {
      const base = nodes.length;
      const count = 2 ** (depth + 1) - 1;
      for (let k = 0; k < count; k++) {
        const level = Math.floor(Math.log2(k + 1));
        const pos = k + 1 - 2 ** level;
        const width = 2 ** level;
        const x = shape === "xgb" ? (t / (trees - 1) - 0.5) * 2.4 + ((pos + 0.5) / width - 0.5) * 0.42 : ((pos + 0.5) / width - 0.5) * 0.6;
        const ang = (t / trees) * Math.PI * 2;
        const p: P3 = shape === "xgb" ? [x, 0.8 - level * 0.5, 0] : [x + Math.cos(ang) * 1.0, 0.8 - level * 0.45, Math.sin(ang) * 1.0];
        nodes.push({ p, label: `drzewo ${t + 1} · ${level === 0 ? "korzeń" : level === depth ? "liść" : "podział"} ${k + 1}`, layer: level });
        if (k > 0) edges.push([base + Math.floor((k - 1) / 2), base + k]);
      }
      roots.push(base);
      if (t === 0) { let k = 0; for (let l = 0; l <= depth; l++) { path.push(base + k); k = 2 * k + 1 + (l % 2); } }
    }
    const out = nodes.length;
    nodes.push({ p: shape === "xgb" ? [1.55, -0.9, 0] : [0, -1.05, 0], label: shape === "xgb" ? "suma wkładów drzew" : "głosowanie lasu", layer: depth + 1 });
    if (shape === "xgb") for (let t = 0; t < trees - 1; t++) edges.push([roots[t], roots[t + 1]]);
    for (let t = 0; t < trees; t++) {
      const leaf = roots[t] + 2 ** (depth + 1) - 2;
      edges.push([leaf, out]);
    }
    path.push(out);
  } else {
    const r = rng(7);
    const lines: P3[][] = [];
    for (let k = 0; k < 26; k++) {
      let y = 0;
      const line: P3[] = [];
      const z = (k / 25 - 0.5) * 1.2;
      for (let i = 0; i <= 30; i++) {
        y += (r() - 0.5) * 0.16;
        line.push([(i / 30 - 0.5) * 2.4, y, z]);
      }
      lines.push(line);
      nodes.push({ p: line[line.length - 1], label: `trajektoria ${k + 1} – koniec`, layer: 1 });
    }
    nodes.unshift({ p: [-1.2, 0, 0], label: "stan początkowy", layer: 0 });
    for (let k = 1; k < nodes.length; k++) edges.push([0, k]);
    path.push(0, 5, 12, 19);
    return { nodes, edges: [], path, lines };
  }
  return { nodes, edges, path };
}

function css(el: HTMLElement, name: string, fallback: string) {
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback;
}

export default function NeuralCanvas({ shape, inputs, mode, playing, intensity, zoom, step, selected, onSelect, onZoom }: {
  shape: Shape; inputs: number | null; mode: ViewMode; playing: boolean; intensity: number; zoom: number; step: number;
  selected: number | null; onSelect: (i: number | null, label: string | null) => void; onZoom: (z: number) => void;
}) {
  const box = useRef<HTMLCanvasElement>(null);
  const graph = useMemo(() => buildGraph(shape, inputs), [shape, inputs]);
  const rot = useRef({ yaw: 0.5, pitch: 0.18 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const t0 = useRef(performance.now());
  const proj = useRef<[number, number, number][]>([]);
  const state = useRef({ mode, playing, intensity, zoom, step, selected });
  state.current = { mode, playing, intensity, zoom, step, selected };

  useEffect(() => {
    const cv = box.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
      || cv.closest(".pmw-terminal")?.getAttribute("data-motion") === "off";
    const draw = (now: number) => {
      const st = state.current;
      const dpr = window.devicePixelRatio || 1;
      const w = cv.clientWidth, h = cv.clientHeight;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const acc = css(cv, "--t-accent", "#2fd394");
      const dim = css(cv, "--t-dim", "#93a59d");
      const anim = st.playing && !reduced();
      const time = (now - t0.current) / 1000;
      if (anim) rot.current.yaw += 0.0025 * (0.4 + st.intensity);
      const { yaw, pitch } = rot.current;
      const s = Math.min(w, h) * 0.36 * st.zoom;
      const P = (p: P3): [number, number, number] => {
        const x1 = p[0] * Math.cos(yaw) + p[2] * Math.sin(yaw);
        const z1 = -p[0] * Math.sin(yaw) + p[2] * Math.cos(yaw);
        const y1 = p[1] * Math.cos(pitch) - z1 * Math.sin(pitch);
        const z2 = p[1] * Math.sin(pitch) + z1 * Math.cos(pitch);
        const f = 3.2 / (3.2 + z2);
        return [w / 2 + x1 * s * f, h / 2 - y1 * s * f, f];
      };
      const pts = graph.nodes.map((n) => P(n.p));
      proj.current = pts;
      const onPath = new Set(st.mode === "path" ? graph.path.slice(0, st.step + 1) : []);
      ctx.lineWidth = 1;
      if (graph.lines) {
        graph.lines.forEach((line, k) => {
          ctx.strokeStyle = acc;
          ctx.globalAlpha = 0.18 + 0.25 * st.intensity;
          if (st.mode === "path" && onPath.has(k + 1)) { ctx.globalAlpha = 0.95; ctx.lineWidth = 2; } else ctx.lineWidth = 1;
          ctx.beginPath();
          const upto = st.mode === "flow" && anim ? Math.floor(((time * 8 + k) % 31)) : line.length - 1;
          line.slice(0, upto + 1).forEach((p, i) => { const [x, y] = P(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
          ctx.stroke();
        });
      }
      for (const [a, b] of graph.edges) {
        const pa = pts[a], pb = pts[b];
        const hot = onPath.has(a) && onPath.has(b);
        ctx.strokeStyle = hot ? acc : dim;
        ctx.globalAlpha = hot ? 0.95 : (0.06 + 0.14 * st.intensity) * Math.min(pa[2], pb[2]);
        ctx.lineWidth = hot ? 2 : 1;
        ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
        if (st.mode === "flow" && anim && (a * 7 + b) % 5 === 0) {
          const u = (time * (0.35 + st.intensity) + ((a * 13 + b) % 17) / 17) % 1;
          ctx.globalAlpha = 0.9;
          ctx.fillStyle = acc;
          ctx.beginPath(); ctx.arc(pa[0] + (pb[0] - pa[0]) * u, pa[1] + (pb[1] - pa[1]) * u, 1.8, 0, Math.PI * 2); ctx.fill();
        }
      }
      pts.forEach(([x, y, f], i) => {
        const hot = onPath.has(i) || st.selected === i;
        ctx.globalAlpha = hot ? 1 : 0.55 + 0.4 * st.intensity;
        ctx.fillStyle = hot ? "#ffffff" : acc;
        ctx.shadowColor = acc;
        ctx.shadowBlur = hot ? 14 : 6 * st.intensity;
        ctx.beginPath(); ctx.arc(x, y, (hot ? 4.2 : 3) * f, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      });
      ctx.globalAlpha = 1;
      if (anim) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); };
    const ro = new ResizeObserver(redraw);
    ro.observe(cv);
    const down = (e: PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; cv.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
      rot.current.yaw += dx * 0.008;
      rot.current.pitch = Math.max(-1.2, Math.min(1.2, rot.current.pitch + dy * 0.006));
      d.x = e.clientX; d.y = e.clientY;
      if (!state.current.playing) redraw();
    };
    const up = (e: PointerEvent) => {
      const d = drag.current;
      drag.current = null;
      if (d && !d.moved) {
        const r = cv.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        let best = -1, bd = 12;
        proj.current.forEach(([px, py], i) => { const dd = Math.hypot(px - x, py - y); if (dd < bd) { bd = dd; best = i; } });
        onSel.current(best >= 0 ? best : null, best >= 0 ? graph.nodes[best].label : null);
      }
    };
    const wheel = (e: WheelEvent) => { e.preventDefault(); zoomCb.current(Math.max(0.5, Math.min(2.5, state.current.zoom * (e.deltaY < 0 ? 1.1 : 0.9)))); };
    cv.addEventListener("pointerdown", down);
    cv.addEventListener("pointermove", move);
    cv.addEventListener("pointerup", up);
    cv.addEventListener("wheel", wheel, { passive: false });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      cv.removeEventListener("pointerdown", down);
      cv.removeEventListener("pointermove", move);
      cv.removeEventListener("pointerup", up);
      cv.removeEventListener("wheel", wheel);
    };
  }, [graph, mode, playing, intensity, zoom, step, selected]);

  const onSel = useRef(onSelect);
  onSel.current = onSelect;
  const zoomCb = useRef(onZoom);
  zoomCb.current = onZoom;
  return <canvas ref={box} className="t-neural-canvas" data-testid="nl-canvas" data-shape={shape} data-mode={mode}
    aria-label={`Graf poglądowy (${shape}) – przeciągnij, aby obrócić; kółko myszy przybliża`} role="img" />;
}
