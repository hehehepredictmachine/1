// Nodes and edges of the two model-flow maps of the main menu, built ONLY from what the bot reports: the store (MT5 connection,
// interval metadata, engine decision), /api/v1/telemetry (publishing activity per event topic, model registry with statuses,
// SCALPING / HEDGING state) and the live event tap (telemetry.ts). This is a map of program modules and their observed data flow -
// not a neuron topology. An edge exists only where the code connects the modules (registry participation, decision tree, data path);
// an impulse runs along an edge only when the corresponding real event arrives.
export type NodeStatus = "active" | "waiting" | "offline" | "error" | "disabled";
export type FlowNode = {
  id: string; label: string; ring: 0 | 1 | 2 | 3; status: NodeStatus; detail: string; lastAt: number | null;
  topics: string[]; metrics: [string, string][]; href?: string; strategies?: string[]; shape?: "square" | "circle";
};
export type FlowEdge = { a: string; b: string; dashed?: boolean };
export type FlowModel = { nodes: FlowNode[]; edges: FlowEdge[]; routes: Record<string, [string, string][]>; core: string; title: string };

export const STATUS_PL: Record<NodeStatus, string> = { active: "aktywny", waiting: "oczekujący", offline: "offline", error: "błąd", disabled: "nieaktywny / niewytrenowany" };
const RECENT_MS = 120_000;
const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export type LastSeen = (key: string) => number | null;   // local receive time (ms) of a topic or "bar:<TF>"

function serverLast(tele: any, topic: string): number | null {
  const ts = tele?.topics?.[topic]?.last_ts;
  if (!ts) return null;
  const t = Date.parse(ts);
  // server time -> local clock: shift by the difference between the server's clock and ours at the response
  const skew = tele?.server_time && tele?._received_at ? tele._received_at - tele.server_time * 1000 : 0;
  return Number.isFinite(t) ? t + skew : null;
}

function lastOf(tele: any, seen: LastSeen, topics: string[]): number | null {
  let best: number | null = null;
  for (const tp of topics) for (const t of [seen(tp), serverLast(tele, tp)]) if (t && (!best || t > best)) best = t;
  return best;
}

function byRecency(last: number | null, now: number): NodeStatus {
  return last && now - last < RECENT_MS ? "active" : "waiting";
}

