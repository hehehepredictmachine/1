// LICENCJA (1.44.0, wersja klienta) – status licencji w panelu systemowym: użytkownik, typ, wygaśnięcie, pozostałe dni, HWID + Kopiuj,
// „Zmień klucz” (to samo okno aktywacji co przy starcie). Dane z LicenseGate (GET /api/v1/license/status).
import { useState } from "react";
import { cls } from "../../util";
import { copyText, useLicense } from "../../license/LicenseGate";

export default function LicensePanel() {
  const { st, refresh, openActivation } = useLicense();
  const [msg, setMsg] = useState<string | null>(null);
  if (!st) return <p className="sys-note">Wczytywanie…</p>;
  if (!st.required) return <p className="sys-note" data-testid="license-panel">Wersja właściciela – licencja nie jest potrzebna.</p>;
  const days = st.days_left;
  return (
    <div className="sys-diag" data-testid="license-panel">
      <section><h4>LICENCJA</h4>
        <dl className="sys-kv">
          <dt>Stan</dt><dd><span className={cls("sys-st", st.valid ? (st.warn ? "warn" : "ok") : "bad")}>{st.valid ? "AKTYWNA" : "NIEWAŻNA"}</span>
            {!st.valid && <span className="sys-err"> {st.message}</span>}</dd>
          <dt>Użytkownik</dt><dd data-testid="license-user">{st.user ?? "—"}</dd>
          <dt>Typ</dt><dd>{st.perpetual ? "bezterminowa" : st.perpetual === false ? "czasowa" : "—"}</dd>
          <dt>Wygasa</dt><dd>{st.perpetual ? "nigdy" : st.exp_local ?? "—"}</dd>
          <dt>Pozostało</dt><dd data-testid="license-days">{st.perpetual ? "bez limitu" : days != null ? `${days} ${days === 1 ? "dzień" : "dni"}` : "—"}</dd>
          <dt>Przypisana do</dt><dd>{st.license_hwid ? <code className="lic-code">{st.license_hwid}</code> : st.valid ? "każdego komputera (bez HWID)" : "—"}</dd>
          <dt>Klucz</dt><dd><code className="lic-code">{st.key_masked ?? "—"}</code></dd>
          <dt>Czas sprawdzenia</dt><dd>{st.time_source === "internet" ? "z internetu" : st.time_source === "komputer" ? "zegar komputera (brak internetu)" : "—"}</dd>
        </dl>
        {st.warn && <p className="note warn" data-testid="license-warn">Licencja wygasa za {days} {days === 1 ? "dzień" : "dni"} ({st.exp_local}). Poproś wydawcę o nowy klucz i wklej go przyciskiem „Zmień klucz”.</p>}
      </section>
      <section><h4>HWID TEGO KOMPUTERA</h4>
        <div className="lic-keyrow"><code className="lic-mono" data-testid="license-panel-hwid">{st.hwid ?? "—"}</code>
          <button type="button" className="act" disabled={!st.hwid} onClick={async () => setMsg((await copyText(st.hwid || "")) ? "Skopiowano HWID." : "Nie udało się skopiować – zaznacz i Ctrl+C.")}>KOPIUJ</button></div>
        <p className="sys-note">Wyślij ten kod wydawcy, gdy prosisz o nowy klucz (np. przedłużenie albo inny komputer).</p>
      </section>
      <div className="lic-btns">
        <button type="button" className="act on" onClick={openActivation} data-testid="license-change">ZMIEŃ KLUCZ</button>
        <button type="button" className="act" onClick={async () => { await refresh(true); setMsg("Sprawdzono licencję."); }}>SPRAWDŹ PONOWNIE</button>
      </div>
      {msg && <p className="sys-note" role="status">{msg}</p>}
    </div>);
}
