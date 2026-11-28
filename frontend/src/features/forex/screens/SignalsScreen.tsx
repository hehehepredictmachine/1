// 02 SIGNALS (E4, S3 §3). Źródła: GET /api/v1/bot-signals (silnik), /api/v1/setups (scenariusze), /api/v1/sh/signals (SH);
// szczegóły: /bot-signals/{id}, /setups/{id}/details, /sh/signals/{sid}; bramki: /api/v1/decision (pola z raportu E0);
// ocena modeli: wszystkie pozycje /api/v1/models/catalog + /api/v1/models/predictions. Szansa % wyłącznie z prawdopodobieństwa
// skalibrowanego (unit=probability + CALIBRATED_DEV); score i symulacja mają własne etykiety. Filtry liczone na pobranej liście.
import { useEffect, useMemo, useState } from "react";
import { useStore } from "../../../store";
import { chanceLabel, fmt, fmtTime, ts, usePoll } from "../data";
import type { ScreenProps } from "../ForexScene";

type Sig = { id: string; kind: "BOT" | "SETUP" | "SH"; strategy: string; name: string; tf: string; dir: string; lc: string; ph: Phase; at: number; entry: number | null; sl: number | null;
  tps: number[]; rr: number | null; score: number | null; ai: string | null; reasons: string[]; outcome: number | null; raw: any };
type Phase = "live" | "mid" | "hist";
const LIVE = new Set(["CANDIDATE", "CONFIRMED", "FILLED", "WAIT", "ACTIVE", "OPEN", "ARMED", "WATCH", "EARLY", "PENDING", "NEW"]);
const HIST = new Set(["CLOSED", "EXPIRED", "INVALIDATED", "REJECTED", "CANCELLED", "DONE"]);
// 1.46: lifecycle per source, from the statuses the APIs really return - BOT /bot-signals: OPEN | WIN | LOSS | TIMEOUT | REJECTED;
// SETUP /setups: EARLY_SETUP … CONFIRMED | INVALIDATED | EXPIRED | MISSED_ENTRY | ENTERED | CANCELLED; SH /sh/signals: READY | WAIT | NO_TRADE |
// EXPIRED | INVALIDATED. One shared set dropped settled bot signals from HISTORIA and counted SH WAIT (an evaluation) as active, SH READY not.
const PHASES: Record<Sig["kind"], { live: string[]; mid?: string[]; hist: string[] }> = {
  BOT: { live: ["OPEN"], hist: ["WIN", "LOSS", "TIMEOUT", "REJECTED"] },
  SETUP: { live: ["EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED"], hist: ["INVALIDATED", "EXPIRED", "MISSED_ENTRY", "ENTERED", "CANCELLED"] },
  SH: { live: ["READY"], mid: ["WAIT"], hist: ["NO_TRADE", "EXPIRED", "INVALIDATED"] },
};
function phaseOf(kind: Sig["kind"], lc: string, raw: any): Phase {
  const p = PHASES[kind];
  if (kind === "SH" && lc === "READY" && ["CLOSED", "REJECTED", "ERROR_CLOSED"].includes(raw?.plan?.state)) return "hist";   // plan of the signal finished
  if (p.live.includes(lc)) return "live";
  if (p.hist.includes(lc)) return "hist";
  if (p.mid?.includes(lc)) return "mid";
  return LIVE.has(lc) ? "live" : HIST.has(lc) ? "hist" : "mid";                     // other / older statuses as before
}
const LC_PL: Record<string, string> = { CANDIDATE: "KANDYDAT", CONFIRMED: "POTWIERDZONY", FILLED: "OTWARTY", CLOSED: "ZAMKNIĘTY", EXPIRED: "WYGASŁY", INVALIDATED: "UNIEWAŻNIONY",
  REJECTED: "ODRZUCONY", WAIT: "CZEKA", WATCH: "OBSERWACJA", EARLY: "WCZESNY", ACTIVE: "AKTYWNY", OPEN: "OTWARTY",
  WIN: "ZYSK", LOSS: "STRATA", TIMEOUT: "LIMIT CZASU", READY: "GOTOWY", NO_TRADE: "BEZ TRANSAKCJI", EARLY_SETUP: "WCZESNY", QUALIFIED: "KWALIFIKOWANY",
  ARMED: "UZBROJONY", TRIGGERED: "WYZWOLONY", MISSED_ENTRY: "POMINIĘTE WEJŚCIE", ENTERED: "WEJŚCIE", CANCELLED: "ANULOWANY" };
