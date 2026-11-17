// Central configuration of the graphic assets of the three tower views (1.32: the main menu has its own - features/cult/assets.ts): one place that says which file is used
// where, for what, and where it came from. Files live in frontend/public/assets/wizard (built by tools/wizard_assets.py).
export type WizardAsset = { file: string; url: string; purpose: string; source: string };

const BASE = "/assets/wizard/";
const a = (file: string, purpose: string, source: string): WizardAsset => ({ file, url: BASE + file, purpose, source });

export const WIZARD_ASSETS = {
  precision: a("precision-observatory.webp", "tło widoku Precision – obserwatorium, nocne niebo, chłodny cyjan",
    "załącznik użytkownika (wieża pod niebieskim księżycem), kadr 1920×1080 bez deformacji + korekta barwna w stronę cyjanu"),
  dyscypline: a("dyscypline-citadel.webp", "tło widoku Dyscypline – cytadela, portal, fioletowo-szmaragdowa energia",
    "załącznik użytkownika (oko nad cytadelą z kręgiem portalu), kadr 1920×1080 bez deformacji + szmaragdowy akcent"),
  profits: a("profits-vault.webp", "tło widoku Profits – skarbiec, szmaragdowe kryształy, złote światło",
    "grafika proceduralna (tools/wizard_backgrounds/profits_vault.html) – żaden załącznik nie przedstawiał skarbca"),
  logo: { file: "src/assets/pepe-wizard.webp", url: "(moduł Vite)", purpose: "logo – Pepe czarodziej w runicznym medalionie (lewy górny róg)",
    source: "istniejący zasób panelu (wcześniej w pasku bocznym terminala)" } as WizardAsset,
} as const;

/** Reference attachments used only as inspiration for procedural geometry / effects (not shipped as files). */
export const WIZARD_REFERENCES = [
  { what: "sieci neuronowe, filamenty, cząstki, film z rotującym grafem", used_for: "mapa przepływu danych i modeli (Wind Portal → Neural Data Flow)" },
  { what: "magiczne oczy", used_for: "rdzenie bocznych map (oko / kryształ w centrum grafu)" },
];

export type TowerId = "precision" | "dyscypline" | "profits";
export const TOWERS: { id: TowerId; name: string; role: string; desc: string; accent: string; accent2: string; bg: WizardAsset }[] = [
  { id: "precision", name: "Precision", role: "Wykresy i analiza rynku", desc: "Świece z MT5, interwały, strefy, warstwy analiz i stan źródła danych.",
    accent: "#3fe6ff", accent2: "#8a7bff", bg: WIZARD_ASSETS.precision },
  { id: "dyscypline", name: "Dyscypline", role: "Setupy, sygnały i warunki wejścia", desc: "Setupy silnika i strategii, warunki, trigger, unieważnienie, ryzyko.",
    accent: "#b46bff", accent2: "#2fe6a0", bg: WIZARD_ASSETS.dyscypline },
  { id: "profits", name: "Profits", role: "ROI, wyniki i historia", desc: "Rachunek, wynik netto, ROI z metodą, win rate, koszty, historia transakcji.",
    accent: "#ffcf5c", accent2: "#2fe6a0", bg: WIZARD_ASSETS.profits },
];
