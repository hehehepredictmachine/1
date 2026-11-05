// CONTROL TOWER – BOT MANAGEMENT CENTER (controltower.jpg). Every setting here is the REAL configuration of the bot:
//   strategy selection -> POST /api/v1/strategy/mode; thresholds, filters, risk limits, Telegram -> PUT /api/v1/config (validated);
//   presets -> /api/v1/presets/strategy; Auto Trading Stop -> POST /api/v1/kill (STOP of new entries); Emergency Kill Switch and the
//   autopilot open the existing confirmation dialogs (account confirmation for AUTO, "ZAMKNIJ" for closing positions).
// Results come from /api/v1/stats (closed trades of the bot in the current mode; ROI by the modified Dietz method). Nothing is
// invented: periods / metrics the API does not provide are shown as unavailable.
import { useEffect, useMemo, useState } from "react";
import { apiSend } from "../../api";
import { ModeDialog, PowerDialog } from "../../components/Dialogs";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { A } from "./assets";
import CultShell from "./CultShell";
import { hhmm, kindOf, money, num, pct, signed, useEnvKind, useGet, useLatency, type Kind } from "./data";
import { Badge, Bar, Icon, Monitor, NA, Ring, Stat, StatusBar, Tag, Toggle } from "./kit";

const PERIODS: { id: string; label: string; key: string | null }[] = [
  { id: "24H", label: "24H", key: "day" }, { id: "7D", label: "7D", key: "week" }, { id: "30D", label: "30D", key: "month" },
  { id: "90D", label: "90D", key: null }, { id: "YTD", label: "YTD", key: null }, { id: "ALL", label: "ALL", key: "all" },
];

function Msg({ m }: { m: string | null }) {
  return m ? <p className={cls("cu-msg", m.startsWith("Błąd") || m.startsWith("Odmowa") ? "bad" : "ok")} role="status">{m}</p> : null;
}

function EquityLine({ points }: { points: any[] }) {
  const pts = (points || []).map((p: any) => (Array.isArray(p) ? p[1] : p.equity ?? p.value)).filter((v: any) => Number.isFinite(v));
  if (pts.length < 2) return <NA>Za mało zapisanych snapshotów equity (zapis co 60 s podczas pracy bota).</NA>;
  const lo = Math.min(...pts), hi = Math.max(...pts), w = 400, h = 120;
  const d = pts.map((v: number, i: number) => `${(i / (pts.length - 1)) * w},${h - ((v - lo) / (hi - lo || 1)) * (h - 10) - 5}`).join(" ");
  return <svg className="ct-eq" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Krzywa equity"><polyline points={d} /></svg>;
}

