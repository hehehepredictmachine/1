// Telemetry tap of the single live WebSocket (store.tsx): every event the backend publishes is announced here - type, local
// receive time, sequence - for the main menu's model-flow maps. No second connection and no React re-render per event; the maps
// subscribe directly. Only real events pass through here: nothing is generated to make the maps look busy.
export type TelemetryEvent = { type: string; at: number; seq: number | null; data: any };
type Fn = (e: TelemetryEvent) => void;

const subs = new Set<Fn>();
const lastSeen: Record<string, { at: number; count: number }> = {};
let link = "INIT";
const linkSubs = new Set<(s: string) => void>();

export const telemetry = {
  emit(m: any) {
    if (!m || typeof m.type !== "string") return;
    const e: TelemetryEvent = { type: m.type, at: Date.now(), seq: typeof m.seq === "number" ? m.seq : null, data: m.data };
    const l = lastSeen[m.type] || { at: 0, count: 0 };
    lastSeen[m.type] = { at: e.at, count: l.count + 1 };
    subs.forEach((f) => { try { f(e); } catch { /* a broken observer never affects the store */ } });
  },
  status(s: string) {
    link = s;
    linkSubs.forEach((f) => { try { f(s); } catch { /* ignore */ } });
  },
  subscribe(fn: Fn): () => void {
    subs.add(fn);
    return () => { subs.delete(fn); };
  },
  onLink(fn: (s: string) => void): () => void {
    linkSubs.add(fn);
    fn(link);
    return () => { linkSubs.delete(fn); };
  },
  link: () => link,
  lastSeen: (type: string) => lastSeen[type] ?? null,
  subscribers: () => subs.size,
};
(window as any).__mqTelemetry = telemetry;            // used by UI tests (subscriber count after view changes)
