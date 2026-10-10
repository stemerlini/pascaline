"""The math engine: Casio-style input parsed with SymPy, plus the sheet's state.

Syntax on top of SymPy:
  2x, 3(x+1), sin x   implicit multiplication and application
  x^2, 5!, √2, π      powers, factorial, unicode shorthands
  a = 3/4             store a variable
  f(x) = x^2 + 1      define a function
  x^2 - 4 = 0         solve an equation (several separated by commas = a system)
  ans, _3             last result, result of cell 3
  plot(sin x, cos x, -pi, pi)   sketch one or more functions
"""

from __future__ import annotations

import contextlib
import re
import threading
import warnings
from dataclasses import dataclass, field

import mpmath
import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_application,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from . import units

warnings.filterwarnings("ignore", module="sympy")
warnings.filterwarnings("ignore", message=".*non-Expr.*")

TRANSFORMS = standard_transformations + (convert_xor, implicit_multiplication, implicit_application)

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
ASSIGN_RE = re.compile(rf"^\s*({IDENT})\s*=(?!=)(.*)$", re.S)
FUNCDEF_RE = re.compile(rf"^\s*({IDENT})\s*\(\s*({IDENT}(?:\s*,\s*{IDENT})*)\s*\)\s*=(?!=)(.*)$", re.S)

# A number written against a name binds tighter than / and *, like on paper:
# 100 km / 2 hour is 100 km / (2 hour), and 1/2x is 1/(2x).
TIGHT_RE = re.compile(r"(?<![\w.])((?>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?))\s*([A-Za-z_]\w*(?:\^-?\d+)?)(?![\w(])")
HEX_RE = re.compile(r"(?<![\w.])0[xXbBoO][0-9a-fA-F]")

UNICODE = {
    "×": "*", "·": "*", "÷": "/", "−": "-", "π": "pi", "√": "sqrt ", "∞": "oo",
    "²": "^2", "³": "^3", "⁻¹": "^(-1)", "θ": "theta",
}

# Python habits: math.sqrt(2), np.exp(1) and friends mean the plain function.
MODULE_PREFIX = re.compile(r"\b(?:math|cmath|numpy|np|sympy|sp|scipy)\.")


def _round(x, n=None):
    if n is None:
        return sp.sympify(x).round()
    return sp.Float(round(float(sp.N(x, 30)), int(n)), 15)


def _sum(*args):
    items = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple, sp.Tuple)) else args
    return sp.Add(*items)


# Names that read better than SymPy's own: Python builtins, Casio and textbook style.
ALIASES = {
    "round": _round,
    "max": sp.Max,
    "min": sp.Min,
    "pow": lambda a, b: sp.sympify(a) ** b,
    "sum": _sum,
    "int": lambda x: sp.Integer(int(sp.N(x, 50))),
    "float": lambda x: sp.N(x),
    "hypot": lambda a, b: sp.sqrt(sp.sympify(a) ** 2 + sp.sympify(b) ** 2),
    "radians": lambda x: sp.sympify(x) * sp.pi / 180,
    "degrees": lambda x: sp.sympify(x) * 180 / sp.pi,
    "comb": sp.binomial,
    "perm": lambda n, r: sp.factorial(n) / sp.factorial(n - r),
    "ln": sp.log,
    "lg": lambda x: sp.log(x, 10),
    "log10": lambda x: sp.log(x, 10),
    "log2": lambda x: sp.log(x, 2),
    "abs": sp.Abs,
    "nCr": sp.binomial,
    "nPr": lambda n, r: sp.factorial(n) / sp.factorial(n - r),
    "mod": sp.Mod,
    "mat": sp.Matrix,
    "det": lambda m: sp.Matrix(m).det(),
    "inv": lambda m: sp.Matrix(m).inv(),
    "tr": lambda m: sp.Matrix(m).trace(),
    "transpose": lambda m: sp.Matrix(m).T,
    "deriv": sp.diff,
    "integ": sp.integrate,
    "num": sp.N,
    "e": sp.E,
    "i": sp.I,
    "inf": sp.oo,
}

