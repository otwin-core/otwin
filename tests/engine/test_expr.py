"""The symbolic expression layer: simplification, differentiation, serialisation."""

import math

import pytest

from otwin import expr as ex

x = ex.symbol("state", "x")
y = ex.symbol("state", "y")
p = ex.symbol("param", "p")


def ev(e, **vals):
    env = {f"state:{k}": v for k, v in vals.items() if k in ("x", "y")}
    env.update({f"param:{k}": v for k, v in vals.items() if k == "p"})
    return e.evaluate(env)


def test_constant_folding_and_identities():
    assert (x + 0).is_symbol
    assert (x * 1) == x
    assert (x * 0).is_zero()
    assert (x - x).is_zero()
    assert (x / x).is_one()
    assert (2 * x + 3 * x) == 5 * x
    assert (ex.const(2) * ex.const(3)).value == 6.0
    assert ex.neg(ex.neg(x)) == x


def test_structural_equality_and_hash():
    a = 2 * x + p
    b = 2 * x + p
    assert a == b and hash(a) == hash(b)
    assert (a - b).is_zero()
    assert len({a, b}) == 1


def test_differentiation():
    e = p * x * x / 2 + ex.sqrt(x) + ex.exp(2 * x) + ex.log(x) + x**3
    d = e.diff(x)
    for xv in (0.5, 1.3, 2.0):
        exact = 2.0 * xv + 0.5 / math.sqrt(xv) + 2 * math.exp(2 * xv) + 1 / xv + 3 * xv**2
        assert ev(d, x=xv, p=2.0) == pytest.approx(exact, rel=1e-12)
    assert e.diff(y).is_zero()


def test_piecewise_and_abs():
    e = ex.maximum(x, 0.0) ** 2 + abs(x)
    assert ev(e, x=-2.0) == 2.0
    assert ev(e, x=3.0) == 12.0
    d = e.diff(x)
    assert ev(d, x=3.0) == 7.0
    assert ev(d, x=-2.0) == -1.0
    w = ex.where(x > 1.0, x, -x)
    assert ev(w, x=2.0) == 2.0 and ev(w, x=0.5) == -0.5


def test_json_roundtrip_and_lowering():
    e = ex.sign(x) * ex.sqrt(abs(x) / p) + ex.tanh(y) - ex.minimum(x, y)
    back = ex.from_json(e.to_json())
    assert back == e
    low = ex.lower([e], {"state:x": 0, "state:y": 1, "param:p": 2})
    assert low[0][0] == "sub"
    assert "sym" not in str(low)


def test_trace_rejects_untraceable():
    with pytest.raises(TypeError):
        ex.trace(lambda v: "not an expression", x)
    assert ex.trace(lambda v: 3 * v + 1, x) == 3 * x + 1


def test_no_truth_value():
    with pytest.raises(TypeError):
        bool(x)


def test_division_by_constant_zero():
    with pytest.raises(ZeroDivisionError):
        x / 0
