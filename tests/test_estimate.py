"""Tests for :mod:`otwin.estimate` — the ISO 13374 State Detection block.

Every test here is written so that it can fail. Where a test asserts that a
constrained or corrected estimator behaves well, it also asserts that the
*unconstrained* estimator on the same data behaves badly. A test that only
checks the good half passes just as happily against a stub that returns the
prior, and tells you nothing.
"""

import math

import numpy as np
import pytest

from otwin.estimate import (
    EnergyConsistentObserver,
    ExtendedKalmanFilter,
    FilterResult,
    KalmanFilter,
    MovingHorizonEstimator,
)
from otwin.model.phs import PortHamiltonianSystem

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


class LinearModel:
    """Continuous linear twin ``ẋ = A x + B u``, ``y = C x``, duck-typed."""

    def __init__(self, A, B, C):
        self.A = np.asarray(A, dtype=float)
        self.B = np.asarray(B, dtype=float)
        self.C = np.asarray(C, dtype=float)
        self.n_states = self.A.shape[0]
        self.n_inputs = self.B.shape[1]

    def rhs(self, x, u, t):
        out = self.A @ x
        if self.B.shape[1]:
            out = out + self.B @ np.asarray(u, dtype=float).reshape(self.B.shape[1])
        return out

    def observe(self, x, u=None, t=0.0):
        return self.C @ x

    def jac_f(self, x, u, t):
        return self.A

    def jac_h(self, x, u, t):
        return self.C


def rk4_discretise(A, B, dt):
    """RK4 transition pair for a linear system, derived independently.

    Applying classical RK4 to ``ẋ = Ax + Bu`` with a zero-order-hold input and
    ``M = A·dt`` gives, by expanding the four stages by hand,

        ``A_d = Σ_{k=0}^{4} M^k / k!``      (the truncated matrix exponential)
        ``B_d = dt · Σ_{k=0}^{3} M^k / (k+1)!``

    This is written out here rather than taken from the library so that the
    EKF/KF equivalence test compares against an independent derivation.
    """
    M = np.asarray(A, dtype=float) * dt
    A_d = sum(np.linalg.matrix_power(M, k) / math.factorial(k) for k in range(5))
    B_d = (
        dt
        * sum(np.linalg.matrix_power(M, k) / math.factorial(k + 1) for k in range(4))
        @ np.asarray(B, dtype=float)
    )
    return A_d, B_d


def damped_oscillator_phs(m=1.0, k=4.0, c=0.3):
    """Mass-spring-damper as a port-Hamiltonian system.

    State ``x = (q, p)``, energy ``H = ½(k q² + p²/m)``, force input, velocity
    output — so the output is the port variable collocated with the input and
    ``yᵀu`` is a genuine mechanical power.
    """
    return PortHamiltonianSystem(
        H=lambda x: 0.5 * (k * x[0] ** 2 + x[1] ** 2 / m),
        J=lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),
        R=lambda x: np.array([[0.0, 0.0], [0.0, c]]),
        g=lambda x: np.array([[0.0], [1.0]]),
        n_states=2,
        n_inputs=1,
        grad_H=lambda x: np.array([k * x[0], x[1] / m]),
    )


def rc_circuit_phs(C=1.0, R_elec=2.0):
    """Charging RC circuit as a port-Hamiltonian system.

    State is charge ``q``, energy ``H = q²/2C``, input is a current source and
    output is the capacitor voltage ``q/C`` — collocated, so ``yᵀu`` is
    electrical power in watts. With ``q > 0`` and a positive current the port
    power is strictly positive, which is what gives the correction a non-trivial
    energy budget.

    ``R_elec`` is the electrical resistance in ohms; the PHS dissipation matrix
    is ``1/R_elec``, and it is spelled out here rather than called ``R`` because
    ``R`` in this codebase is that matrix, not the resistance.
    """
    return PortHamiltonianSystem(
        H=lambda x: 0.5 * x[0] ** 2 / C,
        J=lambda x: np.zeros((1, 1)),
        R=lambda x: np.array([[1.0 / R_elec]]),
        g=lambda x: np.array([[1.0]]),
        n_states=1,
        n_inputs=1,
        grad_H=lambda x: np.array([x[0] / C]),
    )


def simulate(model, x0, us, ts, rng=None, process_std=0.0):
    """Ground-truth trajectory via RK4, optionally with process noise."""
    from otwin.estimate.kalman import rk4_step

    xs = np.zeros((len(ts), len(x0)))
    xs[0] = x0
    for k in range(1, len(ts)):
        xs[k] = rk4_step(
            model.rhs, xs[k - 1], us[k - 1], float(ts[k - 1]), float(ts[k] - ts[k - 1])
        )
        if process_std and rng is not None:
            xs[k] = xs[k] + rng.normal(0.0, process_std, size=xs.shape[1])
    return xs


