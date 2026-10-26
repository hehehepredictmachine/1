// Fixed, collapsible sidebar of the new panels. The three new areas first, then every existing section of the bot (they open in the
// existing shell, unchanged). The collapsed state is a per-browser preference only.
import { GROUPS, href, type Page, usePersisted } from "../../router";
import { cls } from "../../util";

export const TERMINAL_PAGES: { id: Page; label: string; icon: string }[] = [
  { id: "trading-intelligence", label: "Trading Intelligence", icon: "▦" },
  { id: "ai-neural-lab", label: "AI Neural Lab", icon: "✦" },
  { id: "system-control", label: "System Control Center", icon: "⛨" },
];

export default function TerminalSidebar({ page }: { page: Page }) {
  const [collapsed, setCollapsed] = usePersisted<boolean>("terminal.sidebar.collapsed", false, (v) => typeof v === "boolean");
  return (
    <nav className={cls("t-sidebar", collapsed && "collapsed")} aria-label="Nawigacja terminala" data-testid="t-sidebar" data-collapsed={collapsed ? "1" : "0"}>
      <button className="t-collapse" onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed} aria-controls="t-sidebar-lists"
        data-testid="t-collapse" title={collapsed ? "Rozwiń menu" : "Zwiń menu"}>
        <span aria-hidden="true">{collapsed ? "»" : "«"}</span><span className="t-sr">{collapsed ? "Rozwiń menu" : "Zwiń menu"}</span>
      </button>
      <div id="t-sidebar-lists">
        <ul className="t-nav" aria-label="Nowe panele">
          {TERMINAL_PAGES.map((p) => (
            <li key={p.id}>
              <a href={href(p.id)} className={cls("t-nav-item", page === p.id && "on")} aria-current={page === p.id ? "page" : undefined}
                data-page={p.id} title={p.label}><i aria-hidden="true">{p.icon}</i><span>{p.label}</span></a>
            </li>))}
        </ul>
        <p className="t-nav-title">Istniejące widoki</p>
        <ul className="t-nav t-nav-existing" aria-label="Istniejące widoki" data-testid="t-existing">
          {GROUPS.map((g) => (
            <li key={g.id}>
              <a href={href(g.pages[0])} className="t-nav-item" data-section={g.id} title={`${g.label} (dotychczasowy panel)`}>
                <i aria-hidden="true">{g.icon}</i><span>{g.label}</span></a>
            </li>))}
        </ul>
      </div>
    </nav>);
}
