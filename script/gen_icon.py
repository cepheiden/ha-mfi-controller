#!/usr/bin/env python3
"""Render the integration icon (power strip with three outlets) -> brand/icon.png, icon@2x.png."""
import pathlib

from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "mfi_controller" / "brand"


def render(size: int) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # strip body
    d.rounded_rectangle([20 * s, 70 * s, 236 * s, 186 * s], radius=34 * s, fill=(0, 111, 255, 255))
    # outlets (EU style: circle with two holes)
    for cx in (68, 128, 188):
        d.ellipse([(cx - 25) * s, 103 * s, (cx + 25) * s, 153 * s], fill=(255, 255, 255, 255))
        for dx in (-9, 9):
            d.ellipse([(cx + dx - 5) * s, 123 * s, (cx + dx + 5) * s, 133 * s], fill=(0, 111, 255, 255))
    # signal arcs (push / inform)
    for r, w in ((30, 9), (50, 9)):
        d.arc([(128 - r) * s, (62 - r) * s, (128 + r) * s, (62 + r) * s], start=225, end=315, fill=(0, 111, 255, 255), width=int(w * s))
    d.ellipse([122 * s, 50 * s, 134 * s, 62 * s], fill=(0, 111, 255, 255))
    return img


OUT.mkdir(parents=True, exist_ok=True)
render(256).save(OUT / "icon.png", optimize=True)
render(512).save(OUT / "icon@2x.png", optimize=True)
print("written", sorted(p.name for p in OUT.iterdir()))
