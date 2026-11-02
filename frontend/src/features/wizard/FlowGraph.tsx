// Interactive spatial map of program modules (left: data flow and analyses, right: models, aggregation and decisions). Two layers:
// a decorative one (slow rotation, floating motes, the eye of the core) and a telemetry one (node colours from the bot's reported
// state, impulses ONLY when a matching real event arrives through the single WebSocket). Offline: no impulses, grey nodes, label.
// Mouse: hover highlights a node and its links + tooltip, click opens details, drag rotates, wheel zooms (inside the map only).
// Keyboard / screen readers: the "Lista modułów" button shows the same nodes as an HTML list.
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useStore } from "../../store";
import { telemetry } from "../../telemetry";
import { cls, fmtTime } from "../../util";
import { dataModel, modelsModel, STATUS_PL, statusColor, type FlowModel, type FlowNode, type NodeStatus } from "./flowModel";

type Filter = "all" | "active" | "problems" | "SCALPING" | "HEDGING" | "S01–S12";
type Pos = { x: number; y: number; z: number };
type Impulse = { a: string; b: string; t0: number; color: string };
const RING_R = [0, 0.38, 0.66, 0.95];

function layout(m: FlowModel): Map<string, Pos> {
  const out = new Map<string, Pos>();
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (const ring of [0, 1, 2, 3] as const) {
    const ns = m.nodes.filter((n) => n.ring === ring).sort((a, b) => a.id.localeCompare(b.id));
    ns.forEach((n, i) => {
      if (ring === 0) { out.set(n.id, { x: 0, y: 0, z: 0 }); return; }
      const k = ns.length;
      const yv = k > 1 ? 1 - (2 * (i + 0.5)) / k : 0;
      const phi = Math.asin(yv) * 0.62;
      const th = i * golden + ring * 0.7;
      const r = RING_R[ring];
      out.set(n.id, { x: r * Math.cos(phi) * Math.cos(th), y: r * Math.sin(phi), z: r * Math.cos(phi) * Math.sin(th) });
    });
  }
  return out;
}

function matches(n: FlowNode, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "active") return n.status === "active";
  if (f === "problems") return n.status === "error" || n.status === "offline";
  return (n.strategies || []).includes(f) || n.id === f;
}

function ago(t: number | null, now: number): string {
  if (!t) return "brak zdarzeń w tej sesji";
  const s = Math.max(0, Math.round((now - t) / 1000));
  return s < 90 ? `${s} s temu` : s < 5400 ? `${Math.round(s / 60)} min temu` : fmtTime(new Date(t).toISOString(), true);
}

