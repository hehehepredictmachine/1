// Routing 1.42 (S2): trzy trasy – #/menu (film intro + menu 3 planet), #/forex (kula FOREX; ekran planety w ?s=charts|signals|models|roi),
// #/system?p=settings|mode|diagnostics (panele systemowe). Każdy adres starego interfejsu 1.41 przekierowuje (replace) na najbliższe
// nowe miejsce według LEGACY_REDIRECTS; nieznany adres -> #/menu.
import { useEffect, useState } from "react";

export type Page = "menu" | "forex" | "system" | "trader-life-game";       // 1.45: TraderLifeGame = cel nawigacji (nie profil rynku)
export type Route = { page: Page; setupId: string | null; params: URLSearchParams };
export const PAGES: { id: Page; label: string }[] = [
  { id: "menu", label: "Menu główne" }, { id: "forex", label: "FOREX" }, { id: "system", label: "Panele systemowe" },
  { id: "trader-life-game", label: "TraderLifeGame" },
];
export const PAGE_IDS = PAGES.map((p) => p.id) as string[];
export const FOREX_SCREENS = ["charts", "signals", "models", "roi"] as const;
export type ForexScreen = (typeof FOREX_SCREENS)[number];
export const SYSTEM_PANELS = ["settings", "mode", "stop", "diagnostics", "training", "license"] as const;

const R = (page: Page, params?: Record<string, string>) => ({ page, params: params || {} });
/** S2 §3 – stare hashe 1.41 -> nowe miejsce (stare zakładki i linki nie prowadzą w próżnię). */
export const LEGACY_REDIRECTS: Record<string, { page: Page; params: Record<string, string> }> = {
  ...Object.fromEntries(["galaxy", "neural-city", "lightning", "wind", "control", "strategy-lab", "nc"].map((k) => [k, R("menu")])),
  ...Object.fromEntries(["pepe-wtc", "wtc", "wykresy", "precision", "strefy", "scalp-mtf", "indykatory", "dxy", "svp", "kontekst", "market-news", "trading-intelligence"]
    .map((k) => [k, R("forex", { s: "charts" })])),
  ...Object.fromEntries(["pepe-signal", "signal", "brain-signal", "sygnal", "setupy", "warunki", "strategie", "ai", "formacje", "dyscypline", "decyzje"]
    .map((k) => [k, R("forex", { s: "signals" })])),
  ...Object.fromEntries(["modele", "trening", "training-lab", "neural", "struktura", "testy", "badania", "ai-neural-lab"].map((k) => [k, R("forex", { s: "models" })])),
  ...Object.fromEntries(["profits", "pepe-roi", "leaderboard", "pozycje", "dziennik", "pulpit", "pepe-bank"].map((k) => [k, R("forex", { s: "roi" })])),
  ...Object.fromEntries(["ustawienia", "settings", "licencje", "dane"].map((k) => [k, R("system", { p: "settings" })])),
  "system-control": R("system", { p: "mode" }),
  diagnostyka: R("system", { p: "diagnostics" }),
  // 1.45 (TASK 020): OTC wycofane – stare linki do OTC wracają do menu (bez aktywnego selektora OTC)
  otc: R("menu", { retired: "otc" }), "otc-gold": R("menu", { retired: "otc" }),
};
const LAST = "mq.lastHash";

export function parse(hash: string): Route & { redirect?: string } {
  const h = (hash || "").replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const first = path.split("/").filter(Boolean)[0] || "";
  if (PAGE_IDS.includes(first)) return { page: first as Page, setupId: null, params: new URLSearchParams(query || "") };
  const r = LEGACY_REDIRECTS[first] || R("menu");
  return { page: r.page, setupId: null, params: new URLSearchParams(r.params), redirect: href(r.page, { params: r.params }) };
}

export function href(page: Page, opts: { params?: Record<string, string | number | null | undefined> } = {}): string {
  const q = Object.entries(opts.params || {}).filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return `#/${page}${q.length ? "?" + q.join("&") : ""}`;
}

export function navigate(page: Page, opts: { params?: Record<string, string | number | null | undefined>; replace?: boolean } = {}) {
  const h = href(page, opts);
  if (opts.replace) { history.replaceState(null, "", h); window.dispatchEvent(new HashChangeEvent("hashchange")); }
  else location.hash = h;
}

function current(): Route {
  if (!location.hash || location.hash === "#" || location.hash === "#/") history.replaceState(null, "", "#/menu");
  const r = parse(location.hash);
  if (r.redirect) history.replaceState(null, "", r.redirect);
  return r;
}

export function useRoute(): Route {
  const [r, setR] = useState<Route>(current);
  useEffect(() => {
    const h = () => setR(current());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => {
    try { if (r.page !== "system") localStorage.setItem(LAST, location.hash); } catch { /* brak pamięci */ }
  }, [r]);
  return r;
}

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
