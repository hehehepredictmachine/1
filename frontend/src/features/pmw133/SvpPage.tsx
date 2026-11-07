// Precision → „SVP – Session Volume Profile” (1.33, PMW-SVP-1). Profile użytkownika (SESSION / RANGE / LIVE), przeliczenie, zamrożenie,
// LIVE i AI LIVE, strefy MANUAL / ALGORITHM / AI z wersjami, propozycja AI (walidowana względem snapshotu). Strefy = informacja, nie zlecenia.
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { cls, fmtTime } from "../../util";
import { num, STATUS_PL, tone, usePoll } from "./usePoll";
import "./pmw133.css";

const MODES = ["SESSION", "RANGE", "LIVE"];
const ERR_PL: Record<string, string> = {
  NO_ACTIVE_SESSION: "brak trwającej sesji (poza godzinami sesji lub weekend) – wybierz RANGE z zakresem dat",
  PROFILE_NOT_FOUND: "profil nie istnieje", SVP_MODE_INVALID: "nieprawidłowy tryb", ZONE_BOUNDS_INVALID: "dolna granica musi być niższa od górnej",
};
function errText(e: any): string {
  const raw = String(e?.message || e);
  let code = raw;
  try { code = JSON.parse(raw.slice(raw.indexOf("{"))).detail ?? raw; } catch { /* not JSON */ }
  return ERR_PL[code] ? `${ERR_PL[code]} (${code})` : code;
}
const SESSIONS = ["ASIA", "LONDON", "NEW_YORK"];

