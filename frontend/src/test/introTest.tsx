// Strona testu 1:1 intro 3D (pakiet update_intro3d, SC3 §5). Budowana WYŁĄCZNIE w trybie `vite build --mode test` (intro-test.html nie trafia
// do buildu produkcyjnego). Prawdziwe menu główne (CinematicMenu) w fazie boot z intro na pełnym ekranie, jak REF_C po otwarciu; statyczny
// store (bez WebSocketu i API); window.__PMW_TEST__.intro.seek(t) wstrzymuje intro i rysuje klatkę t (poziom jakości PEŁNY).
import { createRoot } from "react-dom/client";
import CinematicMenu from "../features/cinematic/CinematicMenu";
import { StaticStoreProvider, type AppState } from "../store";
import "../styles.css";

const STATE: AppState = { loaded: true, ws: "CLOSED", barTick: {}, analysisSeq: 0, synthetic: false, mode: { mode: "PAPER" } };

createRoot(document.getElementById("root")!).render(
  <StaticStoreProvider value={STATE}>
    <CinematicMenu testIntro />
  </StaticStoreProvider>,
);