function Performance({ stats, env }: { stats: any; env: Kind }) {
  const [per, setPer] = useState("30D");
  const p = PERIODS.find((x) => x.id === per)!;
  const agg = p.key ? stats.d?.bot?.[p.key] : null;
  const roi = stats.d?.account_roi;
  const eng = stats.d?.engines;
  const recent: any[] = stats.d?.bot?.recent || [];
  const buy = recent.filter((r) => (r.side ?? r.direction) === "BUY" || (r.side ?? r.direction) === "LONG").length;
  const sell = recent.length - buy;
  const days = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of recent) { const d = (r.closed_at || "").slice(0, 10); if (d) m.set(d, (m.get(d) ?? 0) + (r.net_pnl ?? 0)); }
    return [...m.entries()].sort().slice(-30);
  }, [recent]);
  const dmax = Math.max(1e-9, ...days.map(([, v]) => Math.abs(v)));
  const k = kindOf(stats, env, !!agg?.trades);
  return (
    <Monitor id="ct-perf" title="PERFORMANCE INTELLIGENCE" icon="chart" className="ct-perf" testid="ct-performance"
      right={<span className="ct-periods" role="group" aria-label="Okres">{PERIODS.map((x) => (
        <button key={x.id} type="button" className={cls(per === x.id && "on")} disabled={!x.key} aria-pressed={per === x.id} onClick={() => setPer(x.id)}
          title={x.key ? undefined : "okres niedostępny w API statystyk (dzień / tydzień / miesiąc / całość)"} data-testid={`ct-per-${x.id}`}>{x.label}</button>))}<Tag kind={k} /></span>}>
      <div className="ct-perf-top">
        <Ring label="ROI" value={per === "30D" && roi?.status === "OK" ? roi.roi_pct : null} max={Math.max(10, Math.abs(roi?.roi_pct ?? 0))}
          text={per === "30D" && roi?.status === "OK" ? pct(roi.roi_pct, 2) : "—"} testid="ct-roi" />
        <Ring label="WIN RATIO" value={agg?.win_rate ?? null} text={agg?.win_rate != null ? pct(agg.win_rate) : "—"} testid="ct-winratio" />
        <dl className="cu-kv ct-kv">
          <dt>Total Trades</dt><dd data-testid="ct-trades">{agg ? agg.trades : "—"}</dd><dt>Winning Trades</dt><dd>{agg?.wins ?? "—"}</dd>
          <dt>Losing Trades</dt><dd>{agg?.losses ?? "—"}</dd><dt>Profit Factor</dt><dd>{agg?.profit_factor != null ? num(agg.profit_factor) : "—"}</dd>
          <dt>Avg. R</dt><dd>{agg?.avg_r != null ? signed(agg.avg_r) : "—"}</dd><dt>Net P/L</dt><dd>{agg?.trades ? signed(agg.net) : "—"}</dd>
        </dl>
        <div className="ct-eq-box"><EquityLine points={stats.d?.equity?.points} /></div>
      </div>
      {per === "30D" && roi?.status !== "OK" && <NA>ROI: {roi?.note ?? "brak danych"}</NA>}
      <div className="ct-perf-row">
        <div><h3 className="cu-h3">PERFORMANCE BY ASSET</h3>{!eng || !Object.keys(eng.per_symbol || {}).length ? <NA>brak rozliczonych transakcji</NA> :
          Object.entries(eng.per_symbol).map(([sym, a]: any) => <Bar key={sym} label={sym} value={a.win_rate != null ? a.win_rate / 100 : null} text={`${signed(a.net)} · ${pct(a.win_rate)}`} />)}</div>
        <div><h3 className="cu-h3">PERFORMANCE BY MODEL</h3>{!eng ? <NA>…</NA> :
          Object.entries(eng.per_engine || {}).map(([e, a]: any) => <Bar key={e} label={e.replace("ACTIVE_", "").replace("SH_", "")} value={a.win_rate != null ? a.win_rate / 100 : null}
            text={a.trades ? `${signed(a.net)} · ${pct(a.win_rate)}` : "brak transakcji"} title="silnik / ścieżka decyzji bota" />)}</div>
        <div><h3 className="cu-h3">TRADE DISTRIBUTION</h3>{!recent.length ? <NA>brak transakcji</NA> : (
          <div className="ct-dist"><Ring label="TRADES" value={recent.length} max={recent.length} text={String(recent.length)} size={96} color="#b46bff" />
            <ul><li className="buy">BUY {pct((buy / recent.length) * 100)}</li><li className="sell">SELL {pct((sell / recent.length) * 100)}</li></ul>
            <small className="cu-dim">ostatnie {recent.length} transakcji</small></div>)}</div>
        <div><h3 className="cu-h3">DAILY P/L</h3>{!days.length ? <NA>brak transakcji</NA> : (
          <div className="ct-days">{days.map(([d, v]) => <i key={d} title={`${d}: ${signed(v)}`} className={v >= 0 ? "up" : "dn"} style={{ height: `${(Math.abs(v) / dmax) * 100}%` }} />)}</div>)}</div>
      </div>
    </Monitor>);
}

