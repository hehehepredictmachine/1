// Shared frame of the three pages: compact top bar, navigation (collapsible side menu on desktop, three buttons on small
// screens), global failure banner, and ONE global side panel at a time (positions + statistics, or logs). The store and
// the single WebSocket live in StoreProvider ABOVE this component, so switching pages never opens a new connection.
import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { Frog } from "../../appearance";
import { PAGES, href, type Page, usePersisted } from "../../router";
import { useStore } from "../../store";
import { cls, fmtMoney, fmtNum, fmtTime, tone } from "../../util";
import SignalsPanel from "../SignalsPanel";
import StatsPanel from "../StatsPanel";

const ICON: Record<Page, string> = { ai: "✦", wykresy: "▦", warunki: "☑" };

export type Overlay = null | "side" | "logs";

function useBotStats(statsMode: string) {
  const { s } = useStore();
  const [stats, setStats] = useState<any>(null);
  const settled = (s.logs || []).filter((l: any) => l.code === "SETTLED" || l.category === "PAPER").length;
  useEffect(() => {
    if (!s.loaded) return;
    const load = () => apiGet(`/api/v1/stats?mode=${statsMode}`).then(setStats).catch(() => undefined);
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [statsMode, s.loaded, settled]);
  return stats;
}

/** Global failure line, visible on every page; the details stay short (title / one line). */
function FailureBanner() {
  const { s } = useStore();
  const con = s.connection || {};
  const items: string[] = [];
  if (s.ws !== "OPEN") items.push(`Brak połączenia z lokalnym backendem (${s.ws}) – pokazane dane mogą być nieaktualne; ponowne łączenie automatyczne.`);
  else if (con.state && con.state !== "CONNECTED") items.push(`MT5: ${con.state}${con.reason ? ` – ${con.reason}` : ""}. Dane z terminala nie są aktualne.`);
  if (s.engine?.last_error) items.push(`Błąd silnika: ${String(s.engine.last_error).slice(0, 140)}`);
  if (s.mode?.kill_switch) items.push("Nowe wejścia ZATRZYMANE (STOP). Otwarte pozycje pozostają z SL/TP po stronie brokera.");
  if (!items.length) return null;
  return <div className="fail-banner" role="status" data-testid="fail-banner">{items.map((t) => <span key={t}>⚠ {t}</span>)}</div>;
}

function AccountSummary({ stats, onClose }: { stats: any; onClose: () => void }) {
  const { s, refresh } = useStore();
  const a = s.account;
  const cur = a?.currency;
  const daily = stats?.account?.trading_net_today;
  const wr = stats?.bot?.all;
  const auto = s.auto || {};
  const clock = s.connection?.clock || {};
  const positions = (s.positions?.positions || []).filter((p: any) => p.symbol === s.symbol?.symbol);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const c = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest?.("[data-act=account]")) onClose(); };
    window.addEventListener("keydown", k);
    window.addEventListener("mousedown", c);
    return () => { window.removeEventListener("keydown", k); window.removeEventListener("mousedown", c); };
  }, [onClose]);
  const toggleStrategyMode = async () => {
    setErr(null);
    try {
      const next = auto.strategy_mode === "MANUAL" ? { strategy_mode: "AUTO" } : { strategy_mode: "MANUAL", manual_strategy_id: auto.selected_strategy_id || "S01" };
      await apiSend("POST", "/api/v1/strategy/mode", next);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  };
  return (
    <div className="acct-pop" ref={ref} role="dialog" aria-label="Podsumowanie rachunku" data-testid="account-summary">
      <div className="acct-row">
        <Frog />
        <div className="card"><label>BALANCE</label><b>{fmtMoney(a?.balance, cur)}</b><small>{cur ?? ""}</small></div>
        <div className="card"><label>EQUITY</label><b>{fmtMoney(a?.equity, cur)}</b>
          <small className={(a?.profit ?? 0) >= 0 ? "pos" : "neg"}>{a ? `float ${fmtNum(a.profit)}` : ""}</small></div>
      </div>
      <div className="acct-grid">
        <div><label>Rachunek</label><b>{a ? `${a.login ?? ""} · ${a.server ?? ""} · ${a.trade_mode ?? ""}` : "—"}</b></div>
        <div><label>Dzienny wynik (z historii)</label><b className={(daily ?? 0) >= 0 ? "pos" : "neg"}>{daily == null ? "—" : fmtMoney(daily, cur)}</b></div>
        <div><label>Otwarte pozycje ({s.symbol?.symbol})</label><b>{a ? positions.length : "—"}</b></div>
        <div><label>Win rate bota</label><b>{wr?.win_rate == null ? "brak danych" : `${fmtNum(wr.win_rate, 1)}% (${wr.trades} transakcji, ${stats?.bot?.mode ?? ""})`}</b></div>
        <div><label>Czas serwera</label><b>{clock.status === "VERIFIED" ? `UTC${clock.offset_hours >= 0 ? "+" : ""}${clock.offset_hours}` : clock.status ?? "?"}</b></div>
        <div><label>Agent Claude</label><b>{s.agent?.state ?? "?"}</b></div>
        <div><label>ML</label><b>{s.ml?.mode ?? "…"} · {s.ml?.status ?? "…"}</b></div>
        <div><label>Zlecenia</label><b>{s.mode?.mode === "SIGNALS" ? "brak (analiza)" : s.mode?.kill_switch ? "STOP" : s.decision?.mode_gate?.allowed ? "dozwolone" : "wstrzymane"}</b></div>
      </div>
      <div className="acct-auto">
        <span>Wybór strategii silnika: <b>{auto.profile === "ORIGINAL" ? "PROFIL ORIGINAL" : auto.strategy_mode ?? "…"}</b> ({auto.selected_strategy_id ?? "brak"} · {auto.system_state ?? "…"})</span>
        <button className="btn ghost" onClick={toggleStrategyMode} disabled={auto.profile === "ORIGINAL"} data-testid="toggle-strategy-mode"
          title="Ustawienie działania bota (nie składa zleceń). Zwykła nawigacja nigdy go nie zmienia.">Przełącz AUTO / MANUAL</button>
        {err && <span className="bad small">{err}</span>}
      </div>
    </div>
  );
}

