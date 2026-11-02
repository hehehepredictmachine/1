// One presentation shape for setups and signals of the three real sources: the engine S01–S12 (selected setup + candidate ranking),
// SCALPING / HEDGING (the SH service's last evaluation and open plans) and the bot's signals. States are mapped from the backend's
// own states - nothing is inferred. A score is called "ocena setupu" (a heuristic); a probability is shown only when the backend
// marks it calibrated.
export type UiState = "OBSERWACJA" | "FORMUJE_SIE" | "GOTOWY" | "AKTYWNY" | "UNIEWAZNIONY" | "WYGASLY" | "ZAKONCZONY";
export const UI_STATE_PL: Record<UiState, string> = {
  OBSERWACJA: "obserwacja", FORMUJE_SIE: "setup formujący się", GOTOWY: "setup gotowy", AKTYWNY: "sygnał aktywny",
  UNIEWAZNIONY: "setup unieważniony", WYGASLY: "wygasły", ZAKONCZONY: "zakończony",
};
export type Cond = { label: string; ok: boolean | null; detail?: string };
export type SetupItem = {
  key: string; source: "SILNIK" | "SCALPING" | "HEDGING" | "SYGNAŁ"; instrument: string; strategy: string; tf: string | null;
  side: "BUY" | "SELL" | null; state: UiState; stateRaw: string; createdAt: string | number | null; validUntil: string | number | null;
  conditions: Cond[]; trigger: string | null; invalidation: string | null; entry: string | null; sl: number | null; tps: number[];
  reasons: string[]; against: string[]; conflicts: string[]; score: number | null; probability: { value: number; event: string } | null;
  risk: string[]; chartTf: string; raw: any;
};

const side = (d: any): "BUY" | "SELL" | null => (d === "LONG" || d === "BUY" ? "BUY" : d === "SHORT" || d === "SELL" ? "SELL" : null);
const ENGINE_STATE: Record<string, UiState> = { WATCH: "OBSERWACJA", EARLY: "FORMUJE_SIE", CONFIRMED: "GOTOWY", INVALIDATED: "UNIEWAZNIONY",
  EXPIRED: "WYGASLY", MISSED_ENTRY: "WYGASLY", CANCELLED: "UNIEWAZNIONY" };

