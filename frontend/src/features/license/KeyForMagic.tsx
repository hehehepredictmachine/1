// CLIENT EDITION: "KEY FOR MAGIC" - activation / license-state window over the whole panel while the license does not authorize
// trading (not activated, invalid, expired, revoked, other device, server unavailable, tampered answer). No customer login: the key
// goes to the local backend, which activates it on the License API and keeps only the license id + device token. Open positions
// are listed here because a license problem never closes them (SL/TP and position management keep running).
import { useState } from "react";
import { apiSend } from "../../api";
import { useStore } from "../../store";
import { cls, fmtNum, fmtTime } from "../../util";
import WizardLogo from "../wizard/WizardLogo";
import "./license.css";

const TONE: Record<string, string> = {
  NOT_ACTIVATED: "info", CHECKING: "info", INVALID: "bad", EXPIRED: "warn", REVOKED: "bad", DEVICE_MISMATCH: "bad",
  SERVER_UNAVAILABLE: "warn", RATE_LIMITED: "warn", TAMPERED: "bad", NOT_CONFIGURED: "bad", HWID_ERROR: "bad",
};

export function licenseBlocks(lic: any): boolean {
  return !!lic && lic.edition?.edition === "CLIENT" && !lic.authorized;
}

export default function KeyForMagic() {
  const { s } = useStore();
  const lic = s.license;
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [local, setLocal] = useState<any>(null);
  if (!licenseBlocks(lic)) return null;
  const st = local && local.checked_at >= (lic.checked_at || "") ? local : lic;
  const status: string = st.status;
  const run = async (what: string, path: string, body?: any) => {
    setBusy(what);
    try {
      setLocal(await apiSend("POST", path, body));
    } catch (e: any) {
      setLocal({ ...st, status: "SERVER_UNAVAILABLE", reason: String(e?.message || e), checked_at: new Date().toISOString() });
    } finally {
      setBusy(null);
    }
  };
  const positions: any[] = s.positions?.positions || [];
  return (
    <div className="kfm-overlay" role="dialog" aria-modal="true" aria-labelledby="kfm-title" data-testid="license-overlay" data-status={status}>
      <div className="kfm-card">
        <div className="kfm-brand"><WizardLogo size={58} /><span>Pepe<b>Market</b>Wizard</span></div>
        <h1 id="kfm-title" className="kfm-title">KEY FOR MAGIC</h1>
        {status === "NOT_CONFIGURED" ? (
          <p className="kfm-msg bad" data-testid="license-status">{st.reason || st.status_pl}</p>) : (
          <form className="kfm-form" onSubmit={(e) => { e.preventDefault(); if (key.trim()) void run("activate", "/api/v1/license/activate", { license_key: key.trim() }); }}>
            <label htmlFor="kfm-key">Klucz licencji</label>
            <input id="kfm-key" data-testid="license-key" autoComplete="off" spellCheck={false} placeholder="PMW-XXXXX-XXXXX-XXXXX-XXXXX" value={key}
              onChange={(e) => setKey(e.target.value.toUpperCase())} maxLength={64} />
            <button type="submit" className="kfm-btn" disabled={!!busy || !key.trim()} data-testid="license-activate">
              {busy === "activate" ? "Łączenie…" : "ACTIVATE MAGIC"}</button>
          </form>)}
        {status !== "NOT_CONFIGURED" && (
          <p className={cls("kfm-msg", TONE[status] || "info")} role="status" data-testid="license-status">
            <b>{st.status_pl}</b>{st.reason && st.reason !== st.status_pl ? <> – {st.reason}</> : null}
            {st.key_hint ? <span className="kfm-dim"> · klucz {st.key_hint}</span> : null}
            {st.expires_at && status === "EXPIRED" ? <span className="kfm-dim"> · wygasła {fmtTime(st.expires_at, true)}</span> : null}
          </p>)}
        <div className="kfm-actions">
          {st.license_id && status !== "NOT_CONFIGURED" && (
            <button className="kfm-link" disabled={!!busy} onClick={() => void run("check", "/api/v1/license/check")} data-testid="license-retry">
              {busy === "check" ? "Sprawdzanie…" : "Sprawdź ponownie"}</button>)}
          {st.license_id && (
            <button className="kfm-link" disabled={!!busy} onClick={() => void run("forget", "/api/v1/license/forget")}>Użyj innego klucza</button>)}
        </div>
        <p className="kfm-note">Licencja jest sprawdzana online przy starcie, co {(st.validate_every_seconds || 300) >= 60 ? `${Math.round((st.validate_every_seconds || 300) / 60)} min`
          : `${st.validate_every_seconds} s`} i przed każdym nowym
          wejściem. Bez ważnej licencji bot nie otwiera nowych pozycji i nie wysyła powiadomień o nowych sygnałach.</p>
        <div className="kfm-positions" data-testid="license-positions">
          <b>Otwarte pozycje: {positions.length}</b>
          <span className="kfm-dim"> – {st.positions_note}</span>
          {positions.length > 0 && (
            <ul>{positions.slice(0, 8).map((p: any) => (
              <li key={p.ticket}>{p.symbol} {p.side ?? (p.type === 0 ? "BUY" : "SELL")} {fmtNum(p.volume, 2)} · wynik {fmtNum(p.profit, 2)}</li>))}</ul>)}
        </div>
      </div>
    </div>);
}

/** Small status chip for the top bars. */
export function LicenseChip() {
  const { s } = useStore();
  const lic = s.license;
  if (!lic) return null;
  if (lic.edition?.edition === "OWNER") {
    return <a className="wz-chip ok" href="#/licencje" data-testid="license-chip" title="OWNER EDITION – License Manager">OWNER</a>;
  }
  return (
    <span className={cls("wz-chip", lic.authorized ? "ok" : "bad")} data-testid="license-chip" title={lic.status_pl}>
      <i className="wz-dot" aria-hidden="true" />Licencja <b>{lic.authorized ? `do ${fmtTime(lic.expires_at, true)}` : "nieaktywna"}</b></span>);
}
