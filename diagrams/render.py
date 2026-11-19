#!/usr/bin/env python3
"""Render diagram HTML to trimmed 2x PNGs. Usage: python3 diagrams/render.py"""
import subprocess, pathlib, tempfile
from PIL import Image, ImageChops

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "img"
OUT.mkdir(exist_ok=True)
W, H, SCALE = 900, 3000, 2


def render(src: pathlib.Path, name: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        shot = pathlib.Path(td) / f"{name}.png"
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={W},{H}", f"--force-device-scale-factor={SCALE}",
             f"--screenshot={shot}", "--virtual-time-budget=3000", src.as_uri()],
            check=True, capture_output=True)
        im = Image.open(shot).convert("RGB")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        box = ImageChops.difference(im, bg).getbbox()
        if box:
            pad = 6
            im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                          min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
        dest = OUT / f"{name}.png"
        gray = im.convert("L").convert("RGB")
        if ImageChops.difference(im, gray).getbbox() is None:
            im = im.convert("L")
        im.save(dest, optimize=True)
        print(f"{dest.name}  {im.width}x{im.height}")


if __name__ == "__main__":
    for html in sorted((ROOT / "diagrams").glob("*.html")):
        render(html, html.stem)
