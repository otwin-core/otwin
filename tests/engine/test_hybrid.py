"""Grey-box models: symbolic residuals, learned residuals, parameter fitting."""

import numpy as np
import pytest

import otwin
from otwin import HybridModel, fit_parameters
from otwin.components import catalogue
from otwin.hybrid import residual_data


def plant():
    """The README grey-box case: quadratic drag the linear model does not know about."""
    return otwin.compile(catalogue.mass_spring_damper(1.0, 2.0, 0.3, position=1.0))


def test_symbolic_residual_runs_in_the_engine(backend):
    m = otwin.compile(
        catalogue.mass_spring_damper(1.0, 2.0, 0.3, position=1.0), backend=backend
    )
    v = m.symbol("mass.velocity")
    grey = m.with_residual(
        {"mass.momentum": -m.parameter("drag") * v * abs(v)}, parameters={"drag": 0.6}
    )
    assert "drag" in grey.param_names and grey.backend == backend
    assert "residual" in grey.representation
    t = np.linspace(0, 10, 501)
    a, b = m.simulate(t=t), grey.simulate(t=t)
    assert b.energy[-1] < a.energy[-1]  # extra dissipation
    # setting drag to zero recovers the physics exactly
    assert np.allclose(grey.with_parameters(drag=1e-300).simulate(t=t).x, a.x, atol=1e-12)
    with pytest.raises(KeyError, match="give its value"):
        m.with_residual({"mass.momentum": m.parameter("unknown") * v})
    with pytest.raises(KeyError, match="not a state"):
        m.with_residual({"nothing": v})


def test_fit_parameters_recovers_a_coefficient():
    m = plant()
    v = m.symbol("mass.velocity")
    truth = m.with_residual(
        {"mass.momentum": -m.parameter("drag") * v * abs(v)}, parameters={"drag": 0.9}
    )
    t = np.linspace(0, 8, 161)
    y = truth.simulate(t=t)["spring.extension"]
    rng = np.random.default_rng(0)
    y_noisy = y + rng.normal(0, 1e-3, y.shape)
    start = truth.with_parameters(drag=0.2)
    fit = fit_parameters(
        start, t, {"spring.extension": y_noisy}, ["drag", "spring.stiffness"]
    )
    assert fit.success
    assert fit.values["drag"] == pytest.approx(0.9, rel=0.05)
    assert fit.values["spring.stiffness"] == pytest.approx(2.0, rel=0.02)
    assert fit.identifiability is not None
    assert fit.identifiability.verdicts["spring.stiffness"] is True
    assert fit.model.parameters["drag"] == pytest.approx(fit.values["drag"])


def test_fit_rejects_unknown_names():
    m = plant()
    t = np.linspace(0, 1, 11)
    with pytest.raises(KeyError, match="not a parameter"):
        fit_parameters(m, t, {"spring.extension": np.zeros(11)}, ["nope"])
    with pytest.raises(KeyError, match="not an output"):
        fit_parameters(m, t, {"nope": np.zeros(11)}, ["spring.stiffness"])


def test_hybrid_model_with_callable_residual():
    m = plant()
    hybrid = HybridModel(m, lambda x, u, t: np.array([0.0, -0.9 * x[1] * abs(x[1])]))
    assert hybrid.n_states == 2 and hybrid.state_names == m.state_names
    t = np.linspace(0, 5, 101)
    tr = hybrid.simulate(t=t)
    assert tr.energy[0] == pytest.approx(m.energy(m.initial_state()))
    assert tr.energy[-1] < m.simulate(t=t).energy[-1]
    r = hybrid.residual_rhs(np.array([0.0, 2.0]))
    assert r[0] == 0.0 and r[1] == pytest.approx(-3.6)
    assert "Residual" in hybrid.summary()
    masked = HybridModel(m, lambda x, u, t: np.ones(2), mask=[1])
    assert masked.residual_rhs(np.zeros(2))[0] == 0.0


def test_residual_data_is_the_physics_gap():
    m = plant()
    X = np.array([[0.5, 1.0], [-0.2, 0.3]])
    truth = np.array([m.rhs(x) + np.array([0.0, -0.9 * x[1] * abs(x[1])]) for x in X])
    r = residual_data(m, X, truth)
    assert np.allclose(r[:, 0], 0.0)
    assert np.allclose(r[:, 1], -0.9 * X[:, 1] * np.abs(X[:, 1]))


def test_gp_residual_plugs_in():
    pytest.importorskip("sklearn")
    from otwin.forecast import GPPHS

    m = plant()
    rng = np.random.default_rng(0)
    X = rng.uniform(-1.2, 1.2, size=(80, 2))
    truth = np.array([m.rhs(x) + np.array([0.0, -0.9 * x[1] * abs(x[1])]) for x in X])
    np.random.seed(0)  # noqa: NPY002 - GPPHS seeds its restarts from the legacy global state
    gp = GPPHS(n_states=2, prior_dynamics=lambda x, u: m.rhs(x)).fit(X, truth)
    # GPPHS predicts the full derivative (prior + correction); feed only the correction
    hybrid = HybridModel(
        m, lambda x, u, t: gp.predict(x.reshape(1, -1), return_std=False)[0] - m.rhs(x)
    )
    x = np.array([0.5, 0.8])
    assert np.allclose(
        hybrid.rhs(x), gp.predict(x.reshape(1, -1), return_std=False)[0], atol=1e-9
    )
