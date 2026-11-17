// Page 3 "Warunki setupu": the setup the user LOOKS AT (route #/warunki/<setup_id>, or #/warunki/bot = follow the bot's
// choice) is presentation state only. Reading uses GET /api/v1/setups and GET /api/v1/setups/{id}/details; the one
// mutation of the engine's strategy choice (POST /api/v1/prefs/setup-view) lives in the explicit "Działanie bota" card.
import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { LiveSetupsPanel, useAutoFull } from "../components/AutoPanels";
import { RiskPanel } from "../components/BottomPanels";
import MLPanel from "../components/MLPanel";
import { EnginePlan } from "../components/SignalsPanel";
import { href, navigate, usePersisted, type Route } from "../router";
import { useStore } from "../store";
import { useUi } from "../ui";
import { cls, fmtNum, fmtTime } from "../util";
import Section from "../components/Section";

type St = "MET" | "MISSING" | "PENDING" | "NO_DATA" | "NA";
const ST_PL: Record<St, string> = { MET: "Spełnione", MISSING: "Niespełnione", PENDING: "Oczekiwanie", NO_DATA: "Brak danych", NA: "Nie dotyczy" };
const ST_ICON: Record<St, string> = { MET: "✓", MISSING: "✗", PENDING: "…", NO_DATA: "?", NA: "–" };
const SCEN_PL: Record<string, string> = { WARUNKI_SPELNIONE: "warunki spełnione", OCZEKIWANIE: "oczekiwanie", UNIEWAZNIONY: "zakończony", BRAK_DANYCH: "brak danych" };
const STAGE_PL: Record<string, string> = { WATCH: "obserwacja", EARLY: "wczesny", CONFIRMED: "potwierdzony" };
const BIND_PL: Record<string, string> = { risk: "budżet ryzyka", margin: "wolny margin", exposure: "limit ekspozycji (dźwignia)", volume_max: "maks. wolumen symbolu" };
type Filter = "all" | "missing" | "nodata";

function useTick(ms: number) {
  const [t, setT] = useState(0);
  useEffect(() => { const h = setInterval(() => setT((x) => x + 1), ms); return () => clearInterval(h); }, [ms]);
  return t;
}

/** List of scenarios (read only). */
function SetupList({ list, viewed, followBot }: { list: any; viewed: string | null; followBot: boolean }) {
  const [f, setF] = usePersisted<{ sid: string; tf: string; dir: string; st: string }>("warunki.filters", { sid: "", tf: "", dir: "", st: "ACTIVE" },
    (x) => x && typeof x === "object" && "sid" in x);
  const items: any[] = (list?.items ?? []).filter((i: any) => (!f.sid || i.strategy_id === f.sid) && (!f.tf || i.timeframe === f.tf) && (!f.dir || i.direction === f.dir)
    && (!f.st || (f.st === "ACTIVE" ? i.status === "ACTIVE" : i.status !== "ACTIVE")));
  const tfs = [...new Set<string>((list?.items ?? []).map((i: any) => i.timeframe))];
  return (
    <section className="card setup-list" data-testid="setup-list">
      <div className="card-head"><h2>Wykryte setupy</h2>
        <a className={cls("btn ghost", followBot && "on")} href={href("warunki", { setupId: "bot" })} data-testid="follow-bot"
          title="Pokazuj zawsze setup aktualnie wybrany przez bota">Wybrany przez bota</a></div>
      <div className="filters" role="group" aria-label="Filtry listy">
        <select aria-label="Strategia" value={f.sid} onChange={(e) => setF({ ...f, sid: e.target.value })}>
          <option value="">wszystkie strategie</option>{(list?.strategies ?? []).map((x: any) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} {x.name}</option>)}</select>
        <select aria-label="Interwał" value={f.tf} onChange={(e) => setF({ ...f, tf: e.target.value })}><option value="">każdy TF</option>{tfs.map((t) => <option key={t}>{t}</option>)}</select>
        <select aria-label="Kierunek" value={f.dir} onChange={(e) => setF({ ...f, dir: e.target.value })}><option value="">oba kierunki</option><option value="BUY">BUY</option><option value="SELL">SELL</option></select>
        <select aria-label="Stan" value={f.st} onChange={(e) => setF({ ...f, st: e.target.value })}><option value="ACTIVE">aktywne</option><option value="ENDED">zakończone</option><option value="">wszystkie</option></select>
      </div>
      <ul className="setup-items">
        {items.map((i) => (
          <li key={i.setup_id} className={cls("setup-item", viewed === i.setup_id && "sel", i.status !== "ACTIVE" && "ended")} data-setup={i.setup_id}>
            <a href={href("warunki", { setupId: i.setup_id })} data-testid="open-details" aria-current={viewed === i.setup_id ? "true" : undefined}>
              <b>{i.strategy_id} {i.strategy_name}</b>
              {i.engine_selected && <span className="badge ok">Wybrany przez bota</span>}
              <span className={i.direction === "BUY" ? "pos" : "neg"}>{i.direction}</span>
              <span>{i.symbol} · {i.timeframe} · {i.status === "ACTIVE" ? STAGE_PL[i.stage] ?? i.stage : "zakończony"}</span>
              <small>{SCEN_PL[i.scenario_status] ?? i.scenario_status} · aktualizacja {fmtTime(i.updated_at, true)}{i.terminal_reason_pl ? ` · ${i.terminal_reason_pl}` : ""}</small>
            </a>
          </li>))}
        {!items.length && <li className="muted">Brak scenariuszy dla tych filtrów – strategie nie wykryły struktury.</li>}
      </ul>
    </section>
  );
}

