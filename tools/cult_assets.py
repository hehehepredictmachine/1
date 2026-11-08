"""Builds the graphic layers of the CULT interface (launcher, intro, main menu, Lightning / Wind / Control / Strategy Lab) from the
approved visualisations in projekt.zip.

  python tools/cult_assets.py --src <folder with menu.jpg, launcher.jpg, lig.jpg, wind.jpg, ai.jpg, controltower.jpg, strategy.png
                                     and the four texture images "Obraz ChatGPT ….jpg">

Rules (no invented art, no invented numbers):
* every layer is a crop of the approved visualisation, at its original pixel size (no stretching);
* the visualisations contain example numbers (+352.68 %, 87.4 %, $1,350,000, 88.4 % …). Those are NEVER shipped: crops avoid the
  stat panels, the few baked labels inside the menu scene (brand, slogan, bell / profile icons) are removed by inpainting and drawn
  live in HTML, and panel backgrounds are blurred until no text is legible;
* the four texture images are the card art of the AI models (XGBoost, Random Forest, ML engine, Monte Carlo).
Output: frontend/public/assets/cult/*.webp + zrodla.json (SHA-256 of the sources and the crop box of every layer)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "assets" / "cult"

# ---------------------------------------------------------------- crop boxes (pixels of the source image)
SCENE = (236, 0, 1536, 708)                      # menu.jpg without the left menu and the bottom stat panels
TOWERS = {                                        # menu.jpg - the six towers with their labels
    "lightning": (452, 376, 594, 594), "ice": (598, 366, 748, 578), "wind": (744, 330, 888, 568),
    "control": (890, 360, 1031, 568), "strategy": (1030, 340, 1188, 578), "fire": (1188, 370, 1328, 588),
}
CHARACTERS = {                                    # menu.jpg - the four Pepe wizards (upper bodies) and the king portrait
    "lightning": (262, 212, 508, 470), "ice": (500, 150, 805, 430), "wind": (840, 150, 1120, 405), "fire": (1170, 200, 1510, 500),
    "king": (1338, 28, 1502, 246),
}
EFFECTS = {"lightning": (420, 205, 512, 312), "fire": (1180, 210, 1272, 336), "core": (730, 582, 972, 708),
           "ice_crystal": (712, 150, 800, 262), "wind_swirl": (818, 140, 1186, 312), "city": (236, 420, 1536, 708)}
TEXT_BOXES = [(822, 4, 878, 33), (652, 31, 1053, 67), (617, 69, 1088, 95), (402, 97, 1322, 146), (766, 142, 934, 164), (1405, 5, 1532, 61)]
LOGO = (84, 27, 161, 97)                         # menu.jpg - crowned Pepe line logo of the left panel
MEDALLION = (796, 690, 954, 852)                  # menu.jpg - brain medallion between the stat panels (no numbers)
LAUNCHER = (140, 112, 1396, 546)                  # launcher.jpg - inside the gold frame, above the "JOIN THE CULT" text
LAUNCHER_CROWN = (733, 14, 806, 54)
PANELS = {   # file, Pepe crop, centre piece crop (decorative - labels only, no values)
    "lightning": ("lig.jpg", (180, 392, 428, 762), (694, 712, 856, 864)),
    "wind": ("wind.jpg", (150, 380, 402, 752), (596, 84, 1112, 484)),
    "control": ("controltower.jpg", (163, 360, 400, 602), (712, 756, 830, 865)),
    "strategy": ("strategy.png", (170, 470, 480, 846), (594, 106, 1176, 422)),
}
# parts of a Pepe crop covered by a baked panel of the visualisation -> made transparent (box relative to the crop)
PANEL_CUTS = {"strategy": [(75, 0, 320, 80), (150, 0, 320, 184), (172, 176, 320, 202)]}
CORE_TREE = ("ai.jpg", (688, 128, 1012, 724))     # Wind Portal: the neural tree of "AI ENGINE CORE" (the % in it is covered live)
CORE_TEXT = [(98, 352, 208, 466)]                  # baked "AI CONSENSUS CORE 88.4%" inside the crop -> inpainted, value drawn live
TEXTURES = {"xgboost": "Obraz ChatGPT 5 lis 2026, 10_39_59.jpg", "ml": "Obraz ChatGPT 5 lis 2026, 10_40_03.jpg",
            "forest": "Obraz ChatGPT 5 lis 2026, 10_40_07.jpg", "flow": "Obraz ChatGPT 5 lis 2026, 10_40_11.jpg"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Separable box blur (edge-padded) on a 2-D or 3-D float array; three passes approximate a Gaussian."""
    for _ in range(3):
        for ax in (0, 1):
            pad = [(0, 0)] * a.ndim
            pad[ax] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=ax)
            hi = np.take(c, np.arange(2 * r + 1, c.shape[ax]), axis=ax)
            lo = np.take(c, np.arange(0, c.shape[ax] - 2 * r - 1), axis=ax)
            a = (hi - lo) / (2 * r + 1)
    return a


