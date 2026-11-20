// PMW-UPD-06: "Dlaczego bot tak odczytuje warstwy" - the deterministic OBSERVE policy over the shared session boxes and the heatmap
// snapshot (same rules as the agent tool), with reason codes, missing conditions and the knowledge rules applied. Never a signal.
import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { useStore } from "../store";

export default function LiquidityContextCard() {
  const { s } = useStore();
  const asset = s.assets?.active;
  const [side, setSide] = useState<string>("");
  const [d, setD] = useState<any>(null);
  const [sess, setSess] = useState<any>(null);
  useEffect(() => {
    if (!asset) return;
    let alive = true;
    apiGet(`/api/v1/liquidity/context${side ? `?setup_side=${side}` : ""}`).then((r) => alive && r.asset === asset && setD(r)).catch(() => undefined);
    apiGet("/api/v1/liquidity/sessions?tf=M5").then((r) => alive && r.asset === asset && setSess(r)).catch(() => undefined);
    return () => { alive = false; };
  }, [asset, side, s.analysisSeq]);
  if (!d) return null;
  return (
    <div className="card" data-testid="liq-context">
      <h3>Boksy sesji i heatmapa – jak bot to odczytuje (OBSERVE)</h3>
      <p className="small">Profil sesji: <b>{sess?.profile_label ?? "—"}</b> · baza {sess?.base_tf} · {d.policy_version} / {d.knowledge_version} · walidacja: <b>{d.validation_status}</b>
        {" "}· strona do analizy: <select aria-label="Strona" value={side} onChange={(e) => setSide(e.target.value)}><option value="">(bez setupu)</option><option value="BUY">BUY</option><option value="SELL">SELL</option></select></p>
      <div className="tbl-wrap"><table className="tbl small" data-testid="liq-boxes"><thead><tr><th>Sesja</th><th>Okno (UTC / lokalnie)</th><th>Stan</th><th>High / Low</th><th>Pokrycie</th><th>Krawędzie</th><th>Zdarzenia</th></tr></thead>
        <tbody>{(sess?.boxes || []).filter((b: any) => b.state !== "SCHEDULED").map((b: any) => (
          <tr key={b.box_id} data-state={b.state}><td>{b.session}</td><td>{b.start_utc.slice(5, 16)}–{b.end_utc.slice(11, 16)} UTC<div className="muted">{b.local_hours}</div></td>
            <td>{b.state}{b.known_at ? <div className="muted">znany {b.known_at.slice(11, 16)}</div> : null}</td>
            <td>{b.state === "FINAL" ? `${b.final_high} / ${b.final_low}` : b.state === "DEVELOPING" ? `w trakcie ${b.developing_high} / ${b.developing_low}` : b.observed_high != null ? `niepełny ${b.observed_high} / ${b.observed_low}` : "—"}</td>
            <td>{b.observed_slots}/{b.expected_slots}{b.coverage_basis === "CALENDAR_UNKNOWN" ? " (kalendarz nieznany)" : ""}</td>
            <td>{b.edges ? `H: ${b.edges.HIGH.state} · L: ${b.edges.LOW.state}` : "—"}</td>
            <td>{(b.events || []).map((e: any) => `${e.kind} @${e.bar_open_utc.slice(11, 16)} (dost. ${e.available_at.slice(11, 16)})`).join("; ") || "—"}</td></tr>))}</tbody></table></div>
      <ul className="small" data-testid="liq-codes">{d.reason_codes.map((c: any, i: number) => <li key={i}><b>{c.code}</b> – {c.detail ?? c.cause}</li>)}</ul>
      {d.missing_conditions.length > 0 && <p className="small">Brakuje: {d.missing_conditions.join("; ")}</p>}
      <p className="small muted">{d.explanation_pl} Zastosowane reguły: {d.applied_rules.join(", ")}. {d.note}.</p>
    </div>);
}
