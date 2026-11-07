import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./studio.css";

type Json = Record<string, any>;
const AREAS = ["Połączenia", "Modele", "Eksport", "Walidacja i dataset", "Trening", "Kolejka i wyniki"] as const;
type Area = (typeof AREAS)[number];
const OP_LABEL: Record<string, string> = {
  FULL_EXPORT: "Pełny eksport", VALIDATE: "Waliduj", BUILD_DATASET: "Przygotuj dane", TRAIN: "Trenuj", FIT: "Dopasuj (estymacja)",
  CALIBRATE: "Kalibruj / waliduj parametry", EXPORT_FEATURES: "Eksportuj cechy", FULL_PROCESS: "Pełny proces", TRANSFER: "Przekaż do bota",
};
const STATE_PL: Record<string, string> = {
  QUEUED: "w kolejce", RUNNING: "uruchamianie", EXPORTING: "eksport", VALIDATING_RAW: "walidacja danych", BUILDING_DATASET: "budowa datasetu",
  VALIDATING_DATASET: "walidacja datasetu", READY_FOR_TRAINING: "gotowe do treningu", TRAINING: "trening", EVALUATING: "ocena",
  PACKAGING: "test loadera / paczka", PACKAGED: "paczka gotowa", TRANSFERRED: "przekazano do bota", PAUSED: "wstrzymane",
  INTERRUPTED: "przerwane (wznów)", CANCELLED: "anulowane", BLOCKED_DATA: "brak danych", BLOCKED_DEPENDENCY: "brak zależności", FAILED: "błąd",
  FEATURES_EXPORTED: "cechy wyeksportowane", EXPORTED: "wyeksportowano", VALIDATED: "zwalidowano",
};

