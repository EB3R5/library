"""Render the library icon: indigo rounded square, three white book spines on a shelf.

Usage: uv run --with pillow make_icon.py <output.png> [size]

Drawn at 1024px and downscaled to `size` when given (256 for the Linux
hicolor icon). library.icns and packaging/desktop/linux/library.png are both
committed, so nothing runs this at build time — it is here for when the
artwork changes.
"""
import sys

from PIL import Image, ImageDraw

S = 1024
OUT = sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png"
SIZE = int(sys.argv[2]) if len(sys.argv) > 2 else S

INDIGO = (49, 46, 101, 255)
WHITE = (255, 255, 255, 255)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

inset = int(S * 0.08)
d.rounded_rectangle([inset, inset, S - inset, S - inset],
                    radius=int(S * 0.22), fill=INDIGO)

# three spines of different heights, standing on a shelf
shelf_y = int(S * 0.72)
spine_w = int(S * 0.115)
gap = int(S * 0.045)
total = spine_w * 3 + gap * 2
x = (S - total) // 2
for height, lean in ((0.34, 0), (0.42, 0), (0.28, 0)):
    top = shelf_y - int(S * height)
    d.rounded_rectangle([x, top, x + spine_w, shelf_y],
                        radius=int(spine_w * 0.18), fill=WHITE)
    # a band across each spine, so the shapes read as books at 16px
    band = top + int((shelf_y - top) * 0.24)
    d.rectangle([x, band, x + spine_w, band + int(S * 0.022)], fill=INDIGO)
    x += spine_w + gap + lean

d.rounded_rectangle([int(S * 0.24), shelf_y + int(S * 0.03),
                     int(S * 0.76), shelf_y + int(S * 0.075)],
                    radius=int(S * 0.02), fill=WHITE)

if SIZE != S:
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
img.save(OUT)
print("wrote", OUT)
