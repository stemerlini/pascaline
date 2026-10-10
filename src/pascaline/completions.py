"""What the autocomplete menu offers: names, signatures and one-line help."""

from __future__ import annotations

from dataclasses import dataclass

import sympy as sp

from .engine import _SYMPY_NAMES, ALIASES, FUNCTIONS


@dataclass(frozen=True)
class Item:
    name: str
    signature: str  # what follows the name, e.g. "(x)"; empty for constants
    help: str
    kind: str  # func | const | var

    @property
    def callable(self) -> bool:
        return self.kind == "func"


# The everyday ones, in the order they rank among equal prefix matches.
CATALOG: list[tuple[str, str, str]] = [
    ("sqrt", "(x)", "square root"),
    ("sin", "(x)", "sine"),
    ("cos", "(x)", "cosine"),
    ("tan", "(x)", "tangent"),
    ("asin", "(x)", "arc sine"),
    ("acos", "(x)", "arc cosine"),
    ("atan", "(x)", "arc tangent"),
    ("atan2", "(y, x)", "angle of the point (x, y)"),
    ("sinh", "(x)", "hyperbolic sine"),
    ("cosh", "(x)", "hyperbolic cosine"),
    ("tanh", "(x)", "hyperbolic tangent"),
    ("exp", "(x)", "e to the power x"),
    ("log", "(x, base=e)", "logarithm, natural unless a base is given"),
    ("ln", "(x)", "natural logarithm"),
    ("log10", "(x)", "base-10 logarithm"),
    ("log2", "(x)", "base-2 logarithm"),
    ("abs", "(x)", "absolute value"),
    ("round", "(x, digits)", "round, to whole number or to digits"),
    ("floor", "(x)", "round down"),
    ("ceiling", "(x)", "round up"),
    ("int", "(x)", "whole part, toward zero"),
    ("float", "(x)", "decimal value"),
    ("max", "(a, b, ...)", "largest"),
    ("min", "(a, b, ...)", "smallest"),
    ("sum", "([a, b, ...])", "add up"),
    ("pow", "(x, y)", "x to the power y"),
    ("cbrt", "(x)", "cube root"),
    ("root", "(x, n)", "n-th root"),
    ("hypot", "(a, b)", "√(a² + b²)"),
    ("factorial", "(n)", "n!"),
    ("binomial", "(n, k)", "n choose k"),
    ("nCr", "(n, r)", "combinations"),
    ("nPr", "(n, r)", "permutations"),
    ("gcd", "(a, b)", "greatest common divisor"),
    ("lcm", "(a, b)", "least common multiple"),
    ("mod", "(a, n)", "remainder of a / n"),
    ("factorint", "(n)", "prime factors with powers"),
    ("isprime", "(n)", "is n prime?"),
    ("prime", "(n)", "the n-th prime"),
    ("radians", "(deg)", "degrees to radians"),
    ("degrees", "(rad)", "radians to degrees"),
    ("solve", "(expr, x)", "roots of expr = 0 (or just type a = b)"),
    ("nsolve", "(expr, x, guess)", "numeric root near a guess"),
    ("diff", "(f, x, n=1)", "derivative"),
    ("integrate", "(f, x) | (f, (x, a, b))", "integral, indefinite or definite"),
    ("limit", "(f, x, a)", "limit as x → a"),
    ("series", "(f, x, a, n)", "Taylor series around a"),
    ("summation", "(f, (k, a, b))", "Σ f for k from a to b"),
    ("product", "(f, (k, a, b))", "Π f for k from a to b"),
    ("simplify", "(expr)", "simplest form"),
    ("expand", "(expr)", "multiply out"),
    ("factor", "(expr)", "factorise"),
    ("collect", "(expr, x)", "group powers of x"),
    ("apart", "(expr)", "partial fractions"),
    ("together", "(expr)", "single fraction"),
    ("N", "(expr, digits)", "numeric value to any precision"),
    ("re", "(z)", "real part"),
    ("im", "(z)", "imaginary part"),
    ("arg", "(z)", "argument (angle) of z"),
    ("conjugate", "(z)", "complex conjugate"),
    ("Matrix", "([[a, b], [c, d]])", "matrix"),
    ("det", "(M)", "determinant"),
    ("inv", "(M)", "inverse matrix"),
    ("tr", "(M)", "trace"),
    ("transpose", "(M)", "transpose"),
    ("eye", "(n)", "identity matrix"),
    ("zeros", "(n, m)", "zero matrix"),
    ("plot", "(f, g, ..., a, b)", "sketch functions from a to b"),
    ("pi", "", "π = 3.14159…"),
    ("e", "", "ℯ = 2.71828…"),
    ("i", "", "imaginary unit"),
    ("oo", "", "infinity"),
    ("ans", "", "last result"),
]
_RANK = {name: k for k, (name, _, _) in enumerate(CATALOG)}
_KNOWN = {name: (sig, doc) for name, sig, doc in CATALOG}
# Beyond the catalog, only real mathematical functions (gamma, erf, besselj…),
# not SymPy's internal helpers.
MATH_FUNCTIONS = sorted(
    n for n in FUNCTIONS
    if isinstance(_SYMPY_NAMES.get(n), type) and issubclass(_SYMPY_NAMES[n], sp.Function)
)
CONSTANTS = {"pi", "e", "i", "oo", "ans", "E", "I"}


def describe(name: str) -> Item:
    if name in _KNOWN:
        sig, doc = _KNOWN[name]
        return Item(name, sig, doc, "const" if name in CONSTANTS or not sig else "func")
    obj = ALIASES.get(name) or _SYMPY_NAMES.get(name)
    doc = ""
    if obj is not None and getattr(obj, "__doc__", None):
        doc = next((ln.strip() for ln in obj.__doc__.strip().splitlines() if ln.strip()), "")
        doc = doc.rstrip(".")[:70]
    return Item(name, "(…)", doc, "func")


def complete(word: str, user: dict[str, object], limit: int = 8) -> list[Item]:
    """Names starting with word: your variables first, then everyday functions, then the rest."""
    if not word:
        return []
    out: list[Item] = []
    for name, value in sorted(user.items()):
        if name.startswith(word) and name != "ans":
            if isinstance(value, sp.Lambda):
                sig = "(" + ", ".join(str(v) for v in value.variables) + ")"
                out.append(Item(name, sig, "your function", "func"))
            else:
                out.append(Item(name, "", f"= {sp.sstr(value)}"[:60], "var"))
    seen = {i.name for i in out}
    common = sorted((n for n in _RANK if n.startswith(word) and n not in seen), key=_RANK.get)
    rest = sorted(n for n in MATH_FUNCTIONS if n.startswith(word) and n not in seen and n not in _RANK)
    for name in common + rest:
        if len(out) >= limit:
            break
        out.append(describe(name))
    return out[:limit]
