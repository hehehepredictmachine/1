// Login, registration, activation and the limited "protection of existing positions" view shown when the product is locked.
// This screen is only presentation: the backend refuses every product API call without a valid license.
import { useEffect, useState } from "react";
import { apiSend } from "../api";
import { useStore } from "../store";
import { fmtNum, fmtTime } from "../util";

const ERR: Record<string, string> = {
  INVALID_CREDENTIALS: "Nieprawidłowy e-mail lub hasło.",
  EMAIL_NOT_VERIFIED: "Potwierdź najpierw adres e-mail (link w wiadomości).",
  ACCOUNT_BLOCKED: "Konto zablokowane – skontaktuj się z administratorem.",
  RATE_LIMITED: "Za dużo prób – odczekaj chwilę.",
  LICENSE_NOT_FOUND_FOR_ACCOUNT: "Ten klucz nie należy do Twojego konta albo jest błędny.",
  LICENSE_EXPIRED: "Ta licencja już wygasła – poproś administratora o nową.",
  LICENSE_REVOKED: "Licencja została cofnięta.",
  SEAT_IN_USE: "Licencja jest aktywna na innym komputerze. Administrator może zwolnić stanowisko (termin się nie wydłuży).",
  CENTRAL_UNREACHABLE: "Brak połączenia z serwerem kont MasterQUO.",
  CENTRAL_URL_NOT_CONFIGURED: "Ustaw adres serwera kont.",
  CENTRAL_URL_MUST_BE_HTTPS: "Adres serwera musi zaczynać się od https://",
  MFA_REQUIRED: "Konto administratora: podaj kod TOTP.",
  SERVER_CLOCK_ANOMALY: "Serwer wstrzymał wydawanie uprawnień (anomalia zegara).",
  PASSWORD_WEAK: "Hasło jest za słabe (min. 12 znaków).",
};
const err = (e: any) => ERR[String(e?.message)] ?? String(e?.message || e);

const REASON: Record<string, string> = {
  NO_LEASE_YET: "sprawdzanie licencji…",
  NOT_ACTIVATED_ON_THIS_COMPUTER: "licencja nie jest aktywna na tym komputerze",
  CENTRAL_URL_NOT_CONFIGURED: "nie ustawiono serwera kont",
  LICENSE_EXPIRED: "licencja wygasła (48 h od aktywacji minęło)",
  LICENSE_REVOKED: "licencja cofnięta przez administratora",
  NO_ACTIVE_ACTIVATION: "stanowisko zwolnione – aktywuj licencję ponownie",
  DEVICE_REVOKED: "to urządzenie zostało unieważnione",
  ACCOUNT_NOT_ACTIVE: "konto nieaktywne lub zablokowane",
  LEASE_EXPIRED_NO_FRESH_SERVER_CONFIRMATION: "brak potwierdzenia z serwera (sieć?) – uprawnienie wygasło",
  CLOCK_DISCONTINUITY_REVALIDATE_ONLINE: "wykryto skok zegara – wymagane ponowne sprawdzenie online",
};

export default function LicenseGate() {
  const { s, refresh } = useStore();
  const lic = s.license || {};
  if (!lic.configured) return <ServerForm />;
  if (!lic.logged_in) return <AuthForms />;
  return <Locked lic={lic} s={s} refresh={refresh} />;
}

function Box({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="gate"><div className="gate-card panel" data-testid="license-gate"><div className="panel-head"><span className="ptitle">{title}</span></div>
      <div className="gate-body">{children}</div></div></div>
  );
}

function ServerForm() {
  const { refresh } = useStore();
  const [url, setUrl] = useState("https://");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Box title="MasterQUO – serwer kont">
      <p>Podaj adres centralnego serwera kont i licencji (otrzymasz go od administratora).</p>
      <input value={url} onChange={(e) => setUrl(e.target.value)} name="central-url" style={{ width: "100%" }} />
      <button className="btn" onClick={() => apiSend("POST", "/api/v1/license/server", { url }).then(refresh).catch((e) => setMsg(err(e)))}>Zapisz</button>
      {msg && <div className="note bad">{msg}</div>}
    </Box>
  );
}