function TopBar({ page, stats, onSettings, onPower, onMode, onLook, overlay, setOverlay }: {
  page: Page; stats: any; onSettings: () => void; onPower: () => void; onMode: () => void; onLook: () => void; overlay: Overlay; setOverlay: (o: Overlay) => void;
}) {
  const { s } = useStore();
  const con = s.connection || {};
  const mode = s.mode || {};
  const dq = s.decision?.data_quality;
  const engineOk = !s.engine?.last_error;
  const [acct, setAcct] = useState(false);
  const tickAge = s.quote?.age_seconds;
  return (
    <header className="topbar2" data-testid="topbar">
      <a className="brand" href={href(page)} aria-label="MasterQUO AI">
        <svg viewBox="0 0 32 32" width="24" height="24" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--panel)" stroke="var(--neon)" /><path d="M8 22V11m5 11V7m5 15v-8m5 8V13" stroke="var(--neon)" strokeWidth="2.6" strokeLinecap="round" /></svg>
        <span>MasterQUO <em>AI</em></span>
      </a>
      <div className="tb-chips">
        <span className={cls("chip", s.symbol?.status === "OK" ? "ok" : "warn")} title="Dokładny symbol brokera i jego status handlu"><i className="dot" />{s.symbol?.symbol ?? "?"}</span>
        <span className={cls("chip", tone(con.state))} title={con.reason || con.module_error || ""} data-testid="chip-mt5"><i className="dot" />MT5 <b>{con.state === "CONNECTED" ? "połączony" : con.state ?? "…"}</b></span>
        <span className={cls("chip", engineOk ? tone(dq) : "bad")} title={(s.engine?.last_error || "") + (tickAge != null ? ` · tick ${Math.round(tickAge)} s` : "")}>
          <i className="dot" />Dane <b>{engineOk ? dq ?? "…" : "BŁĄD"}{tickAge != null ? ` · ${Math.round(tickAge)} s` : ""}</b></span>
        {s.ws !== "OPEN" && <span className="chip warn" title="Połączenie z lokalnym backendem (jedno WebSocket)"><i className="dot" />Backend {s.ws}</span>}
        <button className={cls("chip mode", mode.mode === "AUTO_LIVE" ? "bad" : mode.mode === "SIGNALS" ? "muted" : "warn")} onClick={onMode} data-testid="chip-mode"
          title="Tryb wykonania – kliknij, aby zmienić (osobno od wyboru strategii i trybu ML)">Wykonanie <b>{mode.mode_label ?? mode.mode ?? "…"}</b></button>
      </div>
      <span className="spacer" />
      <div className="tb-buttons">
        <button className={cls("tb-btn", acct && "on")} data-act="account" aria-expanded={acct} onClick={() => setAcct(!acct)} title="Rachunek, balance/equity, statystyki, AUTO/MANUAL">
          Konto<span className="tb-long"> {s.account ? fmtMoney(s.account.equity, s.account.currency) : "—"}</span> ▾</button>
        <button className={cls("tb-btn", overlay === "side" && "on")} data-testid="open-side" onClick={() => setOverlay(overlay === "side" ? null : "side")}
          title="Pozycje, zlecenia i statystyki">Pozycje<span className="tb-long"> i statystyki</span></button>
        <button className={cls("tb-btn", overlay === "logs" && "on")} data-testid="open-logs" onClick={() => setOverlay(overlay === "logs" ? null : "logs")} title="Pełny dziennik bota">Logi</button>
        <button className="icon big" title="Wygląd – kolory i motywy" aria-label="Wygląd" onClick={onLook}>🎨</button>
        <button className="icon big" title="Ustawienia" aria-label="Ustawienia" onClick={onSettings}>⚙</button>
        <button className="tb-btn stop" onClick={onPower} data-testid="stop-button" title="Zatrzymanie: nowe wejścia / pozycje bota / aplikacja (tylko procesy MasterQUO)">
          {mode.kill_switch ? "STOP aktywny" : "STOP"}</button>
      </div>
      {acct && <AccountSummary stats={stats} onClose={() => setAcct(false)} />}
    </header>
  );
}

