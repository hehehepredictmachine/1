// 1.41 panels - every value and every button comes from / goes to the backend (no front-end strategy list, no fake percentages):
//  BasketsPanel          three market profiles, 9 baskets / 90 strategies (/api/v1/baskets*), OTC feed + payoff, declared exposure
//  ResearchModulesPanel  six MQL5-derived modules with separate state axes (/api/v1/research-modules*)
//  TabICLCard            TabICLv2 confidence estimator of Quant (/api/v1/quant/tabicl*)
//  ComponentsCards       Training Center TH_SDFORMERFLOW + ETC_LOG_CHANNEL (/api/v1/trainhub/components*)
import { useEffect, useState } from "react";
import { apiGet, apiSend, apiUpload } from "../api";
import { cls, fmtNum, fmtTime } from "../util";

const TONE: Record<string, string> = { READY: "ok", SIGNAL: "ok", HEDGE_PLAN: "ok", RUNNING: "ok", ACTIVE: "ok", PREDICTION_ACTIVE: "ok", FEATURES_ACTIVE: "ok",
  RAW_SCORE_ACTIVE: "ok", COMPATIBLE: "ok", DONE: "ok", LIVE: "ok", NO_SETUP: "muted", NO_EXPOSURE: "muted", NO_HEDGE: "muted", NOT_SELECTED: "muted",
  DISABLED: "muted", STOPPED: "muted", NOT_REQUIRED: "muted", NOT_APPLICABLE: "muted", WARMUP: "warn", WAITING_FOR_DATA: "warn", WAITING_FOR_OTC_FEED: "warn",
  WAITING_FOR_LABELS: "warn", COLD_START: "warn", MISSING: "warn", TRAINING: "warn", DEGRADED: "warn", CONFLICT: "warn", DUPLICATE_EVENT: "muted",
  COOLDOWN: "muted", LIMIT: "warn", ERROR: "bad", FAILED: "bad", INCOMPATIBLE: "bad", NOT_INSTALLED: "warn" };
const Badge = ({ s }: { s?: string | null }) => <span className={cls("badge", TONE[s || ""] || "muted")}>{s || "—"}</span>;
const errText = (e: any) => String(e?.message || e).slice(0, 300);

function useLoad<T = any>(path: string, every = 10000): [T | null, string | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => apiGet<T>(path).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(errText(e)));
  useEffect(() => { load(); const t = setInterval(load, every); return () => clearInterval(t); }, [path]);  // eslint-disable-line react-hooks/exhaustive-deps
  return [d, err, load];
}

// ============================================================================ baskets
const PROFILE_PL: Record<string, string> = { FOREX_MT5: "FOREX / MT5", CRYPTO_FOMO_PERPS: "CRYPTO PERPS / FOMO", OTC_GOLD_POCKETOPTION: "OTC GOLD / Pocket Option" };

