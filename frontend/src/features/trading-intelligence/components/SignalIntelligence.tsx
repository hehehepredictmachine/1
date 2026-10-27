// Signal Intelligence: the setup the engine is following (or another candidate, view only), direction, conditions, trigger,
// invalidation, plan prices, model results and two separate answers: why there is no SIGNAL and why there is no ORDER.
// Everything comes from the engine's decision (WS "decision") and AUTO ranking (WS "auto") - nothing is computed or invented here.
import { useState } from "react";
import { href } from "../../../router";
import { useStore } from "../../../store";
import { cls, fmtNum, fmtTime, reasonPl } from "../../../util";

/** decision_tree nodes that decide whether a SIGNAL exists; every other node decides whether an ORDER may be sent. */
export const SIGNAL_NODES = ["DATA", "MARKET", "STRATEGY", "TRIGGER"];

const SIDE_PL: Record<string, string> = { LONG: "BUY", SHORT: "SELL", BUY: "BUY", SELL: "SELL" };
const STAGE_PL: Record<string, string> = { WATCH: "obserwacja", EARLY: "wczesny", CONFIRMED: "potwierdzony", EXPIRED: "wygasły", INVALIDATED: "unieważniony" };
const STATUS_ICON: Record<string, [string, string]> = {
  MET: ["✓", "ok"], PASS: ["✓", "ok"], MISSING: ["✕", "bad"], FAIL: ["✕", "bad"], NO_DATA: ["?", "muted"], PENDING: ["…", "warn"],
};

// the node's reasons; the unmet conditions only when the engine gave no reason for them
function nodeReasons(n: any): string[] {
  const codes: string[] = (n.reason_codes || []).length ? n.reason_codes : n.unmet || [];
  return [...new Set(codes)].map(reasonPl);
}

const NODE_PL: Record<string, string> = {
  DATA: "Dane", MARKET: "Rynek", STRATEGY: "Strategia", TRIGGER: "Wyzwalacz", RISK: "Ryzyko", AI: "Agent AI", ML: "Model ML", PERMISSION: "Zgoda na wykonanie",
};

function WhyItem({ n }: { n: any }) {
  return <li data-node={n.node} data-status={n.status}><b>{NODE_PL[n.node] ?? n.node}</b>{n.status === "PENDING" ? " (oczekuje)" : ""}: {nodeReasons(n).join(" · ") || n.status}</li>;
}

export function whyLists(d: any) {
  const tree: any[] = d?.decision_tree || [];
  const blocking = (n: any) => n.status === "FAIL" || n.status === "PENDING";
  const sig = tree.filter((n) => SIGNAL_NODES.includes(n.node) && blocking(n));
  const ord = tree.filter((n) => !SIGNAL_NODES.includes(n.node) && blocking(n));
  return { sig, ord };
}

