"""The modulated (Ramírez–Maschke–Sbarbaro) irreversible form.

`IrreversiblePHS` implements ẋ = (J − R)∇H + gu + L∇S. Most of the irreversible
port-Hamiltonian literature — including Ramírez, Maschke & Sbarbaro (2013), which
this package cites — writes ẋ = γ(x)·J∇H + gu instead. The two are not notational
variants of each other: recasting a reactor from the second into the first means
constructing an L whose column against ∇S reproduces γJ∇H and then padding the
rest to stay PSD. That derivation is what `ModulatedIPHS` removes.

The reactor below is the standard non-isothermal CSTR with the internal-energy
Hamiltonian, x = (n_A, n_B, S). It is used because it has a property worth
testing against: in the adiabatic closed configuration the internal energy must
be conserved *exactly*, so a structural claim becomes a number.
"""

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from otwin.model import IrreversiblePHS, ModulatedIPHS

RG = 8.314462618
CV_A, CV_B = 75.0, 80.0
DMU0 = 2000.0  # mildly exothermic: equilibrium sits at partial conversion
TREF = 350.0
K0, EA = 2.0, 20000.0
J3 = np.array([[0.0, 0.0, -1.0], [0.0, 0.0, 1.0], [1.0, -1.0, 0.0]])


def _thermo(x):
    """Recover T and the chemical potentials from x = (n_A, n_B, S)."""
    n_a, n_b, entropy = max(x[0], 1e-12), max(x[1], 1e-12), x[2]
    heat_cap = n_a * CV_A + n_b * CV_B
    n = n_a + n_b
    s_mix = -RG * (n_a * np.log(n_a / n) + n_b * np.log(n_b / n))
    temp = TREF * np.exp((entropy - s_mix) / heat_cap)
    mu_a = (
        CV_A * (temp - TREF)
        - CV_A * temp * np.log(temp / TREF)
        + RG * temp * np.log(n_a / n)
        + DMU0
    )
    mu_b = (
        CV_B * (temp - TREF)
        - CV_B * temp * np.log(temp / TREF)
        + RG * temp * np.log(n_b / n)
    )
    return temp, mu_a, mu_b


def _rate(temp, n_a, n_b, affinity):
    """Mass action made thermodynamically consistent: sign(r) == sign(A) identically."""
    kf = K0 * np.exp(-EA / (RG * temp))
    return kf * (n_a + n_b) * (1.0 - np.exp(-affinity / (RG * temp))) / 2.0


def _gamma(x):
    temp, mu_a, mu_b = _thermo(x)
    return _rate(temp, x[0], x[1], mu_a - mu_b) / temp


def _energy(x):
    temp, _, _ = _thermo(x)
    return x[0] * CV_A * (temp - TREF) + x[1] * CV_B * (temp - TREF) + x[0] * DMU0


def _grad_energy(x):
    temp, mu_a, mu_b = _thermo(x)
    return np.array([mu_a, mu_b, temp])


def _reactor(**kwargs):
    return IrreversiblePHS.from_modulated(
        H=_energy,
        S=lambda x: float(x[2]),
        J=lambda x: J3,
        gamma=_gamma,
        g=lambda x: np.zeros((3, 1)),
        n_states=3,
        n_inputs=1,
        grad_H=_grad_energy,
        grad_S=lambda x: np.array([0.0, 0.0, 1.0]),
        **kwargs,
    )


X0 = np.array([8.0, 2.0, 0.0])


def test_from_modulated_returns_the_modulated_class():
    assert isinstance(_reactor(), ModulatedIPHS)


def test_adiabatic_closed_reactor_conserves_energy_structurally():
    """dU/dt = ∇Uᵀ γJ ∇U = 0 for any skew J and any scalar γ. Check it as a number."""
    react = _reactor()
    for x in (X0, np.array([5.0, 5.0, 20.0]), np.array([2.0, 8.0, 40.0])):
        conserved, du_dt = react.check_energy_conservation(x)
        assert conserved, du_dt
        assert abs(du_dt) < 1e-9


def test_entropy_production_is_non_negative_along_the_whole_trajectory():
    react = _reactor()
    sol = solve_ivp(
        lambda t, x: react.dynamics(x, np.zeros(1), t),
        (0, 4000),
        X0,
        rtol=1e-12,
        atol=1e-14,
        max_step=2.0,
        method="LSODA",
    )
    sigma = np.array(
        [react.entropy_production(sol.y[:, k]) for k in range(sol.y.shape[1])]
    )
    assert sigma.min() >= -1e-12
    assert np.mean(sigma < 0) == 0.0
    # Energy drift over 4000 s of integration, not just at a point.
    drift = np.array([_energy(sol.y[:, k]) for k in range(sol.y.shape[1])])
    assert np.max(np.abs(drift - drift[0])) / abs(drift[0]) < 1e-9
    # The reaction actually ran: this is not a test of a system sitting still.
    assert 0.5 < 1 - sol.y[0, -1] / sol.y[0, 0] < 0.7