function AuthForms() {
  const { refresh } = useStore();
  const [tab, setTab] = useState<"login" | "register" | "forgot">("login");
  const [f, setF] = useState({ email: "", password: "", totp: "", name: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<any>, ok?: (r: any) => string) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      if (ok) setMsg(ok(r));
      await refresh();
    } catch (e) {
      setMsg(err(e));
    } finally {
      setBusy(false);
      setF((x) => ({ ...x, password: "" }));
    }
  };
  return (
    <Box title="MasterQUO – konto">
      <div className="tabs small">{(["login", "register", "forgot"] as const).map((t) =>
        <button key={t} className={tab === t ? "on" : ""} onClick={() => { setTab(t); setMsg(null); }}>{{ login: "Logowanie", register: "Rejestracja", forgot: "Nie pamiętam hasła" }[t]}</button>)}</div>
      <label className="field"><span>E-mail</span><input name="email" autoComplete="username" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
      {tab !== "forgot" && <label className="field"><span>Hasło</span><input name="password" type="password" autoComplete={tab === "login" ? "current-password" : "new-password"}
        value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>}
      {tab === "register" && <label className="field"><span>Nazwa (opcjonalnie)</span><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>}
      {tab === "login" && <label className="field"><span>Kod TOTP (tylko konto administratora)</span><input value={f.totp} onChange={(e) => setF({ ...f, totp: e.target.value })} /></label>}
      {tab === "login" && <button className="btn" disabled={busy} onClick={() => run(() => apiSend("POST", "/api/v1/license/login", { email: f.email, password: f.password, totp: f.totp || null }))}>Zaloguj</button>}
      {tab === "register" && <button className="btn" disabled={busy} onClick={() => run(() => apiSend("POST", "/api/v1/license/register", { email: f.email, password: f.password, display_name: f.name || null }),
        (r) => r.message)}>Załóż konto</button>}
      {tab === "forgot" && <button className="btn" disabled={busy} onClick={() => run(() => apiSend("POST", "/api/v1/license/forgot", { email: f.email }), (r) => r.message)}>Wyślij link</button>}
      {msg && <div className="note" data-testid="gate-msg">{msg}</div>}
      <small className="muted">Konto programu i rachunek MT5 to dwie różne rzeczy. Rejestracja nie daje licencji – licencję 48 h przypisuje administrator.</small>
    </Box>
  );
}

function Locked({ lic, s, refresh }: { lic: any; s: any; refresh: () => Promise<void> }) {
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const activate = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await apiSend("POST", "/api/v1/license/activate", { key });
      setKey("");
      await refresh();
    } catch (e) {
      setMsg(err(e));
    } finally {
      setBusy(false);
    }
  };
  const L = lic.license;
  const positions = s.positions?.positions || [];
  const paper = (s.managed || []).filter((m: any) => m.mode === "PAPER");
  return (
    <Box title={`MasterQUO – ${lic.user?.email ?? ""}`}>
      <div className="note warn" data-testid="lock-reason">Funkcje bota są zablokowane: <b>{REASON[lic.reason] ?? lic.reason ?? "brak ważnej licencji"}</b>.
        {L?.expires_at ? <> Licencja {L.key_hint} {L.status === "EXPIRED" ? "wygasła" : "ważna do"} {fmtTime(new Date(L.expires_at * 1000).toISOString(), true)} (czas serwera).</> : null}</div>
      {lic.activated_here && !lic.owner_matches_user && <div className="note bad">Ta instalacja jest aktywowana na inne konto. Zaloguj się na nie albo aktywuj własną licencję.</div>}
      <label className="field"><span>Klucz licencji (MQL1-…)</span>
        <input name="license-key" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} /></label>
      <button className="btn" disabled={busy || key.length < 20} onClick={activate}>Aktywuj licencję</button>
      {msg && <div className="note bad" data-testid="gate-msg">{msg}</div>}
      <small className="muted">48 godzin liczy się od pierwszej aktywacji według czasu serwera – także gdy program jest wyłączony lub jest weekend.
        Ponowna aktywacja na tym samym komputerze nie wydłuża terminu. Aktywacja wymaga internetu.</small>
      <h4>Podłączenie terminala</h4>
      <ol className="small">
        <li>Uruchom MetaTrader 5 i zaloguj się na wybrany rachunek (MasterQUO nie potrzebuje hasła brokera).</li>
        <li>Status terminala: <b>{s.connection?.state ?? "?"}</b>{s.account ? ` · rachunek ${s.account.login} ${s.account.server} (${s.account.trade_mode})` : ""}</li>
        <li>Po aktywacji możesz w pasku konta włączyć przesyłanie danych tego rachunku do serwera MasterQUO (opcjonalne, za Twoją zgodą).</li>
      </ol>
      <h4>Ochrona istniejących pozycji bota</h4>
      <p className="small muted">Bez licencji nie powstają nowe analizy ani wejścia. Pozycje otwarte wcześniej przez bota zachowują SL/TP po stronie brokera
        i dotychczasową obsługę ochronną (TP1, przesunięcie SL na BE). Możesz je zamknąć ręcznie.</p>
      <table className="tbl small"><thead><tr><th>Ticket</th><th>Strona</th><th>Lot</th><th>Otwarcie</th><th>SL</th><th>TP</th><th>P/L</th></tr></thead>
        <tbody>{positions.map((p: any) => <tr key={p.ticket}><td>{p.ticket}</td><td>{p.side}</td><td>{p.volume}</td><td>{fmtNum(p.price_open)}</td><td>{fmtNum(p.sl)}</td><td>{fmtNum(p.tp)}</td><td>{fmtNum(p.profit)}</td></tr>)}
          {paper.map((m: any) => <tr key={m.position_key}><td>PAPER</td><td>{m.side}</td><td>{m.volume_open}</td><td>{fmtNum(m.entry_price)}</td><td>{fmtNum(m.sl)}</td><td>{fmtNum(m.tp2)}</td><td>—</td></tr>)}
          {!positions.length && !paper.length && <tr><td colSpan={7} className="muted">Brak otwartych pozycji bota.</td></tr>}</tbody></table>
      {(positions.length > 0 || paper.length > 0) && <button className="btn danger" onClick={() => window.confirm("Zamknąć wszystkie pozycje bota?") &&
        apiSend("POST", "/api/v1/positions/close", { scope: "BOT", confirm: "ZAMKNIJ" }).then(refresh).catch((e) => setMsg(err(e)))}>Zamknij pozycje bota</button>}
      <div className="row end">
        <button className="btn ghost" onClick={() => apiSend("POST", "/api/v1/license/refresh").then(refresh).catch(() => undefined)}>Sprawdź ponownie</button>
        <button className="btn ghost" onClick={() => apiSend("POST", "/api/v1/license/logout").catch(() => undefined).finally(() => window.location.reload())}>Wyloguj</button>
      </div>
    </Box>
  );
}

