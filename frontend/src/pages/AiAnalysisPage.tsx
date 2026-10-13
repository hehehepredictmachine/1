// Page 1 "Analiza AI": what the AI proposes now, why, what it waits for and where it is on the chart (H1 → M30 → M15 →
// M5 → M1). The AI assessment is shown SEPARATELY from the engine's permission to execute. Entering the page or clicking
// a TF never requests a (paid) AI analysis - only the two explicit buttons do.
import { useEffect, useRef, useState } from "react";
import { ACTION_PL, aiState, DIR_PL, STAGE_PL, STATE_PL, type AiRecord } from "../ai";
import { apiGet, apiSend } from "../api";
import { NewsPanel } from "../components/BottomPanels";
import ChartPanel, { type AiLevels } from "../components/ChartPanel";
import ChartToolbar, { useChartOpts } from "../components/ChartToolbar";
import SignalTop, { blockPl } from "../components/SignalTop";
import { href, usePersisted } from "../router";
import { ROLE_PL, useTimeframes } from "./BotChartsPage";
import { useStore } from "../store";
import Section from "../components/Section";
import { cls, fmtNum, fmtTime } from "../util";

const AI_TFS = ["H1", "M30", "M15", "M5", "M1"] as const;
const ENGINE_PL: Record<string, string> = { BUY: "KUPNO dozwolone", SELL: "SPRZEDAŻ dozwolona", OCZEKIWANIE: "oczekiwanie – brak zgody na wejście",
  BRAK_SYGNALU: "brak zakwalifikowanego setupu", BLOKADA: "wejście ZABLOKOWANE", NIEAKTUALNY: "sygnał nieaktualny", BRAK_DANYCH: "brak danych" };

