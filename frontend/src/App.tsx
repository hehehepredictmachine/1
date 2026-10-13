// Three routable pages inside one shared frame. The store (one WebSocket) is provided ABOVE this component (main.tsx),
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
import { useRoute } from "./router";
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
    document.title = `MasterQUO AI – ${{ ai: "Analiza AI", wykresy: "Wykresy bota", warunki: "Warunki setupu" }[route.page]}`;
  }, [route.page]);

  if (!s.loaded) return <><BackgroundLayer /><div className="loading">MasterQUO AI – łączenie z lokalnym backendem…</div></>;
  return (
    <UiCtx.Provider value={{ openSettings: () => setSettings(true) }}>
      <div className={cls("app", s.synthetic && "synthetic", "anim-" + prefs.mode.toLowerCase())}>
        <BackgroundLayer />
        {s.synthetic && <div className="synthetic-banner">DANE SYNTETYCZNE – symulator terminala, oddzielna baza. To nie są notowania MT5 ani wyniki rachunku.</div>}
        <AppShell page={route.page} onSettings={() => setSettings(true)} onPower={() => setPower(true)} onMode={() => setMode(true)} onLook={() => setLook(true)}>
          {route.page === "ai" && <AiAnalysisPage />}
          {route.page === "wykresy" && <BotChartsPage route={route} />}
          {route.page === "warunki" && <SetupRequirementsPage route={route} />}
        </AppShell>
        {settings && <SettingsModal onClose={() => setSettings(false)} />}
        {mode && <ModeDialog onClose={() => setMode(false)} />}
        {power && <PowerDialog onClose={() => setPower(false)} />}
        {look && <ThemeDialog onClose={() => setLook(false)} />}
        <footer className="footer">
          MasterQUO AI {s.app_version} · kontrakt API {s.contract} · wykresy: TradingView Lightweight Charts™ (Apache-2.0) – źródło notowań: wyłącznie Twój terminal MT5 ·
          Narzędzie analityczne – nie gwarantuje zysków.
        </footer>
      </div>
    </UiCtx.Provider>
  );
}
