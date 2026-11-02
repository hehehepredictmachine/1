// WebGL availability without loading three.js (the 3D scene is a lazy chunk). `#/menu?webgl=0` forces the fallback (tests, weak GPUs),
// `#/menu?webgl=1` forces the 3D scene even when it is measured as too slow (software rendering).
export function webglForced(): boolean {
  try {
    return new URLSearchParams(location.hash.split("?")[1] || "").get("webgl") === "1";
  } catch {
    return false;
  }
}

export function webglAvailable(): boolean {
  try {
    if (new URLSearchParams(location.hash.split("?")[1] || "").get("webgl") === "0") return false;
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}