/** The ONLY place on this page that changes what the engine analyses (an explicit bot setting, not navigation). */
function EngineChoice({ list }: { list: any }) {
  const { s } = useStore();
  const view = s.prefs?.setup_view ?? list?.setup_view ?? { mode: "AUTO", strategy_id: null };
  const [sid, setSid] = useState<string>(view.strategy_id ?? "S01");
  const [msg, setMsg] = useState<string | null>(null);
  const set = (v: any) => apiSend("POST", "/api/v1/prefs/setup-view", v).then(() => setMsg("Zapisano – dotyczy kolejnych cykli silnika.")).catch((e) => setMsg(String(e.message || e)));
  return (
    <div className="engine-choice" data-testid="engine-choice">
      <p className="small">Obecnie: <b>{view.mode === "SELECTED" ? `tylko strategia ${view.strategy_id}` : "AUTO – silnik wybiera spośród wszystkich strategii"}</b>.
        Zapisane dla rachunku {s.prefs?.account_key ?? "—"}. To ustawienie działania bota; przeglądanie setupów go nie zmienia.</p>
      <div className="row">
        <button className={cls("btn", view.mode !== "SELECTED" && "on")} data-testid="engine-auto" onClick={() => set({ mode: "AUTO" })}>AUTO</button>
        <select value={sid} onChange={(e) => setSid(e.target.value)} aria-label="Strategia dla silnika">
          {(list?.strategies ?? []).map((x: any) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} {x.name}</option>)}</select>
        <button className={cls("btn ghost", view.mode === "SELECTED" && "on")} data-testid="engine-selected" onClick={() => set({ mode: "SELECTED", strategy_id: sid })}>Analizuj tylko tę strategię</button>
      </div>
      <p className="small muted">Wybór nie wymusza sygnału ani zlecenia – obowiązują wszystkie filtry ryzyka i jakości danych.</p>
      {msg && <p className="small">{msg}</p>}
    </div>
  );
}

function ConditionList({ rows, groups }: { rows: any[]; groups: Record<string, string> }) {
  const [flt, setFlt] = usePersisted<Filter>("warunki.ckfilter", "all", (x) => ["all", "missing", "nodata"].includes(x));
  const vis = rows.filter((r) => flt === "all" || (flt === "missing" ? ["MISSING", "PENDING"].includes(r.state) : r.state === "NO_DATA"));
  const byGroup = Object.keys(groups).map(Number).sort((a, b) => a - b).map((g) => ({ g, rows: vis.filter((r) => r.group === g) })).filter((x) => x.rows.length);
  return (
    <section className="card cond-list" data-testid="condition-list">
      <div className="card-head"><h2>Pełna checklista</h2>
        <div className="tabs small" role="group" aria-label="Filtr warunków">
          {([["all", "Wszystkie"], ["missing", "Niespełnione"], ["nodata", "Brak danych"]] as [Filter, string][]).map(([k, l]) =>
            <button key={k} className={cls(flt === k && "on")} aria-pressed={flt === k} data-filter={k} onClick={() => setFlt(k)}>{l}</button>)}
        </div></div>
      {byGroup.map(({ g, rows: rs }) => {
        const allMet = rs.every((r) => r.state === "MET" || r.state === "NA");
        return (
          <details key={g} className={cls("cond-group", allMet && "all-met")} open={!allMet || flt !== "all"} data-group={g}>
            <summary><b>{g}. {groups[g]}</b> <span className="muted small">{rs.filter((r) => r.state === "MET").length}/{rs.filter((r) => r.required).length} wymaganych spełnionych</span></summary>
            <ul>{rs.map((r, i) => (
              <li key={i} className={cls("cond", "cs-" + r.state)} data-state={r.state}>
                <span className="cond-st"><i aria-hidden="true">{ST_ICON[r.state as St] ?? "?"}</i>{ST_PL[r.state as St] ?? r.state}{!r.required && r.state !== "NA" ? " (opcjonalne)" : ""}</span>
                <span className="cond-name"><b>{r.name}</b>{r.reason && <small>{r.reason}</small>}</span>
                <span className="cond-req"><label>Wymaganie</label>{r.threshold ?? "—"}</span>
                <span className="cond-val"><label>Odczyt</label>{r.value ?? "—"}</span>
                <span className="cond-meta">{r.tf ?? "—"} · {r.at ? fmtTime(r.at, true) : "—"}</span>
              </li>))}</ul>
          </details>);
      })}
      {!byGroup.length && <p className="muted">Brak warunków dla tego filtra.</p>}
    </section>
  );
}

