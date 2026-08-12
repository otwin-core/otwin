"""Tests for :mod:`otwin.model.integrators`.

The point of the implicit-midpoint integrator is a *structural guarantee*: with
``u = 0`` a passive port-Hamiltonian system must not gain energy, to machine
precision, no matter how the implicit step is solved. The rewrite that replaced
``scipy.optimize.fsolve`` with a Newton solve on the analytic Jacobian is a pure
performance change, so the tests here are written to catch it changing anything
else:

* the energy bound holds on **every** solver path, not just the default one;
* the trajectories are the same as the old ``fsolve`` path, to 1e-10;
* the closed-form fast path agrees with the general Newton path, to 1e-12;
* the fast path does **not** engage when ``H`` is genuinely nonlinear;
* a step that cannot be solved is reported, not quietly returned.

Each test that asserts good behaviour also pins the thing that would make it
vacuous — which solver path actually ran, or how badly a non-structure-preserving
integrator does on the same problem.
"""

import numpy as np
import pytest

from otwin.model.integrators import (
    IntegratorConvergenceError,
    implicit_midpoint,
    integrate_phs,
    newton_step,
)
from otwin.model.phs import PortHamiltonianSystem
from otwin.model.solvers import integrate_with_inputs

# ----------------------------------------------------------------------
# systems under test
# ----------------------------------------------------------------------


def damped_oscillator(k: float = 1.0, m: float = 1.0, c: float = 0.1):
    """Mass-spring-damper: quadratic ``H``, constant ``J``, ``R``, ``g``.

    ``H(q, p) = ½kq² + ½p²/m``, so ``∇²H = diag(k, 1/m)`` is constant and the
    whole system is linear — the case the closed-form fast path exists for.
    """
    Q = np.diag([k, 1.0 / m])
    J = np.array([[0.0, 1.0], [-1.0, 0.0]])
    R = np.array([[0.0, 0.0], [0.0, c]])
    G = np.array([[0.0], [1.0]])

    phs = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x @ Q @ x),
        J=lambda x: J,
        R=lambda x: R,
        g=lambda x: G,
        n_states=2,
        n_inputs=1,
        grad_H=lambda x: Q @ x,
    )
    phs.hess_H = lambda x: Q
    phs.Q = Q
    return phs


def nonlinear_pendulum(c: float = 0.1):
    """Damped pendulum: ``H(q, p) = (1 − cos q) + ½p²``.

    ``∇H = [sin q, p]`` and ``∇²H = diag(cos q, 1)`` — genuinely state
    dependent, so the quadratic fast path must refuse to engage and Newton has
    to iterate.
    """
    J = np.array([[0.0, 1.0], [-1.0, 0.0]])
    R = np.array([[0.0, 0.0], [0.0, c]])
    G = np.array([[0.0], [1.0]])

    phs = PortHamiltonianSystem(
        H=lambda x: float((1.0 - np.cos(x[0])) + 0.5 * x[1] ** 2),
        J=lambda x: J,
        R=lambda x: R,
        g=lambda x: G,
        n_states=2,
        n_inputs=1,
        grad_H=lambda x: np.array([np.sin(x[0]), x[1]]),
    )
    phs.hess_H = lambda x: np.diag([np.cos(x[0]), 1.0])
    return phs


def stiffening_spring(c: float = 0.05):
    """Nonlinear spring ``H = ½q² + ¼q⁴ + ½p²`` with *state-dependent* damping.

    ``R(x) = diag(0, c(1 + q²))`` varies with the state, so the constant-
    structure heuristic must reject this model outright.
    """
    J = np.array([[0.0, 1.0], [-1.0, 0.0]])
    G = np.array([[0.0], [1.0]])

    phs = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x[0] ** 2 + 0.25 * x[0] ** 4 + 0.5 * x[1] ** 2),
        J=lambda x: J,
        R=lambda x: np.array([[0.0, 0.0], [0.0, c * (1.0 + x[0] ** 2)]]),
        g=lambda x: G,
        n_states=2,
        n_inputs=1,
        grad_H=lambda x: np.array([x[0] + x[0] ** 3, x[1]]),
    )
    phs.hess_H = lambda x: np.diag([1.0 + 3.0 * x[0] ** 2, 1.0])
    return phs


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def energies(phs, xs):
    return np.array([phs.energy(x) for x in xs])


