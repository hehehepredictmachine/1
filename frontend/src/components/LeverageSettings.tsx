// Settings → Ryzyko: leverage / exposure limit of the bot (per MT5 account, backend prefs.py). Not a broker setting.
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";

/** Settings → Ryzyko: "Dźwignia / limit ekspozycji". A planning / exposure limit of the bot - not a broker setting. */
export function LeverageSettings() {
  const { s } = useStore();
  const [p, setP] = useState<any>(null);
  const [mode, setMode] = useState<"AUTO" | "MANUAL">("AUTO");
  const [limit, setLimit] = useState<number>(30);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => apiGet("/api/v1/prefs").then((r) => { setP(r); setMode(r.leverage.mode); if (r.leverage.limit) setLimit(r.leverage.limit); }).catch(() => undefined);
  useEffect(() => { load(); }, [s.account?.login, s.prefs?.settings_version]);
  const acc = p?.exposure?.account_leverage;
  const save = () => apiSend("POST", "/api/v1/prefs/leverage", mode === "AUTO" ? { mode } : { mode, limit: Number(limit) })
    .then((r: any) => { setP(r); setMsg("Zapisano. Dotyczy przyszłych decyzji; otwarte pozycje i zlecenia bez zmian."); })
    .catch((e: any) => setMsg(String(e.message || e).replace(/LEVERAGE_LIMIT_ABOVE_ACCOUNT_1_(\d+)/, "Limit wyższy niż dźwignia rachunku 1:$1")));
  return (
    <div className="lev-settings" data-testid="leverage-settings">
      <h4>Dźwignia / limit ekspozycji</h4>
      <div className="lev-values">
        <div><label>Dźwignia rachunku (odczyt MT5)</label><b data-testid="lev-account">{acc ? `1:${acc}` : "brak danych"}</b></div>
        <div><label>Limit wybrany w bocie</label><b data-testid="lev-user">{p?.leverage?.mode === "MANUAL" ? `1:${p.leverage.limit}` : "AUTO (= dźwignia rachunku)"}</b></div>
        <div><label>Limit stosowany do wyliczeń</label><b>{p?.exposure?.limit ? `1:${p.exposure.limit}` : "— (tylko margin brokera)"}</b></div>
      </div>
      <div className="row">
        <label><input type="radio" checked={mode === "AUTO"} onChange={() => setMode("AUTO")} /> AUTO – parametry aktualnego rachunku MT5</label>
        <label><input type="radio" checked={mode === "MANUAL"} onChange={() => setMode("MANUAL")} /> RĘCZNIE</label>
        {mode === "MANUAL" && <select value={limit} data-testid="lev-select" onChange={(e) => setLimit(Number(e.target.value))}>
          {(p?.leverage_choices ?? [1, 10, 20, 30, 50, 100]).filter((x: number) => !acc || x <= acc).map((x: number) => <option key={x} value={x}>1:{x}</option>)}
        </select>}
        <button className="btn" data-testid="lev-save" onClick={save}>Zapisz limit</button>
      </div>
      {msg && <p className="small" data-testid="lev-msg">{msg}</p>}
      <p className="note small">Ręczny wybór to limit planowania i ekspozycji bota (nominał pozycji / equity) – <b>nie zmienia dźwigni u brokera</b>.
        Wymagany margin zawsze liczy kalkulator brokera dla konkretnego instrumentu (order_calc_margin). Wyższa dźwignia nie zwiększa procentowego
        budżetu ryzyka i nie przesuwa SL/TP. Ustawienie zapisuje się dla rachunku {p?.account_key ?? "—"}.</p>
    </div>
  );
}