TRIG = ("sin", "cos", "tan", "sec", "csc", "cot")
ARC = ("asin", "acos", "atan", "asec", "acsc", "acot")

_SYMPY_NAMES: dict = {}
exec("from sympy import *", _SYMPY_NAMES)  # what parse_expr uses by default

FUNCTIONS = sorted(
    {n for n, v in _SYMPY_NAMES.items() if callable(v) and n[:1].islower() and not n.startswith("_")}
    | set(ALIASES) | {"plot", "sqrt", "cbrt", "root"}
)


class MathError(Exception):
    """A problem worth showing the user as is."""


@dataclass
class Plot:
    exprs: list
    var: sp.Symbol
    lo: float
    hi: float
    labels: list[str] = field(default_factory=list)


@dataclass
class Result:
    kind: str  # value | assign | solve | plot | error
    text: str = ""  # exact, pretty-printed (may span lines)
    approx: str | None = None  # decimal approximation, when it adds something
    value: object = None
    plot: Plot | None = None
    inline: str | None = None  # one-line form, when the pretty one spans lines
    latex: str | None = None

    @property
    def copy_text(self) -> str:
        if self.approx:
            return self.approx
        if self.value is not None and not isinstance(self.value, Plot):
            try:
                return sp.sstr(self.value)
            except ValueError:  # integers too long to print
                return self.text.split()[0]
        return self.text


