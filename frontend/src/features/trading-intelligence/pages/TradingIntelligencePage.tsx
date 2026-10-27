// Trading Intelligence (approved mockup 01): account, market overview (1/4/6 charts), Signal Intelligence with the separate answers
// "why no signal" / "why no order", positions and results. Every value comes from the engine and the MT5 terminal; missing = "—".
import { useState } from "react";
import { useStore } from "../../../store";
import PageBanner from "../../shell/PageBanner";
import AccountCards from "../components/AccountCards";
import MarketCharts from "../components/MarketCharts";
import PositionsStrip from "../components/PositionsStrip";
import SignalIntelligence from "../components/SignalIntelligence";

export default function TradingIntelligencePage() {
  const { s } = useStore();
  const [chartMode, setChartMode] = useState(false);
  const linked = s.ws === "OPEN" && s.connection?.state === "CONNECTED";
  const source = !linked ? ["t-badge-gold", "BRAK DANYCH MT5"] : s.synthetic ? ["t-badge-gold", "DANE SYNTETYCZNE"]
    : ["t-badge-ok", `DANE MT5 · ${s.account?.trade_mode ?? "?"}`];
  return (
    <div className="t-page" data-testid="page-trading-intelligence">
      <PageBanner testId="ti-banner" kicker="Pepe Market Wizard / Rynek" title="Trading Intelligence" subtitle="Twój widok rynku, setupów i rachunku."
        badges={<span className={`t-badge ${source[0]}`} data-testid="ti-source">{source[1]}</span>}
        actions={<button className="t-btn t-btn-acc" aria-pressed={chartMode} onClick={() => setChartMode(!chartMode)} data-testid="ti-chart-mode-btn">Tryb wykresów</button>} />
      <AccountCards />
      <div className="t-ti-grid">
        <MarketCharts modeOpen={chartMode} onModeClose={() => setChartMode(false)} />
        <SignalIntelligence />
      </div>
      <PositionsStrip />
    </div>);
}