function StrategyControl({ cfg, reload, setups }: { cfg: any; reload: () => void; setups: any }) {
  const { s } = useStore();
  const pre = useGet<any>("/api/v1/presets/strategy", 0);
  const shG = useGet<any>("/api/v1/sh", 60000);
  const [f, setF] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pick, setPick] = useState("");
  useEffect(() => {
    if (cfg) setF({ mode: cfg.active.strategy_mode, manual: cfg.active.manual_strategy_id ?? "S01", early: cfg.active.thresholds.early, confirmed: cfg.active.thresholds.confirmed,
      macro: cfg.risk.macro_block_high_impact, spread: cfg.risk.max_spread_points ?? "", d1: cfg.strategy.d1_conflict_blocks_entry });
  }, [cfg]);
  if (!f) return <Monitor id="ct-strategy" title="STRATEGY CONTROL CENTER" icon="sliders" className="ct-strat"><NA>Ładowanie konfiguracji…</NA></Monitor>;
  const strategies: any[] = setups.d?.strategies || [];
  const run = async (fn: () => Promise<any>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg(ok); reload(); pre.load(); } catch (e: any) { setMsg(`Błąd: ${String(e?.message || e)}`); }
  };
  const save = () => run(async () => {
    if (f.mode !== cfg.active.strategy_mode || (f.mode === "MANUAL" && f.manual !== cfg.active.manual_strategy_id))
      await apiSend("POST", "/api/v1/strategy/mode", f.mode === "AUTO" ? { strategy_mode: "AUTO" } : { strategy_mode: "MANUAL", manual_strategy_id: f.manual });
    await apiSend("PUT", "/api/v1/config", { active: { thresholds: { ...cfg.active.thresholds, early: Number(f.early), confirmed: Number(f.confirmed) } },
      risk: { macro_block_high_impact: f.macro, max_spread_points: f.spread === "" ? null : Number(f.spread) }, strategy: { d1_conflict_blocks_entry: f.d1 } });
  }, "Zapisano ustawienia strategii (obowiązują od następnej decyzji).");
  const models: any[] = (shG.d?.models?.rows || []).filter((m: any) => m.kind !== "DETERMINISTIC");
  return (
    <Monitor id="ct-strategy" title="STRATEGY CONTROL CENTER" icon="sliders" className="ct-strat" testid="ct-strategy">
      <label className="cu-field">Active Strategy
        <select value={f.mode === "AUTO" ? "AUTO" : f.manual} onChange={(e) => setF({ ...f, mode: e.target.value === "AUTO" ? "AUTO" : "MANUAL", manual: e.target.value === "AUTO" ? f.manual : e.target.value })}
          data-testid="ct-active-strategy">
          <option value="AUTO">AUTO – wybór przez bota{s.decision?.setup?.strategy_id ? ` (teraz ${s.decision.setup.strategy_id})` : ""}</option>
          {strategies.map((x) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} {x.name}</option>)}
        </select></label>
      <div className="ct-models"><span>Active Models</span>
        {models.length ? models.slice(0, 5).map((m: any) => <Badge key={m.id} tone={m.status?.includes("OK") || m.status === "READY" ? "ok" : "muted"} title={m.reason}>{m.name?.split(" ")[0] ?? m.id}</Badge>)
          : <small className="cu-dim">rola modeli w strategiach SH: Wind Portal / Modele</small>}</div>
      <p className="cu-na">Model Weights: wagi wynikają z walidacji walk-forward (Wind Portal → AI Consensus Matrix) – nie ustawia się ich ręcznie.</p>
      <label className="cu-field">Consensus Threshold <small>(próg CONFIRMED oceny setupu 0–100)</small>
        <input type="number" min={0} max={100} step={1} value={f.confirmed} onChange={(e) => setF({ ...f, confirmed: e.target.value })} data-testid="ct-th-confirmed" /></label>
      <label className="cu-field">Min. Confidence <small>(próg EARLY oceny setupu 0–100)</small>
        <input type="number" min={0} max={100} step={1} value={f.early} onChange={(e) => setF({ ...f, early: e.target.value })} data-testid="ct-th-early" /></label>
      <div className="ct-filters"><span>Trade Filters</span>
        <Toggle on={!!f.macro} onChange={(v) => setF({ ...f, macro: v })} label="News (blokada makro)" testid="ct-f-news" />
        <Toggle on={!!f.d1} onChange={(v) => setF({ ...f, d1: v })} label="Konflikt D1" testid="ct-f-d1" />
        <label className="cu-field inline">Max spread [pkt]<input type="number" min={0} value={f.spread} placeholder="bez limitu" onChange={(e) => setF({ ...f, spread: e.target.value })} data-testid="ct-f-spread" /></label>
      </div>
      <div className="cu-row">
        <button type="button" className="cu-btn acc" onClick={save} data-testid="ct-strategy-save">Zapisz</button>
        <input className="ct-preset-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="nazwa presetu" aria-label="Nazwa presetu" data-testid="ct-preset-name" />
        <button type="button" className="cu-btn" disabled={!name.trim()} onClick={() => run(() => apiSend("POST", "/api/v1/presets/strategy", { name: name.trim() }), `Zapisano preset „${name.trim()}”.`)}
          data-testid="ct-preset-save">Save Preset</button>
        <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Preset do wczytania" data-testid="ct-preset-pick">
          <option value="">— preset —</option>{(pre.d?.items || []).map((p: any) => <option key={p.name} value={p.name}>{p.name}</option>)}</select>
        <button type="button" className="cu-btn" disabled={!pick} onClick={() => run(() => apiSend("POST", "/api/v1/presets/strategy/load", { name: pick }), `Wczytano preset „${pick}”.`)}
          data-testid="ct-preset-load">Load</button>
        <button type="button" className="cu-btn" onClick={() => { if (window.confirm("Przywrócić domyślne ustawienia sterowania strategią (wybór strategii, progi, filtry)?")) void run(() => apiSend("POST", "/api/v1/presets/strategy/reset", {}), "Przywrócono ustawienia domyślne."); }}
          data-testid="ct-preset-reset">Reset</button>
      </div>
      <Msg m={msg} />
    </Monitor>);
}

