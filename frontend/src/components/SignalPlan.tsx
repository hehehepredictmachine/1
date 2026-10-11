// "Sygnał AI / plan wejścia" - the Signal contract (backend engine/signal_contract.py) next to the entry checklist.
// Prices, SL/TP, risk and volume come from the engine and the broker calculator; the AI only qualifies and explains.
import { cls, fmtNum, fmtTime, reasonPl } from "../util";

const ST_TONE: Record<string, string> = { POTWIERDZONY: "ok", OCZEKIWANIE: "warn", ZABLOKOWANY: "bad", BRAK_DANYCH: "bad", UNIEWAŻNIONY: "muted", WYGASŁY: "muted" };
const AI_PL: Record<string, string> = {
  AI_NIEDOSTEPNE: "AI NIEDOSTĘPNE", BRAK_SETUPU: "brak setupu", OCZEKUJE_NA_OCENE: "oczekuje na ocenę AI", OCENA_TYLKO_PO_POTWIERDZENIU: "AI ocenia dopiero potwierdzony setup",
  AI_BLAD: "błąd odpowiedzi AI (sygnał nie jest potwierdzony przez AI)", NIEAKTUALNA: "ocena AI dotyczy starszego stanu – nieaktualna", AKTUALNA: "ocena aktualna",
};
const EX_PL: Record<string, string> = { BRAK: "nie wysłano", WYSŁANO: "zlecenie wysłane", WYKONANO: "wykonane (fill)", ODRZUCONO: "odrzucone" };

export default function SignalPlan({ sig, digits = 2 }: { sig: any; digits?: number }) {
  if (!sig) return <div className="signal-plan" data-testid="signal-plan"><b>Sygnał AI / plan wejścia</b><p className="muted">Brak aktywnego setupu – brak sygnału.</p></div>;
  if (sig.error) return <div className="signal-plan" data-testid="signal-plan"><b>Sygnał AI / plan wejścia</b><p className="bad">BRAK_DANYCH: {sig.error}</p></div>;
  const ai = sig.ai || {};
  const px = (x: any) => (x == null ? "—" : fmtNum(x, digits));
  const tp = (sig.targets || []).map((t: any) => px(t.price)).join(" / ") || "—";
  return (
    <div className="signal-plan" data-testid="signal-plan">
      <div className="sp-head">
        <b>Sygnał AI / plan wejścia</b>
        <span className={cls("badge", ST_TONE[sig.status] ?? "muted")} data-testid="signal-status">{sig.status}</span>
        <span className={cls("badge", sig.side === "LONG" ? "ok" : "bad")}>{sig.side === "LONG" ? "LONG ↑" : sig.side === "SHORT" ? "SHORT ↓" : "—"}</span>
        <span className="badge" title="źródło decyzji">{sig.decision_source}</span>
        <span className="badge muted" title="stan wykonania – osobno od statusu sygnału">{EX_PL[sig.execution_state] ?? sig.execution_state}</span>
        <span className="spacer" />
        <span className="muted small">{sig.strategy_id} {sig.strategy_name} · {sig.entry_tf} · kontekst {(sig.context_tfs || []).join("/")}</span>
      </div>
      <div className="sp-grid">
        <div><label>Wejście ({sig.entry_type === "MARKET_ON_CONFIRMATION" ? "rynek po potwierdzeniu" : sig.entry_type})</label>
          <b>{sig.entry_price != null ? px(sig.entry_price) : sig.trigger_level != null ? `po potwierdzeniu, poziom ${px(sig.trigger_level)}` : "—"}</b></div>
        <div><label>Cena odniesienia sygnału</label><b>{px(sig.reference_price)}</b></div>
        <div><label>Bid / Ask</label><b>{px(sig.quote?.bid)} / {px(sig.quote?.ask)}</b>
          <span className="muted small"> {sig.quote?.age_seconds != null ? `(${sig.quote.age_seconds}s)` : ""}</span></div>
        <div><label>Stop loss</label><b>{px(sig.stop_loss)}</b></div>
        <div><label>Take profit</label><b>{tp}</b>{sig.tp_rule === "RR_FROM_FILL" && <span className="muted small"> (z ceny wejścia)</span>}</div>
        <div><label>RR brutto / po kosztach</label><b>{sig.rr_gross ?? "—"} / {sig.rr_net ?? "—"}</b></div>
        <div><label>Ryzyko</label><b>{sig.risk_money != null ? `${fmtNum(sig.risk_money)} ${sig.currency ?? ""}` : "—"}{sig.risk_pct != null ? ` (${sig.risk_pct}%)` : ""}</b></div>
        <div><label>Wolumen</label><b>{sig.volume ?? "—"}</b></div>
        <div><label>Spread</label><b>{sig.spread?.points ?? "—"} pkt{sig.spread?.pct_of_sl_distance != null ? ` · ${sig.spread.pct_of_sl_distance}% odl. SL` : ""}</b></div>
        <div><label>Ważny do</label><b>{fmtTime(sig.valid_until, true)}</b></div>
        <div><label>Jakość setupu</label><b title={sig.quality?.method}>{sig.quality?.score ?? "—"} / 100</b></div>
        <div><label>Prawdopodobieństwo wygranej</label><b title="tylko z modelu ML skalibrowanego i sprawdzonego poza próbką">{sig.probability_win ? `${Math.round(100 * sig.probability_win.value)}% (${sig.probability_win.model})` : "— (brak zwalidowanego modelu)"}</b></div>
      </div>
      {sig.trigger && <div className="small"><b>Trigger:</b> {sig.trigger}</div>}
      {sig.invalidation?.level != null && <div className="small"><b>Unieważnienie:</b> {px(sig.invalidation.level)} ({sig.invalidation.rule ?? "zamknięcie poza poziomem"}), zmiana kontekstu, TTL, utrata danych</div>}
      {(sig.block_reasons || []).length > 0 && <div className="small warn"><b>Blokady:</b> {sig.block_reasons.map(reasonPl).join(" · ")}</div>}
      <div className={cls("sp-ai", ai.status === "AI_NIEDOSTEPNE" && "muted")}>
        <b>AI:</b> {AI_PL[ai.status] ?? ai.status}
        {ai.verdict && <span className={cls("badge", ai.verdict === "ZGODA" ? "ok" : "bad")}>{ai.verdict === "ZGODA" ? "zgoda z kierunkiem" : "brak zgody"}</span>}
        {ai.explanation && <p className="prewrap small">{ai.explanation}</p>}
      </div>
      <div className="muted small">Źródło danych: {sig.data_source}{sig.synthetic ? " (DANE SYNTETYCZNE)" : ""} · snapshot {sig.snapshot_id} · {fmtTime(sig.generated_at, true)}
        · koszty: prowizja {sig.cost_assumptions?.commission_per_lot_side ?? "nieznana"}/lot/stronę, stres poślizgu {sig.cost_assumptions?.slippage_stress_points ?? "—"} pkt</div>
    </div>
  );
}

