"""Pascaline's pixel art: a chunky pop calculator icon and a pixel-font banner.

    python tools/make_art.py assets      # writes icon.svg and banner.svg
    rsvg-convert -w 256 assets/icon.svg -o assets/icon-256.png   (etc.)

Everything is drawn on a pixel grid with flat colours and black outlines,
like early-80s computer icons. No fonts needed: the letters are below.
"""

import sys
from pathlib import Path

INK = "#141414"
YELLOW = "#FFD23F"
PINK = "#FF4F8B"
CYAN = "#2EC4F1"
CREAM = "#FFF6E3"
LCD = "#B9F5C8"



def paint_icon():
    """The icon on a 32 × 32 grid: a pink pocket calculator on a yellow tile."""
    g = [[None] * 32 for _ in range(32)]

    def box(x0, y0, x1, y1, c):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                g[y][x] = c

    box(1, 2, 30, 29, YELLOW)  # the tile, corners rounded by a pixel
    box(2, 1, 29, 30, YELLOW)

    def part(x0, y0, x1, y1, c):  # the calculator, centred with its shadow
        box(x0 - 1, y0 - 1, x1 - 1, y1 - 1, c)

    part(10, 6, 26, 29, INK)  # drop shadow, two pixels down-right
    part(9, 4, 23, 27, INK)  # body outline, rounded corners
    part(8, 5, 24, 26, INK)
    part(9, 5, 23, 26, PINK)
    part(10, 6, 22, 13, INK)  # display
    part(11, 7, 21, 12, LCD)
    part(14, 8, 18, 8, INK)  # π
    part(15, 9, 15, 11, INK)
    part(17, 9, 17, 11, INK)
    for row, y in enumerate((15, 19, 23)):  # keys: three rows, each with its own shadow
        for col, x in enumerate((10, 15, 20)):
            last = col == 2
            color = YELLOW if (last and row == 2) else CYAN if last else CREAM
            part(x, y, x + 2, y + 1, color)
            part(x, y + 2, x + 2, y + 2, INK)
    return g


# A 5 × 7 pixel font, just the letters we need.
FONT = {
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    " ": ["00000"] * 7,
}


def rects(cells, scale, x0=0, y0=0):
    """Pixels as SVG rects, merging horizontal runs of one colour."""
    out = []
    for y, row in enumerate(cells):
        x = 0
        while x < len(row):
            c = row[x]
            run = 1
            while x + run < len(row) and row[x + run] == c:
                run += 1
            if c:
                out.append(f'<rect x="{x0 + x * scale}" y="{y0 + y * scale}" width="{run * scale}" '
                           f'height="{scale}" fill="{c}"/>')
            x += run
    return "\n  ".join(out)


def icon_cells():
    return paint_icon()


def text_cells(text, color):
    rows = [[] for _ in range(7)]
    for k, ch in enumerate(text):
        for y in range(7):
            if k:
                rows[y].append(None)  # one pixel between letters
            rows[y].extend(color if b == "1" else None for b in FONT[ch][y])
    return rows


def svg(w, h, body, bg=None):
    back = f'<rect width="{w}" height="{h}" fill="{bg}"/>\n  ' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'shape-rendering="crispEdges">\n  {back}{body}\n</svg>\n')


def icon():
    return svg(32, 32, rects(icon_cells(), 1))


def banner():
    w, h = 1280, 320
    calc_scale = 8  # the icon at 256 px, without its yellow tile
    cells = icon_cells()
    for y in range(32):  # drop the tile, keep the calculator (its "=" key is yellow too)
        for x in range(32):
            if cells[y][x] == YELLOW and not (22 <= y <= 23 and 19 <= x <= 21):  # the = key
                cells[y][x] = None
    title = "PASCALINE"
    tag = "NOTEBOOK CALCULATOR - 1642"
    ts, gs = 12, 4  # title and tagline pixel sizes
    title_w = (len(title) * 6 - 1) * ts
    tag_w = (len(tag) * 6 - 1) * gs
    total = 32 * calc_scale - 7 * calc_scale + 56 + title_w  # icon art is ~25 px wide
    x0 = (w - total) // 2
    calc_x, calc_y = x0 - 8 * calc_scale, (h - 32 * calc_scale) // 2
    tx = x0 + 25 * calc_scale + 56
    ty = h // 2 - 7 * ts + 10
    body = "\n  ".join([
        rects(cells, calc_scale, calc_x, calc_y),
        rects(text_cells(title, INK), ts, tx + ts // 2, ty + ts // 2),  # pop shadow
        rects(text_cells(title, PINK), ts, tx, ty),
        rects(text_cells(tag, INK), gs, tx + (title_w - tag_w) // 2, ty + 7 * ts + 36),
    ])
    return svg(w, h, body, bg=YELLOW)


out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets")
out.mkdir(parents=True, exist_ok=True)
(out / "icon.svg").write_text(icon())
(out / "banner.svg").write_text(banner())
print("ok")