/** Left map: MT5 -> bridge data -> data quality -> analysis modules -> analysis core. */
export function dataModel(s: any, tele: any, seen: LastSeen, now: number, link: string): FlowModel {
  const off = link !== "OPEN";
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const conn = s.connection?.state;
  const add = (n: Omit<FlowNode, "lastAt" | "status"> & { status?: NodeStatus; lastAt?: number | null }) => {
    const last = n.lastAt !== undefined ? n.lastAt : lastOf(tele, seen, n.topics);
    nodes.push({ ...n, lastAt: last, status: off ? "offline" : n.status ?? byRecency(last, now) } as FlowNode);
  };
  add({ id: "core", label: "Analiza rynku", ring: 0, topics: ["analysis"], detail: "Wyniki analiz przekazywane do strategii", metrics: [], href: "#/precision" });
  add({ id: "mt5", label: "Terminal MT5", ring: 1, topics: ["connection", "quote"], shape: "circle",
    status: !conn ? "offline" : conn === "CONNECTED" ? "active" : "error",
    detail: conn ? `stan: ${conn}${s.connection?.reason ? ` – ${s.connection.reason}` : ""}` : "brak statusu połączenia",
    metrics: [["Symbol", s.symbol?.symbol ?? "—"], ["Rachunek", s.account?.trade_mode ?? "—"], ["Tick", s.quote?.age_seconds != null ? `${Math.round(s.quote.age_seconds)} s temu` : "—"]],
    href: "#/diagnostyka" });
  add({ id: "quote", label: "Notowania Bid/Ask", ring: 2, topics: ["quote"], detail: "tick z terminala (worker MT5)",
    metrics: [["Bid", s.quote?.bid != null ? String(s.quote.bid) : "—"], ["Ask", s.quote?.ask != null ? String(s.quote.ask) : "—"]] });
  add({ id: "clock", label: "Zegar serwera", ring: 2, topics: ["clock"], detail: `offset: ${s.connection?.clock?.status ?? "—"}`, metrics: [] });
  add({ id: "account", label: "Rachunek i pozycje", ring: 2, topics: ["account", "positions"], detail: "saldo, equity, otwarte pozycje",
    metrics: [["Equity", s.account?.equity != null ? `${s.account.equity} ${s.account.currency ?? ""}` : "—"]], href: "#/profits" });
  edges.push({ a: "mt5", b: "quote" }, { a: "mt5", b: "clock" }, { a: "mt5", b: "account" });
  for (const tf of TFS) {
    const meta = s.tf_meta?.[tf];
    const last = lastOf(tele, seen, [`bar:${tf}`]);
    add({ id: `bar:${tf}`, label: `Świece ${tf}`, ring: 2, topics: [`bar:${tf}`], lastAt: last,
      status: meta && meta.loaded === false ? "offline" : byRecency(last, now),
      detail: meta ? (meta.loaded === false ? "brak danych tego interwału" : `zamknięte świece z MT5${meta.bars ? ` (${meta.bars})` : ""}`) : "brak metadanych interwału",
      metrics: [], href: `#/precision?tf=${tf}` });
    edges.push({ a: "mt5", b: `bar:${tf}` }, { a: `bar:${tf}`, b: "dq" });
  }
  const dq = s.decision?.data_quality;
  add({ id: "dq", label: "Jakość danych", ring: 1, topics: ["dq"], shape: "circle",
    status: !dq ? "waiting" : dq === "GOOD" ? "active" : dq === "DEGRADED" ? "waiting" : "error",
    detail: dq ? `werdykt silnika: ${dq}` : "silnik nie podał jakości danych", metrics: [["Rynek", s.decision?.market_state ?? "—"]] });
  edges.push({ a: "quote", b: "dq" });
  const modules: [string, string, string[], string, string?][] = [
    ["analysis", "Analiza silnika (reżim, struktura)", ["analysis", "decision"], "MQ-REGIME / structure_v2 na zamkniętych świecach", "#/precision"],
    ["zones", "Strefy High/Low", ["zones"], "HLZE + DSVIE + UZICE – mapa stref M5/M15", "#/precision"],
    ["analytics", "Analityka BB/MA, FFT/VMD/EMD", ["analytics"], "AnalyticsService", "#/indykatory"],
    ["structure", "Structure Intelligence", ["structure_intelligence", "structure_quotes"], "struktura i kwotowania (SHADOW)", "#/struktura"],
    ["liquidity", "Płynność (sesje, heatmapa)", ["liquidity"], "sweep boxes, heatmapa likwidacji", "#/wykresy"],
    ["forecast", "Prognozy świec gold_candles", ["forecast"], "ForecastService (SHADOW)", "#/testy"],
    ["scalp", "Scalp M5→M1 (profil)", ["scalp", "scalp_dashboard", "scalp_dashboard_health"], "ScalpService (SHADOW)", "#/scalp-mtf"],
    ["markets", "Skaner rynków", ["markets"], "MarketScanner – wiele symboli", "#/pulpit"],
    ["lab", "Lab i Neural", ["lab", "lab_neural"], "LabService, NSS", "#/neural"],
    ["extind", "Kontekst wskaźników SAR/IQ", ["extind"], "IndicatorContext (SHADOW)", "#/kontekst"],
  ];
  for (const [id, label, topics, detail, href] of modules) {
    add({ id, label, ring: 3, topics, detail, metrics: [], href });
    edges.push({ a: "dq", b: id }, { a: id, b: "core" });
  }
  const routes: FlowModel["routes"] = {
    quote: [["mt5", "quote"]], clock: [["mt5", "clock"]], account: [["mt5", "account"]], positions: [["mt5", "account"]],
    dq: [["quote", "dq"]], analysis: [["dq", "analysis"], ["analysis", "core"]], decision: [["analysis", "core"]],
    zones: [["dq", "zones"], ["zones", "core"]], analytics: [["dq", "analytics"], ["analytics", "core"]],
    structure_intelligence: [["dq", "structure"], ["structure", "core"]], structure_quotes: [["dq", "structure"]],
    liquidity: [["dq", "liquidity"], ["liquidity", "core"]], forecast: [["dq", "forecast"], ["forecast", "core"]],
    scalp: [["dq", "scalp"], ["scalp", "core"]], scalp_dashboard: [["dq", "scalp"]], markets: [["dq", "markets"], ["markets", "core"]],
    lab: [["dq", "lab"], ["lab", "core"]], lab_neural: [["dq", "lab"]], extind: [["dq", "extind"], ["extind", "core"]],
  };
  for (const tf of TFS) routes[`bar:${tf}`] = [["mt5", `bar:${tf}`], [`bar:${tf}`, "dq"]];
  return { nodes, edges, routes, core: "core", title: "Przepływ danych i analizy" };
}