class Engine:
    def __init__(self, digits: int = 12, degrees: bool = False):
        self.digits = digits
        self.degrees = degrees
        self.vars: dict[str, object] = {}
        self.lock = threading.Lock()

    # -- state -------------------------------------------------------------

    def reset(self) -> None:
        self.vars.clear()

    def user_names(self) -> list[str]:
        return [n for n in self.vars if n != "ans" and not re.fullmatch(r"_\d+", n)]

    def namespace(self) -> dict:
        ns = dict(_SYMPY_NAMES)
        ns.update(ALIASES)
        ns["plot"] = _plot
        if self.degrees:
            k = sp.pi / 180
            for name in TRIG:
                ns[name] = (lambda f: lambda x: f(x * k))(getattr(sp, name))
            for name in ARC:
                ns[name] = (lambda f: lambda x: f(x) / k)(getattr(sp, name))
        return ns

    # -- evaluation --------------------------------------------------------

    def run(self, src: str, cell: int | None = None, commit: bool = True) -> Result:
        """Evaluate one cell. With commit=False nothing is stored (live preview)."""
        try:
            res = self._run(normalize(src), commit)
        except MathError as exc:
            return Result("error", str(exc))
        except (SyntaxError, TokenError_) as exc:
            return Result("error", f"syntax error{_where(exc)}")
        except ZeroDivisionError:
            return Result("error", "division by zero")
        except RecursionError:
            return Result("error", "too deeply nested")
        except Exception as exc:  # SymPy raises nearly anything on bad input
            msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            return Result("error", msg[:200])
        if commit and res.value is not None and res.kind != "plot":
            self.vars["ans"] = res.value
            if cell is not None:
                self.vars[f"_{cell}"] = res.value
        return res

    def _run(self, src: str, commit: bool) -> Result:
        if not src:
            raise MathError("nothing to evaluate")
        m = FUNCDEF_RE.match(src)
        if m and self._is_definition(m):
            name, params, body = m.group(1), m.group(2), m.group(3)
            syms = [sp.Symbol(p.strip()) for p in params.split(",")]
            expr = self.parse(body, {s.name: s for s in syms})
            fn = sp.Lambda(tuple(syms), expr)
            if commit:
                self.vars[name] = fn
            shown = sp.Eq(sp.Function(name)(*syms), expr, evaluate=False)
            return Result("assign", self.pretty(shown), value=None, latex=sp.latex(shown))
        if (m := ASSIGN_RE.match(src)) and _top_level_eq(src) == [m.start(2) - 1]:
            name, body = m.group(1), m.group(2)
            if name in ("pi", "oo", "e", "i"):  # E and I stay free: E for energy, I for current
                raise MathError(f"{name} is a constant")
            value = self.parse(body)
            if commit:
                self.vars[name] = value
            res = self.describe(value)
            res.kind = "assign"
            if _is_expr(value) and not units.has_units(value):
                res.text = self.pretty(sp.Eq(sp.Symbol(name), value, evaluate=False))
            else:
                res.text = f"{name} = {res.text}"
            if res.latex:
                res.latex = f"{sp.latex(sp.Symbol(name))} = {res.latex}"
            return res
        if _top_level_eq(src):
            return self.solve(src)
        return self.describe(self.parse(src))

    def _is_definition(self, m: re.Match) -> bool:
        """f(x) = ... defines f, unless f is built in, or already defined and the
        right side doesn't mention x: then it is an equation, f(x) = 0."""
        name, params, body = m.group(1), m.group(2), m.group(3)
        if isinstance(self.vars.get(name), sp.Lambda):
            words = set(re.findall(IDENT, body))
            return any(p.strip() in words for p in params.split(","))
        return name not in self.namespace() and name not in self.vars

    def parse(self, src: str, extra: dict | None = None):
        if not src.strip():
            raise MathError("missing expression")
        body, target_src = units.split_target(src)
        local = dict(self.vars)
        if extra:
            local.update(extra)
        local = {**units.bindings(src, set(local), explicit=target_src is not None), **local}
        body = _wrap_matrices(body)
        ns = self.namespace()
        _guard(body, local, ns)
        value = parse_expr(body, local_dict=local, global_dict=ns, transformations=TRANSFORMS)
        if target_src is not None:
            if not target_src:
                raise MathError("convert to what? e.g. 5 km/h to m/s")
            target = parse_expr(target_src, local_dict=local, global_dict=ns, transformations=TRANSFORMS)
            try:
                value = units.convert(value, target)
            except ValueError as exc:
                raise MathError(str(exc)) from None
        elif units.has_units(value):
            value = units.convert(value, src=body, skip=frozenset(self.vars) | frozenset(extra or ()))
        if isinstance(value, (list, tuple)) and value and all(isinstance(r, (list, tuple)) for r in value):
            value = sp.Matrix(value)
        elif isinstance(value, bool):
            value = sp.true if value else sp.false
        elif isinstance(value, (int, float, complex)):
            value = sp.sympify(value)
        return value

    def solve(self, src: str) -> Result:
        eqs = []
        for part in _split_top(src, ","):
            idx = _top_level_eq(part)
            if len(idx) != 1:
                raise MathError("one '=' per equation")
            lhs, rhs = part[: idx[0]], part[idx[0] + 1 :]
            eqs.append(sp.Eq(self.parse(lhs), self.parse(rhs)))
        eqs = [e for e in eqs if e is not sp.true]
        if any(e is sp.false for e in eqs):
            return Result("solve", "no solution (contradiction)")
        if not eqs:
            return Result("solve", "always true")
        syms = sorted(set().union(*(e.free_symbols for e in eqs)), key=lambda s: s.name)
        if len(eqs) == 1 and len(syms) > 1:
            pick = next((s for s in syms if s.name in ("x", "y", "z", "t", "n")), syms[0])
            syms = [pick]
        try:
            sols = sp.solve(eqs, syms, dict=True)
        except NotImplementedError:
            sols = None
        if not sols and len(eqs) == 1 and len(syms) == 1:
            sols = self._nsolve(eqs[0], syms[0])
            if sols:
                return self._format_solutions(sols, numeric=True)
        if sols is None:
            raise MathError("can't solve this one symbolically")
        if not sols:
            return Result("solve", "no solution")
        return self._format_solutions(sols)

    def _nsolve(self, eq, x) -> list[dict]:
        f = eq.lhs - eq.rhs
        roots: list[float] = []
        for guess in [0, 1, -1, 2, -2, 5, -5, 10, -10, 0.5, -0.5, 3, -3, 20, -20]:
            try:
                r = complex(sp.nsolve(f, x, guess))
            except Exception:
                continue
            if abs(r.imag) > 1e-10:
                continue
            if all(abs(r.real - q) > 1e-8 * max(1, abs(q)) for q in roots):
                roots.append(r.real)
        return [{x: sp.Float(r, self.digits + 3)} for r in sorted(roots)]

    def _format_solutions(self, sols: list[dict], numeric: bool = False) -> Result:
        lines, approx = [], []
        for sol in sols:
            eqs = [sp.Eq(k, v, evaluate=False) for k, v in sol.items()]
            shown = eqs[0] if len(eqs) == 1 else sp.Tuple(*eqs)
            lines.append(self.pretty(shown) if not numeric else
                         ", ".join(f"{k} ≈ {fmt_number(v, self.digits)}" for k, v in sol.items()))
            vals = [v for v in sol.values() if _is_expr(v) and v.is_number]
            if not numeric and vals and not all(v.is_Integer for v in vals):
                line = ", ".join(f"{k} ≈ {fmt_number(v, self.digits)}" for k, v in sol.items()
                                 if v.is_number)
                if not _same(line.replace("≈", "="), lines[-1]):
                    approx.append(line)
        value = sols[0][next(iter(sols[0]))] if len(sols) == 1 and len(sols[0]) == 1 else \
            sp.Tuple(*[sp.Tuple(*s.values()) for s in sols])
        inline = "   ".join(
            ", ".join(f"{k} = {_sstr(v)}" for k, v in sol.items()) if not numeric
            else ", ".join(f"{k} ≈ {fmt_number(v, self.digits)}" for k, v in sol.items())
            for sol in sols
        )
        latex = r", \quad ".join(sp.latex(sp.Eq(k, v)) for sol in sols for k, v in sol.items())
        return Result("solve", "\n".join(lines), "\n".join(approx) or None, value=value, inline=inline,
                      latex=latex)

    # -- formatting --------------------------------------------------------

    def describe(self, value) -> Result:
        if isinstance(value, Plot):
            return Result("plot", plot=value, value=value)
        if isinstance(value, str):
            return Result("value", value, value=None)
        if not isinstance(value, sp.Basic | sp.MatrixBase):
            try:
                value = sp.sympify(value)
            except Exception:
                return Result("value", str(value), value=None)
        if value in (sp.zoo, sp.nan):
            raise MathError("undefined (division by zero?)")
        res = self._describe(value)
        if res.latex is None and res.value is not None:
            with contextlib.suppress(Exception):
                res.latex = sp.latex(res.value)
        return res

    def _describe(self, value) -> Result:
        if units.has_units(value):
            num, unit = units.split(value)
            if num * unit != value:  # mixed sums that don't share units
                return Result("value", self.pretty(value), value=value)
            shown = units.show(unit)
            approx = None
            if num.is_Float or (num.is_Rational and num.q > 100):  # 96.56 km/h, not 301752/3125
                text = fmt_number(num, self.digits)
            elif num.is_Integer:
                text = str(num)
            else:
                text = _sstr(num)
                if num.is_number:
                    approx = f"{fmt_number(num, self.digits)} {shown}"
            return Result("value", f"{text} {shown}", approx, value)
        if value in (sp.true, sp.false):
            return Result("value", "true" if value is sp.true else "false", value=value)
        approx = None
        if isinstance(value, sp.MatrixBase):
            if any(not v.is_Integer and v.is_number and not v.is_Float for v in value) and value.is_symbolic() is False:
                approx = self.pretty(value.evalf(self.digits))
            return Result("value", self.pretty(value), approx, value)
        if value.is_Integer:
            n = int(value)
            digits = len(str(abs(n))) if n.bit_length() < 4000 else \
                int(mpmath.floor(mpmath.log10(mpmath.mpf(abs(n))))) + 1
            if digits > 80:
                return Result("value", f"{fmt_number(value, self.digits)}  ({digits} digits)", value=value)
            return Result("value", str(n), value=value)
        if value.is_Float:
            dps = mpmath.libmp.prec_to_dps(value._prec)
            return Result("value", fmt_number(value, dps if dps > 15 else self.digits), value=value)
        if value.is_number:
            if value.has(sp.I):
                value = sp.expand(value)
            try:
                approx = fmt_number(value, self.digits)
            except Exception:
                approx = None
            text = self.pretty(value)
            if approx is None or _same(approx, text) or approx == "nan":
                approx = None
            return Result("value", text, approx, value)
        return Result("value", self.pretty(value), value=value)

    def pretty(self, value) -> str:
        if _is_expr(value) and value.has(sp.Float):
            value = value.xreplace({f: sp.Float(fmt_number(f, self.digits)) for f in value.atoms(sp.Float)})
        out = sp.pretty(value, use_unicode=True, num_columns=10_000)
        return out.replace("⋅ⅈ", "i").replace("ⅈ", "i")


