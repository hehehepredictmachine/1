// Formatting and time helpers. Times from the backend are UTC ISO strings.
export type TimeZoneMode = "LOCAL" | "UTC" | "SERVER";

export function epochSec(iso: string): number {
  return Math.floor(Date.parse(iso) / 1000);
}

// lightweight-charts renders timestamps as UTC; shift to show local/server wall-clock time.
export function chartShift(mode: TimeZoneMode, serverOffsetSec: number | null): number {
  if (mode === "UTC") return 0;
  if (mode === "SERVER") return serverOffsetSec ?? 0;
  return -new Date().getTimezoneOffset() * 60;
}

export function fmtTime(iso?: string | null, withDate = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return withDate
    ? d.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "medium" })
    : d.toLocaleTimeString("pl-PL");
}

export function fmtNum(v: any, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMoney(v: any, cur?: string | null): string {
  if (v === null || v === undefined) return "—";
  return `${fmtNum(v, 2)} ${cur ?? ""}`.trim();
}

export function cls(...a: (string | false | null | undefined)[]): string {
  return a.filter(Boolean).join(" ");
}

export function tone(status?: string | null): "ok" | "warn" | "bad" | "muted" {
  if (!status) return "muted";
  const s = status.toUpperCase();
  if (["CONNECTED", "OK", "GOOD", "OPEN", "VERIFIED", "PASS", "ALLOWED", "IDLE", "HEALTHY", "RUNNING", "ON"].includes(s)) return "ok";
  if (s.includes("FAIL") || s.includes("ERROR") || s.includes("BAD") || s.includes("BLOCK") || s.includes("UNAVAILABLE") || s.includes("DISCONNECT") || s === "MODULE_MISSING" || s.includes("AUTH") || s.includes("INVALID")) return "bad";
  return "warn";
}

export const REASON_PL: Record<string, string> = {
  READ_ONLY_MODE: "Tryb READ_ONLY – zlecenia wyłączone",
  RISK_LIMITS_NOT_CONFIGURED: "Limity ryzyka nieustawione (Ustawienia → Ryzyko)",
  AI_UNAVAILABLE_NO_KEY: "Brak klucza Claude API",
  MODEL_NOT_CONFIGURED: "Nie wybrano modelu Claude",
  MACRO_CALENDAR_UNAVAILABLE: "Kalendarz makro niedostępny",
  MACRO_CALENDAR_NOT_LOADED: "Kalendarz makro jeszcze nie pobrany",
  MACRO_EVENT_WINDOW: "Okno wydarzenia makro wysokiego wpływu",
  STRUCTURAL_DIRECTION_UNRESOLVED: "Brak zgodności struktury H4/H1",
  SETUP: "Brak setupu MasterQUO",
  FROZEN_M07_SETUP: "Brak zamrożonego setupu M07",
  M10A_CONFIRMED: "Setup niepotwierdzony (M10A)",
  QUOTE_STALE: "Kwotowanie nieświeże",
  NEW_ENTRIES_STOPPED: "Nowe wejścia zatrzymane",
  COST_MODEL_UNKNOWN_COMMISSION: "Nieznana prowizja",
  SLIPPAGE_STRESS_NOT_CONFIGURED: "Nieustawiony stres poślizgu",
  SIZE_BELOW_BROKER_MIN_LOT: "Wielkość poniżej min. lota brokera (nie zaokrąglamy w górę)",
  MARKET_CLOSED_WEEKEND: "Rynek zamknięty (weekend)",
  MARKET_CLOSED_SESSION_BREAK: "Przerwa sesji",
  MARKET_NO_FRESH_TICKS: "Brak świeżych ticków",
  TIME_OFFSET_UNKNOWN: "Nieznany offset czasu serwera",
  TIME_OFFSET_MEASURING: "Pomiar offsetu czasu serwera",
  TIME_OFFSET_STORED_UNVERIFIED: "Offset czasu z poprzedniej sesji (niezweryfikowany)",
};

export function reasonPl(code: string): string {
  if (REASON_PL[code]) return REASON_PL[code];
  if (code.startsWith("RR_NET_BELOW")) return "RR netto poniżej progu blokady";
  if (code.startsWith("RR_NET_CONDITIONAL")) return "RR netto warunkowy – bez wykonania";
  if (code.endsWith("_INSUFFICIENT_HISTORY")) return `${code.split("_")[0]}: za mało historii (WARMING_UP)`;
  if (code.startsWith("SETUP_STATE_")) return "Etap setupu: " + code.slice(12);
  if (code.startsWith("AI_")) return "Agent: " + code.slice(3).replace(/_/g, " ").toLowerCase();
  return code;
}
