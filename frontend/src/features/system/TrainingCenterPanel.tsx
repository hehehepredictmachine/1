// CENTRUM TRENINGOWE PEPE (1.42.10, PMW-TCP-1) – jeden prosty widok treningu wszystkich modeli bota.
// GET /api/v1/pepe-training (stan modeli per instrument, kolejka, bieżący trening, historia), POST …/train {units, instruments},
// POST …/cancel, POST …/remove, GET …/log. Treningi idą po kolei (jeden naraz) – każdy swoim istniejącym mechanizmem w backendzie.
// Panel nie składa zleceń i nie zmienia trybu wykonania.
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { cls } from "../../util";

type St = { state: string; state_pl: string; detail?: string; at?: any; fails?: string[] };
type Unit = { id: string; name: string; group: string; via: string; instruments: string[]; status: Record<string, St> };
type Settings = { commission_xauusd: number | null; commission_btc: number | null };
type View = { units: Unit[]; queue: any[]; current: any | null; history: any[]; demo: boolean; instruments: string[]; pipeline_running?: string | null; settings?: Settings };

const TONE: Record<string, string> = { DONE: "ok", RUNNING: "run", QUEUED: "run", FAILED: "bad", SKIPPED: "warn", CANCELLED: "warn", UNAVAILABLE: "off", NOT_TRAINED: "off" };
const FILTERS: [string, string][] = [["all", "WSZYSTKIE"], ["todo", "DO TRENINGU"], ["bad", "BŁĘDY"], ["done", "WYTRENOWANE"]];
const INST_CHOICES: [string, string[]][] = [["OBA", ["XAUUSD", "BTC"]], ["XAUUSD", ["XAUUSD"]], ["BTC", ["BTC"]]];