function RiskCenter({ cfg, reload }: { cfg: any; reload: () => void }) {
  const ctx = useTerminalContext();
  const [f, setF] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [power, setPower] = useState(false);
  useEffect(() => { if (cfg) setF({ ...cfg.risk }); }, [cfg]);
  if (!f) return <Monitor id="ct-risk" title="RISK MANAGEMENT CENTER" icon="shield" className="ct-risk"><NA>Ładowanie…</NA></Monitor>;
  const field = (k: string, label: string, unit: string, step = 0.1) => (
    <label className="cu-field row" key={k}><Icon n="shield" size={15} />{label}
      <input type="number" step={step} min={0} value={f[k] ?? ""} placeholder="bez limitu" onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? null : Number(e.target.value) })}
        data-testid={`ct-risk-${k}`} /><small>{unit}</small></label>);
  const save = async () => {
    setMsg(null);
    try {
      await apiSend("PUT", "/api/v1/config", { risk: { risk_per_trade_pct: f.risk_per_trade_pct, daily_loss_limit_pct: f.daily_loss_limit_pct,
        max_drawdown_pct: f.max_drawdown_pct, max_open_positions: f.max_open_positions } });
      setMsg("Zapisano limity ryzyka (obowiązują od następnej decyzji).");
      reload();
    } catch (e: any) { setMsg(`Błąd: ${String(e?.message || e)}`); }
  };
  const kill = async (on: boolean) => {
    if (on && !window.confirm("Zatrzymać NOWE wejścia bota (STOP)? Otwarte pozycje pozostają zarządzane.")) return;
    try { await apiSend("POST", "/api/v1/kill", { on, reason: on ? "control_tower_stop" : "control_tower_resume" }); setMsg(on ? "STOP nowych wejść włączony." : "Nowe wejścia wznowione."); }
    catch (e: any) { setMsg(`Odmowa: ${String(e?.message || e)}`); }
  };
  return (
    <Monitor id="ct-risk" title="RISK MANAGEMENT CENTER" icon="shield" className="ct-risk" testid="ct-risk">
      {field("risk_per_trade_pct", "Risk per Trade", "% equity")}
      {field("daily_loss_limit_pct", "Daily Loss Limit", "% salda dnia")}
      {field("max_drawdown_pct", "Max Drawdown", "% od szczytu")}
      {field("max_open_positions", "Max Open Positions", "pozycji", 1)}
      <Toggle on={ctx.killSwitch} onChange={kill} label={<><Icon n="clock" size={15} />Auto Trading Stop <small>(STOP nowych wejść)</small></>} testid="ct-kill" />
      <div className="cu-row"><span><Icon n="alert" size={15} /> Emergency Kill Switch</span>
        <button type="button" className="cu-btn danger" onClick={() => setPower(true)} data-testid="ct-emergency">⏻ ACTIVATE</button></div>
      <button type="button" className="cu-btn acc" onClick={save} data-testid="ct-risk-save">Zapisz limity</button>
      <Msg m={msg} />
      {power && <PowerDialog onClose={() => setPower(false)} />}
    </Monitor>);
}

