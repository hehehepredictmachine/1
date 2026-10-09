import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime, reasonPl } from "../util";

const STAGE_PL: Record<string, string> = { WATCH: "WATCH (obserwacja)", EARLY: "EARLY (rozwija się)", CONFIRMED: "CONFIRMED (potwierdzony)" };
const STATE_PL: Record<string, string> = {
  SCANNING: "skanowanie – brak poprawnego kandydata", WATCHING: "obserwacja", DEVELOPING: "setup się rozwija", CONFIRMED: "setup potwierdzony",
  STALE: "dane nieaktualne", STARTING: "start", DISABLED_PROFILE_ORIGINAL: "profil ORIGINAL (AUTO wyłączone)",
};
const REGIME_PL: Record<string, string> = {
  TREND_UP: "trend wzrostowy", TREND_DOWN: "trend spadkowy", RANGE: "konsolidacja", COMPRESSION: "kompresja zmienności", EXPANSION: "ekspansja",
  EXHAUSTION_OR_REVERSAL_CANDIDATE: "wyczerpanie / kandydat odwrócenia", TRANSITION: "przejściowy / niepewny", DATA_UNAVAILABLE: "brak danych", STALE: "dane nieaktualne",
};
const PTS_PL: Record<string, string> = { structure: "struktura", formation: "formacja", momentum: "momentum", trigger: "trigger", htf: "HTF", extra: "dodatkowe" };

/** Full AUTO status (setups, strategies, funnel) refreshed on every backend AUTO update, at most every 2 s. */
export function useAutoFull() {
  const { s } = useStore();
  const [full, setFull] = useState<any>(null);
  const last = useRef(0);
  const tick = s.auto?.last_evaluated_at;
  useEffect(() => {
    const now = Date.now();
    const wait = Math.max(0, 2000 - (now - last.current));
    const t = setTimeout(() => {
      last.current = Date.now();
      apiGet("/api/v1/strategy/auto").then(setFull).catch(() => undefined);
    }, wait);
    return () => clearTimeout(t);
  }, [tick, s.active_config?.profile, s.active_config?.strategy_mode]);
  return [full, () => apiGet("/api/v1/strategy/auto").then(setFull)] as const;
}

function Dir({ d }: { d?: string }) {
  return <b className={d === "LONG" ? "pos" : d === "SHORT" ? "neg" : ""}>{d ?? "—"}</b>;
}

function Points({ score }: { score: any }) {
  if (!score?.points) return null;
  return (
    <div className="pts">
      {Object.entries(score.points).map(([k, v]: any) => (
        <span key={k} title={`${PTS_PL[k] ?? k}: ${v} / ${score.weights?.[k]}`}>
          <i style={{ width: `${(100 * v) / (score.weights?.[k] || 1)}%` }} />{PTS_PL[k] ?? k} {v}/{score.weights?.[k]}
        </span>
      ))}
      <small>kompletność danych {Math.round((score.completeness ?? 0) * 100)}% · skala 0–100 to heurystyka, nie prawdopodobieństwo</small>
    </div>
  );
}

