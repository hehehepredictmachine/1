// Top of the monitor: (1) the current signal card, (2) the entry checklist, (3) the timeframe context.
// Everything comes from ONE presentation model built by the engine from one decision (backend engine/signal_view.py):
// same snapshot / decision / signal id for the card, the checklist and the reason. The browser only DOWNGRADES the card
// when it can no longer be trusted (validity passed, no live connection, stale decision) - it never upgrades a state.
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime, reasonPl } from "../util";

const LABEL: Record<string, string> = {
  BUY: "BUY", SELL: "SELL", OCZEKIWANIE: "OCZEKIWANIE", BRAK_SYGNALU: "BRAK SYGNAŁU", BLOKADA: "BLOKADA", NIEAKTUALNY: "NIEAKTUALNY", BRAK_DANYCH: "BRAK DANYCH",
};
const SUB: Record<string, string> = {
  BUY: "kupno – otwarcie pozycji LONG", SELL: "sprzedaż – otwarcie pozycji SHORT", OCZEKIWANIE: "setup w przygotowaniu – jeszcze nie wchodzić",
  BRAK_SYGNALU: "brak zakwalifikowanego setupu", BLOKADA: "wejście zablokowane", NIEAKTUALNY: "sygnał wygasł lub unieważniony – nie wchodzić",
  BRAK_DANYCH: "nie można ocenić sytuacji",
};
const TONE: Record<string, string> = { BUY: "buy", SELL: "sell", OCZEKIWANIE: "wait", BLOKADA: "block", NIEAKTUALNY: "muted", BRAK_SYGNALU: "muted", BRAK_DANYCH: "nodata" };
const ICON: Record<string, string> = { MET: "✓", MISSING: "✗", NO_DATA: "?", PENDING: "…" };
const ST_PL: Record<string, string> = { MET: "spełnione", MISSING: "niespełnione", NO_DATA: "brak danych", PENDING: "w toku" };
const AI_PL: Record<string, string> = {
  AI_NIEDOSTEPNE: "AI NIEDOSTĘPNE", AKTUALNA: "ocena AI aktualna", NIEAKTUALNA: "ocena AI nieaktualna (starszy stan)", AI_BLAD: "błąd AI",
  OCZEKUJE_NA_OCENE: "AI: oczekuje na ocenę", OCENA_TYLKO_PO_POTWIERDZENIU: "AI ocenia tylko potwierdzony setup", BRAK_SETUPU: "AI: brak setupu",
};
const STALE_DECISION_S = 120;
const NODE_PL: Record<string, string> = { DATA: "Dane", MARKET: "Rynek", STRATEGY: "Strategia", RISK: "Ryzyko", AI: "Agent AI", ML: "Model ML", PERMISSION: "Tryb wykonania" };
/** "RISK:SPREAD_TOO_WIDE" -> "Ryzyko: <polish reason>" */
export function blockPl(code: string): string {
  const m = /^([A-Z]+):(.+)$/.exec(code);
  if (m && NODE_PL[m[1]]) return `${NODE_PL[m[1]]}: ${reasonPl(m[2])}`;
  return code === "LEVELS_INCONSISTENT_WITH_LIVE_PRICE" ? "poziomy niespójne z bieżącą ceną (cena minęła wejście/TP)" : reasonPl(code);
}

export function planText(p: { side?: string | null; symbol?: string; entry?: number | null; sl?: number | null; tp?: (number | null)[]; rr?: number | null;
  validUntil?: string | null; digits?: number; waiting?: boolean; signalId?: string | null }): string {
  const n = (x: any) => (x == null ? "—" : fmtNum(x, p.digits ?? 2));
  return [`${p.waiting ? "PLAN " : ""}${p.side ?? "—"} ${p.symbol ?? ""}`.trim(), `wejście ${n(p.entry)}`, `SL ${n(p.sl)}`,
    `TP ${(p.tp && p.tp.length ? p.tp : [null]).map(n).join(" / ")}`, `RR ${p.rr == null ? "—" : fmtNum(p.rr, 2)}`,
    `ważny do ${p.validUntil ? fmtTime(p.validUntil, true) : "—"}`, p.signalId ? `(${p.signalId})` : ""].filter(Boolean).join(" | ");
}

function useNow(ms = 1000) {
  const [t, setT] = useState(Date.now());
  useEffect(() => { const h = setInterval(() => setT(Date.now()), ms); return () => clearInterval(h); }, [ms]);
  return t;
}

