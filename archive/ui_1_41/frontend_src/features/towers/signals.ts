// PEPE$SIGNAL – one registry of signals from every source the bot really has (no hand-written catalogue):
//   BOT   /api/v1/bot-signals   confirmed signals of S01–S12 (main engine + market scanner) and the SH / SHADOW sources, with plan,
//                               validation and outcome in R
//   SETUP /api/v1/setups        engine scenarios S01–S12 of the active instrument (WATCH / EARLY = candidates, CONFIRMED, terminal)
//   SH    /api/v1/sh/signals    SCALPING / HEDGING machines (WAIT / NO_TRADE / BUY / SELL with the reason)
// Dedup on stable ids: a scenario that already became a BOT signal (same setup_id) is shown once, as the BOT signal.
export type Lifecycle = "CANDIDATE" | "CONFIRMED" | "FILLED" | "CLOSED" | "EXPIRED" | "INVALIDATED" | "REJECTED" | "WAIT";
export type Cond = "MET" | "NOT_MET" | "PENDING" | "UNKNOWN" | "INVALIDATED";
export type Sig = {
  id: string; kind: "BOT" | "SETUP" | "SH"; strategyId: string; strategyName: string; family: string | null; symbol: string; tf: string | null;
  direction: "BUY" | "SELL" | "WAIT"; scenarioDir: string | null; lifecycle: Lifecycle; statusRaw: string; at: string | null; updated: string | null;
  entry: number | null; sl: number | null; targets: number[]; strength: number | null; setupId: string | null; source: string; reason: string | null;
  rr: number | null; outcomeR: number | null; live: boolean; raw: any;
};

const iso = (v: any): string | null => (v == null ? null : typeof v === "number" ? new Date(v * (v < 1e12 ? 1000 : 1)).toISOString() : String(v));
const dirOf = (v: any): "BUY" | "SELL" | null => { const u = String(v ?? "").toUpperCase(); return u === "BUY" || u === "LONG" ? "BUY" : u === "SELL" || u === "SHORT" ? "SELL" : null; };

function fromBot(x: any): Sig {
  const st = String(x.status || "");
  const lc: Lifecycle = st === "OPEN" ? "FILLED" : st === "PENDING_ENTRY" ? "CONFIRMED" : ["WIN", "LOSS", "BREAKEVEN"].includes(st) ? "CLOSED"
    : ["EXPIRED", "TIMEOUT"].includes(st) ? "EXPIRED" : st === "REJECTED" ? "REJECTED" : st === "NO_TRADE" ? "WAIT" : "CLOSED";
  const d = dirOf(x.action);
  return {
    id: x.signal_id, kind: "BOT", strategyId: x.strategy_id || x.trigger || "BOT", strategyName: x.strategy_name || x.strategy_id || "—", family: x.detail?.family ?? null,
    symbol: x.symbol, tf: x.timeframe ?? null, direction: d ?? "WAIT", scenarioDir: d, lifecycle: lc, statusRaw: st, at: x.created_at, updated: x.updated_at,
    entry: x.entry_price ?? null, sl: x.stop_loss ?? null, targets: x.take_profits || [], strength: x.setup_score ?? null, setupId: x.setup_id ?? null,
    source: x.trigger === "SCANNER" ? "skaner rynków" : x.trigger === "MAIN" ? "silnik główny" : String(x.trigger || "bot"),
    reason: (x.validation?.reasons || []).join(", ") || null, rr: x.rr1 ?? x.validation?.rr_weighted ?? null, outcomeR: x.outcome_r ?? null,
    live: lc === "FILLED" || lc === "CONFIRMED", raw: x,
  };
}

function fromSetup(x: any): Sig {
  const terminal = x.status !== "ACTIVE";
  const t = String(x.terminal_reason || x.status || "");
  const lc: Lifecycle = !terminal ? (x.stage === "CONFIRMED" ? "CONFIRMED" : "CANDIDATE") : t === "INVALIDATED" ? "INVALIDATED" : t === "EXPIRED" ? "EXPIRED"
    : t === "ENTERED" ? "FILLED" : "CLOSED";
  const d = dirOf(x.direction);
  return {
    id: x.setup_id, kind: "SETUP", strategyId: x.strategy_id, strategyName: x.strategy_name || x.strategy_id, family: null, symbol: x.symbol, tf: x.timeframe,
    direction: lc === "CONFIRMED" && d ? d : "WAIT", scenarioDir: d, lifecycle: lc, statusRaw: `${x.stage} · ${x.scenario_status ?? x.status}`, at: x.created_at,
    updated: x.updated_at, entry: null, sl: null, targets: [], strength: x.setup_score ?? null, setupId: x.setup_id, source: x.engine_selected ? "silnik – wybrany" : "silnik",
    reason: x.terminal_reason_pl ?? null, rr: null, outcomeR: null, live: !terminal, raw: x,
  };
}

