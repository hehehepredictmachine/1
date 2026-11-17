// Appearance of the new panels ("Wygląd"): accent, background, panel and text colour, font size, animation. A per-client preference
// (this browser / the app window profile) - never sent to the bot. Applied as CSS variables on the shell root only.
import { createContext, useContext, type CSSProperties } from "react";

export type Motion = "full" | "reduced" | "off";
export interface Look { accent: string; bg: string; panel: string; text: string; fontSize: number; motion: Motion }

export const DEFAULT_LOOK: Look = { accent: "#2fd394", bg: "#070909", panel: "#0f1415", text: "#dbe7e1", fontSize: 14, motion: "full" };
export const PRESETS: { id: string; label: string; look: Look }[] = [
  { id: "pepe", label: "Pepe (domyślny)", look: DEFAULT_LOOK },
  { id: "gold", label: "Złoto", look: { ...DEFAULT_LOOK, accent: "#d8b45a" } },
  { id: "contrast", label: "Wysoki kontrast", look: { accent: "#5dffb0", bg: "#000000", panel: "#0b0b0b", text: "#ffffff", fontSize: 15, motion: "reduced" } },
];

const HEX = /^#[0-9a-f]{6}$/i;

export function validLook(v: any): v is Look {
  return !!v && typeof v === "object" && [v.accent, v.bg, v.panel, v.text].every((c) => typeof c === "string" && HEX.test(c))
    && typeof v.fontSize === "number" && v.fontSize >= 12 && v.fontSize <= 18 && ["full", "reduced", "off"].includes(v.motion);
}

function lum(hex: string): number {
  const ch = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

/** WCAG 2.x contrast ratio (1..21). */
export function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return Math.round(((x + 0.05) / (y + 0.05)) * 100) / 100;
}

function mix(hex: string, other: string, t: number): string {
  const p = (h: string, i: number) => parseInt(h.slice(i, i + 2), 16);
  return "#" + [1, 3, 5].map((i) => Math.round(p(hex, i) * (1 - t) + p(other, i) * t).toString(16).padStart(2, "0")).join("");
}

/** CSS variables of the shell; derived tones (second panel, lines, dim text) follow the chosen colours. */
export function lookStyle(l: Look): CSSProperties {
  const ink = lum(l.accent) > 0.35 ? "#04150e" : "#ffffff";
  return {
    "--t-accent": l.accent, "--t-accent-ink": ink, "--t-bg": l.bg, "--t-bg2": mix(l.bg, l.panel, 0.5), "--t-panel": l.panel,
    "--t-panel2": mix(l.panel, l.text, 0.04), "--t-line": mix(l.panel, l.text, 0.1), "--t-line2": mix(l.panel, l.accent, 0.22),
    "--t-text": l.text, "--t-strong": mix(l.text, "#ffffff", 0.5), "--t-dim": mix(l.text, l.panel, 0.38), fontSize: `${l.fontSize}px`,
  } as CSSProperties;
}

export const LookCtx = createContext<{ look: Look; setLook: (l: Look) => void; openLook: () => void } | null>(null);
export function useLook() {
  const c = useContext(LookCtx);
  if (!c) throw new Error("no look context");
  return c;
}