/** Engine S01–S12: the selected setup with the full decision (plan, checklist, gates) + the other candidates of the AUTO ranking. */
export function engineSetups(s: any): SetupItem[] {
  const d = s.decision;
  const out: SetupItem[] = [];
  const inst = s.symbol?.symbol ?? s.assets?.active ?? "—";
  if (d?.setup) {
    const st = d.setup;
    const lv = d.levels || {}, risk = d.risk || {}, cl = d.checklist || {};
    const active = (d.decision === "BUY" || d.decision === "SELL") && d.execution_permission === "ALLOWED";
    const items: any[] = d.signal_view?.checklist || [];
    const ml = d.ml || {};
    const conflicts: string[] = [];
    if (ml.direction && side(ml.direction) && side(ml.direction) !== side(st.direction)) conflicts.push(`model ML wskazuje ${ml.direction}, setup ${st.direction}`);
    if (d.agent_gate?.status && !["PASS", "NOT_REQUIRED", "SKIPPED", "DISABLED"].includes(d.agent_gate.status)) conflicts.push(`agent AI: ${d.agent_gate.status}`);
    if (st.countertrend) conflicts.push("setup przeciw trendowi wyższego interwału");
    const nodes: any[] = d.decision_tree || [];
    out.push({
      key: `engine:${st.setup_id}`, source: "SILNIK", instrument: inst, strategy: `${st.strategy_id} ${st.strategy_name}`, tf: st.setup_tf ?? null,
      side: side(st.direction), state: active ? "AKTYWNY" : ENGINE_STATE[st.state] ?? "OBSERWACJA", stateRaw: `${st.state} · decyzja ${d.decision}`,
      createdAt: st.created_at ?? null, validUntil: d.expires_at_utc ?? null,
      conditions: items.length ? items.map((c) => ({ label: c.label, ok: c.status === "MET" || c.status === "PASS" ? true : c.status === "NO_DATA" || c.status === "PENDING" ? null : false, detail: c.desc }))
        : (st.missing_confirmations || []).map((m: string) => ({ label: m, ok: false })),
      trigger: cl.trigger?.description ?? st.entry_plan?.trigger ?? null,
      invalidation: cl.invalidation?.event ? `${cl.invalidation.event}${cl.invalidation.level != null ? ` (${px(cl.invalidation.level)})` : ""}` : st.invalidation_level != null ? px(st.invalidation_level) : null,
      entry: risk.entry != null ? px(risk.entry) : lv.entry_zone ? `${px(lv.entry_zone[0])} – ${px(lv.entry_zone[1])}` : null,
      sl: risk.stop_loss ?? lv.stop_loss ?? null, tps: (risk.targets || lv.targets || []).map((t: any) => t.price),
      reasons: [...Object.entries(st.score_points || st.score_breakdown || {}).filter(([, v]) => Number(v) > 0).map(([k, v]) => `${k}: ${v} pkt`),
        ...(st.reasons || []).map(String),
        ...items.filter((c) => c.status === "MET" || c.status === "PASS").map((c) => `potwierdzone: ${c.label}`)],
      against: nodes.filter((n) => n.status !== "PASS").map((n) => `${n.node}: ${(n.reason_codes || []).join(", ") || n.status}`),
      conflicts, score: st.setup_score ?? null,
      probability: ml.calibrated_probability != null && ml.calibration_status === "CALIBRATED" ? { value: ml.calibrated_probability, event: ml.event ?? "zdarzenie modelu ML" } : null,
      risk: [`bramka ryzyka: ${risk.risk_gate ?? "—"}`, `zgoda na wykonanie: ${d.execution_permission ?? "—"}`, ...(risk.limits_missing?.length ? [`brak limitów: ${risk.limits_missing.join(", ")}`] : [])],
      chartTf: st.setup_tf ?? "M15", raw: d,
    });
  }
  for (const c of s.auto?.candidate_ranking || []) {
    if (d?.setup && c.setup_id === d.setup.setup_id) continue;
    out.push({
      key: `engine:${c.setup_id}`, source: "SILNIK", instrument: inst, strategy: `${c.strategy_id} ${c.strategy_name}`, tf: c.timeframe ?? null,
      side: side(c.direction), state: ENGINE_STATE[c.stage] ?? "OBSERWACJA", stateRaw: `${c.stage}${c.trade === false ? " · tylko sygnał" : ""}`,
      createdAt: null, validUntil: null, conditions: Object.entries(c.score_points || {}).map(([k, v]) => ({ label: k, ok: Number(v) > 0, detail: `${v} pkt` })),
      trigger: null, invalidation: null, entry: null, sl: null, tps: [], reasons: [`dopasowanie strategii ${c.strategy_fit_score ?? "—"}`],
      against: c.countertrend ? ["przeciw trendowi wyższego interwału"] : [], conflicts: [], score: c.setup_score ?? null, probability: null,
      risk: ["kandydat rankingu AUTO – plan i bramki tylko dla setupu wybranego przez silnik"], chartTf: c.timeframe ?? "M15", raw: c,
    });
  }
  return out;
}

const SH_STATE: Record<string, UiState> = { NO_TRADE: "OBSERWACJA", WAIT: "FORMUJE_SIE", READY: "GOTOWY", INVALIDATED: "UNIEWAZNIONY", EXPIRED: "WYGASLY" };