async function api(path: string, body?: Json): Promise<Json> {
  const r = await fetch(path, { method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}

function badge(state?: string) {
  const s = state || "";
  const cls = /SUPPORTED|PACKAGED|TRANSFERRED|READY|FEATURES|AVAILABLE/.test(s) ? "ok" : /BLOCKED|PAUSED|INTERRUPTED|EXTERNAL|QUEUED/.test(s) ? "warn"
    : /FAIL|CANCEL|ERROR/.test(s) ? "bad" : "";
  return <span className={`b ${cls}`}>{STATE_PL[s] || s || "–"}</span>;
}

function App() {
  const [area, setArea] = useState<Area>("Modele");
  const [conn, setConn] = useState<Json | null>(null);
  const [models, setModels] = useState<Json[]>([]);
  const [jobs, setJobs] = useState<Json>({ items: [] });
  const [inst, setInst] = useState("XAUUSD");
  const [sel, setSel] = useState<string[]>([]);
  const [source, setSource] = useState("AUTO");
  const [profile, setProfile] = useState("smoke");
  const [msg, setMsg] = useState("");
  const [report, setReport] = useState<Json | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [c, j] = await Promise.all([api("/api/studio/connections"), api("/api/studio/jobs")]);
      setConn(c); setJobs(j);
    } catch (e) { setMsg(String(e)); }
  }, []);
  useEffect(() => {
    api("/api/studio/models").then((m) => setModels(m.items)).catch((e) => setMsg(String(e)));
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const rows = useMemo(() => models.filter((m) => m.instrument === inst), [models, inst]);
  const selected = rows.filter((r) => sel.includes(r.task_key));
  const toggle = (k: string) => setSel((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));

  async function run(op: string, keys: string[]) {
    setMsg("");
    try {
      const r = await api("/api/studio/jobs", { task_keys: keys, op, source, profile });
      setMsg(`Dodano ${r.items.length} osobnych zadań (${OP_LABEL[op] || op}) – wykonywane po kolei.`);
      setArea("Kolejka i wyniki"); refresh();
    } catch (e) { setMsg(String(e)); }
  }
  async function act(jid: string, a: string) {
    try {
      const r = await api(`/api/studio/jobs/${jid}/${a}`, {});
      if (a === "transfer") setMsg(`Przekazano (${r.via}) – model w bocie jako kandydat, aktywacja jawnie w bocie.`);
      refresh();
    } catch (e) { setMsg(String(e)); }
  }
  async function openReport(jid: string) {
    try { setReport(await api(`/api/studio/jobs/${jid}/report`)); setArea("Walidacja i dataset"); } catch (e) { setMsg(String(e)); }
  }
  const running = (jobs.items || []).find((j: Json) => j.job_id === jobs.running);

  return (
    <div>
      <div className="st-top">
        <h1>Pepe Data &amp; Training Studio</h1>
        <span className="sub">osobna aplikacja · jeden eksport = jeden model · Studio nie wysyła zleceń</span>
        <span style={{ flex: 1 }} />
        <span className="sub" data-testid="running">{running ? <>Teraz: <b>{running.task_key.split(":")[0]}</b> · {STATE_PL[running.state] || running.state} · {running.progress?.tf || ""} {running.progress?.rows ?? ""}</> : "Kolejka bezczynna"}</span>
      </div>
      <div className="st-tabs">{AREAS.map((a) => <button key={a} className={a === area ? "on" : ""} onClick={() => setArea(a)}>{a}</button>)}</div>
      <main>
        {msg && <div className="card"><span className={msg.startsWith("Error") ? "err" : ""}>{msg}</span></div>}
        {area === "Połączenia" && conn && (
          <div className="card"><h2>Połączenia</h2>
            <div className="kv">
              <span className="dim">Bot</span><span>{conn.bot.running ? <>działa (port {conn.bot.port}) – tryb źródła BOT_CACHE</> : "nie działa – tryb MT5_DIRECT (własny adapter tylko do odczytu)"}</span>
              <span className="dim">Katalog danych bota</span><span>{conn.bot.data_dir}</span>
              <span className="dim">Katalog Studio</span><span>{conn.studio_data_dir}</span>
              <span className="dim">Pakiet MetaTrader5</span><span>{conn.mt5_package}</span>
              <span className="dim">Środowiska</span><span>{Object.entries(conn.envs).map(([k, v]) => <span key={k} className={`b ${v ? "ok" : "warn"}`} style={{ marginRight: 6 }}>{k}</span>)}</span>
              <span className="dim">Blokada eksportu</span><span>{conn.export_lock ? `${conn.export_lock.app} – zadanie ${conn.export_lock.job}` : "wolna"}</span>
            </div>
          </div>)}
        {area === "Modele" && (
          <div className="card"><h2>Modele i zadania ({rows.length})</h2>
            <div className="row" style={{ marginBottom: 8 }}>
              <select value={inst} onChange={(e) => { setInst(e.target.value); setSel([]); }}><option>XAUUSD</option><option>BTC</option></select>
              <button className="btn" disabled={!selected.length} onClick={() => run("FULL_PROCESS", selected.filter((s) => s.operations.includes("FULL_PROCESS")).map((s) => s.task_key))}>
                Wybrane modele — po kolei ({selected.length})</button>
            </div>
            <table><thead><tr><th></th><th>Model / zadanie</th><th>Kategoria</th><th>TF / H</th><th>Źródła</th><th>Środowisko</th><th>Stan</th><th>Działania</th></tr></thead>
              <tbody>{rows.map((m) => (
                <tr key={m.task_key} className={sel.includes(m.task_key) ? "sel" : ""}>
                  <td><input type="checkbox" checked={sel.includes(m.task_key)} disabled={!m.operations.length} onChange={() => toggle(m.task_key)} /></td>
                  <td><b>{m.model_id}</b><div className="dim">{m.name}</div><div className="dim">{m.task_id}</div></td>
                  <td>{m.category}</td><td>{m.base_tf}{m.horizon ? ` / H${m.horizon}` : ""}</td>
                  <td className="dim">{(m.sources || []).map((s: Json) => `${s.kind}${s.tf ? " " + s.tf : ""}`).join(", ")}</td>
                  <td>{m.env}</td><td>{badge(m.state)}{m.reason && <div className="dim">{m.reason}</div>}</td>
                  <td>{m.operations.filter((o: string) => o !== "TRANSFER").map((o: string) => <button key={o} className="btn" onClick={() => run(o, [m.task_key])}>{OP_LABEL[o] || o}</button>)}</td>
                </tr>))}</tbody></table>
          </div>)}
        {area === "Eksport" && (
          <div className="card"><h2>Eksport</h2>
            <div className="row">
              <label>Źródło <select value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="AUTO">automatycznie (bot działa → BOT_CACHE, inaczej MT5_DIRECT)</option>
                <option value="BOT_CACHE">magazyn świec działającego bota</option><option value="MT5_DIRECT">własny adapter MT5 (bot wyłączony)</option>
                <option value="SYNTHETIC">symulator (paczka testowa SYNTHETIC)</option></select></label>
              <label>Profil <select value={profile} onChange={(e) => setProfile(e.target.value)}><option>smoke</option><option>research</option><option>full</option></select></label>
            </div>
            <p className="dim">Domyślny zakres: <b>cała dostępna historia</b> (porcjami, z punktami kontrolnymi i sumami). Cutoff zamrażany przy starcie zadania; tylko zamknięte świece.
              Wybór kilku modeli tworzy osobne zadania i osobne paczki – nigdy wspólny plik ALL_MODELS.</p>
          </div>)}
        {area === "Walidacja i dataset" && (
          <div className="card"><h2>Raport paczki</h2>{report ? <pre>{JSON.stringify(report, null, 1)}</pre> : <p className="dim">Wybierz „Otwórz raport” w kolejce.</p>}</div>)}
        {area === "Trening" && (
          <div className="card"><h2>Trening</h2>
            <p className="dim">Trener dostaje jawny dataset_id i ścieżkę paczki. Profil: <b>{profile}</b> (smoke = test techniczny, nie ocena skuteczności).
              Wznawianie: od ostatniego zatwierdzonego etapu; ponowny fit nie jest kontynuacją epoki.</p>
            {running ? <pre>{JSON.stringify(running.progress, null, 1)}</pre> : <p>Brak trwającego treningu.</p>}
          </div>)}
        {area === "Kolejka i wyniki" && (
          <div className="card"><h2>Kolejka i wyniki</h2>
            {jobs.busy_by_other && <p className="err">Blokada eksportu zajęta przez {jobs.busy_by_other.app} ({jobs.busy_by_other.job}) – zadania czekają.</p>}
            <table><thead><tr><th>Zadanie</th><th>Operacja</th><th>Źródło</th><th>Stan</th><th>Etap / postęp</th><th>Akcje</th></tr></thead>
              <tbody>{(jobs.items || []).map((j: Json) => (
                <tr key={j.job_id}><td><b>{j.task_key.split(":").slice(0, 3).join(" · ")}</b><div className="dim">{j.job_id}</div></td>
                  <td>{OP_LABEL[j.op] || j.op}</td><td>{j.source?.mode}</td><td>{badge(j.state)}{j.error && <div className="err">{j.error}</div>}</td>
                  <td className="dim">{j.stage || ""} {j.progress?.tf || ""} {j.progress?.rows ?? ""}</td>
                  <td>
                    {j.state === "QUEUED" && <button className="btn alt" onClick={() => act(j.job_id, "move")}>Na koniec</button>}
                    {!["CANCELLED", "PACKAGED", "TRANSFERRED", "FAILED", "FEATURES_EXPORTED", "READY_FOR_TRAINING"].includes(j.state) && <button className="btn alt" onClick={() => act(j.job_id, "pause")}>Pauza</button>}
                    {["PAUSED", "INTERRUPTED", "FAILED"].includes(j.state) && <button className="btn" onClick={() => act(j.job_id, "resume")}>Wznów</button>}
                    {!["CANCELLED", "PACKAGED", "TRANSFERRED", "FEATURES_EXPORTED", "READY_FOR_TRAINING"].includes(j.state) && <button className="btn alt" onClick={() => act(j.job_id, "cancel")}>Anuluj</button>}
                    {j.package && <button className="btn" onClick={() => openReport(j.job_id)}>Otwórz raport</button>}
                    {j.state === "PACKAGED" && <button className="btn" onClick={() => act(j.job_id, "transfer")}>Przekaż do bota</button>}
                  </td></tr>))}</tbody></table>
          </div>)}
      </main>
    </div>
  );
}

createRoot(document.getElementById("studio-root")!).render(<App />);