# ----------------------------------------------------------------------
# 1. acceptance gate
# ----------------------------------------------------------------------


def test_ekf_matches_closed_form_kalman_on_linear_system():
    """On a linear system the EKF must *be* the Kalman filter.

    This is the acceptance gate for the module. The EKF's only difference from
    the exact filter is the linearisation; remove the nonlinearity and any
    residual disagreement is a bug in the discretisation, the gain, or the
    covariance recursion — none of which a nonlinear test would isolate.
    """
    rng = np.random.default_rng(0)
    A = np.array([[0.0, 1.0], [-4.0, -0.3]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0]])
    dt = 0.05
    n_steps = 120

    model = LinearModel(A, B, C)
    Q = np.diag([1e-5, 1e-4])
    R_meas = np.array([[4e-2]])
    P0 = np.diag([0.5, 0.5])
    x0 = np.array([0.2, -0.1])

    ts = np.arange(n_steps) * dt
    us = rng.normal(0.0, 0.5, size=(n_steps, 1))
    x_true = simulate(model, np.array([1.0, 0.0]), us, ts)
    ys = x_true @ C.T + rng.normal(0.0, 0.2, size=(n_steps, 1))

    ekf = ExtendedKalmanFilter(
        model, Q, R_meas, P0, x0=x0, jac_f=model.jac_f, jac_h=model.jac_h
    )
    res_ekf = ekf.filter(ys, us, ts)

    A_d, B_d = rk4_discretise(A, B, dt)
    kf = KalmanFilter(A_d, B_d, C, Q, R_meas, P0, x0=x0)
    res_kf = kf.filter(ys, us)

    assert np.max(np.abs(res_ekf.x - res_kf.x)) < 1e-10
    assert np.max(np.abs(res_ekf.P - res_kf.P)) < 1e-10
    assert np.max(np.abs(res_ekf.innovation - res_kf.innovation)) < 1e-10
    assert np.max(np.abs(res_ekf.nis - res_kf.nis)) < 1e-10

    # Same claim with numerical Jacobians, at the accuracy central differences
    # can actually deliver. If this drifts, the fallback path is broken even
    # though the analytic path is fine.
    ekf_num = ExtendedKalmanFilter(model, Q, R_meas, P0, x0=x0)
    res_num = ekf_num.filter(ys, us, ts)
    assert np.max(np.abs(res_num.x - res_kf.x)) < 1e-6


# ----------------------------------------------------------------------
# 2. the filter must actually help
# ----------------------------------------------------------------------


def test_ekf_reduces_rmse_versus_open_loop():
    """Correcting on measurements must beat simulating from a bad guess."""
    rng = np.random.default_rng(7)
    phs = damped_oscillator_phs()
    dt = 0.02
    n_steps = 400
    ts = np.arange(n_steps) * dt
    us = np.zeros((n_steps, 1))

    x_true = simulate(phs, np.array([1.0, 0.5]), us, ts, rng=rng, process_std=0.01)
    meas_std = 0.1
    ys = np.array([phs.observe(x) for x in x_true]) + rng.normal(
        0.0, meas_std, size=(n_steps, 1)
    )

    x0_bad = np.array([-0.6, 1.4])  # badly wrong initial condition
    ekf = ExtendedKalmanFilter(
        phs,
        Q=np.diag([1e-4, 1e-4]),
        R_meas=np.array([[meas_std**2]]),
        P0=np.diag([2.0, 2.0]),
        x0=x0_bad,
    )
    res = ekf.filter(ys, us, ts)

    x_open = simulate(phs, x0_bad, us, ts)

    rmse_ekf = float(np.sqrt(np.mean((res.x - x_true) ** 2)))
    rmse_open = float(np.sqrt(np.mean((x_open - x_true) ** 2)))

    assert rmse_ekf < 0.5 * rmse_open, (rmse_ekf, rmse_open)
    # Steady-state, not just transient: the last half must also be good.
    half = n_steps // 2
    rmse_tail = float(np.sqrt(np.mean((res.x[half:] - x_true[half:]) ** 2)))
    assert rmse_tail < 0.1
    # A well-tuned filter's NIS averages the measurement dimension.
    assert 0.2 < res.nis[half:].mean() < 5.0


# ----------------------------------------------------------------------
# 3. constraints
# ----------------------------------------------------------------------