export default function SignalIntelligence() {
  const { s } = useStore();
  const d = s.decision;
  const auto = s.auto;
  const [view, setView] = useState<string>("");          // "" = the setup the engine follows; otherwise a candidate (view only)
  if (!d) {
    return (
      <aside className="t-card t-signal" aria-label="Signal Intelligence" data-testid="ti-signals">
        <header className="t-card-head"><h2>Signal Intelligence</h2></header>
        <p className="t-dim">Silnik nie opublikował jeszcze decyzji (start, brak danych MT5 albo brak połączenia z backendem).</p>
      </aside>);
  }
  const setup = d.setup;
  const cands: any[] = (auto?.candidate_ranking || []).filter((c: any) => c.setup_id !== setup?.setup_id);
  const other = view ? cands.find((c) => c.setup_id === view) : null;
  const side = SIDE_PL[(other?.direction ?? setup?.direction ?? d.analysis_direction) || ""] ?? null;
  const risk = d.risk || {};
  const lv = d.levels || {};
  const cl = d.checklist || {};
  const sv = d.signal_view || {};
  const digits = sv.digits ?? s.symbol?.info?.digits ?? 2;
  const items: any[] = (sv.checklist || []).slice(0, 8);
  const { sig, ord } = whyLists(d);
  const confirmed = d.signal_stage === "CONFIRMED";
  const permitted = d.execution_permission === "ALLOWED";
  const ml = d.ml || {};
  const targets: any[] = risk.targets || lv.targets || [];
  return (
    <aside className="t-card t-signal" aria-label="Signal Intelligence" data-testid="ti-signals" data-stage={d.signal_stage} data-decision={d.decision}>
      <header className="t-card-head"><h2>Signal Intelligence</h2>
        <span className={cls("t-badge", confirmed ? "t-badge-ok" : "t-badge-muted")}>{confirmed ? "sygnał potwierdzony" : "brak potwierdzonego sygnału"}</span></header>
      <label className="t-field">Setup
        <select value={view} onChange={(e) => setView(e.target.value)} data-testid="ti-setup-select">
          <option value="">{setup ? `${setup.strategy_id} ${setup.strategy_name} · ${SIDE_PL[setup.direction] ?? setup.direction} · ${setup.setup_tf} (wybrany przez silnik)` : "brak setupu silnika"}</option>
          {cands.map((c) => <option key={c.setup_id} value={c.setup_id}>{c.strategy_id} {c.strategy_name} · {SIDE_PL[c.direction] ?? c.direction} · {c.timeframe} · {fmtNum(c.setup_score, 1)} pkt</option>)}
        </select>
      </label>
      {other && <p className="t-note" data-testid="ti-setup-other">Podgląd kandydata – nie zmienia wyboru silnika. Plan, warunki i bramki poniżej dotyczą tylko setupu wybranego przez silnik;
        kandydat: etap {STAGE_PL[other.stage] ?? other.stage}, wynik {fmtNum(other.setup_score, 1)}, dopasowanie strategii {fmtNum(other.strategy_fit_score, 1)}.</p>}
      <div className="t-sig-head">
        <b className={cls("t-sig-side", side === "BUY" && "t-pos", side === "SELL" && "t-neg")} data-testid="ti-direction">{side ?? "—"} · {d.symbol ?? "—"}</b>
        <span className="t-dim">etap: {STAGE_PL[d.signal_stage] ?? d.signal_stage ?? "—"} · decyzja: {d.decision ?? "—"} · {fmtTime(d.as_of_utc)}</span>
        {d.observation_note && <span className="t-note">{d.observation_note}</span>}
      </div>
      {!other && (
        <dl className="t-kv t-plan" data-testid="ti-plan">
          <dt>Strategia / wynik</dt><dd>{setup ? `${setup.strategy_id} ${setup.strategy_name} · ${fmtNum(setup.setup_score, 1)} pkt` : "—"}</dd>
          <dt>Wejście</dt><dd>{risk.entry != null ? fmtNum(risk.entry, digits) : lv.entry_zone ? `${fmtNum(lv.entry_zone[0], digits)} – ${fmtNum(lv.entry_zone[1], digits)}` : "—"}</dd>
          <dt>SL</dt><dd>{fmtNum(risk.stop_loss ?? lv.stop_loss, digits)}</dd>
          <dt>TP</dt><dd>{targets.length ? targets.map((t: any) => fmtNum(t.price, digits)).join(" / ") : "—"}</dd>
          <dt>RR brutto / netto</dt><dd>{fmtNum(risk.rr_gross, 2)} / {fmtNum(risk.rr_net, 2)}{risk.rr_complete === false ? " (koszty niepełne)" : ""}</dd>
          <dt>Wielkość</dt><dd>{risk.sizing_status === "SIZED" && risk.lots
            ? `${risk.lots} lot · szac. strata przy SL ${fmtNum(risk.modeled_loss, 2)} ${risk.currency ?? ""}` : `nie wyliczono (${risk.sizing_status ?? "—"})`}</dd>
        </dl>)}
      {!other && items.length > 0 && (
        <div>
          <p className="t-sub">Warunki wejścia</p>
          <ul className="t-checks" data-testid="ti-conditions">
            {items.map((c) => {
              const [icon, tone] = STATUS_ICON[c.status] ?? ["•", "muted"];
              return <li key={c.id} className={tone}><i aria-hidden="true">{icon}</i><span><b>{c.label}</b><small>{c.desc}</small></span>
                <span className="t-sr">{c.status}</span></li>;
            })}
          </ul>
        </div>)}
      {!other && (cl.trigger || cl.invalidation) && (
        <div className="t-trig" data-testid="ti-trigger">
          <p><b>Trigger</b> {cl.trigger?.description ?? "—"}{cl.trigger?.met ? " – spełniony" : ""}</p>
          <p><b>Unieważnienie</b> {cl.invalidation?.event ?? "—"}{cl.invalidation?.level != null ? ` (${fmtNum(cl.invalidation.level, digits)})` : ""}
            {cl.invalidation?.time_rule ? ` · ${cl.invalidation.time_rule}` : ""}</p>
        </div>)}
      <div className="t-models" data-testid="ti-models">
        <p className="t-sub">Modele</p>
        <p>ML ({ml.ml_mode ?? "—"}): {ml.model_id ? `${ml.model_family ?? ""} ${ml.model_version ?? ""} · prawdopodobieństwo ${ml.calibrated_probability != null ? fmtNum(ml.calibrated_probability * 100, 1) + " %" : "—"} (${ml.calibration_status})`
          : `brak modelu – ${ml.readiness ?? "—"}${ml.uncertainty_reason ? ` (${ml.uncertainty_reason})` : ""}`}</p>
        <p>Agent AI: {d.agent_gate?.status ?? "—"}{(d.agent_gate?.reason_codes || []).length ? ` – ${d.agent_gate.reason_codes.map(reasonPl).join(", ")}` : ""}</p>
      </div>
      <div className="t-why" data-testid="ti-why-signal">
        <b>Dlaczego brak sygnału?</b>
        {confirmed ? <p>Sygnał jest potwierdzony – patrz „Dlaczego brak zlecenia?”.</p>
          : sig.length === 0 ? <p>{setup ? `Setup na etapie „${STAGE_PL[d.signal_stage] ?? d.signal_stage}” – czeka na potwierdzenie.` : "Żadna strategia nie ma teraz setupu."}</p>
            : <ul>{sig.map((n) => <WhyItem key={n.node} n={n} />)}</ul>}
      </div>
      <div className="t-why" data-testid="ti-why-order">
        <b>Dlaczego brak zlecenia?</b>
        {permitted ? <p>Wysłanie zlecenia jest dozwolone w trybie {s.mode?.mode} – o wysłaniu decyduje potwierdzony sygnał.</p>
          : ord.length === 0 ? <p>{confirmed ? "Brak zgody na wykonanie – szczegóły w drzewie decyzji." : "Nie ma potwierdzonego sygnału, więc nie ma czego wysłać."}</p>
            : <ul>{ord.map((n) => <WhyItem key={n.node} n={n} />)}</ul>}
      </div>
      <div className="t-row">
        {setup && <a className="t-btn" href={href("warunki", { setupId: setup.setup_id })} data-testid="ti-open-plan">Pełny plan i ręczna akcja</a>}
        <a className="t-btn t-btn-acc" href={href("ai-neural-lab")}>Pokaż szczegóły modeli</a>
      </div>
      <p className="t-note">Podgląd nigdy nie wysyła zlecenia. Ręczna akcja wymaga potwierdzenia w widoku planu, a backend ponownie sprawdza warunki przed wysłaniem.</p>
    </aside>);
}
