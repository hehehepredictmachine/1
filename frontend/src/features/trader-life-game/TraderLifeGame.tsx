// TraderLifeGame™ (Apollo23 TASK 019) – trasa #/trader-life-game. Funkcjonalny pulpit 8 modułów gry na API /api/v1/tlg/*.
// Gra jest edukacyjna i odizolowana od handlu: żaden przycisk tutaj nie wysyła zleceń, nie zmienia ryzyka, STOP ani trybu wykonania.
// Salda są rozdzielone: realne (MT5, tylko odczyt), wirtualne (symulator), Trader Gold (kosmetyczne) i XP – nigdy nie są sumowane.
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { BRAND, GAME_BRAND } from "../../brand";
import { parseNumText } from "../../components/numText";
import "./tlg.css";

type Tab = "character" | "coach" | "quests" | "journal" | "calendar" | "skills" | "academy" | "simulator" | "lifestyle" | "leaderboard";
const TABS: [Tab, string][] = [["character", "Postać"], ["coach", "Grand Master Coach"], ["quests", "Questy"], ["journal", "Dziennik"],
  ["calendar", "Kalendarz"], ["skills", "Drzewo umiejętności"], ["academy", "Akademia"], ["simulator", "Symulator"], ["lifestyle", "Lifestyle"],
  ["leaderboard", "Ranking"]];

const fmt = (v: any, d = 2) => (v === null || v === undefined ? "—" : typeof v === "number" ? v.toLocaleString("pl-PL", { maximumFractionDigits: d }) : String(v));

export default function TraderLifeGame({ onBack }: { onBack(): void }) {
  const [st, setSt] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("character");
  const [msg, setMsg] = useState<string>("");
  const reload = useCallback(() => apiGet("/api/v1/tlg/state").then(setSt).catch((e) => setMsg(String(e.message || e))), []);
  useEffect(() => { void reload(); }, [reload]);
  // 1.46: act() resolves to null on an error (message already shown) – callers close forms / clear inputs / drop the session only
  // for a non-null result (a failed save closed the journal form, cleared the coach text and hid a still ACTIVE simulator session)
  const act = async (p: Promise<any>, ok?: string) => {
    try { const r = await p; if (ok) setMsg(ok); await reload(); return r; } catch (e: any) { setMsg("Błąd: " + (e.message || e)); return null; }
  };

  return (
    <div className="tlg" data-testid="page-tlg">
      <header className="tlg-top">
        <button type="button" className="btn ghost" data-testid="tlg-back" onClick={onBack}>⟵ POWRÓT DO UNIWERSUM</button>
        <h1>{GAME_BRAND} <small>· {BRAND}</small></h1>
        {st?.profile && <div className="tlg-bar" data-testid="tlg-bar">
          <span>{st.profile.username}</span><span>Poziom {st.progress.level} · {st.progress.rank}</span>
          <span>XP {fmt(st.progress.xp, 0)}{st.progress.xp_next_level ? ` / ${fmt(st.progress.xp_next_level, 0)}` : ""}</span>
          <span>Trader Gold {fmt(st.balances.trader_gold, 0)}</span></div>}
      </header>
      {msg && <p className="tlg-msg" role="status" data-testid="tlg-msg">{msg}</p>}
      {st && st.needs_character ? <CreateCharacter onDone={(m) => { setMsg(m); void reload(); }} /> : st?.profile ? <>
        <nav className="tlg-tabs" aria-label="Moduły gry">{TABS.map(([id, label]) =>
          <button key={id} type="button" className={"btn" + (tab === id ? "" : " ghost")} aria-pressed={tab === id} data-testid={"tlg-tab-" + id}
            onClick={() => setTab(id)}>{label}</button>)}</nav>
        <main className="tlg-main">
          {tab === "character" && <Character st={st} />}
          {tab === "coach" && <Coach act={act} />}
          {tab === "quests" && <Quests act={act} />}
          {tab === "journal" && <Journal act={act} />}
          {tab === "calendar" && <Calendar />}
          {tab === "skills" && <Skills act={act} />}
          {tab === "academy" && <Academy act={act} />}
          {tab === "simulator" && <Simulator act={act} />}
          {tab === "lifestyle" && <Lifestyle act={act} />}
          {tab === "leaderboard" && <Leaderboard />}
        </main></> : <p className="small muted">Wczytywanie…</p>}
      <footer className="tlg-foot small muted">Gra edukacyjna – bez uprawnień do zleceń. Kamienie milowe to wirtualne cele, nie obietnica zysku.</footer>
    </div>);
}

