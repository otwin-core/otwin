"""Evaluate a compiled model's outputs over many states at once.

A compiled Otwin model keeps every output as a symbolic expression in its
IR (``model.ir().outputs``). The backends evaluate one state per call, which
is what a time-stepper needs. Meters, calibration and reports need the same
outputs at thousands of states: every step's midpoint, every hour of a
month. :func:`evaluate_outputs` walks the same expression trees with NumPy
arrays instead of numbers, so the result is the model's own output, with
the model's current parameter values, for all states in one pass.

The node semantics mirror ``otwin.expr._eval`` exactly: division by zero
gives a signed infinity or NaN, ``max``/``min``/``gt``/``where`` and
piecewise tables (``pw``) behave as in the scalar evaluator. The tests
check the two against each other on every output of the catalogue homes,
on both backends.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from otwin.expr import Expr

__all__ = ["evaluate_outputs", "evaluate_expr"]

Array = npt.NDArray[np.floating]


def _div(a: Array, b: Array) -> Array:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.divide(a, b)
    zero = b == 0
    if np.any(zero):
        out = np.where(zero, np.where(a != 0, np.copysign(np.inf, a), np.nan), out)
    return out


def _pow(a: Array, b: Array) -> Array:
    """``math.pow`` semantics: NaN wherever it raises (zero to a negative power,
    a negative base to a fractional power, overflow), not NumPy's inf."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        out = np.power(a, b)
    bad = ((a == 0) & (b < 0)) | ((a < 0) & (b != np.round(b)))
    bad |= ~np.isfinite(out) & np.isfinite(a) & np.isfinite(b)
    return np.where(bad, np.nan, out)


def _pw(table: tuple[Any, Any], x: Array) -> Array:
    knots = np.asarray(table[0], dtype=float)
    coefs = np.asarray(table[1], dtype=float)
    n_seg = coefs.shape[0]
    # segment i covers [knots[i], knots[i+1]); the end segments extrapolate
    i = np.searchsorted(knots, x, side="right") - 1
    i = np.clip(i, 0, n_seg - 1)
    d = x - knots[i]
    c = coefs[i]
    return c[..., 0] + d * (c[..., 1] + d * c[..., 2])


def evaluate_expr(e: Expr, env: Mapping[str, Array | float], n: int) -> Array:
    """Evaluate ``e`` with every symbol key bound to an array (or a number).

    ``n`` is the number of points; constants and scalar symbols are
    broadcast to it.
    """
    cache: dict[int, Array] = {}

    def ev(x: Expr) -> Array:
        k = id(x)
        if k in cache:
            return cache[k]
        if x.is_const:
            out = np.full(n, float(x.value))  # type: ignore[arg-type]
        elif x.is_symbol:
            try:
                v = env[x.key]
            except KeyError:
                raise KeyError(f"no value for symbol {x.key}") from None
            out = np.broadcast_to(np.asarray(v, dtype=float), (n,))
        else:
            op, args = x.op, [ev(a) for a in x.args]
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                if op == "neg":
                    out = -args[0]
                elif op == "sqrt":
                    a = args[0]
                    out = np.where(a >= 0, np.sqrt(np.abs(a)), np.nan)
                elif op == "exp":
                    out = np.exp(args[0])
                elif op == "log":
                    a = args[0]
                    out = np.where(
                        a > 0,
                        np.log(np.where(a > 0, a, 1.0)),
                        np.where(a == 0, -np.inf, np.nan),
                    )
                elif op == "abs":
                    out = np.abs(args[0])
                elif op == "tanh":
                    out = np.tanh(args[0])
                elif op == "sin":
                    out = np.sin(args[0])
                elif op == "cos":
                    out = np.cos(args[0])
                elif op == "sign":
                    out = np.sign(args[0])
                elif op == "add":
                    out = args[0] + args[1]
                elif op == "sub":
                    out = args[0] - args[1]
                elif op == "mul":
                    out = args[0] * args[1]
                elif op == "div":
                    out = _div(args[0], args[1])
                elif op == "pow":
                    out = _pow(args[0], args[1])
                elif op == "max":
                    out = np.where(args[0] >= args[1], args[0], args[1])
                elif op == "min":
                    out = np.where(args[0] <= args[1], args[0], args[1])
                elif op == "gt":
                    out = (args[0] > args[1]).astype(float)
                elif op == "where":
                    out = np.where(args[0] != 0.0, args[1], args[2])
                elif op == "pw":
                    out = _pw(x.value, args[0])  # type: ignore[arg-type]
                else:
                    raise ValueError(f"unknown expression node {op!r}")
        cache[k] = out
        return out

    return np.asarray(ev(e), dtype=float)


def evaluate_outputs(
    model: Any,
    names: Sequence[str],
    x: npt.ArrayLike,
    u: npt.ArrayLike,
    t: npt.ArrayLike,
) -> dict[str, Array]:
    """The named outputs of ``model`` at ``n`` points.

    Args:
        model: a compiled :class:`otwin.runtime.Model`.
        names: output names, as in ``model.output_names``.
        x: states, shape ``(n, n_states)``.
        u: inputs, shape ``(n, n_inputs)`` (``(n, 0)`` for none).
        t: times, shape ``(n,)``.

    Returns:
        ``{name: array of n values}``, with the model's current parameters.
    """
    X = np.atleast_2d(np.asarray(x, dtype=float))
    n = X.shape[0]
    U = np.asarray(u, dtype=float).reshape(n, -1)
    ts = np.broadcast_to(np.asarray(t, dtype=float), (n,))
    ir = model.ir()
    env: dict[str, Array | float] = {}
    for i, s in enumerate(model.state_names):
        env[f"state:{s}"] = X[:, i]
    for i, s in enumerate(model.input_names):
        env[f"input:{s}"] = U[:, i]
    for k, v in model.parameters.items():
        env[f"param:{k}"] = float(v)
    env["time:t"] = ts
    out = {}
    for name in names:
        if name not in ir.outputs:
            raise KeyError(f"{name!r} is not an output; outputs: {model.output_names}")
        out[name] = evaluate_expr(ir.outputs[name].expr, env, n)
    return out
