// Graphic layers of the CULT interface, cut out of the approved visualisations (projekt.zip) by tools/cult_assets.py - crop boxes and
// SHA-256 of the sources are in public/assets/cult/zrodla.json. The example numbers of the visualisations are never shipped.
const B = "/assets/cult/";
export const A = {
  scene: B + "menu-scene.webp", sceneBlur: B + "menu-scene-blur.webp", logo: B + "logo.webp", medallion: B + "medallion.webp",
  crown: B + "crown.webp", launcher: B + "launcher-scene.webp", coreTree: B + "wind-core-tree.webp",
  tower: (k: string) => `${B}tower-${k}.webp`, char: (k: string) => `${B}char-${k}.webp`, fx: (k: string) => `${B}fx-${k}.webp`,
  panelPepe: (k: string) => `${B}panel-${k}-pepe.webp`, panelCentre: (k: string) => `${B}panel-${k}-centre.webp`, panelBg: (k: string) => `${B}panel-${k}-bg.webp`,
  tex: (k: "xgboost" | "ml" | "forest" | "flow") => `${B}tex-${k}.webp`,
};

/** menu.jpg coordinates (1536 x 864); the scene is the crop SCENE. Layers are placed in % of the scene so they always match it. */
export const SCENE = { x: 236, y: 0, w: 1300, h: 708 };
type Box = [number, number, number, number];
export const box = (b: Box) => ({ left: `${((b[0] - SCENE.x) / SCENE.w) * 100}%`, top: `${((b[1] - SCENE.y) / SCENE.h) * 100}%`,
  width: `${((b[2] - b[0]) / SCENE.w) * 100}%`, height: `${((b[3] - b[1]) / SCENE.h) * 100}%` });

export type TowerKey = "lightning" | "ice" | "wind" | "control" | "strategy" | "fire";
export const TOWER_BOX: Record<TowerKey, Box> = {
  lightning: [452, 376, 594, 594], ice: [598, 366, 748, 578], wind: [744, 330, 888, 568],
  control: [890, 360, 1031, 568], strategy: [1030, 340, 1188, 578], fire: [1188, 370, 1328, 588],
};
export const CHAR_BOX: Record<"lightning" | "ice" | "wind" | "fire" | "king", Box> = {
  lightning: [262, 212, 508, 470], ice: [500, 150, 805, 430], wind: [840, 150, 1120, 405], fire: [1170, 200, 1510, 500], king: [1338, 28, 1502, 246],
};
export const FX_BOX: Record<"lightning" | "fire" | "core" | "ice_crystal" | "wind_swirl" | "city", Box> = {
  lightning: [420, 205, 512, 312], fire: [1180, 210, 1272, 336], core: [730, 582, 972, 708], ice_crystal: [712, 150, 800, 262],
  wind_swirl: [818, 140, 1186, 312], city: [236, 420, 1536, 708],
};
