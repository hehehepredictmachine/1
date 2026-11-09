// 1.39 START boot intro (~8.5 s): "$PEPEMARKET WIZARD" + "They call us cult but we are something more", digital matrix that morphs
// into a neural network. Port of DEMO/boot_overlay.js of the approved pack (same canvas renderers, same timeline:
// title 2.8 s, tagline 3.45 s, neural 4.65 s, end 8.5 s, fade 0.75 s). Rules: it NEVER blocks the app (the app loads underneath,
// a hard timeout closes it), ESC / "POMIŃ INTRO" skip it, Ctrl+Alt+B or "↻ INTRO" replay it, reduced motion jumps to the end.
// Played once per browser session; automated browsers (navigator.webdriver) skip it unless localStorage "pmw.boot.force" = "1".
// Test hook: localStorage "pmw.boot.freeze" = seconds holds the timeline on that frame (screenshots of the phases); ESC still closes it.
// Visual only: no server, MT5 or model state is read or claimed here.
import { useCallback, useEffect, useRef, useState } from "react";
import "./boot.css";

export const BOOT_TOTAL = 8.5;
const SEEN = "pmw.boot.seen";
const FORCE = "pmw.boot.force";

function shouldPlay(): boolean {
  try {
    if (localStorage.getItem(FORCE) === "1") return true;
    if ((navigator as any).webdriver) return false;
    return sessionStorage.getItem(SEEN) !== "1";
  } catch { return !(navigator as any).webdriver; }
}

