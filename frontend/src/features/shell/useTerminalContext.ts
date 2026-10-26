// Shared context of the new panels (Trading Intelligence, AI Neural Lab, System Control Center), derived ONLY from the existing
// store (one reducer, one WebSocket) - no second store and no UI defaults: what the backend does not confirm is UNKNOWN / DISCONNECTED.
import { useStore } from "../../store";

export type Env = "LIVE" | "DEMO" | "SYNTHETIC" | "HISTORY" | "UNKNOWN";
export type Freshness = "FRESH" | "DEGRADED" | "STALE" | "DISCONNECTED" | "UNKNOWN";
export type Mt5 = "CONNECTED" | "DISCONNECTED" | "UNKNOWN";

export interface TerminalContext {
  env: Env;
  envDetail: string;
  mt5: Mt5;
  mt5State: string | null;            // raw bridge state (CONNECTING, RECONNECTING, ...) shown next to the summary
  connection: any;
  freshness: Freshness;
  freshnessDetail: string;
  instrument: string | null;          // bot asset id (XAUUSD / BTC)
  brokerSymbol: string | null;
  mode: string | null;                // SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE
  modeLabel: string | null;
  executionLock: string | null;
  killSwitch: boolean;
  backend: string;                    // WebSocket status of the single live connection
  opsBlocked: boolean;                // new operations must stay blocked in the UI (the backend keeps its own gates)
  warnings: string[];
  alerts: any[];                      // WARNING / ERROR log entries (latest first)
}

/** D2: LIVE = account REAL, DEMO = DEMO / CONTEST, SYNTHETIC = terminal simulator, HISTORY = an "as of" view; otherwise UNKNOWN. */
export function envOf(s: any, asOf?: string | null): { env: Env; detail: string } {
  if (asOf) return { env: "HISTORY", detail: `widok historyczny na ${asOf}` };
  if (s.synthetic === true || s.connection?.synthetic === true)
    return { env: "SYNTHETIC", detail: "symulator terminala – dane syntetyczne, nie notowania MT5 ani wyniki rachunku" };
  const tm = s.account?.trade_mode;
  if (tm === "REAL") return { env: "LIVE", detail: "rachunek REAL (potwierdzony przez terminal)" };
  if (tm === "DEMO" || tm === "CONTEST") return { env: "DEMO", detail: `rachunek ${tm} (potwierdzony przez terminal)` };
  return { env: "UNKNOWN", detail: tm ? `nieznany typ rachunku: ${tm}` : "terminal nie potwierdził rachunku" };
}

/** Without the backend link the last MT5 state cannot be confirmed - it is shown only as "last known", never as current. */
export function mt5Of(s: any): Mt5 {
  const st = s.connection?.state;
  if (!st || s.ws !== "OPEN") return "UNKNOWN";
  return st === "CONNECTED" ? "CONNECTED" : "DISCONNECTED";
}

/** Freshness from the backend's own data-quality verdict (never a UI threshold); a broken link always wins. */
export function freshnessOf(s: any): { state: Freshness; detail: string } {
  if (s.ws !== "OPEN") return { state: "DISCONNECTED", detail: `brak połączenia z lokalnym backendem (${s.ws ?? "?"})` };
  if (mt5Of(s) !== "CONNECTED") return { state: "DISCONNECTED", detail: `MT5: ${s.connection?.state ?? "brak statusu"}` };
  const dq = s.decision?.data_quality;
  const age = s.quote?.age_seconds;
  const market = s.decision?.market_state;
  const tail = [age != null ? `tick ${Math.round(age)} s temu` : "brak ticka", market ? `rynek ${market}` : null].filter(Boolean).join(" · ");
  if (dq === "GOOD") return { state: "FRESH", detail: tail };
  if (dq === "DEGRADED") return { state: "DEGRADED", detail: `jakość danych DEGRADED · ${tail}` };
  if (dq === "STALE" || dq === "BAD" || dq === "NO_DATA") return { state: "STALE", detail: `jakość danych ${dq} · ${tail}` };
  return { state: "UNKNOWN", detail: "backend nie podał jakości danych" };
}

export function warningsOf(s: any): string[] {
  const w: string[] = [];
  if (s.ws !== "OPEN") w.push(`Brak połączenia z lokalnym backendem (${s.ws ?? "?"}) – dane mogą być nieaktualne; ponowne łączenie automatyczne.`);
  else if (s.connection?.state && s.connection.state !== "CONNECTED")
    w.push(`MT5: ${s.connection.state}${s.connection.reason ? ` – ${s.connection.reason}` : ""}. Dane z terminala nie są aktualne.`);
  if (s.engine?.last_error) w.push(`Błąd silnika: ${String(s.engine.last_error).slice(0, 140)}`);
  if (s.mode?.kill_switch) w.push("Nowe wejścia ZATRZYMANE (STOP).");
  if (s.mode?.primary_path === "UNSET" && s.mode?.mode !== "SIGNALS") w.push("Nie wybrano ścieżki głównej – nowe wejścia wstrzymane.");
  return w;
}

export function useTerminalContext(asOf?: string | null): TerminalContext {
  const { s } = useStore();
  const { env, detail } = envOf(s, asOf);
  const fr = freshnessOf(s);
  const mt5 = mt5Of(s);
  return {
    env, envDetail: detail, mt5, mt5State: s.connection?.state ?? null, connection: s.connection || null,
    freshness: fr.state, freshnessDetail: fr.detail,
    instrument: s.assets?.active ?? null, brokerSymbol: s.symbol?.symbol ?? null,
    mode: s.mode?.mode ?? null, modeLabel: s.mode?.mode_label ?? null,
    executionLock: s.execution_lock ?? null, killSwitch: !!s.mode?.kill_switch, backend: s.ws ?? "UNKNOWN",
    opsBlocked: s.ws !== "OPEN" || mt5 !== "CONNECTED" || fr.state !== "FRESH" || !!s.mode?.kill_switch,
    warnings: warningsOf(s),
    alerts: (s.logs || []).filter((l: any) => l.level === "WARNING" || l.level === "ERROR"),
  };
}