export function BasketsPanel() {
  const [d, err, load] = useLoad<any>("/api/v1/baskets", 8000);
  const [sig, , loadSig] = useLoad<any>("/api/v1/baskets/signals?limit=30", 8000);
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const st = d?.status;
  const active = st?.active_profile || "FOREX_MT5";
  const put = (body: any, ok: string) => apiSend("PUT", "/api/v1/baskets/settings", body).then(() => { setMsg(ok); load(); loadSig(); }).catch((e) => setMsg(errText(e)));
  const baskets = (d?.baskets || []).filter((b: any) => all || b.profile_id === active);
  return (
    <div className="pmw141 baskets" data-testid="baskets-panel">
      {err && <p className="err">{err}</p>}
      <div className="row wrap" style={{ gap: 6 }}>
        {Object.keys(PROFILE_PL).map((p) => (
          <button key={p} className={cls("btn", p === active ? "" : "ghost")} data-testid={`profile-${p}`} onClick={() => put({ active_profile: p }, `aktywny profil: ${PROFILE_PL[p]}`)}>
            {PROFILE_PL[p]} <Badge s={(st?.profiles?.[p]?.contexts || [])[0]?.data_state || (p === "OTC_GOLD_POCKETOPTION" ? st?.otc_feed?.state : null)} /></button>))}
        <label className="small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> wszystkie 9 koszyków</label>
        {st && <span className="small muted" data-testid="baskets-counts">zaimplementowane: <b>{st.counts.implemented}</b> · stany wykonalne teraz (per instrument): <b>{st.counts.executable_now}</b> ·
          katalog {st.version} {st.catalog.ok ? "OK" : "BŁĄD"}</span>}
      </div>
      {st && <div className="row wrap small" style={{ gap: 10 }}>
        <span>Wybór strategii ({PROFILE_PL[active]}):</span>
        {["OFF", "AUTO", "MANUAL_SELECT"].map((m) => (
          <label key={m}><input type="radio" name="sel" checked={st.profiles[active]?.selection === m} onChange={() => put({ profiles: { [active]: { selection: m } } }, `wybór: ${m}`)} /> {m}</label>))}
        <span className="muted">(osobno od trybu zleceń SIGNALS/PAPER/AUTO – koszyki publikują sygnały, plany i tickety, bez zleceń)</span>
      </div>}
      {msg && <p className="small muted">{msg}</p>}
      <div className="basket-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 8 }}>
        {baskets.map((b: any) => (
          <div key={b.basket_id} className="panel" data-testid={`basket-${b.basket_id}`}>
            <div className="panel-head"><b>{b.basket_id}</b> <span className="muted small">{PROFILE_PL[b.profile_id]} · {b.family}</span>
              <label className="small" style={{ marginLeft: "auto" }}><input type="checkbox" checked={!!b.enabled} data-testid={`basket-toggle-${b.basket_id}`}
                onChange={(e) => put({ baskets: { [b.basket_id]: { enabled: e.target.checked } } }, `${b.basket_id}: ${e.target.checked ? "włączony" : "wyłączony"}`)} /> włączony</label></div>
            <div className="small">{Object.entries(b.data_status || {}).map(([k, v]: any) => <div key={k}>{k}: <Badge s={v.state} /> {v.regime ? `reżim ${v.regime.regime}` : ""} <span className="muted">{v.reason || ""}</span></div>)}</div>
            <div className="small muted">{Object.entries(b.status_counts || {}).map(([k, n]) => `${k}: ${n}`).join(" · ") || "brak ocen"}</div>
            <div className="small muted">ledger: {Object.entries(b.ledger || {}).map(([k, n]) => `${k}: ${n}`).join(" · ") || "—"} · wykonanie: {b.execution_capability}</div>
            <button className="btn tiny ghost" onClick={() => setOpen(open === b.basket_id ? null : b.basket_id)}>{open === b.basket_id ? "ukryj" : "10 strategii"}</button>
            {open === b.basket_id && <div className="table-wrap"><table className="tbl small"><thead><tr><th>ID</th><th>Strategia</th><th>TF</th><th>Stan</th><th>Wł.</th></tr></thead>
              <tbody>{b.strategies.map((s: any) => { const v: any = Object.values(s.states || {})[0] || s.hedge || {}; return (
                <tr key={s.strategy_id}><td>{s.strategy_id}</td><td>{s.name}</td><td>{s.tf}{s.context?.length ? ` / ${s.context.join(",")}` : ""}</td>
                  <td><Badge s={v.state} /> <span className="muted">{v.reason || v.primary || ""}</span></td>
                  <td><input type="checkbox" checked={!!s.enabled} onChange={(e) => put({ strategies: { [s.strategy_id]: { enabled: e.target.checked } } }, `${s.strategy_id}: ${e.target.checked ? "wł." : "wył."}`)} /></td></tr>); })}</tbody></table></div>}
            <p className="small muted">{b.execution_note}</p>
          </div>))}
      </div>
      <h4>Ostatnie sygnały koszyków</h4>
      <div className="table-wrap"><table className="tbl small" data-testid="basket-signals"><thead><tr><th>Czas</th><th>Strategia</th><th>Instrument</th><th>Kier.</th><th>Plan</th><th>Setup score</th><th>p_event_raw</th><th>Stan / wynik</th></tr></thead>
        <tbody>{(sig?.signals || []).map((x: any) => (
          <tr key={x.signal_id}><td>{fmtTime(new Date(x.created_at * 1000).toISOString())}</td><td>{x.strategy_id}{x.setup?.justifications?.length ? <div className="muted">+ {x.setup.justifications.join(", ")}</div> : null}</td>
            <td>{x.instrument} {x.tf}</td><td>{x.side}</td>
            <td>{x.plan?.plan_type === "FixedExpiryPlan" ? `${x.plan.direction} · D ${x.plan.requested_duration_s}s → ${x.plan.selected_duration_s ?? "brak terminu"} · payout ${x.plan.payout_profit_ratio ?? "?"}`
              : `E ${fmtNum(x.plan?.entry_ref, 2)} · SL ${fmtNum(x.plan?.sl, 2)} · TP ${(x.plan?.targets || []).map((t: any) => fmtNum(t.price, 2)).join(" / ")} · ilość ${x.plan?.quantity ?? "—"}`}</td>
            <td>{x.scores?.setup_score ?? "—"}</td><td>{x.scores?.p_event_raw != null ? fmtNum(x.scores.p_event_raw, 3) : "null"}</td>
            <td><Badge s={x.status} /> {x.outcome_kind || ""}</td></tr>))}</tbody></table></div>
      <p className="small muted">Wyniki koszyków to SIGNAL_SIMULATION (przebieg sygnału na zamkniętych świecach), nie PnL konta. Ticket manualny to nie fill. setup_score to jawna skala warunków, nie prawdopodobieństwo.</p>
      <OtcBox otc={st?.otc_feed} reload={load} />
      <DeclaredBox />
    </div>);
}