function Details({ d, digits }: { d: any; digits: number }) {
  const px = (v: any) => (v == null ? "—" : fmtNum(v, digits));
  const sm = d.summary || {};
  const z = d.sizing || {};
  const lv = d.leverage || {};
  const cur = z.currency ?? "";
  const L = d.levels || {};
  const show = (price: number | null | undefined, label: string) => price == null ? null : (
    <a className="btn tiny ghost" data-testid="show-on-chart" href={href("wykresy", { params: { tf: d.timeframe, price, label, setup: d.setup_id, sid: d.strategy_id } })}>Pokaż na wykresie</a>);
  const ended = d.scenario_status === "UNIEWAZNIONY";
  return (
    <>
      <section className={cls("card setup-summary", ended && "ended")} data-testid="setup-summary" data-setup={d.setup_id}>
        <div className="card-head">
          <h2>{d.strategy_id} {d.strategy_name}</h2>
          <span className={cls("badge", d.direction === "BUY" ? "ok" : "bad")} title={d.direction_note}>{d.direction} – kierunek scenariusza</span>
          <span className="badge">{d.symbol} · {d.timeframe}</span>
          {d.engine_selected && <span className="badge ok">Wybrany przez bota</span>}
        </div>
        {ended && <p className="warn" data-testid="setup-ended">Scenariusz zakończony: {d.terminal_reason ?? "—"}. <a href={href("warunki", { setupId: "bot" })}>Wróć do aktywnych scenariuszy</a></p>}
        <div className="sum-grid">
          <div><label>Etap</label><b>{STAGE_PL[d.stage] ?? d.stage} · {d.scenario_status_pl}</b></div>
          <div className="big"><label>Postęp checklisty</label><b data-testid="req-count">Spełniono {sm.required_met ?? 0} z {sm.required_total ?? 0} warunków wymaganych</b>
            <small>{sm.meaning}</small></div>
          <div><label>Najważniejszy brak / blokada</label><b>{sm.first_blocker ? `${sm.first_blocker.name}` : "brak"}</b><small>{sm.first_blocker?.reason ?? ""}</small></div>
          <div><label>Następne wymagane potwierdzenie</label><b>{sm.next_confirmation ? sm.next_confirmation.name : "—"}</b><small>{sm.next_confirmation?.threshold ?? ""}</small></div>
          <div><label>Unieważnienie</label><b>{L.invalidation_rule ?? "—"}</b></div>
          <div><label>Możliwość wejścia</label><b className={d.entry?.status === "DOSTĘPNE" ? "pos" : "neg"} data-testid="sd-entry">{d.entry?.status}</b>
            <small>{(d.entry?.reasons || []).slice(0, 3).join("; ")}</small></div>
        </div>
        <p className="small muted">{d.context?.rationale} Spełnienie struktury nie oznacza zgody bramek ryzyka, danych i wykonania.</p>
      </section>

      <div className="two-cards">
        <section className="card trig-card" data-testid="trigger-card">
          <h3>Trigger i unieważnienie</h3>
          <dl>
            <dt>Wymagane zamknięcie</dt><dd>świeca {d.timeframe} (zamknięta)</dd>
            <dt>Warunek potwierdzenia</dt><dd>{L.trigger ?? "—"}</dd>
            <dt>Poziom aktywacji</dt><dd>{px(L.trigger_level)} {show(L.trigger_level, "trigger")}</dd>
            <dt>Strefa wejścia</dt><dd>{L.entry_zone ? `${px(L.entry_zone[0])} – ${px(L.entry_zone[1])}` : "—"}</dd>
            <dt>Ważny do</dt><dd>{L.expires_at ? fmtTime(L.expires_at, true) : "—"}</dd>
            <dt>Unieważnienie</dt><dd>{L.invalidation_level != null ? <>{px(L.invalidation_level)} – {L.invalidation_rule} {show(L.invalidation_level, "unieważnienie")}</> : "brak poziomu w planie"}; także wygaśnięcie i utrata danych</dd>
          </dl>
        </section>
        <section className="card plan-card" data-testid="plan-card">
          <h3>Plan wejścia <small className="muted">(wartości planowane; wykonanie – panel Pozycje)</small></h3>
          <dl>
            <dt>Planowane wejście</dt><dd>{px(L.planned_entry)} <small>{L.entry_basis === "LIVE_QUOTE" ? "bieżąca cena" : L.entry_basis ? "hipotetycznie – poziom wyzwalacza" : ""}</small></dd>
            <dt>SL</dt><dd>{px(L.stop_loss)} {show(L.stop_loss, "SL")}</dd>
            <dt>TP</dt><dd>{(L.targets || []).length ? (L.targets as number[]).map((t, i) => <span key={i}>TP{i + 1} {px(t)} </span>) : "—"}</dd>
            <dt>RR brutto / netto</dt><dd>{d.rr?.gross != null ? fmtNum(d.rr.gross, 2) : "—"} / {d.rr?.net != null ? fmtNum(d.rr.net, 2) : "—"} <small>{d.rr?.note}</small></dd>
            <dt>Wolumen</dt><dd data-testid="sd-lots">{z.lots ? `${z.lots} lot (ogranicza: ${BIND_PL[z.binding_constraint] ?? z.binding_constraint ?? "—"})` : (z.reasons_pl || []).slice(0, 2).join("; ") || "—"}</dd>
            <dt>Strata przy SL (szac.)</dt><dd>{z.estimated_loss_at_sl != null ? `${fmtNum(z.estimated_loss_at_sl)} ${cur}` : "—"}{z.equity && z.estimated_loss_at_sl != null ? ` (${fmtNum(100 * z.estimated_loss_at_sl / z.equity, 2)}% equity)` : ""}</dd>
            <dt>Wynik przy TP (po kosztach)</dt><dd>{z.estimated_result_at_tp != null ? `${fmtNum(z.estimated_result_at_tp)} ${cur}` : "—"}</dd>
            <dt>Wymagany margin</dt><dd>{z.margin_required != null ? `${fmtNum(z.margin_required)} ${cur}` : "—"}</dd>
            <dt>Dźwignia rachunku / limit bota</dt><dd data-testid="sd-acc-lev">{lv.account_leverage ? `1:${lv.account_leverage}` : "—"} / {lv.user_limit ? `1:${lv.user_limit}` : "AUTO"}</dd>
            <dt>Efektywna ekspozycja</dt><dd>{lv.effective_exposure_position != null ? `${lv.effective_exposure_position}×` : lv.missing_reason ?? "—"}</dd>
          </dl>
        </section>
      </div>
    </>
  );
}