def fmt_number(value, digits: int = 12) -> str:
    """A short decimal rendering: 1025.41421356, 6.02214076e+23, 1.5 + 2i."""
    v = sp.N(value, digits + 3)
    re_, im_ = v.as_real_imag()
    if not (re_.is_number and im_.is_number):
        raise MathError("not a number")

    def one(x) -> str:
        with mpmath.workdps(digits + 5):
            s = mpmath.nstr(mpmath.mpf(x), digits, min_fixed=-5, max_fixed=digits)
        return s[:-2] if s.endswith(".0") else s

    if abs(im_) < sp.Float(10) ** -(digits + 1) * max(1, abs(re_)):
        return one(re_)
    if abs(re_) < sp.Float(10) ** -(digits + 1) * max(1, abs(im_)):
        return ("-" if im_ < 0 else "") + _imag(one(abs(im_)))
    sign = "-" if im_ < 0 else "+"
    return f"{one(re_)} {sign} {_imag(one(abs(im_)))}"


def _imag(s: str) -> str:
    return "i" if s == "1" else f"{s}i"


def normalize(src: str) -> str:
    src = MODULE_PREFIX.sub("", src.strip())
    for k, v in UNICODE.items():
        src = src.replace(k, v)
    if src.endswith("=") and not src.endswith("=="):
        src = src[:-1].rstrip()  # Casio habit: "2+3="
    if not HEX_RE.search(src):
        src = TIGHT_RE.sub(r"(\1*\2)", src)
    return src


