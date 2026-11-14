"""The vectorised output evaluator against the model's own scalar evaluation.

Meters and calibration evaluate outputs at thousands of states in one pass;
the numbers must be the model's, bit for bit, or the energy bookkeeping and
every fit built on it would quietly drift.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from otwin import expr as ex

from components import ZERO_CELSIUS, madrid_flat, seville_house
from components.evaluate import evaluate_expr, evaluate_outputs

K0 = ZERO_CELSIUS
START = datetime(2026, 1, 11, 23, tzinfo=timezone.utc)


@pytest.mark.parametrize("build", [madrid_flat, seville_house])
def test_every_output_matches_the_backend(backend, build):
    twin = build(backend=backend)
    t = np.arange(0, 2 * 86400 + 1, 900.0)
    warm = 22.0 if build is seville_house else 0.0
    outdoor = K0 + 6 + warm - 5 * np.cos(2 * np.pi * (t / 3600 - 6) / 24)
    u = twin.inputs(t, start=START, outdoor=outdoor)
    run = twin.model.simulate(t=t, inputs=u)
    X = np.asarray(run.x)
    U = np.column_stack([u[n] for n in twin.model.input_names])
    names = twin.model.output_names
    vec = evaluate_outputs(twin.model, names, X, U, t)
    for k in range(0, t.size, 5):
        ref = twin.model.outputs(X[k], U[k], t[k])
        for n in names:
            assert vec[n][k] == pytest.approx(ref[n], rel=1e-14, abs=1e-12), (n, k)


def test_it_follows_parameter_changes(backend):
    twin = madrid_flat(backend=backend)
    x = np.asarray(twin.model.initial_state().values)[None, :]
    u = np.zeros((1, twin.model.n_inputs))
    before = evaluate_outputs(twin.model, ["base.electric_power"], x, u, [0.0])
    twin.model.set_parameters({"base.power": 333.0})
    after = evaluate_outputs(twin.model, ["base.electric_power"], x, u, [0.0])
    assert before["base.electric_power"][0] == 120.0
    assert after["base.electric_power"][0] == 333.0
    with pytest.raises(KeyError, match="not an output"):
        evaluate_outputs(twin.model, ["nope"], x, u, [0.0])


def test_every_node_type_matches_the_scalar_evaluator():
    a, b = ex.symbol("state", "a"), ex.symbol("input", "b")
    t = ex.symbol("time", "t")
    exprs = [
        a + b,
        a - b,
        a * b,
        a / b,
        ex.power(ex.abs_(a), b),
        -a,
        ex.sqrt(a),
        ex.exp(b),
        ex.log(a),
        ex.abs_(a),
        ex.tanh(a),
        ex.sin(a),
        ex.cos(b),
        ex.sign(a),
        ex.maximum(a, b),
        ex.minimum(a, b),
        ex.where(a > b, a, b * t),
        ex.interp(a, [-1.0, 0.0, 2.0], [3.0, -1.0, 5.0]),
        ex.piecewise(b, [0.0, 1.0, 3.0], [(1.0, 2.0, 0.5), (0.0, -1.0, 2.0)]),
    ]
    av = np.array([-2.0, -0.5, 0.0, 0.3, 1.0, 2.5, 7.0])
    bv = np.array([1.5, 0.0, -1.0, 0.3, 2.0, -3.0, 0.5])
    tv = np.linspace(0.0, 6.0, av.size)
    env = {"state:a": av, "input:b": bv, "time:t": tv}
    for e in exprs:
        vec = evaluate_expr(e, env, av.size)
        for i in range(av.size):
            ref = e.evaluate({"state:a": av[i], "input:b": bv[i], "time:t": tv[i]})
            if np.isnan(ref):
                assert np.isnan(vec[i]), (e, i)
            else:
                assert vec[i] == pytest.approx(ref, rel=1e-15, abs=0), (e, i)