def worst_energy_gain(phs, xs) -> float:
    """Largest step-to-step *increase* in H, relative to H(x0).

    Negative means the energy never went up. This is the number the package's
    structural guarantee is about.
    """
    H = energies(phs, xs)
    return float(np.max(np.diff(H)) / H[0])


def midpoint_residuals(phs, res, u):
    """‖x_{n+1} − x_n − Δt f(x_mid, u_mid, t_mid)‖_∞ over the whole trajectory."""
    t, xs = res["t"], res["x"]
    out = []
    for n in range(len(t) - 1):
        dt = float(t[n + 1] - t[n])
        x_mid = 0.5 * (xs[n] + xs[n + 1])
        u_mid = 0.5 * (u[n] + u[n + 1])
        t_mid = 0.5 * (t[n] + t[n + 1])
        f = np.asarray(phs.dynamics(x_mid, u_mid, t_mid), dtype=float)
        out.append(np.max(np.abs(xs[n + 1] - xs[n] - dt * f)))
    return float(np.max(out))


@pytest.fixture
def grid():
    t = np.linspace(0.0, 100.0, 4001)
    return t, np.zeros((t.size, 1))


# ----------------------------------------------------------------------
# 1. the structural guarantee, on every path
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "expected_path"),
    [
        ("auto", "linear"),
        ("linear", "linear"),
        ("newton", "newton"),
        ("fsolve", "fsolve"),
    ],
)
def test_energy_bound_still_holds(method, expected_path, grid):
    """No solver path may let a passive system gain energy.

    The bound is 1e-9 of H(0) per step, which is ~1e7 times looser than what the
    integrator actually achieves — it is a guard against a path silently losing
    the structure, not a tight accuracy check.
    """
    t, u = grid
    phs = damped_oscillator()
    x0 = np.array([1.0, 0.0])

    res = integrate_phs(phs, x0, t, u, method=method)

    assert res["success"], res["message"]
    # Pin the path: without this the parametrisation could collapse to one path
    # and the test would still pass.
    assert res["method"] == expected_path
    assert worst_energy_gain(phs, res["x"]) <= 1e-9
    # And the system really did dissipate, i.e. this is not a trivial pass on a
    # trajectory that never moved.
    H = energies(phs, res["x"])
    assert H[-1] < 1e-3 * H[0]


def test_energy_bound_holds_for_nonlinear_dissipation(grid):
    """Same guarantee with a state-dependent R, where the Jacobian is inexact.

    ``(J − R(x))·∇²H(x)`` drops the ∂R/∂x term, so Newton runs on an approximate
    Jacobian here. That must cost iterations, not structure.
    """
    t, u = grid
    phs = stiffening_spring()
    x0 = np.array([1.5, 0.0])

    res = integrate_phs(phs, x0, t, u)

    assert res["success"], res["message"]
    assert res["method"] == "newton"
    assert worst_energy_gain(phs, res["x"]) <= 1e-9


# ----------------------------------------------------------------------
# 2 & 3. the rewrite must not change answers
# ----------------------------------------------------------------------


def test_newton_matches_fsolve(grid):
    """Newton on the analytic Jacobian reproduces the old fsolve trajectory."""
    t, u = grid
    phs = damped_oscillator()
    x0 = np.array([1.0, 0.0])

    newton = integrate_phs(phs, x0, t, u, method="newton")
    reference = integrate_phs(phs, x0, t, u, method="fsolve")

    assert newton["success"] and reference["success"]
    assert newton["method"] == "newton"
    assert reference["method"] == "fsolve"
    assert np.max(np.abs(newton["x"] - reference["x"])) <= 1e-10