function SideNav({ page }: { page: Page }) {
  const [collapsed, setCollapsed] = usePersisted<boolean>("nav.collapsed", false, (v) => typeof v === "boolean");
  return (
    <nav className={cls("sidenav", collapsed && "collapsed")} aria-label="Strony" data-testid="sidenav">
      {PAGES.map((p) => (
        <a key={p.id} href={href(p.id)} className={cls("nav-item", page === p.id && "on")} aria-current={page === p.id ? "page" : undefined} data-page={p.id} title={p.label}>
          <i aria-hidden="true">{ICON[p.id]}</i><span>{p.label}</span>
        </a>
      ))}
      <span className="spacer" />
      <button className="nav-collapse" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Rozwiń menu" : "Zwiń menu"} title={collapsed ? "Rozwiń menu" : "Zwiń menu"}>
        {collapsed ? "»" : "«"}</button>
    </nav>
  );
}

function MobileNav({ page }: { page: Page }) {
  return (
    <nav className="mobnav" aria-label="Strony (mobilne)" data-testid="mobnav">
      {PAGES.map((p) => (
        <a key={p.id} href={href(p.id)} className={cls("nav-item", page === p.id && "on")} aria-current={page === p.id ? "page" : undefined} data-page={p.id}>
          <i aria-hidden="true">{ICON[p.id]}</i><span>{p.short}</span>
        </a>
      ))}
    </nav>
  );
}

