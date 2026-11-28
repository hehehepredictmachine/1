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