def test_mhe_respects_state_bounds():
    """MHE keeps a state of charge inside [0, 1]; an EKF does not.

    Both halves matter. The bound-respecting half alone would pass against an
    estimator that returned the prior forever.
    """
    rng = np.random.default_rng(3)
    A = np.array([[-0.05]])
    B = np.zeros((1, 0))
    C = np.array([[1.0]])
    model = LinearModel(A, B, C)

    dt = 0.1
    n_steps = 40
    ts = np.arange(n_steps) * dt
    # A biased sensor: true SoC sits near 0.95, the sensor reports ~1.2.
    ys = 1.2 + rng.normal(0.0, 0.02, size=(n_steps, 1))

    Q = np.array([[1e-4]])
    R_meas = np.array([[4e-4]])
    P0 = np.array([[1e-2]])
    x0 = np.array([0.95])

    mhe = MovingHorizonEstimator(
        model,
        Q,
        R_meas,
        P0,
        x0=x0,
        horizon=5,
        bounds=[(0.0, 1.0)],
        jac_f=model.jac_f,
        jac_h=model.jac_h,
    )
    res_mhe = mhe.filter(ys, None, ts)

    assert np.all(res_mhe.x >= 0.0 - 1e-12)
    assert np.all(res_mhe.x <= 1.0 + 1e-12)
    # It must also be pulled up against the bound, not sitting at the prior.
    assert res_mhe.x.max() > 0.99

    ekf = ExtendedKalmanFilter(
        model, Q, R_meas, P0, x0=x0, jac_f=model.jac_f, jac_h=model.jac_h
    )
    res_ekf = ekf.filter(ys, None, ts)

    # Teeth: the unconstrained filter really does report an impossible state.
    assert res_ekf.x.max() > 1.0 + 1e-3, res_ekf.x.max()


# ----------------------------------------------------------------------
# 4. the novel piece
# ----------------------------------------------------------------------


def _uphill_measurements(phs, x_true, rng, meas_std):
    """Velocity measurements exaggerated away from zero.

    Multiplying the true velocity by a factor > 1 and adding noise makes the
    innovation point outwards along ``p``, which is exactly the direction that
    raises ``H``. This is the adversarial case the observer exists for.
    """
    y_clean = np.array([phs.observe(x) for x in x_true])
    return 1.8 * y_clean + rng.normal(0.0, meas_std, size=y_clean.shape)


def test_energy_consistent_observer_never_creates_energy():
    """Autonomous PHS: the observer's H is non-increasing, the EKF's is not."""
    rng = np.random.default_rng(11)
    phs = damped_oscillator_phs(c=0.05)
    dt = 0.01
    n_steps = 300
    ts = np.arange(n_steps) * dt
    us = np.zeros((n_steps, 1))  # autonomous: no energy may enter

    x_true = simulate(phs, np.array([1.0, 0.0]), us, ts)
    ys = _uphill_measurements(phs, x_true, rng, meas_std=0.3)

    kwargs = {
        "Q": np.diag([1e-5, 1e-5]),
        "R_meas": np.array([[0.09]]),
        "P0": np.diag([0.2, 0.2]),
        "x0": np.array([1.0, 0.0]),
    }

    obs = EnergyConsistentObserver(phs, **kwargs)
    res = obs.filter(ys, us, ts)

    # The guarantee, at the trajectory level. The tolerance covers RK4's O(dt⁵)
    # error on the prediction half-step, not the correction, which is exact.
    assert np.all(np.diff(res.energy) <= 1e-9), np.max(np.diff(res.energy))
    assert res.energy[-1] < res.energy[0]
    assert res.alpha.min() < 1.0  # the clamp was genuinely exercised
    assert np.all(res.alpha >= 0.0) and np.all(res.alpha <= 1.0)
    # The diagnostic must report a real quantity, not a placeholder zero.
    assert res.energy_injected > 0.0
    assert obs.energy_injected == pytest.approx(res.energy_injected)
    assert 0.0 < res.clamp_rate <= 1.0

    # Teeth: the plain EKF on identical data manufactures energy.
    ekf = ExtendedKalmanFilter(phs, **kwargs)
    res_ekf = ekf.filter(ys, us, ts)
    H_ekf = np.array([phs.energy(x) for x in res_ekf.x])
    assert np.max(np.diff(H_ekf)) > 1e-6, np.max(np.diff(H_ekf))