export function AutoPanel({ full }: { full: any }) {
  const { s } = useStore();
  const a = full || s.auto || {};
  const sel = a.selected;
  const reg = a.regime || {};
  const d = s.decision;
  const blockers = (d?.decision_tree || []).filter((n: any) => n.status !== "PASS").map((n: any) => `${n.node}: ${(n.reason_codes?.length ? n.reason_codes : n.unmet).slice(0, 2).map(reasonPl).join(", ")}`);
  return (
    <section className="panel auto-panel">
      <div className="panel-head"><b>AUTO — wybór strategii</b>
        <span className={cls("tag", a.strategy_mode === "MANUAL" ? "warn" : "ok")}>{a.strategy_mode ?? "…"}{a.manual_strategy_id ? ` ${a.manual_strategy_id}` : ""}</span>
        <span className={cls("tag", a.data_status === "OK" ? "ok" : "warn")}>dane {a.data_status ?? "?"}</span>
        <span className="spacer" /><small>ostatnia analiza {fmtTime(a.last_evaluated_at)} · skan {a.scan_ms ?? "–"} ms</small>
      </div>
      <div className="auto-body">
        <div className="auto-row"><label>Stan</label><b>{STATE_PL[a.system_state] ?? a.system_state ?? "—"}</b></div>
        <div className="auto-row"><label>Reżim ({reg.local_tf ?? "M15"})</label><b>{REGIME_PL[reg.state] ?? reg.state ?? "—"}</b>
          <small>{reg.reason ?? ""}</small></div>
        <div className="auto-row"><label>Horyzonty</label><span className="hz">
          {Object.entries(reg.horizons || {}).map(([k, v]: any) => <i key={k} className={v === "UP" ? "pos" : v === "DOWN" ? "neg" : ""}>{k}: {v ?? "?"}</i>)}</span></div>
        {(reg.conflicts || []).length > 0 && <div className="auto-row"><label>Konflikty TF</label>
          <small className="warn">{reg.conflicts.map((c: any) => `${c.a} ${c.a_dir} vs ${c.b} ${c.b_dir}`).join(" · ")}</small></div>}
        {a.manual_fit?.mismatch && <div className="note warn">Wybrana ręcznie strategia {a.manual_fit.strategy_id} słabo pasuje do reżimu (dopasowanie {a.manual_fit.fit}/100).</div>}
        {sel ? (
          <div className="auto-sel-box">
            <div className="auto-row big"><label>Wybrana</label><b>{sel.strategy_id} {sel.strategy_name}</b><small>v{sel.strategy_version} · {sel.validation_status}</small></div>
            <div className="auto-row"><label>Setup</label><span><Dir d={sel.direction} /> {sel.timeframe} · {STAGE_PL[sel.stage] ?? sel.stage} · wynik <b>{fmtNum(sel.setup_score, 1)}</b>
              {sel.countertrend && <span className="tag warn">COUNTERTREND {sel.horizon}</span>}</span></div>
            <div className="auto-row"><label>Dlaczego</label><small>
              {sel.family} pasuje do reżimu „{REGIME_PL[reg.state] ?? reg.state}” (dopasowanie {sel.strategy_fit_score}/100), najwyższy ranking po grupowaniu podobnych sygnałów.
              {(a.selection_reason_codes || []).length ? " " + a.selection_reason_codes.join(", ") : ""}</small></div>
            <div className="auto-row"><label>Aktywacja</label><small>{sel.entry_plan?.trigger ?? "—"}{sel.entry_plan?.trigger_level ? ` (poziom ${fmtNum(sel.entry_plan.trigger_level, 2)})` : ""}</small></div>
            <div className="auto-row"><label>Unieważnienie</label><small>{sel.invalidation_level != null ? `zamknięcie ${sel.direction === "LONG" ? "poniżej" : "powyżej"} ${fmtNum(sel.invalidation_level, 2)}` : "nieustalone"}
              · SL {fmtNum(sel.stop_loss, 2)} · cele {(sel.targets || []).map((t: any) => fmtNum(t.price, 2)).join(" / ") || "nieustalone"}</small></div>
            <div className="auto-row"><label>Brakuje</label><small>{(sel.missing_confirmations || []).map(reasonPl).join(", ") || "—"}</small></div>
            <Points score={sel.score} />
          </div>
        ) : <div className="note">Brak wybranej strategii – {(a.selection_reason_codes || []).map(reasonPl).join(", ") || "skanowanie"}. Bot nie wymusza wyboru.</div>}
        <div className="auto-row"><label>Wykonanie</label><small className={d?.execution_permission === "ALLOWED" ? "pos" : "neg"}>
          {d?.execution_permission ?? "—"}{blockers.length ? " – " + blockers.slice(0, 4).join(" · ") : ""}</small></div>
        {a.alternative && <div className="auto-row"><label>Alternatywa</label><small>{a.alternative.strategy_id} {a.alternative.direction} {a.alternative.stage} – {a.alternative.needs}</small></div>}
        {a.last_change && <div className="auto-row"><label>Ostatnia zmiana</label><small>{fmtTime(a.last_change.at)}: {a.last_change.previous_strategy ?? "brak"} → {a.last_change.selected_strategy ?? "brak"} ({a.last_change.reason})</small></div>}
        <div className="auto-rank">
          <label>Najlepsze kandydatury (ranking = 0,35·dopasowanie + 0,65·wynik + etap)</label>
          {(a.candidate_ranking || []).slice(0, 3).map((c: any) => (
            <div key={c.setup_id} className={cls("rank", sel && c.setup_id === sel.setup_id && "on")}>
              <b>{c.strategy_id}</b> <Dir d={c.direction} /> {c.timeframe} {c.stage} · ranking {fmtNum(c.rank_score, 1)} (dopas. {c.strategy_fit_score}, wynik {fmtNum(c.setup_score, 1)})
              {c.grouped_with?.length ? <small> · ten sam ruch: {c.grouped_with.join(", ")}</small> : null}
            </div>
          ))}
          {!(a.candidate_ranking || []).length && <small>brak kandydatów</small>}
        </div>
      </div>
    </section>
  );
}