function CreateCharacter({ onDone }: { onDone(m: string): void }) {
  const [meta, setMeta] = useState<any>(null);
  const [f, setF] = useState({ username: "", class_id: "THE_ROOKIE", difficulty: "EASY", currency: "USD", virtual_capital: 10000 });
  const [err, setErr] = useState("");
  // 1.46: an error of /tlg/meta (e.g. 402 licence) left an empty page without a message – show it with a retry
  const [metaErr, setMetaErr] = useState("");
  const loadMeta = useCallback(() => { setMetaErr(""); apiGet("/api/v1/tlg/meta").then(setMeta).catch((e) => setMetaErr(String(e?.message || e))); }, []);
  useEffect(loadMeta, [loadMeta]);
  if (!meta) return metaErr ? <section className="panel tlg-create" data-testid="tlg-create-error"><p className="bad small">Nie udało się wczytać klas postaci: {metaErr}</p>
    <button type="button" className="btn" onClick={loadMeta}>Spróbuj ponownie</button></section> : null;
  const save = async () => { try { await apiSend("POST", "/api/v1/tlg/profile", f); onDone("Postać utworzona."); } catch (e: any) { setErr(e.message); } };
  return (
    <section className="panel tlg-create" data-testid="tlg-create"><div className="panel-head"><b>Stwórz postać</b></div>
      <label>Nazwa <input value={f.username} maxLength={32} onChange={(e) => setF({ ...f, username: e.target.value })} data-testid="tlg-username" /></label>
      <div className="tlg-grid">{Object.entries<any>(meta.classes).map(([id, c]) =>
        <button key={id} type="button" className={"tlg-card" + (f.class_id === id ? " on" : "")} onClick={() => setF({ ...f, class_id: id })} data-testid={"tlg-class-" + id}>
          <b>{c.name}</b><span className="small">{c.specialization}</span><span className="small muted">{c.description}</span></button>)}</div>
      <div className="tlg-grid">{Object.entries<any>(meta.difficulties).map(([id, d]) =>
        <button key={id} type="button" className={"tlg-card" + (f.difficulty === id ? " on" : "")} onClick={() => setF({ ...f, difficulty: id })}>
          <b>{d.name}</b><span className="small">Cel wirtualny: {fmt(d.milestone, 0)}</span></button>)}</div>
      <p className="small muted">{meta.milestone_note}</p>
      <label>Waluta wirtualna <input value={f.currency} maxLength={5} onChange={(e) => setF({ ...f, currency: e.target.value })} /></label>
      <label>Kapitał wirtualny <input type="number" value={f.virtual_capital} onChange={(e) => setF({ ...f, virtual_capital: Number(e.target.value) })} /></label>
      {err && <p className="bad small">{err}</p>}
      <button type="button" className="btn" onClick={save} data-testid="tlg-create-save">UTWÓRZ POSTAĆ</button>
    </section>);
}

function Character({ st }: { st: any }) {
  const b = st.balances;
  return (<div className="tlg-cols">
    <section className="panel"><div className="panel-head"><b>{st.profile.class} · {st.profile.difficulty_name}</b></div>
      <p>{st.profile.intro}</p>
      <p className="small">Cel wirtualny: {fmt(st.profile.milestone, 0)} {st.profile.currency} – {st.profile.milestone_note}</p>
      <table className="tlg-table"><tbody>{Object.entries<any>(st.attributes).map(([k, v]) =>
        <tr key={k}><td>{k.replace(/_/g, " ")}</td><td><meter min={0} max={100} value={v} /></td><td>{v}</td></tr>)}</tbody></table></section>
    <section className="panel" data-testid="tlg-balances"><div className="panel-head"><b>Salda (osobno, nigdy sumowane)</b></div>
      <table className="tlg-table"><tbody>
        <tr><td>Realne saldo (MT5, odczyt)</td><td>{fmt(b.real_balance)} {b.real_currency || ""}</td><td className="small muted">{b.real_source}</td></tr>
        <tr><td>Realne equity (MT5, odczyt)</td><td>{fmt(b.real_equity)}</td><td /></tr>
        <tr><td>Saldo wirtualne (symulator)</td><td>{fmt(b.virtual_balance)} {b.virtual_currency}</td><td className="small muted">SIMULATOR</td></tr>
        <tr><td>Wynik symulacji</td><td>{fmt(b.simulated_pnl)}</td><td /></tr>
        <tr><td>Trader Gold (kosmetyczne)</td><td>{fmt(b.trader_gold, 0)}</td><td /></tr>
        <tr><td>XP</td><td>{fmt(b.xp, 0)}</td><td /></tr></tbody></table></section></div>);
}