function TelegramStudio({ cfg, reload }: { cfg: any; reload: () => void }) {
  const tg = useGet<any>("/api/v1/telegram", 30000);
  const saved = useGet<any>("/api/v1/telegram/template", 0);      // 1.32: own file (data/telegram/signal_template.json), not config.json
  const [tab, setTab] = useState<"Template" | "Editor" | "Variables" | "Preview">("Editor");
  const [tpl, setTpl] = useState<string>("");
  const [prev, setPrev] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [flags, setFlags] = useState<any>(null);
  useEffect(() => { if (cfg) setFlags({ ...cfg.telegram }); }, [cfg]);
  useEffect(() => { if (saved.d) setTpl(saved.d.template ?? ""); }, [saved.d]);
  useEffect(() => {
    const t = setTimeout(() => {
      apiSend("POST", "/api/v1/telegram/preview", { template: tpl }).then((r) => { setPrev(r); }).catch((e: any) => setPrev({ error: String(e?.message || e) }));
    }, 350);
    return () => clearTimeout(t);
  }, [tpl]);
  if (!flags || (!saved.d && !saved.err)) return <Monitor id="ct-telegram" title="TELEGRAM MESSAGE STUDIO" icon="send" className="ct-tg"><NA>Ładowanie…</NA></Monitor>;
  const vars = prev?.variables || {};
  const saveAll = async () => {
    setMsg(null);
    try {
      await apiSend("PUT", "/api/v1/telegram/template", { template: tpl.trim() ? tpl : null });     // validated first: a bad template saves nothing
      await apiSend("PUT", "/api/v1/config", { telegram: { send_signals: flags.send_signals, send_trades: flags.send_trades, send_stats: flags.send_stats } });
      setMsg("Zapisano szablon i ustawienia wiadomości.");
      reload();
      saved.load();
    } catch (e: any) { setMsg(`Błąd: ${String(e?.message || e)}`); }
  };
  const test = async () => {
    setMsg("Wysyłanie wiadomości testowej…");
    try { const r: any = await apiSend("POST", "/api/v1/telegram/test", { template: tpl }); setMsg(r.ok ? "Wiadomość testowa dostarczona." : `Odmowa: ${r.error}`); tg.load(); }
    catch (e: any) { setMsg(`Błąd: ${String(e?.message || e)}`); }
  };
  return (
    <Monitor id="ct-telegram" title="TELEGRAM MESSAGE STUDIO" icon="send" className="ct-tg" testid="ct-telegram"
      right={<Badge tone={tg.d?.state === "OK" ? "ok" : tg.d?.state === "ERROR" ? "bad" : "muted"}>{tg.d?.state ?? "…"}</Badge>}>
      <div className="ct-tg-tabs" role="tablist">{(["Template", "Editor", "Variables", "Preview"] as const).map((t) => (
        <button key={t} role="tab" aria-selected={tab === t} className={cls(tab === t && "on")} onClick={() => setTab(t)} data-testid={`ct-tg-tab-${t}`}>{t}</button>))}</div>
      <div className="ct-tg-body">
        <div className="ct-tg-main">
          {tab === "Template" && <NA>{tpl.trim() ? "Własny szablon sygnału jest ustawiony." : "Format wbudowany (EN / 中文). Zacznij edycję w zakładce Editor."} Język: {flags.language}. Tag symulatora i zdanie „Analysis only – not an order.” bot dodaje zawsze.</NA>}
          {tab === "Editor" && <textarea value={tpl} onChange={(e) => setTpl(e.target.value)} rows={8} maxLength={1500} spellCheck={false} data-testid="ct-tg-editor"
            placeholder={"PEPEMARKETWIZARD SIGNAL\nSymbol: {symbol}\nDirection: {direction}\nEntry: {entry}\nStop Loss: {sl}\nTake Profit: {tp}\nTimeframe: {timeframe}"} aria-label="Szablon wiadomości sygnału" />}
          {tab === "Variables" && <ul className="ct-vars">{Object.entries(vars).map(([k, d]: any) => (
            <li key={k}><button type="button" onClick={() => { setTpl(tpl + `{${k}}`); setTab("Editor"); }}>{`{${k}}`}</button> {d}</li>))}</ul>}
          {(tab === "Preview" || tab === "Editor") && (
            <pre className={cls("ct-tg-prev", prev?.error && "bad")} data-testid="ct-tg-preview">{prev?.error ?? prev?.text ?? "…"}</pre>)}
          {prev?.source === "EXAMPLE" && <small className="cu-dim">Podgląd na przykładowych danych (brak sygnału w tej sesji).</small>}
        </div>
        <div className="ct-tg-side">
          <Toggle on={!!flags.send_signals} onChange={(v) => setFlags({ ...flags, send_signals: v })} label="Trade Signal" testid="ct-tg-signals" />
          <Toggle on={!!flags.send_trades} onChange={(v) => setFlags({ ...flags, send_trades: v })} label="Trade Open / Close" testid="ct-tg-trades" />
          <Toggle on={!!flags.send_stats} onChange={(v) => setFlags({ ...flags, send_stats: v })} label="Daily Summary" testid="ct-tg-stats" />
          <Toggle on={false} onChange={() => undefined} disabled label="Performance Report" title="brak takiej wiadomości w bocie" />
          <button type="button" className="cu-btn" onClick={test} data-testid="ct-tg-test"><Icon n="send" size={14} /> Test Send</button>
          <button type="button" className="cu-btn acc" onClick={saveAll} data-testid="ct-tg-save">Save Template</button>
        </div>
      </div>
      {saved.err && <NA>Nie można odczytać zapisanego szablonu: {saved.err}</NA>}
      {saved.d?.load_error && <NA>{saved.d.load_error}</NA>}
      {!cfg.telegram.enabled && <NA>Powiadomienia są wyłączone w konfiguracji (token bota i chat_id: Ustawienia → Inne / Centrum sterowania).</NA>}
      <Msg m={msg} />
    </Monitor>);
}