def test_newton_matches_fsolve_for_nonlinear_system():
    """...and on a system where the step actually needs several iterations.

    Over a shorter horizon than the linear case: neither solver is exact, both
    stop at a residual of ``newton_tol``, and on a nonlinear oscillator those
    per-step differences accumulate — 7e-12 at t=40, 1.0e-10 at t=100. That is
    the tolerance talking, not a discrepancy between the methods (tightening
    ``newton_tol`` to 1e-13 pulls t=100 back to 9.6e-12).
    """
    t = np.linspace(0.0, 40.0, 1601)
    u = np.zeros((t.size, 1))
    phs = nonlinear_pendulum()
    x0 = np.array([2.0, 0.0])

    newton = integrate_phs(phs, x0, t, u, method="newton")
    reference = integrate_phs(phs, x0, t, u, method="fsolve")

    assert newton["success"] and reference["success"]
    assert newton["n_newton_iter"] > len(t) - 1  # more than one iteration per step
    assert np.max(np.abs(newton["x"] - reference["x"])) <= 1e-10


def test_quadratic_fast_path_matches_general_newton(grid):
    """The closed form and the general Newton solve are the same integrator."""
    t, u = grid
    phs = damped_oscillator()
    x0 = np.array([1.0, 0.0])

    fast = integrate_phs(phs, x0, t, u, method="linear")
    general = integrate_phs(phs, x0, t, u, method="newton")

    assert fast["method"] == "linear"
    assert fast["n_feval"] == 0  # the closed form never touches the vector field
    assert general["n_newton_iter"] == len(t) - 1  # one Newton step per step
    assert np.max(np.abs(fast["x"] - general["x"])) <= 1e-12


def test_fast_path_handles_a_driven_system():
    """With u ≠ 0 the closed form must still agree with the general path.

    The input enters the closed form through a pre-solved matrix, which is where
    a sign or a factor of ½ on ``u_mid`` would hide.
    """
    t = np.linspace(0.0, 40.0, 2001)
    u = (0.6 * np.sin(0.7 * t)).reshape(-1, 1)
    phs = damped_oscillator()
    x0 = np.array([0.3, -0.2])

    fast = integrate_phs(phs, x0, t, u, method="linear")
    general = integrate_phs(phs, x0, t, u, method="newton")
    reference = integrate_phs(phs, x0, t, u, method="fsolve")

    assert np.max(np.abs(fast["x"] - general["x"])) <= 1e-12
    assert np.max(np.abs(fast["x"] - reference["x"])) <= 1e-10
    assert np.max(np.abs(fast["x"])) > 0.5  # the drive did something


def test_fast_path_handles_a_nonuniform_grid():
    """A grid that is genuinely non-uniform must refactorise, not reuse."""
    rng = np.random.default_rng(7)
    dts = 0.01 + 0.02 * rng.random(600)
    t = np.concatenate([[0.0], np.cumsum(dts)])
    u = np.zeros((t.size, 1))
    phs = damped_oscillator()
    x0 = np.array([1.0, 0.0])

    fast = integrate_phs(phs, x0, t, u, method="linear")
    general = integrate_phs(phs, x0, t, u, method="newton")

    assert np.max(np.abs(fast["x"] - general["x"])) <= 1e-12
    assert worst_energy_gain(phs, fast["x"]) <= 1e-9


# ----------------------------------------------------------------------
# 4. the fast path must know when it does not apply
# ----------------------------------------------------------------------


def test_nonlinear_H_still_converges(grid):
    """A genuinely nonlinear H falls back to Newton and still hits tolerance."""
    t, u = grid
    phs = nonlinear_pendulum()
    x0 = np.array([2.0, 0.0])

    res = integrate_phs(phs, x0, t, u)

    # The fast path must NOT engage: ∇²H = diag(cos q, 1) is not constant.
    assert res["method"] == "newton"
    assert res["success"], res["message"]
    # Every step really solved the implicit midpoint equation.
    assert midpoint_residuals(phs, res, u) <= 1e-10
    # ...and the pendulum swung, so this is not a trivial trajectory.
    assert np.ptp(res["x"][:, 0]) > 1.0

    # Asking for the closed form on this model is refused outright, rather than
    # silently answering with a linearisation.
    with pytest.raises(ValueError, match="affine"):
        integrate_phs(phs, x0, t, u, method="linear")


