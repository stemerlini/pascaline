"""Units and physical constants: `5 km/h to m/s`, `c0 * 3 s`, `2 kWh to J`.

Single letters (m, s, g, h, c) are everyday variable names, so units only switch
on for an expression that clearly means them: a ` to ` conversion, a named
constant, or an unmistakable unit such as km, kg or hour. Then every unit name
counts, except your own variables.
"""

from __future__ import annotations

import re

import sympy as sp
from sympy.physics import units as U
from sympy.physics.units import Quantity, convert_to
from sympy.physics.units.definitions import dimension_definitions as D
from sympy.physics.units.systems.si import SI

SCALES: dict[str, object] = {}  # how the extra units are defined, for notebook export


def _unit(name: str, dimension, scale) -> Quantity:
    SCALES[name] = scale
    q = Quantity(name, abbrev=name)
    SI.set_quantity_dimension(q, dimension)
    SI.set_quantity_scale_factor(q, scale)
    return q


# Everyday units SymPy doesn't have.
EXTRA = {
    "kWh": _unit("kWh", D.energy, 3_600_000 * U.joule),
    "Wh": _unit("Wh", D.energy, 3600 * U.joule),
    "kJ": _unit("kJ", D.energy, 1000 * U.joule),
    "MJ": _unit("MJ", D.energy, 10**6 * U.joule),
    "cal": _unit("cal", D.energy, sp.Rational(4184, 1000) * U.joule),
    "kcal": _unit("kcal", D.energy, 4184 * U.joule),
    "kW": _unit("kW", D.power, 1000 * U.watt),
    "MW": _unit("MW", D.power, 10**6 * U.watt),
    "mW": _unit("mW", D.power, sp.Rational(1, 1000) * U.watt),
    "kN": _unit("kN", D.force, 1000 * U.newton),
    "MPa": _unit("MPa", D.pressure, 10**6 * U.pascal),
    "GPa": _unit("GPa", D.pressure, 10**9 * U.pascal),
    "kHz": _unit("kHz", D.frequency, 1000 * U.hertz),
    "MHz": _unit("MHz", D.frequency, 10**6 * U.hertz),
    "GHz": _unit("GHz", D.frequency, 10**9 * U.hertz),
    "THz": _unit("THz", D.frequency, 10**12 * U.hertz),
    "GW": _unit("GW", D.power, 10**9 * U.watt),
    "TW": _unit("TW", D.power, 10**12 * U.watt),
    "GJ": _unit("GJ", D.energy, 10**9 * U.joule),
    "TWh": _unit("TWh", D.energy, 36 * 10**14 * U.joule),
    "GWh": _unit("GWh", D.energy, 36 * 10**11 * U.joule),
    "MWh": _unit("MWh", D.energy, 36 * 10**8 * U.joule),
    "kV": _unit("kV", D.voltage, 1000 * U.volt),
    "mV": _unit("mV", D.voltage, sp.Rational(1, 1000) * U.volt),
    "mA": _unit("mA", D.current, sp.Rational(1, 1000) * U.ampere),
    "mph": _unit("mph", D.velocity, U.mile / U.hour),
    "kmh": _unit("kmh", D.velocity, U.kilometer / U.hour),
    "knot": _unit("knot", D.velocity, U.nautical_mile / U.hour),
    "lbf": _unit("lbf", D.force, sp.Rational(4448222, 10**6) * U.newton),
    "gal": _unit("gal", D.volume, sp.Rational(3785411784, 10**12) * U.meter**3),
}

# Physical constants under names that can't be mistaken for variables.
CONSTANTS: dict[str, tuple[object, str]] = {
    "c0": (U.speed_of_light, "speed of light"),
    "g0": (U.acceleration_due_to_gravity, "standard gravity"),
    "G_N": (U.gravitational_constant, "Newton's gravitational constant"),
    "h_P": (U.planck, "Planck constant"),
    "hbar": (U.hbar, "reduced Planck constant"),
    "k_B": (U.boltzmann_constant, "Boltzmann constant"),
    "N_A": (U.avogadro_constant, "Avogadro constant"),
    "q_e": (U.elementary_charge, "elementary charge"),
    "m_e": (U.electron_rest_mass, "electron mass"),
    "m_p": (sp.Float("1.67262192369e-27") * U.kilogram, "proton mass"),
    "eps0": (U.vacuum_permittivity, "vacuum permittivity"),
    "mu0": (U.vacuum_permeability, "vacuum permeability"),
    "R_gas": (U.molar_gas_constant, "molar gas constant"),
    "sigma_SB": (U.stefan_boltzmann_constant, "Stefan–Boltzmann constant"),
    "F_c": (U.faraday_constant, "Faraday constant"),
}