function DataQuality() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const news = useGet<any>("/api/v1/news", 60000);
  const dq = s.decision?.data_quality;
  const meta = s.tf_meta || {};
  const gaps = Object.values(meta).reduce((a: number, m: any) => a + (m?.gap_fills ?? 0), 0);
  const revs = Object.values(meta).reduce((a: number, m: any) => a + (m?.revisions ?? 0), 0);
  const loaded = Object.values(meta).filter((m: any) => m?.loaded).length;
  const ping = s.connection?.terminal?.ping_last;
  const rows = [
    { n: "MT5 Price Feed", ok: ctx.mt5 === "CONNECTED", v: ctx.mt5State ?? "—" },
    { n: "OHLC Data", ok: loaded > 0, v: `${loaded}/${Object.keys(meta).length} TF` },
    { n: "Tick Data", ok: s.quote?.age_seconds != null && s.quote.age_seconds < 30, v: s.quote?.age_seconds != null ? `${num(s.quote.age_seconds, 1)} s` : "—" },
    { n: "Economic Calendar", ok: news.d?.status === "OK", v: news.d?.status ?? "—" },
    { n: "Market News", ok: news.d?.status === "OK" && (news.d?.news || []).length > 0, v: news.d ? `${(news.d.news || []).length} wiad.` : "—" },
  ];
  return (
    <Monitor id="ct-data" title="DATA QUALITY & FEEDS" icon="db" className="ct-dq" testid="ct-data">
      <Ring label="DATA QUALITY" value={dq === "GOOD" ? 100 : dq === "DEGRADED" ? 60 : dq ? 20 : null} text={dq ?? "—"} testid="ct-dq-ring"
        color={dq === "GOOD" ? "var(--cu-green)" : "#ffcc4d"} />
      <ul className="cu-checks">{rows.map((r) => <li key={r.n} className={r.ok ? "ok" : "warn"}><Icon n={r.ok ? "check" : "x"} size={14} />{r.n}<em>{r.v}</em></li>)}</ul>
      <dl className="cu-kv">
        <dt>Data Freshness</dt><dd>{s.quote?.age_seconds != null ? `${num(s.quote.age_seconds, 1)} s` : "—"}</dd>
        <dt>Missing Candles</dt><dd title="świece uzupełnione po lukach (gap fills) we wszystkich TF">{gaps}</dd>
        <dt>Duplicate Records</dt><dd title="korekty / ponowne wersje świec (revisions); duplikatów rekordów strumień nie przyjmuje">{revs} korekt</dd>
        <dt>Feed Latency</dt><dd title="ping terminala MT5 do serwera brokera">{ping != null ? `${num(ping / 1000, 0)} ms` : "—"}</dd>
      </dl>
      <p className="cu-dim">Jakość wg werdyktu silnika (GOOD / DEGRADED / STALE) – bez procentów, których bot nie liczy.</p>
    </Monitor>);
}

function Autopilot() {
  const { s } = useStore();
  const [open, setOpen] = useState<string | null>(null);
  const mode = s.mode?.mode;
  const tiles = [
    { id: "MANUAL", label: "MANUAL", sub: "Analysis Only", modes: ["SIGNALS"], target: "SIGNALS", note: "SIGNALS – analiza warunków, bez zleceń" },
    { id: "SEMI", label: "SEMI-AUTO", sub: "Symulacja", modes: ["PAPER"], target: "PAPER", note: "PAPER – automatyczna symulacja, bez zleceń u brokera (potwierdzanie pojedynczych transakcji nie istnieje w bocie)" },
    { id: "FULL", label: "FULL AUTO", sub: "Live Trading", modes: ["AUTO_DEMO", "AUTO_LIVE"], target: s.account?.trade_mode === "REAL" ? "AUTO_LIVE" : "AUTO_DEMO", note: "AUTO DEMO / AUTO LIVE wg typu rachunku – z potwierdzeniem rachunku" },
  ];
  return (
    <Monitor id="ct-autopilot" title="BOT AUTOPILOT" icon="robot" className="ct-auto" testid="ct-autopilot">
      <div className="ct-tiles">{tiles.map((t) => (
        <button key={t.id} type="button" className={cls("ct-tile", t.modes.includes(mode) && "on")} onClick={() => setOpen(t.target)} title={t.note} data-testid={`ct-ap-${t.id}`}
          aria-pressed={t.modes.includes(mode)}><i className="ct-radio" /><b>{t.label}</b><small>({t.sub})</small></button>))}</div>
      <p className="ct-cur">Current Mode: <b className="buy">{s.mode?.mode_label ?? mode ?? "—"}</b>{s.mode?.kill_switch ? " · STOP" : ""}</p>
      <p className="cu-dim">Zmiana trybu otwiera okno trybów pracy (potwierdzenie rachunku dla AUTO). Kafelek nie zmienia niczego sam.</p>
      {open && <ModeDialog initial={open} onClose={() => setOpen(null)} />}
    </Monitor>);
}