function LogsPanel() {
  const { s } = useStore();
  const [lvl, setLvl] = useState<"ALL" | "WARN">("ALL");
  const logs = (s.logs || []).filter((l: any) => lvl === "ALL" || l.level === "WARNING" || l.level === "ERROR");
  return (
    <div className="side-body" data-testid="logs-panel">
      <div className="tabs small">
        <button className={cls(lvl === "ALL" && "on")} onClick={() => setLvl("ALL")}>Wszystkie</button>
        <button className={cls(lvl === "WARN" && "on")} onClick={() => setLvl("WARN")}>Ostrzeżenia i błędy</button>
      </div>
      <ul className="list mono loglist">
        {logs.map((l: any, i: number) => (
          <li key={l.id ?? `${l.ts}-${i}`} className={cls(l.level === "ERROR" ? "bad" : l.level === "WARNING" ? "warn" : "")}>
            <span className="time">{fmtTime(l.ts, true)}</span> <span className="tag muted">{l.category ?? ""}</span> {l.message}
          </li>))}
        {!logs.length && <li className="muted">Brak wpisów.</li>}
      </ul>
    </div>
  );
}

function SidePanel({ kind, onClose, stats, statsMode, setStatsMode }: { kind: Overlay; onClose: () => void; stats: any; statsMode: string; setStatsMode: (m: string) => void }) {
  const [tab, setTab] = usePersisted<"pos" | "stats">("side.tab", "pos", (v) => v === "pos" || v === "stats");
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector(".fullscreen")) onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!kind) return null;
  return (
    <aside className="sidepanel" role="complementary" aria-label={kind === "logs" ? "Logi" : "Pozycje i statystyki"} data-testid="sidepanel">
      <div className="side-head">
        <b>{kind === "logs" ? "Dziennik bota" : "Pozycje i statystyki"}</b>
        {kind === "side" && (
          <div className="tabs small" role="tablist">
            <button role="tab" aria-selected={tab === "pos"} className={cls(tab === "pos" && "on")} onClick={() => setTab("pos")}>Pozycje i zlecenia</button>
            <button role="tab" aria-selected={tab === "stats"} className={cls(tab === "stats" && "on")} onClick={() => setTab("stats")}>Statystyki</button>
          </div>)}
        <span className="spacer" />
        <button className="icon" onClick={onClose} aria-label="Zamknij panel">✕</button>
      </div>
      {kind === "logs" ? <LogsPanel /> : (
        <div className="side-body">
          {tab === "pos" ? <SignalsPanel index={5} /> : <StatsPanel index={6} stats={stats} mode={statsMode} setMode={setStatsMode} />}
        </div>)}
    </aside>
  );
}

export default function AppShell({ page, children, onSettings, onPower, onMode, onLook }: {
  page: Page; children: React.ReactNode; onSettings: () => void; onPower: () => void; onMode: () => void; onLook: () => void;
}) {
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [statsModeRaw, setStatsMode] = usePersisted<string>("statsmode", "PAPER");
  const statsMode = ["PAPER", "AUTO_DEMO", "AUTO_LIVE"].includes(statsModeRaw) ? statsModeRaw : "PAPER";
  const stats = useBotStats(statsMode);
  return (
    <div className="shell">
      <TopBar page={page} stats={stats} onSettings={onSettings} onPower={onPower} onMode={onMode} onLook={onLook} overlay={overlay} setOverlay={setOverlay} />
      <FailureBanner />
      <div className="shell-body">
        <SideNav page={page} />
        <main className="page" data-page={page} id="main">{children}</main>
      </div>
      <MobileNav page={page} />
      <SidePanel kind={overlay} onClose={() => setOverlay(null)} stats={stats} statsMode={statsMode} setStatsMode={setStatsMode} />
    </div>
  );
}