const numOrNull = (v: unknown): number | null => (v == null || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));

function norm(bot: any, setups: any, sh: any): Sig[] {
  const out: Sig[] = [];
  const push = (x: Omit<Sig, "ph">) => out.push({ ...x, ph: phaseOf(x.kind, x.lc, x.raw) });
  for (const x of bot?.items || []) push({ id: "BOT:" + x.signal_id, kind: "BOT", strategy: x.strategy_id ?? "—", name: x.strategy_name ?? "", tf: x.timeframe ?? "", dir: (x.action || x.direction || "").toUpperCase(),
    lc: (x.status || "").toUpperCase(), at: ts(x.created_at), entry: x.entry_price ?? null, sl: x.stop_loss ?? null, tps: x.take_profits || [], rr: x.validation?.rr_weighted ?? x.rr1 ?? null,
    score: x.setup_score ?? null, ai: x.ai_verdict ?? null, reasons: x.validation?.reasons || [], outcome: x.outcome_r ?? null, raw: x });
  for (const x of setups?.items || []) push({ id: "SETUP:" + x.setup_id, kind: "SETUP", strategy: x.strategy_id ?? "—", name: x.strategy_name ?? "", tf: x.timeframe ?? "", dir: (x.direction || "").toUpperCase(),
    lc: (x.status || x.stage || "").toUpperCase(), at: ts(x.created_at), entry: null, sl: null, tps: [], rr: null, score: x.setup_score ?? null, ai: null,
    reasons: x.terminal_reason_pl ? [x.terminal_reason_pl] : [], outcome: null, raw: x });
  // 1.46: /sh/signals (signals_with_levels) gives signal_tf, levels.{entry, sl, targets[].price, net_rr}, plan.r_multiple and strategy_id (variant) -
  // TF, levels and the R result were always empty (and the WYNIKI curve silently skipped closed SH cycles); old field names kept as fallback
  for (const x of sh?.items || []) {
    const L = x.levels || {};
    push({ id: "SH:" + (x.signal_id ?? x.sid ?? x.id), kind: "SH", strategy: x.strategy_id ?? x.strategy ?? x.variant ?? "SH",
      name: x.variant_name ?? x.name ?? (x.strategy_id && x.strategy ? x.strategy : ""), tf: x.signal_tf ?? x.tf ?? x.timeframe ?? "",
      dir: (x.side ?? L.side ?? x.direction ?? "").toUpperCase(), lc: (x.state ?? x.status ?? "").toUpperCase(), at: ts(x.created_at ?? x.at),
      entry: numOrNull(L.entry ?? x.entry), sl: numOrNull(L.sl ?? x.sl),
      tps: Array.isArray(L.targets) ? L.targets.map((t: any) => numOrNull(t?.price)).filter((v: number | null): v is number => v != null) : x.tps ?? [],
      rr: numOrNull(L.net_rr ?? x.rr), score: x.score ?? null, ai: null, reasons: x.reasons ?? (x.status_reason ? [x.status_reason] : []),
      outcome: numOrNull(x.plan?.r_multiple ?? x.outcome_r), raw: x });
  }
  return out.filter((x) => x.at).sort((a, b) => b.at - a.at);
}