function Infrastructure({ res }: { res: any }) {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const tg = useGet<any>("/api/v1/telegram", 30000);
  const r = res.d;
  const ping = s.connection?.terminal?.ping_last;
  const rows: { n: string; v: number | null; t: string; ok: boolean | null }[] = [
    { n: "MT5 Connection", v: ping != null ? Math.min(1, ping / 1000 / 200) : null, t: ping != null ? `${num(ping / 1000, 0)} ms` : ctx.mt5State ?? "—", ok: ctx.mt5 === "CONNECTED" },
    { n: "Telegram API", v: null, t: tg.d?.state ?? "—", ok: tg.d?.state === "OK" ? true : tg.d?.state === "ERROR" ? false : null },
    { n: "Data Feed (Primary)", v: s.quote?.age_seconds != null ? Math.min(1, s.quote.age_seconds / 30) : null, t: s.quote?.age_seconds != null ? `tick ${num(s.quote.age_seconds, 1)} s` : "—", ok: ctx.freshness === "FRESH" },
    { n: "Data Feed (Backup)", v: null, t: "brak – bot używa tylko MT5", ok: null },
    { n: "System CPU", v: r?.cpu_pct != null ? r.cpu_pct / 100 : null, t: r?.cpu_pct != null ? pct(r.cpu_pct, 0) : "brak pomiaru", ok: r?.cpu_pct != null ? r.cpu_pct < 90 : null },
    { n: "System RAM", v: r?.memory?.used_pct != null ? r.memory.used_pct / 100 : null, t: r?.memory?.used_pct != null ? `${pct(r.memory.used_pct, 0)}${r.memory.process_mb ? ` · bot ${num(r.memory.process_mb, 0)} MB` : ""}` : "brak pomiaru", ok: r?.memory?.used_pct != null ? r.memory.used_pct < 92 : null },
  ];
  return (
    <Monitor id="ct-infra" title="INFRASTRUCTURE MONITOR" icon="server" className="ct-infra" testid="ct-infra" right={<Tag kind={kindOf(res, "REAL")} title="pomiar z komputera bota" />}>
      {rows.map((x) => (
        <div key={x.n} className={cls("ct-infra-r", x.ok === true && "ok", x.ok === false && "bad")}>
          <Icon n={x.ok === false ? "x" : "check"} size={14} /><Bar label={x.n} value={x.v} text={x.t} /></div>))}
    </Monitor>);
}

function AuditLog() {
  const logs = useGet<any[]>("/api/v1/logs", 10000);
  const [cat, setCat] = useState("ALL");
  const cats = useMemo(() => [...new Set((logs.d || []).map((l: any) => l.category))].sort(), [logs.d]);
  const rows = (logs.d || []).filter((l: any) => cat === "ALL" || l.category === cat).slice(0, 40);
  return (
    <Monitor id="ct-audit" title="SYSTEM AUDIT LOG (LIVE)" icon="log" className="ct-audit" testid="ct-audit"
      right={<select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Filtr zdarzeń" data-testid="ct-audit-filter">
        <option value="ALL">All Events</option>{cats.map((c) => <option key={c} value={c}>{c}</option>)}</select>}>
      {!rows.length ? <NA>{logs.err ? `Błąd: ${logs.err}` : "Brak zdarzeń."}</NA> : (
        <table className="cu-tbl ct-log"><thead><tr><th>TIMESTAMP</th><th>EVENT TYPE</th><th>DESCRIPTION</th><th>STATUS</th></tr></thead>
          <tbody>{rows.map((l: any) => (
            <tr key={l.id}><td>{hhmm(l.ts)}</td><td><Badge tone="info">{l.category}</Badge></td><td>{l.message}</td>
              <td>{l.level === "ERROR" ? <Badge tone="bad">ERROR</Badge> : l.level === "WARNING" ? <Badge tone="warn">WARN</Badge> : <Icon n="check" size={14} />}</td></tr>))}</tbody></table>)}
    </Monitor>);
}