function Histogram({ p }: { p: any }) {
  const h: any[] = p?.histogram || [];
  if (!h.length) return <p className="pmw-na">{p?.reason || "Brak histogramu."}</p>;
  const max = Math.max(...h.map((x) => x.weight)) || 1;
  const rows = [...h].reverse();
  const H = Math.max(120, Math.min(420, rows.length * 6)), W = 360, bh = H / rows.length;
  return (
    <svg className="pmw-hist" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Profil: POC ${p.poc}, VAH ${p.vah}, VAL ${p.val}`} data-testid="svp-hist">
      {rows.map((x, i) => {
        const inVa = x.price >= p.val && x.price <= p.vah;
        const isPoc = Math.abs(x.price - p.poc) < 1e-9;
        return <rect key={i} x={60} y={i * bh} width={(x.weight / max) * (W - 70)} height={Math.max(1, bh - 0.5)}
          className={cls("bar", inVa && "va", isPoc && "poc")}><title>{`${x.lo}–${x.hi}: ${x.weight}`}</title></rect>;
      })}
      <text x="2" y="10" className="lg">{num(rows[0]?.hi)}</text><text x="2" y={H - 2} className="lg">{num(rows[rows.length - 1]?.lo)}</text>
    </svg>);
}

export default function SvpPage() {
  const profiles = usePoll<any>("/api/v1/svp/profiles", 15000);
  const status = usePoll<any>("/api/v1/svp/status", 10000);
  const [src, setSrc] = useState<string>("");
  const zones = usePoll<any>(`/api/v1/svp/zones${src ? `?source=${src}` : ""}`, 15000);
  const [sel, setSel] = useState<string | null>(null);
  const [calc, setCalc] = useState<any>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState({ mode: "SESSION", tf: "M5", session: "LONDON", t0: "", t1: "", bin_ticks: 50, va_pct: 0.7, name: "" });
  const [zf, setZf] = useState({ lower: "", upper: "", name: "" });
  const items: any[] = profiles.data?.items || [];
  const cur = items.find((p) => p.profile_id === sel) ?? null;
  useEffect(() => { if (!sel && items.length) setSel(items[0].profile_id); }, [items.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setCalc(null);
    if (!sel) return;
    apiGet(`/api/v1/svp/profiles/${sel}/compute`).then(setCalc).catch((e) => setCalc({ status: "ERROR", reason: errText(e) }));
  }, [sel]);
  const run = async (fn: () => Promise<any>, ok: string | ((r: any) => string)) => {
    setMsg(null);
    try {
      const r = await fn();
      setMsg({ ok: true, text: typeof ok === "function" ? ok(r) : ok });
      await Promise.all([profiles.reload(), zones.reload(), status.reload()]);
      if (sel) setCalc(await apiGet(`/api/v1/svp/profiles/${sel}/compute`));
    } catch (e: any) { setMsg({ ok: false, text: errText(e) }); }
  };
  const create = () => run(async () => {
    const body: any = { mode: form.mode, tf: form.tf, bin_ticks: Number(form.bin_ticks), va_pct: Number(form.va_pct), name: form.name || undefined };
    if (form.mode === "SESSION" || form.mode === "LIVE") body.session = form.session;
    if (form.mode === "RANGE") { body.t0 = form.t0; body.t1 = form.t1; }
    const p = await apiSend("POST", "/api/v1/svp/profiles", body);
    setSel(p.profile_id);
    return p;
  }, (p) => `Utworzono profil ${p.profile_id}.`);
  const p = sel ? `/api/v1/svp/profiles/${sel}` : "";
  return (
    <div className="pmw-page" data-testid="page-svp">
      <header className="pmw-head">
        <h2>SVP – Session Volume Profile</h2>
        <span className="pmw-sub">Profil z OHLC = estymata aktywności (rozkład świecy w zakresie), nie footprint transakcji. Strefy to informacja analityczna.</span>
        <span className="spacer" />
        <span className={cls("badge", status.data?.agent?.state?.startsWith("AI_UNAVAILABLE") ? "muted" : "ok")} title="agent AI (propozycje stref)">
          AI: {status.data?.agent?.state ?? "—"}</span>
      </header>
      {msg && <p className={msg.ok ? "pmw-msg" : "pmw-err"} role="status" data-testid="svp-msg">{msg.text}</p>}
      <div className="pmw-grid two">
        <section className="pmw-card">
          <h3>Nowy profil</h3>
          <div className="pmw-form" data-testid="svp-form">
            <select aria-label="tryb" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>{MODES.map((m) => <option key={m}>{m}</option>)}</select>
            <select aria-label="interwał" value={form.tf} onChange={(e) => setForm({ ...form, tf: e.target.value })}>{["M1", "M5", "M15"].map((m) => <option key={m}>{m}</option>)}</select>
            {form.mode !== "RANGE" ? <select aria-label="sesja" value={form.session} onChange={(e) => setForm({ ...form, session: e.target.value })}>{SESSIONS.map((m) => <option key={m}>{m}</option>)}</select> : <>
              <input aria-label="od UTC" placeholder="od UTC 2026-11-06T08:00:00Z" value={form.t0} onChange={(e) => setForm({ ...form, t0: e.target.value })} />
              <input aria-label="do UTC" placeholder="do UTC 2026-11-06T16:00:00Z" value={form.t1} onChange={(e) => setForm({ ...form, t1: e.target.value })} /></>}
            <label>kubełek (ticki) <input type="number" min={1} value={form.bin_ticks} onChange={(e) => setForm({ ...form, bin_ticks: Number(e.target.value) })} /></label>
            <label>VA <input type="number" step={0.05} min={0.35} max={0.95} value={form.va_pct} onChange={(e) => setForm({ ...form, va_pct: Number(e.target.value) })} /></label>
            <input placeholder="nazwa" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <button className="btn" data-testid="svp-create" onClick={create}>Utwórz</button>
          </div>
          <h3>Profile ({items.length})</h3>
          <ul className="pmw-list" data-testid="svp-profiles">{items.map((x) => (
            <li key={x.profile_id} className={cls(x.profile_id === sel && "on")}><button className="link" onClick={() => setSel(x.profile_id)}>
              {x.name} · {x.mode} {x.tf} {x.session ?? ""}{x.live ? " · LIVE" : ""}{x.ai_live ? " · AI LIVE" : ""}{x.frozen_snapshot ? " · zamrożony" : ""} · v{x.version}</button></li>))}
            {!items.length && <li className="pmw-na">Brak profili – utwórz pierwszy powyżej.</li>}</ul>
        </section>
        <section className="pmw-card" data-testid="svp-current">
          <h3>{cur ? `${cur.name} (${cur.profile_id})` : "Wybierz profil"} {calc && <span className={cls("badge", tone(calc.status))} title={calc.reason ?? ""}>{STATUS_PL[calc.status] ?? calc.status}</span>}</h3>
          {cur && <div className="pmw-actions">
            <button className="btn" onClick={() => run(() => apiGet(`${p}/compute`), "Przeliczono profil.")}>Przelicz</button>
            <button className="btn" onClick={() => run(() => apiSend("POST", `${p}/freeze`), "Zamrożono profil (snapshot).")}>Zamroź</button>
            <button className="btn" onClick={() => run(() => apiSend("POST", `${p}/live`, { on: !cur.live }), cur.live ? "LIVE wyłączony." : "LIVE włączony.")}>{cur.live ? "Wyłącz LIVE" : "LIVE"}</button>
            <button className="btn" onClick={() => run(() => apiSend("POST", `${p}/ai-live`, { on: !cur.ai_live }), cur.ai_live ? "AI LIVE wyłączony." : "AI LIVE włączony.")}>{cur.ai_live ? "Wyłącz AI LIVE" : "AI LIVE"}</button>
            <button className="btn" data-testid="svp-algo" onClick={() => run(() => apiSend("POST", `${p}/zones-now`), (r) => `Strefy algorytmu: ${(r.zones || []).length}.`)}>Strefy teraz (algorytm)</button>
            <button className="btn" onClick={() => run(() => apiSend("POST", `${p}/ai-propose`), (r) => `AI: ${r.status ?? ""} ${r.reason ?? ""} ${(r.zones || []).length ? `strefy: ${r.zones.length}` : ""}`)}>Propozycja AI</button>
            <button className="btn danger" onClick={() => run(async () => { await apiSend("DELETE", p); setSel(null); }, "Usunięto profil.")}>Usuń</button>
          </div>}
          {calc && calc.status !== "ERROR" && <>
            <dl className="pmw-dl"><dt>POC</dt><dd>{num(calc.poc)}</dd><dt>VAH / VAL</dt><dd>{num(calc.vah)} / {num(calc.val)}</dd>
              <dt>VA</dt><dd>{calc.va_share != null ? `${Math.round(calc.va_share * 100)}%` : "—"}</dd><dt>świece</dt><dd>{calc.bars}/{calc.expected_bars} ({Math.round((calc.coverage || 0) * 100)}%)</dd>
              <dt>wolumen</dt><dd>{calc.volume_source}</dd><dt>zakres</dt><dd>{fmtTime(calc.start, true)} – {fmtTime(calc.end, true)}</dd></dl>
            <Histogram p={calc} />
            <p className="pmw-note">{calc.method_note}</p></>}
          {calc?.status === "ERROR" && <p className="pmw-err">{calc.reason}</p>}
        </section>
      </div>
      <section className="pmw-card" data-testid="svp-zones">
        <h3>Strefy ({(zones.data?.items || []).length})
          <select aria-label="źródło stref" value={src} onChange={(e) => setSrc(e.target.value)}><option value="">wszystkie</option>{["MANUAL", "ALGORITHM", "AI"].map((x) => <option key={x}>{x}</option>)}</select>
          <button className="btn" onClick={() => run(() => apiSend("POST", "/api/v1/svp/clear-auto", sel ? { profile_id: sel } : {}), (r) => `Wyłączono strefy auto: ${r.deactivated}.`)}>Wyczyść strefy auto</button></h3>
        <div className="pmw-form">
          <input aria-label="dolna granica" placeholder="dolna" value={zf.lower} onChange={(e) => setZf({ ...zf, lower: e.target.value })} />
          <input aria-label="górna granica" placeholder="górna" value={zf.upper} onChange={(e) => setZf({ ...zf, upper: e.target.value })} />
          <input placeholder="nazwa" value={zf.name} onChange={(e) => setZf({ ...zf, name: e.target.value })} />
          <button className="btn" onClick={() => run(() => apiSend("POST", "/api/v1/svp/zones", { lower: Number(zf.lower), upper: Number(zf.upper), name: zf.name || undefined, profile_id: sel }),
            "Dodano strefę ręczną.")}>Dodaj strefę ręczną</button>
        </div>
        <table className="pmw-t"><thead><tr><th>źródło</th><th>nazwa</th><th>dolna</th><th>górna</th><th>wersja</th><th>utworzona</th><th></th></tr></thead>
          <tbody>{(zones.data?.items || []).map((z: any) => (
            <tr key={z.zone_id}><td>{z.source}</td><td>{z.name}</td><td>{num(z.lower)}</td><td>{num(z.upper)}</td><td>v{z.version}</td>
              <td>{z.created_at ? fmtTime(new Date(z.created_at * 1000).toISOString(), true) : "—"}</td>
              <td>{!z.locked && <button className="link" onClick={() => run(() => apiSend("DELETE", `/api/v1/svp/zones/${z.zone_id}`), "Usunięto strefę.")}>usuń</button>}</td></tr>))}</tbody></table>
      </section>
    </div>);
}
