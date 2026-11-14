// 1.39 MAIN MENU – Galaxy V2 (FULL NEURAL MESH). 1:1 visual port of the approved reference (galaxyEngine.ts + galaxy.css): seven
// planets, WTC PEPE in the centre, the full K7 mesh (21/21 animated links), side AI emitters, the bottom electric band and the live
// editor "Projektuj" (drag, name, size, position, colour, effects, add / delete planet, JSON export / import, reset).
// Integration: every planet opens a REAL screen of the bot (route), a planet without a route shows "Niepołączony moduł".
// The status pill comes from the backend state only: MT5 ONLINE / DEMO SIM / OFFLINE / UNKNOWN - never a fake "AI ONLINE".
// The previous menu (Neural City, 1.34-1.38) stays available under #/neural-city.
import { useEffect, useRef } from "react";
import { navigate, PAGES, type Page } from "../../router";
import { useStore } from "../../store";
import { mountGalaxy } from "./galaxyEngine";
import { GALAXY_MARKUP } from "./galaxyMarkup";
import "./galaxy.css";

const ROUTES: Page[] = ["pepe-wtc", "pepe-signal", "lightning", "profits", "modele", "sygnal", "ustawienia", "trening", "strategy-lab",
  "strategie", "wykresy", "kontekst", "pozycje", "dziennik", "precision", "dyscypline", "wind", "control", "diagnostyka", "neural-city"];

export type GalaxyStatus = { text: string; tone: "ok" | "warn" | "bad" };
/** Status pill text from the real backend state (no state -> UNKNOWN, synthetic feed -> DEMO SIM). */
export function galaxyStatus(s: Record<string, any>): GalaxyStatus {
  if (!s || !s.loaded) return { text: "UNKNOWN", tone: "warn" };
  if (s.synthetic) return { text: "DEMO SIM · BEZ MT5", tone: "warn" };
  const st = s.connection?.state;
  if (!st) return { text: "UNKNOWN", tone: "warn" };
  if (st === "CONNECTED") {
    const mode = s.mode?.mode ? ` · ${s.mode.mode}` : "";
    return { text: `MT5 ONLINE${mode}`, tone: "ok" };
  }
  return { text: `MT5 OFFLINE (${String(st)})`, tone: "bad" };
}

export default function GalaxyMenu() {
  const { s } = useStore();
  const ref = useRef<HTMLDivElement>(null);
  const stateRef = useRef(s);
  stateRef.current = s;
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const routes = ROUTES.map((r) => ({ value: r, label: `${PAGES.find((p) => p.id === r)?.short ?? r} (#/${r})` }));
    return mountGalaxy(root, {
      routes,
      open: (route) => { if (route) navigate(route as Page); },
      status: () => galaxyStatus(stateRef.current),
    });
  }, []);
  return <div className="pmw-galaxy" ref={ref} data-testid="galaxy-menu" dangerouslySetInnerHTML={{ __html: GALAXY_MARKUP }} />;
}
