// Trading Intelligence (stage 1: layout only). Every section says it is not integrated yet and lists the existing sources it will use
// (docs/PEPE_UI_API_MAP.md §2) - no placeholder numbers, prices or statuses.
import { NotIntegrated, StateView } from "../../shell/StateView";

const CHART_TFS = ["M5", "M15", "H1", "H4"];

export default function TradingIntelligencePage() {
  return (
    <div className="t-page" data-testid="page-trading-intelligence">
      <div className="t-page-head">
        <h1>Trading Intelligence</h1>
        <p className="t-dim">Rynek, sygnały, ryzyko i podgląd zlecenia – na istniejących danych i zabezpieczeniach bota.</p>
      </div>
      <div className="t-ti-grid">
        <section className="t-card t-pending" aria-label="Market Overview" data-testid="ti-market" data-integration="NOT_INTEGRATED">
          <header className="t-card-head"><h2>Market Overview</h2><span className="t-badge t-badge-muted">etap 2 – nie zintegrowane</span></header>
          <div className="t-chart-grid">
            {CHART_TFS.map((tf) => (
              <div key={tf} className="t-chart-slot" data-tf={tf} aria-label={`Wykres ${tf}`}>
                <span className="t-chart-tf">{tf}</span>
                <StateView state="empty" detail="wykres zostanie podłączony do /api/v1/candles" />
              </div>))}
          </div>
          <ul className="t-sources" aria-label="Planowane źródła danych">
            {["GET /api/v1/candles?tf=", "WS bar / bar_closed", "GET /api/v1/zones/map", "GET /api/v1/liquidity/sessions", "WS decision (wejście / SL / TP)"].map((x) =>
              <li key={x}><code>{x}</code></li>)}
          </ul>
        </section>
        <NotIntegrated title="Signal Intelligence" stage={2} testId="ti-signals"
          sources={["GET /api/v1/signals", "GET /api/v1/setups", "GET /api/v1/sh", "GET /api/v1/eval/assessments", "GET /api/v1/mm/live (tablica dowodów)"]} />
      </div>
      <div className="t-two">
        <NotIntegrated title="Risk & Performance" stage={2} testId="ti-risk"
          sources={["WS positions / orders / account", "GET /api/v1/eval/exposure", "GET /api/v1/stats?mode="]} />
        <NotIntegrated title="Order Preview" stage={2} testId="ti-order"
          sources={["GET /api/v1/decision → POST /api/v1/execute", "POST /api/v1/manual/plan → /manual/intents → /execute"]}>
          <p className="t-note">Podgląd nigdy nie wysyła zlecenia. Wysłanie wymaga jawnego potwierdzenia, a backend ponownie sprawdza warunki tuż przed wysłaniem.</p>
        </NotIntegrated>
      </div>
    </div>);
}
