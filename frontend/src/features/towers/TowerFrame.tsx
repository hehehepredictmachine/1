// Frame of the tower interiors PEPE$WTC and PEPE$SIGNAL (1.36): compact logo top-left, the navigation of the eight towers of the
// Main Menu V2 (same targets as the menu - towers.ts), the environment badge from the terminal (REAL / DEMO / SIMULATOR / OFFLINE -
// never guessed), the clock, warnings of the bot and the bottom status bar. Esc does nothing here (the panels use it for their own
// dialogs); the way back is the logo, "← Stół" and the browser history.
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { href, type Page } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { TOWERS } from "../neural-city/towers";
import { useTerminalContext } from "../shell/useTerminalContext";
import "./towers.css";

export function useClock(): string {
  const [t, setT] = useState(() => new Date());
  useEffect(() => { const i = setInterval(() => setT(new Date()), 1000); return () => clearInterval(i); }, []);
  return t.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Environment badge: what the TERMINAL confirmed; the simulator is always DEMO, a broken link is OFFLINE. */
export function useEnvBadge(): { label: string; tone: "real" | "demo" | "off"; title: string } {
  const ctx = useTerminalContext();
  if (ctx.backend !== "OPEN") return { label: "OFFLINE", tone: "off", title: "brak połączenia z lokalnym backendem bota" };
  if (ctx.mt5 !== "CONNECTED") return { label: "MT5 ROZŁĄCZONY", tone: "off", title: `MT5: ${ctx.mt5State ?? "brak statusu"}` };
  if (ctx.env === "SYNTHETIC") return { label: "DEMO / SYMULATOR", tone: "demo", title: ctx.envDetail };
  if (ctx.env === "DEMO") return { label: "DEMO MT5", tone: "demo", title: ctx.envDetail };
  if (ctx.env === "LIVE") return { label: "LIVE MT5", tone: "real", title: ctx.envDetail };
  return { label: "NIEZNANY RACHUNEK", tone: "off", title: ctx.envDetail };
}

export default function TowerFrame({ page, accent, title, subtitle, tagline, tabs, children, status, testid }: {
  page: Page; accent: string; title?: ReactNode; subtitle?: string; tagline?: string; tabs?: ReactNode; children: ReactNode; status: ReactNode; testid: string;
}) {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const env = useEnvBadge();
  const clock = useClock();
  useEffect(() => {
    document.documentElement.classList.add("tw-doc");
    return () => document.documentElement.classList.remove("tw-doc");
  }, []);
  return (
    <div className={cls("tw", s.synthetic && "tw-syn")} style={{ "--acc": accent } as CSSProperties} data-testid={testid}>
      <header className="tw-top" data-testid="tw-top">
        <a className="tw-logo" href={href("menu")} aria-label="PepeMarketWizard – wróć do menu głównego (stół neuronowy)" data-testid="tw-logo">
          <span className="tw-logo-mark" aria-hidden="true">♛</span>
          <span><b>Pepe<em>Market</em><i>Wizard</i></b><small>NEURAL TRADING COMMAND CENTER</small></span></a>
        <nav className="tw-nav" aria-label="Wieże PepeMarketWizard">
          <a className="tw-nav-i home" href={href("menu")} data-testid="tw-nav-menu" title="Menu główne – stół neuronowy">← Stół</a>
          {TOWERS.map((t) => (
            <a key={t.key} href={href(t.page)} className={cls("tw-nav-i", t.page === page && "on")} aria-current={t.page === page ? "page" : undefined}
              data-testid={`tw-nav-${t.key}`} style={{ "--c": t.color } as CSSProperties} title={`${t.name} → ${t.panel}`}>
              <span aria-hidden="true">{t.icon}</span>{t.name}</a>))}
        </nav>
        <div className="tw-top-r">
          <span className={cls("tw-env", `e-${env.tone}`)} title={env.title} data-testid="tw-env"><i />{env.label}</span>
          <span className="tw-clock" aria-label="Czas lokalny">{clock}</span>
        </div>
      </header>
      {ctx.warnings.length > 0 && (
        <div className="tw-warn" role="status" data-testid="tw-warn">{ctx.warnings.slice(0, 2).map((w) => <span key={w}>⚠ {w}</span>)}</div>)}
      {title && (
        <div className="tw-hero">
          <h1>{title}</h1>
          {subtitle && <div className="tw-hero-s"><b>{subtitle}</b>{tagline && <small>{tagline}</small>}</div>}
          <div className="tw-hero-net" aria-hidden="true" />
        </div>)}
      {tabs}
      <main className="tw-main">{children}</main>
      <footer className="tw-status" data-testid="tw-status">{status}</footer>
    </div>);
}

/** Panel card of the towers (thin neon frame, header with an icon, a title and a right-side slot). */
export function Card({ title, icon, right, children, className, testid, id }: {
  title: ReactNode; icon?: string; right?: ReactNode; children: ReactNode; className?: string; testid?: string; id?: string;
}) {
  return (
    <section className={cls("tw-card", className)} data-testid={testid} id={id} aria-label={typeof title === "string" ? title : undefined}>
      <header className="tw-card-h"><h2>{icon && <span className="tw-ico" aria-hidden="true">{icon}</span>}{title}</h2>{right && <span className="tw-card-r">{right}</span>}</header>
      <div className="tw-card-b">{children}</div>
    </section>);
}

/** Source / state chip: LIVE (terminal REAL), DEMO, SYM (simulator), N/A, STALE, ERROR, OFF … */
export function Src({ k, children, title }: { k: "live" | "demo" | "na" | "stale" | "err" | "ok" | "warn" | "off" | "info"; children: ReactNode; title?: string }) {
  return <span className={cls("tw-src", `s-${k}`)} title={title}>{children}</span>;
}

export function Dir({ d }: { d: string | null | undefined }) {
  const v = (d || "").toUpperCase();
  const k = v === "BUY" || v === "LONG" || v === "BULLISH" || v === "UP" ? "buy" : v === "SELL" || v === "SHORT" || v === "BEARISH" || v === "DOWN" ? "sell" : "wait";
  const txt = v === "LONG" ? "BUY" : v === "SHORT" ? "SELL" : v || "N/A";
  return <span className={cls("tw-dir", `d-${k}`)}>{txt}</span>;
}

/** 0-100 bar. value null -> empty bar + "N/A" (never a made-up value). */
export function Meter({ value, label, title }: { value: number | null | undefined; label?: ReactNode; title?: string }) {
  const v = value == null || !Number.isFinite(value) ? null : Math.max(0, Math.min(100, value));
  return (
    <span className="tw-meter" title={title} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v ?? undefined} aria-label={title}>
      <i style={{ width: `${v ?? 0}%` }} /><b>{label ?? (v == null ? "N/A" : `${Math.round(v)}/100`)}</b></span>);
}
