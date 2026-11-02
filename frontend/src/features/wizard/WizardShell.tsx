// Frame of the main menu and the three tower views (PEPEMARKETWIZARD – NEURO MAGIC CYBERPUNK): compact top bar with the logo
// (back to the menu), the tower tabs, the instrument switch (existing endpoint), and the REAL state of the backend link, MT5, data
// freshness and the bot (mode, STOP). Everything shown comes from the existing store (one WebSocket) - nothing is assumed.
import { useEffect, type CSSProperties, type ReactNode } from "react";
import { href, type Page } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { InstrumentSwitch } from "../shell/TerminalHeader";
import { useTerminalContext } from "../shell/useTerminalContext";
import "../shell/terminal.css";
import { TOWERS, type WizardAsset } from "./assets";
import WizardLogo from "./WizardLogo";
import "./wizard.css";

const FRESH: Record<string, [string, string]> = {
  FRESH: ["ok", "dane aktualne"], DEGRADED: ["warn", "dane z ostrzeżeniem"], STALE: ["warn", "dane nieaktualne"],
  DISCONNECTED: ["bad", "brak połączenia"], UNKNOWN: ["muted", "stan danych nieznany"],
};

/** Environment label: REAL / DEMO only when the terminal confirmed the account; the simulator is never called live. */
export function envLabel(env: string): string {
  return env === "LIVE" ? "RACHUNEK REAL" : env === "DEMO" ? "RACHUNEK DEMO" : env === "SYNTHETIC" ? "SYMULATOR (dane syntetyczne)" : env === "HISTORY" ? "WIDOK HISTORYCZNY" : "RACHUNEK NIEZNANY";
}

export function WizardTopBar({ page }: { page: Page }) {
  const ctx = useTerminalContext();
  const fr = FRESH[ctx.freshness] ?? FRESH.UNKNOWN;
  const botTone = ctx.backend !== "OPEN" ? "muted" : ctx.killSwitch ? "bad" : ctx.mode === "AUTO_LIVE" ? "bad" : ctx.mode ? "ok" : "muted";
  return (
    <header className="wz-top" data-testid="wz-top">
      <a className="wz-logo" href={href("menu")} aria-label="PepeMarketWizard – menu główne" data-testid="wz-logo">
        <WizardLogo /><span className="wz-logo-text">Pepe<b>Market</b>Wizard</span>
      </a>
      <nav className="wz-tabs" aria-label="Wieże">
        {TOWERS.map((t) => (
          <a key={t.id} href={href(t.id)} className={cls("wz-tab", page === t.id && "on")} aria-current={page === t.id ? "page" : undefined}
            style={{ "--tw": t.accent } as CSSProperties} data-testid={`wz-tab-${t.id}`}>{t.name}</a>))}
      </nav>
      <span className="wz-spacer" />
      <InstrumentSwitch ctx={ctx} />
      <span className={cls("wz-chip", ctx.mt5 === "CONNECTED" ? "ok" : ctx.mt5 === "UNKNOWN" ? "muted" : "bad")} data-testid="wz-mt5" data-mt5={ctx.mt5}
        title={ctx.mt5State ? `MT5: ${ctx.mt5State}` : "MT5: brak statusu"}>
        <i className="wz-dot" aria-hidden="true" />MT5 <b>{ctx.mt5 === "CONNECTED" ? "połączony" : ctx.mt5 === "UNKNOWN" ? "nieznany" : "rozłączony"}</b></span>
      <span className={cls("wz-chip", fr[0])} data-testid="wz-fresh" data-fresh={ctx.freshness} title={ctx.freshnessDetail}>
        <i className="wz-dot" aria-hidden="true" />{fr[1]}</span>
      <span className={cls("wz-chip", botTone)} data-testid="wz-bot" title={`${envLabel(ctx.env)} – ${ctx.envDetail}`}>
        Bot: <b>{ctx.backend !== "OPEN" ? "brak łącza" : ctx.mode ? `${ctx.mode.replace("_", " ")}${ctx.killSwitch ? " · STOP" : ""}` : "nieznany"}</b>
        <span className="wz-env"> · {envLabel(ctx.env)}</span></span>
      {ctx.backend !== "OPEN" && <span className="wz-chip bad" role="status" data-testid="wz-backend">Backend <b>{ctx.backend}</b> – ponowne łączenie</span>}
    </header>);
}

export default function WizardShell({ page, bg, children, accent }: { page: Page; bg: WizardAsset | null; children: ReactNode; accent?: string }) {
  const { s } = useStore();
  const ctx = useTerminalContext();
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("wz-doc");
    return () => root.classList.remove("wz-doc");
  }, []);
  return (
    <div className="pmw-terminal wz-root" data-testid="wizard-shell" data-page={page} data-env={ctx.env}
      style={{ "--wz-accent": accent ?? "#b46bff" } as CSSProperties}>
      {bg && (
        <div className="wz-view-bg" aria-hidden="true" data-testid="wz-view-bg" data-asset={bg.file}>
          <img src={bg.url} alt="" draggable={false} />
          <div className="wz-view-shade" />
        </div>)}
      <a className="t-skip wz-skip" href="#wz-main" onClick={(e) => { e.preventDefault(); document.getElementById("wz-main")?.focus(); }}>Przejdź do treści</a>
      <WizardTopBar page={page} />
      {ctx.env === "SYNTHETIC" && (
        <div className="wz-strip warn" role="note" data-testid="wz-synthetic">DANE SYNTETYCZNE – symulator terminala. To nie są notowania MT5 ani wyniki rachunku.</div>)}
      {ctx.warnings.length > 0 && (
        <div className="wz-strip bad" role="status" data-testid="wz-warnings">{ctx.warnings.map((w) => <span key={w}>⚠ {w}</span>)}</div>)}
      <main id="wz-main" className="wz-main" tabIndex={-1} data-page={page}>{children}</main>
      <footer className="wz-footer">PepeMarketWizard {s.app_version} · notowania wyłącznie z Twojego terminala MT5 · narzędzie analityczne – nie gwarantuje zysków ·
        <a href={href("trading-intelligence")}> pełny terminal</a> · <a href={href("pulpit")}>dotychczasowe menu</a></footer>
    </div>);
}
