// OWNER EDITION - License Manager: log in to the License API (server address + admin login; the password is forwarded once and not
// stored), dashboard counts, generate 24h / 72h / 7d / 31d keys (the full key is shown ONCE with a copy button - the server keeps only
// a hash), list / search, revoke, reset the device binding, audit log. Every action is authorized by the server, not by this page.
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { useStore } from "../../store";
import { cls, fmtTime } from "../../util";
import "./license.css";

const ST_PL: Record<string, string> = { CREATED: "utworzona", ACTIVE: "aktywna", EXPIRED: "wygasła", REVOKED: "cofnięta" };
const DUR = ["24h", "72h", "7d", "31d"];

export default function LicenseManager() {
  const { s } = useStore();
  const [srv, setSrv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [login, setLogin] = useState({ server_url: "", username: "", password: "" });
  const [stats, setStats] = useState<any>(null);
  const [list, setList] = useState<any>(null);
  const [filter, setFilter] = useState({ status: "", q: "" });
  const [dur, setDur] = useState("31d");
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [audit, setAudit] = useState<any[] | null>(null);
  const owner = s.license?.edition?.edition === "OWNER";

  const wrap = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setErr(null);
    try {
      return await fn();
    } catch (e: any) {
      setErr(String(e?.message || e));
      if (String(e?.message || "").startsWith("UNAUTHORIZED")) setSrv((x: any) => ({ ...(x || {}), logged_in: false }));
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

  useEffect(() => {
    if (!owner) return;
    apiGet("/api/v1/owner/license-server").then((x) => { setSrv(x); setLogin((l) => ({ ...l, server_url: x.server_url || "" })); }).catch((e) => setErr(String(e)));
  }, [owner]);
  useEffect(() => {
    if (srv?.logged_in) void wrap(reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srv?.logged_in, reload]);

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
  return (
    <main className="page lm-page" data-testid="page-licencje">
      <section className="panel lm-panel">
        <h2>License Manager <span className="lm-dim">OWNER EDITION · serwer licencji {srv?.server_url || "nie ustawiony"}</span></h2>
        {err && <p className="lm-err" role="alert" data-testid="lm-error">{err}</p>}
        {!srv?.logged_in ? (
          <form className="lm-login" data-testid="lm-login" onSubmit={async (e) => {
            e.preventDefault();
            const out = await wrap(() => apiSend("POST", "/api/v1/owner/license-server/login", login));
            if (out) { setSrv(out); setLogin((l) => ({ ...l, password: "" })); }
          }}>
            <label>Adres serwera licencji<input value={login.server_url} placeholder="https://licencje.twoja-domena.pl" data-testid="lm-url"
              onChange={(e) => setLogin({ ...login, server_url: e.target.value })} /></label>
            <label>Login administratora<input value={login.username} autoComplete="username" data-testid="lm-user"
              onChange={(e) => setLogin({ ...login, username: e.target.value })} /></label>
            <label>Hasło<input type="password" value={login.password} autoComplete="current-password" data-testid="lm-pass"
              onChange={(e) => setLogin({ ...login, password: e.target.value })} /></label>
            <button className="btn primary" disabled={busy || !login.server_url || !login.username || !login.password} data-testid="lm-login-btn">Zaloguj</button>
            <p className="lm-dim">Hasło jest przekazywane tylko do serwera licencji i nie jest zapisywane. Sesja trwa do wylogowania albo jej wygaśnięcia na serwerze.</p>
          </form>) : (
          <div className="lm-bar">
            <span>Zalogowano: <b>{srv.username}</b> · sesja do {fmtTime(srv.session_expires_at, true)}</span>
            <button className="btn" onClick={async () => setSrv(await apiSend("POST", "/api/v1/owner/license-server/logout"))}>Wyloguj</button>
          </div>)}
      </section>
      {srv?.logged_in && (<>
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
              {DUR.map((d) => (
                <button key={d} type="button" role="radio" aria-checked={dur === d} className={cls("btn", dur === d && "primary")} onClick={() => setDur(d)}
                  data-testid={`lm-dur-${d}`}>{srv.durations_pl?.[d] ?? d}</button>))}
            </div>
            <input placeholder="notatka (np. imię klienta)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} data-testid="lm-note" />
            <button className="btn primary" disabled={busy} data-testid="lm-create" onClick={async () => {
              const out = await wrap(() => apiSend("POST", "/api/v1/owner/licenses", { duration: dur, note: note || null }));
              if (out) { setCreated(out); setCopied(false); setNote(""); await wrap(reload); }
            }}>Generuj klucz</button>
          </div>
          {created && (
            <div className="lm-key" role="alert" data-testid="lm-new-key">
              <span>Klucz ({created.duration_pl}) – <b>pokazany tylko teraz</b>, serwer przechowuje wyłącznie jego skrót:</span>
              <code data-testid="lm-key-value">{created.license_key}</code>
              <button className="btn" onClick={async () => { try { await navigator.clipboard.writeText(created.license_key); setCopied(true); } catch { setCopied(false); } }}>
                {copied ? "Skopiowano" : "Kopiuj"}</button>
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
      </>)}
    </main>);
}