export function LiveSetupsPanel({ full }: { full: any }) {
  const [showAll, setShowAll] = useState(false);
  const { s } = useStore();
  const setups = (full?.setups || []).filter((x: any) => showAll || x.status === "ACTIVE");
  const sel = full?.selected?.setup_id;
  const d = s.decision;
  return (
    <section className="panel setups-panel">
      <div className="panel-head"><b>Setupy na bieżąco</b><span className="tag">{setups.length}</span>
        <span className="spacer" /><label className="inline"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />historia (także odwołane)</label></div>
      <div className="setups-body">
        {setups.map((x: any) => (
          <div key={x.setup_id} className={cls("setup-card", x.setup_id === sel && "on", x.status !== "ACTIVE" && "done", x.stale && "stale")}>
            <div className="sc-head"><Dir d={x.direction} /> <b>{x.stage}</b> · {x.strategy_id} {x.strategy_name} · {x.timeframe} · {x.horizon}
              {x.countertrend && <span className="tag warn">COUNTERTREND</span>}
              {x.stale && <span className="tag warn">STALE</span>}
              {x.status !== "ACTIVE" && <span className="tag">{x.status}: {x.terminal_reason}</span>}
              <span className="spacer" /><b>{fmtNum(x.setup_score, 1)}</b></div>
            <small>Strefa {x.entry_plan?.zone ? x.entry_plan.zone.map((z: number) => fmtNum(z, 2)).join("–") : "nieustalona"} · trigger: {x.entry_plan?.trigger ?? "—"}
              · unieważnienie {x.invalidation_level != null ? fmtNum(x.invalidation_level, 2) : "nieustalone"} · cele {(x.targets || []).map((t: any) => fmtNum(t.price, 2)).join(" / ") || "nieustalone"}</small>
            <small>HTF: {Object.entries(x.score?.htf || {}).map(([k, v]: any) => `${k} ${v ?? "?"}`).join(", ") || "—"} · dane {fmtTime(x.source_time)}{x.forming_bar_used ? " (z tworzącą się świecą)" : ""}
              · ważny do {fmtTime(x.expires_at)} · wersja {x.version} · wykryty {fmtTime(x.first_seen_at)}</small>
            <small>Brakuje: {(x.missing_confirmations || []).map(reasonPl).join(", ") || "—"}</small>
            <small>AI: {x.setup_id === d?.setup?.setup_id ? (d?.agent_gate?.status ?? "—") : "AI_PENDING (ocenia tylko wybrany setup)"} ·
              wykonanie: {x.setup_id === d?.setup?.setup_id ? d?.execution_permission : "BLOCKED – nie jest wybranym setupem"}
              {x.setup_id === d?.setup?.setup_id && d?.risk?.rr_net != null ? ` · RR netto ${fmtNum(d.risk.rr_net, 2)}` : ""}</small>
          </div>
        ))}
        {!setups.length && (
          <div className="why">
            <b>Dlaczego nie ma setupu?</b>
            <ul>{(full?.why_no_setup || ["brak danych o skanie"]).map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
            <small>Stan NEUTRAL jest poprawny – bot nie wymusza sygnałów.</small>
          </div>
        )}
      </div>
    </section>
  );
}

export function StrategiesPanel({ full, reload }: { full: any; reload: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [log, setLog] = useState<any[]>([]);
  useEffect(() => { apiGet("/api/v1/strategy/selection-log?limit=12").then((r) => setLog(r.log)).catch(() => undefined); }, [full?.last_change?.at]);
  const toggle = async (sid: string, field: "scan" | "trade", v: boolean) => {
    setErr(null);
    try {
      await apiSend("POST", "/api/v1/strategy/toggle", { strategy_id: sid, [field]: v });
      reload();
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  };
  const per = full?.per_strategy || {};
  const funnel = full?.funnel || {};
  return (
    <section className="panel strategies-panel">
      <div className="panel-head"><b>Strategie (10) i dziennik AUTO</b><span className="spacer" />{err && <small className="neg">{err}</small>}</div>
      <div className="strat-body">
        <table className="tbl">
          <thead><tr><th>ID</th><th>Strategia</th><th>Rodzina</th><th>Status skanu</th><th title="wykryte struktury / opublikowane od startu">Lejek</th><th>Skanuj</th><th>Dopuść do handlu</th></tr></thead>
          <tbody>
            {(full?.strategies || []).map((st: any) => {
              const p = per[st.strategy_id] || {};
              const f = funnel[st.strategy_id] || {};
              return (
                <tr key={st.strategy_id}>
                  <td><b>{st.strategy_id}</b></td><td title={`v${st.version} · ${st.validation_status}`}>{st.name}</td><td>{st.family}</td>
                  <td className={p.status === "OK" ? "" : "warn"} title={(p.reasons || []).join(", ")}>{p.status ?? "—"} {p.published ? Object.entries(p.published).map(([k, v]) => `${k[0]}${v}`).join(" ") : ""}</td>
                  <td>{f.drafts ?? 0}/{(f.published_WATCH ?? 0) + (f.published_EARLY ?? 0) + (f.published_CONFIRMED ?? 0)}</td>
                  <td><input type="checkbox" checked={!!st.scan} onChange={(e) => toggle(st.strategy_id, "scan", e.target.checked)} /></td>
                  <td><input type="checkbox" checked={!!st.trade} onChange={(e) => toggle(st.strategy_id, "trade", e.target.checked)} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <small className="muted">Wszystkie strategie: status FUNCTIONAL_ONLY_OOS_NOT_RUN (eksperymentalne). „Dopuść do handlu” nie omija trybu, limitów ryzyka ani AI.</small>
        <div className="sel-log">
          <b>Dziennik AUTO</b>
          {log.map((l) => <div key={l.id}><small>{fmtTime(l.at)} [{l.strategy_mode}] {l.previous_strategy ?? "brak"} → {l.selected_strategy ?? "brak"}: {l.reason}</small></div>)}
          {!log.length && <small>brak zmian</small>}
        </div>
      </div>
    </section>
  );
}
