// Centrum sterowania (approved mockup 03): engine, MT5, account and data time; execution modes with their consequences, STOP of new
// entries, primary path; MT5 / Telegram / application behaviour; risk limits and real costs; diagnostics. Every change goes through
// the engine's protected API and its own checks - this page adds no second lock and no default values.
import { usePersisted } from "../../../router";
import { useStore } from "../../../store";
import { cls, fmtTime } from "../../../util";
import PageBanner from "../../shell/PageBanner";
import { useTerminalContext } from "../../shell/useTerminalContext";
import { AppPrefsCard, DiagnosticsCard, Mt5Card, RiskCostsCard, TelegramCard } from "../components/Cards";
import ModePanel, { StopPanel } from "../components/ModePanel";

type Tab = "overview" | "connections" | "risk" | "diag";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Przegląd" }, { id: "connections", label: "MT5 i połączenia" }, { id: "risk", label: "Ryzyko i koszty" }, { id: "diag", label: "Diagnostyka" },
];

export default function SystemControlPage() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const [tab, setTab] = usePersisted<Tab>("sc.tab", "overview", (v) => TABS.some((t) => t.id === v));
  const acc = s.account || {};
  const linked = s.ws === "OPEN";
  const engine = !linked ? `brak połączenia (${s.ws})` : s.engine?.last_error ? "działa z błędem" : "działa";
  const cards: [string, string, string, string][] = [
    ["Silnik", engine, !linked || s.engine?.last_error ? "bad" : "ok", s.engine?.cycle_ms != null ? `cykl ${Math.round(s.engine.cycle_ms)} ms` : ""],
    ["MT5", ctx.mt5 === "CONNECTED" ? "połączony" : ctx.mt5 === "UNKNOWN" ? "nieznany" : "rozłączony", ctx.mt5 === "CONNECTED" ? "ok" : "bad", ctx.mt5State ?? ""],
    ["Rachunek", linked && acc.login ? `${acc.login} · ${acc.trade_mode}` : "—", acc.trade_mode === "REAL" ? "warn" : "muted", acc.server ?? ""],
    ["Ostatnia aktualizacja", linked && s.quote?.time_utc ? fmtTime(s.quote.time_utc) : "—", ctx.freshness === "FRESH" ? "ok" : "warn", `dane: ${ctx.freshness}`],
  ];
  return (
    <div className="t-page" data-testid="page-system-control">
      <PageBanner testId="sc-banner" kicker="Pepe Market Wizard / Sterowanie" title="Centrum sterowania" subtitle="Tryb pracy, MT5, ryzyko i stan systemu."
        badges={<span className={cls("t-badge", s.mode?.mode === "AUTO_LIVE" ? "t-badge-bad" : "t-badge-gold")} data-testid="sc-mode-badge">
          TRYB: {s.mode?.mode?.replace("_", " ") ?? "NIEZNANY"}{s.mode?.kill_switch ? " · STOP" : ""}</span>} />
      <div className="t-tabs" role="tablist" aria-label="Centrum sterowania">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} data-testid={`sc-tab-${t.id}`}>{t.label}</button>)}
      </div>
      <div className="t-stats" data-testid="sc-status">
        {cards.map(([k, v, tone, sub]) => <div key={k} className={cls("t-stat", `t-stat-${tone}`)}><span>{k}</span><b>{v}</b><small>{sub}</small></div>)}
      </div>
      {tab === "overview" && (
        <div className="t-sc-grid">
          <div className="t-col-stack"><ModePanel /><StopPanel /></div>
          <div className="t-col-stack"><Mt5Card /><AppPrefsCard /></div>
        </div>)}
      {tab === "connections" && <div className="t-two"><Mt5Card /><TelegramCard /></div>}
      {tab === "risk" && <RiskCostsCard />}
      {tab === "diag" && <DiagnosticsCard />}
    </div>);
}