# SymPy names that stay what they are (functions or symbols), never units.
_NOT_UNITS = {"N", "S", "deg", "degree", "degrees", "rad", "radian", "radians", "E", "percent", "percents"}
UNITS: dict[str, Quantity] = {
    n: q for n, q in vars(U).items() if isinstance(q, Quantity) and n not in _NOT_UNITS
}
UNITS.update(EXTRA)

# Names that only ever mean a unit; seeing one switches units on.
_AMBIGUOUS = {
    "A", "C", "D", "F", "G", "H", "J", "K", "L", "R", "T", "V", "W", "c", "g", "h", "l", "m", "s", "t", "v",
    "me", "pm", "ms", "ns", "ps", "us", "um", "mi", "mil", "au", "ha", "cl", "dl", "ml", "dm", "pa", "cd",
    "gee", "mho", "ug", "lx", "ly", "wb", "hz", "bit", "day", "mg", "nm", "gray", "u0", "e0", "Z0",
}
TRIGGERS = (set(UNITS) - _AMBIGUOUS) | set(CONSTANTS)

TO_RE = re.compile(r"\s+to\s+")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DISPLAY = {"hour": "h", "minute": "min", "second": "s", "meter": "m"}
SI_BASE = [U.meter, U.kilogram, U.second, U.ampere, U.kelvin, U.mole, U.candela]
DERIVED = [U.newton, U.joule, U.watt, U.pascal, U.volt, U.coulomb, U.ohm, U.farad, U.tesla, U.weber, U.henry]


def split_target(src: str) -> tuple[str, str | None]:
    """'5 km/h to m/s' → ('5 km/h', 'm/s') when ' to ' sits outside brackets."""
    depth = 0
    for i, ch in enumerate(src):
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if depth == 0 and ch == " ":
            m = TO_RE.match(src, i)
            if m:
                return src[:i].strip(), src[m.end() :].strip()
    return src, None


def bindings(src: str, taken: set[str], explicit: bool) -> dict:
    """Unit and constant names to bind for this input, or {} when units are off."""
    names = set(IDENT_RE.findall(src)) - taken
    if not (explicit or names & TRIGGERS):
        return {}
    out = {n: UNITS[n] for n in names if n in UNITS}
    out.update({n: CONSTANTS[n][0] for n in names if n in CONSTANTS})
    return out


def has_units(value) -> bool:
    return isinstance(value, sp.Basic) and value.has(Quantity)


def convert(value, target=None, src: str = "", skip: frozenset = frozenset()):
    """Express value in target units, or in the clearest units we can find."""
    if target is not None:
        out = convert_to(value, target)
        if _units_of(out) - target.atoms(Quantity):
            raise ValueError(f"can't convert {show(_unit_part(value))} to {show(target)}: different dimensions")
        return out
    # The first unit you typed, if everything fits it: 3 km + 200 m → 3.2 km.
    for name in IDENT_RE.findall(src):
        q = None if name in skip else UNITS.get(name)
        if q is not None:
            out = convert_to(value, q)
            if _units_of(out) <= {q}:
                return out
            break
    out = convert_to(value, SI_BASE)
    for unit in DERIVED:  # kg·m²/s² reads better as J
        named = convert_to(out, unit)
        if _units_of(named) == {unit}:
            return named
    return out


def python(expr) -> str:
    """SymPy expression with units as Python on `u` (sympy.physics.units)."""
    sub = {q: sp.Symbol(f"u.{q.name}") for q in expr.atoms(Quantity)}
    return sp.sstr(expr.xreplace(sub))


def _units_of(value) -> set:
    return set(value.atoms(Quantity)) if isinstance(value, sp.Basic) else set()


def _unit_part(value):
    return sp.Mul(*[f for f in sp.Mul.make_args(value) if f.has(Quantity)])


def split(value) -> tuple[object, object]:
    """(number, units) for a product like 25/18 * meter/second."""
    num = sp.Mul(*[f for f in sp.Mul.make_args(value) if not f.has(Quantity)])
    return num, _unit_part(value)


def show(units) -> str:
    """meter/second → 'm/s', kilogram*meter**2/second**2 → 'kg·m²/s²'."""
    sub = {q: sp.Symbol(DISPLAY.get(q.name.name if hasattr(q.name, "name") else str(q.name), str(q.abbrev)))
           for q in units.atoms(Quantity)}
    text = sp.sstr(units.xreplace(sub))
    text = re.sub(r"\*\*(\d+)", lambda m: m.group(1).translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")), text)
    text = re.sub(r"\*\*\((-?\d+)\)", lambda m: m.group(1).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")),
                  text)
    return text.replace("*", "·")