const when = (x: any) => {
  if (x == null || x === "") return "";
  const d = typeof x === "number" ? new Date(x > 1e12 ? x : x * 1000) : new Date(String(x));
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const ago = (t0: any) => {
  if (!t0) return "";
  const s = Math.max(0, Date.now() / 1000 - Number(t0));
  return s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
};

export default function TrainingCenterPanel() {
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [inst, setInst] = useState("OBA");
  const [filter, setFilter] = useState("all");
  const [arm, setArm] = useState<string | null>(null);                  // dwuetapowe potwierdzenie „TRENUJ WSZYSTKO” / „ZATRZYMAJ”
  const [log, setLog] = useState<string[] | null>(null);
  const [comm, setComm] = useState<Record<string, string> | null>(null);   // edycja prowizji (null = zamknięte)
  const armT = useRef<any>(0);
  const busy = !!(v?.current || v?.queue?.length);
  const load = () => apiGet<View>("/api/v1/pepe-training").then((x) => { setV(x); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  useEffect(() => { void load(); const t = setInterval(load, busy ? 2500 : 6000); return () => clearInterval(t); }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearTimeout(armT.current), []);
  const insts = INST_CHOICES.find((x) => x[0] === inst)![1];
  const confirm = (key: string, fn: () => void) => {
    if (arm === key) { setArm(null); clearTimeout(armT.current); fn(); return; }
    setArm(key); clearTimeout(armT.current); armT.current = setTimeout(() => setArm(null), 5000);
  };
  const train = (units: string[] | "ALL", label: string) =>
    apiSend("POST", "/api/v1/pepe-training/train", { units, instruments: insts }).then((r: any) => {
      const sk = (r.skipped || []).map((x: any) => x.reason).filter(Boolean);
      setMsg(r.added?.length ? `Dodano do kolejki: ${label}${sk.length ? ` · pominięte: ${sk[0]}` : ""}` : `Nic nie dodano – ${sk[0] || "ten trening już czeka w kolejce lub trwa"}`);
      void load();
    }).catch((e) => setMsg("BŁĄD: " + String(e?.message || e)));
  const stop = () => apiSend("POST", "/api/v1/pepe-training/cancel", {}).then((r: any) => { setMsg(`Zatrzymano${r.stopped ? ": " + r.stopped : ""}${r.dropped ? ` · usunięto z kolejki: ${r.dropped}` : ""}`); void load(); })
    .catch((e) => setMsg("BŁĄD: " + String(e?.message || e)));
  const saveComm = () => apiSend("PUT", "/api/v1/pepe-training/settings", comm || {}).then(() => { setComm(null); setMsg("Zapisano prowizję – użyje jej następny trening."); void load(); })
    .catch((e) => setMsg("BŁĄD: " + String(e?.message || e)));
  const fmtC = (x: number | null | undefined) => (x == null ? "z historii transakcji" : `${x} / lot / stronę`);
  const showLog = () => (log ? setLog(null) : apiGet<any>("/api/v1/pepe-training/log?lines=120").then((r) => setLog(r.center || [])).catch(() => setLog([])));

  const units = v?.units || [];
  const cells = (u: Unit) => u.instruments.filter((i) => i === "*" || insts.includes(i));
  const shown = useMemo(() => units.filter((u) => {
    const sts = cells(u).map((i) => u.status[i]?.state);
    if (!sts.length) return false;
    if (filter === "bad") return sts.some((s) => s === "FAILED");
    if (filter === "todo") return sts.some((s) => ["NOT_TRAINED", "FAILED", "CANCELLED"].includes(s));
    if (filter === "done") return sts.some((s) => s === "DONE");
    return true;
  }), [units, filter, inst]); // eslint-disable-line react-hooks/exhaustive-deps
  const count = (st: string) => units.reduce((n, u) => n + cells(u).filter((i) => u.status[i]?.state === st).length, 0);
  const groups = [...new Set(shown.map((u) => u.group))];

  return (
    <div className="ptc" data-testid="training-center">
      <div className="ptc-intro">
        <p><b>Wybierz instrument i kliknij TRENUJ</b> przy modelu albo <b>TRENUJ WSZYSTKO</b>. Treningi idą po kolei – jeden naraz, żeby nie zabrakło
          pamięci. Przed każdym treningiem bot sam pobiera historię z MT5 i sprawdza dane. Model trafia do bota tylko wtedy, gdy przejdzie
          walidację. Trening nie składa zleceń.</p>
        {v?.demo && <p className="warn">Tryb DEMO (dane syntetyczne): wynik to test techniczny – modele nie są aktywowane.</p>}
      </div>
      <div className="ptc-bar">
        <div className="ptc-seg" role="group" aria-label="Instrument">{INST_CHOICES.map(([k]) => (
          <button key={k} type="button" aria-pressed={inst === k} onClick={() => setInst(k)}>{k}</button>))}</div>
        <button type="button" className={cls("ptc-big", arm === "all" && "armed")} data-testid="train-all" disabled={!v}
          onClick={() => confirm("all", () => void train("ALL", "wszystkie modele"))}>
          {arm === "all" ? "KLIKNIJ PONOWNIE, ABY POTWIERDZIĆ" : "TRENUJ WSZYSTKO"}</button>
        <span className="ptc-hint">{arm === "all" ? "Pełny trening może potrwać od kilkudziesięciu minut do kilku godzin." : ""}</span>
      </div>
      <div className="ptc-set">
        <span>PROWIZJA (waluta konta, 1 lot, jedna strona): <b>XAUUSD</b> {fmtC(v?.settings?.commission_xauusd)} · <b>BTC</b> {fmtC(v?.settings?.commission_btc)}</span>
        {comm ? (<>
          {(["commission_xauusd", "commission_btc"] as const).map((k) => (
            <label key={k}>{k === "commission_xauusd" ? "XAUUSD" : "BTC"}
              <input inputMode="decimal" placeholder="puste = z historii" value={comm[k] ?? ""} data-testid={"in-" + k}
                onChange={(e) => setComm({ ...comm, [k]: e.target.value })} /></label>))}
          <button type="button" className="act" data-testid="comm-save" onClick={() => void saveComm()}>ZAPISZ</button>
          <button type="button" className="act" onClick={() => setComm(null)}>ANULUJ</button>
        </>) : (
          <button type="button" className="act" data-testid="comm-edit" disabled={!v} onClick={() => setComm({
            commission_xauusd: v?.settings?.commission_xauusd == null ? "" : String(v.settings.commission_xauusd),
            commission_btc: v?.settings?.commission_btc == null ? "" : String(v.settings.commission_btc) })}>ZMIEŃ</button>)}
      </div>
      {err && <div className="note bad">Brak połączenia z botem: {err}</div>}
      {msg && <div className="note" role="status">{msg}</div>}

      <section className="ptc-now" aria-live="polite">
        {v?.current ? (<>
          <div className="ptc-now-h"><span className="ptc-pulse" /><b>TRWA:</b> {v.current.name}<span className="dim"> · {ago(v.current.started_at)}</span>
            <button type="button" className={cls("act danger", arm === "stop" && "armed")} data-testid="train-stop"
              onClick={() => confirm("stop", () => void stop())}>{arm === "stop" ? "POTWIERDŹ ZATRZYMANIE" : "ZATRZYMAJ"}</button></div>
          {v.current.detail && <div className="dim">{v.current.detail}</div>}
        </>) : <div className="dim">Nic się teraz nie trenuje.{v?.pipeline_running ? ` Trwa trening uruchomiony poza panelem (${v.pipeline_running}).` : ""}</div>}
        {!!v?.queue?.length && <ol className="ptc-queue">{v.queue.map((q: any) => (
          <li key={q.id}>{q.name}<button type="button" className="ptc-x" aria-label={"Usuń z kolejki: " + q.name}
            onClick={() => apiSend("POST", "/api/v1/pepe-training/remove", { id: q.id }).then(load)}>✕</button></li>))}</ol>}
      </section>

      <div className="ptc-sum">
        <span className="ok">wytrenowane <b>{count("DONE")}</b></span><span className="run">w toku / kolejce <b>{count("RUNNING") + count("QUEUED")}</b></span>
        <span className="bad">błędy <b>{count("FAILED")}</b></span><span className="off">nie trenowane <b>{count("NOT_TRAINED")}</b></span>
        <span className="ptc-seg sm" role="group" aria-label="Filtr">{FILTERS.map(([k, l]) => (
          <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>))}</span>
      </div>

      {!v && !err && <div className="dim">Wczytywanie…</div>}
      {groups.map((g) => (
        <section key={g} className="ptc-group"><h4>{g.toUpperCase()}</h4>
          {shown.filter((u) => u.group === g).map((u) => (
            <div key={u.id} className="ptc-row" data-testid={"unit-" + u.id}>
              <div className="ptc-name">{u.name}</div>
              <div className="ptc-cells">{cells(u).map((i) => {
                const s = u.status[i] || { state: "NOT_TRAINED", state_pl: "nie trenowany" };
                return (
                  <div key={i} className={cls("ptc-cell", TONE[s.state] || "off")} title={(s.detail || "") + (s.fails?.length ? "\n" + s.fails.join("\n") : "")}>
                    <span className="ptc-inst">{i === "*" ? "MODEL" : i}</span><span className="ptc-pill">{s.state_pl}</span>
                    <span className="ptc-det">{s.detail || ""}{s.at ? <i> · {when(s.at)}</i> : null}</span>
                  </div>);
              })}</div>
              <button type="button" className="act" data-testid={"train-" + u.id}
                disabled={cells(u).every((i) => ["UNAVAILABLE", "RUNNING", "QUEUED"].includes(u.status[i]?.state))}
                onClick={() => void train([u.id], u.name)}>TRENUJ</button>
            </div>))}
        </section>))}

      <section className="ptc-hist"><h4>OSTATNIE TRENINGI</h4>
        {v?.history?.length ? (
          <table className="sys-tbl"><tbody>{v.history.slice(0, 12).map((h: any) => (
            <tr key={h.id + String(h.finished_at)}><td>{when(h.finished_at)}</td><td>{h.name}</td>
              <td className={TONE[h.state] || ""}>{h.state_pl}</td><td className="dim">{(h.detail || "").slice(0, 160)}</td></tr>))}</tbody></table>
        ) : <div className="dim">Brak – po pierwszym treningu pojawi się tu wynik.</div>}
        <button type="button" className="act" onClick={() => void showLog()}>{log ? "UKRYJ LOG" : "POKAŻ LOG"}</button>
        {log && <pre className="ptc-log">{log.length ? log.join("\n") : "Log jest pusty."}</pre>}
      </section>
    </div>);
}