/** SCALPING / HEDGING: last evaluation of each strategy; an open plan of the strategy = active signal. */
export function shSetups(sh: any, now = Date.now() / 1000): SetupItem[] {
  if (!sh) return [];
  const out: SetupItem[] = [];
  for (const [strat, su] of Object.entries<any>(sh.last_eval || {})) {
    const open = (sh.open_plans || []).find((p: any) => p.strategy === strat);
    const expired = su.valid_until && su.valid_until < now && su.status === "READY";
    const prob = su.probability?.status === "SKALIBROWANE" && su.probability?.value != null ? { value: su.probability.value, event: su.probability.event } : null;
    const risk = su.risk || {};
    out.push({
      key: `sh:${strat}`, source: strat === "HEDGING" ? "HEDGING" : "SCALPING", instrument: su.symbol ?? su.instrument ?? "—", strategy: strat, tf: "M1 / M5",
      side: side(su.side), state: open ? "AKTYWNY" : expired ? "WYGASLY" : SH_STATE[su.status] ?? "OBSERWACJA",
      stateRaw: `${su.status}${su.status_reason ? ` – ${su.status_reason}` : ""}${open ? ` · plan ${open.plan_id} (${open.state})` : ""}`,
      createdAt: su.created_at ? su.created_at * 1000 : null, validUntil: su.valid_until ? su.valid_until * 1000 : null,
      conditions: (su.checklist || []).map((c: any) => ({ label: c.label, ok: c.status === "PASS" ? true : c.status === "WAIT" ? null : false, detail: c.detail })),
      trigger: (su.checklist || []).find((c: any) => c.id === "trigger")?.detail ?? null,
      invalidation: su.invalidation != null ? px(su.invalidation) : null, entry: su.entry_ref != null ? px(su.entry_ref) : null,
      sl: su.sl ?? null, tps: (su.tps || []).map((t: any) => t.price), reasons: su.args_for || [], against: su.args_against || [],
      conflicts: [...(su.coordination && su.coordination.decision !== "PROCEED" ? [`koordynator: ${su.coordination.reason ?? su.coordination.decision}`] : []),
        ...(su.entry_block || []).map((x: string) => `blokada nowych wejść: ${x}`)],
      score: su.score?.value ?? null, probability: prob,
      risk: [`ryzyko: ${risk.status ?? "nie oceniono (setup nie był gotowy)"}`, ...(risk.reasons || []), `tryb modeli: ${su.model_mode ?? "—"}`],
      chartTf: "M1", raw: su,
    });
  }
  return out;
}

const SIG_STATE: Record<string, UiState> = { OPEN: "AKTYWNY", PENDING: "GOTOWY", SIGNAL: "GOTOWY", REJECTED: "UNIEWAZNIONY", STALE: "WYGASLY", TIMEOUT: "WYGASLY",
  EXPIRED: "WYGASLY", WIN: "ZAKONCZONY", LOSS: "ZAKONCZONY", CLOSED: "ZAKONCZONY", INVALIDATED: "UNIEWAZNIONY" };

/** Bot signals (S01–S12 on the scanned markets). */
export function botSignals(s: any): SetupItem[] {
  return (s.bot_signals?.items || []).slice(0, 30).map((x: any) => ({
    key: `sig:${x.signal_id}`, source: "SYGNAŁ", instrument: x.symbol ?? "—", strategy: `${x.strategy_id ?? ""} ${x.strategy_name ?? ""}`.trim() || "—",
    tf: x.timeframe ?? null, side: side(x.action), state: SIG_STATE[x.status] ?? "OBSERWACJA", stateRaw: `${x.status}${x.error ? ` – ${x.error}` : ""}`,
    createdAt: x.created_at ?? null, validUntil: null,
    conditions: Object.entries(x.validation || {}).filter(([, v]) => typeof v === "boolean").map(([k, v]) => ({ label: k, ok: v as boolean })),
    trigger: x.trigger ?? null, invalidation: null, entry: x.entry_price != null ? px(x.entry_price) : null, sl: x.stop_loss ?? null,
    tps: (x.take_profits || []).map((t: any) => (typeof t === "number" ? t : t.price)), reasons: x.detail ? [String(x.detail).slice(0, 200)] : [],
    against: [], conflicts: x.ai_verdict && x.ai_verdict !== "AGREE" ? [`agent AI: ${typeof x.ai_verdict === "string" ? x.ai_verdict : JSON.stringify(x.ai_verdict)}`] : [],
    score: x.setup_score ?? null, probability: null, risk: [x.synthetic ? "dane syntetyczne" : "sygnał z danych terminala"], chartTf: x.timeframe ?? "M15", raw: x,
  }));
}

/** A price for display: numbers rounded to 2 decimals, text passed through. */
function px(v: unknown): string {
  const n = typeof v === "number" ? v : typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v.trim()) ? Number(v) : NaN;
  return Number.isFinite(n) ? n.toFixed(2) : String(v);
}
