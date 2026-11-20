// Common frame of the CULT screens (approved visualisations): left panel with the logo, the menu, the system status, the app version
// and the latency; top header with the brand, the screen title, notifications and the profile. The DEMO / simulator strip and the
// warnings of the bot are always visible. Navigation entries point only to EXISTING screens of the bot (Community / Membership /
// Accounts of the visualisations do not exist in the bot, so they are not shown).
import StudioButton from "../pmw133/StudioButton";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { href, type Page } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { A, type TowerKey } from "./assets";
import { hhmm, useLatency, useSystemStatus } from "./data";
import { Icon } from "./kit";
import "./cult.css";

export type NavItem = { page: Page; label: string; sub?: string; icon: string };
/** Menu of the main screen - as in menu.jpg (without Community / Membership: not part of the bot). */
/** Menu of the tower panels - as in wind.jpg / controltower.jpg (Backtest Lab, Accounts, Community, Membership: not part of the bot). */
export const TOWER_NAV: NavItem[] = [
  { page: "menu", label: "Galaxy", sub: "Menu główne", icon: "home" }, { page: "lightning", label: "PEPE$BANK", sub: "Lightning · Live Signals", icon: "bolt" },
  { page: "precision", label: "Ice Tower", sub: "Analytics", icon: "snow" }, { page: "pepe-signal", label: "PEPE$SIGNAL", sub: "Signal Intelligence", icon: "signal" },
  { page: "pepe-wtc", label: "PEPE$WTC", sub: "Market Command Center", icon: "chart" }, { page: "wind", label: "Wind Portal", sub: "AI Engine Core", icon: "wind" },
  { page: "trading-intelligence", label: "Trading Terminal", sub: "Trading Intelligence", icon: "fire" },
  { page: "control", label: "Control Tower", sub: "Bot Manager", icon: "sliders" }, { page: "strategy-lab", label: "STRATEGIES", sub: "Strategy Lab", icon: "flask" },
  { page: "profits", label: "PEPE$ROI", sub: "Profits", icon: "bars" }, { page: "kontekst", label: "MARKET NEWS", sub: "Kontekst rynku", icon: "chart" },
  { page: "trening", label: "TRAINING LAB", sub: "Centrum treningu", icon: "dna" }, { page: "dane", label: "Data Center", icon: "db" }, { page: "ustawienia", label: "SETTINGS", sub: "Ustawienia", icon: "gear" },
];

export function LeftPanel({ page, nav, emblem }: { page: Page; nav: NavItem[]; emblem?: { tower: TowerKey; title: string; sub: string } }) {
  const { s } = useStore();
  const st = useSystemStatus();
  const lat = useLatency();
  return (
    <aside className="cu-left" data-testid="cu-left">
      <a className="cu-brand" href={href("menu")} aria-label="PepeMarketWizard – menu główne" data-testid="cu-logo">
        <img src={A.logo} alt="" /><b>PEPEMARKETWIZARD</b><small>ALGORITHMIC TRADING INTELLIGENCE</small></a>
      <p className="cu-menu-t" aria-hidden="true"><i />MENU<i /></p>
      <nav aria-label="Menu" className="cu-nav">
        {nav.map((n) => (
          <a key={n.page + n.label} href={href(n.page)} className={cls("cu-nav-i", page === n.page && "on")} aria-current={page === n.page ? "page" : undefined}
            data-testid={`cu-nav-${n.page}`}>
            <Icon n={n.icon} size={20} /><span>{n.label}{n.sub && <small>{n.sub}</small>}</span></a>))}
        <StudioButton variant="nav" />
      </nav>
      {emblem && (
        <div className="cu-emblem" aria-hidden="true"><img src={A.tower(emblem.tower)} alt="" /><b>{emblem.title}</b><small>{emblem.sub}</small></div>)}
      <div className={cls("cu-sys", `s-${st.state.toLowerCase()}`)} data-testid="cu-sys" data-state={st.state} title={st.detail}>
        <b><i />SYSTEM {st.state}</b>
        <span>v{s.app_version ?? "—"} <em>|</em> LATENCY: <span data-testid="cu-latency">{lat == null ? "—" : `${lat} ms`}</span></span>
      </div>
    </aside>);
}

function Notifications() {
  const ctx = useTerminalContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const f = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", f);
    return () => window.removeEventListener("mousedown", f);
  }, [open]);
  const items = [...ctx.warnings.map((w) => ({ level: "WARN", text: w, ts: null as string | null })),
    ...ctx.alerts.slice(0, 12).map((l: any) => ({ level: l.level, text: l.message, ts: l.ts }))];
  return (
    <div className="cu-pop-w" ref={ref}>
      <button type="button" className="cu-round" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`Powiadomienia (${items.length})`} data-testid="cu-bell">
        <Icon n="bell" size={20} />{items.length > 0 && <i className="cu-dot" data-testid="cu-bell-count">{items.length}</i>}</button>
      {open && (
        <div className="cu-pop" role="dialog" aria-label="Powiadomienia" data-testid="cu-notifications">
          <h3>Powiadomienia</h3>
          {!items.length ? <p className="cu-na">Brak ostrzeżeń – silnik nie zgłasza problemów.</p> : (
            <ul>{items.map((n, i) => <li key={i} className={`l-${n.level.toLowerCase()}`}>{n.ts && <time>{hhmm(n.ts)}</time>}{n.text}</li>)}</ul>)}
          <a href={href("diagnostyka")} className="cu-link">Pełny dziennik i diagnostyka →</a>
        </div>)}
    </div>);
}

