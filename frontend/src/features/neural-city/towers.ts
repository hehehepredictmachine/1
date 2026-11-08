// Neural City Main Menu V7.0 - the seven towers of the approved scene (assets/neural/neural-city-scene.webp, 1672 x 941 px).
// Positions are pixels of that scene (the buildings never move); every tower opens an EXISTING panel of the bot (its route below) -
// the menu never builds or replaces a panel. Old names stay as legacy aliases (route + search), the visible name is the new one.
import type { Page } from "../../router";

export const SCENE_W = 1672;
export const SCENE_H = 941;
type Box = [number, number, number, number];                 // x0, y0, x1, y1 in scene pixels

export type TowerKey = "wtc" | "signal" | "bank" | "news" | "strategies" | "settings" | "roi";
export type Tower = {
  key: TowerKey; name: string; legacy: string[]; page: Page; alias: string; panel: string; desc: string; color: string;
  hit: Box; plate: Box; ring: [number, number, number]; // ring: centre x, centre y, radius (px) of the hologram ring at the base
};

export const TOWERS: Tower[] = [
  { key: "wtc", name: "PEPE$WTC", legacy: ["WTC PEPE", "TRADING"], page: "trading-intelligence", alias: "wtc", panel: "Trading Intelligence – terminal handlowy",
    desc: "Rynek, scenariusze, sygnały i pozycje – istniejący terminal handlowy.", color: "#39ff8f",
    hit: [300, 250, 540, 520], plate: [345, 470, 506, 512], ring: [425, 468, 118] },
  { key: "signal", name: "PEPE$SIGNAL", legacy: ["BRAIN SIGNAL", "BACKTEST"], page: "wind", alias: "pepe-signal", panel: "Wind Portal – AI Engine Core",
    desc: "Oceny modeli AI, konsensus, Monte Carlo i ślad decyzji strategii.", color: "#5fe3ff",
    hit: [60, 370, 320, 652], plate: [91, 608, 289, 648], ring: [190, 600, 122] },
  { key: "bank", name: "PEPE$BANK", legacy: ["AI AGENT"], page: "lightning", alias: "pepe-bank", panel: "Lightning Tower – Live Signals Center",
    desc: "Sygnały BUY/SELL wszystkich strategii, plan wejścia i cykl życia sygnału.", color: "#7d8bff",
    hit: [1130, 250, 1370, 516], plate: [1169, 471, 1330, 512], ring: [1250, 468, 118] },
  { key: "news", name: "MARKET NEWS", legacy: ["NEWS"], page: "kontekst", alias: "market-news", panel: "Kontekst rynku – wiadomości i kalendarz makro",
    desc: "Nagłówki, kalendarz makro i sentyment (brak feedu pokazany jawnie).", color: "#5fe3ff",
    hit: [1370, 360, 1640, 652], plate: [1398, 609, 1599, 648], ring: [1498, 600, 124] },
  { key: "strategies", name: "STRATEGIES", legacy: [], page: "strategy-lab", alias: "strategies", panel: "Strategy Lab – Quant Strategy Chamber",
    desc: "Silnik strategii, ustawienia, biblioteka i porównanie.", color: "#39ff8f",
    hit: [270, 560, 560, 832], plate: [315, 786, 508, 828], ring: [412, 780, 132] },
  { key: "settings", name: "SETTINGS", legacy: [], page: "ustawienia", alias: "settings", panel: "Ustawienia",
    desc: "MT5, ryzyko, koszty, strategia, agent, rynki i wygląd.", color: "#39ff8f",
    hit: [700, 620, 1000, 868], plate: [755, 823, 950, 864], ring: [852, 818, 134] },
  { key: "roi", name: "PEPE$ROI", legacy: ["LEADERBOARD"], page: "profits", alias: "pepe-roi", panel: "Profits – wyniki i rachunek",
    desc: "Rozliczone pozycje MT5, wynik netto i progresja rachunku.", color: "#ffcf5c",
    hit: [1130, 560, 1420, 832], plate: [1167, 789, 1367, 828], ring: [1267, 780, 132] },
];

/** Old and new route names of the towers -> the real page (#/wtc, #/pepe-signal, #/brain-signal, #/leaderboard ...). */
export const TOWER_ALIASES: Record<string, Page> = Object.fromEntries(TOWERS.flatMap((t) => [
  [t.alias, t.page], ...t.legacy.map((l) => [l.toLowerCase().replace(/[^a-z0-9]+/g, "-"), t.page] as [string, Page]),
]));

export const CORE: [number, number] = [845, 520];             // AI brain hologram in the middle of the table
export const HANDS: [number, number] = [858, 296];            // Pepe's steepled fingers - start of the reach gesture (2.5D)

export const pct = (v: number, of: number) => `${(v / of) * 100}%`;
export const boxStyle = (b: Box) => ({ left: pct(b[0], SCENE_W), top: pct(b[1], SCENE_H), width: pct(b[2] - b[0], SCENE_W), height: pct(b[3] - b[1], SCENE_H) });
