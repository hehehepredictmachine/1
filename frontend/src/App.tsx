// PepeMarketWizard: routable pages (grouped menu) inside one shared frame. The store (one WebSocket) is provided ABOVE this component (main.tsx),
// so switching pages never reconnects; pages only choose what to show.
import { useEffect, useState } from "react";
import { BackgroundLayer, useAppearance } from "./appearance";
import { migrateLegacyViews } from "./chartview";
import { ModeDialog, PowerDialog, SettingsModal } from "./components/Dialogs";
import AppShell from "./components/layout/AppShell";
import { ThemeDialog } from "./components/ThemeDialog";
import AiAnalysisPage from "./pages/AiAnalysisPage";
import BotChartsPage from "./pages/BotChartsPage";
import SetupRequirementsPage from "./pages/SetupRequirementsPage";
import { ContextPage, DashboardPage, DiagnosticsPage, IndicatorsPage, JournalPage, PatternsPage, PositionsPage, SignalAnalysisPage, TestsPage } from "./pages/AnalyticsPages";
import { NeuralPage } from "./components/NeuralSystem";
import { StructurePage } from "./components/StructureIntel";
import ScalpMtfPage from "./pages/ScalpMtfPage";
import { StrategyPage } from "./components/ShPanels";
import NeuralCyberpunk from "./nc/NeuralCyberpunk";
import { DataPage, LabDashboardTop, LabSettingsPage, ModelsPage, ResearchPage, SetupsPage } from "./pages/LabPages";
import { PAGES, TERMINAL_PAGE_IDS, useRoute } from "./router";
import TerminalShell from "./features/shell/TerminalShell";
import TradingIntelligencePage from "./features/trading-intelligence/pages/TradingIntelligencePage";
import AiNeuralLabPage from "./features/ai-neural-lab/pages/AiNeuralLabPage";
import SystemControlPage from "./features/system-control/pages/SystemControlPage";
import { useStore } from "./store";
import { UiCtx } from "./ui";
import { cls } from "./util";

migrateLegacyViews();          // 1.10: zoom saved under the old positional chart ids -> new ids per page and TF (once)

export default function App() {
  const { s } = useStore();
  const route = useRoute();
  const [settings, setSettings] = useState(false);
  const [mode, setMode] = useState(false);
  const [power, setPower] = useState(false);
  const [look, setLook] = useState(false);
  const { prefs } = useAppearance();

  useEffect(() => {
    if (s.loaded && s.first_run_completed === false) setSettings(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loaded]);
  useEffect(() => {
    document.title = `PepeMarketWizard – ${PAGES.find((p) => p.id === route.page)?.label ?? ""}`;
  }, [route.page]);

  if (!s.loaded) return <><BackgroundLayer /><div className="loading">PepeMarketWizard – łączenie z lokalnym backendem…</div></>;
  const terminal = TERMINAL_PAGE_IDS.includes(route.page);
  return (
    <UiCtx.Provider value={{ openSettings: () => setSettings(true) }}>
      <div className={cls("app", s.synthetic && "synthetic", "anim-" + prefs.mode.toLowerCase(), terminal && "app-terminal")}>
        {!terminal && <BackgroundLayer />}
        {s.synthetic && !terminal && <div className="synthetic-banner">DANE PRZYKŁADOWE (SYNTETYCZNE) – symulator terminala, oddzielna baza. To nie są notowania MT5 ani wyniki rachunku.</div>}
        {terminal ? (
          <TerminalShell page={route.page} asOf={route.params.get("as_of")}>
            {route.page === "trading-intelligence" && <TradingIntelligencePage />}
            {route.page === "ai-neural-lab" && <AiNeuralLabPage />}
            {route.page === "system-control" && <SystemControlPage />}
          </TerminalShell>) :
        route.page === "nc" ? <NeuralCyberpunk route={route} /> :
        <AppShell page={route.page} onSettings={() => setSettings(true)} onPower={() => setPower(true)} onMode={() => setMode(true)} onLook={() => setLook(true)}>
          {route.page === "ai" && <AiAnalysisPage />}
          {route.page === "wykresy" && <BotChartsPage route={route} />}
          {route.page === "scalp-mtf" && <ScalpMtfPage params={route.params} />}
          {route.page === "warunki" && <SetupRequirementsPage route={route} />}
          {route.page === "pulpit" && <><LabDashboardTop /><DashboardPage /></>}
          {route.page === "setupy" && <SetupsPage />}
          {route.page === "strategie" && <StrategyPage />}
          {route.page === "modele" && <ModelsPage />}
          {route.page === "neural" && <NeuralPage params={route.params} />}
          {route.page === "struktura" && <StructurePage />}
          {route.page === "badania" && <ResearchPage />}
          {route.page === "dane" && <DataPage />}
          {route.page === "ustawienia" && <LabSettingsPage />}
          {route.page === "kontekst" && <ContextPage />}
          {route.page === "indykatory" && <IndicatorsPage />}
          {route.page === "sygnal" && <SignalAnalysisPage />}
          {route.page === "formacje" && <PatternsPage />}
          {route.page === "pozycje" && <PositionsPage />}
          {route.page === "dziennik" && <JournalPage />}
          {route.page === "testy" && <TestsPage />}
          {route.page === "diagnostyka" && <DiagnosticsPage />}
        </AppShell>}
        {settings && <SettingsModal onClose={() => setSettings(false)} />}
        {mode && <ModeDialog onClose={() => setMode(false)} />}
        {power && <PowerDialog onClose={() => setPower(false)} />}
        {look && <ThemeDialog onClose={() => setLook(false)} />}
        <footer className="footer">
          PepeMarketWizard {s.app_version} · kontrakt API {s.contract} · wykresy: TradingView Lightweight Charts™ (Apache-2.0) – źródło notowań: wyłącznie Twój terminal MT5 ·
          Narzędzie analityczne – nie gwarantuje zysków.
        </footer>
      </div>
    </UiCtx.Provider>
  );
}