def test_state_dependent_structure_disables_the_fast_path(grid):
    """Constant ∇²H is not enough — J, R, g must be constant too."""
    t, u = grid
    phs = stiffening_spring()
    x0 = np.array([1.2, 0.0])

    res = integrate_phs(phs, x0, t, u)
    assert res["method"] == "newton"
    assert midpoint_residuals(phs, res, u) <= 1e-10

    with pytest.raises(ValueError, match="affine"):
        integrate_phs(phs, x0, t, u, method="linear")


def test_constant_structure_false_overrides_the_heuristic(grid):
    """The user can veto the detection; the answer must not change."""
    t, u = grid
    phs = damped_oscillator()
    x0 = np.array([1.0, 0.0])

    detected = integrate_phs(phs, x0, t, u)
    vetoed = integrate_phs(phs, x0, t, u, constant_structure=False)

    assert detected["method"] == "linear"
    assert vetoed["method"] == "newton"
    assert np.max(np.abs(detected["x"] - vetoed["x"])) <= 1e-12


def test_model_without_hessian_uses_finite_differences(grid):
    """A plain PHS with no ``hess_H`` still integrates, via a FD Jacobian."""
    t, u = grid
    phs = damped_oscillator()
    del phs.hess_H  # a model that exposes nothing beyond `dynamics`
    x0 = np.array([1.0, 0.0])

    res = integrate_phs(phs, x0, t, u)
    reference = integrate_phs(phs, x0, t, u, method="fsolve")

    assert res["method"] == "newton"
    assert res["success"], res["message"]
    assert np.max(np.abs(res["x"] - reference["x"])) <= 1e-10


# ----------------------------------------------------------------------
# 5. failure must be visible
# ----------------------------------------------------------------------


def test_non_convergence_is_reported_not_swallowed():
    """A step that cannot converge in one iteration must not pass silently."""
    phs = nonlinear_pendulum()
    x0 = np.array([3.0, 0.0])
    t = np.linspace(0.0, 20.0, 21)  # Δt = 1.0: far too coarse for one iteration
    u = np.zeros((t.size, 1))

    # Sanity: the problem itself is solvable — the failure below is about the
    # iteration budget, not about an impossible system.
    ok = integrate_phs(phs, x0, t, u, method="newton", max_iter=50)
    assert ok["success"], ok["message"]

    starved = integrate_phs(phs, x0, t, u, method="newton", max_iter=1)
    assert starved["success"] is False
    assert "converge" in starved["message"]
    # The failure is flagged, and the unsolved tail is not passed off as a
    # trajectory: everything after the failed step is frozen, and the caller
    # sees success=False.
    assert midpoint_residuals(phs, starved, u) > 1e-10

    # The same failure can be made fatal instead of advisory.
    with pytest.raises(IntegratorConvergenceError, match="converge"):
        integrate_phs(phs, x0, t, u, method="newton", max_iter=1, raise_on_failure=True)


def test_auto_falls_back_to_fsolve_but_still_reports_failure():
    """``auto`` may rescue a step with fsolve; it may not hide a dead one."""
    phs = nonlinear_pendulum()
    x0 = np.array([3.0, 0.0])
    t = np.linspace(0.0, 20.0, 21)
    u = np.zeros((t.size, 1))

    starved = integrate_phs(phs, x0, t, u, method="auto", max_iter=1)
    assert starved["success"] is False
    assert "fsolve" in starved["message"]

    # With a workable budget, auto solves it and agrees with the strict path.
    fine = integrate_phs(phs, x0, t, u, method="auto", max_iter=50)
    strict = integrate_phs(phs, x0, t, u, method="newton", max_iter=50)
    assert fine["success"]
    assert np.max(np.abs(fine["x"] - strict["x"])) <= 1e-12


def test_newton_step_reports_its_own_non_convergence():
    """The solver primitive reports failure through its result, not by guessing."""
    # x**2 + 1 = 0 has no real root; Newton must give up and say so.
    res = newton_step(
        lambda x: x**2 + 1.0, np.array([1.0]), lambda x: np.diag(2 * x), max_iter=20
    )
    assert res.converged is False
    assert res.residual_norm > 0.1
    assert res.message


