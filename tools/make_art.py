"""Generate Pascaline's 80s icon and banner as self-contained SVGs (text as paths)."""

import math
import random
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

# Needs fonttools and the Orbitron variable font (SIL OFL), e.g.
#   curl -LO "https://github.com/google/fonts/raw/main/ofl/orbitron/Orbitron%5Bwght%5D.ttf"
#   python tools/make_art.py assets Orbitron[wght].ttf
# then render PNGs with rsvg-convert.
FONT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "orbitron.ttf"
OUT = Path(sys.argv[1])
FONTS = {w: instancer.instantiateVariableFont(TTFont(FONT), {"wght": w}) for w in (900, 600)}


def text_path(text, weight, size, x, y, spacing=0.0, anchor="middle", skew=0.0):
    """Text outlined as one SVG path; x/y is the baseline anchor."""
    font = FONTS[weight]
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    scale = size / font["head"].unitsPerEm
    names = [cmap[ord(ch)] for ch in text]
    advance = sum(hmtx[n][0] for n in names) * scale + spacing * (len(names) - 1)
    start = {"middle": x - advance / 2, "start": x, "end": x - advance}[anchor]
    pen = SVGPathPen(gs)
    cursor = start
    for n in names:
        # flip y (font units go up), skew for italics, place at cursor
        t = (scale, 0, -scale * skew, -scale, cursor, y)
        gs[n].draw(TransformPen(pen, t))
        cursor += hmtx[n][0] * scale + spacing
    return pen.getCommands(), advance


def defs(w, h, horizon):
    return f"""
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#07021a"/>
      <stop offset="0.55" stop-color="#26094a"/>
      <stop offset="0.85" stop-color="#7a1468"/>
      <stop offset="1" stop-color="#ff3d7f"/>
    </linearGradient>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1c0533"/>
      <stop offset="1" stop-color="#05010e"/>
    </linearGradient>
    <linearGradient id="sun" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff27a"/>
      <stop offset="0.45" stop-color="#ffa53a"/>
      <stop offset="0.8" stop-color="#ff3d7f"/>
      <stop offset="1" stop-color="#d4148f"/>
    </linearGradient>
    <linearGradient id="chrome" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f4fbff"/>
      <stop offset="0.38" stop-color="#7fd6ff"/>
      <stop offset="0.5" stop-color="#ffffff"/>
      <stop offset="0.53" stop-color="#2a1050"/>
      <stop offset="0.75" stop-color="#b03ab8"/>
      <stop offset="1" stop-color="#ffb3ec"/>
    </linearGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff" stop-opacity="0.15"/>
      <stop offset="1" stop-color="#fff" stop-opacity="1"/>
    </linearGradient>
    <mask id="gridfade"><rect x="0" y="{horizon}" width="{w}" height="{h - horizon}" fill="url(#fade)"/></mask>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="{max(2, w / 260):.1f}" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="bigglow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="{max(6, w / 90):.1f}"/>
    </filter>
  </defs>"""


def stars(w, h, n, seed=7):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.choice([0.6, 0.8, 1.0, 1.4]) * max(1, w / 900)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" fill="#fff" opacity="{rnd.uniform(0.3, 0.9):.2f}"/>')
    return "\n    ".join(out)


def sun(cx, cy, r, horizon, sid):
    """The striped synthwave sun, cut off at the horizon."""
    stripes = []
    top = cy + r * 0.05
    k = 0
    y = top
    while y < cy + r:
        gap = r * (0.025 + 0.018 * k)
        stripes.append(f'<rect x="{cx - r}" y="{y:.1f}" width="{2 * r}" height="{gap:.1f}" fill="#000"/>')
        y += gap + r * (0.16 - 0.018 * k)
        k += 1
    return f"""
  <mask id="{sid}">
    <rect x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" fill="#fff"/>
    {''.join(stripes)}
    <rect x="{cx - r}" y="{horizon}" width="{2 * r}" height="{2 * r}" fill="#000"/>
  </mask>
  <circle cx="{cx}" cy="{cy}" r="{r * 1.08}" fill="#ff3d7f" opacity="0.35" filter="url(#bigglow)"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#sun)" mask="url(#{sid})"/>"""


