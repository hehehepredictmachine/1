import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, errText, fmtAge, fmtLeft, fmtMoney, fmtMs, fmtTime, setCsrf } from "./api";
import "./styles.css";

type Me = { id: string; email: string; role: string };

function Login({ onDone }: { onDone: (u: Me) => void }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"pw" | "mfa">("pw");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (step === "pw") {
        const r = await api("POST", "/api/v1/auth/login", { email, password: pw, client: "web" });
        setPw("");
        setCsrf(r.csrf);
        if (r.mfa_required) setStep("mfa");
        else if (r.user.role !== "ADMIN") setErr("To konto nie ma roli administratora.");
        else onDone(r.user);
      } else {
        const r = await api("POST", "/api/v1/auth/mfa", { code });
        setCsrf(r.csrf);
        onDone(r.user);
      }
    } catch (x) {
      setErr(errText(x));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="center">
      <form className="card" onSubmit={submit} aria-label="Logowanie administratora">
        <h2 style={{ margin: 0 }}>MasterQUO License Manager</h2>
        {step === "pw" ? (
          <>
            <label className="f">E-mail<input name="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
            <label className="f">Hasło<input name="password" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
          </>
        ) : (
          <label className="f">Kod z aplikacji TOTP albo kod odzyskiwania
            <input name="mfa" autoComplete="one-time-code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} autoFocus required /></label>
        )}
        {err && <div className="err">{err}</div>}
        <button className="primary" disabled={busy}>{step === "pw" ? "Zaloguj" : "Potwierdź kod"}</button>
        <span className="muted small">Panel służy do licencji i podglądu statystyk. Nie składa zleceń na rachunkach klientów.</span>
      </form>
    </div>
  );
}

const LIC_BADGE: Record<string, string> = { ACTIVE: "ok", ISSUED: "warn", EXPIRED: "bad", REVOKED: "bad" };

function KeyModal({ data, onClose }: { data: any; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="modal-bg">
      <div className="modal" role="dialog" aria-label="Nowa licencja">
        <h3>Licencja 48h wygenerowana</h3>
        <p>Dla: <b>{data.email}</b> · identyfikator <code>{data.license.key_hint}</code></p>
        <div className="keybox" data-testid="license-key">{data.key}</div>
        <div className="note warn" style={{ marginTop: 10 }}>{data.warning} Przekaż klucz użytkownikowi bezpiecznym kanałem. 48 godzin liczy się od pierwszej aktywacji.</div>
        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={() => navigator.clipboard?.writeText(data.key).then(() => setCopied(true)).catch(() => setCopied(false))}>
            {copied ? "Skopiowano ✓" : "Kopiuj klucz"}</button>
          <span className="spacer" />
          <button className="primary" onClick={onClose}>Zamknij (klucz nie będzie już widoczny)</button>
        </div>
      </div>
    </div>
  );
}

function GenerateLicense({ preset, onDone }: { preset?: { id: string; email: string }; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<any[]>([]);
  const [uid, setUid] = useState(preset?.id ?? "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  useEffect(() => {
    if (!open || preset) return;
    api("GET", `/api/v1/admin/users?size=50&q=${encodeURIComponent(q)}`).then((r) => setUsers(r.items)).catch(() => undefined);
  }, [open, q, preset]);
  const go = async () => {
    setErr(null);
    try {
      const r = await api("POST", "/api/v1/admin/licenses", { user_id: uid, note: note || null });
      const email = preset?.email ?? users.find((u) => u.user.id === uid)?.user.email;
      setResult({ ...r, email });
      setOpen(false);
      setNote("");
    } catch (x) {
      setErr(errText(x));
    }
  };
  return (
    <>
      <button className="primary" onClick={() => setOpen(true)}>Wygeneruj licencję 48h</button>
      {open && (
        <div className="modal-bg">
          <div className="modal" role="dialog" aria-label="Generowanie licencji">
            <h3>Wygeneruj licencję 48h</h3>
            {preset ? <p>Konto: <b>{preset.email}</b></p> : (
              <>
                <label className="f">Szukaj konta<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e-mail" /></label>
                <label className="f">Konto użytkownika
                  <select value={uid} onChange={(e) => setUid(e.target.value)} name="user">
                    <option value="">— wybierz —</option>
                    {users.map((u) => <option key={u.user.id} value={u.user.id}>{u.user.email} ({u.user.status})</option>)}
                  </select></label>
              </>
            )}
            <label className="f">Notatka (opcjonalna)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} name="note" /></label>
            <p className="muted small">Typ STD_48H: dokładnie 48 godzin od pierwszej aktywacji (czas serwera). Utworzenie i przypisanie nie uruchamiają odliczania.</p>
            {err && <div className="err">{err}</div>}
            <div className="row"><span className="spacer" /><button onClick={() => setOpen(false)}>Anuluj</button>
              <button className="primary" disabled={!uid} onClick={go}>Utwórz licencję</button></div>
          </div>
        </div>
      )}
      {result && <KeyModal data={result} onClose={() => { setResult(null); onDone(); }} />}
    </>
  );
}

