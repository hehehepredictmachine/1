"""Builds the background assets of the PepeMarketWizard main menu and its three tower views (frontend/public/assets/wizard).

  python tools/wizard_assets.py --menu <tower-with-lightning image> --precision <observatory image> --dyscypline <citadel image>

Sources: the user's attachments (the tower with purple lightning is the base of the main menu; the night-sky tower and the
eye cathedral become the Precision and Dyscypline backgrounds) and one procedural image (Profits - vault, drawn by
tools/wizard_backgrounds/profits_vault.html, no external art). Portrait or small sources are composed onto a 1920x1080 canvas:
the picture itself is never stretched - it is fitted by height and the sides are filled with a blurred, darkened copy."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "assets" / "wizard"
W, H = 1920, 1080


def cover(im: Image.Image, w: int = W, h: int = H, y_focus: float = 0.5) -> Image.Image:
    s = max(w / im.width, h / im.height)
    r = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x0 = (r.width - w) // 2
    y0 = int(max(0, min(r.height - h, (r.height - h) * y_focus)))
    return r.crop((x0, y0, x0 + w, y0 + h))


def fit_height(im: Image.Image) -> Image.Image:
    """Picture fitted by height in the middle; sides = blurred, darkened copy (no distortion, nothing cut off)."""
    back = cover(im).filter(ImageFilter.GaussianBlur(28))
    back = ImageEnhance.Brightness(back).enhance(0.45)
    s = H / im.height
    fg = im.resize((round(im.width * s), H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=50, threshold=2))
    mask = Image.new("L", fg.size, 255)
    fade = max(1, fg.width // 7)
    px = mask.load()
    for x in range(fade):                                    # feathered left / right edge
        v = int(255 * x / fade)
        for y in range(fg.height):
            px[x, y] = v
            px[fg.width - 1 - x, y] = v
    back.paste(fg, ((W - fg.width) // 2, 0), mask)
    return back


def grade(im: Image.Image, mul: tuple[float, float, float], tint: tuple[int, int, int], tint_alpha: float) -> Image.Image:
    r, g, b = im.convert("RGB").split()
    im = Image.merge("RGB", (r.point(lambda v: min(255, v * mul[0])), g.point(lambda v: min(255, v * mul[1])),
                             b.point(lambda v: min(255, v * mul[2]))))
    return Image.blend(im, ImageChops.screen(im, Image.new("RGB", im.size, tint)), tint_alpha)


def save(im: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    im.convert("RGB").save(p, "WEBP", quality=84, method=6)
    print(f"{p.relative_to(ROOT)}  {im.width}x{im.height}  {p.stat().st_size // 1024} KB")


def render_vault() -> Image.Image:
    from playwright.sync_api import sync_playwright
    html = ROOT / "tools" / "wizard_backgrounds" / "profits_vault.html"
    with sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium"
        b = pw.chromium.launch(**({"executable_path": exe} if Path(exe).exists() else {}))
        p = b.new_page(viewport={"width": W, "height": H})
        p.goto(html.as_uri())
        p.wait_for_function("document.title === 'done'")
        tmp = OUT / "_vault.png"
        p.locator("#c").screenshot(path=str(tmp))
        b.close()
    im = Image.open(tmp).convert("RGB")
    tmp.unlink()
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", required=True)
    ap.add_argument("--precision", required=True)
    ap.add_argument("--dyscypline", required=True)
    a = ap.parse_args()
    menu = Image.open(a.menu).convert("RGB")                 # the tower with purple lightning (GIF delivered as one frame)
    big = menu.resize((W, round(menu.height * W / menu.width)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    save(cover(big), "menu-tower-lightning.webp")
    save(menu, "menu-tower-lightning-source.webp")           # untouched source frame (static fallback / reference)
    save(grade(fit_height(Image.open(a.precision).convert("RGB")), (0.78, 1.02, 1.12), (20, 190, 230), 0.18), "precision-observatory.webp")
    save(grade(fit_height(Image.open(a.dyscypline).convert("RGB")), (1.0, 0.96, 1.06), (40, 200, 140), 0.10), "dyscypline-citadel.webp")
    save(render_vault(), "profits-vault.webp")


if __name__ == "__main__":
    main()
