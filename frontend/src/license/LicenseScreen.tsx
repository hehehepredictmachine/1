// Ekran aktywacji licencji (1.44.0) – pierwszy ekran wersji klienta bez ważnej licencji (przed intro i menu) oraz okno „Zmień klucz”
// z panelu LICENCJA. HWID tego komputera + Kopiuj (klient wysyła go wydawcy), klucz + Wklej + Aktywuj. Komunikaty po polsku z backendu
// (licensing.gate / license_key): zły format / podpis, wygasła (z datą), inny komputer, błąd / cofnięcie zegara.
import { useEffect, useRef, useState } from "react";
import { apiSend } from "../api";
import { cls } from "../util";
import { copyText, type LicStatus } from "./LicenseGate";

const TONE: Record<string, string> = { OK: "ok", NO_LICENSE: "", FORMAT: "bad", SIGNATURE: "bad", VERSION: "bad", EXPIRED: "bad", HWID: "bad",
  CLOCK_ROLLBACK: "bad", CLOCK_ERROR: "bad", HWID_ERROR: "bad", NO_PUBLIC_KEY: "bad", NO_CRYPTO: "bad" };
const CONFIG_ERR = ["NO_PUBLIC_KEY", "NO_CRYPTO"];

export default function LicenseScreen({ status, modal = false, onClose, onActivated }:
  { status: LicStatus; modal?: boolean; onClose?(): void; onActivated(st: LicStatus): void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ tone: string; text: string } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const keyRef = useRef<HTMLTextAreaElement>(null);
  const done = useRef<number>(0);
  useEffect(() => { keyRef.current?.focus(); return () => window.clearTimeout(done.current); }, []);
  // komunikat startowy: dlaczego klucz zapisany na tym komputerze nie działa (wygasł / inny komputer / zegar)
  const startMsg = !modal && status.code !== "NO_LICENSE" ? { tone: TONE[status.code] ?? "bad", text: status.message } : null;
  const shown = res ?? startMsg;
  const blocked = CONFIG_ERR.includes(status.code);

  const paste = async () => {
    try { const t = await navigator.clipboard.readText(); setKey(t.trim()); setRes(null); }
    catch { keyRef.current?.focus(); setRes({ tone: "", text: "Schowek niedostępny – kliknij w pole klucza i naciśnij Ctrl+V." }); }
  };
  const activate = async () => {
    const k = key.replace(/\s+/g, "");
    if (!k) { setRes({ tone: "bad", text: "Wklej klucz licencyjny (zaczyna się od „PMW1-”)." }); keyRef.current?.focus(); return; }
    setBusy(true);
    try {
      const st = await apiSend<LicStatus>("POST", "/api/v1/license/activate", { key: k });
      if (st.valid && st.activated) {
        setRes({ tone: "ok", text: "Licencja aktywna" + (st.user ? ` · ${st.user}` : "") + (st.perpetual ? " · bezterminowa" : st.exp_local ? ` · do ${st.exp_local}` : "") });
        done.current = window.setTimeout(() => onActivated(st), 1400);
      } else setRes({ tone: TONE[st.code] ?? "bad", text: st.message });
    } catch (e: any) { setRes({ tone: "bad", text: String(e?.message || e) }); }
    finally { setBusy(false); }
  };
  const copyHwid = async () => { setCopied((await copyText(status.hwid || "")) ? "Skopiowano HWID." : "Nie udało się skopiować – zaznacz kod i Ctrl+C."); };

  return (
    <div className={cls("lic-screen", modal && "modal")} role="dialog" aria-modal="true" aria-label="Aktywacja licencji Apollo23" data-testid="license-screen">
      <div className="lic-scene" aria-hidden="true" />
      <section className="lic-card">
        <i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
        <header className="lic-brand"><span className="lic-logo">APOLLO23</span><span className="lic-sub">{modal ? "ZMIANA KLUCZA LICENCJI" : "AKTYWACJA LICENCJI"}</span></header>

        <div className="lic-blk">
          <span className="lic-lbl">TWÓJ HWID</span>
          <div className="lic-row"><code className="lic-hwid" data-testid="license-hwid">{status.hwid || "—"}</code>
            <button type="button" className="lic-btn" onClick={copyHwid} disabled={!status.hwid} data-testid="license-copy-hwid">KOPIUJ</button></div>
          <small className="lic-help">{copied ?? "Wyślij ten kod wydawcy programu – na jego podstawie otrzymasz klucz dla tego komputera."}</small>
        </div>

        <div className="lic-blk">
          <label className="lic-lbl" htmlFor="lic-key">KLUCZ LICENCYJNY</label>
          <textarea id="lic-key" ref={keyRef} className="lic-key" rows={3} spellCheck={false} placeholder="PMW1-…" value={key} disabled={blocked}
            onChange={(e) => { setKey(e.target.value); setRes(null); }} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void activate(); } }}
            data-testid="license-key" />
          <div className="lic-row end">
            <button type="button" className="lic-btn" onClick={paste} disabled={blocked || busy}>WKLEJ</button>
            <button type="button" className="lic-btn primary" onClick={activate} disabled={blocked || busy} data-testid="license-activate">{busy ? "SPRAWDZANIE…" : "AKTYWUJ"}</button>
          </div>
        </div>

        {shown && <p className={cls("lic-msg", shown.tone)} role={shown.tone === "bad" ? "alert" : "status"} data-testid="license-msg">{shown.text}</p>}
        {modal && <button type="button" className="lic-btn ghost" onClick={onClose}>ANULUJ – ZOSTAW OBECNY KLUCZ</button>}
        <small className="lic-foot">Licencja działa offline – klucz zostaje zapisany na tym komputerze. Bez ważnej licencji tryby FOREX, CRYPTO i handel nie startują.</small>
      </section>
    </div>);
}
