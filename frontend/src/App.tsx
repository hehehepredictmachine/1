// PepeMarketWizard: routable pages (grouped menu) inside one shared frame. The store (one WebSocket) is provided ABOVE this component (main.tsx),
// so switching pages never reconnects; pages only choose what to show.
import { lazy, Suspense, useEffect, useState } from "react";
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
import { CULT_PAGE_IDS, PAGES, TERMINAL_PAGE_IDS, WIZARD_PAGE_IDS, useRoute } from "./router";
import Launcher, { launcherNeeded } from "./features/cult/Launcher";
import WizardShell from "./features/wizard/WizardShell";
import { TOWERS } from "./features/wizard/assets";
import TerminalShell from "./features/shell/TerminalShell";
import TradingIntelligencePage from "./features/trading-intelligence/pages/TradingIntelligencePage";
import AiNeuralLabPage from "./features/ai-neural-lab/pages/AiNeuralLabPage";
import SystemControlPage from "./features/system-control/pages/SystemControlPage";
import { useStore } from "./store";
import { UiCtx } from "./ui";
import { cls } from "./util";

// tower views and the 1.32 CULT screens: lazy chunks
const NeuralCityMenu = lazy(() => import("./features/neural-city/NeuralCityMenu"));
const LightningTower = lazy(() => import("./features/cult/LightningTower"));
const WindPortal = lazy(() => import("./features/cult/WindPortal"));
const ControlTower = lazy(() => import("./features/cult/ControlTower"));
const StrategyLab = lazy(() => import("./features/cult/StrategyLab"));
const PrecisionView = lazy(() => import("./features/wizard/PrecisionView"));
const DyscyplineView = lazy(() => import("./features/wizard/DyscyplineView"));
const ProfitsView = lazy(() => import("./features/wizard/ProfitsView"));
const MarketZonesPage = lazy(() => import("./features/market-zones/MarketZonesPage"));
const TrainingCenterPage = lazy(() => import("./features/training-center/TrainingCenterPage"));
const DxyPage = lazy(() => import("./features/pmw133/DxyPage"));
const SvpPage = lazy(() => import("./features/pmw133/SvpPage"));
const DecisionPage = lazy(() => import("./features/pmw133/DecisionPage"));

migrateLegacyViews();          // 1.10: zoom saved under the old positional chart ids -> new ids per page and TF (once)
const NEED_LAUNCHER = launcherNeeded();   // decided once, before the router fills in an empty address

export default function App() {
  const [gate, setGate] = useState(NEED_LAUNCHER);
  if (gate) return <Launcher onJoin={() => setGate(false)} />;      // 1.32: the full panel is not mounted before JOIN THE CULT
  return <Panel />;
}

function Panel() {
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
  if (CULT_PAGE_IDS.includes(route.page)) {
    return (
      <UiCtx.Provider value={{ openSettings: () => setSettings(true) }}>
        <div className={cls("app", "app-cult", s.synthetic && "synthetic")}>
          <Suspense fallback={<div className="cu-loading" role="status">Ładowanie…</div>}>
            {route.page === "menu" && <NeuralCityMenu route={route} />}
            {route.page === "lightning" && <LightningTower />}
            {route.page === "wind" && <WindPortal />}
            {route.page === "control" && <ControlTower />}
            {route.page === "strategy-lab" && <StrategyLab />}
          </Suspense>
          {settings && <SettingsModal onClose={() => setSettings(false)} />}
        </div>
      </UiCtx.Provider>);
  }
  if (WIZARD_PAGE_IDS.includes(route.page)) {
    const tower = TOWERS.find((t) => t.id === route.page);
    return (
      <UiCtx.Provider value={{ openSettings: () => setSettings(true) }}>
        <div className={cls("app", "app-wizard", s.synthetic && "synthetic")}>
          <WizardShell page={route.page} bg={tower ? tower.bg : null} accent={tower?.accent}>
            <Suspense fallback={<div className="wz-loading" role="status">Ładowanie widoku…</div>}>
              {route.page === "precision" && <PrecisionView />}
              {route.page === "dyscypline" && <DyscyplineView route={route} />}
              {route.page === "profits" && <ProfitsView />}
            </Suspense>
          </WizardShell>
          {settings && <SettingsModal onClose={() => setSettings(false)} />}
        </div>
      </UiCtx.Provider>);
  }
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
          {route.page === "strefy" && <Suspense fallback={<div className="loading">Ładowanie…</div>}><MarketZonesPage /></Suspense>}
          {route.page === "trening" && <Suspense fallback={<div className="loading">Ładowanie…</div>}><TrainingCenterPage /></Suspense>}
          {route.page === "dxy" && <Suspense fallback={<div className="loading">Ładowanie…</div>}><DxyPage /></Suspense>}
          {route.page === "svp" && <Suspense fallback={<div className="loading">Ładowanie…</div>}><SvpPage /></Suspense>}
          {route.page === "decyzje" && <Suspense fallback={<div className="loading">Ładowanie…</div>}><DecisionPage /></Suspense>}
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
