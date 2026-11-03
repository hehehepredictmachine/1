// Shared state of the market zones (/api/v1/market-zones) for the charts outside the "Strefy rynkowe" page: one request stream per
// instrument however many charts show it. Responses for another instrument than the one asked for are dropped (no mixing), a
// running job or LIVE mode is polled, and the WebSocket "market_zones" message triggers an immediate refresh. Analytical only:
// the calls go to /market-zones/* and nothing else (no orders, no change of trading settings).
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { telemetry } from "../../telemetry";

export const MZ_TFS = ["M1", "M5", "M15", "M30"];
export type MzState = { view: any | null; err: string | null; busy: string | null; at: number };

type Entry = { st: MzState; subs: Set<(s: MzState) => void>; seq: number; timer: ReturnType<typeof setTimeout> | null; unsub: (() => void) | null };
const STORE = new Map<string, Entry>();

function entry(inst: string): Entry {
  let e = STORE.get(inst);
  if (!e) {
    e = { st: { view: null, err: null, busy: null, at: 0 }, subs: new Set(), seq: 0, timer: null, unsub: null };
    STORE.set(inst, e);
  }
  return e;
}

function emit(inst: string, patch: Partial<MzState>) {
  const e = entry(inst);
  e.st = { ...e.st, ...patch };
  e.subs.forEach((f) => f(e.st));
}

function schedule(inst: string) {
  const e = entry(inst);
  if (e.timer) clearTimeout(e.timer);
  e.timer = null;
  if (!e.subs.size) return;
  const v = e.st.view;
  const running = v?.job && ["QUEUED", "RUNNING"].includes(v.job.status);
  if (!running && !v?.live?.enabled) return;
  e.timer = setTimeout(() => void refreshZones(inst), running ? 700 : 5000);
}

export async function refreshZones(inst: string): Promise<void> {
  const e = entry(inst);
  const my = ++e.seq;
  try {
    const v = await apiGet(`/api/v1/market-zones?instrument=${encodeURIComponent(inst)}`);
    if (my !== e.seq || v?.instrument !== inst) return;          // older response or another instrument: ignored
    emit(inst, { view: v, err: null, at: Date.now() });
  } catch (x: any) {
    if (my === e.seq) emit(inst, { err: String(x?.message || x) });
  }
  schedule(inst);
}

async function post(inst: string, what: string, path: string, body: any) {
  emit(inst, { busy: what, err: null });
  try {
    const r = await apiSend("POST", path, body);
    if (what === "compute") {
      const v = entry(inst).st.view;
      if (v && v.instrument === inst) emit(inst, { view: { ...v, job: r } });
    }
    await refreshZones(inst);
  } catch (x: any) {
    emit(inst, { err: String(x?.message || x) });
  } finally {
    emit(inst, { busy: null });
  }
}

export const computeZones = (inst: string, tfs: string[]) => post(inst, "compute", "/api/v1/market-zones/compute", { instrument: inst, timeframes: tfs });
export const setZonesLive = (inst: string, enabled: boolean, tfs: string[]) =>
  post(inst, "live", "/api/v1/market-zones/live", { instrument: inst, enabled, timeframes: tfs });
export const stopZones = (inst: string) => post(inst, "stop", "/api/v1/market-zones/stop", { instrument: inst });

/** Subscribe to the zones of one instrument (null = none). */
export function useMarketZones(inst: string | null): MzState {
  const [st, setSt] = useState<MzState>(() => (inst ? entry(inst).st : { view: null, err: null, busy: null, at: 0 }));
  useEffect(() => {
    if (!inst) { setSt({ view: null, err: null, busy: null, at: 0 }); return; }
    const e = entry(inst);
    e.subs.add(setSt);
    setSt(e.st);
    if (!e.unsub) e.unsub = telemetry.subscribe((m: any) => { if (m?.type === "market_zones" && m.data?.instrument === inst) void refreshZones(inst); });
    if (!e.st.view || Date.now() - e.st.at > 3000) void refreshZones(inst);
    else schedule(inst);
    return () => {
      e.subs.delete(setSt);
      if (!e.subs.size) {
        if (e.timer) clearTimeout(e.timer);
        e.timer = null;
        e.unsub?.();
        e.unsub = null;
      }
    };
  }, [inst]);
  return st;
}
