"""Tests for the port-Hamiltonian machinery itself.

Deliberately self-contained: the models here are defined inline rather than
imported from ``otwin-systems``, because ``otwin-systems`` depends on this
package. Tests of the *model library* live there; these test the *machinery*.

The distinction matters beyond dependency hygiene. A failure here means the
PHS class or an integrator is broken. A failure in otwin-systems means one
physical model is wrong. Mixing them makes both harder to diagnose.
"""

from __future__ import annotations

import numpy as np
import pytest

from otwin.model import (
    PortHamiltonianSystem,
    check_psd,
    check_skew_symmetric,
    integrate_phs,
    integrate_with_inputs,
    numerical_gradient,
)

# --------------------------------------------------------------------------
# Inline models
# --------------------------------------------------------------------------


def damped_oscillator(m=1.0, k=2.0, c=0.3) -> PortHamiltonianSystem:
    """q, p with a spring and a damper. J is the canonical symplectic form."""
    return PortHamiltonianSystem(
        H=lambda x: float(0.5 * k * x[0] ** 2 + 0.5 * x[1] ** 2 / m),
        grad_H=lambda x: np.array([k * x[0], x[1] / m]),
        J=lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),
        R=lambda x: np.array([[0.0, 0.0], [0.0, c]]),
        g=lambda x: np.array([[0.0], [1.0]]),
        n_states=2,
        n_inputs=1,
    )


def pure_dissipator(r=0.5) -> PortHamiltonianSystem:
    """The simplest passive system: one state, no interconnection."""
    return PortHamiltonianSystem(
        H=lambda x: float(0.5 * x[0] ** 2),
        grad_H=lambda x: np.array([x[0]]),
        J=lambda x: np.zeros((1, 1)),
        R=lambda x: np.array([[r]]),
        g=lambda x: np.array([[1.0]]),
        n_states=1,
        n_inputs=1,
    )


def lossless(k=1.0) -> PortHamiltonianSystem:
    """R = 0: energy must be conserved exactly, not merely non-increasing."""
    return PortHamiltonianSystem(
        H=lambda x: float(0.5 * k * x[0] ** 2 + 0.5 * x[1] ** 2),
        grad_H=lambda x: np.array([k * x[0], x[1]]),
        J=lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),
        R=lambda x: np.zeros((2, 2)),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
    )


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def test_satisfies_the_otwin_base_protocol():
    """This is the whole reason the package is splittable.

    A tool in another package must be able to accept this model without
    importing otwin-phs, and without this class inheriting from anything.
    """
    from otwin.interfaces import HasEnergyGradient, PortHamiltonianModel, TwinModel

    sys = damped_oscillator()
    assert isinstance(sys, TwinModel)
    assert isinstance(sys, PortHamiltonianModel)
    assert isinstance(sys, HasEnergyGradient)


def test_rhs_is_the_contract_name_for_dynamics():
    sys = damped_oscillator()
    x, u = np.array([1.0, 0.5]), np.array([0.2])
    assert np.allclose(sys.rhs(x, u, 0.0), sys.dynamics(x, u))


def test_observe_is_the_contract_name_for_output():
    sys = damped_oscillator()
    x = np.array([1.0, 0.5])
    assert np.allclose(sys.observe(x, np.array([0.0])), sys.output(x))


def test_observe_ignores_u_as_documented():
    """y = gᵀ∇H has no u term; the argument exists only to match the protocol."""
    sys = damped_oscillator()
    x = np.array([1.0, 0.5])
    assert np.allclose(sys.observe(x, np.array([0.0])), sys.observe(x, np.array([99.0])))


# --------------------------------------------------------------------------
# The structural guarantees
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model", [damped_oscillator(), pure_dissipator(), lossless()])
@pytest.mark.parametrize("scale", [0.0, 0.1, 1.0, 10.0])
def test_J_is_skew_and_R_is_psd_everywhere_tested(model, scale):
    x = scale * np.ones(model.n_states)
    assert check_skew_symmetric(model.J(x))[0]
    assert check_psd(model.R(x))[0]


