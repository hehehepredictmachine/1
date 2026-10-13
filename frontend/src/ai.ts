// Typed presentation adapter for the agent's result (contract: backend agent/schema.py, MQAI agent record). It only
// normalises missing fields and decides how CURRENT the answer is; it never generates an opinion or a confidence.
export type AiAction = "BUY" | "SELL" | "WAIT" | "NO_TRADE";
export type AiScenario = { summary: string; activation: string[]; invalidation: string[] };
export type AiRecord = {
  snapshot_id?: string; setup_id: string | null; analysis_direction: "LONG" | "SHORT" | "NEUTRAL"; signal_stage: string; proposed_action: AiAction;
  strategy_id: string | null; preferred_strategy_id?: string | null; scenario_still_valid?: boolean; entry_zone: { low: number; high: number } | null;
  invalidation_level: number | null; proposed_targets: number[]; scenarios: { bullish: AiScenario; bearish: AiScenario; wait: AiScenario };
  evidence_refs: string[]; contradictions: string[]; missing_data: string[]; reason_codes: string[]; explanation_pl: string; answer_pl: string | null;
  decision_id?: string; as_of_utc?: string; expires_at_utc?: string; model_id?: string; prompt_version?: string;
};
/** CURRENT = valid answer for the setup the engine works on now. Everything else is history and is labelled as such. */
export type AiState = "CURRENT" | "EXPIRED" | "OTHER_SETUP" | "SCENARIO_ENDED" | "NO_KEY" | "NO_ANSWER" | "ERROR_LAST_RUN" | "RUNNING";

export const ACTION_PL: Record<AiAction, string> = { BUY: "KUPNO", SELL: "SPRZEDAŻ", WAIT: "CZEKAJ", NO_TRADE: "BEZ TRANSAKCJI" };
export const DIR_PL: Record<string, string> = { LONG: "wzrostowy (LONG)", SHORT: "spadkowy (SHORT)", NEUTRAL: "neutralny" };
export const STAGE_PL: Record<string, string> = { WATCH: "obserwacja", EARLY: "wczesny", CONFIRMED: "potwierdzony", EXPIRED: "wygasły", INVALIDATED: "unieważniony" };
export const STATE_PL: Record<AiState, string> = {
  CURRENT: "aktualna", EXPIRED: "WYGASŁA – historia, nie aktualny sygnał", OTHER_SETUP: "dotyczy INNEGO setupu niż obecny wybór silnika – historia",
  SCENARIO_ENDED: "AI uznało scenariusz za nieaktualny", NO_KEY: "AI niedostępne – brak klucza ANTHROPIC_API_KEY (ustawiasz lokalnie)",
  NO_ANSWER: "brak odpowiedzi AI", ERROR_LAST_RUN: "ostatni przebieg AI zakończony błędem – pokazana poprzednia udana ocena (historia)", RUNNING: "AI analizuje…",
};

const arr = (x: any): string[] => (Array.isArray(x) ? x.filter((v) => typeof v === "string") : []);
const scen = (x: any): AiScenario => ({ summary: typeof x?.summary === "string" ? x.summary : "", activation: arr(x?.activation), invalidation: arr(x?.invalidation) });

export function normalize(rec: any): AiRecord | null {
  if (!rec || typeof rec !== "object" || !rec.proposed_action) return null;
  return {
    ...rec,
    setup_id: rec.setup_id ?? null, strategy_id: rec.strategy_id ?? null, entry_zone: rec.entry_zone ?? null, invalidation_level: rec.invalidation_level ?? null,
    proposed_targets: Array.isArray(rec.proposed_targets) ? rec.proposed_targets.filter((v: any) => typeof v === "number") : [],
    scenarios: { bullish: scen(rec.scenarios?.bullish), bearish: scen(rec.scenarios?.bearish), wait: scen(rec.scenarios?.wait) },
    evidence_refs: arr(rec.evidence_refs), contradictions: arr(rec.contradictions), missing_data: arr(rec.missing_data), reason_codes: arr(rec.reason_codes),
    explanation_pl: typeof rec.explanation_pl === "string" ? rec.explanation_pl : "", answer_pl: rec.answer_pl ?? null,
  };
}

/** How current the last successful answer is, judged against the engine's present setup and the clock. */
export function aiState(s: any, now: number): { state: AiState; rec: AiRecord | null; last: any; lastAny: any } {
  const last = s.agent_last;
  const lastAny = s.agent_last_any;
  const rec = normalize(last?.record);
  const engineSetup = s.decision?.signal_view?.setup_id ?? null;
  let state: AiState;
  if (!rec) state = s.agent?.state === "AI_UNAVAILABLE_NO_KEY" ? "NO_KEY" : s.agent?.state === "RUNNING" ? "RUNNING" : "NO_ANSWER";
  else if (lastAny && lastAny.status !== "OK" && lastAny.run_id !== last?.run_id) state = "ERROR_LAST_RUN";
  else if (rec.expires_at_utc && Date.parse(rec.expires_at_utc) <= now) state = "EXPIRED";
  else if ((last?.setup_id ?? rec.setup_id ?? null) !== engineSetup && (rec.setup_id || engineSetup)) state = "OTHER_SETUP";
  else if (rec.scenario_still_valid === false) state = "SCENARIO_ENDED";
  else state = "CURRENT";
  return { state, rec, last, lastAny };
}