function useNow(ms = 1000) {
  const [t, setT] = useState(Date.now());
  useEffect(() => { const h = setInterval(() => setT(Date.now()), ms); return () => clearInterval(h); }, [ms]);
  return t;
}
const ago = (iso: string | undefined | null, now: number) => {
  if (!iso) return "—";
  const s = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  return s < 60 ? `${s} s temu` : s < 3600 ? `${Math.floor(s / 60)} min temu` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min temu`;
};

/** "Analizuj teraz" / "Zapytaj AI" through the existing endpoints; one request at a time (no duplicate sends). */
function useAgentActions() {
  const { s } = useStore();
  const [pending, setPending] = useState<null | "analyze" | "ask">(null);
  const [msg, setMsg] = useState<string | null>(null);
  const runAtSend = useRef<string | null>(null);
  useEffect(() => {                                    // a new run result ends the waiting state
    if (pending && s.agent_last_any?.run_id && s.agent_last_any.run_id !== runAtSend.current) { setPending(null); setMsg(null); }
  }, [s.agent_last_any?.run_id, pending]);
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => { setPending(null); setMsg("Brak wyniku po 3 min – sprawdź status agenta (Logi)."); }, 180000);
    return () => clearTimeout(t);
  }, [pending]);
  const send = async (kind: "analyze" | "ask", body?: any) => {
    if (pending) return false;
    setPending(kind);
    setMsg(null);
    runAtSend.current = s.agent_last_any?.run_id ?? null;
    try {
      const r = await apiSend("POST", kind === "ask" ? "/api/v1/agent/ask" : "/api/v1/agent/analyze", body);
      if (!r.queued) { setPending(null); setMsg("Agent niedostępny – " + (s.agent?.detail || s.agent?.state || "brak klucza lub budżetu")); return false; }
      setMsg(kind === "ask" ? "Pytanie w kolejce – odpowiedź pojawi się w karcie." : "Analiza w kolejce.");
      return true;
    } catch (e: any) {
      setPending(null);
      setMsg(String(e?.message || e));
      return false;
    }
  };
  const busy = !!pending || s.agent?.state === "RUNNING";
  return { pending, busy, msg, analyze: () => send("analyze"), ask: (q: string) => send("ask", { question: q }) };
}

function Levels({ rec, dig }: { rec: AiRecord; dig: number }) {
  const n = (x: number | null | undefined) => (x == null ? "—" : fmtNum(x, dig));
  return (
    <div className="ai-levels">
      <div><label>Strefa wejścia (AI)</label><b>{rec.entry_zone ? `${n(rec.entry_zone.low)} – ${n(rec.entry_zone.high)}` : "brak"}</b></div>
      <div><label>Unieważnienie (AI)</label><b>{rec.invalidation_level == null ? "brak" : n(rec.invalidation_level)}</b></div>
      <div><label>Cele (AI)</label><b>{rec.proposed_targets.length ? rec.proposed_targets.map(n).join(" / ") : "brak"}</b></div>
    </div>
  );
}

export function AiSignalCard({ onAsk }: { onAsk: ReturnType<typeof useAgentActions> }) {
  const { s } = useStore();
  const now = useNow();
  const { state, rec, last, lastAny } = aiState(s, now);
  const v = s.decision?.signal_view;
  const dig = v?.digits ?? 2;
  const current = state === "CURRENT";
  const setupId = last?.setup_id ?? rec?.setup_id ?? v?.setup_id ?? null;
  const engineState: string = v?.state ?? "BRAK_DANYCH";
  const disagree = rec && current && ((rec.proposed_action === "BUY" && engineState !== "BUY") || (rec.proposed_action === "SELL" && engineState !== "SELL"));
  const [q, setQ] = useState("");
  return (
    <section className={cls("card ai-card", "ai-" + state.toLowerCase())} data-testid="ai-card" data-ai-state={state}>
      <div className="ai-card-head">
        <h2>Sygnał AI</h2>
        <span className={cls("badge", current ? "ok" : state === "NO_KEY" || state === "NO_ANSWER" ? "muted" : "warn")} data-testid="ai-state">{STATE_PL[state]}</span>
      </div>
      {rec ? (
        <>
          <div className={cls("ai-action", rec.proposed_action.toLowerCase(), !current && "dim")}>
            <span className="ai-action-label" data-testid="ai-action">{ACTION_PL[rec.proposed_action]}</span>
            {!current && <span className="ai-hist">HISTORIA</span>}
          </div>
          <div className="ai-meta">
            <span>Kierunek: <b>{DIR_PL[rec.analysis_direction] ?? rec.analysis_direction}</b></span>
            <span>Etap scenariusza: <b>{STAGE_PL[rec.signal_stage] ?? rec.signal_stage}</b></span>
            <span>Strategia/setup: <b>{rec.strategy_id ?? "nie wskazano"}</b></span>
            <span>Analiza: <b>{fmtTime(rec.as_of_utc ?? last?.finished_at, true)}</b> ({ago(rec.as_of_utc ?? last?.finished_at, now)})</span>
            <span>Ważna do: <b>{rec.expires_at_utc ? fmtTime(rec.expires_at_utc, true) : "—"}</b></span>
          </div>
          <Levels rec={rec} dig={dig} />
          <p className="ai-short" data-testid="ai-short">{rec.explanation_pl ? rec.explanation_pl.split(/(?<=[.!?])\s/)[0] : "AI nie podało uzasadnienia."}</p>
        </>
      ) : (
        <p className="muted ai-empty" data-testid="ai-empty">{state === "NO_KEY" ? "Klucz ANTHROPIC_API_KEY ustawiasz lokalnie (Ustawienia → Agent AI). Sygnały strategii działają bez AI."
          : state === "RUNNING" ? "Agent analizuje bieżący snapshot…" : "Brak udanej odpowiedzi agenta w tej sesji. Użyj „Analizuj teraz”."}</p>
      )}
      {lastAny && lastAny.status !== "OK" && <p className="small warn" data-testid="ai-last-error">Ostatni przebieg ({fmtTime(lastAny.finished_at, true)}): {lastAny.status}{lastAny.error ? ` – ${lastAny.error}` : ""}. Brak nowej decyzji AI (nie zastępujemy jej fikcyjną).</p>}

      <div className={cls("engine-gate", "eg-" + engineState.toLowerCase())} data-testid="engine-gate">
        <label>Pozwolenie silnika (osobno od oceny AI)</label>
        <b>{ENGINE_PL[engineState] ?? engineState}</b>
        {v?.plan_side && <span className="muted"> · plan silnika: {v.plan_side} {v.strategy ?? ""}</span>}
        {(v?.block_reasons || []).length > 0 && <small> – {v.block_reasons.slice(0, 3).map(blockPl).join("; ")}</small>}
        {disagree && <p className="small warn" data-testid="ai-engine-diff">AI proponuje {ACTION_PL[rec!.proposed_action]}, ale silnik nie daje zgody na wejście – propozycja AI nie zmienia zleceń.</p>}
      </div>

      <div className="ai-actions">
        <a className="btn" href={href("warunki", { setupId: setupId || "bot" })} data-testid="ai-setup-link"
          title={setupId ? `Pełna checklista setupu ${setupId}` : "Brak setupu w odpowiedzi – pokaże setup wybrany przez bota"}>Warunki tego setupu</a>
        <button className="btn ghost" onClick={() => onAsk.analyze()} disabled={onAsk.busy} data-testid="ai-analyze"
          title="Płatne zapytanie do Claude dla bieżącego snapshotu">{onAsk.pending === "analyze" ? "Analiza w toku…" : "Analizuj teraz"}</button>
      </div>
      <div className="ai-ask">
        <label htmlFor="ai-q">Zapytaj AI o bieżący snapshot</label>
        <div className="row">
          <input id="ai-q" value={q} maxLength={2000} onChange={(e) => setQ(e.target.value)} placeholder="np. Dlaczego setup nie jest potwierdzony?"
            onKeyDown={(e) => { if (e.key === "Enter" && q.trim().length >= 2 && !onAsk.busy) onAsk.ask(q).then((ok) => ok && setQ("")); }} />
          <button className="btn" disabled={q.trim().length < 2 || onAsk.busy} data-testid="ai-ask" onClick={() => onAsk.ask(q).then((ok) => ok && setQ(""))}>
            {onAsk.pending === "ask" ? "Wysłano…" : "Zapytaj AI"}</button>
        </div>
        {onAsk.msg && <p className="small" data-testid="ai-msg">{onAsk.msg}</p>}
        {rec?.answer_pl && <p className="answer"><b>Odpowiedź{last?.question ? ` na „${last.question}”` : ""}:</b> {rec.answer_pl}</p>}
      </div>
    </section>
  );
}

export function AiExplanation() {
  const { s } = useStore();
  const now = useNow(5000);
  const { state, rec } = aiState(s, now);
  const [open, setOpen] = usePersisted<boolean>("ai.fullText", false, (x) => typeof x === "boolean");
  if (!rec) return null;
  const long = rec.explanation_pl.length > 420;
  const pro = rec.analysis_direction === "LONG" ? rec.scenarios.bullish : rec.analysis_direction === "SHORT" ? rec.scenarios.bearish : rec.scenarios.wait;
  const List = ({ items, empty }: { items: string[]; empty: string }) => (items.length ? <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted small">{empty}</p>);
  return (
    <section className={cls("card ai-expl", state !== "CURRENT" && "hist")} data-testid="ai-explanation">
      <h3>Dokładne wyjaśnienie AI {state !== "CURRENT" && <span className="badge warn">historia</span>}</h3>
      <div className={cls("ai-text", long && !open && "clamped")} data-testid="ai-full-text">{rec.explanation_pl || "—"}</div>
      {long && <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Zwiń opis" : "Pełny opis"}</button>}
      <div className="ai-sections">
        <div><h4>Za scenariuszem</h4><List items={[pro.summary, ...rec.reason_codes.map((c) => `kod: ${c}`)].filter(Boolean)} empty="AI nie podało argumentów." /></div>
        <div><h4>Przeciw i sprzeczności</h4><List items={rec.contradictions} empty="AI nie wskazało sprzeczności." /></div>
        <div><h4>Warunki aktywacji</h4><List items={pro.activation} empty="brak w odpowiedzi" /></div>
        <div><h4>Warunki unieważnienia</h4><List items={pro.invalidation} empty="brak w odpowiedzi" /></div>
      </div>
      <div className="ai-scen">
        {(["bullish", "bearish", "wait"] as const).map((k) => (
          <div key={k} className={cls("scen", "scen-" + k)}>
            <h4>{{ bullish: "Scenariusz wzrostowy", bearish: "Scenariusz spadkowy", wait: "Oczekiwanie" }[k]}</h4>
            <p>{rec.scenarios[k].summary || "—"}</p>
            {rec.scenarios[k].activation.length > 0 && <p className="small"><b>Aktywacja:</b> {rec.scenarios[k].activation.join("; ")}</p>}
            {rec.scenarios[k].invalidation.length > 0 && <p className="small"><b>Unieważnienie:</b> {rec.scenarios[k].invalidation.join("; ")}</p>}
          </div>))}
      </div>
      <div className="ai-sections">
        <div><h4>Brakujące dane</h4><List items={rec.missing_data} empty="AI nie zgłosiło braków." /></div>
        <div><h4>Dowody (odwołania)</h4><List items={rec.evidence_refs.slice(0, 12)} empty="brak odwołań" /></div>
      </div>
      <p className="muted small">decyzja {rec.decision_id ?? "—"} · snapshot {rec.snapshot_id ?? "—"} · setup {rec.setup_id ?? "—"} · model {rec.model_id ?? "—"} · prompt {rec.prompt_version ?? "—"}</p>
    </section>
  );
}

function AgentHistory() {
  const { s } = useStore();
  const [runs, setRuns] = useState<any[]>([]);
  const [mem, setMem] = useState<any[]>([]);
  const st = s.agent || {};
  const load = () => {
    apiGet("/api/v1/agent").then((r) => setRuns(r.runs || [])).catch(() => undefined);
    apiGet("/api/v1/agent/memory").then(setMem).catch(() => undefined);
  };
  useEffect(load, [s.agent_last_any?.run_id]);
  const setMemStatus = async (id: number, status: string) => { await apiSend("POST", `/api/v1/agent/memory/${id}`, { status }); load(); };
  return (
    <div className="agent-hist" data-testid="agent-history">
      <div className="kv">
        <div><label>Stan agenta</label><b>{st.state ?? "?"}</b></div>
        <div><label>Model</label><b>{st.model ?? "nie wybrano"}</b></div>
        <div><label>Klucz</label><b>{st.key_source === "MISSING" ? "brak (ustaw lokalnie)" : `${st.key_source ?? "—"} ${st.key_masked ?? ""}`}</b></div>
        <div><label>Koszt dziś (szac.)</label><b>{fmtNum(st.spent_today_usd_estimate, 3)} / {fmtNum(st.daily_budget_usd)} USD</b></div>
        <div><label>Rola AI</label><b>{st.gate_policy ?? (st.required_for_entry ? "REQUIRED" : "ADVISORY")}</b></div>
      </div>
      <h4>Historia przebiegów</h4>
      <div className="table-wrap"><table className="tbl small">
        <thead><tr><th>Czas</th><th>Wyzwalacz</th><th>Status</th><th>Setup</th><th>ms</th><th>USD≈</th></tr></thead>
        <tbody>{runs.slice(0, 20).map((r) => <tr key={r.run_id}><td>{fmtTime(r.started_at, true)}</td><td>{r.trigger}</td>
          <td>{r.status}{r.error_code ? ` (${r.error_code})` : ""}</td><td className="muted">{r.setup_id ?? "—"}</td><td>{r.latency_ms ?? ""}</td><td>{r.est_cost_usd ? fmtNum(r.est_cost_usd, 4) : ""}</td></tr>)}
          {!runs.length && <tr><td colSpan={6} className="muted">Brak przebiegów.</td></tr>}</tbody>
      </table></div>
      <h4>Propozycje playbooka i wnioski (nie zmieniają strategii LIVE)</h4>
      <ul className="list">
        {mem.slice(0, 20).map((m) => {
          let c: any = {};
          try { c = JSON.parse(m.content_json || "{}"); } catch { /* malformed row */ }
          return (
            <li key={m.id}><span className="tag">{m.kind}</span> {c.title ? <b>{c.title}: </b> : null}{c.text || c.change}
              <span className="tag muted">{m.status}</span>
              {m.kind === "PLAYBOOK_PROPOSAL" && m.status === "PROPOSED" && <>
                <button className="btn tiny" onClick={() => setMemStatus(m.id, "ACCEPTED_FOR_OOS_TEST")}>do testu OOS</button>
                <button className="btn tiny ghost" onClick={() => setMemStatus(m.id, "REJECTED")}>odrzuć</button></>}
            </li>);
        })}
        {!mem.length && <li className="muted">Brak zapisanych wniosków.</li>}
      </ul>
    </div>
  );
}

export default function AiAnalysisPage() {
  const { s } = useStore();
  const now = useNow(5000);
  const actions = useAgentActions();
  const [opts, setOpt] = useChartOpts("ai", { showAiLevels: true });
  const [main, setMain] = usePersisted<string>("ai.main", "M5", (x) => AI_TFS.includes(x));
  const [layout, setLayout] = usePersisted<"main" | "grid">("ai.layout", "main", (x) => x === "main" || x === "grid");
  const [focus, setFocus] = usePersisted<string>("ai.focus", "M5", (x) => AI_TFS.includes(x));
  const [full, setFull] = useState<string | null>(null);
  const { state, rec } = aiState(s, now);
  const { r: tfReg } = useTimeframes();
  const roleOf = (tf: string) => { const x = tfReg?.timeframes.find((t) => t.tf === tf); return x ? ROLE_PL[x.role] ?? x.role : null; };
  const ai: AiLevels = rec && state === "CURRENT" ? { zone: rec.entry_zone ? [rec.entry_zone.low, rec.entry_zone.high] : null, invalidation: rec.invalidation_level,
    targets: rec.proposed_targets } : null;
  // grid areas only move the five charts (stable keys -> no remount, zoom kept); the 6th chart never exists
  const others = AI_TFS.filter((t) => t !== main);
  const area = (tf: string) => (layout === "grid" ? `g${AI_TFS.indexOf(tf as any)}` : tf === main ? "main" : `o${others.indexOf(tf as any)}`);
  return (
    <div className="ai-page" data-testid="page-ai">
      <div className="page-head">
        <h1>Analiza AI</h1>
        <div className="tabs small desk-only" role="group" aria-label="Układ wykresów">
          <button className={cls(layout === "main" && "on")} onClick={() => setLayout("main")} aria-pressed={layout === "main"}>Wykres główny + 4</button>
          <button className={cls(layout === "grid" && "on")} onClick={() => setLayout("grid")} aria-pressed={layout === "grid"} data-testid="ai-grid5">Siatka 5 wykresów</button>
        </div>
        <div className="tabs small mob-only" role="group" aria-label="Skupienie na TF (mały ekran)">
          {AI_TFS.map((t) => <button key={t} className={cls(focus === t && "on")} onClick={() => setFocus(t)}>{t}</button>)}
        </div>
        <ChartToolbar opts={opts} set={setOpt} show={["showAiLevels", "showPatterns", "showStructure", "showZones", "showVol", "showRsi", "showMacd", "syncCrosshair"]} />
      </div>
      <div className={cls("ai-grid", "lay-" + layout)} data-focus={focus}>
        <div className="ai-col" style={{ gridArea: "card" }}>
          <AiSignalCard onAsk={actions} />
          <AiExplanation />
        </div>
        {AI_TFS.map((tf) => (
          <div key={tf} className={cls("ai-slot", focus === tf && "mob-focus")} style={{ gridArea: area(tf) }} data-slot={area(tf)}>
            <ChartPanel tf={tf} index={0} chartId={`ai-${tf}`} opts={opts} variant={layout === "main" && tf === main ? "main" : "normal"}
              isMain={layout === "main" && tf === main} roleText={roleOf(tf)} onMain={layout === "main" ? () => setMain(tf) : undefined} aiLevels={ai}
              fullscreen={full === tf} onFullscreen={() => setFull(full === tf ? null : tf)} />
          </div>
        ))}
      </div>
      <Section id="ai.engine" title="Decyzja silnika: karta wykonania, warunki wejścia i kontekst TF" defaultOpen testid="sec-engine"><SignalTop /></Section>
      <Section id="ai.news" title="News i kalendarz makro" testid="sec-news"><NewsPanel /></Section>
      <Section id="ai.history" title="Agent: historia ocen, koszty i propozycje playbooka" testid="sec-agent-history"><AgentHistory /></Section>
    </div>
  );
}
