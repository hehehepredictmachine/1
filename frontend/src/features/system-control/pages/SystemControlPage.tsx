// System Control Center (stage 1: layout only, no controls). Mode changes, LIVE activation and model deployment stay in the existing
// panel until stage 4 wires them to the same backend checks; the header already shows the confirmed MT5 status.
import { NotIntegrated } from "../../shell/StateView";

export default function SystemControlPage() {
  return (
    <div className="t-page" data-testid="page-system-control">
      <div className="t-page-head">
        <h1>System Control Center</h1>
        <p className="t-dim">Tryby LIVE / DEMO, połączenie MT5, wdrożenia modeli, błędy i rozłączenia.</p>
      </div>
      <div className="t-two">
        <NotIntegrated title="LIVE / DEMO" stage={4} testId="sc-live"
          sources={["POST /api/v1/mode (fraza „LIVE <login>” sprawdzana w backendzie)", "POST /api/v1/kill (STOP nowych wejść)"]} />
        <NotIntegrated title="MT5 – szczegóły połączenia" stage={4} testId="sc-mt5"
          sources={["WS connection / clock", "GET /api/v1/diagnostics"]} />
      </div>
      <div className="t-two">
        <NotIntegrated title="Wdrożenia modeli" stage={4} testId="sc-deploy"
          sources={["GET /api/v1/training/models", "POST /api/v1/training/sh/promote", "POST /api/v1/ml/rollback"]} />
        <NotIntegrated title="Błędy i rozłączenia" stage={4} testId="sc-errors"
          sources={["WS log", "GET /api/v1/logs", "GET /api/v1/health"]} />
      </div>
    </div>);
}
