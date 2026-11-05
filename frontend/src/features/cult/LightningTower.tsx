// LIGHTNING TOWER – LIVE SIGNALS CENTER (lig.jpg). Sources: MT5 candles of the active symbol (ChartPanel, the single WebSocket),
// /api/v1/bot-signals (signals of all strategies: plan, lifecycle, validation), /api/v1/models/catalog + /api/v1/models/predictions
// (AI engine status / consensus - only real model outputs, uncalibrated values are labelled), /api/v1/montecarlo/scenarios,
// /api/v1/news + engine warnings (alerts), /api/v1/stats (bottom bar). A setup score is a heuristic 0-100, NEVER a probability.
import { Fragment, useMemo, useState } from "react";
import ChartPanel from "../../components/ChartPanel";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { A } from "./assets";
import CultShell from "./CultShell";
import { MODEL_FAMILIES, familyState, hhmm, kindOf, money, num, pct, signed, useEnvKind, useGet } from "./data";
import { Badge, Bar, Icon, Monitor, NA, Stat, StatusBar, Tag } from "./kit";

const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const ACTIVE = ["OPEN", "ACTIVE", "PENDING"];
const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "muted" | "info"> = { OPEN: "ok", ACTIVE: "ok", PENDING: "warn", CLOSED: "info", REJECTED: "bad", EXPIRED: "muted", CANCELLED: "muted" };

function lifecycle(sig: any): { label: string; at: string | null; done: boolean }[] {
  const val = sig?.validation;
  const rejected = sig?.status === "REJECTED";
  return [
    { label: "GENERATED", at: sig?.created_at ?? null, done: !!sig },
    { label: "ANALYZED", at: sig?.updated_at ?? null, done: !!val },
    { label: rejected ? "REJECTED" : "CONFIRMED", at: rejected || sig?.status !== "PENDING" ? sig?.updated_at ?? null : null, done: !!sig && sig.status !== "PENDING" },
    { label: "EXECUTED", at: sig?.filled_at ?? null, done: !!sig?.filled_at },
    { label: "TP / SL", at: sig?.closed_at ?? null, done: !!sig?.closed_at },
  ];
}

