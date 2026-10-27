// Sidebar of the new panels (approved mockups): Pepe brand, RYNEK and SYSTEM sections, every existing view of the bot (they open in
// the existing shell, unchanged) and the engine status card. Collapsing is a per-client preference only.
import pepe from "../../assets/pepe-wizard.webp";
import { GROUPS, href, type Page, usePersisted } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";

export const TERMINAL_PAGES: { id: Page; label: string; icon: string }[] = [
  { id: "trading-intelligence", label: "Trading Intelligence", icon: "◈" },
  { id: "ai-neural-lab", label: "AI Neural Lab", icon: "✧" },
  { id: "system-control", label: "Centrum sterowania", icon: "◎" },
];

const SECTIONS: { title: string; items: { id: Page; label: string; icon: string; existing?: boolean }[] }[] = [
  { title: "Rynek", items: [
    { id: "trading-intelligence", label: "Trading Intelligence", icon: "◈" },
    { id: "wykresy", label: "Wykresy MTF", icon: "▦", existing: true },
    { id: "warunki", label: "Setupy i strategie", icon: "◇", existing: true },
    { id: "pozycje", label: "Pozycje i wyniki", icon: "≋", existing: true },
  ] },
  { title: "System", items: [
    { id: "ai-neural-lab", label: "AI Neural Lab", icon: "✧" },
    { id: "system-control", label: "Centrum sterowania", icon: "◎" },
    { id: "ustawienia", label: "Ustawienia", icon: "⚙", existing: true },
  ] },
];

function EngineCard() {
  const { s } = useStore();
  const linked = s.ws === "OPEN";
  const err = s.engine?.last_error;
  const state = !linked ? `brak połączenia (${s.ws ?? "?"})` : err ? "działa z błędem" : "działa";
  return (
    <div className={cls("t-engine", !linked ? "bad" : err ? "warn" : "ok")} data-testid="t-engine" role="status">
      <b>Silnik bota</b>
      <span>Stan: {state}</span>
      {linked && s.engine?.cycle_ms != null && <span className="t-dim">cykl analizy {Math.round(s.engine.cycle_ms)} ms</span>}
    </div>);
}

export default function TerminalSidebar({ page }: { page: Page }) {
  const [collapsed, setCollapsed] = usePersisted<boolean>("terminal.sidebar.collapsed", false, (v) => typeof v === "boolean");
  return (
    <nav className={cls("t-sidebar", collapsed && "collapsed")} aria-label="Nawigacja" data-testid="t-sidebar" data-collapsed={collapsed ? "1" : "0"}>
      <div className="t-side-brand">
        <img src={pepe} alt="" aria-hidden="true" width={44} height={46} />
        <span><b>Pepe Market Wizard</b><small>Trading system</small></span>
      </div>
      <button className="t-collapse" onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed} aria-controls="t-sidebar-lists"
        data-testid="t-collapse" title={collapsed ? "Rozwiń menu" : "Zwiń menu"}>
        <span aria-hidden="true">{collapsed ? "»" : "«"}</span><span className="t-sr">{collapsed ? "Rozwiń menu" : "Zwiń menu"}</span>
      </button>
      <div id="t-sidebar-lists" className="t-side-lists">
        {SECTIONS.map((sec) => (
          <div key={sec.title}>
            <p className="t-nav-title">{sec.title}</p>
            <ul className="t-nav" aria-label={sec.title}>
              {sec.items.map((p) => (
                <li key={p.id}>
                  <a href={href(p.id)} className={cls("t-nav-item", page === p.id && "on")} aria-current={page === p.id ? "page" : undefined}
                    data-page={p.id} title={p.existing ? `${p.label} (dotychczasowy widok)` : p.label}>
                    <i aria-hidden="true">{p.icon}</i><span>{p.label}</span></a>
                </li>))}
            </ul>
          </div>))}
        <p className="t-nav-title">Wszystkie widoki</p>
        <ul className="t-nav t-nav-existing" aria-label="Wszystkie dotychczasowe widoki" data-testid="t-existing">
          {GROUPS.map((g) => (
            <li key={g.id}>
              <a href={href(g.pages[0])} className="t-nav-item" data-section={g.id} title={`${g.label} (dotychczasowy panel)`}>
                <i aria-hidden="true">{g.icon}</i><span>{g.label}</span></a>
            </li>))}
        </ul>
      </div>
      <EngineCard />
    </nav>);
}
