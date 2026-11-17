// Main Menu V2 – Neural Table (PepeMarketWizard_Menu_New_V2): three Pepe in dark suits at the round neural table with EIGHT towers
// (assets/neural/neural-table-scene.webp, 1672 x 941 px). Positions are pixels of that scene (the buildings never move). Every tower opens
// a REAL panel of the bot (its route below) – the menu never builds, replaces or changes a panel. The artwork has old names baked into
// the plates (WTC PEPE, BRAIN SIGNAL …): the live plates drawn by the menu cover them with the current names; old names stay as aliases.
import type { Page } from "../../router";

export const SCENE_W = 1672;
export const SCENE_H = 941;
type Box = [number, number, number, number];                 // x0, y0, x1, y1 in scene pixels

export type TowerKey = "wtc" | "signal" | "bank" | "roi" | "strategies" | "news" | "training" | "settings";
export type Tower = {
  key: TowerKey; id: string; name: string; legacy: string[]; page: Page; alias: string; panel: string; desc: string; color: string; icon: string;
  hit: Box; plate: Box; base: [number, number];               // base: point on the table where the neural path of this tower ends
};

/** Order = order of the top navigation (Menu V2 brief). `id` = the semantic identifier of the brief (pepe-wtc, pepe-signal …). */
export const TOWERS: Tower[] = [
  { key: "wtc", id: "pepe-wtc", name: "PEPE$WTC", legacy: ["WTC PEPE", "WTC", "TRADING"], page: "pepe-wtc", alias: "wtc",
    panel: "PEPE$WTC – Neural Market Command Center", icon: "▥", color: "#ffca67",
    desc: "Wykresy MT5, multi-chart, indykatory bota, Kronos, AI Live Zones i Volume Profile Auto Zones.",
    hit: [300, 289, 546, 539], plate: [334, 497, 518, 541], base: [420, 489] },
  { key: "signal", id: "pepe-signal", name: "PEPE$SIGNAL", legacy: ["BRAIN SIGNAL", "BACKTEST"], page: "pepe-signal", alias: "signal",
    panel: "PEPE$SIGNAL – Signal Intelligence Center", icon: "◈", color: "#be72ff",
    desc: "Strumień sygnałów wszystkich strategii, warunki wejścia / triggera / unieważnienia i oceny modeli AI.",
    hit: [557, 261, 805, 509], plate: [596, 452, 778, 497], base: [677, 467] },
  { key: "bank", id: "pepe-bank", name: "PEPE$BANK", legacy: ["AI AGENT"], page: "lightning", alias: "bank",
    panel: "Lightning Tower – Live Signals Center", icon: "▣", color: "#6bffc4",
    desc: "Pełne informacje i historia sygnałów: plan wejścia, cykl życia, walidacja i wyniki w R.",
    hit: [868, 262, 1094, 516], plate: [903, 452, 1087, 497], base: [981, 485] },
  { key: "roi", id: "pepe-roi", name: "PEPE$ROI", legacy: ["LEADERBOARD"], page: "profits", alias: "roi",
    panel: "Profits – wyniki i rachunek", icon: "↗", color: "#ff6c6c",
    desc: "Rozliczone transakcje MT5, statystyki, wynik netto i progresja rachunku.",
    hit: [1124, 303, 1354, 547], plate: [1170, 496, 1350, 540], base: [1237, 508] },
  { key: "strategies", id: "strategies", name: "STRATEGIES", legacy: [], page: "strategy-lab", alias: "strategy",
    panel: "Strategy Lab – Quant Strategy Chamber", icon: "◇", color: "#5ce4ff",
    desc: "Strategie bota, tryb automatyczny (Auto Mode), ustawienia, biblioteka i porównanie.",
    hit: [251, 528, 514, 763], plate: [270, 701, 475, 750], base: [377, 719] },
  { key: "news", id: "market-news", name: "MARKET NEWS", legacy: ["NEWS"], page: "kontekst", alias: "news",
    panel: "Kontekst rynku – wiadomości i kalendarz makro", icon: "◉", color: "#ffb452",
    desc: "Nagłówki, kalendarz makro i kontekst rynku (brak feedu pokazany jawnie).",
    hit: [560, 568, 788, 828], plate: [579, 763, 775, 811], base: [675, 760] },
  { key: "training", id: "training-lab", name: "TRAINING LAB", legacy: ["TRAINING"], page: "trening", alias: "training",
    panel: "Centrum treningu – eksport, walidacja, trening, aktywacja", icon: "⬡", color: "#ff6bd4",
    desc: "Eksport historii MT5, walidacja danych i trening modeli z aktywacją i rollbackiem.",
    hit: [867, 553, 1121, 810], plate: [927, 763, 1131, 811], base: [1006, 758] },
  { key: "settings", id: "settings", name: "SETTINGS", legacy: [], page: "ustawienia", alias: "settings",
    panel: "Ustawienia i połączenia", icon: "⚙", color: "#72bbff",
    desc: "Połączenie MT5, ryzyko, koszty, strategia, agent, rynki i wygląd.",
    hit: [1200, 552, 1440, 767], plate: [1229, 700, 1432, 750], base: [1325, 704] },
];

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** Old and new route names of the towers -> the real page (#/pepe-wtc, #/wtc, #/brain-signal, #/training-lab, #/leaderboard …).
 *  Ids that are real pages themselves (pepe-wtc, pepe-signal) are not aliases. */
export const TOWER_ALIASES: Record<string, Page> = Object.fromEntries(TOWERS.flatMap((t) => [
  [t.id, t.page], [t.alias, t.page], ...t.legacy.map((l) => [slug(l), t.page] as [string, Page]),
]).filter(([k, p]) => k !== p));

export const CORE: [number, number] = [838, 587];              // neural brain hologram in the middle of the table
export const HANDS: [number, number] = [845, 262];             // steepled fingers of the Pepe in the middle (2.5D reach gesture)
/** The three Pepe (click = light impulse; Pepe in the middle also fires the neural wave). */
export const PEPES: { key: "left" | "center" | "right"; label: string; hit: Box; flash: [number, number] }[] = [
  { key: "left", label: "Pepe z cygarem (po lewej)", hit: [10, 156, 360, 486], flash: [295, 325] },
  { key: "center", label: "Pepe w koronie (pośrodku) – fala neuronowa", hit: [592, 79, 1084, 344], flash: [838, 315] },
  { key: "right", label: "Pepe liczący banknoty (po prawej)", hit: [1305, 163, 1663, 500], flash: [1455, 380] },
];

export const pct = (v: number, of: number) => `${(v / of) * 100}%`;
export const boxStyle = (b: Box) => ({ left: pct(b[0], SCENE_W), top: pct(b[1], SCENE_H), width: pct(b[2] - b[0], SCENE_W), height: pct(b[3] - b[1], SCENE_H) });
