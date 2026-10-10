"""Braille sketches: each terminal cell is a 2x4 dot grid."""

from __future__ import annotations

import math
from fractions import Fraction

import sympy as sp
from rich.text import Text

from .engine import Plot, fmt_number

# Dot bit for (column, row) inside a braille cell.
BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))


def sample(plot: Plot, n: int) -> list[list[float]]:
    xs = [plot.lo + (plot.hi - plot.lo) * k / (n - 1) for k in range(n)]
    series = []
    for expr in plot.exprs:
        f = sp.lambdify(plot.var, expr, modules=["math", "mpmath", "sympy"])
        ys = []
        for x in xs:
            try:
                y = complex(f(x))
                ys.append(y.real if abs(y.imag) < 1e-9 else math.nan)
            except Exception:
                ys.append(math.nan)
        series.append([y if math.isfinite(y) else math.nan for y in ys])
    return series


def y_range(series: list[list[float]]) -> tuple[float, float]:
    ys = sorted(y for s in series for y in s if not math.isnan(y))
    if not ys:
        return -1.0, 1.0
    lo, hi = ys[0], ys[-1]
    # Asymptotes (tan, 1/x) would flatten everything else: trim the extremes.
    if len(ys) > 20:
        q_lo, q_hi = ys[len(ys) // 10], ys[-1 - len(ys) // 10]
        spread = q_hi - q_lo
        if (hi - lo) > 10 * spread > 0:
            lo, hi = max(lo, q_lo - spread), min(hi, q_hi + spread)
    if hi - lo < 1e-12:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.05
    return lo - pad, hi + pad


GUTTER = 9  # columns for the y labels and the axis


def nice_step(span: float, count: int) -> float:
    """A 1, 2 or 5 × 10^k step that cuts span into about count pieces."""
    raw = span / max(1, count)
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw * 0.999)


def ticks(lo: float, hi: float, count: int) -> list[tuple[float, str]]:
    """Round values between lo and hi with their labels; in multiples of π when the
    range itself is a multiple of π/2 (sin x from -π to π reads -π, -π/2, 0, …)."""
    pi_mode = all(abs(v / (math.pi / 2) - round(v / (math.pi / 2))) < 1e-9 for v in (lo, hi)) and hi - lo > 1
    unit = math.pi if pi_mode else 1.0
    step = nice_step((hi - lo) / unit, count)
    if pi_mode:
        step = min((s for s in (0.25, 0.5, 1, 2, 5, 10, 20) if s >= step), default=step)
    out = []
    for k in range(math.ceil(lo / unit / step - 1e-9), math.floor(hi / unit / step + 1e-9) + 1):
        v = k * step
        if pi_mode:
            f = Fraction(v).limit_denominator(4)
            num = "" if abs(f.numerator) == 1 else str(abs(f.numerator))
            den = f"/{f.denominator}" if f.denominator > 1 else ""
            label = "0" if f == 0 else ("-" if f < 0 else "") + num + "π" + den
        else:
            label = fmt_number(round(v, 12), 6)
        out.append((v * unit, label))
    return out


def render(plot: Plot, width: int, height: int, colors: list[str], axis_style: str) -> Text:
    gutter = GUTTER
    w = max(10, width - gutter)
    px_w, px_h = w * 2, height * 4
    series = sample(plot, px_w)
    lo, hi = y_range(series)

    def row_of(y: float) -> float:
        return (hi - y) / (hi - lo) * (px_h - 1)

    grid = [[0] * w for _ in range(height)]
    owner = [[-1] * w for _ in range(height)]
    axes = [[0] * w for _ in range(height)]

    def dot(target, px: int, py: int, who: int = -1) -> None:
        if 0 <= px < px_w and 0 <= py < px_h:
            cx, cy = px // 2, py // 4
            target[cy][cx] |= BITS[px % 2][py % 4]
            if who >= 0:
                owner[cy][cx] = who

    if lo < 0 < hi:
        r = round(row_of(0))
        for px in range(0, px_w, 2):
            dot(axes, px, r)
    if plot.lo < 0 < plot.hi:
        c = round((0 - plot.lo) / (plot.hi - plot.lo) * (px_w - 1))
        for py in range(0, px_h, 2):
            dot(axes, c, py)

    for k, ys in enumerate(series):
        prev = None
        for px, y in enumerate(ys):
            if math.isnan(y):
                prev = None
                continue
            r = row_of(y)
            if prev is not None and abs(r - prev) < px_h * 1.5:  # join, but not across asymptotes
                a, b = sorted((round(prev), round(r)))
                for py in range(max(a, -1), min(b, px_h) + 1):
                    dot(grid, px, py, k)
            else:
                dot(grid, px, round(r), k)
            prev = r

    labels: dict[int, str] = {}
    for v, label in ticks(lo, hi, max(2, height // 3)):
        cy = round(row_of(v)) // 4
        if 0 <= cy < height and len(label) <= gutter - 2:
            labels.setdefault(cy, label)
    out = Text()
    for cy in range(height):
        out.append(f"{labels.get(cy, ''):>{gutter - 2}} ┤" if cy in labels else " " * (gutter - 1) + "│",
                   style=axis_style)
        for cx in range(w):
            bits = grid[cy][cx]
            if bits:
                out.append(chr(0x2800 + (bits | axes[cy][cx])), style=colors[owner[cy][cx] % len(colors)])
            elif axes[cy][cx]:
                out.append(chr(0x2800 + axes[cy][cx]), style=axis_style)
            else:
                out.append(" ")
        out.append("\n")
    axis, under = ["─"] * w, [" "] * (w + gutter)
    free_from = 0  # first column of `under` a new label may use
    for v, label in ticks(plot.lo, plot.hi, max(2, w // 10)):
        cx = round((v - plot.lo) / (plot.hi - plot.lo) * (px_w - 1)) // 2
        if not 0 <= cx < w:
            continue
        axis[cx] = "┬"
        start = max(0, gutter + cx - len(label) // 2)
        if start >= free_from and start + len(label) <= len(under):
            under[start : start + len(label)] = label
            free_from = start + len(label) + 1
    out.append(" " * (gutter - 1) + "└" + "".join(axis) + "\n", style=axis_style)
    out.append("".join(under).rstrip() + "\n", style=axis_style)
    legend = Text(" " * gutter)
    for k, expr in enumerate(plot.exprs):
        legend.append("━ ", style=colors[k % len(colors)])
        legend.append(sp.sstr(expr).replace("**", "^") + "   ", style=axis_style)
    out.append_text(legend)
    return out