function useLoad<T = any>(path: string, deps: any[] = []): [T | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const load = useCallback(() => { apiGet<T>(path).then(setD).catch(() => setD(null)); }, [path]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [load, ...deps]);
  return [d, load];
}
type Act = (p: Promise<any>, ok?: string) => Promise<any>;

function Coach({ act }: { act: Act }) {
  const [c, load] = useLoad<any>("/api/v1/tlg/coach");
  const [t, setT] = useState("");
  if (!c) return null;
  return (<section className="panel" data-testid="tlg-coach"><div className="panel-head"><b>{c.persona}</b> <span className="small muted">tryb {c.mode} · {c.ai}</span></div>
    <p>{c.greeting}</p><h4>Plan dnia</h4><ul>{c.daily_plan.map((x: string) => <li key={x}>{x}</li>)}</ul>
    <h4>Obserwacje</h4><ul>{c.observations.map((o: any, i: number) => <li key={i}><span className="small muted">{o.kind}</span> {o.text}</li>)}</ul>
    <p className="small muted">{c.disclaimer}</p>
    <h4>Pamięć coacha (Twoja, edytowalna)</h4>
    <ul>{c.memory.map((m: any) => <li key={m.id}>{m.text} <button type="button" className="btn ghost" onClick={() => act(apiSend("DELETE", "/api/v1/tlg/coach/memory?memory_id=" + m.id)).then(load)}>usuń</button></li>)}</ul>
    <input value={t} onChange={(e) => setT(e.target.value)} placeholder="np. handluję tylko sesję londyńską" />
    <button type="button" className="btn" onClick={() => act(apiSend("POST", "/api/v1/tlg/coach/memory", { text: t })).then((r) => { if (r) { setT(""); load(); } })}>Zapamiętaj</button>
    <button type="button" className="btn ghost" onClick={() => act(apiSend("DELETE", "/api/v1/tlg/coach/memory")).then(load)}>Wyczyść pamięć</button></section>);
}

function Quests({ act }: { act: Act }) {
  const [q, load] = useLoad<any>("/api/v1/tlg/quests");
  return (<section className="panel" data-testid="tlg-quests"><table className="tlg-table"><thead><tr><th>Kategoria</th><th>Quest</th><th>Postęp</th><th>Nagroda</th><th>Status</th><th /></tr></thead>
    <tbody>{(q?.items || []).map((x: any) => <tr key={x.id}><td>{x.category}</td><td><b>{x.title}</b><br /><span className="small muted">{x.description}</span></td>
      <td>{x.progress}/{x.requirement.count}</td><td>{x.xp_reward} XP · {x.gold_reward} G</td><td>{x.status}</td>
      <td>{x.status === "COMPLETED" && <button type="button" className="btn" onClick={() => act(apiSend("POST", `/api/v1/tlg/quests/${x.id}/claim`), "Nagroda odebrana.").then(load)}>Odbierz</button>}</td></tr>)}
    </tbody></table></section>);
}