export default function ControlTower() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const env = useEnvKind();
  const lat = useLatency();
  const cfgG = useGet<any>("/api/v1/config", 0);
  const stats = useGet<any>("/api/v1/stats", 20000);
  const setups = useGet<any>("/api/v1/setups", 60000);
  const res = useGet<any>("/api/v1/system/resources", 10000);
  const tg = useGet<any>("/api/v1/telegram", 30000);
  const cfg = cfgG.d?.config;
  const roi = stats.d?.account_roi, all = stats.d?.bot?.all;
  const up = res.d?.uptime_s;
  const health = ctx.warnings.length ? (ctx.backend !== "OPEN" ? "OFFLINE" : "WARN") : "OK";
  const tabs = [{ id: "ct-perf", label: "PERFORMANCE" }, { id: "ct-strategy", label: "STRATEGY" }, { id: "ct-risk", label: "RISK" }, { id: "ct-telegram", label: "TELEGRAM" },
    { id: "ct-infra", label: "INFRASTRUCTURE" }, { id: "ct-audit", label: "AUDIT" }, { id: "ct-autopilot", label: "AUTOPILOT" }];
  return (
    <CultShell page="control" tower="control" title="CONTROL TOWER – BOT MANAGEMENT CENTER" accent="#ffb347" bg={A.panelBg("control")} tabs={tabs}
      emblem={{ title: "CONTROL TOWER", sub: "BOT MANAGEMENT" }}
      right={<div className="ct-chips">
        <span className="ct-time" title="czas serwera bota (UTC)"><small>SERVER TIME (UTC)</small><b data-testid="ct-server-time">{s.server_time ? new Date(s.server_time).toISOString().slice(11, 19) : "—"}</b></span>
        <span className={cls("ct-chip", ctx.backend === "OPEN" ? "ok" : "bad")}><Icon n="robot" size={14} />{ctx.backend === "OPEN" ? "BOT ONLINE" : "BOT OFFLINE"}</span>
        <span className={cls("ct-chip", ctx.mt5 === "CONNECTED" ? "ok" : "bad")}><Icon n="check" size={14} />{ctx.mt5 === "CONNECTED" ? "MT5 CONNECTED" : "MT5 " + (ctx.mt5State ?? "?")}</span>
        <span className={cls("ct-chip", tg.d?.state === "OK" ? "ok" : "muted")}><Icon n="send" size={14} />TELEGRAM {tg.d?.state === "OK" ? "OK" : tg.d?.state ?? "—"}</span></div>}>
      <div className="ct-grid">
        <img className="cu-pepe ct-pepe" src={A.panelPepe("control")} alt="" aria-hidden="true" />
        <Performance stats={stats} env={env} />
        <DataQuality />
        {cfgG.err && <NA>Błąd odczytu konfiguracji: {cfgG.err}</NA>}
        <StrategyControl cfg={cfg} reload={cfgG.load} setups={setups} />
        <RiskCenter cfg={cfg} reload={cfgG.load} />
        {cfg && <TelegramStudio cfg={cfg} reload={cfgG.load} />}
        <Autopilot />
        <Infrastructure res={res} />
        <AuditLog />
      </div>
      <StatusBar testid="ct-bar" centre={<img src={A.panelCentre("control")} alt="" />}>
        <Stat icon="robot" label="BOT STATUS" value={ctx.backend !== "OPEN" ? "OFFLINE" : ctx.killSwitch ? "STOP" : "RUNNING"} tone={ctx.backend === "OPEN" && !ctx.killSwitch ? "ok" : "bad"} />
        <Stat icon="chart" label="ROI (30D)" value={roi?.status === "OK" ? pct(roi.roi_pct, 2) : "—"} kind={kindOf(stats, env, roi?.status === "OK")} />
        <Stat icon="target" label="WIN RATIO" value={all?.win_rate != null ? pct(all.win_rate) : "—"} kind={kindOf(stats, env, all?.win_rate != null)} />
        <Stat icon="bars" label="PROFIT FACTOR" value={all?.profit_factor != null ? num(all.profit_factor) : "—"} kind={kindOf(stats, env, all?.profit_factor != null)} />
        <span className="cu-sbar-gap" aria-hidden="true" />
        <Stat icon="alert" label="MAX DRAWDOWN" value={all?.max_drawdown != null ? money(-all.max_drawdown, s.account?.currency) : "—"} sub="zrealizowany wynik" kind={kindOf(stats, env, all?.max_drawdown != null)} />
        <Stat icon="db" label="DATA QUALITY" value={s.decision?.data_quality ?? "—"} tone={s.decision?.data_quality === "GOOD" ? "ok" : "warn"} />
        <Stat icon="clock" label="LATENCY" value={lat != null ? `${lat} ms` : "—"} sub="API lokalne" />
        <Stat icon="clock" label="UPTIME" value={up != null ? `${Math.floor(up / 3600)} h ${Math.floor((up % 3600) / 60)} min` : "—"} sub="silnik bota" />
        <Stat icon="shield" label="SYSTEM HEALTH" value={health} tone={health === "OK" ? "ok" : "bad"} sub={`${ctx.warnings.length} ostrzeżeń`} />
      </StatusBar>
    </CultShell>);
}