function left(untilIso: string | null | undefined, now: number) {
  if (!untilIso) return "—";
  const s = Math.floor((Date.parse(untilIso) - now) / 1000);
  if (s <= 0) return "minął";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h} h ${m} min` : `${m} min ${String(sec).padStart(2, "0")} s`;
}

/** Client-side downgrade only (never upgrade): returns [state, note]. */
export function effectiveState(v: any, ws: string, asOf: string | null | undefined, now: number): [string, string | null] {
  if (!v) return ["BRAK_DANYCH", "czekam na pierwszy cykl silnika"];
  if (ws !== "OPEN") return ["BRAK_DANYCH", "brak połączenia z lokalnym backendem – karta nie jest aktualna"];
  if (asOf && now - Date.parse(asOf) > STALE_DECISION_S * 1000) return ["BRAK_DANYCH", `ostatnia decyzja starsza niż ${STALE_DECISION_S / 60} min`];
  if (v.valid_until && Date.parse(v.valid_until) <= now && ["BUY", "SELL", "OCZEKIWANIE", "BLOKADA"].includes(v.state))
    return ["NIEAKTUALNY", "upłynęła ważność sygnału"];
  return [v.state, null];
}

function Px({ label, abbr, v, digits, note, big }: { label: string; abbr: string; v: any; digits: number; note?: string | null; big?: boolean }) {
  return (
    <div className={cls("lv", big && "big")}>
      <label title={abbr}>{label}</label>
      <b data-testid={`lv-${label.toLowerCase()}`}>{v == null ? "—" : typeof v === "number" ? fmtNum(v, digits) : v}</b>
      <small>{v == null ? note ?? "" : note ?? ""}</small>
    </div>
  );
}

export default function SignalTop() {
  const { s } = useStore();
  const now = useNow();
  const d = s.decision;
  const v = d?.signal_view;
  const [state, note] = effectiveState(v, s.ws, d?.as_of_utc, now);
  const [copied, setCopied] = useState<string | null>(null);
  const dig = v?.digits ?? 2;
  const L = v?.levels;
  const live = state === v?.state;                       // the card shows the engine's state (not downgraded)
  const showPlan = !!(v?.plan_side && ["BUY", "SELL", "OCZEKIWANIE", "BLOKADA"].includes(state));
  const tp = L?.tp?.values ?? [];
  const copy = () => {
    const txt = planText({ side: v.plan_side, symbol: v.symbol, entry: L?.entry?.value, sl: L?.sl?.value, tp, rr: L?.rr?.net ?? L?.rr?.gross,
      validUntil: v.valid_until, digits: dig, waiting: state !== "BUY" && state !== "SELL", signalId: v.signal_id });
    (navigator.clipboard?.writeText(txt) ?? Promise.reject()).then(() => setCopied("Skopiowano plan."), () => setCopied(txt));
  };
  const items: any[] = v?.checklist ?? [];
  return (
    <section className="signal-top" data-testid="signal-top">
      <div className={cls("hero", "hero-" + (TONE[state] ?? "muted"))} data-testid="signal-hero" data-state={state}>
        <div className="hero-head">
          <div className="hero-state">
            <span className="hero-label" data-testid="hero-state">{LABEL[state] ?? state}</span>
            {showPlan && state !== "BUY" && state !== "SELL" && <span className={cls("hero-plan", v.plan_side === "BUY" ? "buy" : "sell")} data-testid="hero-plan">Plan: {v.plan_side}</span>}
            <span className="hero-sub">{note ?? SUB[state]}</span>
          </div>
          <div className="hero-meta">
            <b>{v?.symbol ?? s.symbol?.symbol ?? "—"}</b>
            {v?.strategy && <span>{v.strategy}</span>}
            {v?.entry_tf && <span className="badge" title="interwał wejścia">{v.entry_tf}</span>}
            <span className="badge" title="źródło decyzji">{v?.source ?? "STRATEGIA"}</span>
            {v?.ai && <span className={cls("badge", v.ai.status === "AKTUALNA" ? (v.ai.verdict === "ZGODA" ? "ok" : "bad") : "muted")} data-testid="hero-ai">
              {v.ai.status === "AKTUALNA" ? (v.ai.verdict === "ZGODA" ? "AI: zgoda" : "AI: brak zgody") : AI_PL[v.ai.status] ?? v.ai.status}</span>}
            {!v?.ai && s.agent?.state === "AI_UNAVAILABLE_NO_KEY" && <span className="badge muted" data-testid="hero-ai">AI NIEDOSTĘPNE</span>}
            {v?.synthetic && <span className="badge warn">DANE SYNTETYCZNE</span>}
          </div>
        </div>

        <div className={cls("hero-levels", !live && "dim")}>
          <Px label="WEJŚCIE" abbr={L?.entry?.kind === "PLANOWANE" ? "planowana cena wejścia (rynek przy potwierdzeniu)" : "poziom wyzwalacza – wejście dopiero po potwierdzeniu"}
            v={L?.entry?.value} digits={dig} note={L?.entry?.value == null ? L?.entry?.note ?? "brak setupu" : L?.entry?.kind === "PLANOWANE" ? L.entry.note : "wyzwalacz – " + (L?.entry?.note ?? "")} big />
          <Px label="SL" abbr="SL – stop loss: poziom zamknięcia ze stratą" v={L?.sl?.value} digits={dig} note={L?.sl?.note ?? (L ? null : "brak setupu")} big />
          <Px label="TP" abbr="TP – take profit: poziom realizacji zysku" v={tp.length > 1 ? tp.map((x: number) => fmtNum(x, dig)).join(" / ") : L?.tp?.value} digits={dig}
            note={L?.tp?.rule ?? L?.tp?.note ?? (L ? null : "brak setupu")} big />
          <Px label="RR" abbr="RR – stosunek zysku do ryzyka; po kosztach (prowizja, poślizg), w nawiasie brutto" v={L?.rr?.net ?? L?.rr?.gross}
            digits={2} note={L?.rr?.net != null ? (L?.rr?.gross != null ? `po kosztach (brutto ${fmtNum(L.rr.gross, 2)})` : "po kosztach") : L?.rr?.note ?? (L ? null : "brak setupu")} big />
        </div>

        <div className="hero-rows">
          <div><label>Ryzyko / wolumen</label>
            <span>{v?.risk?.money != null ? `${fmtNum(v.risk.money)} ${v.risk.currency ?? ""}${v.risk.pct != null ? ` (${v.risk.pct}%)` : ""}` : "—"} · {v?.risk?.volume != null ? `${v.risk.volume} lot` : `— ${v?.risk?.note ? `(${v.risk.note})` : ""}`}</span></div>
          <div><label>Wygenerowano / ważny do</label>
            <span>{fmtTime(v?.generated_at, true)} · {v?.valid_until ? `${fmtTime(v.valid_until, true)} (pozostało ${left(v.valid_until, now)})` : "—"}</span></div>
          <div><label>Dane</label>
            <span>{v?.data_quality ?? "—"} · Bid/Ask {fmtNum(v?.quote?.bid, dig)} / {fmtNum(v?.quote?.ask, dig)}{v?.quote?.age_seconds != null ? ` (${v.quote.age_seconds} s)` : ""}</span></div>
          <div><label>Wykonanie</label>
            <span data-testid="hero-fill">{L?.fill?.executed ? `wykonano po ${fmtNum(L.fill.value, dig)}` : L?.fill?.note ?? "—"}{L?.reference_price != null ? ` · cena odniesienia ${fmtNum(L.reference_price, dig)}` : ""}</span></div>
        </div>

        <p className="hero-reason" data-testid="hero-reason">{v?.reason ?? "—"}</p>
        {state === "BLOKADA" && (v?.block_reasons || []).length > 0 && <p className="hero-block" data-testid="hero-block"><b>Powód blokady:</b> {v.block_reasons.map(blockPl).join(" · ")}</p>}
        {v?.execution_note && <p className="hero-note">{v.execution_note}</p>}
        {(v?.trigger || v?.invalidation?.level != null) && (
          <p className="hero-ti"><b>Trigger:</b> {v.trigger ?? "—"}<br />
            <b>Unieważnienie:</b> {v.invalidation?.level != null ? `${fmtNum(v.invalidation.level, dig)} – ${v.invalidation.rule}` : "—"}; także wygaśnięcie, zmiana kontekstu, utrata danych</p>)}
        {state === "BRAK_SYGNALU" && (v?.why || []).length > 0 && <ul className="hero-why">{v.why.map((w: string) => <li key={w}>{w}</li>)}</ul>}

        <div className="hero-actions">
          {showPlan && <button onClick={copy} data-testid="hero-copy" title="Kopiuje: kierunek, symbol, wejście, SL, TP, RR i ważność – dokładnie jak na karcie">Kopiuj plan</button>}
          {copied && <span className="muted small" data-testid="hero-copied">{copied}</span>}
        </div>
        <details className="hero-details">
          <summary>Szczegóły</summary>
          <div className="small">
            <p><b>Uzasadnienie AI:</b> {v?.ai?.explanation ?? (v?.ai?.status === "AI_NIEDOSTEPNE" ? "AI niedostępne – sygnał pochodzi wyłącznie ze strategii." : "brak")}</p>
            <p><b>Jakość setupu:</b> {v?.quality?.score ?? "—"} / 100 – {v?.quality?.method ?? "heurystyka strategii (nie prawdopodobieństwo)"}</p>
            <p><b>Prawdopodobieństwo wygranej:</b> {v?.probability_win ? `${Math.round(100 * v.probability_win.value)}% (${v.probability_win.model}, ${v.probability_win.validated})` : "— (brak zwalidowanego modelu)"}</p>
            <p><b>Status sygnału w silniku:</b> {v?.signal_status ?? "—"} · wykonanie: {v?.execution_state ?? "—"} · intencja: {v?.intent === "OTWARCIE" ? "otwarcie pozycji (nie zamknięcie)" : v?.intent}</p>
            <p className="muted">sygnał {v?.signal_id ?? "—"} · setup {v?.setup_id ?? "—"} · decyzja {v?.decision_id ?? "—"} · snapshot {v?.snapshot_id ?? "—"} · dane {v?.data_source ?? "—"}</p>
            {(v?.block_reasons || []).length > 0 && <p className="muted">kody blokad: {v.block_reasons.join(", ")}</p>}
          </div>
        </details>
      </div>

      <div className="simple-checklist" data-testid="simple-checklist">
        <h4>Warunki wejścia{v?.strategy ? ` – ${v.strategy}` : ""}</h4>
        {!items.length && <p className="muted">Brak warunków do pokazania – {state === "BRAK_DANYCH" ? "brak danych" : "brak aktywnego setupu"}.</p>}
        <ul>{items.map((i) => (
          <li key={i.id} className={cls("sc-item", "sc-" + i.status)}>
            <i aria-label={ST_PL[i.status]}>{ICON[i.status] ?? "?"}</i>
            <span><b>{i.label}</b> <small>({ST_PL[i.status] ?? i.status})</small><br /><em>{i.desc}{(i.reasons || []).length ? ` – ${i.reasons.map(reasonPl).join(", ")}` : ""}</em></span>
          </li>))}</ul>
        <p className="sc-summary" data-testid="missing-summary">{v?.missing_summary ?? "—"}</p>
      </div>

      <TfOverview rows={d?.tf_overview} />
    </section>
  );
}

const ARROW: Record<string, string> = { UP: "↑ wzrost", DOWN: "↓ spadek", FLAT: "→ płasko" };

function TfOverview({ rows }: { rows?: any[] }) {
  if (!rows?.length) return null;
  return (
    <div className="tf-overview" data-testid="tf-overview">
      <h4>Kontekst interwałów</h4>
      <div className="tfo-grid">
        {rows.map((r) => (
          <div key={r.tf} className={cls("tfo", r.conflict && "conflict", r.data !== "OK" && "nodata")} data-tf={r.tf}>
            <b>{r.tf}</b>
            <span className={r.direction === "UP" ? "pos" : r.direction === "DOWN" ? "neg" : "muted"}>{r.direction ? ARROW[r.direction] : "brak danych"}</span>
            <small>{r.role}</small>
            <small title="ostatnia zamknięta świeca (czas otwarcia)">zamkn.: {r.last_closed_utc ? fmtTime(r.last_closed_utc) : "—"}{r.forming ? " · tworzy się nowa" : ""}</small>
            <small>{r.data === "OK" ? (r.source === "resampled" ? "dane: z H1 (resampling)" : "dane: OK") : `dane: ${r.data}`}</small>
            {r.conflict && <small className="warn" title={r.conflict_impact}>⚠ konflikt z planem – {r.conflict_impact}</small>}
          </div>
        ))}
      </div>
    </div>
  );
}
