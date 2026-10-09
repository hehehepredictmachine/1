import React, { createContext, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { apiGet, initSession, LiveSocket } from "./api";

export type AppState = Record<string, any> & { loaded: boolean; ws: string; barTick: Record<string, any>; analysisSeq: number };

type Action = { type: "full"; state: any } | { type: "ev"; ev: any } | { type: "ws"; status: string };

const initial: AppState = { loaded: false, ws: "INIT", barTick: {}, analysisSeq: 0, logs: [] };

function reducer(s: AppState, a: Action): AppState {
  if (a.type === "full") return { ...s, ...a.state, loaded: true, analysisSeq: s.analysisSeq + 1 };
  if (a.type === "ws") return { ...s, ws: a.status };
  const ev = a.ev;
  const d = ev.data;
  switch (ev.type) {
    case "resync":
      return { ...s, ...ev.state, loaded: true, analysisSeq: s.analysisSeq + 1 };
    case "quote":
      return { ...s, quote: d };
    case "connection":
      return { ...s, connection: d };
    case "account":
      return { ...s, account: d };
    case "positions":
      return { ...s, positions: d };
    case "symbol":
      return { ...s, symbol: d };
    case "decision":
      return { ...s, decision: d };
    case "dq":
      return s.decision ? { ...s, decision: { ...s.decision, data_quality: d.data_quality, market_state: d.market_state } } : s;
    case "analysis":
      return { ...s, analysis: d, analysisSeq: s.analysisSeq + 1 };
    case "agent":
      return { ...s, agent: d };
    case "agent_result":
      return { ...s, agent_last: d.status === "OK" ? d : s.agent_last, agent_last_any: d };
    case "mode":
      return { ...s, mode: d };
    case "news":
      return { ...s, news: d };
    case "orders":
      return { ...s, attempts: d };
    case "clock":
      return s.connection ? { ...s, connection: { ...s.connection, clock: d } } : s;
    case "log":
      return { ...s, logs: [d, ...(s.logs || [])].slice(0, 120) };
    case "bar":
    case "bar_closed":
      return { ...s, barTick: { ...s.barTick, [d.tf]: { bar: d.bar, closed: ev.type === "bar_closed", seq: ev.seq } } };
    case "bars_reloaded":
      return { ...s, analysisSeq: s.analysisSeq + 1 };
    case "auto":
      return { ...s, auto: d };
    case "engine_error":
      return { ...s, engine: { ...(s.engine || {}), last_error: d.error } };
    default:
      return s;
  }
}

const Ctx = createContext<{ s: AppState; refresh: () => Promise<void> } | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [s, dispatch] = useReducer(reducer, initial);
  const [error, setError] = useState<string | null>(null);
  const sock = useRef<LiveSocket | null>(null);
  const refresh = async () => {
    const st = await apiGet("/api/v1/state");
    dispatch({ type: "full", state: st });
  };
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await initSession();
        await refresh();
        if (!alive) return;
        sock.current = new LiveSocket((m) => dispatch({ type: "ev", ev: m }), (st) => dispatch({ type: "ws", status: st }));
        sock.current.start();
      } catch (e: any) {
        setError(String(e?.message || e));
      }
    })();
    const t = setInterval(() => {
      refresh().catch(() => undefined);
    }, 30000);
    // after the tab becomes visible again: full resync (the backend kept working meanwhile)
    const onVis = () => {
      if (document.visibilityState === "visible") refresh().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      alive = false;
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVis);
      sock.current?.stop();
    };
  }, []);
  const value = useMemo(() => ({ s, refresh }), [s]);
  if (error)
    return (
      <div className="fatal">
        <h1>MasterQUO AI</h1>
        <p>Nie można połączyć się z lokalnym backendem: {error}</p>
        <p>Uruchom 03_START_MASTERQUO.bat i odśwież stronę.</p>
      </div>
    );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const c = useContext(Ctx);
  if (!c) throw new Error("no store");
  return c;
}
