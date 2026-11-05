// STRATEGY LAB – QUANT STRATEGY CHAMBER (strategy.png): chamber, Hybrid Builder, hybrid colour system (purple / gold / green).
// Built on the strategies the bot really has (S01–S12 registry, SCALPING / HEDGING) - nothing is invented:
//   AI Strategy Engine  - model families of the catalog + the setup thresholds (same real config as the Control Tower);
//   Strategy Settings   - active strategy, active instrument, the strategy's own TF / direction rules, real filters only;
//   Strategy Builder    - Visual Builder = the live decision pipeline of the engine (data -> conditions -> AI -> entry rules ->
//                         execute / reject); Code (Pseudo) = the rules of the selected strategy read from its setup details;
//                         Advanced Editor / Condition Wizard / AI Assistant have no backend in the bot -> marked "do doprecyzowania";
//   TEST STRATEGY       - scan on, trade off for the strategy (the bot generates its signals without trading);
//   DEPLOY TO BOT       - trade on for the strategy (with a confirmation; the execution mode still decides about orders);
//   Library / Comparison / Performance - registry + per-strategy statistics; Strategy Evolution - optimizer not active in the bot.
import { useMemo, useState } from "react";
import { apiSend } from "../../api";
import ChartPanel from "../../components/ChartPanel";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { A } from "./assets";
import CultShell from "./CultShell";
import { MODEL_FAMILIES, familyState, kindOf, num, pct, signed, useEnvKind, useGet } from "./data";
import { Badge, Icon, Monitor, NA, Ring, Stat, StatusBar, Tag, Toggle } from "./kit";

const BUILDER_TABS = ["Visual Builder", "Advanced Editor", "Code (Pseudo)", "Condition Wizard", "AI Assistant"] as const;