function fromSh(x: any): Sig {
  const d = dirOf(x.side);
  const st = String(x.status || "");
  const lc: Lifecycle = st === "WAIT" || st === "NO_TRADE" || !d ? "WAIT" : st === "INVALIDATED" ? "INVALIDATED" : st === "EXPIRED" ? "EXPIRED" : "CONFIRMED";
  // 1.38: variant identity (PMW_SC01.. / PMW_HG01..; old rows LEGACY_SCALPING / LEGACY_HEDGING) and its own signal TF - never "M1" for all
  const sid = x.strategy_id || (x.strategy === "SCALPING" ? "LEGACY_SCALPING" : x.strategy === "HEDGING" ? "LEGACY_HEDGING" : x.strategy);
  return {
    id: x.signal_id, kind: "SH", strategyId: sid, strategyName: sid, family: x.strategy ?? "SCALPING/HEDGING", symbol: x.symbol, tf: x.signal_tf || (x.strategy_id ? null : "M1"),
    direction: lc === "CONFIRMED" && d ? d : "WAIT",
    scenarioDir: d, lifecycle: lc, statusRaw: st, at: iso(x.created_at), updated: iso(x.updated_at ?? x.created_at), entry: null, sl: null, targets: [],
    strength: null, setupId: null, source: "maszyna SH", reason: x.status_reason ?? null, rr: null, outcomeR: null, live: lc !== "EXPIRED" && lc !== "INVALIDATED", raw: x,
  };
}

export function mergeSignals(bot: any[], setups: any[], sh: any[]): Sig[] {
  const out: Sig[] = [];
  const seen = new Set<string>();
  const botSetups = new Set(bot.map((x) => x.setup_id).filter(Boolean));
  for (const x of bot) if (!seen.has(x.signal_id)) { seen.add(x.signal_id); out.push(fromBot(x)); }
  for (const x of setups) if (!botSetups.has(x.setup_id) && !seen.has(x.setup_id)) { seen.add(x.setup_id); out.push(fromSetup(x)); }
  const latestSh = new Map<string, any>();                   // SH: the current state per symbol / variant / TF (20 variants are never collapsed to 2 cards)
  const shKey = (x: any) => `${x.symbol}|${x.strategy_id || x.strategy}|${x.signal_tf || ""}`;
  for (const x of sh) { const k = shKey(x); const p = latestSh.get(k); if (!p || (x.created_at ?? 0) > (p.created_at ?? 0)) latestSh.set(k, x); }
  for (const x of latestSh.values()) if (!seen.has(x.signal_id)) { seen.add(x.signal_id); out.push(fromSh(x)); }
  return out.sort((a, b) => (Date.parse(b.updated || b.at || "") || 0) - (Date.parse(a.updated || a.at || "") || 0));
}

export type CondRow = { label: string; state: Cond; evidence: string | null; at: string | null };
const ST: Record<string, Cond> = { MET: "MET", MISSING: "NOT_MET", PENDING: "PENDING", NO_DATA: "UNKNOWN", NA: "UNKNOWN", PASS: "MET", OK: "MET", FAIL: "NOT_MET",
  WAIT: "PENDING", INFO: "UNKNOWN", BLOCK: "NOT_MET" };

