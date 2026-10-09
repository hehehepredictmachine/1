// Presentation layer only: animated background + dancing frog. Never affects data, router or orders.
//
// FULL  = animated background (if the original animated GIF is available) + animated frog
// LIGHT = static background frame, animated frog, reduced decorative effects
// OFF   = static frames of both images, no decorative animation
// The static mode really swaps the <img> source for a still frame (prepared PNG/WebP, or frame 0
// decoded in the browser with ImageDecoder / canvas for a user-uploaded GIF) - CSS cannot stop GIF frames.
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { apiGet } from "./api";
import { useTheme } from "./theme";

export type AnimMode = "FULL" | "LIGHT" | "OFF";
type Assets = Record<string, { animated_available: boolean; source: string; animated_url: string; static_url: string; gif: any }>;
type Prefs = { mode: AnimMode; dim: number; posX: number; posY: number };

const KEY = "mq.appearance";

function initialPrefs(): Prefs {
  let reduced = false;
  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    /* no matchMedia */
  }
  const def: Prefs = { mode: reduced ? "OFF" : "FULL", dim: 0.55, posX: 22, posY: 45 };
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...def, ...JSON.parse(raw) } : def;
  } catch {
    return def;
  }
}

/** First frame of a GIF as an object URL (ImageDecoder when available, canvas fallback). */
async function firstFrame(url: string): Promise<string | null> {
  try {
    const W: any = window as any;
    if (W.ImageDecoder) {
      const data = await (await fetch(url, { credentials: "same-origin" })).arrayBuffer();
      const dec = new W.ImageDecoder({ data, type: "image/gif" });
      const { image } = await dec.decode({ frameIndex: 0 });
      const c = document.createElement("canvas");
      c.width = image.displayWidth;
      c.height = image.displayHeight;
      c.getContext("2d")!.drawImage(image, 0, 0);
      image.close?.();
      const blob: Blob | null = await new Promise((r) => c.toBlob(r, "image/png"));
      return blob ? URL.createObjectURL(blob) : null;
    }
    const img = new Image();
    img.src = url;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    c.getContext("2d")!.drawImage(img, 0, 0);
    const blob: Blob | null = await new Promise((r) => c.toBlob(r, "image/png"));
    return blob ? URL.createObjectURL(blob) : null;
  } catch {
    return null;
  }
}

type Ctx = {
  prefs: Prefs;
  setPrefs: (p: Partial<Prefs>) => void;
  assets: Assets | null;
  reloadAssets: () => void;
  hidden: boolean;
  bgSrc: string | null;
  bgAnimated: boolean;
  frogSrc: string | null;
  frogAnimated: boolean;
};
const AppearanceCtx = createContext<Ctx | null>(null);

export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  const [prefs, setP] = useState<Prefs>(initialPrefs);
  const [assets, setAssets] = useState<Assets | null>(null);
  const [hidden, setHidden] = useState(typeof document !== "undefined" && document.visibilityState === "hidden");
  const [stills, setStills] = useState<Record<string, string | null>>({});
  const reloadAssets = () => apiGet<Assets>("/api/v1/appearance/assets").then(setAssets).catch(() => setAssets(null));
  useEffect(() => { reloadAssets(); }, []);
  useEffect(() => {
    const f = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  // still frames for user-uploaded GIFs (built-in assets ship prepared still images)
  useEffect(() => {
    if (!assets) return;
    let alive = true;
    (async () => {
      const out: Record<string, string | null> = {};
      for (const slot of ["background", "frog"]) {
        const a = assets[slot];
        out[slot] = a && a.source === "USER_UPLOAD" ? await firstFrame(a.animated_url) : null;
      }
      if (alive) setStills(out);
    })();
    return () => { alive = false; };
  }, [assets]);
  const setPrefs = (p: Partial<Prefs>) => {
    const n = { ...prefs, ...p };
    setP(n);
    try {
      localStorage.setItem(KEY, JSON.stringify(n));
    } catch {
      /* storage unavailable */
    }
  };
  const value = useMemo<Ctx>(() => {
    const bg = assets?.background;
    const frog = assets?.frog;
    // a hidden tab shows still frames (decoration only - the backend keeps running)
    const bgAnimated = !!bg?.animated_available && prefs.mode === "FULL" && !hidden;
    const frogAnimated = !!frog?.animated_available && prefs.mode !== "OFF" && !hidden;
    const bgStill = bg ? (bg.source === "USER_UPLOAD" ? stills.background ?? null : bg.static_url) : null;
    const frogStill = frog ? (frog.source === "USER_UPLOAD" ? stills.frog ?? null : frog.static_url) : null;
    return {
      prefs, setPrefs, assets, reloadAssets, hidden,
      bgSrc: bg ? (bgAnimated ? bg.animated_url : bgStill ?? bg.static_url) : null,
      bgAnimated,
      frogSrc: frog ? (frogAnimated ? frog.animated_url : frogStill ?? frog.static_url) : null,
      frogAnimated,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs, assets, hidden, stills]);
  return <AppearanceCtx.Provider value={value}>{children}</AppearanceCtx.Provider>;
}

export function useAppearance(): Ctx {
  const c = useContext(AppearanceCtx);
  if (!c) throw new Error("no appearance");
  return c;
}

/** Fixed layer under the whole UI: no pointer events, no layout shift, no extra scroll. */
export const BackgroundLayer = React.memo(function BackgroundLayer() {
  const { bgSrc, prefs } = useAppearance();
  const { effective: t } = useTheme();
  if (!bgSrc) return null;
  return (
    <div className="mq-bg" aria-hidden="true">
      <img src={bgSrc} alt="" style={{ objectPosition: `${prefs.posX}% ${prefs.posY}%`, opacity: Number(t.gifOpacity ?? 1) }} data-anim={bgSrc.includes("/media/") ? "1" : "0"} />
      <div className="mq-bg-dim" style={{ opacity: Number(t.overlayDim ?? prefs.dim) }} />
    </div>
  );
});

/** Second GIF: dancing frog next to BALANCE (fixed box -> numbers never jump while loading). */
export const Frog = React.memo(function Frog() {
  const { frogSrc, frogAnimated } = useAppearance();
  const { effective: t } = useTheme();
  return (
    <span className="mq-frog" aria-hidden="true" title={frogAnimated ? "" : "animacja wyłączona – kadr statyczny"}>
      {frogSrc && <img src={frogSrc} alt="" data-anim={frogAnimated ? "1" : "0"} style={{ opacity: Number(t.frogOpacity ?? 1) }} />}
    </span>
  );
});