def inpaint(im: Image.Image, boxes, thr: int = 62, rounds: int = 40) -> Image.Image:
    """Removes bright text inside the boxes: mask = bright pixels (dilated), filled from the surrounding pixels by iterative
    normalized blur (diffusion). Only the region around the boxes is processed."""
    a = np.asarray(im).astype(np.float32)
    x0 = max(0, min(b[0] for b in boxes) - 24); y0 = max(0, min(b[1] for b in boxes) - 24)
    x1 = min(a.shape[1], max(b[2] for b in boxes) + 24); y1 = min(a.shape[0], max(b[3] for b in boxes) + 24)
    reg = a[y0:y1, x0:x1].copy()
    lum = reg.max(axis=2)
    mask = np.zeros(lum.shape, bool)
    for bx0, by0, bx1, by1 in boxes:
        sl = (slice(by0 - y0, by1 - y0), slice(bx0 - x0, bx1 - x0))
        mask[sl] |= lum[sl] > thr
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    known = (~mask).astype(np.float32)
    fill = reg * known[..., None]
    for _ in range(rounds):
        num = _box_blur(fill * known[..., None], 3)
        den = _box_blur(known, 3)[..., None]
        est = num / np.maximum(den, 1e-4)
        fill = np.where(mask[..., None], est, reg)
        known = np.where(mask & (den[..., 0] > 0.02), 1.0, known).astype(np.float32)
    out = a.copy()
    out[y0:y1, x0:x1] = fill
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def feather(im: Image.Image, cuts, edge: float = 0.10) -> Image.Image:
    """RGBA with soft edges (the figure blends into the panel) and transparent rectangles where a baked UI panel overlapped."""
    w, h = im.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ex, ey = max(1.0, w * edge), max(1.0, h * edge)
    a = np.minimum.reduce([np.clip(xx / ex, 0, 1), np.clip((w - 1 - xx) / ex, 0, 1), np.clip(yy / ey, 0, 1), np.ones_like(xx)])
    for x0, y0, x1, y1 in cuts:
        dx = np.maximum(np.maximum(x0 - xx, xx - x1), 0)
        dy = np.maximum(np.maximum(y0 - yy, yy - y1), 0)
        inside_dist = np.where((xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1), 0, np.hypot(dx, dy))
        a = np.minimum(a, np.clip(inside_dist / 18.0, 0, 1))
    rgba = np.dstack([np.asarray(im.convert("RGB")), (a * 255).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def save(im: Image.Image, name: str, report: dict, src: str, box=None, q: int = 90, alpha=False):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    (im if alpha else im.convert("RGB")).save(p, "WEBP", quality=q, method=6)
    report["outputs"][name] = {"from": src, "box": list(box) if box else None, "size": list(im.size), "sha256": sha(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    a = ap.parse_args()
    src = Path(a.src)
    need = ["menu.jpg", "launcher.jpg", "lig.jpg", "wind.jpg", "ai.jpg", "controltower.jpg", "strategy.png", *TEXTURES.values()]
    missing = [n for n in need if not (src / n).is_file()]
    if missing:
        raise SystemExit(f"brak plików w {src}: {', '.join(missing)}")
    report = {"sources": {n: {"sha256": sha(src / n), "size": list(Image.open(src / n).size)} for n in need}, "outputs": {}}

    menu = Image.open(src / "menu.jpg").convert("RGB")
    clean = inpaint(menu, TEXT_BOXES)                                       # brand, slogan, icons -> drawn live in HTML
    save(clean.crop(SCENE), "menu-scene.webp", report, "menu.jpg", SCENE, q=92)
    dim = clean.crop(SCENE).filter(ImageFilter.GaussianBlur(26))
    save(dim, "menu-scene-blur.webp", report, "menu.jpg", SCENE, q=70)    # fills the screen around the scene (letterbox)
    for k, b in TOWERS.items():
        save(clean.crop(b), f"tower-{k}.webp", report, "menu.jpg", b, q=92)
    for k, b in CHARACTERS.items():
        save(clean.crop(b), f"char-{k}.webp", report, "menu.jpg", b, q=92)
    for k, b in EFFECTS.items():
        save(clean.crop(b), f"fx-{k}.webp", report, "menu.jpg", b, q=90)
    save(menu.crop(LOGO), "logo.webp", report, "menu.jpg", LOGO, q=92)
    save(menu.crop(MEDALLION), "medallion.webp", report, "menu.jpg", MEDALLION, q=92)

    la = Image.open(src / "launcher.jpg").convert("RGB")
    save(la.crop(LAUNCHER), "launcher-scene.webp", report, "launcher.jpg", LAUNCHER, q=90)
    save(la.crop(LAUNCHER_CROWN), "crown.webp", report, "launcher.jpg", LAUNCHER_CROWN, q=92)
    small = la.crop(LAUNCHER).resize((880, round(880 * (LAUNCHER[3] - LAUNCHER[1]) / (LAUNCHER[2] - LAUNCHER[0]))), Image.LANCZOS)
    save(small, "launcher-scene-small.webp", report, "launcher.jpg", LAUNCHER, q=80)   # embedded in the Windows launcher window

    for k, (fn, pepe, centre) in PANELS.items():
        im = Image.open(src / fn).convert("RGB")
        save(feather(im.crop(pepe), PANEL_CUTS.get(k, [])), f"panel-{k}-pepe.webp", report, fn, pepe, q=90, alpha=True)
        save(im.crop(centre), f"panel-{k}-centre.webp", report, fn, centre, q=90)
        bg = im.resize((im.width // 2, im.height // 2), Image.LANCZOS).filter(ImageFilter.GaussianBlur(22))
        save(bg, f"panel-{k}-bg.webp", report, fn, None, q=60)                     # colour atmosphere only - nothing legible
    fn, box = CORE_TREE
    save(inpaint(Image.open(src / fn).convert("RGB").crop(box), CORE_TEXT, thr=96, rounds=60), "wind-core-tree.webp", report, fn, box, q=90)
    for k, fn in TEXTURES.items():
        im = Image.open(src / fn).convert("RGB")
        im.thumbnail((640, 640), Image.LANCZOS)
        save(im, f"tex-{k}.webp", report, fn, None, q=82)
    # 1.34: the Windows launcher window embeds desktop/assets/launcher-speech.webp from tools/neural_city_assets.py (TASK 001)
    (OUT / "zrodla.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum((OUT / n).stat().st_size for n in report["outputs"])
    print(f"{len(report['outputs'])} plików, {total // 1024} KB -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
