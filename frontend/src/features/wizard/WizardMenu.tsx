// Main menu: the tower with purple lightning as the base background (parallax + live fog, dust, lightning and a cursor light in the
// colour of the indicated tower), three 3D towers in the centre (Precision, Dyscypline, Profits) and the two model-flow maps on the
// sides. On narrow screens the maps move into collapsible panels; the towers stay first.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";
import { TOWERS, WIZARD_ASSETS, type TowerId } from "./assets";
import BackdropFx from "./BackdropFx";
import FlowGraph from "./FlowGraph";
import TowerMenu from "./TowerMenu";
import { prefersReducedMotion } from "./webgl";

/** /api/v1/telemetry every 15 s while the menu is open (one request for both maps). */
export function useTelemetryModules() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => apiGet("/api/v1/telemetry")
      .then((x: any) => { if (alive) { setD({ ...x, _received_at: Date.now() }); setErr(null); } })
      .catch((e: any) => { if (alive) setErr(String(e?.message || e)); });
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return { d, err };
}

function useWide(min = 1100): boolean {
  const q = `(min-width: ${min}px)`;
  const [wide, setWide] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const f = () => setWide(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [q]);
  return wide;
}

export default function WizardMenu() {
  const reduced = prefersReducedMotion();
  const [hover, setHover] = useState<TowerId | null>(null);
  const tele = useTelemetryModules();
  const img = useRef<HTMLImageElement>(null);
  const wide = useWide();
  const accent = TOWERS.find((t) => t.id === hover)?.accent ?? "#9b5cff";
  const side = (kind: "data" | "models", title: string) => (
    <details className={`wz-side wz-side-${kind}`} open={wide || undefined} data-testid={`wz-side-${kind}`}>
      <summary>{title}</summary>
      <div className="wz-side-body">
        <FlowGraph kind={kind} tele={tele.d} reduced={reduced} />
        {tele.err && <p className="wz-note" data-testid={`wz-tele-err-${kind}`}>Telemetria modułów niedostępna: {tele.err}</p>}
      </div>
    </details>);
  return (
    <div className="wz-menu" data-testid="page-menu" data-hover={hover ?? ""}>
      <div className="wz-menu-bg" aria-hidden="true" data-testid="wz-menu-bg" data-asset={WIZARD_ASSETS.menuBackground.file}>
        <img ref={img} src={WIZARD_ASSETS.menuBackground.url} alt="" draggable={false} />
        <div className="wz-menu-shade" style={{ "--glow": accent } as React.CSSProperties} />
      </div>
      <BackdropFx accent={accent} lightning imgRef={img} reduced={reduced} />
      <div className="wz-menu-grid">
        {side("data", "Mapa przepływu danych i analiz")}
        <TowerMenu onHover={setHover} reduced={reduced} />
        {side("models", "Mapa modeli, agregacji i decyzji")}
      </div>
    </div>);
}
