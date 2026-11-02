// Centre of the main menu: three 3D towers (lazy three.js chunk) with accessible HTML buttons under each tower. Mouse hover, keyboard
// focus and touch give the same highlight; click / Enter / tap opens the tower's view after a short camera move and portal
// (~0.6 s, none with reduced motion). Without WebGL the same buttons are shown with drawn silhouettes - navigation never depends on
// the 3D scene. Opening a tower only navigates: it never touches positions or the trading mode.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { navigate } from "../../router";
import { cls } from "../../util";
import { TOWERS, type TowerId } from "./assets";
import type { Anchor, TowerScene } from "./TowerScene";
import { webglAvailable, webglForced } from "./webgl";

const SILHOUETTE: Record<TowerId, string> = {
  precision: "M44 118 L48 54 L42 50 L60 30 L78 50 L72 54 L76 118 Z M60 4 L64 24 L56 24 Z",
  dyscypline: "M18 118 L22 60 L30 60 L30 44 L40 44 L40 30 L50 30 L60 6 L70 30 L80 30 L80 44 L90 44 L90 60 L98 60 L102 118 Z M50 118 L50 92 Q60 80 70 92 L70 118 Z",
  profits: "M34 118 L38 52 L82 52 L86 118 Z M30 52 L90 52 L86 44 L34 44 Z M60 40 A14 14 0 1 1 60.1 40 Z",
};

export default function TowerMenu({ onHover, reduced }: { onHover: (id: TowerId | null) => void; reduced: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<TowerScene | null>(null);
  const [gl, setGl] = useState<"loading" | "on" | "off">(() => (webglAvailable() ? "loading" : "off"));
  const [slowFps, setSlowFps] = useState<number | null>(null);         // 3D switched off because it was measured too slow
  const [anchors, setAnchors] = useState<Record<TowerId, Anchor> | null>(null);
  const [hover, setHover] = useState<TowerId | null>(null);
  const [leaving, setLeaving] = useState<TowerId | null>(null);
  const leavingRef = useRef(false);                                   // the scene keeps the first open(): guard through a ref, not state
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  const changeHover = useCallback((id: TowerId | null) => {
    setHover(id);
    hoverRef.current(id);
  }, []);

  const open = useCallback(async (id: TowerId) => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(id);
    hoverRef.current(id);
    if (!reduced) await Promise.all([scene.current?.select(id) ?? Promise.resolve(), new Promise((r) => setTimeout(r, 420))]);
    navigate(id);
  }, [reduced]);

  useEffect(() => {
    if (gl === "off") return;
    let alive = true;
    let sc: TowerScene | null = null;
    const c = canvas.current;
    const lost = () => setGl("off");
    c?.addEventListener("wz-webgl-lost", lost);
    import("./TowerScene").then(({ TowerScene: Scene }) => {
      if (!alive || !canvas.current || !host.current) return;
      try {
        sc = new Scene(canvas.current, host.current, {
          onHover: changeHover, onSelect: (id) => { void open(id); }, onAnchors: setAnchors, reduced,
          onTooSlow: (fps) => { if (!webglForced()) { setSlowFps(fps); setGl("off"); } },
        });
        scene.current = sc;
        setGl("on");
      } catch {
        setGl("off");
      }
    }).catch(() => setGl("off"));
    return () => {
      alive = false;
      c?.removeEventListener("wz-webgl-lost", lost);
      sc?.dispose();
      scene.current = null;
    };
    // the scene is built once per mount; open() reads the latest state through refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl === "off", reduced]);

  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const n = (i + (e.key === "ArrowRight" ? 1 : TOWERS.length - 1)) % TOWERS.length;
    (document.querySelector(`[data-testid=wz-tower-${TOWERS[n].id}]`) as HTMLButtonElement | null)?.focus();
  };

  const active = TOWERS.find((t) => t.id === (leaving ?? hover));
  return (
    <section className={cls("wz-towers", gl === "off" && "wz-towers-flat")} aria-label="Trzy wieże – nawigacja" data-testid="wz-towers" data-webgl={gl}
      data-webgl-reason={gl === "off" ? (slowFps != null ? "slow" : "unavailable") : undefined}
      data-hover={hover ?? ""}>
      <div className="wz-scene" ref={host} data-testid="wz-scene" aria-hidden="true">
        {gl !== "off" && <canvas ref={canvas} className="wz-canvas" data-testid="wz-canvas" />}
      </div>
      <div className="wz-tower-row" role="list">
        {TOWERS.map((t, i) => {
          const a = anchors?.[t.id];
          const pos: CSSProperties = gl === "on" && a ? { left: a.x, top: a.y } : {};
          return (
            <div key={t.id} role="listitem" className={cls("wz-tower-slot", gl === "on" && a && "anchored")} style={pos}>
              <button className={cls("wz-tower-btn", hover === t.id && "hot", leaving === t.id && "leaving")} data-tower={t.id} data-testid={`wz-tower-${t.id}`}
                style={{ "--tw": t.accent, "--tw2": t.accent2 } as CSSProperties} aria-describedby={`wz-desc-${t.id}`}
                onMouseEnter={() => { changeHover(t.id); scene.current?.setFocus(t.id); }} onMouseLeave={() => { changeHover(null); scene.current?.setFocus(null); }}
                onFocus={() => { changeHover(t.id); scene.current?.setFocus(t.id); }} onBlur={() => { changeHover(null); scene.current?.setFocus(null); }}
                onClick={() => { void open(t.id); }} onKeyDown={(e) => onKey(e, i)}>
                {gl === "off" && (
                  <svg viewBox="0 0 120 120" className="wz-sil" aria-hidden="true">
                    <path d={SILHOUETTE[t.id]} />
                  </svg>)}
                <span className="wz-tower-name">{t.name}</span>
                <span className="wz-tower-role">{t.role}</span>
              </button>
              <span id={`wz-desc-${t.id}`} className="wz-sr">{t.desc}</span>
            </div>);
        })}
      </div>
      <p className={cls("wz-tower-desc", active && "on")} aria-live="polite" data-testid="wz-tower-desc">
        {active ? <><b style={{ color: active.accent }}>{active.name}</b> – {active.desc}</> : "Wskaż wieżę, aby zobaczyć jej opis. Kliknięcie lub Enter otwiera widok."}
      </p>
      {gl === "off" && (
        <p className="wz-note wz-nowebgl" data-testid="wz-nowebgl">{slowFps != null
          ? <>Grafika 3D wyłączona automatycznie – ten komputer rysuje ją bez karty graficznej (zmierzono {slowFps} kl./s), a bot potrzebuje
            procesora. Wieże jako przyciski; cała nawigacja działa. Wymuszenie 3D: adres <code>#/menu?webgl=1</code>.</>
          : "Tryb bez WebGL – wieże jako przyciski; cała nawigacja działa."}</p>)}
      {leaving && (
        <div className="wz-portal" aria-hidden="true" style={{ "--tw": TOWERS.find((t) => t.id === leaving)!.accent } as CSSProperties} data-testid="wz-portal" />)}
    </section>);
}
