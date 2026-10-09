// Same-origin API client. Session = HttpOnly cookie (never readable here); CSRF token kept only in memory.
let csrf: string | null = null;

export class ApiError extends Error {
  status: number;
  code: string;
  detail: any;
  constructor(status: number, code: string, detail: any) {
    super(code);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function setCsrf(t: string | null) {
  csrf = t;
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-CSRF"] = csrf;
  const r = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, j.error || j.detail?.[0]?.msg || `HTTP_${r.status}`, j.detail);
  return j as T;
}

export const ERR_PL: Record<string, string> = {
  INVALID_CREDENTIALS: "Nieprawidłowy e-mail lub hasło.",
  ACCOUNT_BLOCKED: "Konto jest zablokowane.",
  EMAIL_NOT_VERIFIED: "Adres e-mail nie został potwierdzony.",
  MFA_INVALID: "Nieprawidłowy kod MFA.",
  MFA_REQUIRED: "Wymagany kod MFA.",
  ADMIN_ONLY: "Brak uprawnień administratora.",
  ADMIN_MFA_NOT_CONFIGURED: "Administrator nie ma skonfigurowanego MFA (bootstrap-admin).",
  RATE_LIMITED: "Za dużo prób – odczekaj chwilę.",
  CSRF_INVALID: "Sesja wygasła – odśwież stronę.",
  NOT_AUTHENTICATED: "Zaloguj się ponownie.",
  TOKEN_INVALID_OR_EXPIRED: "Link jest nieważny, wygasł lub został już użyty.",
  PASSWORD_WEAK: "Hasło jest za słabe.",
  SERVER_CLOCK_ANOMALY: "Wykryto anomalię zegara serwera – nowe uprawnienia są wstrzymane.",
  EMAIL_EXISTS: "Konto z tym adresem już istnieje.",
  NO_SUCH_USER: "Nie ma takiego użytkownika.",
};

export const errText = (e: any) => (e instanceof ApiError ? `${ERR_PL[e.code] ?? e.code}${e.detail?.problems ? " " + e.detail.problems.join("; ") : ""}` : String(e?.message || e));

export const fmtTime = (s?: number | null) => (s ? new Date(s * 1000).toLocaleString("pl-PL") : "—");
export const fmtMs = (ms?: number | null) => (ms ? new Date(ms).toLocaleString("pl-PL") : "—");
export const fmtMoney = (v?: number | null, cur?: string | null) =>
  v === null || v === undefined ? "brak danych" : `${v.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur ?? ""}`;
export function fmtLeft(s?: number | null) {
  if (s === null || s === undefined) return "—";
  if (s <= 0) return "0";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return `${h} h ${m} min`;
}
export function fmtAge(s?: number | null) {
  if (s === null || s === undefined) return "brak danych";
  if (s < 90) return `${s} s temu`;
  if (s < 5400) return `${Math.round(s / 60)} min temu`;
  if (s < 172800) return `${Math.round(s / 3600)} h temu`;
  return `${Math.round(s / 86400)} dni temu`;
}
