// Backend contract /api/v1 (same origin). State-changing calls carry the CSRF token.
let csrf: string | null = null;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function initSession(): Promise<void> {
  const r = await fetch("/api/v1/session", { credentials: "same-origin" });
  if (!r.ok) throw new ApiError(r.status, "SESSION_FAILED");
  const j = await r.json();
  csrf = j.csrf;
}

// 1.46: getCsrf() removed - no caller since 1.42 (only the archived 1.41 UI, which is not built); the token stays private to this module.

// 1.44.0: 402 = brak ważnej licencji (wersja klienta) – LicenseGate wraca do ekranu aktywacji
const licenseLost = (status: number) => { if (status === 402) window.dispatchEvent(new CustomEvent("pmw-license-required")); };

export async function apiGet<T = any>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  licenseLost(r.status);
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return r.json();
}

export async function apiSend<T = any>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-MQ-CSRF": csrf ?? "" },
    body: JSON.stringify(body ?? {}),
  });
  licenseLost(r.status);
  const text = await r.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!r.ok) throw new ApiError(r.status, (data && (data.detail || data.error)) || text || `HTTP ${r.status}`);
  return data as T;
}

export type WsHandler = (msg: any) => void;

// WebSocket with sequence tracking: on reconnect asks for events since the last seq;
// the server answers with the missing events or a full "resync" snapshot.
export class LiveSocket {
  private ws: WebSocket | null = null;
  private lastSeq: number | null = null;
  private bootId: string | null = null;
  private closed = false;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  constructor(private onMessage: WsHandler, private onStatus: (s: string) => void) {}

  start() {
    this.closed = false;
    this.connect();
  }

  // 1.46: stop() also cancels a scheduled reconnect - before, a store unmounted during the back-off (licence screen after 402) got an
  // orphan WebSocket from the pending timer, and the next StoreProvider a second one (every telemetry event emitted twice).
  stop() {
    this.closed = true;
    if (this.timer !== null) { clearTimeout(this.timer); this.timer = null; }
    this.ws?.close();
  }

  private connect() {
    this.timer = null;
    if (this.closed) return;                        // 1.46: a timer that fired after stop() opens nothing
    const url = `ws://${location.host}/api/v1/ws`;
    const ws = new WebSocket(url);
    this.ws = ws;
    this.onStatus("CONNECTING");
    ws.onopen = () => {
      this.retry = 0;
      ws.send(JSON.stringify({ csrf, last_seq: this.lastSeq, boot_id: this.bootId }));
      this.onStatus("OPEN");
    };
    ws.onmessage = (e) => {
      let m: any;
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      if (m.type === "resync") {
        this.lastSeq = m.seq;
        this.bootId = m.boot_id;
      } else if (typeof m.seq === "number") {
        if (this.lastSeq !== null && m.boot_id === this.bootId && m.seq <= this.lastSeq) return; // already in snapshot
        if (this.lastSeq !== null && m.seq !== this.lastSeq + 1 && m.boot_id === this.bootId) {
          // gap -> reconnect to receive the missing events or a resync
          ws.close();
          return;
        }
        this.lastSeq = m.seq;
        this.bootId = m.boot_id;
      }
      this.onMessage(m);
    };
    ws.onclose = (ev) => {
      this.onStatus("CLOSED");
      if (this.closed) return;
      if (ev.code === 4403) {
        // server restarted -> session unknown; reload the page to obtain a new session
        this.timer = setTimeout(() => location.reload(), 1500);
        return;
      }
      this.retry = Math.min(this.retry + 1, 6);
      this.timer = setTimeout(() => this.connect(), 500 * 2 ** this.retry);
    };
  }
}

export async function apiUpload<T = any>(path: string, file: Blob): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": file.type || "application/octet-stream", "X-MQ-CSRF": csrf ?? "" },
    body: file,
  });
  const text = await r.text();
  if (!r.ok) throw new ApiError(r.status, text);
  return JSON.parse(text);
}