/** Compact bar above the monitor: account, license, remaining time, connected account, connection. */
export function LicenseBar() {
  const { s, refresh } = useStore();
  const lic = s.license || {};
  const con = s.connector || lic.connector || {};
  const [now, setNow] = useState(Date.now());
  const [warn, setWarn] = useState<string | null>(null);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (s.licenseWarning) setWarn(`Licencja wygaśnie za około ${s.licenseWarning.minutes} min. Po tym czasie nowe wejścia i analizy zostaną zatrzymane.`);
  }, [s.licenseWarning?.minutes, s.licenseWarning?.license_id]);
  const L = lic.license;
  // countdown is only a visualisation: the backend decides with the server clock
  const left = L?.expires_at ? Math.max(0, Math.round(L.expires_at - (now / 1000 + (lic.server_offset_s ?? 0)))) : null;
  const h = left === null ? null : `${Math.floor(left / 3600)} h ${Math.floor((left % 3600) / 60)} min`;
  const toggle = async (on: boolean) => {
    if (on && !window.confirm(con.disclosure + "\n\nWłączyć przesyłanie danych rachunku " + (s.account ? `${s.account.login} (${s.account.server})` : "") + "?")) return;
    await apiSend("POST", "/api/v1/license/connector", { enabled: on }).catch(() => undefined);
    await refresh();
  };
  return (
    <div className="license-bar" data-testid="license-bar">
      <span>Konto: <b>{lic.user?.email ?? "—"}</b></span>
      <span>Licencja: <b className={L?.status === "ACTIVE" ? "pos" : "neg"}>{L?.status ?? "—"}</b> {L?.key_hint ?? ""}</span>
      <span>Pozostało: <b>{h ?? "—"}</b> (do {L?.expires_at ? new Date(L.expires_at * 1000).toLocaleString("pl-PL") : "—"})</span>
      <span>Rachunek: <b>{s.account ? `${s.account.login} · ${s.account.server}` : "brak"}</b></span>
      <span>Serwer kont: <b className={lic.online ? "pos" : "neg"}>{lic.online ? "połączony" : "brak połączenia"}</b></span>
      <span>Dane do serwera: <b>{con.enabled ? con.status : "wyłączone"}</b>
        <button className="btn tiny ghost" onClick={() => toggle(!con.enabled)}>{con.enabled ? "Wyłącz" : "Włącz…"}</button></span>
      <span className="spacer" />
      <button className="btn tiny ghost" onClick={() => apiSend("POST", "/api/v1/license/logout").catch(() => undefined).finally(() => window.location.reload())}>Wyloguj</button>
      {warn && <div className="note warn license-warn" role="alert">{warn} <button className="btn tiny" onClick={() => setWarn(null)}>OK</button></div>}
    </div>
  );
}
