// Strona testu 1:1 ekranu CHARTS (pakiet update_charts, K1 §3). Budowana WYŁĄCZNIE w trybie `vite build --mode test`
// (charts-test.html nie trafia do buildu produkcyjnego). Prawdziwy ForexScene + ekran CHARTS na statycznym store: bez WebSocketu,
// bez zapytań do API, bez pollingu; dane wyłącznie z fixture przez window.__PMW_TEST__.charts.load(fx).
import { createRoot } from "react-dom/client";
import ForexScene from "../features/forex/ForexScene";
import { StaticStoreProvider, type AppState } from "../store";
import "../styles.css";

const STATE: AppState = { loaded: true, ws: "CLOSED", barTick: {}, analysisSeq: 0, synthetic: false, mode: { mode: "PAPER" } };

createRoot(document.getElementById("root")!).render(
  <StaticStoreProvider value={STATE}>
    <ForexScene screen={null} fromMenu={false} onSystem={() => undefined} testMode />
  </StaticStoreProvider>,
);