function Profile() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const [open, setOpen] = useState(false);
  const a = s.account || {};
  return (
    <div className="cu-pop-w">
      <button type="button" className="cu-round" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Profil – rachunek MT5" data-testid="cu-profile">
        <Icon n="user" size={20} /></button>
      {open && (
        <div className="cu-pop" role="dialog" aria-label="Profil" data-testid="cu-profile-pop">
          <h3>Rachunek MT5</h3>
          <dl className="cu-kv">
            <dt>Login</dt><dd>{a.login ?? "—"}</dd><dt>Serwer</dt><dd>{a.server ?? "—"}</dd><dt>Broker</dt><dd>{a.company ?? "—"}</dd>
            <dt>Typ</dt><dd>{ctx.env === "SYNTHETIC" ? "symulator (DEMO)" : a.trade_mode ?? "—"}</dd><dt>Waluta</dt><dd>{a.currency ?? "—"}</dd>
            <dt>Tryb bota</dt><dd>{ctx.modeLabel ?? ctx.mode ?? "—"}{ctx.killSwitch ? " · STOP" : ""}</dd>
          </dl>
          <p className="cu-na">Bot działa lokalnie – nie ma kont użytkowników; profil to rachunek podłączonego terminala.</p>
          <a href={href("ustawienia")} className="cu-link">Ustawienia →</a>
        </div>)}
    </div>);
}

export function TopRight({ children }: { children?: ReactNode }) {
  return <div className="cu-top-r">{children}<Notifications /><Profile /></div>;
}

export function Strips() {
  const ctx = useTerminalContext();
  return (
    <>
      {ctx.backend !== "OPEN" && (
        <div className="cu-strip bad" role="status" data-testid="cu-backend">Brak łącza z botem ({ctx.backend}) – ponowne łączenie. Wartości na ekranie są
          nieaktualne (STALE) do czasu odzyskania połączenia.</div>)}
      {ctx.env === "SYNTHETIC" && <div className="cu-strip demo" role="note" data-testid="cu-demo">DEMO – symulator terminala: dane syntetyczne, to nie są notowania MT5 ani wyniki rachunku.</div>}
      {ctx.env === "DEMO" && <div className="cu-strip demo" role="note" data-testid="cu-demo">DEMO – rachunek demonstracyjny MT5.</div>}
      {ctx.warnings.length > 0 && <div className="cu-strip warn" role="status" data-testid="cu-warnings">{ctx.warnings.map((w) => <span key={w}>⚠ {w}</span>)}</div>}
    </>);
}

/** Frame of a tower panel. */
export default function CultShell({ page, tower, title, sub, emblem, tabs, right, accent, bg, children }: {
  page: Page; tower: TowerKey; title: string; sub?: string; emblem: { title: string; sub: string }; tabs?: { id: string; label: string }[];
  right?: ReactNode; accent: string; bg: string; children: ReactNode;
}) {
  useEffect(() => {
    document.documentElement.classList.add("cu-doc");
    return () => document.documentElement.classList.remove("cu-doc");
  }, []);
  return (
    <div className={cls("cu-root", `tw-${tower}`)} style={{ "--acc": accent } as CSSProperties} data-testid={`page-${page}`} data-page={page}>
      <div className="cu-bg" aria-hidden="true" style={{ backgroundImage: `url(${bg})` }} />
      <LeftPanel page={page} nav={TOWER_NAV} emblem={{ tower, ...emblem }} />
      <div className="cu-main">
        <header className="cu-top">
          <div className="cu-title">
            <p className="cu-brandline"><img src={A.crown} alt="" />PEPEMARKETWIZARD<img src={A.crown} alt="" /></p>
            <h1 data-testid="cu-title">{title}</h1>
            {sub && <p className="cu-sub">{sub}</p>}
            {tabs && (
              <nav className="cu-tabs" aria-label="Sekcje">
                {tabs.map((t, i) => <a key={t.id} href={`#${t.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(t.id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>
                  {i > 0 && <i aria-hidden="true">|</i>}{t.label}</a>)}
              </nav>)}
          </div>
          <TopRight>{right}</TopRight>
        </header>
        <Strips />
        <main className="cu-content" id="cu-content">{children}</main>
      </div>
    </div>);
}