def test_alpha_is_one_when_correction_is_benign():
    """A well-tuned filter on a forced system must never be clamped.

    If this fails the observer is not a strict refinement of the EKF — it is
    quietly degrading normal operation, which is worse than the problem it was
    written to solve.

    The system is a charging RC circuit, driven by a constant current source.
    That choice is deliberate: the port power ``yᵀu = (q/C)·i`` is strictly
    positive throughout, so there is a real energy budget for the correction to
    sit inside, and this test is the only one that exercises the ``∫yᵀu dt``
    term at all. On an *autonomous* system the budget is zero by definition and
    a healthy filter's noise-driven corrections are clamped roughly half the
    time — documented behaviour, not a bug, and covered in the
    ``EnergyConsistentObserver`` docstring.
    """
    rng = np.random.default_rng(5)
    phs = rc_circuit_phs()
    dt = 0.01
    n_steps = 200
    ts = np.arange(n_steps) * dt
    us = np.ones((n_steps, 1))  # 1 A constant current into the capacitor

    x_true = simulate(phs, np.array([0.5]), us, ts)
    meas_std = 0.01
    ys = np.array([phs.observe(x) for x in x_true]) + rng.normal(
        0.0, meas_std, size=(n_steps, 1)
    )
    assert np.all(x_true > 0.0)  # so that yᵀu > 0 at every step

    kwargs = {
        "Q": np.array([[1e-8]]),
        "R_meas": np.array([[meas_std**2]]),
        "P0": np.array([[1e-6]]),
        "x0": np.array([0.5]),
    }
    obs = EnergyConsistentObserver(phs, **kwargs)
    res = obs.filter(ys, us, ts)

    assert np.all(res.alpha == 1.0), res.alpha.min()
    assert res.clamp_rate == 0.0
    assert res.energy_injected == 0.0

    # And in that regime it is bit-for-bit the EKF it wraps: the observer is a
    # refinement, not a different estimator.
    res_ekf = ExtendedKalmanFilter(phs, **kwargs).filter(ys, us, ts)
    assert np.max(np.abs(res.x - res_ekf.x)) < 1e-14
    assert np.max(np.abs(res.P - res_ekf.P)) < 1e-14

    # Teeth: the clamp is armed, not disabled. Replay the same filter against
    # measurements that demand a jump far larger than the ports can pay for and
    # it must fire.
    obs2 = EnergyConsistentObserver(phs, **kwargs)
    res2 = obs2.filter(ys + 5.0, us, ts)
    assert res2.alpha.min() < 1.0


# ----------------------------------------------------------------------
# 6. contract
# ----------------------------------------------------------------------


def test_filter_result_shapes():
    """Shape and dtype contract, identical across every estimator."""
    rng = np.random.default_rng(21)
    A = np.array([[0.0, 1.0], [-2.0, -0.4]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0], [0.0, 1.0]])
    model = LinearModel(A, B, C)

    n_steps, n, m = 25, 2, 2
    dt = 0.05
    ts = np.arange(n_steps) * dt
    us = rng.normal(0.0, 0.1, size=(n_steps, 1))
    ys = rng.normal(0.0, 0.1, size=(n_steps, m))

    Q = 1e-4 * np.eye(n)
    R_meas = 1e-2 * np.eye(m)
    P0 = np.eye(n)
    x0 = np.zeros(n)

    A_d, B_d = rk4_discretise(A, B, dt)
    results = {
        "ekf": ExtendedKalmanFilter(model, Q, R_meas, P0, x0=x0).filter(ys, us, ts),
        "kf": KalmanFilter(A_d, B_d, C, Q, R_meas, P0, x0=x0).filter(ys, us),
        "mhe": MovingHorizonEstimator(
            model, Q, R_meas, P0, x0=x0, horizon=3, bounds=[(-5.0, 5.0)] * n
        ).filter(ys, us, ts),
    }

    for name, res in results.items():
        assert isinstance(res, FilterResult), name
        assert res.x.shape == (n_steps, n), name
        assert res.P.shape == (n_steps, n, n), name
        assert res.innovation.shape == (n_steps, m), name
        assert res.nis.shape == (n_steps,), name
        assert res.t.shape == (n_steps,), name
        assert res.n_steps == n_steps, name
        for arr in (res.x, res.P, res.innovation, res.nis, res.t):
            assert arr.dtype == np.float64, name
            assert np.all(np.isfinite(arr)), name
        # Covariances stay symmetric and positive semidefinite.
        for k in range(n_steps):
            assert np.allclose(res.P[k], res.P[k].T, atol=1e-12), (name, k)
            assert np.min(np.linalg.eigvalsh(res.P[k])) > -1e-12, (name, k)

    phs = damped_oscillator_phs()
    eres = EnergyConsistentObserver(phs, Q, np.array([[1e-2]]), P0, x0=x0).filter(
        rng.normal(0.0, 0.1, size=(n_steps, 1)), us, ts
    )
    assert isinstance(eres, FilterResult)
    assert eres.x.shape == (n_steps, n)
    assert eres.P.shape == (n_steps, n, n)
    assert eres.innovation.shape == (n_steps, 1)
    assert eres.nis.shape == (n_steps,)
    assert eres.alpha.shape == (n_steps,)
    assert eres.energy.shape == (n_steps,)
    assert eres.energy_created.shape == (n_steps,)
    assert eres.alpha.dtype == np.float64
    assert eres.energy.dtype == np.float64
    assert isinstance(eres.energy_injected, float)
