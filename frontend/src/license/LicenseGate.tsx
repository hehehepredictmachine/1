// LICENCJA wersji klienta (1.44.0). LicenseGate stoi PRZED Store, intro i menu (main.tsx): w wersji klienta bez ważnej licencji pokazuje
// wyłącznie ekran aktywacji (backend i tak blokuje resztę API kodem 402 i nie uruchamia silnika). Wersja właściciela: przepuszcza od razu.
// GET /api/v1/license/status (co 5 min i po każdym 402), POST /api/v1/license/activate, POST /api/v1/license/require (przed trybem FOREX).
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { apiGet, apiSend, initSession } from "../api";
import LicenseScreen from "./LicenseScreen";
import "./license.css";

export type LicStatus = {
  edition: "OWNER" | "CLIENT"; required: boolean; valid: boolean; code: string; message: string; hwid?: string | null;
  user?: string | null; license_hwid?: string | null; perpetual?: boolean | null; iat_iso?: string | null; exp_iso?: string | null;
  exp_local?: string | null; days_left?: number | null; warn?: boolean; time_source?: string | null; key_masked?: string | null; activated?: boolean;
};
type Ctx = { st: LicStatus | null; refresh(force?: boolean): Promise<LicStatus | null>; openActivation(): void };
export const LicenseCtx = createContext<Ctx>({ st: null, refresh: async () => null, openActivation: () => undefined });
export const useLicense = () => useContext(LicenseCtx);

/** Centralna kontrola przed uruchomieniem trybu (backend: licensing.gate.require). false = brak licencji – brama pokaże ekran aktywacji. */
export async function requireLicense(action: string): Promise<boolean> {
  try { await apiSend("POST", "/api/v1/license/require", { action }); return true; }
  catch (e: any) { return e?.status !== 402; }                      // 402 -> zdarzenie pmw-license-required (api.ts); inny błąd nie blokuje
}

export async function copyText(t: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(t); return true; } catch { /* WebView2 bez uprawnień – zapas niżej */ }
  try {
    const ta = document.createElement("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta);
    ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok;
  } catch { return false; }
}

export default function LicenseGate({ children }: { children: ReactNode }) {
  const [st, setSt] = useState<LicStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [modal, setModal] = useState(false);
  const refresh = useCallback(async (force = false) => {
    try {
      await initSession();
      const x = await apiGet<LicStatus>("/api/v1/license/status" + (force ? "?refresh=1" : ""));
      setSt(x); setErr(null); return x;
    } catch (e: any) { setErr(String(e?.message || e)); return null; }
  }, []);
  useEffect(() => {
    void refresh(true);
    const t = window.setInterval(() => void refresh(), 5 * 60 * 1000);
    const lost = () => void refresh(true);
    window.addEventListener("pmw-license-required", lost);
    return () => { window.clearInterval(t); window.removeEventListener("pmw-license-required", lost); };
  }, [refresh]);

  if (!st) return <div className="pmw-loading" role="status">{err ? `APOLLO23 · brak połączenia z lokalnym backendem (${err})` : "PEPEMARKETWIZARD · sprawdzanie licencji…"}</div>;
  if (st.required && !st.valid) return <LicenseScreen status={st} onActivated={(x) => setSt(x)} />;
  return (
    <LicenseCtx.Provider value={{ st, refresh, openActivation: () => setModal(true) }}>
      {children}
      {modal && <LicenseScreen status={st} modal onClose={() => setModal(false)} onActivated={(x) => { setSt(x); setModal(false); }} />}
    </LicenseCtx.Provider>);
}