// 1.46: catalog ids are lower case (th_logreg, kronos, chronos2, granite_ttm, gold_forecast) while /models/predictions names the models
// TH_LOGREG, Kronos-small, Chronos-2, Granite TTM, gold_candles - the case-sensitive match never hit and every model landed in "BEZ WYNIKU".
// Match without case / separators, a prefix only up to a separator (kronos -> Kronos-small), explicit aliases; a READY prediction first.
// 1.46 arch (I0009): the catalog row and the prediction both carry canonical_id (quant/ids) - an exact match first; a group row
// (group:lab, group:th_direction, group:si_move) never stands for one prediction; the name heuristic only for an older server.
const PRED_ALIAS: Record<string, string[]> = { gold_forecast: ["gold_candles"] };
const nkey = (v: unknown) => String(v ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
function predFor(id: string, preds: any[], canonicalId?: string | null): any {
  const cid = String(canonicalId ?? "");
  if (cid.startsWith("group:")) return undefined;
  if (cid && preds.some((p) => p?.canonical_id)) {
    const exact = preds.filter((p) => p?.canonical_id === cid);
    return exact.find((p) => p.state === "READY") ?? exact[0];
  }
  const keys = [id, ...(PRED_ALIAS[id] || [])].map((k) => String(k).toLowerCase());
  const hit = preds.filter((p) => {
    const n = String(p?.model_name ?? "").toLowerCase();
    return keys.some((k) => n === k || nkey(n) === nkey(k) || (n.startsWith(k) && /[^a-z0-9]/.test(n.charAt(k.length))));
  });
  return hit.find((p) => p.state === "READY") ?? hit[0];
}

export default function SignalsScreen({ engine }: ScreenProps) {
  const { s } = useStore();
  const bot = usePoll<any>("/api/v1/bot-signals?limit=200", 15000);
  const setups = usePoll<any>("/api/v1/setups", 15000);
  const sh = usePoll<any>("/api/v1/sh/signals?limit=200", 15000);
  const all = useMemo(() => norm(bot.data, setups.data, sh.data), [bot.data, setups.data, sh.data]);
  const [tab, setTab] = useState("center");
  const [f, setF] = useState({ src: "ALL", dir: "ALL", range: "24h" });
  const [sel, setSel] = useState<string | null>(null);
  const now = Date.now();
  const rng = { "1h": 3600e3, "24h": 86400e3, "7d": 7 * 86400e3 }[f.range] as number;
  const list = all.filter((x) => (tab === "live" ? x.ph === "live" : tab === "history" ? x.ph === "hist" : true) && (f.src === "ALL" || x.kind === f.src)
    && (f.dir === "ALL" || (f.dir === "WAIT" ? !["BUY", "SELL"].includes(x.dir) : x.dir === f.dir)) && now - x.at <= rng);
  const cur = all.find((x) => x.id === sel) || list[0] || null;
  const mode = s.mode || {};
  // konstelacja: kąt = czas (teraz u góry), pierścień = stan
  useEffect(() => {
    engine?.setScreenData(1, { center: s.quote?.bid != null ? String(s.quote.bid) : "", stars: list.slice(0, 120).map((x) => ({ id: x.id, dir: x.dir, live: x.ph === "live",
      sel: cur?.id === x.id, ring: x.ph === "live" ? 0 : x.ph === "hist" ? 2 : 1, angle: ((now - x.at) / rng) * 6.283 })) });
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const err = bot.err || setups.err;
  return (
    <section id="signals-screen" aria-label="SIGNALS" data-testid="forex-signals">
      <div id="sg-head" className="ci">
        <div id="sg-title" aria-hidden="true"><span className="n">02</span>SIGNALS</div><span className="ch-sep" />
        <div id="sg-asset" className="segb"><button type="button" aria-pressed="true">{s.symbol?.symbol ?? "—"}</button></div><span className="ch-sep" />
        <div id="sg-tabs" className="segb" role="group" aria-label="Widok">{[["center", "CENTRUM"], ["live", "NA ŻYWO"], ["history", "HISTORIA"], ["strategies", "STRATEGIE"], ["perf", "WYNIKI"]].map(([k, l]) =>
          <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
        <div className="gates-sum"><span>TRYB<b>{mode.mode_label ?? mode.mode ?? "—"}</b></span><span>ŚCIEŻKA GŁÓWNA<b>{mode.primary_path ?? "—"}</b></span>
          <span>STOP<b>{mode.kill_switch ? "WŁ." : "WYŁ."}</b></span></div>
      </div>
      <div className="sg-wrap">
        <div id="sg-left" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div id="sg-filters">
            {([["src", "ŹRÓDŁO", [["ALL", "WSZYSTKIE"], ["BOT", "SILNIK"], ["SETUP", "SCENARIUSZE"], ["SH", "SH"]]], ["dir", "KIERUNEK", [["ALL", "WSZYSTKIE"], ["BUY", "BUY"], ["SELL", "SELL"], ["WAIT", "CZEKA"]]],
              ["range", "ZAKRES", [["1h", "1 H"], ["24h", "24 H"], ["7d", "7 D"]]]] as [string, string, string[][]][]).map(([k, lab, opts]) => (
              <div className="fr" key={k}><label>{lab}</label>{opts.map(([v, l]) => <button key={v} type="button" aria-pressed={(f as any)[k] === v} onClick={() => setF({ ...f, [k]: v })}>{l}</button>)}</div>))}
          </div>
          <div id="sg-count">{list.length} SYGNAŁÓW · {all.filter((x) => x.ph === "live").length} AKTYWNYCH</div>
          <div id="sg-stream" role="list" aria-label="Strumień sygnałów" data-testid="signals-list">
            {err && <p className="empty">BŁĄD: {err}</p>}
            {!err && !list.length && <p className="empty">BRAK DANYCH – brak sygnałów dla tych filtrów.</p>}
            {list.map((x, i) => (
              <button key={x.id} type="button" className="sgc" data-lc={x.lc} data-dir={x.dir} aria-pressed={cur?.id === x.id} onClick={() => setSel(x.id)} {...(i === 0 ? { "data-autofocus": "" } : {})}>
                <span className="ic">{x.kind === "SH" ? "⚡" : x.kind === "SETUP" ? "◇" : "↗"}</span><span className="t1"><b>{x.strategy.replace("PMW_", "")}</b> {x.name}</span>
                <span className="pc na"><b>—</b><small>{x.score != null ? "SCORE " + Math.round(x.score) : "BRAK MODELU"}</small></span>
                <span className="t2"><i className="dir">{["BUY", "SELL"].includes(x.dir) ? x.dir : "—"}</i> {x.tf} · {x.kind === "BOT" ? "silnik" : x.kind === "SETUP" ? "scenariusz" : "maszyna SH"}</span>
                <span className="t3"><span className="lc">{LC_PL[x.lc] ?? x.lc}</span><span className="tm">{fmtTime(x.at)}</span></span></button>))}
          </div>
        </div>
        <div id="sg-center" className="ci" data-alt={tab === "strategies" || tab === "perf" ? "1" : "0"}>
          <div id="sg-orbit" aria-label="Konstelacja sygnałów: kąt = czas (teraz u góry), pierścień = stan"
            onClick={(e) => { const id = engine?.nodeAt(1, e.clientX, e.clientY); if (id) setSel(id); }} />
          <div id="sg-alt">{tab === "strategies" && <Strategies all={all} />}{tab === "perf" && <Perf all={all} />}</div>
          <Gates />
        </div>
        <div id="sg-right" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          {cur ? <Detail s={cur} /> : <p className="empty">Wybierz sygnał.</p>}
        </div>
      </div>
    </section>);
}

function Gates() {
  const d = usePoll<any>("/api/v1/decision", 10000).data;
  if (!d) return <div id="sg-gates"><span className="gl">BRAMKI</span><span className="empty">BRAK DANYCH</span></div>;
  const st = (v: any) => (v == null ? "—" : typeof v === "object" ? "—" : String(v));
  // 1.46: mode_gate = ExecutionModes.gate() {mode, allowed, reason_codes, …} has no status field (the step showed "[object Object]" and never
  // said whether the mode blocks orders); agent_gate without a status likewise - the value comes from allowed / reason_codes, the tone from allowed
  const gate = (g: any): [string, string | null] => {
    if (g == null || typeof g !== "object") return [st(g), null];
    if (g.status != null) return [String(g.status), null];
    if (typeof g.allowed === "boolean") return [g.allowed ? "ALLOWED" : "BLOCKED" + (g.reason_codes?.[0] ? " · " + g.reason_codes[0] : ""), g.allowed ? "OK" : "BLOK"];
    return [g.reason_codes?.[0] != null ? String(g.reason_codes[0]) : "—", null];
  };
  const [agV, agT] = gate(d.agent_gate), [mgV, mgT] = gate(d.mode_gate);
  const steps: [string, string, string, string | null][] = [["DANE", "data quality", st(d.data_quality), null], ["KONTEKST", "market state", st(d.market_state), null],
    ["SETUP", d.setup?.strategy_id ?? "—", st(d.setup?.state), null], ["RYZYKO", "risk gate", st(d.risk?.risk_gate), null], ["AGENT AI", "VETO", agV, agT],
    ["TRYB", "mode gate", mgV, mgT], ["WYKONANIE", "permission", st(d.execution_permission), null]];
  return (
    <div id="sg-gates" aria-label="Bramki wykonania" data-testid="signals-gates"><span className="gl">BRAMKI ŚCIEŻKI A · {d.decision ?? ""}</span>
      {steps.map(([n, sub, v, tone], i) => <span key={n} style={{ display: "contents" }}><div className="gt" data-st={tone ?? (/OK|PASS|ALLOW|TRUE|READY/i.test(v) ? "OK" : /BLOCK|DENY|FALSE|ERROR/i.test(v) ? "BLOK" : "—")}>
        <i /><b>{n}</b><small>{sub}</small><em title={v}>{typeof v === "string" ? v.slice(0, 22) : v}</em></div>{i < steps.length - 1 && <span className="ga" />}</span>)}</div>);
}

function Detail({ s }: { s: Sig }) {
  const cat = usePoll<any>("/api/v1/models/catalog?instrument=XAUUSD", 60000).data;
  const pred = usePoll<any>("/api/v1/models/predictions?instrument=XAUUSD", 15000).data;
  const models: any[] = cat?.items || [];
  const preds: any[] = pred?.items || [];
  const up = s.dir === "BUY";
  const rows = models.map((m) => {
    const p = predFor(String(m.id ?? ""), preds, m.canonical_id);
    const ready = p?.state === "READY" || (!p && m.state === "READY");
    const d = p?.result?.direction;
    // 1.46: FLAT / NEUTRAL / any non UP-DOWN direction is neutral for BOTH sides ((d === "UP") === up was true for SELL + FLAT -> "agrees")
    const agree = !p || p.state !== "READY" ? null : !["BUY", "SELL"].includes(s.dir) || (d !== "UP" && d !== "DOWN") ? 0 : (d === "UP") === up ? 1 : -1;
    const c = p ? chanceLabel(p) : null;
    return { m, p, ready, agree, val: p?.state === "READY" ? (c?.pct != null ? Math.round(c.pct * 100) + "%" : d ?? p.unit ?? "OK") : m.state_pl ?? m.state, note: p ? c?.label : m.reason };
  });
  const tot = rows.length, ag = rows.filter((r) => r.agree === 1).length, dis = rows.filter((r) => r.agree === -1).length, neu = rows.filter((r) => r.agree === 0).length, none = tot - ag - dis - neu;
  const groups = [...new Set(models.map((m) => m.group))];
  return (<>
    <div id="sg-dh"><div className="dh"><span className="ic">{s.kind === "SH" ? "⚡" : "↗"}</span><div><b>{s.strategy.replace("PMW_", "")} · {s.name}</b>
      <small>{s.tf} · {s.kind === "BOT" ? "silnik" : s.kind === "SETUP" ? "scenariusz" : "maszyna SH"} · {s.id.split(":")[1]}</small></div>
      <span className="dchip" data-dir={s.dir}>{["BUY", "SELL"].includes(s.dir) ? s.dir : "CZEKA"}</span><span className="lchip" data-lc={s.lc}>{LC_PL[s.lc] ?? s.lc}</span></div></div>
    <div id="sg-mini" role="img" aria-label="Poziomy sygnału"><MiniLevels s={s} /></div>
    <div id="sg-detail" data-testid="signals-detail">
      <div className="big"><div><b className="na">—</b><span>SZANSA · brak skalibrowanego modelu zdarzenia tego sygnału</span></div>
        <div><b>{s.rr != null ? fmt(s.rr) : "—"}</b><span>RR</span></div><div><b>{s.score != null ? Math.round(s.score) : "—"}</b><span>SIŁA SETUPU · SCORE (NIE SZANSA)</span></div></div>
      <div className="sec"><span>KONTEKST SYGNAŁU</span><span>{fmtTime(s.at, true)}</span></div>
      <div className="lv2"><span>WEJŚCIE</span><b>{fmt(s.entry)}</b><span>SL</span><b>{fmt(s.sl)}</b>{s.tps.slice(0, 3).map((t, j) => <span key={j} style={{ display: "contents" }}><span>TP{j + 1}</span><b>{fmt(t)}</b></span>)}
        <span>WYNIK</span><b className={s.outcome == null ? "" : s.outcome > 0 ? "pos" : "neg"}>{s.outcome == null ? "—" : fmt(s.outcome) + " R"}</b></div>
      {s.reasons.length > 0 && <div className="why">{s.reasons.join(" · ")}</div>}
      <div className="sec"><span>OCENA AI</span><span>agent (VETO)</span></div><div className="ai" data-v={s.ai ?? "BRAK"}><b>{s.ai ?? "BRAK"}</b></div>
      <div className="sec"><span>OCENA PROGNOZY — WSZYSTKIE MODELE ({tot})</span><span>✦ ZGODNY · ✕ PRZECIWNY · · NEUTRALNY · ○ BRAK</span></div>
      <div className="cons"><div className="cb"><i style={{ width: `${ag / Math.max(1, tot) * 100}%` }} className="a" /><i style={{ width: `${neu / Math.max(1, tot) * 100}%` }} className="n" />
        <i style={{ width: `${dis / Math.max(1, tot) * 100}%` }} className="d" /><i style={{ width: `${none / Math.max(1, tot) * 100}%` }} className="x" /></div>
        <div className="cl"><span><b>{ag}</b> ZGODNE</span><span><b>{neu}</b> NEUTRALNE</span><span><b>{dis}</b> PRZECIWNE</span><span><b>{none}</b> BEZ WYNIKU</span></div>
        <p>Zgodność kierunku ≠ prawdopodobieństwo. Szansa % tylko z modelu skalibrowanego dla zdarzenia tego sygnału. Modele cenowe liczą z tych samych świec – są skorelowane.</p></div>
      {groups.map((g) => <div className="mg" key={g}><div className="mgh">{g}</div>{rows.filter((r) => r.m.group === g).map((r) => (
        <div key={r.m.id} className={"mr" + (r.ready ? "" : " off")} data-a={r.agree ?? ""}><i className="ag">{r.agree == null ? "○" : r.agree === 1 ? "✦" : r.agree === -1 ? "✕" : "·"}</i>
          <span className="mn" title={r.m.id}>{r.m.name}</span><span className="mk">{r.m.category}</span><b className="mv">{r.val}</b><span className="mb e" />{r.note && <small>{String(r.note).slice(0, 90)}</small>}</div>))}</div>)}
      <div className="note">Siła setupu to heurystyka. Otwarcie widoku nie wysyła zlecenia.</div>
    </div></>);
}

function MiniLevels({ s }: { s: Sig }) {
  const lv = [s.entry, s.sl, ...s.tps].filter((v): v is number => v != null && isFinite(v));
  if (!lv.length) return <p className="empty">Brak poziomów planu.</p>;
  const W = 360, H = 120, mn = Math.min(...lv), mx = Math.max(...lv), Y = (v: number) => 10 + (mx - v) / (mx - mn || 1) * (H - 20);
  const ln = (v: number | null, c: string, l: string, d?: string) => v == null ? null : <g key={l}><line x1={20} x2={W - 50} y1={Y(v)} y2={Y(v)} stroke={c} strokeDasharray={d} />
    <text x={W - 46} y={Y(v) + 3} fill={c} fontSize="9">{l} {fmt(v)}</text></g>;
  return <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>{ln(s.sl, "rgba(222,150,150,.9)", "SL", "4 3")}{s.tps.map((v, j) => ln(v, "rgba(178,226,200,.85)", "TP" + (j + 1), "3 3"))}{ln(s.entry, "rgba(242,242,239,.95)", "WEJŚCIE")}</svg>;
}

function Strategies({ all }: { all: Sig[] }) {
  const ids = [...new Set(all.map((x) => x.strategy))];
  if (!ids.length) return <p className="empty">BRAK DANYCH</p>;
  return <div className="sgrid">{ids.map((id) => { const ss = all.filter((x) => x.strategy === id), live = ss.filter((x) => x.ph === "live").length; return (
    <div key={id} className="scard" data-live={live > 0}><b>{id.replace("PMW_", "")}</b><small>{ss[0]?.name}</small><em>{live ? live + " AKTYWNE" : ss.length + " SYGNAŁÓW"}</em></div>); })}</div>;
}

function Perf({ all }: { all: Sig[] }) {
  const closed = all.filter((x) => x.outcome != null).sort((a, b) => a.at - b.at);
  if (!closed.length) return <p className="empty">BRAK DANYCH – brak zamkniętych sygnałów z wynikiem R.</p>;
  let eq = 0;
  const pts = closed.map((x) => (eq += x.outcome as number)), mx = Math.max(...pts.map(Math.abs), 1);
  return (<div className="perf"><div className="eq"><svg viewBox="0 0 400 90" preserveAspectRatio="none"><line x1="0" y1="45" x2="400" y2="45" stroke="#2b303b" />
    <polyline fill="none" stroke="#dfe3eb" strokeWidth="1.2" points={pts.map((v, i) => `${i / Math.max(1, pts.length - 1) * 400},${45 - v / mx * 40}`).join(" ")} /></svg>
    <span>KRZYWA R · {closed.length} ZAMKNIĘTYCH · SUMA {eq >= 0 ? "+" : ""}{fmt(eq)} R</span></div>
    <p className="note">Win % to częstość historyczna, nie prawdopodobieństwo.</p></div>);
}