MAX_DIGITS = 1_000_000


def _guard(src: str, local: dict, ns: dict) -> None:
    """Refuse exact results so big they would freeze the app (10^10^10, (10^7)!)."""
    try:
        tree = parse_expr(src, local_dict=dict(local), global_dict=ns, transformations=TRANSFORMS,
                          evaluate=False)
        nodes = list(sp.preorder_traversal(tree)) if isinstance(tree, sp.Basic) else []
    except Exception:
        return  # the real parse reports the problem
    for node in nodes:
        if isinstance(node, sp.Pow) and all(a.is_number for a in node.args):
            base, exp = node.args
            try:
                mag = float(sp.N(sp.Abs(exp))) * abs(float(sp.N(sp.log(sp.Abs(base), 10))))
            except (TypeError, ValueError, OverflowError):
                continue
            if mag > MAX_DIGITS and not base.has(sp.Float):
                raise MathError(f"too big to compute exactly (about 10^{mag:.4g}); try N(...) or a float")
        elif isinstance(node, sp.factorial) and node.args[0].is_number:
            try:
                n = float(sp.N(node.args[0]))
            except (TypeError, ValueError, OverflowError):
                continue
            if n > 200_000:
                raise MathError("factorial too big to compute exactly")


def _sstr(v) -> str:
    s = sp.sstr(v).replace("**", "^").replace("sqrt", "√").replace("*I", "i")
    return re.sub(r"\bI\b", "i", s)