function Users({ onOpen }: { onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [lic, setLic] = useState("");
  const [sort, setSort] = useState("created_at");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [inv, setInv] = useState({ email: "", name: "" });
  const [invMsg, setInvMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    api("GET", `/api/v1/admin/users?q=${encodeURIComponent(q)}&status=${status}&license=${lic}&sort=${sort}&dir=${dir}&page=${page}&size=25`)
      .then((r) => { setData(r); setErr(null); }).catch((x) => setErr(errText(x)));
  }, [q, status, lic, sort, dir, page]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  const th = (k: string, label: string) => (
    <th className="sort" onClick={() => { if (sort === k) setDir(dir === "asc" ? "desc" : "asc"); else { setSort(k); setDir("desc"); } }}>
      {label}{sort === k ? (dir === "asc" ? " ▲" : " ▼") : ""}</th>
  );
  const invite = async () => {
    setInvMsg(null);
    try {
      await api("POST", "/api/v1/admin/users", { email: inv.email, display_name: inv.name || null });
      setInvMsg(`Zaproszenie wysłane do ${inv.email}. Użytkownik sam ustawi hasło (link jednorazowy, 72 h).`);
      setInv({ email: "", name: "" });
      load();
    } catch (x) {
      setInvMsg(errText(x));
    }
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  return (
    <>
      <div className="card">
        <div className="row">
          <input placeholder="Szukaj (e-mail, nazwa)" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Szukaj" />
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status konta">
            <option value="">wszystkie konta</option><option value="ACTIVE">aktywne</option><option value="PENDING_VERIFICATION">oczekujące</option><option value="BLOCKED">zablokowane</option>
          </select>
          <select value={lic} onChange={(e) => { setLic(e.target.value); setPage(1); }} aria-label="Licencja">
            <option value="">każda licencja</option><option value="ACTIVE">ACTIVE</option><option value="ISSUED">ISSUED</option><option value="EXPIRED">EXPIRED</option><option value="REVOKED">REVOKED</option><option value="NONE">brak</option>
          </select>
          <span className="spacer" />
          <GenerateLicense onDone={load} />
        </div>
      </div>
      <div className="card">
        {err && <div className="err">{err}</div>}
        <table>
          <thead><tr>
            {th("email", "Użytkownik")}{th("status", "Konto")}<th>Rachunek MT5</th>{th("balance", "Balance")}<th>Equity</th>
            {th("win_ratio", "Win ratio")}<th>Licencja</th>{th("expires_at", "Wygasa")}<th>Pozostało</th><th>Konektor</th>{th("last_data", "Ostatnie dane")}
          </tr></thead>
          <tbody>
            {(data?.items || []).map((r: any) => (
              <tr key={r.user.id} className="click" onClick={() => onOpen(r.user.id)} data-email={r.user.email}>
                <td><b>{r.user.display_name || r.user.email}</b><div className="muted small">{r.user.email}{r.user.role === "ADMIN" ? " · ADMIN" : ""}</div></td>
                <td><span className={`badge ${r.user.status === "ACTIVE" ? "ok" : r.user.status === "BLOCKED" ? "bad" : "warn"}`}>{r.user.status}</span></td>
                <td>{r.account ? <>{r.account.login} · {r.account.server}<div><span className={`badge ${r.account.trade_mode === "LIVE" ? "bad" : "ok"}`}>{r.account.trade_mode}</span></div></> : <span className="muted">brak</span>}</td>
                <td>{r.account ? fmtMoney(r.account.balance, r.account.currency) : "—"}</td>
                <td>{r.account ? fmtMoney(r.account.equity, r.account.currency) : "—"}</td>
                <td>{r.win_ratio ? <>{r.win_ratio.win_ratio === null ? "N/A" : `${r.win_ratio.win_ratio}%`}
                  <div className="muted small">{r.win_ratio.wins}W/{r.win_ratio.losses}L/{r.win_ratio.neutral}N · 30 dni{r.win_ratio.complete ? "" : " · niepełne"}</div></> : "—"}</td>
                <td>{r.license ? <><span className={`badge ${LIC_BADGE[r.license.status]}`}>{r.license.status}</span><div className="muted small">aktyw. {fmtTime(r.license.activated_at)}</div></> : <span className="muted">brak</span>}</td>
                <td>{fmtTime(r.license?.expires_at)}</td>
                <td>{r.license?.status === "ACTIVE" ? fmtLeft(r.license.remaining_s) : "—"}</td>
                <td><span className={`badge ${r.connector.status === "ONLINE" ? "ok" : r.connector.status === "OFFLINE" ? "warn" : ""}`}>{r.connector.status}</span></td>
                <td>{r.account ? <>{fmtAge(r.account.data_age_s)}{!r.account.data_fresh && r.account.balance !== null && <div className="muted small">nieaktualne</div>}</> : "—"}</td>
              </tr>
            ))}
            {data && !data.items.length && <tr><td colSpan={11} className="muted">Brak użytkowników dla tych filtrów.</td></tr>}
          </tbody>
        </table>
        <div className="pager">
          <span className="muted small">{data?.total ?? 0} kont · {data?.note}</span>
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button><span>{page} / {pages}</span>
          <button disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button>
        </div>
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Utwórz konto (zaproszenie)</h3>
        <div className="row">
          <input placeholder="e-mail" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} aria-label="E-mail zaproszenia" />
          <input placeholder="nazwa (opcjonalnie)" value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} />
          <button onClick={invite} disabled={!inv.email}>Wyślij zaproszenie</button>
        </div>
        <p className="muted small">Administrator nie zna hasła klienta – użytkownik ustawia je jednorazowym linkiem.</p>
        {invMsg && <div className="note">{invMsg}</div>}
      </div>
    </>
  );
}