def test_newton_step_survives_a_domain_boundary():
    """A model undefined at the full Newton point damps the step, not the run."""

    def residual(x):
        if x[0] < 0.0:
            raise ValueError("undefined for negative x")
        return np.array([np.sqrt(x[0]) - 2.0])

    res = newton_step(
        residual,
        np.array([0.05]),  # a full Newton step from here lands far below zero
        lambda x: np.array([[0.5 / np.sqrt(x[0])]]),
        max_iter=60,
    )
    assert res.converged, res.message
    assert abs(res.x[0] - 4.0) < 1e-9


# ----------------------------------------------------------------------
# 6. why any of this is worth the trouble
# ----------------------------------------------------------------------


def test_structure_preservation_beats_rk45():
    """RK45 injects energy into a passive system; implicit midpoint does not.

    This is the comparison the package exists for, and it is why the per-step
    solve is worth optimising rather than dropping.
    """
    phs = damped_oscillator(c=0.02)
    x0 = np.array([1.0, 0.0])
    t = np.linspace(0.0, 200.0, 4001)
    u = np.zeros((t.size, 1))

    def dynamics(tv, x, uv):
        return phs.dynamics(x, uv, tv)

    rk45 = integrate_with_inputs(dynamics, x0, t, u, method="RK45")
    assert rk45["success"]
    rk45_gain = worst_energy_gain(phs, rk45["x"])
    assert rk45_gain > 1e-5  # measured ~1.1e-4 of H(0) on a single step

    for method in ("auto", "newton", "fsolve"):
        res = integrate_phs(phs, x0, t, u, method=method)
        assert res["success"], res["message"]
        gain = worst_energy_gain(phs, res["x"])
        assert gain <= 1e-9
        assert gain < rk45_gain / 1e4


# ----------------------------------------------------------------------
# backward compatibility of the public surface
# ----------------------------------------------------------------------


def test_implicit_midpoint_keeps_its_positional_signature():
    """Existing callers pass a bare vector field and positional tolerances."""
    phs = damped_oscillator()
    t = np.linspace(0.0, 10.0, 501)
    u = np.zeros((t.size, 1))

    res = implicit_midpoint(
        lambda tv, x, uv: phs.dynamics(x, uv, tv),
        np.array([1.0, 0.0]),
        t,
        u,
        1e-12,  # newton_tol, positionally
        100,  # max_iter, positionally
    )

    assert set(res) >= {"t", "x", "success", "message"}
    assert res["success"]
    assert res["x"].shape == (t.size, 2)
    assert worst_energy_gain(phs, res["x"]) <= 1e-9


def test_implicit_midpoint_accepts_one_dimensional_inputs():
    phs = damped_oscillator()
    t = np.linspace(0.0, 5.0, 251)

    res = implicit_midpoint(
        lambda tv, x, uv: phs.dynamics(x, uv, tv),
        np.array([1.0, 0.0]),
        t,
        np.zeros(t.size),  # 1-D input trajectory
    )
    assert res["success"]


def test_integrate_phs_defaults_to_zero_input():
    phs = damped_oscillator()
    t = np.linspace(0.0, 10.0, 501)

    res = integrate_phs(phs, np.array([1.0, 0.0]), t)
    assert res["success"]
    assert worst_energy_gain(phs, res["x"]) <= 1e-9


@pytest.mark.parametrize(
    ("t_eval", "match"),
    [
        (np.array([0.0]), "at least two points"),
        (np.array([0.0, 1.0, 0.5]), "strictly increasing"),
    ],
)
def test_bad_time_grids_are_rejected(t_eval, match):
    phs = damped_oscillator()
    with pytest.raises(ValueError, match=match):
        integrate_phs(phs, np.array([1.0, 0.0]), t_eval, np.zeros((t_eval.size, 1)))


def test_unknown_method_is_rejected():
    phs = damped_oscillator()
    t = np.linspace(0.0, 1.0, 11)
    with pytest.raises(ValueError, match="method must be one of"):
        integrate_phs(phs, np.array([1.0, 0.0]), t, method="hybrd")
