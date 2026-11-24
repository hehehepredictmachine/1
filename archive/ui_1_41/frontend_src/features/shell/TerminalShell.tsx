// Shell of the new panels (Trading Intelligence, AI Neural Lab, Centrum sterowania) in the look of the approved mockups. It wraps ONLY
// the new routes; every existing page keeps its own shell. Uses the existing store and its single WebSocket.
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { usePersisted, type Page } from "../../router";
import { useStore } from "../../store";
import { DEFAULT_LOOK, LookCtx, lookStyle, validLook, type Look } from "./look";
import LookDialog from "./LookDialog";
import TerminalHeader from "./TerminalHeader";
import TerminalSidebar from "./TerminalSidebar";
import { useTerminalContext } from "./useTerminalContext";
import "./terminal.css";

export default function TerminalShell({ page, asOf, children }: { page: Page; asOf?: string | null; children: ReactNode }) {
  const { s } = useStore();
  const ctx = useTerminalContext(asOf);
  const main = useRef<HTMLElement>(null);
  const [look, setLook] = usePersisted<Look>("terminal.look", DEFAULT_LOOK, validLook);
  const [lookOpen, setLookOpen] = useState(false);
  const openLook = useCallback(() => setLookOpen(true), []);
  const lc = useMemo(() => ({ look, setLook, openLook }), [look, setLook, openLook]);
  return (
    <LookCtx.Provider value={lc}>
      <div className="pmw-terminal" data-testid="terminal-shell" data-env={ctx.env} data-motion={look.motion} style={lookStyle(look)}>
        <button className="t-skip" onClick={() => main.current?.focus()} data-testid="t-skip">Przejdź do treści</button>
        <div className="t-body">
          <TerminalSidebar page={page} />
          <div className="t-col">
            <TerminalHeader ctx={ctx} page={page} quoteAge={s.quote?.age_seconds ?? null} />
            {ctx.env === "SYNTHETIC" && (
              <div className="t-strip t-strip-warn" role="note" data-testid="t-synthetic">
                DANE SYNTETYCZNE – symulator terminala, oddzielna baza. To nie są notowania MT5 ani wyniki rachunku.</div>)}
            {ctx.warnings.length > 0 && (
              <div className="t-strip t-strip-bad" role="status" data-testid="t-warnings">
                {ctx.warnings.map((w) => <span key={w}>⚠ {w}</span>)}</div>)}
            <main className="t-main" id="terminal-main" ref={main} tabIndex={-1} data-page={page} data-stale={ctx.freshness === "FRESH" ? "0" : "1"}>
              {children}
              <footer className="t-footer">
                Pepe Market Wizard {s.app_version} · kontrakt API {s.contract} · wykresy: TradingView Lightweight Charts™ (Apache-2.0) – źródło notowań:
                wyłącznie Twój terminal MT5 · Narzędzie analityczne – nie gwarantuje zysków.
              </footer>
            </main>
          </div>
        </div>
        {lookOpen && <LookDialog look={look} onChange={setLook} onClose={() => setLookOpen(false)} />}
      </div>
    </LookCtx.Provider>);
}