function OtcBox({ otc, reload }: { otc: any; reload: () => void }) {
  const [call, setCall] = useState("");
  const [putp, setPutp] = useState("");
  const [exp, setExp] = useState("30,60,120,180,300");
  const [msg, setMsg] = useState<string | null>(null);
  const [pay, setPay] = useState<any>(null);
  const save = () => apiSend("PUT", "/api/v1/baskets/otc/meta", { payout: { CALL: call ? Number(call) / 100 : null, PUT: putp ? Number(putp) / 100 : null },
    expiries_s: exp.split(",").map((x) => Number(x.trim())).filter((x) => x > 0) }).then(() => { setMsg("zapisano (payout z bieżącego ekranu platformy, ze znacznikiem czasu)"); reload(); }).catch((e) => setMsg(errText(e)));
  const demo = () => apiSend("POST", "/api/v1/baskets/otc/payoff", { legs: [{ dir: "CALL", stake: 100, r: 0.8, strike: 1, expiry: 1 }, { dir: "PUT", stake: 100, r: 0.8, strike: 1, expiry: 1 }] }).then(setPay);
  return (
    <div className="panel" data-testid="otc-box">
      <div className="panel-head"><b>Gold OTC – feed i OTC_PAYOFF_GATE</b> <Badge s={otc?.state} /></div>
      <p className="small muted">{otc?.reason || `źródło: ${otc?.source}`} {otc?.note}</p>
      <div className="row wrap small" style={{ gap: 6 }}>
        <label>payout CALL % <input size={4} value={call} onChange={(e) => setCall(e.target.value)} /></label>
        <label>payout PUT % <input size={4} value={putp} onChange={(e) => setPutp(e.target.value)} /></label>
        <label>dozwolone expiry [s] <input size={18} value={exp} onChange={(e) => setExp(e.target.value)} /></label>
        <button className="btn tiny" onClick={save}>Zapisz</button>
        <button className="btn tiny ghost" onClick={demo}>Przykład: CALL 100 + PUT 100 @ 80%</button>
      </div>
      {pay?.rows && <p className="small" data-testid="otc-payoff">{pay.rows.map((r: any) => `${r.kind}: ${r.pnl}`).join(" · ")} → najgorszy wynik {pay.worst} (dwie przeciwne nogi nie dają zysku)</p>}
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

function DeclaredBox() {
  const [prof, setProf] = useState("CRYPTO_FOMO_PERPS");
  const [d, , load] = useLoad<any>(`/api/v1/baskets/declared/${prof}`, 15000);
  const [f, setF] = useState<any>({ instrument: "SOL", side: "LONG", size: "", tags: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const add = () => {
    const body = prof === "CRYPTO_FOMO_PERPS" ? { instrument: f.instrument, side: f.side, size: Number(f.size), tags: String(f.tags || "").split(",").filter(Boolean) }
      : { dir: f.dir || "CALL", stake: Number(f.stake), r: Number(f.r) / 100, strike: Number(f.strike), expiry: Date.parse(f.expiry) / 1000, opened_at: Date.now() / 1000 - 1 };
    apiSend("POST", `/api/v1/baskets/declared/${prof}`, body).then(() => { setMsg("zapisano (MANUAL_DECLARED)"); load(); }).catch((e) => setMsg(errText(e)));
  };
  return (
    <div className="panel" data-testid="declared-box">
      <div className="panel-head"><b>Ekspozycja do ochrony (FOMO / OTC – deklaracja ręczna)</b>
        <select value={prof} onChange={(e) => setProf(e.target.value)}><option value="CRYPTO_FOMO_PERPS">FOMO perps</option><option value="OTC_GOLD_POCKETOPTION">Gold OTC</option></select></div>
      <p className="small muted">Brak API rachunków FOMO / Pocket Option: planery HEDGING widzą tylko pozycje / kontrakty wpisane tutaj (oznaczone MANUAL_DECLARED). FOREX czyta pozycje bota z terminala.</p>
      <div className="row wrap small" style={{ gap: 6 }}>
        {prof === "CRYPTO_FOMO_PERPS" ? <>
          <input size={6} placeholder="SOL" value={f.instrument} onChange={(e) => setF({ ...f, instrument: e.target.value })} />
          <select value={f.side} onChange={(e) => setF({ ...f, side: e.target.value })}><option>LONG</option><option>SHORT</option></select>
          <input size={8} placeholder="ilość (jedn. bazowe)" value={f.size} onChange={(e) => setF({ ...f, size: e.target.value })} />
          <input size={8} placeholder="tagi np. ETH" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} /></> : <>
          <select value={f.dir || "CALL"} onChange={(e) => setF({ ...f, dir: e.target.value })}><option>CALL</option><option>PUT</option></select>
          <input size={6} placeholder="stawka" onChange={(e) => setF({ ...f, stake: e.target.value })} />
          <input size={4} placeholder="payout %" onChange={(e) => setF({ ...f, r: e.target.value })} />
          <input size={8} placeholder="strike" onChange={(e) => setF({ ...f, strike: e.target.value })} />
          <input size={18} placeholder="expiry 2026-11-16T20:05:00Z" onChange={(e) => setF({ ...f, expiry: e.target.value })} /></>}
        <button className="btn tiny" onClick={add}>Dodaj</button>
      </div>
      <ul className="small">{(d?.items || []).map((x: any) => <li key={x.id}>{JSON.stringify({ ...x, id: undefined })}
        <button className="btn tiny ghost" onClick={() => apiSend("DELETE", `/api/v1/baskets/declared/${x.id}`).then(load)}>zamknij</button></li>)}</ul>
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

// ============================================================================ research modules
const MOD_PL: Record<string, string> = { sdformerflow: "SDformerFlow", cellular_feature_graph: "Graf cech (Cellular 10K)", coa_coyote: "COA (Coyote)",
  bchimp: "BChimp", g7_smc_radar: "G7 SMC Radar", exponential_trend_channel: "Exponential Trend Channel" };

export function ResearchModulesPanel() {
  const [d, err, load] = useLoad<any>("/api/v1/research-modules", 8000);
  const [msg, setMsg] = useState<string | null>(null);
  const act = (p: Promise<any>, ok: string) => p.then(() => { setMsg(ok); load(); }).catch((e) => setMsg(errText(e)));
  return (
    <div className="pmw141" data-testid="research-panel">
      {err && <p className="err">{err}</p>}
      <p className="small muted">{d?.semantics} · polityka {d?.activation_policy} · pętla: {d?.loop?.cycles ?? 0} cykli, błędy {d?.loop?.errors ?? 0}</p>
      <div className="table-wrap"><table className="tbl small"><thead><tr><th>Moduł</th><th>Wł.</th><th>Runtime</th><th>Artefakt</th><th>Udział</th><th>Ostatnio</th><th>Szczegóły</th></tr></thead>
        <tbody>{Object.values(d?.modules || {}).map((m: any) => (
          <tr key={m.module_id} data-testid={`rm-${m.module_id}`}><td><b>{MOD_PL[m.module_id] || m.module_id}</b><div className="muted">{m.implementation_id} · {m.author}</div></td>
            <td><input type="checkbox" checked={!!m.enabled} onChange={(e) => act(apiSend("PUT", "/api/v1/research-modules/settings", { modules: { [m.module_id]: { enabled: e.target.checked } } }), `${m.module_id}: ${e.target.checked ? "wł." : "wył."}`)} /></td>
            <td><Badge s={m.runtime_state} /></td><td><Badge s={m.artifact_state} /></td><td><Badge s={m.contribution_state} /></td><td>{m.last_update || "—"}</td>
            <td className="muted" style={{ maxWidth: 420, whiteSpace: "normal" }}>{detail(m)}</td></tr>))}</tbody></table></div>
      {d?.composite && <p className="small">Kompozyt badawczy: wersja <b>{d.composite.version}</b> ({d.composite.status}) wagi [{(d.composite.weights || []).map((w: number) => fmtNum(w, 2)).join(", ")}] dla {(d.composite.names || []).join(", ")}</p>}
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn tiny" onClick={() => act(apiSend("POST", "/api/v1/research-modules/optimizer/run"), "optymalizacja COA → BChimp wykonana")}>Optymalizuj teraz (COA → BChimp)</button>
        <button className="btn tiny ghost" onClick={() => act(apiSend("POST", "/api/v1/research-modules/parameters/rollback"), "przywrócono poprzednie parametry")}>Cofnij parametry</button>
        <button className="btn tiny" onClick={() => act(apiSend("POST", "/api/v1/research-modules/sdformerflow/train", { op: "from_scratch" }), "trening SDformerFlow uruchomiony")}>Trenuj SDformerFlow</button>
        <button className="btn tiny ghost" onClick={() => act(apiSend("POST", "/api/v1/research-modules/sdformerflow/cancel"), "anulowanie zgłoszone")}>Anuluj trening</button>
      </div>
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

function detail(m: any): string {
  const d = m.detail || {};
  if (m.module_id === "exponential_trend_channel" && d.channel) return `okno ${d.channel.bars} · fit ${fmtNum(d.channel.fit, 3)} · kanał ${fmtNum(d.channel.lower, 2)}–${fmtNum(d.channel.upper, 2)} · ${d.parameter_version}`;
  if (m.module_id === "g7_smc_radar" && d.rule_confluence_score != null) return `confluence ${d.rule_confluence_score}/100 (reguła, nie prawdopodob.) · pokrycie ${fmtNum(d.coverage, 2)} · ${d.reason || ""}`;
  if (m.module_id === "cellular_feature_graph" && d.targets) return Object.entries(d.targets).map(([k, v]: any) => `${k}: ${fmtNum(v.raw_score, 3)} (v${v.model_update_version}, oczek. ${v.pending})`).join(" · ");
  if (m.module_id === "sdformerflow") return d.result ? `run ${d.active_run} · DIRECTION_SCORE_RAW ${fmtNum(d.result.direction_score_raw, 3)} · ${fmtNum(d.result.ms, 0)} ms` : (d.reason || d.state || "");
  return "";
}

// ============================================================================ TabICLv2
export function TabICLCard() {
  const [d, err, load] = useLoad<any>("/api/v1/quant/tabicl", 10000);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="panel" data-testid="tabicl-card">
      <div className="panel-head"><b>TabICLv2 – estymator confidence Quant</b> <Badge s={d?.state} /></div>
      {err && <p className="err">{err}</p>}
      <p className="small muted">confidence_score = 100 × p_event_raw (UNCALIBRATED) zdarzenia z EventSpec; kontekst z ledgera lub przyczynowej rekonstrukcji. Brak kontekstu = brak wartości (nie 50%).</p>
      <pre className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto" }}>{d ? JSON.stringify({ state: d.state, reason: d.reason, contexts: d.contexts, reconstruction: d.reconstruction, worker: d.worker }, null, 1) : "…"}</pre>
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn tiny" onClick={() => apiSend("POST", "/api/v1/quant/tabicl/install").then(() => { setMsg("instalacja uruchomiona"); load(); }).catch((e) => setMsg(errText(e)))}>Zainstaluj / napraw</button>
        <button className="btn tiny ghost" onClick={() => apiSend("POST", "/api/v1/quant/tabicl/reconstruct").then(() => { setMsg("rekonstrukcja kontekstu uruchomiona"); load(); }).catch((e) => setMsg(errText(e)))}>Odbuduj kontekst</button>
      </div>
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

// ============================================================================ Training Center components
export function ComponentsCards() {
  const [d, err, load] = useLoad<any>("/api/v1/trainhub/components", 5000);
  const [msg, setMsg] = useState<string | null>(null);
  const call = (p: Promise<any>, ok: string) => p.then((r) => { setMsg(`${ok}${r?.reason ? ` – ${r.reason}` : ""}`); load(); }).catch((e) => setMsg(errText(e)));
  const job = (cid: string, body: any, ok: string) => call(apiSend("POST", `/api/v1/trainhub/components/${cid}/jobs`, body), ok);
  const imp = (cid: string) => { const i = document.createElement("input"); i.type = "file"; i.accept = ".zip";
    i.onchange = () => { const f = i.files?.[0]; if (f) call(apiUpload(`/api/v1/trainhub/components/${cid}/import`, f), "zaimportowano"); }; i.click(); };
  return (
    <section className="tc-panel" data-testid="tc-components">
      <div className="panel-head"><b>Komponenty 1.41: SDformerFlow (wagi) i Exponential Trend Channel (transformacja cech)</b>
        <span className="muted small">polityka {d?.activation_policy} · profil {d?.profile} · jedno ciężkie zadanie naraz</span></div>
      {err && <p className="err">{err}</p>}
      {(d?.components || []).map((c: any) => (
        <div key={c.component_id} className="panel" data-testid={`tc-comp-${c.component_id}`}>
          <div className="panel-head"><b>{c.component_id}</b> <span className="muted small">{c.kind} · {c.implementation_id} · {c.runtime_backend}</span>
            {c.runtime_state && <Badge s={c.runtime_state} />}</div>
          <p className="small">Aktywna wersja: <b>{c.active_version || "brak"}</b> {c.previous_version ? `(poprzednia ${c.previous_version})` : ""} · cel {c.target_id} · horyzont {c.horizon} · kontekst {c.market_context_key || "—"}</p>
          {c.job && <p className="small">Zadanie: <Badge s={c.job.state} /> {c.job.kind || ""} {c.job.op || ""} {c.job.reason || ""}
            {c.job.result?.steps != null && ` · kroki ${c.job.result.steps} · epoki ${c.job.result.epochs_done}`}
            {c.job.computation && ` · strata ${fmtNum(c.job.computation.incumbent_loss, 4)} → ${fmtNum(c.job.computation.candidate_loss, 4)} (${c.job.computation.winner}, oceny ${c.job.computation.evaluations?.join("+")})`}
            {c.job.activation && <> · aktywacja <Badge s={c.job.activation.state} /> {c.job.activation.reason || ""}</>}
            {c.job.error && <span className="err"> {c.job.error}</span>}</p>}
          <div className="row wrap" style={{ gap: 6 }}>
            {c.component_id === "TH_SDFORMERFLOW" ? <>
              <button className="btn tiny ghost" onClick={() => job(c.component_id, { kind: "DATASET" }, "dataset przygotowany")}>Przygotuj dane</button>
              <button className="btn tiny" onClick={() => job(c.component_id, { kind: "TRAIN", op: "from_scratch" }, "trening od zera uruchomiony")}>Trenuj od zera</button>
              <button className="btn tiny" disabled={!c.active_version} onClick={() => job(c.component_id, { kind: "TRAIN", op: "fine_tune" }, "fine-tune uruchomiony")}>Fine-tune</button>
              <button className="btn tiny" disabled={!c.active_version} onClick={() => job(c.component_id, { kind: "TRAIN", op: "resume" }, "wznowienie uruchomione")}>Wznów</button></> : <>
              <button className="btn tiny ghost" onClick={() => job(c.component_id, { kind: "DATASET" }, "cechy przygotowane")}>Przygotuj cechy</button>
              <button className="btn tiny" onClick={() => job(c.component_id, { kind: "OPTIMIZE" }, "optymalizacja uruchomiona")}>Optymalizuj parametry</button></>}
            <button className="btn tiny ghost" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/cancel`), "anulowanie zgłoszone")}>Anuluj</button>
            <button className="btn tiny ghost" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/rollback`), "cofnięto wersję")}>Cofnij wersję</button>
            <button className="btn tiny ghost" onClick={() => imp(c.component_id)}>Import ZIP</button>
          </div>
          <div className="table-wrap"><table className="tbl small"><thead><tr><th>Wersja</th><th>Szczegóły</th><th /></tr></thead>
            <tbody>{(c.versions || []).map((v: any) => (
              <tr key={v.version}><td>{v.version}{v.version === c.active_version && <> <Badge s="ACTIVE" /></>}</td>
                <td className="muted">{c.component_id === "TH_SDFORMERFLOW" ? `epoki ${v.epochs_done ?? "?"} · kroki ${v.steps ?? "?"} · próbki ${v.samples ?? "?"} · strata ${fmtNum(v.history?.slice(-1)?.[0]?.train_loss, 4)} · ${v.ok === false ? v.code : "OK"}`
                  : `${v.params?.price} · ${v.params?.window_set} · szer. ${v.params?.width} · ${v.source || ""}`}</td>
                <td className="row" style={{ gap: 4 }}>
                  {v.version !== c.active_version && <button className="btn tiny" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/activate`, { version: v.version }), `aktywowano ${v.version}`)}>Aktywuj</button>}
                  <a className="btn tiny ghost" href={`/api/v1/trainhub/components/${c.component_id}/export.zip?version=${encodeURIComponent(v.version)}`}>Eksport</a></td></tr>))}</tbody></table></div>
          {c.metrics && <p className="small muted">Metryki skuteczności: {c.metrics.status} (strata treningowa to nie prawdopodobieństwo trafienia)</p>}
        </div>))}
      {msg && <p className="small muted">{msg}</p>}
    </section>);
}