@pytest.mark.parametrize("scale", [0.1, 1.0, 5.0])
def test_power_balance_bounds_energy_rate(scale):
    """dH/dt = -∇Hᵀ R ∇H + yᵀu <= yᵀu, algebraically."""
    sys = damped_oscillator()
    x = scale * np.array([1.0, -0.7])
    u = np.array([0.3])
    pb = sys.power_balance(x, u)
    gh = sys.grad_H(x)
    dissipated = float(gh @ sys.R(x) @ gh)
    supplied = float(sys.output(x) @ u)
    assert dissipated >= -1e-12, "dissipation cannot be negative"
    assert pb["dH_dt"] <= supplied + 1e-9


@pytest.mark.parametrize("scale", [0.1, 1.0, 5.0])
def test_unforced_energy_rate_is_never_positive(scale):
    sys = damped_oscillator()
    x = scale * np.array([1.0, -0.7])
    assert sys.power_balance(x, np.zeros(1))["dH_dt"] <= 1e-12


def test_lossless_system_conserves_energy_exactly():
    """R = 0 is a stronger statement than passivity and must hold as an equality."""
    sys = lossless()
    x = np.array([1.0, 0.5])
    assert abs(sys.power_balance(x, np.zeros(1))["dH_dt"]) < 1e-12


def test_energy_decays_along_an_unforced_trajectory():
    """An ordinary integrator gets the trend right and the guarantee wrong.

    RK45 is accurate but not structure-preserving, so individual steps can add
    a little energy — here about 3e-5 of the initial value. That is invisible
    on a plot and fatal to the claim that energy *cannot* increase. The
    tolerance below is loose on purpose; the strict version is the next test.
    """
    sys = damped_oscillator()
    t = np.linspace(0, 20, 400)
    u = np.zeros((400, 1))
    sol = integrate_with_inputs(
        lambda tt, xx, uu: sys.rhs(xx, uu, tt), np.array([1.0, 0.0]), t, u
    )
    E = np.array([sys.energy(x) for x in sol["x"]])
    assert E[-1] < 0.2 * E[0], (
        "a damped oscillator should actually lose most of its energy"
    )
    assert np.diff(E).max() < 1e-4 * E[0], (
        "RK45 should be nearly, but not exactly, passive"
    )


def test_the_structure_preserving_integrator_is_strictly_better():
    """The reason this package exists.

    `integrate_phs` maintains the energy inequality *discretely*. The
    comparison is the argument for structure preservation: same system, same
    grid, and only one of the two can be relied on at a horizon you have not
    tested.
    """
    sys = damped_oscillator()
    t = np.linspace(0, 20, 400)
    u = np.zeros((400, 1))

    rk = integrate_with_inputs(
        lambda tt, xx, uu: sys.rhs(xx, uu, tt), np.array([1.0, 0.0]), t, u
    )
    E_rk = np.array([sys.energy(x) for x in rk["x"]])

    sp = integrate_phs(sys, np.array([1.0, 0.0]), t, u)
    X_sp = sp["x"] if isinstance(sp, dict) else sp
    E_sp = np.array([sys.energy(x) for x in X_sp])

    worst_rk = float(np.diff(E_rk).max())
    worst_sp = float(np.diff(E_sp).max())

    assert worst_sp <= 1e-9, (
        f"the structure-preserving integrator created {worst_sp:.3e} of energy; "
        f"it is supposed to be unable to"
    )
    assert worst_sp < worst_rk, (
        f"structure preservation should beat RK45 on this metric "
        f"(got {worst_sp:.3e} vs {worst_rk:.3e})"
    )


