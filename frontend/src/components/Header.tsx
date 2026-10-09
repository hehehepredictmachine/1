import { useState } from "react";
import { apiSend } from "../api";
import { Frog } from "../appearance";
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

export default function Header({ onAgent, onSettings, onPower, onMode, onLook, botStats }: {
  onAgent: () => void;
  onSettings: () => void;
  onPower: () => void;
  onMode: () => void;
  onLook: () => void;
  botStats: any;
}) {
  const { s, refresh } = useStore();
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
  const auto = s.auto || {};
  const [autoErr, setAutoErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toggleStrategyMode = async () => {
    setAutoErr(null);
    setBusy(true);
    try {
      const next = auto.strategy_mode === "MANUAL" ? { strategy_mode: "AUTO" } : { strategy_mode: "MANUAL", manual_strategy_id: auto.selected_strategy_id || "S01" };
      await apiSend("POST", "/api/v1/strategy/mode", next);
      await refresh();
    } catch (e: any) {
      setAutoErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const execOn = mode.mode && mode.mode !== "SIGNALS" && !mode.kill_switch;
  const autoTone = auto.system_state === "STALE" || auto.data_status !== "OK" ? "warn" : auto.system_state === "CONFIRMED" ? "ok" : "muted";
  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--panel)" stroke="var(--neon)" /><path d="M8 22V11m5 11V7m5 15v-8m5 8V13" stroke="var(--neon)" strokeWidth="2.6" strokeLinecap="round" /></svg>
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
        <button className={cls("chip mode", mode.mode === "AUTO_LIVE" ? "bad" : mode.mode === "SIGNALS" ? "muted" : "warn")} onClick={onMode}
          title="Tryb wykonania – kliknij, aby zmienić (osobno od wyboru strategii i trybu ML)">
          WYKONANIE <b>{mode.mode_label ?? mode.mode ?? "…"}</b>
        </button>
        <button className={cls("chip auto-sel", autoTone)} onClick={toggleStrategyMode} disabled={busy || auto.profile === "ORIGINAL"}
          title={(autoErr ? "Błąd: " + autoErr + "\n" : "") + "Wybór strategii (nie składa zleceń). Kliknij, aby przełączyć AUTO / MANUAL. Stan potwierdzony przez backend."}>
          <i className="dot" />{auto.profile === "ORIGINAL" ? "PROFIL ORIGINAL" : <>AUTO — wybór strategii <b>{auto.strategy_mode ?? "…"}</b></>}
          {auto.profile !== "ORIGINAL" && <b className="sub">{auto.selected_strategy_id ?? "brak"} · {auto.system_state ?? "…"}</b>}
        </button>
        <span className={cls("chip", (s.decision?.mode_gate?.allowed ? (mode.mode === "AUTO_LIVE" ? "bad" : "ok") : execOn ? "warn" : "muted"))}
          title={(s.decision?.mode_gate?.reason_codes || []).join(", ") || "Zlecenia dopuszczone przez tryb – pozostałe bramki w checkliście"}>
          <i className="dot" />Zlecenia <b>{mode.mode === "SIGNALS" ? "brak (analiza)" : mode.kill_switch ? "STOP" : s.decision?.mode_gate?.allowed ? "dozwolone" : "wstrzymane"}</b>
        </span>
        <span className={cls("chip", (s.ml?.status === "ACTIVE" || s.ml?.status === "SHADOW") ? "ok" : s.ml?.status === "ERROR" || s.ml?.status === "DEGRADED" ? "bad" : "muted")}
          title={s.ml?.reason || ""}>
          <i className="dot" />ML <b>{s.ml?.mode ?? "…"} · {s.ml?.status ?? "…"}</b>
        </span>
        {autoErr && <span className="chip bad" title={autoErr}><i className="dot" />AUTO: błąd zapisu</span>}
        {mode.kill_switch && <span className="chip bad"><i className="dot" />NOWE WEJŚCIA ZATRZYMANE</span>}
      </div>
      <div className="cards">
        <div className="balance-group">
          <Frog />
          <div className="card"><label>BALANCE</label><b>{fmtMoney(a?.balance, cur)}</b><small>{cur ?? ""}</small></div>
        </div>
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
        <button className="icon big" title="Wygląd – kolory i motywy" onClick={onLook}>🎨</button>
        <button className="icon big" title="Ustawienia" onClick={onSettings}>⚙</button>
        <button className="icon big danger" title="Zatrzymanie: nowe wejścia / pozycje / aplikacja" onClick={onPower}>⏻</button>
      </div>
    </header>
  );
}
