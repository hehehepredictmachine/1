import { fmtNum, fmtTime, reasonPl } from "../util";

const ICON: Record<string, string> = { MET: "✓", MISSING: "✗", NO_DATA: "?", PENDING: "…" };
const TXT: Record<string, string> = { MET: "spełnione", MISSING: "brakuje", NO_DATA: "brak danych", PENDING: "w toku" };

/** 12A: conditions instead of BUY/SELL signals. Text + icon for every status (never colour only). */
export default function Checklist({ c, positions }: { c: any; positions: number }) {
  if (!c) return <div className="checklist" data-testid="entry-checklist"><p className="muted">Brak analizy – czekam na pierwszy cykl silnika.</p></div>;
  if (c.status === "ERROR") return <div className="checklist" data-testid="entry-checklist"><p className="bad">Checklista niedostępna: {c.error}</p></div>;
  if (c.status === "NO_SCENARIO")
    return (
      <div className="checklist" data-testid="entry-checklist">
        <div className="cl-head"><b>Brak aktualnego scenariusza</b>{positions > 0 && <span className="badge warn">otwarte pozycje: {positions} (zakładka Pozycje)</span>}</div>
        <p className="muted">{c.no_scenario_reason}</p>
        {(c.why || []).length > 0 && <ul className="cl-why">{c.why.map((w: string) => <li key={w}>{w}</li>)}</ul>}
        <Gates gates={c.gates} />
      </div>
    );
  const trg = c.trigger || {};
  const inv = c.invalidation || {};
  return (
    <div className="checklist" data-testid="entry-checklist">
      <div className="cl-head">
        <b>{c.strategy_id} {c.strategy_name}</b><span className="badge">{c.timeframe}</span><span className="badge">etap: {c.stage}</span>
        {c.stale && <span className="badge warn">dane nieaktualne</span>}
        {positions > 0 && <span className="badge warn">otwarte pozycje: {positions}</span>}
      </div>
      <div className="cl-grid">
        <section>
          <h5>1. Spełnione</h5>
          <ul>{(c.met || []).map((m: any) => <li key={m.id} className="cl-met"><i aria-label="spełnione">{ICON.MET}</i><span>{m.label}</span><em>{m.reading}</em></li>)}</ul>
        </section>
        <section>
          <h5>2. Brakuje</h5>
          {(c.missing || []).length === 0 ? <p className="muted">Nic – wszystkie warunki spełnione.</p> :
            <ul>{c.missing.map((m: any) => (
              <li key={m.id} className={m.status === "NO_DATA" ? "cl-nodata" : m.status === "PENDING" ? "cl-pending" : "cl-missing"}>
                <i aria-label={TXT[m.status] ?? m.status}>{ICON[m.status] ?? "✗"}</i><span>{m.label} <small>({TXT[m.status] ?? m.status})</small></span>
                <em>{m.status === "NO_DATA" ? "brak danych" : (m.reasons || []).length ? m.reasons.slice(0, 3).map(reasonPl).join(" · ") : m.required}</em>
              </li>))}</ul>}
        </section>
        <section>
          <h5>3. Wyzwalacz wejścia</h5>
          <p>{trg.description || "—"}</p>
          <dl>
            <dt>Poziom</dt><dd>{trg.level != null ? fmtNum(trg.level, 2) : "—"}</dd>
            <dt>Strefa</dt><dd>{trg.zone ? `${fmtNum(trg.zone[0], 2)} – ${fmtNum(trg.zone[1], 2)}` : "—"}</dd>
            <dt>Interwał</dt><dd>{trg.timeframe}</dd>
            <dt>Świeca</dt><dd>{trg.closed_bar_required ? "wymagane ZAMKNIĘCIE świecy" : "dowolna"}</dd>
            <dt>Maks. odległość</dt><dd>{trg.max_distance_atr != null ? `${trg.max_distance_atr} ATR od poziomu` : "—"}</dd>
            <dt>Stan</dt><dd>{trg.met ? `${ICON.MET} wyzwalacz spełniony` : `${ICON.MISSING} jeszcze nie`}</dd>
          </dl>
        </section>
        <section>
          <h5>4. Unieważnienie</h5>
          <dl>
            <dt>Poziom</dt><dd>{inv.level != null ? fmtNum(inv.level, 2) : "brak danych"}</dd>
            <dt>Zdarzenie</dt><dd>{inv.event}</dd>
            <dt>Czas</dt><dd>{inv.time ? `${fmtTime(inv.time, true)}${inv.time_rule ? ` (${inv.time_rule})` : ""}` : inv.time_rule ?? "—"}</dd>
            <dt>Stop / cele planu</dt><dd>{fmtNum(inv.stop_loss, 2)} / {(inv.targets || []).map((t: number) => fmtNum(t, 2)).join(", ") || "—"}</dd>
          </dl>
        </section>
      </div>
      {c.data_note && <p className="warn small">{c.data_note}</p>}
    </div>
  );
}

function Gates({ gates }: { gates: any[] }) {
  if (!gates?.length) return null;
  return (
    <ul className="cl-gates">{gates.map((g) => (
      <li key={g.id} className={g.status === "MET" ? "cl-met" : g.status === "PENDING" ? "cl-pending" : "cl-missing"}>
        <i>{ICON[g.status] ?? "?"}</i><span>{g.label}</span><em>{g.status === "MET" ? "spełnione" : (g.reasons || []).slice(0, 3).map(reasonPl).join(" · ")}</em>
      </li>))}</ul>
  );
}