def test_a_forced_trajectory_may_gain_energy():
    """Passivity bounds the rate, it does not forbid energy entering the port."""
    sys = pure_dissipator()
    t = np.linspace(0, 5, 200)
    u = np.ones((200, 1))
    sol = integrate_with_inputs(
        lambda tt, xx, uu: sys.rhs(xx, uu, tt), np.array([0.0]), t, u
    )
    E = np.array([sys.energy(x) for x in sol["x"]])
    assert E[-1] > E[0]


# --------------------------------------------------------------------------
# Validation of user-supplied structure
# --------------------------------------------------------------------------


def test_check_structure_rejects_a_non_skew_J():
    bad = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x @ x),
        grad_H=lambda x: x,
        J=lambda x: np.array([[0.0, 1.0], [1.0, 0.0]]),  # symmetric, not skew
        R=lambda x: np.zeros((2, 2)),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
    )
    ok, violation = bad.check_structure(np.array([1.0, 1.0]))["J_skew"]
    assert not ok
    assert violation > 0


def test_check_structure_rejects_a_non_psd_R():
    bad = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x @ x),
        grad_H=lambda x: x,
        J=lambda x: np.zeros((2, 2)),
        R=lambda x: np.array([[-1.0, 0.0], [0.0, 1.0]]),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
    )
    ok, min_eig = bad.check_structure(np.array([1.0, 1.0]))["R_psd"]
    assert not ok
    assert min_eig < 0


def test_check_skew_symmetric_and_psd_agree_with_definitions():
    ok, violation = check_skew_symmetric(np.array([[0.0, 2.0], [-2.0, 0.0]]))
    assert ok and violation == pytest.approx(0.0, abs=1e-12)

    ok, violation = check_skew_symmetric(np.array([[1.0, 2.0], [-2.0, 0.0]]))
    assert not ok
    assert violation > 0, "a rejection must report how far off it was"

    assert check_psd(np.diag([0.0, 1.0]))[0], "PSD permits a zero eigenvalue"
    assert not check_psd(np.diag([-1e-6, 1.0]))[0]


# --------------------------------------------------------------------------
# Numerical gradient fallback
# --------------------------------------------------------------------------


def test_numerical_gradient_matches_the_analytic_one():
    sys = damped_oscillator()
    no_analytic = PortHamiltonianSystem(
        H=sys.H, J=sys.J, R=sys.R, g=sys.g, n_states=2, n_inputs=1
    )
    x = np.array([0.7, -1.3])
    assert np.allclose(no_analytic.grad_H(x), sys.grad_H(x), rtol=1e-5, atol=1e-7)


def test_numerical_gradient_of_a_known_function():
    f = lambda x: float(x[0] ** 2 + 3.0 * x[1] ** 2)  # noqa: E731
    x = np.array([2.0, -1.0])
    assert np.allclose(numerical_gradient(f, x), [4.0, -6.0], rtol=1e-5, atol=1e-6)


def test_check_structure_returns_tuples_not_bare_bools():
    """A footgun worth pinning.

    ``check_structure`` returns ``{"J_skew": (ok, violation), ...}``. A caller
    writing the natural ``if result["J_skew"]:`` gets ``True`` unconditionally,
    because a non-empty tuple is truthy — so a broken model reads as fine. The
    value is genuinely useful (it says *how far off*), so the fix is to make
    the shape explicit and tested rather than to change it silently.
    """
    bad = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x @ x),
        grad_H=lambda x: x,
        J=lambda x: np.array([[0.0, 1.0], [1.0, 0.0]]),
        R=lambda x: np.zeros((2, 2)),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
    )
    result = bad.check_structure(np.array([1.0, 1.0]))
    assert isinstance(result["J_skew"], tuple) and len(result["J_skew"]) == 2
    assert bool(result["J_skew"]) is True, (
        "the truthiness trap is real: always unpack, never test the tuple"
    )
    assert result["J_skew"][0] is False or result["J_skew"][0] == False  # noqa: E712
