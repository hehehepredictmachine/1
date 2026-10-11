import { useEffect, useState } from "react";

// License of this run (pasted at masterquo_start). The monitor only shows the state - it never sees the key or token.
type Lic = { state: string; ok: boolean; reason?: string | null; message?: string | null; hint?: string; license_seconds_left?: number | null;
  lease_seconds_left?: number; license_expires_at?: number | null };

const fmt = (s: number) => `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;

export function useLicense(): Lic | null {
  const [lic, setLic] = useState<Lic | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => fetch("/api/v1/license", { credentials: "same-origin" }).then((r) => r.json()).then((j) => alive && setLic(j)).catch(() => undefined);
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return lic;
}

export function LicenseBadge({ lic }: { lic: Lic | null }) {
  if (!lic || !lic.ok) return null;
  const left = lic.license_seconds_left ?? 0;
  return <span className={"lic-badge" + (left < 6 * 3600 ? " warn" : "")} data-testid="license-badge"
    title="Licencja tego uruchomienia (czas wg zegara serwera licencji). Po wygaśnięciu: brak nowych sygnałów, analizy i zleceń; otwarte pozycje zostają z SL/TP.">
    Licencja: {fmt(left)}</span>;
}

export function LicenseBlocker({ lic }: { lic: Lic | null }) {
  if (!lic || lic.ok) return null;
  return (
    <div className="lic-block" data-testid="license-blocked">
      <div className="lic-card">
        <h2>Licencja nieaktywna</h2>
        <p><b>{lic.message || lic.reason || lic.state}</b></p>
        <p>{lic.hint || "Uruchom ponownie masterquo_start i wklej ważną licencję."}</p>
        <p className="muted">Nowe sygnały, analiza, agent AI, ML i nowe zlecenia są zablokowane. Otwarte pozycje NIE są zamykane, ich SL/TP pozostają na serwerze brokera.</p>
      </div>
    </div>
  );
}