function Stats({ accountId }: { accountId: string }) {
  const [rng, setRng] = useState("30d");
  const [scope, setScope] = useState("ACCOUNT");
  const [symbol, setSymbol] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let p = `/api/v1/admin/accounts/${accountId}/stats?range=${rng}&scope=${scope}&symbol=${encodeURIComponent(symbol)}`;
    if (rng === "custom") {
      if (!from || !to) return;
      p += `&since_ms=${new Date(from).getTime()}&until_ms=${new Date(to).getTime() + 86400000}`;
    }
    api("GET", p).then((r) => { setS(r); setErr(null); }).catch((x) => setErr(errText(x)));
  }, [accountId, rng, scope, symbol, from, to]);
  return (
    <div>
      <div className="row small">
        <select value={rng} onChange={(e) => setRng(e.target.value)} aria-label="Zakres"><option value="7d">7 dni</option><option value="30d">30 dni</option><option value="all">cały dostępny okres</option><option value="custom">własny przedział</option></select>
        {rng === "custom" && <><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></>}
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Zakres transakcji"><option value="ACCOUNT">cały rachunek</option><option value="BOT">tylko bot (magic)</option></select>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="Symbol"><option value="">wszystkie symbole</option><option value="XAUUSD-">XAUUSD-</option></select>
      </div>
      {err && <div className="err">{err}</div>}
      {s && (
        <div style={{ marginTop: 6 }}>
          <div><b style={{ fontSize: 20 }}>{s.win_ratio === null ? "N/A" : `${s.win_ratio}%`}</b> win ratio · {s.trade_mode === "REAL" ? "LIVE" : s.trade_mode}</div>
          <div className="small">wygrane {s.wins} · przegrane {s.losses} · neutralne {s.neutral} · otwarte {s.open_cycles} · niekompletne {s.incomplete_cycles} · wynik netto {fmtMoney(s.net_total, s.currency)}</div>
          <div className="small muted">Wykluczone zdarzenia (wpłaty/wypłaty/korekty itp.): {Object.entries(s.excluded_non_trade || {}).map(([k, v]) => `${k} ${v}`).join(", ") || "brak"}
            {s.unattributed_costs ? ` · koszty nieprzypisane ${fmtMoney(s.unattributed_costs, s.currency)}` : ""}</div>
          <div className="small muted">Historia: {s.history_status} · {fmtMs(s.history_from_ms)} → {fmtMs(s.history_to_ms)} {s.complete ? "" : "· STATYSTYKA NIEPEŁNA"}</div>
          <div className="small muted">{s.definition}. {s.source}.</div>
        </div>
      )}
    </div>
  );
}

function UserDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const load = useCallback(() => api("GET", `/api/v1/admin/users/${id}`).then(setD).catch((x) => setErr(errText(x))), [id]);
  useEffect(() => { load(); }, [load]);
  const act = async (fn: () => Promise<any>, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setErr(null);
    try { await fn(); await load(); } catch (x) { setErr(errText(x)); }
  };
  if (!d) return <div className="card">{err ?? "Ładowanie…"}</div>;
  const u = d.user;
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}><button onClick={onBack}>‹ Lista</button><h2 style={{ margin: 0 }}>{u.display_name || u.email}</h2>
        <span className={`badge ${u.status === "ACTIVE" ? "ok" : u.status === "BLOCKED" ? "bad" : "warn"}`}>{u.status}</span><span className="badge">{u.role}</span></div>
      {err && <div className="err">{err}</div>}
      <div className="grid2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Konto</h3>
          <div>{u.email} · utworzone {fmtTime(u.created_at)} · e-mail potwierdzony {fmtTime(u.email_verified_at)}</div>
          {u.blocked_reason && <div className="err">Powód blokady: {u.blocked_reason}</div>}
          <div className="row" style={{ marginTop: 8 }}>
            <input placeholder="powód (opcjonalnie)" value={reason} onChange={(e) => setReason(e.target.value)} />
            {u.status !== "BLOCKED" ? <button className="danger" onClick={() => act(() => api("POST", `/api/v1/admin/users/${id}/block`, { reason: reason || null }), "Zablokować konto? Sesje zostaną unieważnione, licencje NIE zostaną przedłużone.")}>Zablokuj</button>
              : <button onClick={() => act(() => api("POST", `/api/v1/admin/users/${id}/unblock`, {}))}>Odblokuj</button>}
          </div>
        </div>
        <div className="card">
          <div className="row"><h3 style={{ margin: 0 }}>Licencje</h3><span className="spacer" /><GenerateLicense preset={{ id: u.id, email: u.email }} onDone={load} /></div>
          <table><thead><tr><th>Id</th><th>Stan</th><th>Aktywacja</th><th>Wygasa</th><th>Pozostało</th><th /></tr></thead>
            <tbody>{d.licenses.map((l: any) => (
              <tr key={l.id}><td><code>{l.key_hint}</code><div className="muted small">{l.note}</div></td><td><span className={`badge ${LIC_BADGE[l.status]}`}>{l.status}</span></td>
                <td>{fmtTime(l.activated_at)}</td><td>{fmtTime(l.expires_at)}</td><td>{l.status === "ACTIVE" ? fmtLeft(l.remaining_s) : "—"}</td>
                <td>{l.status !== "REVOKED" && <button className="danger" onClick={() => act(() => api("POST", `/api/v1/admin/licenses/${l.id}/revoke`, { reason: reason || "admin" }), "Cofnąć licencję? To jest trwałe – odnowienie wymaga nowej licencji.")}>Cofnij</button>}</td></tr>))}
              {!d.licenses.length && <tr><td colSpan={6} className="muted">Brak licencji (rejestracja nie tworzy darmowej licencji).</td></tr>}</tbody></table>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Stanowiska (aktywacje) i urządzenia</h3>
          <table><thead><tr><th>Aktywacja</th><th>Urządzenie</th><th>Od</th><th>Stan</th><th /></tr></thead>
            <tbody>{d.activations.map((a: any) => (
              <tr key={a.id}><td className="small">{a.id.slice(0, 8)}</td><td className="small">{a.device_id.slice(0, 8)}</td><td>{fmtTime(a.created_at)}</td>
                <td>{a.released_at ? <span className="badge">zwolnione {fmtTime(a.released_at)}</span> : <span className="badge ok">zajęte</span>}</td>
                <td>{!a.released_at && <button onClick={() => act(() => api("POST", `/api/v1/admin/activations/${a.id}/release`, { reason: reason || "wymiana komputera" }), "Zwolnić stanowisko? Stare poświadczenie urządzenia zostanie unieważnione. Termin licencji NIE zostanie przedłużony.")}>Zwolnij stanowisko</button>}</td></tr>))}</tbody></table>
          <table style={{ marginTop: 8 }}><thead><tr><th>Urządzenie</th><th>Nazwa</th><th>Ostatnio</th><th>Stan</th><th /></tr></thead>
            <tbody>{d.devices.map((v: any) => (
              <tr key={v.id}><td className="small">{v.id.slice(0, 8)}</td><td>{v.name}</td><td>{fmtTime(v.last_seen_at)}</td><td>{v.revoked_at ? <span className="badge bad">unieważnione</span> : <span className="badge ok">ważne</span>}</td>
                <td>{!v.revoked_at && <button className="danger" onClick={() => act(() => api("POST", `/api/v1/admin/devices/${v.id}/revoke`, { reason: reason || "admin" }), "Unieważnić urządzenie?")}>Unieważnij</button>}</td></tr>))}</tbody></table>
        </div>
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Połączone rachunki MT5 (dane z konektora klienta)</h3>
        {d.accounts.map((a: any) => (
          <div key={a.id} className="note" style={{ marginBottom: 8 }}>
            <div className="row"><b>{a.login} · {a.server}</b><span className={`badge ${a.trade_mode === "LIVE" ? "bad" : "ok"}`}>{a.trade_mode}</span>
              {a.unlinked_at ? <span className="badge">odłączony {fmtTime(a.unlinked_at)}</span> : <span className="badge ok">połączony</span>}</div>
            <div>Balance <b>{fmtMoney(a.balance, a.currency)}</b> · Equity <b>{fmtMoney(a.equity, a.currency)}</b> · pomiar {fmtMs(a.measured_ms)} ({fmtAge(a.data_age_s)}){!a.data_fresh && a.balance !== null ? " · NIEAKTUALNE" : ""}</div>
            <Stats accountId={a.id} />
          </div>))}
        {!d.accounts.length && <p className="muted">Użytkownik nie połączył rachunku MT5 – brak danych (nie podstawiamy zera).</p>}
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Historia działań</h3>
        <AuditTable items={d.audit} />
      </div>
    </>
  );
}

