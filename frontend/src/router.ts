// Hash routing (1.13: grouped menu Rynek / Analiza / Praca bota; earlier links #/ai, #/wykresy, #/warunki keep working) (no routing library needed for three views; the backend serves only "/", so a refresh
// or a direct link never hits a 404). Back / Forward work through the browser history of hash changes.
//   #/ai                       Analiza AI
//   #/wykresy?tf=M5&view=focus  Wykresy bota (optional TF focus + highlighted price)
//   #/warunki/<setup_id>       Warunki setupu (the setup being VIEWED - presentation state, never the engine's choice)
import { useEffect, useState } from "react";

export type Page = "pulpit" | "wykresy" | "scalp-mtf" | "kontekst" | "warunki" | "ai" | "indykatory" | "sygnal" | "formacje" | "pozycje" | "dziennik" | "testy"
  | "diagnostyka" | "setupy" | "modele" | "neural" | "struktura" | "badania" | "dane" | "ustawienia" | "strategie" | "nc"
  | "trading-intelligence" | "ai-neural-lab" | "system-control" | "menu" | "precision" | "dyscypline" | "profits" | "strefy" | "trening"
  | "lightning" | "wind" | "control" | "strategy-lab";
export type Route = { page: Page; setupId: string | null; params: URLSearchParams };
// 1.29 one interface in the style of the towers: the side menu is grouped by AREAS of the main menu - Precision (charts and
// market), Dyscypline (setups and signals), Profits (results and account), Modele i trening, Ustawienia i diagnostyka.
// 1.30: the license system was removed at the user's request - #/licencje (1.27-1.29) opens Ustawienia. Every earlier page keeps its id and its hash link (#/wykresy, #/ai, #/warunki/<id>, ...); SCREEN_MAP says where it lives now.
export type Area = { id: string; label: string; icon: string; pages: Page[]; accent: string; tower?: "precision" | "dyscypline" | "profits" };
export const GROUPS: Area[] = [
  { id: "precision", label: "Precision – wykresy i rynek", icon: "◎", accent: "#3fe6ff", tower: "precision",
    pages: ["pulpit", "wykresy", "strefy", "scalp-mtf", "kontekst", "indykatory", "sygnal", "nc", "precision"] },
  { id: "dyscypline", label: "Dyscypline – setupy i sygnały", icon: "⟐", accent: "#b46bff", tower: "dyscypline",
    pages: ["setupy", "warunki", "strategie", "ai", "formacje", "dyscypline", "lightning", "strategy-lab"] },
  { id: "profits", label: "Profits – wyniki i rachunek", icon: "◆", accent: "#ffcf5c", tower: "profits", pages: ["pozycje", "dziennik", "profits"] },
  { id: "modele", label: "Modele i trening", icon: "✦", accent: "#2fe6a0", pages: ["modele", "trening", "neural", "struktura", "testy", "badania", "wind"] },
  { id: "ustawienia", label: "Ustawienia i diagnostyka", icon: "⚙", accent: "#a5abd0", pages: ["ustawienia", "dane", "diagnostyka", "control"] },
];
/** Old screen -> where it is now (shown in Ustawienia → "Mapa ekranów" and in the documentation). The hash links did not change. */
export const SCREEN_MAP: { old: string; hash: string; now: string }[] = [
  { old: "Pulpit (sekcja „Pulpit”)", hash: "#/pulpit", now: "Precision → Pulpit" },
  { old: "Neural Cyberpunk (sekcja „Pulpit”)", hash: "#/nc", now: "Precision → Neural Cyberpunk" },
  { old: "Wykresy MTF (sekcja „Wykresy”)", hash: "#/wykresy", now: "Precision → Wykresy MTF (z przyciskiem „Wyznacz strefy”)" },
  { old: "Strefy rynkowe (sekcja „Wykresy”)", hash: "#/strefy", now: "Precision → Strefy rynkowe" },
  { old: "Scalping MTF / Kontekst / Indykatory / Analiza sygnału", hash: "#/scalp-mtf · #/kontekst · #/indykatory · #/sygnal", now: "Precision → te same zakładki" },
  { old: "Setupy, Setup silnika, SCALPING/HEDGING, Analiza AI (sekcja „Setupy”)", hash: "#/setupy · #/warunki · #/strategie · #/ai", now: "Dyscypline → te same zakładki" },
  { old: "Formacje (sekcja „Badania”)", hash: "#/formacje", now: "Dyscypline → Formacje i biblioteka" },
  { old: "Pozycje i ryzyko, Dziennik (sekcja „Setupy”)", hash: "#/pozycje · #/dziennik", now: "Profits → te same zakładki" },
  { old: "Modele, Centrum treningu, Neural, Structure, Testy (sekcja „Modele”)", hash: "#/modele · #/trening · #/neural · #/struktura · #/testy", now: "Modele i trening → te same zakładki" },
  { old: "Badania i walidacja (osobna sekcja)", hash: "#/badania", now: "Modele i trening → Badania i walidacja" },
  { old: "Dane, Diagnostyka (sekcja „Dane”)", hash: "#/dane · #/diagnostyka", now: "Ustawienia i diagnostyka → te same zakładki" },
  { old: "Ustawienia", hash: "#/ustawienia", now: "Ustawienia i diagnostyka → Ustawienia" },
  { old: "Licencje (1.27–1.29)", hash: "#/licencje", now: "usunięte w 1.30 (na Twoją prośbę) – link otwiera Ustawienia" },
  { old: "Menu – trzy wieże (1.26–1.31)", hash: "#/menu", now: "1.32: menu główne – miasto sześciu wież (launcher JOIN THE CULT na starcie, intro)" },
  { old: "Precision, Dyscypline, Profits", hash: "#/precision · #/dyscypline · #/profits", now: "bez zmian; Ice Tower w menu = Precision" },
  { old: "(nowe 1.32) Lightning / Wind / Control / Strategy Lab", hash: "#/lightning · #/wind · #/control · #/strategy-lab", now: "wieże menu głównego" },
  { old: "Trading Intelligence, AI Neural Lab, System Control", hash: "#/trading-intelligence · #/ai-neural-lab · #/system-control", now: "bez zmian („Nowe panele” w menu bocznym)" },
];
export const PAGES: { id: Page; label: string; short: string; icon: string }[] = [
  { id: "menu", label: "Menu główne – miasto wież", short: "Menu", icon: "✶" },
  { id: "lightning", label: "Lightning Tower – Live Signals Center", short: "Lightning", icon: "⚡" },
  { id: "wind", label: "Wind Portal – AI Engine Core", short: "Wind", icon: "✦" },
  { id: "control", label: "Control Tower – Bot Management Center", short: "Control", icon: "⚙" },
  { id: "strategy-lab", label: "Strategy Lab – Quant Strategy Chamber", short: "Strategy Lab", icon: "⚗" },
  { id: "precision", label: "Precision – wykresy i analiza rynku", short: "Precision", icon: "◎" },
  { id: "dyscypline", label: "Dyscypline – setupy i sygnały", short: "Dyscypline", icon: "⟐" },
  { id: "profits", label: "Profits – wyniki i rachunek", short: "Profits", icon: "◆" },
  { id: "trading-intelligence", label: "Trading Intelligence", short: "Trading", icon: "▦" },
  { id: "ai-neural-lab", label: "AI Neural Lab", short: "Neural Lab", icon: "✦" },
  { id: "system-control", label: "System Control Center", short: "Control", icon: "⛨" },
  { id: "pulpit", label: "Pulpit", short: "Pulpit", icon: "◈" },
  { id: "nc", label: "Neural Cyberpunk (11 ekranów)", short: "Neural", icon: "◎" },
  { id: "wykresy", label: "Wykresy MTF", short: "Wykresy", icon: "▦" },
  { id: "strefy", label: "Strefy rynkowe M1/M5/M15/M30", short: "Strefy", icon: "▥" },
  { id: "scalp-mtf", label: "Scalping MTF", short: "MTF", icon: "▤" },
  { id: "kontekst", label: "Kontekst rynku", short: "Kontekst", icon: "◎" },
  { id: "indykatory", label: "Indykatory BB/MA", short: "BB/MA", icon: "≋" },
  { id: "sygnal", label: "Analiza sygnału", short: "Sygnał", icon: "∿" },
  { id: "strategie", label: "SCALPING / HEDGING", short: "Strategie", icon: "⇅" },
  { id: "setupy", label: "Scenariusze (lab)", short: "Setupy", icon: "☑" },
  { id: "warunki", label: "Setup silnika S01–S12", short: "Silnik", icon: "☐" },
  { id: "ai", label: "Analiza AI", short: "AI", icon: "✧" },
  { id: "pozycje", label: "Pozycje i ryzyko", short: "Pozycje", icon: "⚖" },
  { id: "dziennik", label: "Dziennik i wyniki", short: "Dziennik", icon: "☰" },
  { id: "trening", label: "Centrum treningu (eksport → trening → aktywacja)", short: "Trening", icon: "⚙" },
  { id: "modele", label: "Modele i trening", short: "Modele", icon: "✦" },
  { id: "neural", label: "Neural System", short: "Neural", icon: "⟁" },
  { id: "struktura", label: "Structure Intelligence", short: "Struktura", icon: "⌗" },
  { id: "testy", label: "Testy scalp / prognozy", short: "Testy", icon: "⚗" },
  { id: "badania", label: "Badania i walidacja", short: "Badania", icon: "⚗" },
  { id: "formacje", label: "Formacje i biblioteka", short: "Formacje", icon: "W" },
  { id: "dane", label: "Dane i źródła", short: "Dane", icon: "⚙" },
  { id: "diagnostyka", label: "Diagnostyka systemu", short: "Diag.", icon: "⚕" },
  { id: "ustawienia", label: "Ustawienia", short: "Ustaw.", icon: "⚑" },
];
export const SECTION_OF: Record<string, string> = Object.fromEntries(GROUPS.flatMap((g) => g.pages.map((p) => [p, g.id])));
export const PAGE_IDS = PAGES.map((p) => p.id) as string[];
/** Pages rendered in the new terminal shell (features/shell); every other page keeps the existing AppShell. */
export const TERMINAL_PAGE_IDS: Page[] = ["trading-intelligence", "ai-neural-lab", "system-control"];
/** 1.26: the three tower views Precision / Dyscypline / Profits - their own frame (features/wizard). */
export const WIZARD_PAGE_IDS: Page[] = ["precision", "dyscypline", "profits"];
/** 1.32 CULT interface: main menu (city of towers) and the four tower panels - their own frame (features/cult). */
export const CULT_PAGE_IDS: Page[] = ["menu", "lightning", "wind", "control", "strategy-lab"];
const LAST = "mq.lastPage";

export function parse(hash: string): Route {
  const h = (hash || "").replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const first = parts[0] === "licencje" ? "ustawienia" : parts[0];          // 1.30: license system removed - the old link opens Ustawienia
  const page = (PAGE_IDS.includes(first) ? first : "pulpit") as Page;
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
      const page = (PAGE_IDS.includes(last || "") ? last : "menu") as Page;          // 1.26: first start = main menu
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