def test_a_gamma_that_breaks_the_second_law_raises():
    """Fault injection. The check exists to catch this, so make it happen.

    A rate built without the affinity — forward only, no back reaction — drives
    the system past chemical equilibrium. Once the affinity changes sign the
    implied entropy production goes negative, which is precisely the failure the
    irreversible structure is supposed to make impossible to state silently.
    """

    def forward_only_gamma(x):
        temp, _, _ = _thermo(x)
        return K0 * np.exp(-EA / (RG * temp)) * x[0] / temp

    bad = IrreversiblePHS.from_modulated(
        H=_energy,
        S=lambda x: float(x[2]),
        J=lambda x: J3,
        gamma=forward_only_gamma,
        g=lambda x: np.zeros((3, 1)),
        n_states=3,
        n_inputs=1,
        grad_H=_grad_energy,
        grad_S=lambda x: np.array([0.0, 0.0, 1.0]),
    )
    # Past equilibrium: nearly all A consumed, so the affinity has changed sign.
    past_equilibrium = np.array([0.05, 9.95, 60.0])
    assert bad.entropy_production(past_equilibrium) < 0
    with pytest.raises(ValueError, match="second law"):
        bad.dynamics(past_equilibrium, np.zeros(1))

    # validate=False is an explicit opt-out, and must stay an opt-out.
    unchecked = IrreversiblePHS.from_modulated(
        H=_energy,
        S=lambda x: float(x[2]),
        J=lambda x: J3,
        gamma=forward_only_gamma,
        g=lambda x: np.zeros((3, 1)),
        n_states=3,
        n_inputs=1,
        grad_H=_grad_energy,
        grad_S=lambda x: np.array([0.0, 0.0, 1.0]),
        validate=False,
    )
    assert np.all(np.isfinite(unchecked.dynamics(past_equilibrium, np.zeros(1))))


def test_check_structure_reports_the_modulated_guarantees():
    report = _reactor().check_structure(X0)
    assert set(report) == {
        "J_skew",
        "R_psd",
        "gamma_finite",
        "sigma_nonneg",
        "energy_conserved",
    }
    assert report["J_skew"][0]
    assert report["sigma_nonneg"][0]
    assert report["energy_conserved"][0]


def test_modulated_and_additive_forms_agree_on_the_same_reactor():
    """The equivalence, done once here so no user has to do it again.

    With S(x) = x₂ the entropy gradient is (0, 0, 1), so only the third column of
    L reaches the dynamics. Setting it to γJ∇U reproduces the vector field, and
    σ = ∇SᵀL∇S = L₂₂ = γA is the same entropy production. The leading 2×2 block
    is free and is chosen to keep L positive semidefinite.
    """

    def coupling(x):
        temp, mu_a, mu_b = _thermo(x)
        affinity = mu_a - mu_b
        gam = _gamma(x)
        col = np.array([-gam * temp, gam * temp, gam * affinity])
        mat = np.zeros((3, 3))
        mat[:, 2] = col
        mat[2, :] = col
        denom = max(gam * affinity, 1e-30)
        mat[0, 0] = col[0] ** 2 / denom + 1e-18
        mat[1, 1] = col[1] ** 2 / denom + 1e-18
        mat[0, 1] = mat[1, 0] = col[0] * col[1] / denom
        return mat

    additive = IrreversiblePHS(
        H=_energy,
        S=lambda x: float(x[2]),
        J=lambda x: np.zeros((3, 3)),
        R=lambda x: np.zeros((3, 3)),
        L=coupling,
        g=lambda x: np.zeros((3, 1)),
        n_states=3,
        n_inputs=1,
        grad_H=_grad_energy,
        grad_S=lambda x: np.array([0.0, 0.0, 1.0]),
    )
    modulated = _reactor()
    for x in (X0, np.array([6.0, 4.0, 12.0]), np.array([4.0, 6.0, 25.0])):
        np.testing.assert_allclose(
            modulated.dynamics(x, np.zeros(1)),
            additive.dynamics(x, np.zeros(1)),
            rtol=1e-10,
            atol=1e-14,
        )
        assert modulated.entropy_production(x) == pytest.approx(
            additive.entropy_production(x), rel=1e-10
        )


def test_analytic_grad_h_is_used_and_beats_finite_differences():
    """The reason grad_H was added: without it the first-law check is blunter."""
    analytic = IrreversiblePHS(
        H=lambda x: 0.5 * (x[0] ** 2 + 3.0 * x[1] ** 2),
        S=lambda x: float(x[1]),
        J=lambda x: np.zeros((2, 2)),
        R=lambda x: np.zeros((2, 2)),
        L=lambda x: np.zeros((2, 2)),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
        grad_H=lambda x: np.array([x[0], 3.0 * x[1]]),
        grad_S=lambda x: np.array([0.0, 1.0]),
    )
    numeric = IrreversiblePHS(
        H=lambda x: 0.5 * (x[0] ** 2 + 3.0 * x[1] ** 2),
        S=lambda x: float(x[1]),
        J=lambda x: np.zeros((2, 2)),
        R=lambda x: np.zeros((2, 2)),
        L=lambda x: np.zeros((2, 2)),
        g=lambda x: np.zeros((2, 1)),
        n_states=2,
        n_inputs=1,
    )
    x = np.array([1.3, -0.7])
    exact = np.array([1.3, 3.0 * -0.7])
    np.testing.assert_array_equal(analytic.grad_H(x), exact)
    np.testing.assert_array_equal(analytic.grad_S(x), np.array([0.0, 1.0]))
    # The analytic path is exact; the finite-difference path is not, and the
    # gap is the whole reason the argument was added.
    assert np.max(np.abs(analytic.grad_H(x) - exact)) == 0.0
    assert np.max(np.abs(numeric.grad_H(x) - exact)) > 0.0
