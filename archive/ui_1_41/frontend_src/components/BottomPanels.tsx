import { useState } from "react";
import { apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

export function NewsPanel() {
  const { s } = useStore();
  const [tab, setTab] = useState<"news" | "cal" | "sent">("news");
  const n = s.news || {};
  const m = n.macro || {};
  return (
    <div className="panel news">
      <div className="panel-head">
        <div className="tabs">
          <button className={cls(tab === "news" && "on")} onClick={() => setTab("news")}>NEWS</button>
          <button className={cls(tab === "cal" && "on")} onClick={() => setTab("cal")}>ECONOMIC CALENDAR</button>
          <button className={cls(tab === "sent" && "on")} onClick={() => setTab("sent")}>MARKET SENTIMENT</button>
        </div>
        <span className="spacer" />
        <span className={cls("badge", m.status === "PARTIAL" ? "warn" : m.status === "DISABLED" ? "muted" : "bad")} title={m.note || n.error || ""}>
          M04N {n.status ?? "…"} · kalendarz {m.status ?? "?"}{m.risk_level === "HIGH" ? " · OKNO MAKRO" : ""}
        </span>
        <button className="icon" title="Odśwież źródła" onClick={() => apiSend("POST", "/api/v1/news/refresh").catch(() => undefined)}>↻</button>
      </div>
      <div className="news-body">
        {tab === "news" && (
          <ul className="list">
            {(n.news || []).slice(0, 30).map((x: any) => (
              <li key={x.event_id}>
                <span className="time">{fmtTime(x.published_at || x.first_seen_at)}</span>
                <span className={cls("tag", x.impact === "HIGH" || x.impact === "EXTREME" ? "bad" : "muted")}>{x.source_id}</span>
                <a href={x.url} target="_blank" rel="noreferrer noopener">{x.headline}</a>
              </li>
            ))}
            {!(n.news || []).length && <li className="muted">{n.error ? `Źródła niedostępne: ${n.error}` : n.status === "NOT_LOADED" ? "Pobieranie…" : "Brak nagłówków w oknie 48 h (to nie oznacza braku wydarzeń)."}</li>}
          </ul>
        )}
        {tab === "cal" && (
          <ul className="list">
            {(n.calendar || []).map((e: any) => (
              <li key={e.event_id}>
                <span className="time">{fmtTime(e.scheduled_at, true)}</span>
                <span className="tag">{e.currency ?? "USD"}</span>
                <span className={cls("tag", e.impact === "HIGH" ? "bad" : e.impact === "MEDIUM" ? "warn" : "muted")}>{e.impact}</span>
                <span>{e.name}</span>
                <span className="muted small">{e.actual ? ` A:${e.actual}` : ""}{e.forecast ? ` F:${e.forecast}` : ""}{e.previous ? ` P:${e.previous}` : ""}</span>
              </li>
            ))}
            {!(n.calendar || []).length && <li className="muted">{m.status === "PARTIAL" ? "Brak wpisów w częściowym kalendarzu (nie oznacza braku wydarzeń)." : "Kalendarz niedostępny – nie zakładamy braku wydarzeń."}</li>}
          </ul>
        )}
        {tab === "sent" && <div className="muted pad">{n.sentiment?.note ?? "Brak źródła sentymentu."}</div>}
      </div>
    </div>
  );
}

export function RiskPanel({ onSettings }: { onSettings: () => void }) {
  const { s } = useStore();
  const r = s.risk_config || {};
  const risk = s.decision?.risk || {};
  const v = (x: any, suf = "") => (x === null || x === undefined ? <span className="neg">nie ustawiono</span> : `${x}${suf}`);
  return (
    <div className="panel risk">
      <div className="panel-head"><span className="ptitle">RISK MANAGEMENT</span><span className="spacer" />
        <button className="icon" title="Ustaw limity" onClick={onSettings}>✎</button></div>
      <div className="risk-grid">
        <div><label>Ryzyko / transakcja</label><b>{v(r.risk_per_trade_pct, "%")}</b></div>
        <div><label>Maks. pozycji</label><b>{v(r.max_open_positions)}</b></div>
        <div><label>Dzienny limit straty</label><b>{v(r.daily_loss_limit_pct, "%")}</b></div>
        <div><label>Maks. drawdown</label><b>{v(r.max_drawdown_pct, "%")}</b></div>
        <div><label>Suma otwartego ryzyka</label><b>{v(r.max_total_open_risk_pct, "%")}</b></div>
        <div><label>Bramka ryzyka</label><b className={risk.risk_gate === "PASS" ? "pos" : "neg"}>{risk.risk_gate ?? "—"}</b></div>
        <div className="wide"><label>Dziś zużyto</label><b>{risk.daily?.used !== undefined && risk.daily?.used !== null ? `${fmtNum(risk.daily.used)} ${risk.currency ?? ""}` : "—"}</b>
          <small>{s.costs_config?.spread_40pct_rule === "REQUIRES_DEFINITION" ? "Reguła „spread 40%”: wymaga definicji mianownika – nieaktywna" : ""}</small></div>
      </div>
    </div>
  );
}

export function BotLog() {
  const { s } = useStore();
  return (
    <div className="panel log">
      <div className="panel-head"><span className="ptitle">BOT LOG</span></div>
      <ul className="list mono">
        {(s.logs || []).slice(0, 60).map((l: any, i: number) => (
          <li key={l.id ?? `${l.ts}-${i}`} className={cls(l.level === "ERROR" ? "bad" : l.level === "WARNING" ? "warn" : "")}>
            <span className="time">{fmtTime(l.ts, true)}</span> {l.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
