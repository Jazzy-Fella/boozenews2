#!/usr/bin/env python3
"""Generate PWA icons from the pixel art beer mug."""
from PIL import Image, ImageDraw

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# SVG rects from index.html: (x, y, w, h, color) in 5px-grid coords (viewBox 0 0 70 50)
RECTS = [
    (10, 0,  35, 5,  '#ffffff'),
    (5,  5,  40, 5,  '#ffffff'),
    (0,  10, 45, 5,  '#ffffff'),
    (5,  15, 5,  5,  '#cc8800'),
    (10, 15, 30, 5,  '#ff9900'),
    (40, 15, 5,  5,  '#cc8800'),
    (5,  20, 5,  5,  '#cc8800'),
    (10, 20, 5,  5,  '#aa6600'),
    (15, 20, 10, 5,  '#ff9900'),
    (25, 20, 5,  5,  '#aa6600'),
    (30, 20, 10, 5,  '#ff9900'),
    (40, 20, 5,  5,  '#cc8800'),
    (45, 20, 10, 5,  '#cc8800'),
    (5,  25, 5,  5,  '#cc8800'),
    (10, 25, 5,  5,  '#aa6600'),
    (15, 25, 10, 5,  '#ff9900'),
    (25, 25, 5,  5,  '#aa6600'),
    (30, 25, 10, 5,  '#ff9900'),
    (40, 25, 5,  5,  '#cc8800'),
    (55, 25, 5,  5,  '#cc8800'),
    (5,  30, 5,  5,  '#cc8800'),
    (10, 30, 5,  5,  '#aa6600'),
    (15, 30, 10, 5,  '#ff9900'),
    (25, 30, 5,  5,  '#aa6600'),
    (30, 30, 10, 5,  '#ff9900'),
    (40, 30, 5,  5,  '#cc8800'),
    (55, 30, 5,  5,  '#cc8800'),
    (5,  35, 5,  5,  '#cc8800'),
    (10, 35, 5,  5,  '#aa6600'),
    (15, 35, 10, 5,  '#ff9900'),
    (25, 35, 5,  5,  '#aa6600'),
    (30, 35, 10, 5,  '#ff9900'),
    (40, 35, 5,  5,  '#cc8800'),
    (45, 35, 10, 5,  '#cc8800'),
    (5,  40, 5,  5,  '#cc8800'),
    (10, 40, 30, 5,  '#ee8800'),
    (40, 40, 5,  5,  '#cc8800'),
    (5,  45, 40, 5,  '#cc8800'),
]

SRC_W, SRC_H = 70, 50

def make_icon(size):
    img = Image.new('RGB', (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    padding = size * 0.12
    avail = size - padding * 2
    scale = min(avail / SRC_W, avail / SRC_H)
    scaled_w = SRC_W * scale
    scaled_h = SRC_H * scale
    ox = (size - scaled_w) / 2 + size * 0.06
    oy = (size - scaled_h) / 2
    for x, y, w, h, color in RECTS:
        x1 = int(ox + x * scale)
        y1 = int(oy + y * scale)
        x2 = int(ox + (x + w) * scale)
        y2 = int(oy + (y + h) * scale)
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=hex_to_rgb(color))
    return img

import os
out = os.path.dirname(os.path.abspath(__file__))
make_icon(192).save(os.path.join(out, 'icon-192.png'))
make_icon(512).save(os.path.join(out, 'icon-512.png'))
make_icon(180).save(os.path.join(out, 'apple-touch-icon.png'))
print("Icons generated: icon-192.png, icon-512.png, apple-touch-icon.png")
