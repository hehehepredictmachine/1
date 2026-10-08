import { useStore } from "../store";
import { cls, fmtMoney, fmtNum, tone } from "../util";

function Chip({ label, value, t, title }: { label: string; value: string; t: string; title?: string }) {
  return (
    <span className={cls("chip", t)} title={title}>
      <i className="dot" />
      {label}
      {value ? <b>{value}</b> : null}
    </span>
  );
}

export default function Header({ onAgent, onSettings, onPower, onMode, botStats }: {
  onAgent: () => void;
  onSettings: () => void;
  onPower: () => void;
  onMode: () => void;
  botStats: any;
}) {
  const { s } = useStore();
  const con = s.connection || {};
  const a = s.account;
  const mode = s.mode || {};
  const ag = s.agent || {};
  const clock = con.clock || {};
  const engineOk = !s.engine?.last_error;
  const dq = s.decision?.data_quality;
  const positions = (s.positions?.positions || []).filter((p: any) => p.symbol === s.symbol?.symbol);
  const daily = botStats?.account?.trading_net_today;
  const wr = botStats?.bot?.all;
  const cur = a?.currency;
  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#062716" stroke="#22ff88" /><path d="M8 22V11m5 11V7m5 15v-8m5 8V13" stroke="#2bff88" strokeWidth="2.6" strokeLinecap="round" /></svg>
        <span>MasterQUO <em>AI</em></span>
      </div>
      <div className="chips">
        <Chip label="MT5" value={con.state === "CONNECTED" ? (a ? `${a.trade_mode} ${a.server ?? ""}` : "") : con.state ?? "…"}
          t={tone(con.state)} title={con.reason || con.module_error || ""} />
        <Chip label="BRIDGE" value={s.ws === "OPEN" ? (con.worker_wedged_seconds > 5 ? "TERMINAL WOLNY" : "LIVE") : s.ws}
          t={s.ws === "OPEN" && con.worker_wedged_seconds <= 5 ? "ok" : "warn"} />
        <Chip label="CZAS" value={clock.status === "VERIFIED" ? `UTC${clock.offset_hours >= 0 ? "+" : ""}${clock.offset_hours}` : clock.status ?? "?"}
          t={clock.status === "VERIFIED" ? "ok" : clock.status === "UNKNOWN" ? "bad" : "warn"} title="Offset czasu serwera brokera zmierzony z ticków" />
        <Chip label="AGENT CLAUDE" value={ag.state ?? "?"} t={tone(ag.state === "IDLE" || ag.state === "OK" ? "OK" : ag.state)} title={ag.detail || ""} />
        <Chip label="BOT" value={engineOk ? (dq ?? "…") : "BŁĄD"} t={engineOk ? tone(dq) : "bad"} title={s.engine?.last_error || ""} />
        <button className={cls("chip mode", mode.mode === "LIVE_EXECUTION" ? "bad" : mode.mode === "READ_ONLY" ? "muted" : "warn")} onClick={onMode}>
          TRYB <b>{mode.mode ?? "READ_ONLY"}</b>
        </button>
        <span className={cls("chip", mode.auto_trading ? "ok" : "muted")}>
          <i className="dot" />AUTO TRADING <b>{mode.auto_trading ? "ON" : "OFF"}</b>
        </span>
        {mode.kill_switch && <span className="chip bad"><i className="dot" />NOWE WEJŚCIA ZATRZYMANE</span>}
      </div>
      <div className="hdr-art" aria-hidden="true">
        <img src="/static/header_art.webp" alt="" />
        <div className="hdr-candles">{Array.from({ length: 14 }).map((_, i) => <i key={i} style={{ height: `${18 + ((i * 37) % 42)}px` }} />)}</div>
      </div>
      <div className="cards">
        <div className="card"><label>BALANCE</label><b>{fmtMoney(a?.balance, cur)}</b></div>
        <div className="card"><label>EQUITY</label><b>{fmtMoney(a?.equity, cur)}</b>
          <small className={(a?.profit ?? 0) >= 0 ? "pos" : "neg"}>{a ? `float ${fmtNum(a.profit)}` : ""}</small></div>
        <div className="card"><label>DAILY P/L</label><b className={(daily ?? 0) >= 0 ? "pos" : "neg"}>{daily === null || daily === undefined ? "—" : fmtMoney(daily, cur)}</b>
          <small>z historii transakcji</small></div>
        <div className="card"><label>OPEN TRADES</label><b>{a ? positions.length : "—"}</b><small>{s.symbol?.symbol}</small></div>
        <div className="card"><label>WIN RATE</label><b>{wr?.win_rate === null || wr?.win_rate === undefined ? "brak danych" : `${fmtNum(wr.win_rate, 1)}%`}</b>
          <small>{wr ? `${wr.trades} transakcji (${botStats?.bot?.mode ?? ""})` : ""}</small></div>
      </div>
      <div className="hdr-buttons">
        <button className="icon big" title="Agent Claude" onClick={onAgent}>✦</button>
        <button className="icon big" title="Ustawienia" onClick={onSettings}>⚙</button>
        <button className="icon big danger" title="Zatrzymanie: nowe wejścia / pozycje / aplikacja" onClick={onPower}>⏻</button>
      </div>
    </header>
  );
}