function Journal({ act }: { act: Act }) {
  const [j, load] = useLoad<any>("/api/v1/tlg/journal");
  const [edit, setEdit] = useState<any>(null);
  const [note, setNote] = useState({ kind: "PLAN", text: "", invalidation: "", max_risk: "" });
  return (<div className="tlg-cols">
    <section className="panel" data-testid="tlg-journal"><div className="panel-head"><b>Dziennik transakcji (MT5 – tylko odczyt)</b> <span className="small muted">{j?.source}</span></div>
      <table className="tlg-table"><thead><tr><th>Pozycja</th><th>Symbol</th><th>Strona</th><th>Status</th><th>Wynik netto</th><th>Wpis</th><th /></tr></thead>
        <tbody>{(j?.items || []).slice(0, 50).map((p: any) => <tr key={p.ref}><td>{p.position_id}</td><td>{p.symbol}</td><td>{p.side}</td><td>{p.status}</td>
          <td>{fmt(p.net_pnl)}</td><td>{p.annotation ? "✓" : "—"}</td>
          <td><button type="button" className="btn ghost" onClick={() => setEdit({ ref: p.ref, ...(p.annotation || {}) })}>opisz</button></td></tr>)}</tbody></table>
      {!j?.items?.length && <p className="small muted">Brak transakcji z MT5 (albo terminal nie jest połączony).</p>}</section>
    {edit && <section className="panel"><div className="panel-head"><b>Wpis: {edit.ref}</b></div>
      {(["setup", "reason", "emotion_before", "emotion_after", "lesson"] as const).map((k) =>
        <label key={k}>{k} <input value={edit[k] || ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></label>)}
      {/* 1.46: "—" sends null - undefined was dropped by JSON.stringify and the stored true/false came back after saving */}
      <label>Zgodnie z regułami <select value={String(edit.rule_compliance ?? "")} onChange={(e) => setEdit({ ...edit, rule_compliance: e.target.value === "" ? null : e.target.value === "true" })}>
        <option value="">—</option><option value="true">tak</option><option value="false">nie</option></select></label>
      <label>Ocena wykonania 0–10 <input type="number" min={0} max={10} value={edit.review_score ?? ""} onChange={(e) => setEdit({ ...edit, review_score: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      <label>Błędy (po przecinku) <input value={(edit.mistakes || []).join(", ")} onChange={(e) => setEdit({ ...edit, mistakes: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></label>
      <button type="button" className="btn" onClick={() => { const { ref, ...body } = edit; void act(apiSend("PUT", "/api/v1/tlg/journal/" + encodeURIComponent(ref), body), "Wpis zapisany.").then((r) => { if (r) { setEdit(null); load(); } }); }}>Zapisz</button></section>}
    <section className="panel"><div className="panel-head"><b>Notatka: plan / analiza / przegląd tygodnia</b></div>
      <select value={note.kind} onChange={(e) => setNote({ ...note, kind: e.target.value })}><option value="PLAN">Plan dnia</option><option value="ANALYSIS">Analiza wykresu</option><option value="WEEKLY">Przegląd tygodnia</option></select>
      <textarea rows={4} value={note.text} onChange={(e) => setNote({ ...note, text: e.target.value })} placeholder="min. 40 znaków" />
      {note.kind === "ANALYSIS" && <input value={note.invalidation} onChange={(e) => setNote({ ...note, invalidation: e.target.value })} placeholder="poziom unieważnienia" />}
      {note.kind === "PLAN" && <input value={note.max_risk} onChange={(e) => setNote({ ...note, max_risk: e.target.value })} placeholder="maks. ryzyko dnia" />}
      <button type="button" className="btn" onClick={() => act(apiSend("POST", "/api/v1/tlg/notes/" + note.kind, note), "Notatka zapisana.")}>Zapisz notatkę</button></section></div>);
}

function Calendar() {
  const now = new Date();
  const [m, setM] = useState(`${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`);
  const [c] = useLoad<any>("/api/v1/tlg/calendar?month=" + m, [m]);
  return (<section className="panel" data-testid="tlg-calendar"><div className="panel-head"><b>Kalendarz</b> <input type="month" value={m} onChange={(e) => setM(e.target.value)} /></div>
    <p className="small muted">{c?.note} · transakcje: {c?.time_basis?.real_trades} · zdarzenia gry: {c?.time_basis?.game_events}</p>
    <table className="tlg-table"><thead><tr><th>Dzień</th><th>Typ</th><th>Transakcje</th><th>Wynik netto (MT5)</th><th>XP</th><th>Symulator</th></tr></thead>
      <tbody>{(c?.days || []).map((d: any) => <tr key={d.date}><td>{d.date}</td><td>{d.type}</td><td>{d.real_trades}</td><td>{fmt(d.real_net_pnl)}</td><td>{d.xp}</td><td>{d.sim_sessions}</td></tr>)}</tbody></table></section>);
}

function Skills({ act }: { act: Act }) {
  const [s, load] = useLoad<any>("/api/v1/tlg/skills");
  if (!s) return null;
  return (<section className="panel" data-testid="tlg-skills"><div className="panel-head"><b>Drzewo umiejętności</b> <span className="small">punkty: {s.points_available}</span></div>
    <div className="tlg-cols">{Object.entries<any>(s.branches).map(([b, name]) => <div key={b}><h4>{name}</h4>
      {s.nodes.filter((n: any) => n.branch === b).map((n: any) => <div key={n.id} className={"tlg-node " + n.state.toLowerCase()}>
        <b>{n.name}</b> <span className="small muted">poz. {n.min_level}</span><br /><span className="small">{n.description}</span><br />
        {n.state === "AVAILABLE" ? <button type="button" className="btn" onClick={() => act(apiSend("POST", "/api/v1/tlg/skills/" + n.id), "Odblokowano.").then(load)}>Odblokuj</button>
          : <span className="small muted">{n.state}</span>}</div>)}</div>)}</div></section>);
}

function Academy({ act }: { act: Act }) {
  const [a, load] = useLoad<any>("/api/v1/tlg/academy");
  const [ans, setAns] = useState<Record<number, number[]>>({});
  const [risk, loadRisk] = useLoad<any>("/api/v1/tlg/academy/risk");
  const [ra, setRa] = useState("");
  const [raErr, setRaErr] = useState("");
  if (!a) return null;
  // 1.46: Number("7,78") = NaN -> JSON null -> a correct answer typed with a decimal comma was graded wrong; an empty field sent 0
  const checkRisk = () => {
    const x = parseNumText(ra);
    if (x == null) { setRaErr(x === null ? "Wpisz odpowiedź (liczbę jednostek)." : `„${ra}” to nie jest liczba – np. 7,78 albo 7.78.`); return; }
    setRaErr("");
    void act(apiSend("POST", "/api/v1/tlg/academy/risk", { exercise_id: risk.exercise_id, answer: x }))
      .then((r) => { if (r) { alert(r.correct ? "Poprawnie." : `Niepoprawnie – oczekiwano ${r.expected}`); setRa(""); loadRisk(); } });
  };
  return (<div data-testid="tlg-academy">{a.levels.map((L: any) => <section className="panel" key={L.level}>
    <div className="panel-head"><b>Poziom {L.level} — {L.name}</b> <span className="small">{Math.round(L.progress * 100)}% {L.passed_quiz ? "· test zaliczony" : ""}</span></div>
    {L.lessons.map((ls: any) => <details key={ls.id}><summary>{ls.completed ? "✓ " : ""}{ls.title}</summary><p>{ls.body}</p><p className="small"><b>Przykład:</b> {ls.example}</p>
      <p className="small"><b>Ćwiczenie:</b> {ls.exercise}</p>
      {!ls.completed && <button type="button" className="btn" onClick={() => act(apiSend("POST", "/api/v1/tlg/academy/lesson/" + ls.id), "Lekcja ukończona.").then(load)}>Oznacz jako ukończoną</button>}</details>)}
    <h4>Test wiedzy</h4>{L.quiz.map((q: any, i: number) => <div key={i} className="small">{q.q} {q.options.map((o: string, j: number) =>
      <label key={j}><input type="radio" name={`q${L.level}-${i}`} checked={(ans[L.level] || [])[i] === j}
        onChange={() => { const x = [...(ans[L.level] || [])]; x[i] = j; setAns({ ...ans, [L.level]: x }); }} /> {o} </label>)}</div>)}
    <button type="button" className="btn" onClick={() => act(apiSend("POST", "/api/v1/tlg/academy/quiz/" + L.level, { answers: ans[L.level] || [] })).then((r) => { if (r) alert(`Wynik: ${r.correct}/${L.quiz.length} – ${r.passed ? "zaliczony" : "niezaliczony"}`); load(); })}>Sprawdź test</button>
  </section>)}
    {risk && <section className="panel"><div className="panel-head"><b>Ćwiczenie z ryzyka</b></div><p>{risk.question}</p>
      <input value={ra} inputMode="decimal" onChange={(e) => setRa(e.target.value)} /><button type="button" className="btn" onClick={checkRisk}>Sprawdź</button>
      {raErr && <p className="bad small">{raErr}</p>}</section>}
    <p className="small muted">{a.source}</p></div>);
}

function Simulator({ act }: { act: Act }) {
  const [sid, setSid] = useState<number | null>(null);
  const [v, setV] = useState<any>(null);
  const [f, setF] = useState({ symbol: "", tf: "H1", size: 1, sl: "", tp: "" });
  const [ferr, setFerr] = useState("");
  const run = async (p: Promise<any>) => { const r = await act(p); if (r && r.id) { setSid(r.id); setV(r); } return r; };
  // 1.46: the session id lived only in this tab – after a tab switch the ACTIVE session stayed on the server unreachable; offer to resume it
  const [sims, loadSims] = useLoad<any>("/api/v1/tlg/sim");
  const resumable = (sims?.items || []).find((x: any) => x.status === "ACTIVE");
  // 1.46: "2400,5" -> Number() = NaN -> JSON null -> the virtual position was opened WITHOUT SL/TP; comma accepted, unreadable text blocks the order
  const open = (side: "BUY" | "SELL") => {
    const sl = parseNumText(f.sl), tp = parseNumText(f.tp);
    if (sl === undefined || tp === undefined) { setFerr(`Niepoprawna wartość ${sl === undefined ? "SL" : "TP"} – wpisz liczbę (np. 2400,5) albo zostaw pole puste.`); return; }
    setFerr("");
    void run(apiSend("POST", `/api/v1/tlg/sim/${sid}/open`, { side, size: f.size, sl, tp }));
  };
  const last = v?.bars?.[v.bars.length - 1];
  return (<section className="panel" data-testid="tlg-sim"><div className="panel-head"><b>Symulator historyczny</b> <span className="small muted">{v?.isolation}</span></div>
    {!sid ? <div><input placeholder="symbol (domyślnie z ustawień)" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })} />
      <select value={f.tf} onChange={(e) => setF({ ...f, tf: e.target.value })}>{["M5", "M15", "H1", "H4", "D1"].map((t) => <option key={t}>{t}</option>)}</select>
      <button type="button" className="btn" onClick={() => run(apiSend("POST", "/api/v1/tlg/sim", { symbol: f.symbol || undefined, tf: f.tf }))}>Start sesji</button>
      {resumable && <button type="button" className="btn ghost" onClick={() => run(apiGet(`/api/v1/tlg/sim/${resumable.id}`))}>Wznów sesję #{resumable.id} ({resumable.symbol} {resumable.tf})</button>}</div>
      : v && <div>
        <p className="small">{v.symbol} {v.tf} · odsłonięte świece: {v.bars.length} · ostatnie zamknięcie: {fmt(last?.c, 5)} · wynik: {fmt(v.simulated_pnl)} · saldo wirtualne: {fmt(v.virtual_balance)}</p>
        <MiniChart bars={v.bars.slice(-120)} />
        <div className="tlg-row"><button type="button" className="btn" onClick={() => run(apiSend("POST", `/api/v1/tlg/sim/${sid}/step`, { n: 1 }))}>+1 świeca</button>
          <button type="button" className="btn" onClick={() => run(apiSend("POST", `/api/v1/tlg/sim/${sid}/step`, { n: 10 }))}>+10 świec</button>
          <input type="number" value={f.size} onChange={(e) => setF({ ...f, size: Number(e.target.value) })} title="wielkość wirtualna" />
          <input placeholder="SL" inputMode="decimal" value={f.sl} onChange={(e) => setF({ ...f, sl: e.target.value })} /><input placeholder="TP" inputMode="decimal" value={f.tp} onChange={(e) => setF({ ...f, tp: e.target.value })} />
          {(["BUY", "SELL"] as const).map((side) => <button key={side} type="button" className="btn ghost" onClick={() => open(side)}>{side} (wirtualnie)</button>)}
          <button type="button" className="btn ghost" onClick={() => run(apiSend("POST", `/api/v1/tlg/sim/${sid}/finish`)).then((r) => { if (r) { setSid(null); loadSims(); } })}>Zakończ sesję</button></div>
        {ferr && <p className="bad small">{ferr}</p>}
        <table className="tlg-table"><thead><tr><th>#</th><th>Strona</th><th>Wejście</th><th>SL</th><th>TP</th><th>Wyjście</th><th>Wynik</th><th /></tr></thead>
          <tbody>{v.trades.map((t: any) => <tr key={t.id}><td>{t.id}</td><td>{t.side}</td><td>{fmt(t.entry, 5)}</td><td>{fmt(t.sl, 5)}</td><td>{fmt(t.tp, 5)}</td>
            <td>{t.closed_idx == null ? "otwarta" : `${fmt(t.exit, 5)} (${t.reason})`}</td><td>{fmt(t.pnl)}</td>
            <td>{t.closed_idx == null && <button type="button" className="btn ghost" onClick={() => run(apiSend("POST", `/api/v1/tlg/sim/${sid}/close/${t.id}`))}>zamknij</button>}</td></tr>)}</tbody></table>
      </div>}</section>);
}

function MiniChart({ bars }: { bars: any[] }) {
  if (!bars.length) return null;
  const hi = Math.max(...bars.map((b) => b.h)), lo = Math.min(...bars.map((b) => b.l)), W = 720, H = 180, w = W / bars.length;
  const y = (p: number) => H - ((p - lo) / (hi - lo || 1)) * H;
  return (<svg className="tlg-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Odsłonięte świece symulatora">{bars.map((b, i) =>
    <g key={i}><line x1={i * w + w / 2} x2={i * w + w / 2} y1={y(b.h)} y2={y(b.l)} className="wick" />
      <rect x={i * w + 1} width={Math.max(1, w - 2)} y={y(Math.max(b.o, b.c))} height={Math.max(1, Math.abs(y(b.o) - y(b.c)))} className={b.c >= b.o ? "up" : "down"} /></g>)}</svg>);
}

function Lifestyle({ act }: { act: Act }) {
  const [l, load] = useLoad<any>("/api/v1/tlg/lifestyle");
  if (!l) return null;
  return (<section className="panel" data-testid="tlg-lifestyle"><div className="panel-head"><b>Lifestyle</b> <span className="small">Trader Gold: {l.trader_gold}</span></div>
    <p className="small muted">{l.note}</p>
    <table className="tlg-table"><thead><tr><th>Przedmiot</th><th>Miejsce</th><th>Cena</th><th>Poziom</th><th>Stan</th><th /></tr></thead>
      <tbody>{l.items.map((it: any) => <tr key={it.id}><td>{it.name}</td><td>{it.slot}</td><td>{it.price}</td><td>{it.min_level}</td><td>{it.equipped ? "W UŻYCIU" : it.state}</td>
        <td>{it.state === "AFFORDABLE" && <button type="button" className="btn" onClick={() => act(apiSend("POST", `/api/v1/tlg/lifestyle/${it.id}/buy`)).then(load)}>Kup</button>}
          {it.owned && !it.equipped && <button type="button" className="btn ghost" onClick={() => act(apiSend("POST", `/api/v1/tlg/lifestyle/${it.id}/equip`)).then(load)}>Użyj</button>}</td></tr>)}</tbody></table></section>);
}

function Leaderboard() {
  const [b] = useLoad<any>("/api/v1/tlg/leaderboard");
  if (!b) return null;
  return (<section className="panel" data-testid="tlg-leaderboard"><div className="panel-head"><b>Ranking lokalny</b></div>
    <table className="tlg-table"><thead><tr><th>Gracz</th><th>Poziom</th><th>XP</th><th>Dyscyplina</th><th>Ryzyko</th><th>Questy</th><th>Lekcje</th><th>Wynik</th></tr></thead>
      <tbody>{b.local.map((r: any, i: number) => <tr key={i}><td>{r.name}</td><td>{r.level}</td><td>{r.xp}</td><td>{r.discipline}</td><td>{r.risk_management}</td><td>{r.quests}</td><td>{r.lessons}</td><td>{r.score}</td></tr>)}</tbody></table>
    <p className="small muted">{b.formula}</p><p className="small">{b.global.message}</p></section>);
}