def grid(w, h, horizon, vx, rows, cols, stroke):
    lines = []
    depth = h - horizon
    for i in range(1, rows + 1):  # horizontal lines bunch up toward the horizon
        y = horizon + depth * (i / rows) ** 2.2
        lines.append(f'<line x1="0" y1="{y:.1f}" x2="{w}" y2="{y:.1f}"/>')
    spread = w * 2.6
    for j in range(-cols, cols + 1):  # vertical lines run to the vanishing point
        x = vx + spread * j / (2 * cols)
        lines.append(f'<line x1="{vx + (x - vx) * 0.04:.1f}" y1="{horizon}" x2="{x:.1f}" y2="{h}"/>')
    return f"""
  <g stroke="#ff2bd6" stroke-width="{stroke}" mask="url(#gridfade)" filter="url(#glow)">
    {''.join(lines)}
  </g>
  <line x1="0" y1="{horizon}" x2="{w}" y2="{horizon}" stroke="#ff7ae6" stroke-width="{stroke * 1.6}" filter="url(#glow)"/>"""


def sine(x0, x1, y, amp, periods, stroke, color="#2de2ff"):
    pts = []
    n = 160
    for k in range(n + 1):
        t = k / n
        x = x0 + (x1 - x0) * t
        pts.append(f"{x:.1f},{y - amp * math.sin(2 * math.pi * periods * t):.1f}")
    d = "M" + " L".join(pts)
    return f"""
  <path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke * 2.6}" opacity="0.5" filter="url(#bigglow)"/>
  <path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" filter="url(#glow)"/>
  <path d="{d}" fill="none" stroke="#e8fdff" stroke-width="{stroke * 0.35}" stroke-linecap="round"/>"""


def icon():
    w = h = 512
    horizon = 330
    body = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  {defs(w, h, horizon)}
  <clipPath id="round"><rect x="16" y="16" width="480" height="480" rx="104"/></clipPath>
  <g clip-path="url(#round)">
    <rect width="{w}" height="{horizon}" fill="url(#sky)"/>
    {stars(w, horizon - 60, 40)}
    {sun(256, 228, 132, horizon, "sunmask")}
    <rect y="{horizon}" width="{w}" height="{h - horizon}" fill="url(#ground)"/>
    {grid(w, h, horizon, 256, 7, 7, 3)}
    {sine(40, 472, 214, 62, 1.25, 9)}
  </g>
  <rect x="17.5" y="17.5" width="477" height="477" rx="103" fill="none" stroke="#ff7ae6" stroke-width="3" opacity="0.7"/>
</svg>
"""
    return body


def banner():
    w, h = 1280, 400
    horizon = 290
    title, tw = text_path("PASCALINE", 900, 118, w / 2, 214, spacing=10, skew=0.18)
    sub, _ = text_path("NOTEBOOK CALCULATOR  -  EST. 1642", 600, 21, w / 2, 262, spacing=7)
    body = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  {defs(w, h, horizon)}
  <rect width="{w}" height="{horizon}" fill="url(#sky)"/>
  {stars(w, horizon - 40, 140, seed=3)}
  {sun(w / 2, 190, 150, horizon, "sunmask")}
  <rect y="{horizon}" width="{w}" height="{h - horizon}" fill="url(#ground)"/>
  {grid(w, h, horizon, w / 2, 9, 14, 2.4)}
  {sine(70, w - 70, 150, 48, 3.5, 4.5)}
  <path d="{title}" fill="#ff2bd6" opacity="0.9" filter="url(#bigglow)"/>
  <path d="{title}" fill="#1a0533" transform="translate(5 6)"/>
  <path d="{title}" fill="url(#chrome)" stroke="#ffffff" stroke-width="1.6" stroke-linejoin="round"/>
  <path d="{sub}" fill="#2de2ff" filter="url(#glow)"/>
</svg>
"""
    return body


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "icon.svg").write_text(icon())
(OUT / "banner.svg").write_text(banner())
print("ok")