function AuditTable({ items }: { items: any[] }) {
  return (
    <table><thead><tr><th>Kiedy</th><th>Kto</th><th>Akcja</th><th>Obiekt</th><th className="hide-sm">Przed → po</th></tr></thead>
      <tbody>{items.map((e) => (
        <tr key={e.id}><td>{fmtTime(e.at)}</td><td className="small">{e.actor_role ?? ""} {(e.actor_user_id || "").slice(0, 8)}</td><td>{e.action}</td>
          <td className="small">{e.target_type} {(e.target_id || "").slice(0, 8)}</td><td className="small hide-sm muted">{e.before_json} → {e.after_json}</td></tr>))}</tbody></table>
  );
}

function Licenses() {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const load = useCallback(() => api("GET", `/api/v1/admin/licenses?status=${status}&q=${encodeURIComponent(q)}`).then(setData).catch(() => undefined), [status, q]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="card">
      <div className="row"><input placeholder="Szukaj (e-mail, id, notatka)" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">wszystkie</option><option>ISSUED</option><option>ACTIVE</option><option>EXPIRED</option><option>REVOKED</option></select>
        <span className="spacer" /><GenerateLicense onDone={load} /></div>
      <table style={{ marginTop: 10 }}><thead><tr><th>Id</th><th>Konto</th><th>Stan</th><th>Utworzona</th><th>Aktywacja</th><th>Wygasa</th><th>Pozostało</th><th>Stanowisko</th></tr></thead>
        <tbody>{(data?.items || []).map((l: any) => (
          <tr key={l.id}><td><code>{l.key_hint}</code><div className="muted small">{l.note}</div></td><td>{l.email}</td><td><span className={`badge ${LIC_BADGE[l.status]}`}>{l.status}</span></td>
            <td>{fmtTime(l.created_at)}</td><td>{fmtTime(l.activated_at)}</td><td>{fmtTime(l.expires_at)}</td><td>{l.status === "ACTIVE" ? fmtLeft(l.remaining_s) : "—"}</td>
            <td>{l.active_activation ? "zajęte" : "wolne"}</td></tr>))}</tbody></table>
      <p className="muted small">Pełne klucze nie są przechowywane – przy utracie klucza cofnij licencję i wydaj nową.</p>
    </div>
  );
}