export default function FlowGraph({ kind, tele, reduced }: { kind: "data" | "models"; tele: any; reduced: boolean }) {
  const { s } = useStore();
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const seen = useRef<Record<string, number>>({});
  const impulses = useRef<Impulse[]>([]);
  const [link, setLink] = useState(telemetry.link());
  const [tick, setTick] = useState(0);
  const [hover, setHover] = useState<{ node: FlowNode; x: number; y: number } | null>(null);
  const [sel, setSel] = useState<FlowNode | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [list, setList] = useState(false);
  const [pulseCount, setPulseCount] = useState(0);
  const sec = useRef<HTMLElement>(null);
  const spawned = useRef(0);                                          // impulses started by real events (exposed for tests as data-impulses)

  useEffect(() => telemetry.onLink(setLink), []);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 5000);                // recency of nodes (active / waiting) is re-evaluated
    return () => clearInterval(t);
  }, []);

  const model = useMemo(() => {
    const fn = kind === "data" ? dataModel : modelsModel;
    return fn(s, tele, (k) => seen.current[k] ?? null, Date.now(), link);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, s.connection, s.tf_meta, s.decision, s.symbol, s.account, tele, link, tick, pulseCount]);
  const modelRef = useRef(model);
  modelRef.current = model;
  const pos = useMemo(() => layout(model), [model.nodes.map((n) => n.id).join("|")]);   // eslint-disable-line react-hooks/exhaustive-deps
  const posRef = useRef(pos);
  posRef.current = pos;
  const filterRef = useRef(filter);
  filterRef.current = filter;
  const hoverRef = useRef<string | null>(null);
  hoverRef.current = hover?.node.id ?? sel?.id ?? null;

  // real events -> impulses along the edges of the matching route
  useEffect(() => telemetry.subscribe((e) => {
    seen.current[e.type] = e.at;
    const keys = [e.type];
    if ((e.type === "bar" || e.type === "bar_closed") && e.data?.tf) {
      seen.current[`bar:${e.data.tf}`] = e.at;
      keys.push(`bar:${e.data.tf}`);
    }
    if (reduced || document.visibilityState !== "visible") return;
    const m = modelRef.current;
    let n = 0;
    for (const k of keys) {
      for (const [a, b] of m.routes[k] || []) {
        if (impulses.current.length > 160) break;
        const tgt = m.nodes.find((x) => x.id === b);
        impulses.current.push({ a, b, t0: performance.now(), color: tgt?.status === "error" ? "#ff5f7a" : kind === "data" ? "#3fe6ff" : "#2fe6a0" });
        n++;
      }
    }
    if (n) {
      spawned.current += n;
      if (sec.current) sec.current.dataset.impulses = String(spawned.current);
    }
    if (n && (e.type === "decision" || e.type === "sh" || e.type === "dq")) setPulseCount((x) => (x + 1) % 1_000_000);
  }), [kind, reduced]);

  // render loop
  useEffect(() => {
    const c = canvas.current, host = wrap.current;
    if (!c || !host) return;
    const g = c.getContext("2d");
    if (!g) return;
    let raf = 0, running = false, w = 0, h = 0, dpr = 1, last = performance.now();
    let yaw = kind === "data" ? 0.3 : -0.4, pitch = 0.32, zoom = 1, drag: { x: number; y: number; moved: boolean } | null = null;
    const screen = new Map<string, { x: number; y: number; z: number; s: number }>();
    const motes = Array.from({ length: 36 }, () => ({ a: Math.random() * Math.PI * 2, r: 0.2 + Math.random() * 1.1, y: (Math.random() - 0.5) * 1.4, sp: 0.05 + Math.random() * 0.15 }));
    const resize = () => {
      w = host.clientWidth; h = host.clientHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
      c.style.width = `${w}px`; c.style.height = `${h}px`;
    };
    const project = (p: Pos) => {
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const x1 = p.x * cy - p.z * sy, z1 = p.x * sy + p.z * cy;
      const y2 = p.y * cp - z1 * sp, z2 = p.y * sp + z1 * cp;
      const f = 2.6 / (2.6 + z2);
      // a tall side column stretches the map vertically (up to 2.2x) so the graph fills the panel instead of floating in its middle
      const kx = Math.min(w, h) * 0.44 * zoom;
      const ky = h > w * 1.3 ? Math.min(h * 0.4 * zoom, kx * 2.2) : kx;
      return { x: w / 2 + x1 * f * kx, y: h / 2 - y2 * f * ky, z: z2, s: f };
    };
    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const m = modelRef.current, P = posRef.current, flt = filterRef.current, hov = hoverRef.current;
      const offline = telemetry.link() !== "OPEN";
      if (!drag && !reduced) yaw += dt * (offline ? 0.02 : 0.07);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      // decorative motes
      g.globalCompositeOperation = "lighter";
      for (const mo of motes) {
        if (!reduced) mo.a += dt * mo.sp;
        const p = project({ x: Math.cos(mo.a) * mo.r, y: mo.y, z: Math.sin(mo.a) * mo.r });
        g.fillStyle = `rgba(150,130,255,${0.18 * p.s})`;
        g.fillRect(p.x, p.y, 1.6 * p.s, 1.6 * p.s);
      }
      screen.clear();
      for (const n of m.nodes) { const p = P.get(n.id); if (p) screen.set(n.id, project(p)); }
      const byId = new Map(m.nodes.map((n) => [n.id, n]));
      // edges
      for (const e of m.edges) {
        const a = screen.get(e.a), b = screen.get(e.b), na = byId.get(e.a), nb = byId.get(e.b);
        if (!a || !b || !na || !nb) continue;
        const lit = hov && (hov === e.a || hov === e.b);
        const dim = !(matches(na, flt) || matches(nb, flt));
        const act = !offline && na.status === "active" && nb.status !== "offline";
        g.strokeStyle = lit ? "rgba(255,255,255,0.85)" : act ? `rgba(80,220,255,${dim ? 0.05 : 0.28})` : `rgba(140,130,200,${dim ? 0.03 : 0.12})`;
        g.lineWidth = lit ? 1.6 : 1;
        g.setLineDash(e.dashed ? [3, 4] : []);
        g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
      }
      g.setLineDash([]);
      // telemetry impulses (only from real events)
      const keep: Impulse[] = [];
      for (const im of impulses.current) {
        const k = (now - im.t0) / 900;
        if (k >= 1 || offline) continue;
        keep.push(im);
        const a = screen.get(im.a), b = screen.get(im.b);
        if (!a || !b) continue;
        const x = a.x + (b.x - a.x) * k, y = a.y + (b.y - a.y) * k;
        const gr = g.createRadialGradient(x, y, 0, x, y, 7);
        gr.addColorStop(0, im.color); gr.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = gr;
        g.beginPath(); g.arc(x, y, 7, 0, Math.PI * 2); g.fill();
      }
      impulses.current = keep;
      // nodes, far to near
      g.globalCompositeOperation = "source-over";
      const order = [...m.nodes].sort((a, b) => (screen.get(b.id)?.z ?? 0) - (screen.get(a.id)?.z ?? 0));
      const cand: { label: string; x: number; y: number; r: number; z: number; hot: boolean }[] = [];   // labels drawn after all nodes
      for (const n of order) {
        const p = screen.get(n.id);
        if (!p) continue;
        if (n.ring === 0) { drawEye(g, p.x, p.y, Math.min(w, h) * 0.085 * p.s * zoom, kind, offline, n.status, now, reduced); continue; }
        const dim = !matches(n, flt);
        const col = offline ? "#3d4054" : statusColor(n.status);
        const r = (n.ring === 1 ? 6 : n.ring === 2 ? 4.2 : 3.6) * p.s * (hov === n.id ? 1.6 : 1);
        g.globalAlpha = dim ? 0.18 : 1;
        const halo = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.2);
        halo.addColorStop(0, col + "88"); halo.addColorStop(1, col + "00");
        g.fillStyle = halo;
        g.beginPath(); g.arc(p.x, p.y, r * 3.2, 0, Math.PI * 2); g.fill();
        g.fillStyle = col;
        g.strokeStyle = "rgba(255,255,255,0.7)";
        g.lineWidth = 1;
        if (n.shape === "circle") { g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); g.fill(); }
        else { g.strokeStyle = col; g.lineWidth = 1.4; g.strokeRect(p.x - r, p.y - r, r * 2, r * 2); g.fillStyle = col + "55"; g.fillRect(p.x - r, p.y - r, r * 2, r * 2); }
        g.globalAlpha = 1;
        if ((n.ring === 1 && !dim) || hov === n.id) cand.push({ label: n.label, x: p.x, y: p.y, r, z: p.z, hot: hov === n.id });
      }
      // labels on dark pills, above every node and the eye core; nearest (and the hovered one) first, an overlapping label is skipped
      g.font = "600 11px Inter, Segoe UI, sans-serif";
      cand.sort((a, b) => (a.hot === b.hot ? a.z - b.z : a.hot ? -1 : 1));
      const placed: [number, number, number, number][] = [];
      for (const c of cand) {
        const tw = g.measureText(c.label).width + 8;
        let bx = c.x + c.r + 4;
        if (bx + tw > w - 2) bx = c.x - c.r - 4 - tw;                  // keep inside the canvas
        const box: [number, number, number, number] = [Math.max(2, bx), c.y - 8, tw, 16];
        const hit = placed.some(([x, y, bw, bh]) => box[0] < x + bw && box[0] + box[2] > x && box[1] < y + bh && box[1] + box[3] > y);
        if (hit && !c.hot) continue;
        placed.push(box);
        g.fillStyle = "rgba(6,7,18,0.86)";
        g.fillRect(box[0], box[1], box[2], box[3]);
        g.fillStyle = "#e8ecff";
        g.fillText(c.label, box[0] + 4, c.y + 4);
      }
      if (offline) {
        g.fillStyle = "rgba(6,7,18,0.72)";
        g.fillRect(w / 2 - 120, h - 40, 240, 26);
        g.fillStyle = "#ff8fa0";
        g.font = "600 12px Inter, Segoe UI, sans-serif";
        g.textAlign = "center";
        g.fillText("OFFLINE – brak połączenia z botem", w / 2, h - 22);
        g.textAlign = "start";
      }
    };
    let drawnAt = 0;
    const loop = (now: number) => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (reduced && !drag && now - drawnAt < 500) return;            // reduced motion: a still map refreshed twice a second
      drawnAt = now;
      draw(now);
    };
    let visible = true;
    const io = new IntersectionObserver((e) => { visible = e[0]?.isIntersecting ?? true; sync(); });
    const sync = () => {
      const should = visible && document.visibilityState === "visible";
      if (should && !running) { running = true; last = performance.now(); raf = requestAnimationFrame(loop); }
      else if (!should && running) { running = false; cancelAnimationFrame(raf); }
    };
    const pick = (x: number, y: number): FlowNode | null => {
      let best: FlowNode | null = null, bd = 16;
      for (const n of modelRef.current.nodes) {
        const p = screen.get(n.id);
        if (!p) continue;
        const d = Math.hypot(p.x - x, p.y - y) - (n.ring === 0 ? Math.min(w, h) * 0.06 : 0);
        if (d < bd) { bd = d; best = n; }
      }
      return best;
    };
    const local = (e: PointerEvent | WheelEvent) => { const r = c.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    const onDown = (e: PointerEvent) => { const p = local(e); drag = { x: p.x, y: p.y, moved: false }; c.setPointerCapture(e.pointerId); };
    const onMove = (e: PointerEvent) => {
      const p = local(e);
      if (drag) {
        const dx = p.x - drag.x, dy = p.y - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        if (drag.moved) { yaw += dx * 0.008; pitch = Math.max(-0.9, Math.min(0.9, pitch + dy * 0.006)); drag.x = p.x; drag.y = p.y; }
        return;
      }
      const n = pick(p.x, p.y);
      setHover(n ? { node: n, x: p.x, y: p.y } : null);
      c.style.cursor = n ? "pointer" : "grab";
    };
    const onUp = (e: PointerEvent) => {
      const p = local(e);
      if (drag && !drag.moved) { const n = pick(p.x, p.y); setSel(n); }
      drag = null;
    };
    const onLeave = () => setHover(null);
    const onWheel = (e: WheelEvent) => { e.preventDefault(); zoom = Math.max(0.6, Math.min(2.4, zoom * (e.deltaY > 0 ? 0.92 : 1.08))); };
    resize();
    draw(performance.now());
    window.addEventListener("resize", resize);
    c.addEventListener("pointerdown", onDown);
    c.addEventListener("pointermove", onMove);
    c.addEventListener("pointerup", onUp);
    c.addEventListener("pointerleave", onLeave);
    c.addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("visibilitychange", sync);
    io.observe(host);
    sync();
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      io.disconnect();
      window.removeEventListener("resize", resize);
      c.removeEventListener("pointerdown", onDown);
      c.removeEventListener("pointermove", onMove);
      c.removeEventListener("pointerup", onUp);
      c.removeEventListener("pointerleave", onLeave);
      c.removeEventListener("wheel", onWheel);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [kind, reduced]);

  const now = Date.now();
  const filters: [Filter, string][] = [["all", "Wszystkie"], ["active", "Aktywne"], ["problems", "Błędy / offline"],
    ...(kind === "models" ? [["SCALPING", "SCALPING"], ["HEDGING", "HEDGING"], ["S01–S12", "S01–S12"]] as [Filter, string][] : [])];
  const counts = model.nodes.reduce((acc, n) => ({ ...acc, [n.status]: (acc[n.status] || 0) + 1 }), {} as Record<NodeStatus, number>);
  return (
    <section ref={sec} className="wz-flow" data-testid={`wz-flow-${kind}`} data-link={link} data-nodes={model.nodes.length}
      aria-label={`Mapa przepływu modeli – ${model.title}`}>
      <header className="wz-flow-head">
        <h2>{model.title}</h2>
        <span className="wz-flow-sub">mapa przepływu modułów bota{link !== "OPEN" ? " · OFFLINE" : ""}</span>
      </header>
      <div className="wz-flow-filters" role="group" aria-label="Filtr węzłów">
        {filters.map(([f, l]) => (
          <button key={f} className={cls("wz-mini", filter === f && "on")} aria-pressed={filter === f} onClick={() => setFilter(f)} data-testid={`wz-flow-filter-${kind}-${f}`}>{l}</button>))}
      </div>
      <div className="wz-flow-canvas" ref={wrap}>
        <canvas ref={canvas} data-testid={`wz-flow-canvas-${kind}`} role="img"
          aria-label={`${model.title}: ${model.nodes.length} węzłów – aktywne ${counts.active ?? 0}, oczekujące ${counts.waiting ?? 0}, błędy ${counts.error ?? 0}, offline ${counts.offline ?? 0}`} />
        {hover && (
          <div className="wz-tip" style={{ left: Math.min(hover.x + 14, (wrap.current?.clientWidth ?? 300) - 230), top: hover.y + 12 } as CSSProperties}
            role="tooltip" data-testid={`wz-flow-tip-${kind}`}>
            <b>{hover.node.label}</b>
            <span className={cls("wz-st", hover.node.status)}>{STATUS_PL[hover.node.status]}</span>
            <span>{hover.node.detail}</span>
            <span className="wz-dim">Ostatnia praca: {ago(hover.node.lastAt, now)}</span>
          </div>)}
      </div>
      <div className="wz-flow-legend" aria-hidden="true">
        {(["active", "waiting", "error", "disabled", "offline"] as NodeStatus[]).map((st) => (
          <span key={st}><i style={{ background: statusColor(st) }} />{STATUS_PL[st]} {counts[st] ?? 0}</span>))}
      </div>
      <button className="wz-mini wz-flow-listbtn" aria-expanded={list} onClick={() => setList(!list)} data-testid={`wz-flow-list-${kind}`}>Lista modułów</button>
      {list && (
        <ul className="wz-flow-list" data-testid={`wz-flow-listbox-${kind}`}>
          {model.nodes.filter((n) => matches(n, filter)).map((n) => (
            <li key={n.id}><button className="wz-linklike" onClick={() => setSel(n)}>
              <i style={{ background: statusColor(n.status) }} aria-hidden="true" />{n.label}<span className="wz-dim"> – {STATUS_PL[n.status]}</span></button></li>))}
        </ul>)}
      {sel && (
        <div className="wz-flow-detail" role="dialog" aria-label={`Szczegóły: ${sel.label}`} data-testid={`wz-flow-detail-${kind}`}>
          <header><b>{sel.label}</b><button className="wz-mini" onClick={() => setSel(null)} aria-label="Zamknij szczegóły">✕</button></header>
          <p><span className={cls("wz-st", sel.status)}>{STATUS_PL[sel.status]}</span> {sel.detail}</p>
          <dl>
            <dt>Ostatnia praca</dt><dd>{ago(sel.lastAt, now)}</dd>
            {sel.topics.length > 0 && <><dt>Zdarzenia</dt><dd>{sel.topics.join(", ")}</dd></>}
            {sel.metrics.map(([k, v], i) => <Fragment key={`${i}-${k}`}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
          </dl>
          {sel.href && <a className="wz-link" href={sel.href}>Otwórz powiązany widok →</a>}
        </div>)}
    </section>);
}

function drawEye(g: CanvasRenderingContext2D, x: number, y: number, r: number, kind: string, offline: boolean, status: NodeStatus, now: number, reduced: boolean) {
  const pulse = offline || reduced ? 0 : 0.06 * Math.sin(now / 420);
  const base = offline ? "#4a4d63" : kind === "data" ? "#b46bff" : "#2fe6a0";
  const R = r * (1 + pulse);
  const halo = g.createRadialGradient(x, y, R * 0.2, x, y, R * 2.4);
  halo.addColorStop(0, base + "66"); halo.addColorStop(1, base + "00");
  g.fillStyle = halo;
  g.beginPath(); g.arc(x, y, R * 2.4, 0, Math.PI * 2); g.fill();
  const iris = g.createRadialGradient(x, y, R * 0.15, x, y, R);
  iris.addColorStop(0, offline ? "#9a9db0" : "#ffe9ff"); iris.addColorStop(0.35, base); iris.addColorStop(1, "#0b0820");
  g.fillStyle = iris;
  g.beginPath(); g.ellipse(x, y, R, R * 0.92, 0, 0, Math.PI * 2); g.fill();
  g.fillStyle = "#07040f";
  g.beginPath(); g.ellipse(x, y, R * 0.16, R * 0.62, 0, 0, Math.PI * 2); g.fill();
  if (status === "active" && !offline) {
    g.strokeStyle = "rgba(255,255,255,0.5)";
    g.lineWidth = 1;
    g.beginPath(); g.arc(x, y, R * 1.25, 0, Math.PI * 2); g.stroke();
  }
}
