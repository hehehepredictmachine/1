// Live layer over the background image: drifting fog, dust with depth parallax, a soft light that follows the cursor and takes the
// colour of the indicated tower, and - on the main menu - procedural purple lightning with a flash (the delivered tower GIF arrived as
// one frame; the lightning is rendered here, live). Decorative only: pointer-events: none, nothing here reflects bot data.
// Paused when the tab is hidden; with prefers-reduced-motion it draws one static frame (no lightning, no parallax).
import { useEffect, useRef } from "react";

type Bolt = { pts: [number, number][]; branches: [number, number][][]; life: number; max: number };

function makeBolt(w: number, h: number): Bolt {
  const x0 = w * (0.35 + Math.random() * 0.6), y0 = -10;
  const x1 = x0 + (Math.random() - 0.5) * w * 0.5, y1 = h * (0.35 + Math.random() * 0.25);
  const path = (ax: number, ay: number, bx: number, by: number, rough: number, depth: number): [number, number][] => {
    if (depth === 0) return [[ax, ay], [bx, by]];
    const mx = (ax + bx) / 2 + (Math.random() - 0.5) * rough, my = (ay + by) / 2 + (Math.random() - 0.5) * rough * 0.3;
    const a = path(ax, ay, mx, my, rough / 2, depth - 1);
    return a.concat(path(mx, my, bx, by, rough / 2, depth - 1).slice(1));
  };
  const pts = path(x0, y0, x1, y1, w * 0.12, 7);
  const branches: [number, number][][] = [];
  for (let k = 0; k < 3; k++) {
    const i = Math.floor(pts.length * (0.25 + Math.random() * 0.5));
    const [bx, by] = pts[i];
    branches.push(path(bx, by, bx + (Math.random() - 0.5) * w * 0.25, by + h * 0.12 * Math.random() + 30, w * 0.05, 5));
  }
  return { pts, branches, life: 0, max: 0.55 + Math.random() * 0.3 };
}

export default function BackdropFx({ accent, lightning, imgRef, reduced }: {
  accent: string; lightning: boolean; imgRef?: React.RefObject<HTMLImageElement | null>; reduced: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const accentRef = useRef(accent);
  accentRef.current = accent;

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const g = c.getContext("2d");
    if (!g) return;
    let w = 0, h = 0, raf = 0, running = false, last = performance.now();
    let mx = 0.5, my = 0.5, lx = 0.5, ly = 0.5;
    let flash = 0, nextBolt = performance.now() + 1200;
    const bolts: Bolt[] = [];
    const dust = Array.from({ length: 140 }, () => ({ x: Math.random(), y: Math.random(), z: 0.3 + Math.random() * 0.7, s: 0.4 + Math.random() * 1.4 }));
    const fog = Array.from({ length: 7 }, (_, i) => ({ x: Math.random(), y: 0.45 + Math.random() * 0.6, r: 0.25 + Math.random() * 0.3, v: (i % 2 ? 1 : -1) * (0.004 + Math.random() * 0.006) }));
    const resize = () => {
      w = c.clientWidth; h = c.clientHeight;
      c.width = Math.round(w); c.height = Math.round(h);
    };
    const onMove = (e: PointerEvent) => { mx = e.clientX / Math.max(1, window.innerWidth); my = e.clientY / Math.max(1, window.innerHeight); };

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      lx += (mx - lx) * Math.min(1, dt * 2.5);
      ly += (my - ly) * Math.min(1, dt * 2.5);
      g.clearRect(0, 0, w, h);
      // fog banks
      for (const f of fog) {
        if (!reduced) f.x = (f.x + f.v * dt + 1.4) % 1.4 - 0.2;
        const gr = g.createRadialGradient(f.x * w, f.y * h, 0, f.x * w, f.y * h, f.r * w);
        gr.addColorStop(0, "rgba(70,60,130,0.16)"); gr.addColorStop(1, "rgba(20,16,50,0)");
        g.fillStyle = gr;
        g.fillRect(0, 0, w, h);
      }
      // cursor light in the colour of the indicated tower
      const cg = g.createRadialGradient(lx * w, ly * h, 0, lx * w, ly * h, Math.max(w, h) * 0.35);
      cg.addColorStop(0, hexA(accentRef.current, 0.16)); cg.addColorStop(1, hexA(accentRef.current, 0));
      g.fillStyle = cg;
      g.fillRect(0, 0, w, h);
      // lightning
      if (lightning && !reduced) {
        if (now > nextBolt) {
          bolts.push(makeBolt(w, h));
          if (Math.random() < 0.35) bolts.push(makeBolt(w, h));
          flash = 1;
          nextBolt = now + 2600 + Math.random() * 4800;
        }
        g.save();
        g.globalCompositeOperation = "lighter";
        for (let i = bolts.length - 1; i >= 0; i--) {
          const b = bolts[i];
          b.life += dt;
          const k = 1 - b.life / b.max;
          if (k <= 0) { bolts.splice(i, 1); continue; }
          const flick = k * (0.6 + 0.4 * Math.sin(b.life * 90));
          for (const [lw, col] of [[10, `rgba(150,80,255,${0.14 * flick})`], [4, `rgba(190,130,255,${0.45 * flick})`], [1.4, `rgba(245,235,255,${0.95 * flick})`]] as const) {
            g.strokeStyle = col; g.lineWidth = lw; g.lineJoin = "round";
            for (const line of [b.pts, ...b.branches]) {
              g.beginPath();
              line.forEach(([x, y], j) => (j ? g.lineTo(x, y) : g.moveTo(x, y)));
              g.stroke();
            }
          }
        }
        g.restore();
        if (flash > 0) {
          g.fillStyle = `rgba(150,90,255,${0.10 * flash})`;
          g.fillRect(0, 0, w, h);
          flash = Math.max(0, flash - dt * 3.2);
        }
        if (imgRef?.current) imgRef.current.style.filter = `brightness(${(1 + flash * 0.35).toFixed(3)})`;
      }
      // dust with depth parallax
      g.save();
      g.globalCompositeOperation = "lighter";
      for (const d of dust) {
        if (!reduced) { d.y -= dt * 0.006 * d.z; if (d.y < -0.02) d.y = 1.02; }
        const x = (d.x + (0.5 - lx) * 0.03 * d.z) * w, y = (d.y + (0.5 - ly) * 0.02 * d.z) * h;
        g.fillStyle = `rgba(200,180,255,${0.25 * d.z})`;
        g.fillRect(x, y, d.s * d.z, d.s * d.z);
      }
      g.restore();
      if (imgRef?.current && !reduced) imgRef.current.style.transform = `translate3d(${((0.5 - lx) * 22).toFixed(1)}px, ${((0.5 - ly) * 14).toFixed(1)}px, 0) scale(1.06)`;
    };

    const loop = (now: number) => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      draw(now);
    };
    const sync = () => {
      const should = document.visibilityState === "visible" && !reduced;
      if (should && !running) { running = true; last = performance.now(); raf = requestAnimationFrame(loop); }
      else if (!should && running) { running = false; cancelAnimationFrame(raf); }
    };
    resize();
    draw(performance.now());                                     // static frame (also the reduced-motion picture)
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove);
    document.addEventListener("visibilitychange", sync);
    sync();
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [lightning, reduced, imgRef]);

  return <canvas ref={canvas} className="wz-fx" aria-hidden="true" data-testid="wz-fx" />;
}

function hexA(hex: string, a: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