export default function StrategyLab() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const env = useEnvKind();
  const auto = useGet<any>("/api/v1/strategy/auto", 15000);
  const cat = useGet<any>("/api/v1/models/catalog", 60000);
  const cfgG = useGet<any>("/api/v1/config", 0);
  const stats = useGet<any>("/api/v1/stats", 30000);
  const dec = useGet<any>("/api/v1/decision", 10000);
  const sig = useGet<any>("/api/v1/bot-signals?limit=200", 30000);
  const [tab, setTab] = useState<(typeof BUILDER_TABS)[number]>("Visual Builder");
  const [lib, setLib] = useState<"ACTIVE" | "DRAFT" | "ARCHIVED">("ACTIVE");
  const [msg, setMsg] = useState<string | null>(null);
  const [per, setPer] = useState<"week" | "month" | "all">("month");
  const [full, setFull] = useState(false);
  const setupsG = useGet<any>("/api/v1/setups", 60000);
  const cfg = cfgG.d?.config;
  // registry S01–S12 (names from /api/v1/setups) + per-strategy flags of the config (no entry = scan and trade on, as the endpoint)
  const strategies = useMemo(() => {
    const m = (cfg?.active?.strategies || {}) as Record<string, { scan: boolean; trade: boolean }>;
    const per = (auto.d?.per_strategy || {}) as Record<string, any>;
    return ((setupsG.d?.strategies || []) as any[]).map((r) => {
      const flag = m[r.strategy_id];
      const scan = flag ? flag.scan : true, trade = flag ? flag.trade : true;
      return { id: r.strategy_id as string, name: r.name as string, scan, trade, state: trade && scan ? "ACTIVE" : scan ? "DRAFT" : "ARCHIVED", status: per[r.strategy_id]?.status };
    });
  }, [cfg, auto.d, setupsG.d]);
  const selId = auto.d?.selected_strategy_id ?? s.decision?.setup?.strategy_id ?? strategies.find((x) => x.state === "ACTIVE")?.id ?? null;
  const selSetup = s.decision?.setup;
  const tree: any[] = dec.d?.decision_tree || [];
  const node = (n: string) => tree.find((x: any) => x.node === n)?.status ?? "—";
  const perStrat = stats.d?.engines?.per_strategy || {};
  const agg = stats.d?.bot?.[per];
  const sigOf = (id: string) => (sig.d?.items || []).filter((x: any) => x.strategy_id === id);
  const lastSig = selId ? sigOf(selId)[0] : null;
  const fams = MODEL_FAMILIES.map((f) => ({ f, st: familyState(cat.d, f.ids) }));
  const toggle = async (id: string, body: { scan?: boolean; trade?: boolean }, ok: string, confirm?: string) => {
    if (confirm && !window.confirm(confirm)) return;
    setMsg(null);
    try { await apiSend("POST", "/api/v1/strategy/toggle", { strategy_id: id, ...body }); setMsg(ok); cfgG.load(); auto.load(); }
    catch (e: any) { setMsg(`Błąd: ${String(e?.message || e)}`); }
  };
  const pseudo = useMemo(() => {
    const d = lastSig?.detail;
    if (!d) return null;
    const ep = d.entry_plan || {};
    return [`STRATEGY ${lastSig.strategy_id} ${lastSig.strategy_name} (${d.strategy_version ?? "—"})  TF ${lastSig.timeframe}  ${d.family ?? ""}`,
      `IF regime = ${d.regime ?? "?"} AND ${(d.reason_codes || []).join(" AND ") || "warunki strategii"}`,
      `   ENTRY  ${ep.order_type ?? lastSig.entry_type} – ${ep.trigger ?? "wg strategii"}`,
      `   ZONE   ${ep.zone ? `${num(ep.zone[0])} … ${num(ep.zone[1])}` : "—"}   max ${ep.max_wait_bars ?? "—"} świec`,
      `   STOP   ${num(lastSig.stop_loss)}  (unieważnienie ${d.invalidation_rule ?? "—"} ${num(d.invalidation_level)})`,
      `   TP     ${(lastSig.take_profits || []).map((t: number) => num(t)).join(" / ")}  (RR ${d.exit_rules?.rr ?? lastSig.rr1}, BE po TP1: ${d.exit_rules?.be_after_tp1 ? "tak" : "nie"})`,
      `REJECT IF ${(lastSig.validation?.reasons || []).join(", ") || "walidacja OK"}`].join("\n");
  }, [lastSig]);
  return (
    <CultShell page="strategy-lab" tower="strategy" title="STRATEGY LAB — QUANT STRATEGY CHAMBER" accent="#b46bff" bg={A.panelBg("strategy")}
      emblem={{ title: "STRATEGY LAB", sub: "QUANT RESEARCH" }}
      tabs={[{ id: "sl-builder", label: "DEVELOP" }, { id: "sl-settings", label: "CONFIGURE" }, { id: "sl-perf", label: "BACKTEST" },
        { id: "sl-evo", label: "OPTIMIZE" }, { id: "sl-compare", label: "COMPARE" }, { id: "sl-deploy", label: "DEPLOY" }]}>
      <div className="sl-grid">
        <img className="cu-pepe sl-pepe" src={A.panelPepe("strategy")} alt="" aria-hidden="true" />
        <Monitor title="AI STRATEGY ENGINE" icon="brain" className="sl-engine" testid="sl-engine">
          <ul className="sl-models">{fams.map(({ f, st }) => (
            <li key={f.key} title={f.none ?? st.items.map((x: any) => `${x.name}: ${x.state_pl ?? x.state}`).join("\n")}>
              <Icon n="gear" size={15} /><b>{f.label}</b><em>{f.ids.length ? `${st.ready}/${st.total}` : "brak"}</em>
              <span className={cls("sl-dot", st.ready ? "on" : "")} aria-label={st.ready ? "gotowy" : "niegotowy"} /></li>))}</ul>
          {cfg && <dl className="cu-kv">
            <dt>Consensus Threshold</dt><dd>≥ {num(cfg.active.thresholds.confirmed, 0)} <small>(CONFIRMED)</small></dd>
            <dt>Min. Confidence</dt><dd>≥ {num(cfg.active.thresholds.early, 0)} <small>(EARLY)</small></dd>
            <dt>Model Agreement</dt><dd>wg dowodów modeli (Wind Portal)</dd></dl>}
          <p className="cu-dim">Progi i filtry zmieniasz w Control Tower → Strategy Control Center (ta sama konfiguracja bota).</p>
        </Monitor>
        <div className="sl-chamber" aria-hidden="true"><img src={A.panelCentre("strategy")} alt="" /><i /></div>
        <Monitor id="sl-perf" title="STRATEGY PERFORMANCE" icon="chart" className="sl-perf" testid="sl-performance"
          right={<span className="ct-periods">{(["week", "month", "all"] as const).map((p) => (
            <button key={p} type="button" className={cls(per === p && "on")} onClick={() => setPer(p)}>{p === "week" ? "7D" : p === "month" ? "30D" : "ALL"}</button>))}<Tag kind={kindOf(stats, env, !!agg?.trades)} /></span>}>
          <div className="sl-perf-top">
            <Ring label="ROI" value={per === "month" && stats.d?.account_roi?.status === "OK" ? stats.d.account_roi.roi_pct : null} text={per === "month" && stats.d?.account_roi?.status === "OK" ? pct(stats.d.account_roi.roi_pct, 2) : "—"} size={104} />
            <Ring label="WIN RATIO" value={agg?.win_rate ?? null} text={agg?.win_rate != null ? pct(agg.win_rate) : "—"} size={104} />
            <dl className="cu-kv"><dt>Total Trades</dt><dd>{agg?.trades ?? "—"}</dd><dt>Winning</dt><dd>{agg?.wins ?? "—"}</dd><dt>Losing</dt><dd>{agg?.losses ?? "—"}</dd>
              <dt>Profit Factor</dt><dd>{agg?.profit_factor != null ? num(agg.profit_factor) : "—"}</dd><dt>Max Drawdown</dt><dd>{agg?.max_drawdown != null ? `−${num(agg.max_drawdown)}` : "—"}</dd>
              <dt>Net P/L</dt><dd>{agg?.trades ? signed(agg.net) : "—"}</dd></dl>
          </div>
        </Monitor>
        <Monitor id="sl-settings" title="STRATEGY SETTINGS" icon="sliders" className="sl-settings" testid="sl-settings">
          <dl className="cu-kv">
            <dt>Active Strategy</dt><dd data-testid="sl-active">{selId ? `${selId} ${strategies.find((x) => x.id === selId)?.name ?? ""}` : "—"} ({auto.d?.strategy_mode ?? cfg?.active?.strategy_mode ?? "—"})</dd>
            <dt>Instrument</dt><dd>{ctx.instrument ?? "—"} · {ctx.brokerSymbol ?? "—"}</dd>
            <dt>Timeframe</dt><dd>{selSetup?.setup_tf ?? lastSig?.timeframe ?? "wg strategii"}</dd>
            <dt>Direction</dt><dd>Both (Long / Short) – kierunek wybiera strategia</dd>
          </dl>
          {cfg && <>
            <Toggle on={!!cfg.risk.macro_block_high_impact} disabled onChange={() => undefined} label="News Filter (makro)" title="zmiana: Control Tower → Trade Filters" />
            <Toggle on={cfg.risk.max_spread_points != null} disabled onChange={() => undefined} label="Spread Filter" title="limit spreadu: Control Tower → Trade Filters" />
            <Toggle on={!!cfg.strategy.d1_conflict_blocks_entry} disabled onChange={() => undefined} label="Konflikt D1" />
          </>}
          <p className="cu-dim">Smart Money / Smart Odds / Volatility / Liquidity Filter z projektu nie są osobnymi przełącznikami w bocie – są warunkami poszczególnych strategii (do doprecyzowania, jeśli mają być ustawieniami).</p>
        </Monitor>
        <Monitor id="sl-builder" title="STRATEGY BUILDER — HYBRID MODE" icon="grid" className="sl-builder" testid="sl-builder">
          <div className="ct-tg-tabs" role="tablist">{BUILDER_TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={cls(tab === t && "on")} onClick={() => setTab(t)} data-testid={`sl-tab-${t.split(" ")[0]}`}>{t}</button>))}</div>
          {tab === "Visual Builder" && (
            <div className="sl-flow" data-testid="sl-flow">
              <div className={cls("sl-node", node("DATA") === "PASS" && "ok")}><Icon n="db" /><b>MARKET DATA</b><small>{ctx.brokerSymbol} · OHLC / Tick · {s.decision?.data_quality ?? "—"}</small><em>{node("DATA")}</em></div>
              <i className="sl-arrow" />
              <div className={cls("sl-node", node("MARKET") === "PASS" && "ok")}><Icon n="sliders" /><b>CONDITIONS</b><small>reżim, struktura, trigger</small><em>{node("MARKET")} / {node("TRIGGER")}</em></div>
              <i className="sl-arrow" />
              <div className={cls("sl-node", node("AI") === "PASS" && "ok")}><Icon n="brain" /><b>AI CONSENSUS</b><small>agent / modele (weto, ocena)</small><em>{node("AI")}</em></div>
              <i className="sl-arrow" />
              <div className={cls("sl-node", node("RISK") === "PASS" && "ok")}><Icon n="target" /><b>ENTRY RULES</b><small>ocena ≥ progi, ryzyko, RR</small><em>{node("STRATEGY")} / {node("RISK")}</em></div>
              <div className="sl-out">
                <span className={cls("sl-exec", dec.d?.decision === "ENTER" && "on")}><Icon n="check" />EXECUTE TRADE</span>
                <span className={cls("sl-rej", dec.d?.decision && dec.d.decision !== "ENTER" && "on")}><Icon n="x" />REJECT SETUP<small>{dec.d?.decision ?? "—"}</small></span>
              </div>
            </div>)}
          {tab === "Code (Pseudo)" && (pseudo ? <pre className="sl-code" data-testid="sl-pseudo">{pseudo}</pre> : <NA>Brak sygnału wybranej strategii – reguły pojawią się z pierwszym setupem.</NA>)}
          {(tab === "Advanced Editor" || tab === "Condition Wizard" || tab === "AI Assistant") && (
            <NA>„{tab}” – bot nie ma edytora własnych strategii (strategie S01–S12 i SCALPING/HEDGING są w kodzie). Funkcja wymaga doprecyzowania
              zakresu, zanim zostanie zbudowana.</NA>)}
          <div className="cu-row" id="sl-deploy">
            <button type="button" className="cu-btn" disabled={!selId} data-testid="sl-test"
              onClick={() => selId && toggle(selId, { scan: true, trade: false }, `${selId}: tryb testu – bot wyznacza sygnały, nie handluje tą strategią.`,
                `TEST STRATEGY ${selId}: bot będzie wyznaczał sygnały tej strategii bez handlu nią (scan ON, trade OFF). Kontynuować?`)}>
              <Icon n="flask" size={15} /> TEST STRATEGY</button>
            <button type="button" className="cu-btn acc" disabled={!selId} data-testid="sl-deploy"
              onClick={() => selId && toggle(selId, { scan: true, trade: true }, `${selId}: włączona do handlu (o zleceniach nadal decyduje tryb wykonania: ${ctx.modeLabel ?? ctx.mode}).`,
                `DEPLOY TO BOT ${selId}: strategia będzie mogła otwierać wejścia w bieżącym trybie wykonania (${ctx.modeLabel ?? ctx.mode}). Kontynuować?`)}>
              <Icon n="send" size={15} /> DEPLOY TO BOT</button>
          </div>
          {msg && <p className={cls("cu-msg", msg.startsWith("Błąd") ? "bad" : "ok")} role="status">{msg}</p>}
        </Monitor>
        <Monitor title="STRATEGY LIBRARY" icon="log" className="sl-lib" testid="sl-library">
          <div className="ct-tg-tabs">{(["ACTIVE", "DRAFT", "ARCHIVED"] as const).map((k) => (
            <button key={k} className={cls(lib === k && "on")} onClick={() => setLib(k)} title={k === "ACTIVE" ? "scan + trade" : k === "DRAFT" ? "tylko scan (test)" : "wyłączone"}>
              {k === "ACTIVE" ? "Active" : k === "DRAFT" ? "Drafts" : "Archived"} ({strategies.filter((x) => x.state === k).length})</button>))}</div>
          <ul className="sl-lib-l">{strategies.filter((x) => x.state === lib).map((x) => (
            <li key={x.id}><Icon n="target" size={14} /><b>{x.id}</b><span>{x.name}</span><Badge tone={x.state === "ACTIVE" ? "ok" : x.state === "DRAFT" ? "warn" : "muted"}>{x.state}</Badge>
              {x.state !== "ARCHIVED" && <button type="button" className="cu-mini" onClick={() => toggle(x.id, { scan: false, trade: false }, `${x.id}: wyłączona.`, `Wyłączyć strategię ${x.id}?`)}>wyłącz</button>}
              {x.state === "ARCHIVED" && <button type="button" className="cu-mini" onClick={() => toggle(x.id, { scan: true, trade: false }, `${x.id}: przywrócona do testu.`)}>przywróć</button>}</li>))}</ul>
          {!strategies.length && <NA>{auto.err ? `Błąd: ${auto.err}` : "Ładowanie rejestru strategii…"}</NA>}
        </Monitor>
        <Monitor title="ENTRY & EXIT DESIGNER" icon="target" className="sl-entry" testid="sl-entry">
          <div className="sl-entry-in">
            <div className="sl-mini-chart"><ChartPanel tf={selSetup?.setup_tf ?? "M15"} index={0} chartId="cult-sl" variant="compact" opts={{ showAiLevels: true, showVol: false } as any}
              fullscreen={full} onFullscreen={() => setFull(!full)} /></div>
            <dl className="cu-kv">
              <dt>Entry Method</dt><dd>{lastSig?.detail?.entry_plan?.order_type ?? lastSig?.entry_type ?? "—"}</dd>
              <dt>Stop Loss</dt><dd>{lastSig?.detail?.invalidation_rule ?? "—"} {lastSig ? num(lastSig.stop_loss) : ""}</dd>
              <dt>Take Profit</dt><dd>{lastSig?.detail?.exit_rules?.tp_rule ?? "—"} (RR {lastSig?.detail?.exit_rules?.rr ?? "—"})</dd>
              <dt>Trailing Stop</dt><dd>{lastSig?.detail?.exit_rules?.trailing ?? "brak"}</dd>
              <dt>Breakeven</dt><dd>{cfg ? (cfg.strategy.move_sl_to_breakeven_after_tp1 ? "po TP1 (konfiguracja)" : "wyłączony") : "—"}</dd>
              <dt>Invalidation</dt><dd>{lastSig?.detail?.invalidation_level != null ? num(lastSig.detail.invalidation_level) : "—"}</dd>
            </dl>
          </div>
        </Monitor>
        <Monitor id="sl-compare" title="STRATEGY COMPARISON" icon="bars" className="sl-compare" testid="sl-compare" right={<Tag kind={kindOf(stats, env, Object.keys(perStrat).length > 0)} />}>
          {!Object.keys(perStrat).length ? <NA>Brak rozliczonych transakcji strategii w tym trybie ({stats.d?.engines?.mode ?? "—"}).</NA> : (
            <table className="cu-tbl"><thead><tr><th>Strategy</th><th>Net</th><th>Win Ratio</th><th>PF</th><th>DD</th><th>Trades</th></tr></thead>
              <tbody>{Object.entries(perStrat).map(([k, a]: any) => (
                <tr key={k}><td>{k}</td><td>{signed(a.net)}</td><td>{pct(a.win_rate)}</td><td>{a.profit_factor != null ? num(a.profit_factor) : "—"}</td>
                  <td>{a.max_drawdown != null ? `−${num(a.max_drawdown)}` : "—"}</td><td>{a.trades}</td></tr>))}</tbody></table>)}
        </Monitor>
        <Monitor id="sl-evo" title="STRATEGY EVOLUTION (AI)" icon="dna" className="sl-evo" testid="sl-evolution">
          <dl className="cu-kv"><dt>Warianty</dt><dd>—</dd><dt>Testowane</dt><dd>—</dd><dt>Najlepszy wynik</dt><dd>—</dd></dl>
          <NA>Optymalizator wariantów (BUZOA / SDOm) jest w katalogu modułów jako {(cat.d?.items || []).find((x: any) => x.id === "mm_buzoa")?.state_pl ?? "wyłączony"} – bot nie generuje
            nowych wariantów strategii. „Generate new variants” wymaga doprecyzowania.</NA>
          <button type="button" className="cu-btn" disabled title="brak aktywnego optymalizatora w bocie">GENERATE NEW VARIANTS</button>
        </Monitor>
      </div>
      <StatusBar testid="sl-bar">
        <Stat icon="target" label="ACTIVE STRATEGY" value={selId ?? "—"} sub={auto.d?.strategy_mode ?? ""} />
        <Stat icon="brain" label="AI CONSENSUS" value={`${fams.filter(({ st }) => st.ready).length}/${fams.filter(({ f }) => f.ids.length).length}`} sub="rodzin z gotowym modelem" />
        <Stat icon="shield" label="RISK (PER TRADE)" value={cfg?.risk?.risk_per_trade_pct != null ? pct(cfg.risk.risk_per_trade_pct, 2) : "brak limitu"} />
        <Stat icon="bars" label="RR (TAKE PROFIT)" value={lastSig?.rr1 != null ? `1 : ${num(lastSig.rr1, 1)}` : "—"} sub="ostatni sygnał" />
        <Stat icon="alert" label="MAX DRAWDOWN" value={agg?.max_drawdown != null ? `−${num(agg.max_drawdown)}` : "—"} kind={kindOf(stats, env, agg?.max_drawdown != null)} />
        <Stat icon="chart" label="EXPECTANCY" value={agg?.expectancy_r != null ? `${signed(agg.expectancy_r)}R` : "—"} kind={kindOf(stats, env, agg?.expectancy_r != null)} />
        <Stat icon="bars" label="SHARPE RATIO" value="—" sub="bot nie liczy" tone="muted" />
        <Stat icon="db" label="STABILITY" value="—" sub="bot nie liczy" tone="muted" />
        <Stat icon="send" label="DEPLOYMENT" value={ctx.modeLabel ?? ctx.mode ?? "—"} tone={ctx.mode === "AUTO_LIVE" ? "bad" : "ok"} />
      </StatusBar>
    </CultShell>);
}
