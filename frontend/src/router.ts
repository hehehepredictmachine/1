// Hash routing for the three pages (no routing library needed for three views; the backend serves only "/", so a refresh
// or a direct link never hits a 404). Back / Forward work through the browser history of hash changes.
//   #/ai                       Analiza AI
//   #/wykresy?tf=M5&view=focus  Wykresy bota (optional TF focus + highlighted price)
//   #/warunki/<setup_id>       Warunki setupu (the setup being VIEWED - presentation state, never the engine's choice)
import { useEffect, useState } from "react";

export type Page = "ai" | "wykresy" | "warunki";
export type Route = { page: Page; setupId: string | null; params: URLSearchParams };
export const PAGES: { id: Page; label: string; short: string }[] = [
  { id: "ai", label: "Analiza AI", short: "AI" },
  { id: "wykresy", label: "Wykresy bota", short: "Wykresy" },
  { id: "warunki", label: "Warunki setupu", short: "Warunki" },
];
const LAST = "mq.lastPage";

export function parse(hash: string): Route {
  const h = (hash || "").replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const page = (["ai", "wykresy", "warunki"].includes(parts[0]) ? parts[0] : "ai") as Page;
  const setupId = page === "warunki" && parts[1] ? decodeURIComponent(parts[1]) : null;
  return { page, setupId, params: new URLSearchParams(query || "") };
}

export function href(page: Page, opts: { setupId?: string | null; params?: Record<string, string | number | null | undefined> } = {}): string {
  const q = Object.entries(opts.params || {}).filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return `#/${page}${opts.setupId ? "/" + encodeURIComponent(opts.setupId) : ""}${q.length ? "?" + q.join("&") : ""}`;
}

export function navigate(page: Page, opts: { setupId?: string | null; params?: Record<string, string | number | null | undefined>; replace?: boolean } = {}) {
  const h = href(page, opts);
  if (opts.replace) history.replaceState(null, "", h);
  else location.hash = h;
  if (opts.replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function useRoute(): Route {
  const [r, setR] = useState<Route>(() => {
    if (!location.hash || location.hash === "#" || location.hash === "#/") {
      let last: string | null = null;
      try { last = localStorage.getItem(LAST); } catch { /* storage unavailable */ }
      const page = (["ai", "wykresy", "warunki"].includes(last || "") ? last : "ai") as Page;
      history.replaceState(null, "", href(page));
    }
    return parse(location.hash);
  });
  useEffect(() => {
    const h = () => setR(parse(location.hash));
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => {
    try { localStorage.setItem(LAST, r.page); } catch { /* storage unavailable */ }
  }, [r.page]);
  return r;
}

/** Small persisted UI preference (layout choices, collapsed sections). Corrupted storage -> default. */
export function usePersisted<T>(key: string, init: T, valid?: (v: any) => boolean): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem("mq." + key);
      if (!raw) return init;
      const j = JSON.parse(raw);
      return valid && !valid(j) ? init : (j as T);
    } catch {
      return init;
    }
  });
  const set = (x: T) => {
    setV(x);
    try { localStorage.setItem("mq." + key, JSON.stringify(x)); } catch { /* storage unavailable */ }
  };
  return [v, set];
}
