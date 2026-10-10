import pytest

from pascaline.engine import Engine, fmt_number


@pytest.fixture
def e():
    return Engine()


@pytest.mark.parametrize(
    "src, text, approx",
    [
        ("2^10", "1024", None),
        ("2^10 + √2", "√2 + 1024", "1025.41421356"),
        ("1/4", "1/4", "0.25"),
        ("5!", "120", None),
        ("2x + 3x", "5⋅x", None),
        ("sin(pi/6)", "1/2", "0.5"),
        ("0.1 + 0.2", "0.3", None),
        ("2+3=", "5", None),
        ("lg 1000", "3", None),
        ("e^(i pi)", "-1", None),
        ("(1+2i)(3-i)", "5 + 5i", None),
        ("sqrt(-4)", "2i", None),
        ("3 > 2", "true", None),
        ("nCr(5, 2)", "10", None),
        ("det([[1,2],[3,4]])", "-2", None),
        ("integrate(x^2, (x, 0, 1))", "1/3", "0.333333333333"),
        ("limit(sin(x)/x, x, 0)", "1", None),
    ],
)
def test_values(e, src, text, approx):
    r = e.run(src)
    assert r.kind == "value", r.text
    assert r.text == text
    assert r.approx == approx


def test_variables_functions_and_ans(e):
    assert e.run("a = 3/4").kind == "assign"
    assert e.run("2a").text == "3/2"
    assert e.run("ans * 2", cell=3).text == "3"
    assert e.run("_3 + 1").text == "4"
    e.run("f(x) = x^2 + 1")
    assert e.run("f(3)").text == "10"
    assert e.run("f(x) = x^3").kind == "assign"  # redefine
    assert e.run("f(2)").text == "8"
    assert e.run("f(x) = 8").text.split("\n")[0] == "x = 2"  # an equation now, f stays
    assert e.run("f(3)").text == "27"


def test_preview_does_not_store(e):
    e.run("a = 1", commit=False)
    assert "a" not in e.vars
    assert "ans" not in e.vars


def test_solve(e):
    r = e.run("x^2 - 4 = 0")
    assert r.kind == "solve" and r.text == "x = -2\nx = 2" and r.approx is None
    r = e.run("x^2 = 2")
    assert r.approx == "x ≈ -1.41421356237\nx ≈ 1.41421356237"
    assert e.run("x + y = 3, x - y = 1").inline == "x = 2, y = 1"


def test_numeric_fallback(e):
    r = e.run("cos(x) = x")
    assert r.kind == "solve" and r.text == "x ≈ 0.739085133215"


def test_known_function_is_not_redefined(e):
    e.run("cos(x) = x")
    assert e.run("cos(0)").text == "1"


def test_degrees():
    e = Engine(degrees=True)
    assert e.run("sin(30)").text == "1/2"
    assert e.run("asin(1/2)").text == "30"


def test_matrices(e):
    e.run("A = [[1,2],[3,4]]")
    assert e.run("A^-1").value.tolist()[0][0] == -2
    assert e.run("[[1,2],[3,4]]^2").value.tolist() == [[7, 10], [15, 22]]


def test_errors(e):
    assert e.run("1/0").kind == "error"
    assert e.run("sin(").kind == "error"
    assert e.run("pi = 3").kind == "error"
    assert e.run("plot(x*y)").kind == "error"


def test_plot(e):
    r = e.run("plot(sin x, cos x, -pi, pi)")
    assert r.kind == "plot" and len(r.plot.exprs) == 2 and r.plot.hi == pytest.approx(3.14159, 1e-4)
    assert "ans" not in e.vars


def test_big_numbers(e):
    assert e.run("2^300").text.endswith("(91 digits)")
    assert e.run("N(pi, 30)").text == "3.14159265358979323846264338328"


def test_fmt_number():
    assert fmt_number(6.02214076e23) == "6.02214076e+23"
    assert fmt_number(0.25) == "0.25"


def test_axis_ticks_are_round_numbers():
    import math

    from pascaline.plot import ticks

    assert [lab for _, lab in ticks(-1.1, 1.1, 5)] == ["-1", "-0.5", "0", "0.5", "1"]
    assert [lab for _, lab in ticks(-math.pi, math.pi, 4)] == ["-π", "-π/2", "0", "π/2", "π"]
    assert [lab for _, lab in ticks(0, 22000, 5)] == ["0", "5000", "10000", "15000", "20000"]
