// OWNER EDITION - License Manager (1.29: no login screen). The backend signs every admin request with this computer's device key; the
// server trusts it after a one-time pairing done in the server's shell. Dashboard counts, 72h / 7d / 31d keys (24h under "zaawansowane";
// the full key is shown ONCE with a copy button - the server keeps only a hash), list / search, revoke, device reset, audit log,
// device keys + rotation. Every action is authorized by the server, not by this page.
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { useStore } from "../../store";
import { cls, fmtTime } from "../../util";
import "./license.css";

const ST_PL: Record<string, string> = { CREATED: "utworzona", ACTIVE: "aktywna", EXPIRED: "wygasła", REVOKED: "cofnięta" };

export default function LicenseManager() {
  const { s } = useStore();
  const [srv, setSrv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [stats, setStats] = useState<any>(null);
  const [list, setList] = useState<any>(null);
  const [filter, setFilter] = useState({ status: "", q: "" });
  const [dur, setDur] = useState("31d");
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<any>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [audit, setAudit] = useState<any[] | null>(null);
  const [keys, setKeys] = useState<any[] | null>(null);
  const owner = s.license?.edition?.edition === "OWNER";
  const paired = srv?.paired === true;

  const wrap = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setErr(null);
    try {
      return await fn();
    } catch (e: any) {
      setErr(String(e?.message || e));
      if (String(e?.message || "").startsWith("UNAUTHORIZED")) setSrv((x: any) => ({ ...(x || {}), paired: false }));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const reload = useCallback(async () => {
    const qs = new URLSearchParams(Object.entries(filter).filter(([, v]) => v)).toString();
    const [st, ls] = await Promise.all([apiGet("/api/v1/owner/stats"), apiGet(`/api/v1/owner/licenses?limit=200&${qs}`)]);
    setStats(st);
    setList(ls);
  }, [filter]);
  const copy = async (text: string, what: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(what); } catch { setCopied(null); }
  };

  useEffect(() => {
    if (!owner) return;
    // no login: the page asks the backend to check the device key against the server (signed whoami)
    apiSend("POST", "/api/v1/owner/license-server/check").then((x) => { setSrv(x); setUrl(x.server_url || ""); }).catch((e) => setErr(String(e)));
  }, [owner]);
  useEffect(() => {
    if (paired) void wrap(reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paired, reload]);

  if (!owner) {
    return (
      <main className="page lm-page" data-testid="page-licencje">
        <section className="panel lm-panel"><h2>License Manager</h2>
          <p>To jest <b>CLIENT EDITION</b> – zarządzanie licencjami jest dostępne tylko w OWNER EDITION. Status tej instalacji: {s.license?.status_pl ?? "—"}.</p>
        </section>
      </main>);
  }
  const act = async (path: string, label: string, id: string) => {
    const reason = window.prompt(`${label} – licencja ${id}. Powód (opcjonalnie):`, "");
    if (reason === null) return;
    const ok = await wrap(() => apiSend("POST", path, { reason: reason || null }));
    if (ok) await wrap(reload);
  };
  const rotate = async (action: string) => {
    const out = await wrap(() => apiSend("POST", "/api/v1/owner/license-server/rotate", { action }));
    if (out) setSrv(out);
  };
  const durations: string[] = srv?.durations || ["72h", "7d", "31d"];
  const advanced: string[] = srv?.durations_advanced || ["24h"];
  return (
    <main className="page lm-page" data-testid="page-licencje">
      <section className="panel lm-panel" data-testid="lm-connection" data-paired={paired ? "1" : "0"}>
        <h2>License Manager <span className="lm-dim">OWNER EDITION · bez logowania – żądania podpisuje klucz tego komputera</span></h2>
        {err && <p className="lm-err" role="alert" data-testid="lm-error">{err}</p>}
        <form className="lm-login" onSubmit={async (e) => {
          e.preventDefault();
          const out = await wrap(() => apiSend("POST", "/api/v1/owner/license-server", { server_url: url }));
          if (out) setSrv(out);
        }}>
          <label>Adres serwera licencji<input value={url} placeholder="https://licencje.twoja-domena.pl" data-testid="lm-url"
            onChange={(e) => setUrl(e.target.value)} /></label>
          <button className="btn primary" disabled={busy || !url} data-testid="lm-save-url">Zapisz i sprawdź</button>
          <button type="button" className="btn" disabled={busy || !srv?.server_url} data-testid="lm-check"
            onClick={async () => { const out = await wrap(() => apiSend("POST", "/api/v1/owner/license-server/check")); if (out) setSrv(out); }}>Sprawdź połączenie</button>
        </form>
        <p className={cls("lm-state", paired ? "ok" : srv?.paired === false ? "warn" : "bad")} data-testid="lm-state">
          {paired ? <>Połączono – serwer ufa temu komputerowi (klucz <code>{srv.device?.kid}</code>{srv.server_version ? `, serwer ${srv.server_version}` : ""}).</>
            : srv?.paired === false ? <>Ten komputer nie jest jeszcze sparowany z serwerem.</>
              : <>Brak połączenia z serwerem licencji{srv?.reason ? ` – ${srv.reason}` : ""}.</>}
          {srv?.checked_at && <span className="lm-dim"> · sprawdzono {fmtTime(srv.checked_at, true)}</span>}
          {srv?.clock_offset_s ? <span className="lm-dim"> · korekta zegara {srv.clock_offset_s} s</span> : null}</p>
        {srv && srv.paired === false && (
          <div className="lm-pair" data-testid="lm-pair">
            <b>Jednorazowe parowanie (bez hasła):</b>
            <ol>
              <li>Zaloguj się do powłoki SWOJEGO serwera licencji (SSH) – tam, gdzie działa usługa.</li>
              <li>W folderze usługi uruchom polecenie (zawiera tylko klucz PUBLICZNY tego komputera):</li>
            </ol>
            <code className="lm-cmd" data-testid="lm-pair-cmd">{srv.pairing_command}</code>
            <div className="lm-bar">
              <button className="btn" onClick={() => void copy(srv.pairing_command, "pair")}>{copied === "pair" ? "Skopiowano" : "Kopiuj polecenie"}</button>
              <button className="btn primary" disabled={busy} data-testid="lm-pair-check"
                onClick={async () => { const out = await wrap(() => apiSend("POST", "/api/v1/owner/license-server/check")); if (out) setSrv(out); }}>Sprawdź parowanie</button>
            </div>
            <p className="lm-dim">Klucz prywatny zostaje na tym komputerze (Windows: DPAPI bieżącego użytkownika). Po sparowaniu ta strona działa od razu, także po
              restarcie – bez logowania. Klient nigdy nie dostaje tego klucza ani tej zakładki.</p>
          </div>)}
      </section>
      {paired && (<>
        <section className="panel lm-panel" data-testid="lm-stats">
          <h2>Licencje</h2>
          <div className="lm-counts">
            {["CREATED", "ACTIVE", "EXPIRED", "REVOKED"].map((k) => (
              <div key={k} className={cls("lm-count", k.toLowerCase())}><b>{stats?.by_status?.[k] ?? "—"}</b><span>{ST_PL[k]}</span></div>))}
            <div className="lm-count"><b>{stats?.total ?? "—"}</b><span>razem</span></div>
          </div>
        </section>
        <section className="panel lm-panel" data-testid="lm-generate">
          <h2>Nowy klucz</h2>
          <div className="lm-gen">
            <div className="lm-durs" role="radiogroup" aria-label="Okres licencji">
              {durations.map((d) => (
                <button key={d} type="button" role="radio" aria-checked={dur === d} className={cls("btn", dur === d && "primary")} onClick={() => setDur(d)}
                  data-testid={`lm-dur-${d}`}>{srv.durations_pl?.[d] ?? d}</button>))}
            </div>
            <details className="lm-adv"><summary>zaawansowane</summary>
              {advanced.map((d) => (
                <button key={d} type="button" role="radio" aria-checked={dur === d} className={cls("btn", dur === d && "primary")} onClick={() => setDur(d)}
                  data-testid={`lm-dur-${d}`}>{srv.durations_pl?.[d] ?? d}</button>))}
            </details>
            <input placeholder="notatka (np. imię klienta)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} data-testid="lm-note" />
            <button className="btn primary" disabled={busy} data-testid="lm-create" onClick={async () => {
              const out = await wrap(() => apiSend("POST", "/api/v1/owner/licenses", { duration: dur, note: note || null }));
              if (out) { setCreated(out); setCopied(null); setNote(""); await wrap(reload); }
            }}>Generuj klucz</button>
          </div>
          {created && (
            <div className="lm-key" role="alert" data-testid="lm-new-key">
              <span>Klucz ({created.duration_pl}) – <b>pokazany tylko teraz</b>, serwer przechowuje wyłącznie jego skrót:</span>
              <code data-testid="lm-key-value">{created.license_key}</code>
              <button className="btn" onClick={() => void copy(created.license_key, "key")}>{copied === "key" ? "Skopiowano" : "Kopiuj"}</button>
              <button className="btn" onClick={() => setCreated(null)}>Zamknij (klucz zniknie)</button>
            </div>)}
        </section>
        <section className="panel lm-panel" data-testid="lm-list">
          <h2>Lista</h2>
          <div className="lm-filters">
            <select value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })} aria-label="Status">
              <option value="">wszystkie</option>{Object.entries(ST_PL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input placeholder="szukaj: id, końcówka klucza, notatka" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} />
          </div>
          <div className="lm-table-wrap">
            <table className="lm-table">
              <thead><tr><th>ID</th><th>Klucz</th><th>Okres</th><th>Status</th><th>Utworzona</th><th>Aktywowana</th><th>Wygasa</th><th>Urządzenie</th><th>Notatka</th><th /></tr></thead>
              <tbody>{(list?.items || []).map((l: any) => (
                <tr key={l.license_id} data-testid="lm-row" data-status={l.status}>
                  <td><code>{l.license_id}</code></td><td>{l.key_hint}</td><td>{l.duration}</td>
                  <td><span className={cls("lm-st", l.status.toLowerCase())}>{ST_PL[l.status] ?? l.status}</span></td>
                  <td>{fmtTime(l.created_at, true)}</td><td>{l.activated_at ? fmtTime(l.activated_at, true) : "—"}</td>
                  <td>{l.expires_at ? fmtTime(l.expires_at, true) : "od aktywacji"}</td><td>{l.device_bound ? "przypisane" : "—"}</td>
                  <td>{l.note ?? ""}</td>
                  <td className="lm-actions">
                    {l.status !== "REVOKED" && <button className="btn" onClick={() => act(`/api/v1/owner/licenses/${l.license_id}/revoke`, "Cofnięcie", l.license_id)}>Cofnij</button>}
                    {l.device_bound && <button className="btn" onClick={() => act(`/api/v1/owner/licenses/${l.license_id}/reset-device`, "Reset urządzenia", l.license_id)}>Reset HWID</button>}
                  </td>
                </tr>))}</tbody>
            </table>
            {list && !list.items?.length && <p className="lm-dim">Brak licencji w tym filtrze.</p>}
          </div>
        </section>
        <section className="panel lm-panel">
          <h2>Dziennik audytu <button className="btn" onClick={async () => { const a = await wrap(() => apiGet("/api/v1/owner/audit?limit=100")); if (a) setAudit((a as any).items); }}>Pokaż</button></h2>
          {audit && (
            <ul className="lm-audit">{audit.map((a, i) => (
              <li key={i} className={cls(!a.ok && "bad")}>{fmtTime(a.ts, true)} · {a.actor} · {a.action}{a.license_id ? ` · ${a.license_id}` : ""}</li>))}</ul>)}
        </section>
        <section className="panel lm-panel" data-testid="lm-keys">
          <h2>Klucze urządzeń OWNER <button className="btn" onClick={async () => { const k = await wrap(() => apiGet("/api/v1/owner/admin-keys")); if (k) setKeys((k as any).items); }}>Pokaż</button></h2>
          <p className="lm-dim">Ten komputer: <code>{srv.device?.kid}</code> ({srv.label}). Nowy komputer albo podejrzenie wycieku: rotacja – nowy klucz parujesz na serwerze,
            stary zostaje odwołany. Zgubiony komputer: na serwerze <code>python -m pmw_license admin-keys revoke &lt;kid&gt;</code>.</p>
          {keys && (
            <ul className="lm-audit">{keys.map((k) => (
              <li key={k.kid} className={cls(k.revoked_at && "bad")}>{k.kid} · {k.label || "—"} · dodany {fmtTime(k.created_at, true)}
                {k.revoked_at ? ` · odwołany ${fmtTime(k.revoked_at, true)}` : " · zaufany"}{k.kid === srv.device?.kid ? " · ten komputer" : ""}</li>))}</ul>)}
          {!srv.rotation ? <button className="btn" disabled={busy} onClick={() => void rotate("begin")} data-testid="lm-rotate-begin">Rozpocznij rotację klucza</button> : (
            <div className="lm-pair">
              <b>Nowy klucz oczekuje na sparowanie:</b> <code className="lm-cmd">{srv.rotation.pairing_command}</code>
              <div className="lm-bar">
                <button className="btn" onClick={() => void copy(srv.rotation.pairing_command, "rot")}>{copied === "rot" ? "Skopiowano" : "Kopiuj polecenie"}</button>
                <button className="btn primary" disabled={busy} onClick={() => void rotate("commit")} data-testid="lm-rotate-commit">Zakończ rotację</button>
                <button className="btn" disabled={busy} onClick={() => void rotate("cancel")}>Anuluj</button>
              </div>
            </div>)}
        </section>
      </>)}
    </main>);
}