export default function BootScreen() {
  const [run, setRun] = useState(0);          // 0 = not playing; >0 = play id (replay increments)
  const [done, setDone] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [onMenu, setOnMenu] = useState(() => /^#\/?(menu)?(\?|$)/.test(location.hash));
  useEffect(() => {
    const h = () => setOnMenu(/^#\/?(menu)?(\?|$)/.test(location.hash));
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  useEffect(() => { if (shouldPlay()) setRun(1); else setDone(true); }, []);
  const replay = useCallback(() => { setDone(false); setRun((r) => r + 1); }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.ctrlKey && e.altKey && e.key.toLowerCase() === "b") { e.preventDefault(); replay(); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [replay]);

  useEffect(() => {
    if (!run) return;
    const boot = ref.current;
    if (!boot) return;
    const canvas = boot.querySelector("#pmwBootCanvas") as HTMLCanvasElement;
    const cx = canvas.getContext("2d", { alpha: true })!;
    const phaseLabel = boot.querySelector("#pmwBootPhase") as HTMLElement, bar = boot.querySelector("#pmwBootProgress") as HTMLElement;
    const skip = boot.querySelector("#pmwBootSkip") as HTMLButtonElement;
    const TOTAL = BOOT_TOTAL;
    const FAST = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    let FREEZE = 0;
    try { const f = Number(localStorage.getItem("pmw.boot.freeze")); if (Number.isFinite(f) && f > 0 && f < TOTAL) FREEZE = f; } catch { /* storage unavailable */ }
    let w = 0, h = 0, dpr = 1, start = 0, elapsed = 0, raf = 0, active = true, leaving = false, closeTimer = 0;
    let points: any[] = [], sparks: any[] = [], branches: any[] = [];
    const rnd = (n: number) => { const a = Math.sin(n * 78.233 + 11.12) * 43758.5453; return a - Math.floor(a); };
    function resize() { w = Math.max(320, window.innerWidth); h = Math.max(250, window.innerHeight); dpr = Math.min(window.devicePixelRatio || 1, 1.6); canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr); cx.setTransform(dpr, 0, 0, dpr, 0, 0); }
    function init() {
      points = Array.from({ length: 155 }, (_, i) => ({ x: rnd(i + 2), y: rnd(i + 240), z: .15 + rnd(i + 470) * 1.8, amp: .5 + rnd(i + 500) * 1.4, kind: i % 3 }));
      sparks = Array.from({ length: 110 }, (_, i) => ({ a: rnd(i + 740) * Math.PI * 2, r: rnd(i + 1280), s: .3 + rnd(i + 1700) * 1.5 }));
      branches = Array.from({ length: 38 }, (_, i) => ({ a: (i / 38) * Math.PI * 2 + .25 * Math.sin(i * 4.12), len: .48 + rnd(i + 801) * .8, phase: rnd(i + 950) * Math.PI * 2 }));
    }
    function pathFrame(time: number, alpha: number) {
      if (alpha < .01) return; cx.save(); cx.globalAlpha = alpha; const phase = time * .24;
      const scale = Math.min(w / 1440, h / 900) * 1.1;
      for (let i = 0; i < points.length; i++) {
        const p = points[i]; const depth = (p.z + time * .12) % 2.12 + .24; const x = (p.x - .5) * w * (.64 + depth * .35) + w * .5 + Math.sin(time * .5 + i) * 2;
        const y = (p.y - .5) * h * (.58 + depth * .35) + h * .5; const r = (.7 + p.amp) * depth * scale;
        if (i % 3 !== 0) {
          const q = points[(i * 17 + 41) % points.length]; const xd = (q.x - .5) * w * (.64 + depth * .35) + w * .5, yd = (q.y - .5) * h * (.58 + depth * .35) + h * .5;
          if (Math.abs(x - xd) < 170 * scale && Math.abs(y - yd) < 135 * scale) { cx.lineWidth = .3 + .12 * p.amp; cx.strokeStyle = "rgba(18,215,232,.20)"; cx.beginPath(); cx.moveTo(x, y); cx.lineTo(xd, yd); cx.stroke(); }
        }
        cx.fillStyle = i % 5 ? "rgba(42,238,245,.88)" : "rgba(165,255,255,.95)"; cx.shadowBlur = 7; cx.shadowColor = "#20ffff"; cx.beginPath(); cx.arc(x, y, Math.max(.4, r * .60), 0, Math.PI * 2); cx.fill(); cx.shadowBlur = 0;
        if (p.kind === 0) { cx.font = `${Math.max(9, 13 * depth * scale)}px ui-monospace,Consolas,monospace`; cx.globalAlpha = alpha * (.33 + Math.sin(i + time * 2) ** 2 * .5); cx.fillText("" + (i * 7 % 10), x + 8, y - 4); cx.globalAlpha = alpha; }
      }
      for (let i = 0; i < 28; i++) {
        const yy = h * .10 + (i / 27) * h * .86 + Math.sin(i * 4.1 + time * .4) * h * .02;
        cx.strokeStyle = `rgba(7,213,225,${.027 + .025 * Math.sin(phase + i) ** 2})`; cx.lineWidth = .45;
        cx.beginPath(); cx.moveTo(0, yy); cx.bezierCurveTo(w * .30, yy - 50, w * .63, yy + 55, w, yy - 70); cx.stroke();
      }
      cx.restore();
    }
    function neural(time: number, alpha: number) {
      if (alpha < .01) return; cx.save(); cx.globalCompositeOperation = "lighter"; cx.globalAlpha = alpha;
      const centerX = w * .5, centerY = h * .50, R = Math.min(w * .6, h * .90);
      for (let i = 0; i < branches.length; i++) {
        const b = branches[i], wiggle = Math.sin(time * .60 + b.phase) * .055, angle = b.a + wiggle;
        const steps = 26, pts: { x: number; y: number }[] = [];
        for (let k = 0; k <= steps; k++) {
          const u = k / steps; const len = (.11 + u * .92) * R * b.len;
          const skew = Math.sin(u * 11 + b.phase + time * .9) * R * .014 * u;
          pts.push({ x: centerX + Math.cos(angle) * len + Math.cos(angle + Math.PI / 2) * skew, y: centerY + Math.sin(angle) * len + Math.sin(angle + Math.PI / 2) * skew });
        }
        for (const [weight, opacity, glow] of [[8, .065, 24], [3, .18, 15], [.7, .75, 7]]) {
          cx.lineWidth = weight; cx.shadowBlur = glow; cx.shadowColor = i % 6 === 0 ? "#d8ffff" : "#45faf7"; cx.strokeStyle = `rgba(${i % 8 === 0 ? "202,255,255" : "75,235,240"},${opacity})`;
          cx.beginPath(); cx.moveTo(pts[0].x, pts[0].y); for (let j = 1; j < pts.length; j++) cx.lineTo(pts[j].x, pts[j].y); cx.stroke();
        }
        for (const m of [8, 14, 20]) {
          const p = pts[m], side = (i + m) % 2 ? 1 : -1, a = angle + side * (.38 + .17 * Math.sin(b.phase + m));
          const l = R * (.06 + .1 * rnd(i + m * 24));
          cx.strokeStyle = "rgba(146,255,255,.30)"; cx.lineWidth = .75; cx.shadowBlur = 8; cx.shadowColor = "#27eeff";
          cx.beginPath(); cx.moveTo(p.x, p.y); cx.quadraticCurveTo(p.x + Math.cos(a) * l * .4, p.y + Math.sin(a) * l * .4, p.x + Math.cos(a) * l, p.y + Math.sin(a) * l); cx.stroke();
        }
      }
      for (let i = 0; i < sparks.length; i++) {
        const p = sparks[i], r = ((p.r + time * p.s * .038) % 1) * R * 1.1;
        const x = centerX + Math.cos(p.a + time * .08) * r, y = centerY + Math.sin(p.a + time * .08) * r;
        cx.fillStyle = `rgba(138,255,255,${.12 + .53 * Math.sin(i + time * 3) ** 2})`; cx.shadowBlur = 10; cx.shadowColor = "#3cf5ff"; cx.beginPath(); cx.arc(x, y, Math.max(.4, (i % 4) * .35), 0, Math.PI * 2); cx.fill();
      }
      cx.restore();
    }
    function draw(t: number) {
      cx.clearRect(0, 0, w, h); cx.fillStyle = "#011015"; cx.fillRect(0, 0, w, h);
      const matrixAlpha = Math.max(0, Math.min(1, (5.2 - t) / 1.6)), neuronAlpha = Math.max(0, Math.min(1, (t - 3.7) / 1.6));
      const gr = cx.createRadialGradient(w * .5, h * .5, 0, w * .5, h * .5, Math.max(w, h) * .65);
      gr.addColorStop(0, "rgba(5,90,104,.24)"); gr.addColorStop(.5, "rgba(1,28,34,.16)"); gr.addColorStop(1, "rgba(0,2,4,0)"); cx.fillStyle = gr; cx.fillRect(0, 0, w, h);
      pathFrame(t, matrixAlpha); neural(t, neuronAlpha);
      if (t > 2.5 && t < 5.6) {
        const a = Math.sin((t - 2.5) / (5.6 - 2.5) * Math.PI) * .12;
        const grad = cx.createRadialGradient(w * .5, h * .5, 0, w * .5, h * .5, Math.max(w, h) * .42); grad.addColorStop(0, `rgba(77,248,255,${a})`); grad.addColorStop(1, "rgba(0,10,15,0)"); cx.fillStyle = grad; cx.fillRect(0, 0, w, h);
      }
    }
    function close() {
      if (leaving) return; leaving = true; active = false; cancelAnimationFrame(raf); boot!.classList.add("pmwb-exit"); skip.disabled = true; clearTimeout(closeTimer);
      try { sessionStorage.setItem(SEEN, "1"); } catch { /* storage unavailable */ }
      closeTimer = window.setTimeout(() => { setRun(0); setDone(true); window.dispatchEvent(new CustomEvent("pmw:boot-finished")); }, 760);
    }
    function tick(ts: number) {
      if (!active) return; if (!start) start = ts; elapsed = FREEZE || Math.min(FAST ? TOTAL : (ts - start) / 1000, TOTAL);
      if (elapsed > 2.8) boot!.classList.add("pmwb-title"); if (elapsed > 3.45) boot!.classList.add("pmwb-tag-show"); if (elapsed > 4.65) boot!.classList.add("pmwb-neural");
      boot!.dataset.elapsed = elapsed.toFixed(2);
      phaseLabel.textContent = elapsed < 2.8 ? "INITIALIZING NEURAL MATRIX" : elapsed < 4.65 ? "PEPEMARKET WIZARD • SYSTEM BOOT" : elapsed < 6.65 ? "ACTIVATING NEURAL NETWORK" : "NEURAL SYSTEM READY";
      bar.style.width = (100 * elapsed / TOTAL).toFixed(1) + "%"; draw(elapsed);
      if (elapsed >= TOTAL) { close(); return; } raf = requestAnimationFrame(tick);
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && active) close(); };
    // hard timeout: a throttled / background tab never keeps the overlay over the app
    const hard = FREEZE ? 0 : window.setTimeout(close, (TOTAL + 3) * 1000);
    skip.addEventListener("click", close); document.addEventListener("keydown", onKey); window.addEventListener("resize", resize);
    (window as any).pmwBoot = { replay, skip: close, get state() { return { active, elapsed, done: leaving }; } };
    resize(); init(); raf = requestAnimationFrame(tick);
    return () => {
      active = false; cancelAnimationFrame(raf); clearTimeout(closeTimer); clearTimeout(hard);
      skip.removeEventListener("click", close); document.removeEventListener("keydown", onKey); window.removeEventListener("resize", resize);
    };
  }, [run, replay]);

  return (
    <>
      {run > 0 && (
        <div id="pmwBoot" key={run} ref={ref} className="pmwb-grid" role="dialog" aria-modal="true" aria-label="Animacja uruchamiania PepeMarketWizard" data-testid="boot">
          <div className="pmwb-scene" aria-hidden="true">
            <div className="pmwb-ref" id="pmwBootMatrixRef" /><div className="pmwb-ref" id="pmwBootNeuralRef" />
            <canvas id="pmwBootCanvas" /><div className="pmwb-vignette" />
          </div>
          <div id="pmwBootTitlewrap" className="pmwb-titlewrap"><h1 className="pmwb-title"><span className="pmwb-dollar">$</span>PEPEMARKET WIZARD</h1><p className="pmwb-tag">They call us cult but we are something more</p></div>
          <div className="pmwb-subbar" aria-hidden="true"><span id="pmwBootPhase">INITIALIZING NEURAL MATRIX</span><div className="pmwb-track"><div id="pmwBootProgress" /></div></div>
          <button type="button" id="pmwBootSkip" aria-label="Pomiń animację startową" data-testid="boot-skip">POMIŃ INTRO ↗</button>
        </div>
      )}
      {done && onMenu && <button type="button" id="pmwBootReplay" style={{ display: "block" }} title="Odtwórz intro ponownie (Ctrl+Alt+B)" data-testid="boot-replay" onClick={replay}>↻ INTRO</button>}
    </>
  );
}