function Audit() {
  const [page, setPage] = useState(1);
  const [d, setD] = useState<any>(null);
  useEffect(() => { api("GET", `/api/v1/admin/audit?page=${page}`).then(setD).catch(() => undefined); }, [page]);
  return (
    <div className="card">{d && <AuditTable items={d.items} />}
      <div className="pager"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button><span>{page}</span>
        <button disabled={!d || page * d.size >= d.total} onClick={() => setPage(page + 1)}>›</button></div></div>
  );
}

function System() {
  const [d, setD] = useState<any>(null);
  const [mail, setMail] = useState<any>(null);
  useEffect(() => {
    api("GET", "/api/v1/admin/system").then((r) => { setD(r); if (r.dev) api("GET", "/api/v1/admin/dev-outbox").then(setMail).catch(() => undefined); }).catch(() => undefined);
  }, []);
  if (!d) return null;
  return (
    <div className="card">
      <div>Czas serwera: <b>{fmtTime(d.server_time)}</b> (UTC {new Date(d.server_time * 1000).toISOString()})</div>
      <div>Zegar: {d.clock_anomaly ? <span className="badge bad">ANOMALIA {d.clock_anomaly} – nowe uprawnienia wstrzymane</span> : <span className="badge ok">OK</span>}</div>
      <div>Baza: {d.db} · schemat {d.schema.join(", ")} · poczta: {d.mail_mode} · wystawca: {d.issuer}</div>
      {d.dev && <div className="note warn" style={{ marginTop: 8 }}>ŚRODOWISKO DEV – nie jest to wdrożenie produkcyjne.</div>}
      {mail && (<><h3>DEV OUTBOX (e-maile niewysłane)</h3>
        {mail.items.map((m: any) => <div key={m.id} className="note" style={{ marginBottom: 6 }} data-testid="outbox-mail"><b>{m.to_addr}</b> · {m.subject}<pre style={{ whiteSpace: "pre-wrap" }}>{m.body}</pre></div>)}</>)}
    </div>
  );
}

function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);
  const [tab, setTab] = useState("users");
  const [detail, setDetail] = useState<string | null>(null);
  useEffect(() => {
    api("GET", "/api/v1/auth/session").then((r) => { if (r.mfa_ok && r.user.role === "ADMIN") { setCsrf(r.csrf); setMe(r.user); } })
      .catch(() => undefined).finally(() => setChecked(true));
  }, []);
  if (!checked) return null;
  if (!me) return <Login onDone={setMe} />;
  const logout = async () => { await api("POST", "/api/v1/auth/logout", {}).catch(() => undefined); setCsrf(null); setMe(null); location.reload(); };
  return (
    <>
      <header className="top">
        <b>MasterQUO License Manager</b>
        <nav>{[["users", "Użytkownicy"], ["licenses", "Licencje"], ["audit", "Audyt"], ["system", "System"]].map(([k, l]) =>
          <button key={k} className={tab === k ? "on" : ""} onClick={() => { setTab(k); setDetail(null); }}>{l}</button>)}</nav>
        <span className="spacer" /><span className="muted small">{me.email}</span><button onClick={logout}>Wyloguj</button>
      </header>
      <main>
        {tab === "users" && (detail ? <UserDetail id={detail} onBack={() => setDetail(null)} /> : <Users onOpen={setDetail} />)}
        {tab === "licenses" && <Licenses />}
        {tab === "audit" && <Audit />}
        {tab === "system" && <System />}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
