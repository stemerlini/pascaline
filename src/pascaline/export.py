"""Save a sheet as Markdown or as a Jupyter notebook that reruns in plain SymPy."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import sympy as sp

from . import store, units
from .engine import ASSIGN_RE, FUNCDEF_RE, Result, _split_top, _top_level_eq, normalize
from .units import split_target

# Rows the plain-text sketches get in exports.
PLOT_WIDTH, PLOT_ROWS = 72, 16


def default_path(sheet: str, ext: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return store.EXPORTS / f"{sheet}-{stamp}.{ext}"


def output_text(res: Result) -> str:
    if res.kind == "plot":
        from .plot import render

        return render(res.plot, PLOT_WIDTH, PLOT_ROWS, ["default"], "default").plain
    lines = res.text.split("\n")
    if res.approx:
        lines += [f"≈ {a}" for a in res.approx.split("\n")]
    return "\n".join(lines)


def to_markdown(sheet: str, cells: list[tuple[int, str, Result]]) -> str:
    out = [f"# {sheet}", "", f"*Pascaline sheet, {dt.date.today().isoformat()}*", ""]
    for n, src, res in cells:
        out += [f"**[{n}]** `{src}`", "", "```", output_text(res), "```", ""]
        if res.latex and res.kind != "error":
            out += ["$$", res.latex, "$$", ""]
    return "\n".join(out)


SETUP = '''\
from sympy import *
from sympy.parsing.sympy_parser import (parse_expr, standard_transformations,
    convert_xor, implicit_multiplication, implicit_application)
from sympy.physics import units as u
init_printing()

T = standard_transformations + (convert_xor, implicit_multiplication, implicit_application)

UNITS = {k: v for k, v in vars(u).items() if isinstance(v, u.Quantity) and k not in ("N", "S")}
UNITS.update({__EXTRA__})

def calc(s, units=False):
    """Read Pascaline-style input (2x, x^2, sin x) with this notebook's variables.
    units=True also reads unit names (km, h, m, s…), as Pascaline does for such lines."""
    names = {**(UNITS if units else {}), "e": E, "i": I, "ln": log}
    names.update({k: v for k, v in globals().items() if not k.startswith("_") or k[1:].isdigit()})
    return parse_expr(s, local_dict=names, transformations=T)'''


def _setup() -> str:
    extra = {**{n: units.python(sc) for n, sc in units.SCALES.items()},
             **{n: units.python(sp.sympify(q)) for n, (q, _) in units.CONSTANTS.items()}}
    return SETUP.replace("__EXTRA__", ", ".join(f"{json.dumps(k)}: {v}" for k, v in extra.items()))


def to_python(n: int, src: str, res: Result) -> str:
    """The cell as Python for a notebook; keeps Pascaline's syntax inside calc("...")."""
    s = normalize(src)
    q = json.dumps  # a safe Python string literal
    if res.kind == "error":
        return f"# [{n}] {src}\n# error in Pascaline: {res.text}"
    if res.kind == "assign" and (m := FUNCDEF_RE.match(s)):
        params = ", ".join(p.strip() for p in m.group(2).split(","))
        return f'{m.group(1)} = Lambda(symbols({q(params)}), calc({q(m.group(3).strip())}))\n{m.group(1)}'
    if res.kind == "assign" and (m := ASSIGN_RE.match(s)):
        return f"{m.group(1)} = _{n} = {_expr(m.group(2).strip(), res)}\n{m.group(1)}"
    if res.kind == "solve":
        eqs = []
        for part in _split_top(s, ","):
            i = _top_level_eq(part)[0]
            eqs.append(f"Eq(calc({q(part[:i].strip())}), calc({q(part[i + 1 :].strip())}))")
        return f"_{n} = solve([{', '.join(eqs)}], dict=True)\n_{n}"
    if res.kind == "plot":
        p = res.plot
        exprs = ", ".join(f"calc({q(sp.sstr(e))})" for e in p.exprs)
        return f"plot({exprs}, (Symbol({q(str(p.var))}), {p.lo!r}, {p.hi!r}))"
    return f"_{n} = ans = {_expr(s, res)}\n_{n}"


def _expr(s: str, res: Result) -> str:
    body, target = split_target(s)
    q = json.dumps
    with_units = ", units=True" if target is not None or units.has_units(res.value) else ""
    if target is None:
        return f"calc({q(body)}{with_units})"
    return f"u.convert_to(calc({q(body)}{with_units}), calc({q(target)}{with_units}))"


def to_notebook(sheet: str, cells: list[tuple[int, str, Result]]) -> str:
    def code(source: str, count: int | None = None, text: str | None = None) -> dict:
        outputs = []
        if text:
            outputs.append({"output_type": "execute_result", "execution_count": count, "metadata": {},
                            "data": {"text/plain": text.splitlines(keepends=True)}})
        return {"cell_type": "code", "execution_count": count, "metadata": {}, "outputs": outputs,
                "source": source.splitlines(keepends=True)}

    nb_cells = [
        {"cell_type": "markdown", "metadata": {},
         "source": [f"# {sheet}\n", "\n", f"Exported from Pascaline on {dt.date.today().isoformat()}. ",
                    "Units in conversions need `u.` names (e.g. `u.km`) when rerun here."]},
        code(_setup()),
    ]
    for n, src, res in cells:
        nb_cells.append({"cell_type": "markdown", "metadata": {}, "source": [f"**[{n}]** `{src}`"]})
        nb_cells.append(code(to_python(n, src, res), n, output_text(res) if res.kind != "error" else None))
    notebook = {
        "cells": nb_cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1, ensure_ascii=False)


def write(path: Path, text: str) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