const MODEL_TOPICS: Record<string, string[]> = {
  data_quality: ["dq"], risk_engine: ["account", "positions"], news: ["news"], regime_v2: ["analysis"], structure_v2: ["analysis"],
  liquidity: ["liquidity"], decomposition: ["analytics"], sh_tp_model: ["sh"], scalp_A: ["scalp"], scalp_B: ["scalp"],
  gold_forecast: ["forecast"], legacy_ml: ["ml"], lab: ["lab"], indicator_context: ["extind"], ml_scalp: ["ml_scalp"], nss: ["lab_neural"],
  si_move: ["structure_intelligence"],
};
const MODEL_STATUS: Record<string, [NodeStatus, string]> = {
  READY: ["active", "gotowy (walidacja zaliczona)"], DETERMINISTIC_OK: ["active", "obliczenia deterministyczne – działa"],
  SHADOW_ONLY: ["waiting", "SHADOW – obserwacja, bez wpływu na decyzje"], NOT_TRAINED: ["disabled", "niewytrenowany"],
};
const TREE_PL: Record<string, string> = { DATA: "Dane", MARKET: "Rynek", STRATEGY: "Strategia", TRIGGER: "Wyzwalacz", RISK: "Ryzyko", AI: "Agent AI", ML: "Model ML", PERMISSION: "Zgoda na wykonanie" };
const TREE_STATUS: Record<string, NodeStatus> = { PASS: "active", MET: "active", FAIL: "error", MISSING: "error", PENDING: "waiting", NO_DATA: "offline" };

