// Shared states of the new panels. A missing value is shown as N/A / UNKNOWN - never as 0.
import type { ReactNode } from "react";
import { ApiError } from "../../api";
import { cls } from "../../util";

export type ViewState = "loading" | "empty" | "error" | "stale" | "disconnected" | "denied";

const TITLE: Record<ViewState, string> = {
  loading: "Ładowanie…",
  empty: "Brak danych",
  error: "Błąd danych",
  stale: "Dane nieaktualne",
  disconnected: "Brak połączenia",
  denied: "Brak uprawnień / sesja wygasła",
};

export function StateView({ state, detail, children }: { state: ViewState; detail?: string | null; children?: ReactNode }) {
  return (
    <div className={cls("t-state", `t-state-${state}`)} role={state === "error" || state === "denied" ? "alert" : "status"} data-state={state}>
      <b>{TITLE[state]}</b>
      {detail && <span>{detail}</span>}
      {children}
    </div>);
}

/** HTTP error -> view state: 401/403 = session / permission, anything else = error. */
export function stateOfError(e: unknown): ViewState {
  return e instanceof ApiError && (e.status === 401 || e.status === 403) ? "denied" : "error";
}

/** null / undefined / NaN / Infinity -> "N/A"; everything else through the optional formatter. */
export function fmtUnknown(v: unknown, fmt?: (x: any) => string, unknown = "N/A"): string {
  if (v === null || v === undefined || v === "") return unknown;
  if (typeof v === "number" && !Number.isFinite(v)) return unknown;
  return fmt ? fmt(v) : String(v);
}

/** A section that is not integrated yet: says so and lists the real sources it will use (no placeholder numbers). */
export function NotIntegrated({ title, stage, sources, testId, children }: {
  title: string; stage: number; sources: string[]; testId?: string; children?: ReactNode;
}) {
  return (
    <section className="t-card t-pending" aria-label={title} data-testid={testId} data-integration="NOT_INTEGRATED">
      <header className="t-card-head"><h2>{title}</h2><span className="t-badge t-badge-muted">etap {stage} – nie zintegrowane</span></header>
      <StateView state="empty" detail="Ten widok nie pokazuje jeszcze danych – zostanie podłączony do istniejących źródeł bota w swoim etapie." />
      {sources.length > 0 && <ul className="t-sources" aria-label="Planowane źródła danych">{sources.map((x) => <li key={x}><code>{x}</code></li>)}</ul>}
      {children}
    </section>);
}
