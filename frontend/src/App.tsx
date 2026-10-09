import { useEffect, useState } from "react";
import { apiGet } from "./api";
import { BackgroundLayer, useAppearance } from "./appearance";
import AgentDrawer from "./components/AgentDrawer";
import { AutoPanel, LiveSetupsPanel, StrategiesPanel, useAutoFull } from "./components/AutoPanels";
import { BotLog, NewsPanel, RiskPanel } from "./components/BottomPanels";
import ChartPanel, { type ChartOpts } from "./components/ChartPanel";
import { ModeDialog, PowerDialog, SettingsModal } from "./components/Dialogs";
import { ThemeDialog } from "./components/ThemeDialog";
import Header from "./components/Header";
import SignalsPanel from "./components/SignalsPanel";
import StatsPanel from "./components/StatsPanel";
import MLPanel from "./components/MLPanel";
import LicenseGate, { LicenseBar } from "./components/LicenseGate";
import { useStore } from "./store";
import { cls, type TimeZoneMode } from "./util";

function usePersisted<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem("mq." + key);
      return raw ? (JSON.parse(raw) as T) : init;
    } catch {
      return init;
    }
  });
  const set = (x: T) => {
    setV(x);
    try {
      localStorage.setItem("mq." + key, JSON.stringify(x));
    } catch {
      /* storage unavailable */
    }
  };
  return [v, set];
}

export default function App() {
  const { s } = useStore();
  const [layout, setLayout] = usePersisted<"STD" | "SIX">("layout", "STD");
  const [p4, setP4] = usePersisted<string>("panel4tf", "H1");
  const [optsRaw, setOpts] = usePersisted<ChartOpts>("chartopts.v2", { showRsi: true, showMacd: true, showStructure: true, showZones: true, syncCrosshair: false, tz: "LOCAL" });
  const opts: ChartOpts = optsRaw;
  const [full, setFull] = useState<string | null>(null);
  const [agent, setAgent] = useState(false);
  const [settings, setSettings] = useState(false);
  const [mode, setMode] = useState(false);
  const [power, setPower] = useState(false);
  const [look, setLook] = useState(false);
  const [statsModeRaw, setStatsMode] = usePersisted<string>("statsmode", "PAPER");
  const statsMode = ["PAPER", "AUTO_DEMO", "AUTO_LIVE"].includes(statsModeRaw) ? statsModeRaw : "PAPER";   // 1.2 names migrated
  const [stats, setStats] = useState<any>(null);
  const [autoFull, reloadAuto] = useAutoFull();
  const { prefs } = useAppearance();

  useEffect(() => {
    if (s.loaded && s.first_run_completed === false) setSettings(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loaded]);
  useEffect(() => {
    if (!s.loaded) return;
    const load = () => apiGet(`/api/v1/stats?mode=${statsMode}`).then(setStats).catch(() => undefined);
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [statsMode, s.loaded, (s.logs || []).filter((l: any) => l.code === "SETTLED" || l.category === "PAPER").length]);

  if (!s.loaded) return <><BackgroundLayer /><div className="loading">MasterQUO AI – łączenie z lokalnym backendem…</div></>;
  if (s.locked) return <><BackgroundLayer /><LicenseGate /></>;
  const o = (k: keyof ChartOpts, v: any) => setOpts({ ...opts, [k]: v });
  const chart = (tf: string, idx: number) => (
    <ChartPanel key={tf + idx} tf={tf} index={idx} opts={opts} fullscreen={full === tf + idx} onFullscreen={() => setFull(full === tf + idx ? null : tf + idx)} />
  );
  return (
    <div className={cls("app", s.synthetic && "synthetic", "anim-" + prefs.mode.toLowerCase())}>
      <BackgroundLayer />
      {s.synthetic && <div className="synthetic-banner">DANE SYNTETYCZNE – symulator terminala, oddzielna baza. To nie są notowania MT5 ani wyniki rachunku.</div>}
      <Header onAgent={() => setAgent(!agent)} onSettings={() => setSettings(true)} onPower={() => setPower(true)} onMode={() => setMode(true)} onLook={() => setLook(true)} botStats={stats} />
      <LicenseBar />
      <div className="toolbar">
        <div className="tabs small">
          <button className={cls(layout === "STD" && "on")} onClick={() => setLayout("STD")}>Układ standardowy</button>
          <button className={cls(layout === "SIX" && "on")} onClick={() => setLayout("SIX")}>6 wykresów</button>
        </div>
        {layout === "STD" && <div className="tabs small"><span className="lbl">Panel 4:</span>
          {["H1", "H4", "D1"].map((t) => <button key={t} className={cls(p4 === t && "on")} onClick={() => setP4(t)}>{t}</button>)}</div>}
        <div className="toggles">
          {([["showRsi", "RSI"], ["showMacd", "MACD"], ["showStructure", "BOS/CHoCH"], ["showZones", "FVG/OB"], ["syncCrosshair", "Wspólny celownik"]] as const).map(([k, l]) => (
            <label key={k}><input type="checkbox" checked={!!opts[k]} onChange={(e) => o(k, e.target.checked)} />{l}</label>
          ))}
          <select value={opts.tz} onChange={(e) => o("tz", e.target.value as TimeZoneMode)} title="Strefa czasu na wykresach (dane zawsze w UTC)">
            <option value="LOCAL">Czas lokalny</option><option value="UTC">UTC</option><option value="SERVER">Czas serwera</option>
          </select>
        </div>
        <span className="toolbar-note">Każdy wykres ma własny zoom i przyciski. Synchronizacja zakresu – tylko w wybranej grupie (A/B). * = wskaźnik tylko wizualny</span>
      </div>
      <main className={cls("grid", layout === "SIX" ? "six" : "std")}>
        {layout === "STD" ? (
          <>
            {chart("M1", 1)}
            {chart("M5", 2)}
            {chart("M15", 3)}
            {chart(p4, 4)}
            <SignalsPanel index={5} />
            <StatsPanel index={6} stats={stats} mode={statsMode} setMode={setStatsMode} />
          </>
        ) : (
          <>
            {["M1", "M5", "M15", "H1", "H4", "D1"].map((tf, i) => chart(tf, i + 1))}
            <SignalsPanel index={7} />
            <StatsPanel index={8} stats={stats} mode={statsMode} setMode={setStatsMode} />
          </>
        )}
        <div className="auto-row-grid">
          <AutoPanel full={autoFull} />
          <LiveSetupsPanel full={autoFull} />
          <StrategiesPanel full={autoFull} reload={() => { reloadAuto(); }} />
        </div>
        <div className="ml-row"><MLPanel index={layout === "SIX" ? 9 : 7} /></div>
        <div className="bottom-row">
          <NewsPanel />
          <RiskPanel onSettings={() => setSettings(true)} />
          <BotLog />
        </div>
      </main>
      {agent && <AgentDrawer onClose={() => setAgent(false)} />}
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
      {mode && <ModeDialog onClose={() => setMode(false)} />}
      {power && <PowerDialog onClose={() => setPower(false)} />}
      {look && <ThemeDialog onClose={() => setLook(false)} />}
      <footer className="footer">
        MasterQUO AI {s.app_version} · kontrakt API {s.contract} · wykresy: TradingView Lightweight Charts™ (Apache-2.0) – źródło notowań: wyłącznie Twój terminal MT5 ·
        Narzędzie analityczne – nie gwarantuje zysków.
      </footer>
    </div>
  );
}
