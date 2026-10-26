// Shell of the new panels (Trading Intelligence, AI Neural Lab, System Control Center). It wraps ONLY the new routes; every existing
// page keeps its own shell. Uses the existing store and its single WebSocket - nothing here opens a connection or changes bot state.
import { useRef, type ReactNode } from "react";
import { type Page } from "../../router";
import { useStore } from "../../store";
import TerminalHeader from "./TerminalHeader";
import TerminalSidebar from "./TerminalSidebar";
import { useTerminalContext } from "./useTerminalContext";
import "./terminal.css";

export default function TerminalShell({ page, asOf, children }: { page: Page; asOf?: string | null; children: ReactNode }) {
  const { s } = useStore();
  const ctx = useTerminalContext(asOf);
  const main = useRef<HTMLElement>(null);
  return (
    <div className="pmw-terminal" data-testid="terminal-shell" data-env={ctx.env}>
      <button className="t-skip" onClick={() => main.current?.focus()} data-testid="t-skip">Przejdź do treści</button>
      <TerminalHeader ctx={ctx} quoteAge={s.quote?.age_seconds ?? null} />
      {ctx.env === "SYNTHETIC" && (
        <div className="t-strip t-strip-warn" role="note" data-testid="t-synthetic">
          DANE SYNTETYCZNE – symulator terminala, oddzielna baza. To nie są notowania MT5 ani wyniki rachunku.</div>)}
      {ctx.warnings.length > 0 && (
        <div className="t-strip t-strip-bad" role="status" data-testid="t-warnings">
          {ctx.warnings.map((w) => <span key={w}>⚠ {w}</span>)}</div>)}
      <div className="t-body">
        <TerminalSidebar page={page} />
        <main className="t-main" id="terminal-main" ref={main} tabIndex={-1} data-page={page} data-stale={ctx.freshness === "FRESH" ? "0" : "1"}>
          {children}
          <footer className="t-footer">
            Pepe Market Wizard {s.app_version} · kontrakt API {s.contract} · wykresy: TradingView Lightweight Charts™ (Apache-2.0) – źródło notowań:
            wyłącznie Twój terminal MT5 · Narzędzie analityczne – nie gwarantuje zysków.
          </footer>
        </main>
      </div>
    </div>);
}