/** ENTRY / TRIGGER / INVALIDATION from the real definition of the strategy (engine checklist groups), never from a fake boolean. */
export function conditions(sig: Sig | null, det: any, shDet: any): { entry: CondRow[]; trigger: CondRow[]; invalidation: CondRow[]; source: string } {
  const empty = { entry: [], trigger: [], invalidation: [], source: "brak danych warunków" };
  if (!sig) return empty;
  if (det?.checklist) {
    const at = det.times?.checked_at ?? det.summary?.checked_at ?? null;
    const rows: any[] = det.checklist;
    const m = (r: any): CondRow => ({ label: r.name, state: ST[r.state] ?? "UNKNOWN", evidence: [r.value, r.threshold && r.threshold !== "—" ? `próg: ${r.threshold}` : null, r.reason].filter((x) => x && x !== "—").join(" · ") || null, at: r.at ?? at });
    const inv = rows.filter((r) => r.group === 10).map(m);
    if (sig.lifecycle === "INVALIDATED") inv.forEach((r) => { r.state = "INVALIDATED"; });
    if (det.levels?.invalidation_rule && det.levels.invalidation_rule !== "—") inv.unshift({ label: det.levels.invalidation_rule, state: sig.lifecycle === "INVALIDATED" ? "INVALIDATED" : "PENDING", evidence: det.levels.expires_at ? `ważny do ${det.levels.expires_at}` : null, at });
    return {
      entry: rows.filter((r) => r.required && ![4, 9, 10].includes(r.group)).map(m),
      trigger: [...rows.filter((r) => r.group === 4).map(m), ...(det.levels?.trigger ? [{ label: `Trigger strategii: ${det.levels.trigger}`, state: (sig.lifecycle === "CONFIRMED" || sig.lifecycle === "FILLED" ? "MET" : "PENDING") as Cond,
        evidence: det.levels.trigger_level != null ? `poziom ${det.levels.trigger_level}` : null, at }] : [])],
      invalidation: inv, source: `checklista silnika (${det.schema ?? "setup details"})`,
    };
  }
  if (sig.kind === "SH" && (shDet?.payload?.checklist || []).length) {
    const rows: any[] = shDet.payload.checklist;
    const m = (r: any): CondRow => ({ label: r.label, state: ST[r.status] ?? "UNKNOWN", evidence: r.detail ?? null, at: sig.updated });
    const isTrig = (r: any) => /trigger|wyzwal|wejś|entry|potwierdz/i.test(`${r.id} ${r.label}`);
    const isInv = (r: any) => /invalid|unieważ|stop|sl\b/i.test(`${r.id} ${r.label}`);
    return { entry: rows.filter((r) => !isTrig(r) && !isInv(r)).map(m), trigger: rows.filter(isTrig).map(m), invalidation: rows.filter(isInv).map(m),
      source: `checklista maszyny ${sig.strategyId} (${shDet.payload.setup_version ?? "SH"})` };
  }
  if (sig.kind === "BOT") {
    const d = sig.raw.detail || {};
    const ep = d.entry_plan || {};
    const closedLoss = sig.lifecycle === "CLOSED" && (sig.outcomeR ?? 0) < 0;
    return {
      entry: [...(d.reason_codes || []).map((c: string) => ({ label: c.replace(/_/g, " "), state: "MET" as Cond, evidence: "kod powodu strategii przy potwierdzeniu", at: sig.at })),
        ...(d.missing_confirmations || []).map((c: any) => ({ label: String(c?.label ?? c).replace(/_/g, " "), state: "NOT_MET" as Cond, evidence: "brakujące potwierdzenie (sygnał potwierdzony bez niego)", at: sig.at })),
        ...(sig.raw.validation ? [{ label: "Walidacja planu (RR, geometria SL/TP)", state: (sig.raw.validation.ok ? "MET" : "NOT_MET") as Cond, evidence: (sig.raw.validation.reasons || []).join(", ") || `RR ważone ${sig.raw.validation.rr_weighted ?? "N/A"}`, at: sig.at }] : [])],
      trigger: ep.trigger ? [{ label: `${ep.trigger}${ep.kind ? ` (${ep.kind})` : ""}`, state: "MET", evidence: ep.trigger_level != null ? `poziom ${ep.trigger_level}; potwierdzony przy utworzeniu sygnału` : "potwierdzony przy utworzeniu sygnału", at: sig.at }] : [],
      invalidation: d.invalidation_level != null ? [{ label: `${d.invalidation_rule === "CLOSE_BEYOND" ? "Zamknięcie świecy za poziomem" : d.invalidation_rule ?? "Poziom"} ${d.invalidation_level}`,
        state: closedLoss ? "INVALIDATED" : sig.live ? "PENDING" : "UNKNOWN", evidence: closedLoss ? `zamknięty z wynikiem ${sig.outcomeR} R` : sig.live ? "monitorowane" : "sygnał zakończony", at: sig.updated }] : [],
      source: "zapis sygnału (plan strategii) – checklista silnika niedostępna dla tego setupu",
    };
  }
  return empty;
}

/** Plain narrative built ONLY from the facts above (no "thoughts" of a model). */
export function narrative(sig: Sig | null, c: ReturnType<typeof conditions>, det: any, models: { dir: string | null; agree: number; active: number }): string {
  if (!sig) return "Wybierz sygnał z listy.";
  const met = c.entry.filter((r) => r.state === "MET").length, miss = c.entry.filter((r) => r.state === "NOT_MET").length;
  const parts = [`${sig.strategyName} (${sig.strategyId}) na ${sig.symbol}${sig.tf ? ` ${sig.tf}` : ""}: ${sig.lifecycle === "WAIT" ? "brak kierunku (WAIT)" : `scenariusz ${sig.scenarioDir ?? "—"}`}, stan ${sig.lifecycle}.`];
  if (det?.context?.rationale) parts.push(det.context.rationale);
  else if (sig.reason) parts.push(`Powód: ${sig.reason}.`);
  if (c.entry.length) parts.push(`Warunki wejścia: ${met} spełnionych, ${miss} niespełnionych z ${c.entry.length}.`);
  const trg = c.trigger.find((r) => r.state !== "MET");
  parts.push(trg ? `Trigger oczekuje: ${trg.label}.` : c.trigger.length ? "Trigger potwierdzony." : "");
  if (c.invalidation[0]) parts.push(`Unieważnienie: ${c.invalidation[0].label}.`);
  parts.push(models.active ? `Modele AI (stan bieżący): ${models.agree}/${models.active} wskazuje ${models.dir}.` : "Brak aktywnych modeli z kierunkiem – konsensus N/A.");
  parts.push("Opis nie jest prognozą ani obietnicą wyniku.");
  return parts.filter(Boolean).join(" ");
}
