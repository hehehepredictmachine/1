"""Graphic layers of the Neural City Main Menu V7.0 and of the JOIN THE CULT launcher (1.34) from the delivered packages.

  python tools/neural_city_assets.py --menu <folder of PepeMarketWizard_NeuralCity_MainMenu_V7_0> --launcher <folder Launcher>

Rules (the same as tools/cult_assets.py - no invented art, no invented numbers):
* the scene is the approved `assets/neural-city-reference.png` at its original pixel size (no stretching);
* the reference contains baked UI that must not be shipped as if it were live: the OLD tower names (WTC PEPE, BRAIN SIGNAL, AI AGENT,
  MARKET NEWS, STRATEGIES, SETTINGS, LEADERBOARD), the example account values (72.8 %, +168.4 %, $1,248,932, "DEMO"), the preview
  navigation / profile, the "INTERAKTYWNY PODGLĄD WEB · DANE DEMO" tag, the slogan panel and the preview tool buttons. They are removed
  by inpainting (white label text only - the neon plates stay) and drawn live in HTML: current names, values from the bot or N/A;
* the launcher background is the delivered image of Pepe speaking to the crowd, unchanged (re-encoded only);
* the neural animation (GIF of the launcher package) is re-encoded as an animated WebP with every frame and its timing kept.
Output: frontend/public/assets/neural/*.webp, desktop/assets/launcher-speech.webp (embedded in the EXE) and
frontend/public/assets/neural/zrodla.json (SHA-256 of every source and output, inpainted boxes)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cult_assets import _box_blur  # noqa: E402  (same diffusion fill as the 1.32 layers)

OUT = ROOT / "frontend" / "public" / "assets" / "neural"
DESK = ROOT / "desktop" / "assets"

# ---------------------------------------------------------------- neural-city-reference.png (1672 x 941)
LABEL_TEXT = {                                   # white text of the old names inside the neon plates (the plates are kept)
    "wtc": (368, 472, 490, 512), "agent": (1190, 472, 1310, 512), "brain": (100, 610, 284, 648), "news": (1408, 610, 1596, 648),
    "strategies": (334, 790, 496, 828), "settings": (784, 826, 924, 864), "leaderboard": (1176, 790, 1360, 828),
}
PANELS = {                                       # baked preview UI -> filled from the surrounding scene, drawn live in HTML
    "titlebar": (0, 0, 1672, 22), "nav_profile": (480, 22, 1672, 86), "stats": (16, 106, 550, 244), "tag": (1296, 84, 1664, 113),
    "slogan": (1236, 124, 1650, 250), "hint": (16, 878, 282, 924), "tools": (1482, 874, 1662, 924),
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def diffuse(a: np.ndarray, mask: np.ndarray, rounds: int) -> np.ndarray:
    """Fill the masked pixels from their neighbourhood (iterative normalized blur)."""
    known = (~mask).astype(np.float32)
    fill = a * known[..., None]
    for _ in range(rounds):
        num = _box_blur(fill * known[..., None], 3)
        den = _box_blur(known, 3)[..., None]
        est = num / np.maximum(den, 1e-4)
        fill = np.where(mask[..., None], est, a)
        known = np.where(mask & (den[..., 0] > 0.02), 1.0, known).astype(np.float32)
    return fill


def clean_scene(im: Image.Image) -> tuple[Image.Image, dict]:
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    mask = np.zeros((h, w), bool)
    removed = {}
    for k, (x0, y0, x1, y1) in LABEL_TEXT.items():               # white glyphs: all three channels bright
        sub = a[y0:y1, x0:x1]
        m = sub.min(axis=2) > 125
        mask[y0:y1, x0:x1] |= m
        removed[k] = {"box": [x0, y0, x1, y1], "pixels": int(m.sum())}
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    out = diffuse(a, mask, 40)
    big = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in PANELS.values():
        big[y0:y1, x0:x1] = True
    out = diffuse(out, big, 90)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), removed


def save(im: Image.Image, p: Path, rep: dict, src: str, q: int = 90, **kw):
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p, "WEBP", quality=q, method=6, **kw)
    rep["outputs"][str(p.relative_to(ROOT))] = {"from": src, "size": list(im.size), "sha256": sha(p), "bytes": p.stat().st_size}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", required=True, type=Path)
    ap.add_argument("--launcher", required=True, type=Path)
    a = ap.parse_args()
    ref = a.menu / "assets" / "neural-city-reference.png"
    speech = a.launcher / "4da5010f-82ae-4eac-a001-0b38717e5465.png"
    gif = a.launcher / "68d9fbfe305f950ee9f2dfc58b60cc26.gif"
    poster = a.launcher / "47e288ec-1d84-4b6c-88be-bcd096fc5058.png"
    rep = {"sources": {p.name: sha(p) for p in (ref, speech, gif, poster)}, "outputs": {}, "inpainted": {"labels": None, "panels": PANELS}}
    scene, removed = clean_scene(Image.open(ref))
    rep["inpainted"]["labels"] = removed
    save(scene, OUT / "neural-city-scene.webp", rep, ref.name, q=90)
    save(scene.resize((418, 235), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10)), OUT / "neural-city-scene-blur.webp", rep, ref.name, q=70)
    sp = Image.open(speech).convert("RGB")
    save(sp, OUT / "launcher-speech.webp", rep, speech.name, q=90)
    save(sp.resize((sp.width // 4, sp.height // 4), Image.LANCZOS).filter(ImageFilter.GaussianBlur(8)), OUT / "launcher-speech-blur.webp", rep,
         speech.name, q=70)
    save(sp.resize((960, round(960 * sp.height / sp.width)), Image.LANCZOS), DESK / "launcher-speech.webp", rep, speech.name, q=86)
    g = Image.open(gif)
    frames, durs = [], []
    for i in range(g.n_frames):
        g.seek(i)
        frames.append(g.convert("RGB"))
        durs.append(g.info.get("duration", 50))
    p = OUT / "neuron-flight.webp"
    frames[0].save(p, "WEBP", save_all=True, append_images=frames[1:], duration=durs, loop=0, quality=80, method=6)
    rep["outputs"][str(p.relative_to(ROOT))] = {"from": gif.name, "frames": len(frames), "ms": sum(durs), "sha256": sha(p), "bytes": p.stat().st_size}
    save(Image.open(poster).convert("RGB"), OUT / "neuron-poster.webp", rep, poster.name, q=85)
    (OUT / "zrodla.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in rep["outputs"].items():
        print(f"{k}: {v.get('size') or v.get('frames')} {v['bytes']} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