/** Right map: models of the registry -> SCALPING / HEDGING (real participation) and the engine's decision tree -> decisions core. */
export function modelsModel(s: any, tele: any, seen: LastSeen, now: number, link: string): FlowModel {
  const off = link !== "OPEN";
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const d = s.decision || tele?.engine || {};
  const coreLast = lastOf(tele, seen, ["decision", "sh", "bot_signal", "signal"]);
  nodes.push({ id: "core", label: "Decyzje", ring: 0, topics: ["decision", "sh", "bot_signal"], lastAt: coreLast, status: off ? "offline" : byRecency(coreLast, now),
    detail: `silnik: ${d.decision ?? "—"} · etap sygnału ${d.signal_stage ?? "—"}`, metrics: [["Zgoda na wykonanie", s.decision?.execution_permission ?? "—"]],
    href: "#/dyscypline", shape: "circle" });
  const sh = tele?.sh || {};
  for (const st of ["SCALPING", "HEDGING"]) {
    const ev = sh.last_eval?.[st];
    const last = lastOf(tele, seen, ["sh"]);
    nodes.push({ id: st, label: st, ring: 1, topics: ["sh"], lastAt: last, shape: "circle", strategies: [st],
      status: off ? "offline" : !ev ? "waiting" : ev.status === "READY" ? "active" : ev.status === "ERROR" ? "error" : "waiting",
      detail: ev ? `setup ${ev.status}${ev.side ? ` ${ev.side}` : ""}${ev.status_reason ? ` – ${ev.status_reason}` : ""}` : `serwis: ${sh.status ?? "brak danych"}`,
      metrics: [["Ocena setupu (heurystyka, nie prawdopodobieństwo)", ev?.score != null ? String(ev.score) : "—"]], href: "#/dyscypline" });
    edges.push({ a: st, b: "core" });
  }
  const tree: any[] = s.decision?.decision_tree || tele?.engine?.tree || [];
  for (const n of tree) {
    const id = `tree:${n.node}`;
    nodes.push({ id, label: TREE_PL[n.node] ?? n.node, ring: 1, topics: ["decision"], lastAt: lastOf(tele, seen, ["decision"]), shape: "circle", strategies: ["S01–S12"],
      status: off ? "offline" : TREE_STATUS[n.status] ?? "waiting", detail: `węzeł decyzji silnika S01–S12: ${n.status}`,
      metrics: (n.reason_codes || []).slice(0, 3).map((c: string) => ["Powód", c] as [string, string]), href: "#/dyscypline" });
    edges.push({ a: id, b: "core" });
  }
  const rows: any[] = tele?.models?.rows || [];
  for (const r of rows) {
    const [st, label] = MODEL_STATUS[r.status] ?? [/ERR|FAIL|BLOCK|UNAVAIL|INCOMPAT/.test(String(r.status)) ? "error" : "waiting", String(r.status)];
    const topics = MODEL_TOPICS[r.id] ?? [];
    const used = ["SCALPING", "HEDGING"].filter((k) => (r.roles?.[k]?.use ?? "NONE") !== "NONE");
    nodes.push({ id: `m:${r.id}`, label: r.name, ring: r.kind === "TRAINED" ? 3 : 2, topics, lastAt: lastOf(tele, seen, topics),
      status: off ? "offline" : st, strategies: used, shape: "square",
      detail: `${label}${r.reason ? ` – ${r.reason}` : ""}`,
      metrics: [["Rodzaj", r.kind], ["Wyjście", r.output ?? "—"], ...["SCALPING", "HEDGING"].map((k) => [k, `${r.roles?.[k]?.role ?? "—"} / ${r.roles?.[k]?.use ?? "—"}`] as [string, string]),
        ["Trening", r.train ?? "nie dotyczy"]], href: "#/modele" });
    for (const k of used) edges.push({ a: `m:${r.id}`, b: k, dashed: ["INFO", "GATE_UNAVAILABLE"].includes(r.roles?.[k]?.use) });
    if (r.id === "legacy_ml" && tree.some((n) => n.node === "ML")) edges.push({ a: `m:${r.id}`, b: "tree:ML" });
    if (r.id === "data_quality" && tree.some((n) => n.node === "DATA")) edges.push({ a: `m:${r.id}`, b: "tree:DATA" });
    if (r.id === "risk_engine" && tree.some((n) => n.node === "RISK")) edges.push({ a: `m:${r.id}`, b: "tree:RISK" });
    if (r.id === "agent" && tree.some((n) => n.node === "AI")) edges.push({ a: `m:${r.id}`, b: "tree:AI" });
  }
  const routes: FlowModel["routes"] = {
    sh: [["SCALPING", "core"], ["HEDGING", "core"]],
    decision: tree.map((n) => [`tree:${n.node}`, "core"] as [string, string]),
    auto: tree.some((n) => n.node === "STRATEGY") ? [["tree:STRATEGY", "core"]] : [],
  };
  for (const [mid, topics] of Object.entries(MODEL_TOPICS)) {
    const out = edges.filter((e) => e.a === `m:${mid}`).map((e) => [e.a, e.b] as [string, string]);
    for (const tp of topics) routes[tp] = [...(routes[tp] || []), ...out];
  }
  return { nodes, edges, routes, core: "core", title: "Modele, agregacja i decyzje" };
}

export function statusColor(st: NodeStatus): string {
  return st === "active" ? "#3fe6ff" : st === "waiting" ? "#9b7bff" : st === "error" ? "#ff5f7a" : st === "disabled" ? "#5d6382" : "#3d4054";
}