export default function LightningTower() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const env = useEnvKind();
  const [tf, setTf] = useState("M15");
  const [full, setFull] = useState(false);
  const sig = useGet<any>("/api/v1/bot-signals?limit=200", 10000);
  const cat = useGet<any>("/api/v1/models/catalog", 60000);
  const preds = useGet<any>(ctx.instrument ? `/api/v1/models/predictions?instrument=${ctx.instrument}` : null, 30000);
  const mc = useGet<any>("/api/v1/montecarlo/scenarios", 60000);
  const news = useGet<any>("/api/v1/news", 60000);
  const stats = useGet<any>("/api/v1/stats", 20000);
  const setups = useGet<any>("/api/v1/setups", 15000);
  const items: any[] = sig.d?.items || [];
  const [selId, setSelId] = useState<string | null>(null);
  const sel = items.find((x) => x.signal_id === selId) || items.find((x) => ACTIVE.includes(x.status)) || items[0] || null;
  const active = items.filter((x) => ACTIVE.includes(x.status));
  const recent = items.filter((x) => Date.now() - Date.parse(x.created_at) < 86400e3);
  const sameSymbol = sel && sel.symbol === s.symbol?.symbol;
  const aiLevels = sameSymbol ? { zone: sel.detail?.entry_plan?.zone ?? null, invalidation: sel.stop_loss ?? null, targets: sel.take_profits || [], label: "Sygnał" } : null;
  const ready = (cat.d?.items || []).filter((x: any) => x.category === "TRAINABLE");
  const fam = MODEL_FAMILIES.map((f) => ({ ...f, st: familyState(cat.d, f.ids) }));
  const predItems: any[] = (preds.d?.items || []).filter((p: any) => p.state === "READY" && p.result);
  const mcUp = mc.d?.scenarios?.p_up_reach?.[0], mcLvl = mc.d?.scenarios?.levels_price?.[0];
  const alerts = useMemo(() => {
    const out: { icon: string; text: string; right: string; tone: string }[] = [];
    for (const e of (news.d?.calendar || []).filter((x: any) => x.impact === "HIGH").slice(0, 3))
      out.push({ icon: "alert", text: `HIGH IMPACT NEWS (${e.currency ?? "?"}) ${e.title ?? ""}`, right: hhmm(e.time_utc ?? e.time), tone: "bad" });
    if (news.d && news.d.status !== "OK") out.push({ icon: "clock", text: `Kalendarz makro: ${news.d.status}`, right: news.d.error ? "błąd" : "—", tone: "muted" });
    const sp = s.quote?.spread_points, maxSp = s.risk_config?.max_spread_points;
    if (sp != null) out.push({ icon: "signal", text: "SPREAD", right: `${num(sp, 0)} pkt${maxSp ? ` (limit ${maxSp})` : ""}`, tone: maxSp && sp > maxSp ? "bad" : "ok" });
    for (const st of (setups.d?.items || []).filter((x: any) => x.status === "INVALIDATED" || x.scenario_status === "UNIEWAZNIONY").slice(0, 2))
      out.push({ icon: "x", text: `SETUP INVALIDATION ${st.strategy_id} ${st.symbol}`, right: st.terminal_reason_pl ?? "unieważniony", tone: "warn" });
    for (const w of ctx.warnings.slice(0, 3)) out.push({ icon: "alert", text: w, right: "", tone: "warn" });
    for (const l of ctx.alerts.slice(0, 3)) out.push({ icon: "alert", text: l.message, right: hhmm(l.ts), tone: l.level === "ERROR" ? "bad" : "warn" });
    return out.slice(0, 8);
  }, [news.d, s.quote?.spread_points, s.risk_config?.max_spread_points, setups.d, ctx.warnings, ctx.alerts]);
  const allStats = stats.d?.bot?.all, month = stats.d?.bot?.month;
  const rrAvg = active.length ? active.reduce((a, x) => a + (x.rr1 ?? 0), 0) / active.length : null;
  const aiOk = fam.filter((f) => f.st.ready > 0).length;
  return (
    <CultShell page="lightning" tower="lightning" title="⚡ LIGHTNING TOWER – LIVE SIGNALS CENTER ⚡" accent="#ffcc4d" bg={A.panelBg("lightning")}
      emblem={{ title: "LIGHTNING TOWER", sub: "LIVE SIGNALS" }}>
      <div className="lt-grid">
        <img className="cu-pepe lt-pepe" src={A.panelPepe("lightning")} alt="" aria-hidden="true" />
        <Monitor title="AI ENGINE STATUS" icon="bolt" className="lt-ai" testid="lt-ai-status" right={<Tag kind={kindOf(cat, "REAL")} title="stan modułów z katalogu modeli bota" />}>
          <ul className="cu-checks">
            {fam.map((f) => (
              <li key={f.key} className={f.st.ready ? "ok" : f.ids.length ? "warn" : "off"} title={f.none ?? f.st.items.map((x: any) => `${x.name}: ${x.state_pl ?? x.state}`).join("\n")}>
                <Icon n={f.st.ready ? "check" : "x"} size={15} />{f.label}<em>{f.ids.length ? `${f.st.ready}/${f.st.total} gotowe` : "brak w bocie"}</em></li>))}
            <li className={ready.length ? "ok" : "off"}><Icon n="check" size={15} />Model Sync<em>{cat.d ? `${ready.filter((x: any) => x.state === "READY").length}/${ready.length} trenowalnych` : "…"}</em></li>
            <li className={ctx.mt5 === "CONNECTED" ? "ok" : "bad"}><Icon n={ctx.mt5 === "CONNECTED" ? "check" : "x"} size={15} />MT5 Connection<em>{ctx.mt5State ?? "—"}</em></li>
          </ul>
        </Monitor>
        <Monitor title={`MT5 – ${s.symbol?.symbol ?? "—"} ${tf}`} icon="chart" className="lt-chart" testid="lt-chart"
          right={<span className={cls("lt-auto", s.account?.trade_allowed && s.account?.trade_expert ? "ok" : "bad")} title="Algo Trading w terminalu (stan z MT5)">
            AutoTrading {s.account?.trade_allowed && s.account?.trade_expert ? "✓" : "✗"}</span>}>
          <div className="lt-tfs" role="group" aria-label="Interwał">{TFS.map((t) => (
            <button key={t} type="button" className={cls(t === tf && "on")} aria-pressed={t === tf} onClick={() => setTf(t)} data-testid={`lt-tf-${t}`}>{t}</button>))}</div>
          <div className="lt-chart-box"><ChartPanel tf={tf} index={0} chartId="cult-lt" variant="compact" opts={{ showAiLevels: true, showVol: false } as any} aiLevels={aiLevels}
            fullscreen={full} onFullscreen={() => setFull(!full)} /></div>
          {sel && !sameSymbol && <p className="cu-na">Wybrany sygnał dotyczy {sel.symbol} – wykres pokazuje aktywny symbol bota ({s.symbol?.symbol}).</p>}
        </Monitor>
        <Monitor num="01." title="AI CONSENSUS ENGINE" icon="brain" className="lt-cons" testid="lt-consensus">
          {fam.map((f) => {
            const p = predItems.find((x) => f.st.items.some((it: any) => (x.model_key || "").startsWith(it.id)));
            const v = p?.result?.probability ?? p?.result?.p_up ?? null;
            return <Bar key={f.key} label={f.label} value={v} text={v != null ? pct(v * 100) : f.key === "mc" && mcUp != null ? `P(+${mcLvl}) ${pct(mcUp * 100)}` : "brak predykcji"}
              title={f.none ?? (p ? `${p.model_name} · ${p.calibration?.status ?? "kalibracja nieznana"}` : "model nie zwrócił predykcji (stan w AI ENGINE STATUS)")} />;
          })}
          <div className="lt-cons-ring">
            <span>CONSENSUS</span><b data-testid="lt-consensus-value">{predItems.length ? `${predItems.length} model.` : "—"}</b>
            <Badge tone="muted">{predItems.length ? "bez łączenia jednostek" : "BRAK KONSENSUSU"}</Badge>
          </div>
          <NA>Konsensus nie uśrednia różnych zadań i jednostek. Wartości modeli bez kalibracji są oznaczone. Monte Carlo = symulacja ścieżek (nieskalibrowana).</NA>
        </Monitor>
        <Monitor num="" title="AI SIGNAL ENGINE – LIVE SIGNALS" icon="bolt" className="lt-sigs" testid="lt-signals" right={<Tag kind={kindOf(sig, env)} />}>
          {!items.length ? <NA>{sig.err ? `Błąd: ${sig.err}` : "Brak sygnałów."}</NA> : (
            <table className="cu-tbl"><thead><tr><th>TIME</th><th>SYMBOL</th><th>DIR</th><th title="ocena setupu 0–100 – heurystyka, nie prawdopodobieństwo">SCORE</th><th>CONS</th><th>STATUS</th></tr></thead>
              <tbody>{items.slice(0, 7).map((x) => (
                <tr key={x.signal_id} className={cls(x === sel && "on")} onClick={() => setSelId(x.signal_id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelId(x.signal_id)}
                  data-testid="lt-signal-row">
                  <td>{hhmm(x.created_at)}</td><td>{x.symbol}</td><td className={x.action === "BUY" ? "buy" : "sell"}>{x.action}</td><td>{num(x.setup_score, 1)}</td>
                  <td title={x.ai_verdict ?? "brak oceny AI"}>{x.ai_verdict === "ZGODA" ? "✓" : x.ai_verdict === "BRAK_ZGODY" ? "✗" : "⏳"}</td>
                  <td><Badge tone={STATUS_TONE[x.status] ?? "muted"}>{x.status}</Badge></td></tr>))}</tbody></table>)}
        </Monitor>
        <Monitor num="05." title="SIGNAL LIFECYCLE" icon="target" className="lt-life" testid="lt-lifecycle">
          <ol className="lt-steps">{lifecycle(sel).map((st) => (
            <li key={st.label} className={cls(st.done && "done", st.label === "REJECTED" && "bad")}><i>{st.done ? "✓" : ""}</i><b>{st.label}</b><small>{hhmm(st.at)}</small></li>))}</ol>
          <h3 className="cu-h3">RECENT SIGNALS (LAST 24H)</h3>
          {!recent.length ? <NA>Brak sygnałów z ostatnich 24 h.</NA> : (
            <table className="cu-tbl"><thead><tr><th>SYMBOL</th><th>DIR</th><th>RESULT</th><th>R</th></tr></thead>
              <tbody>{recent.slice(0, 4).map((x) => (
                <tr key={x.signal_id}><td>{x.symbol}</td><td className={x.action === "BUY" ? "buy" : "sell"}>{x.action}</td>
                  <td>{x.tp_hit ? `TP${x.tp_hit}` : x.closed_at ? "SL / zamknięty" : x.status}</td><td>{x.outcome_r != null ? signed(x.outcome_r) : "—"}</td></tr>))}</tbody></table>)}
          <NA>Wynik sygnału w R (brutto, bez kosztów) – wynik po kosztach jest w Control Tower.</NA>
        </Monitor>
        <Monitor num="06." title="MARKET ALERT SYSTEM" icon="bell" className="lt-alerts" testid="lt-alerts">
          {!alerts.length ? <NA>Brak alertów.</NA> : (
            <ul className="lt-alert-list">{alerts.map((a, i) => <li key={i} className={`t-${a.tone}`}><Icon n={a.icon} size={16} /><span>{a.text}</span><em>{a.right}</em></li>)}</ul>)}
        </Monitor>
        <Monitor title="SELECTED SIGNAL – DETAILED PLAN" icon="bolt" className="lt-plan" testid="lt-plan">
          {!sel ? <NA>Wybierz sygnał z listy.</NA> : (
            <>
              <h3 className="lt-plan-h"><Icon n="coins" />{sel.symbol} – {sel.action === "BUY" ? "LONG" : "SHORT"}<Tag kind={sel.synthetic ? "SIM" : env} /></h3>
              <div className="lt-chips">
                <span title="ocena AI (agent Claude): zgoda / brak zgody – nie jest prawdopodobieństwem">AI VERDICT: <b>{sel.ai_verdict ?? "brak oceny"}</b></span>
                <span title={sel.detail?.score?.scale ?? "heurystyka 0–100"}>AI SCORE: <b>{num(sel.setup_score, 1)}/100</b></span>
              </div>
              <p className="cu-na">Confidence: brak skalibrowanego prawdopodobieństwa – ocena 0–100 to heurystyka strategii.</p>
              <h4><Icon n="target" size={16} />ENTRY PLAN</h4>
              <dl className="cu-kv">
                <dt>Entry</dt><dd>{num(sel.entry_price)}{sel.detail?.entry_plan?.zone ? ` (strefa ${num(sel.detail.entry_plan.zone[0])}–${num(sel.detail.entry_plan.zone[1])})` : ""}</dd>
                <dt>Order Type</dt><dd>{sel.detail?.entry_plan?.order_type ?? sel.entry_type ?? "—"}</dd>
                <dt>Strategia</dt><dd>{sel.strategy_id} {sel.strategy_name} · {sel.timeframe}</dd>
              </dl>
              <h4><Icon n="target" size={16} />TAKE PROFIT</h4>
              <dl className="cu-kv">{(sel.take_profits || []).map((tp: number, i: number) => (
                <Fragment key={i}><dt>TP{i + 1}</dt><dd className="buy">{num(tp)} ({signed(((tp - sel.entry_price) / sel.entry_price) * 100)} %)</dd></Fragment>))}</dl>
              <h4><Icon n="shield" size={16} />STOP LOSS</h4>
              <dl className="cu-kv"><dt>SL</dt><dd className="sell">{num(sel.stop_loss)} ({signed(((sel.stop_loss - sel.entry_price) / sel.entry_price) * 100)} %)</dd><dt>RR</dt><dd>{num(sel.rr1)}</dd></dl>
              <h4><Icon n="check" size={16} />REQUIRED CONDITIONS</h4>
              <ul className="cu-checks small">
                {(sel.detail?.reason_codes || []).slice(0, 6).map((c: string) => <li key={c} className="ok"><Icon n="check" size={13} />{c}</li>)}
                {(sel.detail?.missing_confirmations || []).map((c: string) => <li key={c} className="warn"><Icon n="x" size={13} />{c}</li>)}
              </ul>
              <div className="lt-inval">
                <h4><Icon n="x" size={16} />INVALIDATION (CANCEL SIGNAL)</h4>
                <ul>
                  {sel.detail?.invalidation_level != null && <li>Cena {sel.detail.invalidation_rule === "CLOSE_BEYOND" ? "zamyka się za" : "przekracza"} {num(sel.detail.invalidation_level)}</li>}
                  {(sel.validation?.reasons || []).map((r: string) => <li key={r}>{r}</li>)}
                  {!sel.detail?.invalidation_level && !(sel.validation?.reasons || []).length && <li>brak dodatkowych warunków</li>}
                </ul>
              </div>
            </>)}
        </Monitor>
        <img className="lt-orb" src={A.panelCentre("lightning")} alt="" aria-hidden="true" />
      </div>
      <StatusBar testid="lt-bar">
        <Stat icon="coins" label="PORTFOLIO (MT5)" value={s.account?.equity != null ? money(s.account.equity, s.account.currency) : "—"} kind={s.account ? env : "NONE"} />
        <Stat icon="bars" label="TOTAL P/L (MIESIĄC)" value={month?.trades ? signed(month.net) : "—"} sub={month?.trades ? `${month.trades} transakcji` : "brak transakcji"} kind={kindOf(stats, env, !!month?.trades)} />
        <Stat icon="target" label="WIN RATE" value={allStats?.win_rate != null ? pct(allStats.win_rate) : "—"} kind={kindOf(stats, env, allStats?.win_rate != null)} />
        <Stat icon="signal" label="ACTIVE SIGNALS" value={sig.d ? String(active.length) : "—"} kind={kindOf(sig, env)} />
        <Stat icon="sliders" label="RISK / REWARD (AVG)" value={rrAvg != null ? `1 : ${num(rrAvg, 1)}` : "—"} sub="aktywne sygnały" kind={kindOf(sig, env, rrAvg != null)} />
        <Stat icon="server" label="AI ENGINE HEALTH" value={cat.d ? `${aiOk}/${fam.filter((f) => f.ids.length).length} rodzin` : "—"} sub="z gotowym modelem" tone={aiOk ? "ok" : "warn"} />
      </StatusBar>
    </CultShell>);
}