export default function SetupRequirementsPage({ route }: { route: Route }) {
  const { s } = useStore();
  const tick = useTick(5000);
  const [list, setList] = useState<any>(null);
  const [d, setD] = useState<any>(null);
  const [miss, setMiss] = useState<string | null>(null);
  const [last, setLast] = usePersisted<string>("warunki.last", "bot", (x) => typeof x === "string");
  const [autoFull] = useAutoFull();
  const ui = useUi();
  const reqSeq = useRef(0);
  const account = s.account ? `${s.account.server}:${s.account.login}` : "";
  const decisionKey = `${s.decision?.decision_id}:${s.decision?.signal_view?.state}`;
  // no id in the URL -> the last viewed (or "follow the bot"), as a replace (Back does not loop)
  useEffect(() => { if (!route.setupId) navigate("warunki", { setupId: last || "bot", replace: true }); }, [route.setupId, last]);
  const followBot = !route.setupId || route.setupId === "bot";
  useEffect(() => { if (route.setupId) setLast(route.setupId); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [route.setupId]);
  useEffect(() => { apiGet("/api/v1/setups").then(setList).catch(() => undefined); }, [tick, decisionKey, account]);
  const botId: string | null = list?.engine_selected ?? null;
  const viewed = followBot ? botId : route.setupId;
  useEffect(() => {
    const my = ++reqSeq.current;                      // a late answer for a previous setup never overwrites the new view
    if (!viewed) { setD(null); return; }
    apiGet(`/api/v1/setups/${encodeURIComponent(viewed)}/details`)
      .then((r) => { if (my === reqSeq.current) { setD(r); setMiss(null); } })
      .catch(() => { if (my === reqSeq.current) { setD(null); setMiss(viewed); } });
  }, [viewed, tick, decisionKey, account, s.prefs?.settings_version]);
  const dd = d && d.setup_id === viewed ? d : null;
  const digits = s.decision?.signal_view?.digits ?? 2;
  return (
    <div className="setup-page" data-testid="page-warunki">
      <div className="page-head"><h1>Warunki setupu</h1>
        <span className="muted small">{followBot ? "Śledzisz wybór bota" : "Oglądasz wybrany przez Ciebie setup (przypięty) – zmiana wyboru bota go nie zastąpi"}</span></div>
      {!followBot && botId && botId !== route.setupId && (
        <p className="note small" data-testid="bot-other">Bot wybrał teraz inny setup. <a href={href("warunki", { setupId: botId })}>Pokaż wybrany przez bota</a></p>)}
      <div className="setup-layout">
        <div className="setup-side">
          <SetupList list={list} viewed={viewed} followBot={followBot} />
          <Section id="warunki.engine" title="Działanie bota – wybór strategii silnika" testid="sec-engine-choice"><EngineChoice list={list} /></Section>
        </div>
        <div className="setup-main">
          {dd ? (<><Details d={dd} digits={digits} /><ConditionList rows={dd.checklist || []} groups={dd.summary?.groups || {}} /></>) : (
            <section className="card" data-testid="setup-empty">
              <h2>Szczegóły setupu</h2>
              <p className="muted">{miss ? "Ten scenariusz nie istnieje dla bieżącego rachunku (wygasł z historii lub zmieniono rachunek)." : followBot ? "Bot nie wybrał teraz żadnego setupu." : "Ładowanie…"}</p>
              {miss && <a className="btn" href={href("warunki", { setupId: "bot" })}>Wróć do aktywnych scenariuszy</a>}
              {(s.auto?.why_no_setup ?? []).length > 0 && <ul className="small muted">{s.auto.why_no_setup.slice(0, 8).map((w: string) => <li key={w}>{w}</li>)}</ul>}
            </section>)}
          {dd && (
            <Section id="warunki.tf" title="Interwały strategii – zgodność / konflikt">
              <div className="tfo-grid">{(dd.timeframes || []).map((t: any) => (
                <div key={t.tf} className={cls("tfo", t.agreement === "KONFLIKT" && "conflict")}>
                  <b>{t.tf}</b><span className="badge">{t.agreement}</span><small>{t.role}</small>
                  <small>zamkn.: {t.last_closed_utc ? fmtTime(t.last_closed_utc) : "—"}</small>
                  <a className="link small" href={href("wykresy", { params: { tf: t.tf, sid: dd.strategy_id, setup: dd.setup_id } })}>wykres {t.tf}</a>
                </div>))}</div>
            </Section>)}
          {dd && (
            <Section id="warunki.hist" title="Wynik ACTIVE i historia strategii">
              <p className="small"><b>Wynik ACTIVE:</b> {dd.score?.value ?? "—"} – {dd.score?.meaning}</p>
              <p className="small"><b>Historia:</b> {dd.history?.trades ? `${dd.history.trades} transakcji, winrate netto ${dd.history.stats?.win_rate ?? "—"}%, PF ${dd.history.stats?.profit_factor ?? "—"}` : dd.history?.note}</p>
              <p className="small muted">id {dd.setup_id} · powstał {fmtTime(dd.times?.created_at, true)} · aktualizacja {fmtTime(dd.times?.updated_at, true)} · źródło {dd.times?.data_source}</p>
            </Section>)}
          <Section id="warunki.signal" title="Sygnał silnika: plan, AI vs strategia, checklista 12A i kontekst M30/H8" testid="sec-engine-plan"><EnginePlan /></Section>
          <Section id="warunki.ranking" title="Ranking AUTO (scenariusze na żywo)" testid="sec-ranking"><LiveSetupsPanel full={autoFull} /></Section>
          <Section id="warunki.risk" title="Ryzyko – limity" testid="sec-risk"><RiskPanel onSettings={ui.openSettings} /></Section>
          <Section id="warunki.ml" title="Podgląd ML" testid="sec-ml"><MLPanel index={7} /></Section>
        </div>
      </div>
    </div>
  );
}