export function ContextTF({ ctx, digits = 2 }: { ctx: any; digits?: number }) {
  if (!ctx) return null;
  return (
    <div className="context-tf" data-testid="context-tf">
      {["M30", "H8"].map((tf) => {
        const c = ctx[tf] || { status: "BRAK_DANYCH" };
        return (
          <div key={tf} className="ctx-card" data-tf={tf}>
            <div className="sp-head"><b>{tf}</b>
              <span className={cls("badge", c.status === "OK" ? "ok" : "bad")}>{c.status}</span>
              {c.source && <span className="badge muted" title={c.parts ? `zbudowana z ${c.parts} świec H1` : ""}>{c.source === "resampled" ? "resampling" : "natywne MT5"}</span>}
              {c.direction && <span className={cls("badge", c.direction === "UP" ? "ok" : c.direction === "DOWN" ? "bad" : "muted")}>{c.direction === "UP" ? "trend ↑" : c.direction === "DOWN" ? "trend ↓" : "płasko"}</span>}
              {c.regime && <span className="badge muted">{c.regime}</span>}
            </div>
            {c.status === "OK" ? <div className="small">
              Ostatnia zamknięta: {fmtTime(c.last_closed_open_utc, true)} · świeca otwarta: {c.forming ? `${fmtTime(c.forming.open_utc, true)} (podgląd)` : "brak"}<br />
              EMA20 {fmtNum(c.ema20, digits)} · EMA50 {fmtNum(c.ema50, digits)} · high/low 20: {fmtNum(c.levels?.high_20, digits)} / {fmtNum(c.levels?.low_20, digits)}<br />
              <span className="muted">{c.impact}</span>
            </div> : <div className="small bad">{c.impact} ({c.closed_bars ?? 0} zamkniętych świec)</div>}
          </div>
        );
      })}
    </div>
  );
}