def _same(a: str, b: str) -> bool:
    """Equal once spacing and the multiplication dot are ignored."""
    def squash(s: str) -> str:
        return re.sub(r"[\s⋅()]", "", s)
    return squash(a) == squash(b)


def _wrap_matrices(src: str) -> str:
    """Turn nested list literals like [[1,2],[3,4]] into Matrix([[1,2],[3,4]])."""
    out, i = [], 0
    while i < len(src):
        prev = src[:i].rstrip()[-1:] if src[:i].strip() else ""
        if src[i] == "[" and src[i + 1 :].lstrip().startswith("[") and not (prev and (prev.isalnum() or prev in "_)]")):
            depth = 0
            for j in range(i, len(src)):
                depth += {"[": 1, "]": -1}.get(src[j], 0)
                if depth == 0:
                    out.append(f"Matrix({src[i : j + 1]})")
                    i = j + 1
                    break
            else:
                out.append(src[i:])
                break
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def _is_expr(v) -> bool:
    return isinstance(v, sp.Basic)


def _depths(src: str):
    depth = 0
    for i, ch in enumerate(src):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        yield i, ch, depth


def _top_level_eq(src: str) -> list[int]:
    """Positions of single '=' (not ==, <=, >=, !=) outside brackets."""
    out = []
    for i, ch, depth in _depths(src):
        if ch == "=" and depth == 0:
            prev = src[i - 1] if i else ""
            nxt = src[i + 1] if i + 1 < len(src) else ""
            if prev not in "=<>!" and nxt != "=":
                out.append(i)
    return out


def _split_top(src: str, sep: str) -> list[str]:
    parts, start = [], 0
    for i, ch, depth in _depths(src):
        if ch == sep and depth == 0:
            parts.append(src[start:i])
            start = i + 1
    parts.append(src[start:])
    return [p for p in (p.strip() for p in parts) if p]


def _where(exc) -> str:
    return f" at column {exc.offset}" if getattr(exc, "offset", None) else ""


try:
    from tokenize import TokenError as TokenError_
except ImportError:  # pragma: no cover
    TokenError_ = SyntaxError


def _plot(*args) -> Plot:
    """plot(f, g, ..., [lo, hi]) or plot(f, (x, lo, hi))."""
    args = list(args)
    lo, hi, var = -10.0, 10.0, None
    if args and isinstance(args[-1], (tuple, sp.Tuple)) and len(args[-1]) == 3:
        var, lo, hi = args.pop()
    elif len(args) >= 3 and all(_is_number(a) for a in args[-2:]):
        hi = args.pop()
        lo = args.pop()
    if not args:
        raise MathError("plot what? e.g. plot(sin x, -pi, pi)")
    exprs = []
    for a in args:
        if isinstance(a, sp.Lambda):
            a = a(*[sp.Symbol(v.name) for v in a.variables])
        exprs.append(sp.sympify(a))
    if var is None:
        free = set().union(*(e.free_symbols for e in exprs))
        if len(free) > 1:
            raise MathError("plot needs a single variable: " + ", ".join(sorted(map(str, free))))
        var = free.pop() if free else sp.Symbol("x")
    lo, hi = float(sp.N(lo)), float(sp.N(hi))
    if not lo < hi:
        raise MathError("plot range must go from low to high")
    return Plot(exprs, var, lo, hi)


def _is_number(a) -> bool:
    try:
        return sp.sympify(a).is_number is True
    except Exception:
        return False
