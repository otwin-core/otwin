"""Heat exchanger: the catalogue entry, the steady-state map, the fouling law.

Three separate objects on purpose, because they are three different kinds of
thing and collapsing them is the modelling error the package's scope note names:

* the exchanger is a dynamic system with a conserved energy — an IPHS;
* the effectiveness is an algebraic map, not a dynamic system at all;
* fouling has no energy and no port, so it is an empirical law.

CONTRIBUTING asks a new catalogue model for one result known in closed form. The
exchanger has two: energy is conserved exactly with the ports closed, and the
ε-NTU relations have textbook closed forms checked against here.
"""

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from otwin.interfaces import EmpiricalLawModel
from otwin.model import (
    ModulatedIPHS,
    effectiveness_ntu,
    heat_exchanger,
    kern_seaton_fouling,
)


def test_exchanger_is_an_irreversible_system_not_a_dissipative_one():
    """Conduction conserves energy and makes entropy. Putting it in R destroys it."""
    hx = heat_exchanger()
    assert isinstance(hx, ModulatedIPHS)
    x = np.array([1.0e5, -1.0e5])
    report = hx.check_structure(x)
    assert report["J_skew"][0]
    assert report["energy_conserved"][0]
    assert report["sigma_nonneg"][0]
    assert report["sigma_nonneg"][1] > 0.0


def test_energy_conserved_and_entropy_produced_over_a_whole_relaxation():
    """Not at a point — along the trajectory, which is where drift would show."""
    hx = heat_exchanger(UA=4.0e4, C_hot=5.0e5, C_cold=8.0e5)
    x0 = np.array([2.0e5, -1.0e5])
    sol = solve_ivp(
        lambda t, x: hx.dynamics(x, np.zeros(2), t),
        (0, 400.0),
        x0,
        rtol=1e-11,
        atol=1e-13,
        max_step=1.0,
    )
    energy = np.array([hx.H(sol.y[:, k]) for k in range(sol.y.shape[1])])
    sigma = np.array([hx.entropy_production(sol.y[:, k]) for k in range(sol.y.shape[1])])
    entropy = sol.y[0] + sol.y[1]

    assert np.max(np.abs(energy - energy[0])) / abs(energy[0]) < 1e-9
    assert sigma.min() >= -1e-12
    assert entropy[-1] > entropy[0]  # total entropy rose
    # And it actually equilibrated rather than sitting still.
    t_hot = 300.0 * np.exp(sol.y[0] / 5.0e5)
    t_cold = 300.0 * np.exp(sol.y[1] / 8.0e5)
    assert abs(t_hot[-1] - t_cold[-1]) < 0.05 * abs(t_hot[0] - t_cold[0])


def test_entropy_production_is_zero_only_at_thermal_equilibrium():
    hx = heat_exchanger()
    assert hx.entropy_production(np.zeros(2)) == 0.0
    # Non-negative whichever body is hotter: the direction of heat flow does
    # not get to decide the sign of the second law.
    assert hx.entropy_production(np.array([1.0e5, -1.0e5])) > 0
    assert hx.entropy_production(np.array([-1.0e5, 1.0e5])) > 0


def test_exchanger_rejects_unphysical_parameters():
    for bad in (dict(UA=0.0), dict(C_hot=-1.0), dict(T_ref=0.0)):
        with pytest.raises(ValueError, match="positive"):
            heat_exchanger(**bad)


def test_effectiveness_matches_the_closed_forms():
    """The textbook relations, evaluated independently here."""
    UA, c_hot, c_cold = 4.0e4, 1.44e4, 5.0e4
    c_min, c_max = min(c_hot, c_cold), max(c_hot, c_cold)
    ntu, ratio = UA / c_min, c_min / c_max

    counter = (1 - np.exp(-ntu * (1 - ratio))) / (1 - ratio * np.exp(-ntu * (1 - ratio)))
    parallel = (1 - np.exp(-ntu * (1 + ratio))) / (1 + ratio)

    assert effectiveness_ntu(UA, c_hot, c_cold) == pytest.approx(counter, rel=1e-12)
    assert effectiveness_ntu(UA, c_hot, c_cold, flow="parallel") == pytest.approx(
        parallel, rel=1e-12
    )
    assert effectiveness_ntu(UA, c_hot, c_cold, flow="evaporator") == pytest.approx(
        1 - np.exp(-ntu), rel=1e-12
    )
    # Balanced counter-flow is the one the general formula divides by zero on.
    assert effectiveness_ntu(4.0e4, 4.0e4, 4.0e4) == pytest.approx(0.5, rel=1e-12)


def test_effectiveness_is_bounded_and_monotone_in_size():
    """Bounded above by 1 -- the asymptote, which large NTU reaches in floating point."""
    rng = np.random.default_rng(0)
    saturated = 0
    for _ in range(200):
        ua = float(rng.uniform(1e3, 1e6))
        c_h = float(rng.uniform(1e3, 1e5))
        c_c = float(rng.uniform(1e3, 1e5))
        eps = effectiveness_ntu(ua, c_h, c_c)
        assert 0.0 < eps <= 1.0
        bigger = effectiveness_ntu(2 * ua, c_h, c_c)
        assert bigger >= eps  # a bigger unit never does less
        if eps == 1.0:
            saturated += 1
        else:
            assert bigger > eps  # and strictly more below the asymptote
    # Some of that sweep really is in the saturated regime, so the <= above is
    # doing work rather than papering over a bug.
    assert saturated > 0


def test_effectiveness_rejects_bad_input():
    with pytest.raises(ValueError, match="positive"):
        effectiveness_ntu(-1.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="counter"):
        effectiveness_ntu(1.0, 1.0, 1.0, flow="crossflow")


def test_fouling_is_an_empirical_law_and_not_a_phs():
    """The structural point: no rhs, on purpose."""
    law = kern_seaton_fouling()
    assert isinstance(law, EmpiricalLawModel)
    assert not hasattr(law, "rhs")
    assert law.param_names == ("R_inf", "tau_days")


def test_fouling_approaches_its_plateau():
    law = kern_seaton_fouling(R_inf=8.0e-4, tau_days=260.0)
    t = np.array([0.0, 260.0, 1300.0, 1e6])
    r_f = law.law(t)
    assert r_f[0] == 0.0
    assert r_f[1] == pytest.approx(8.0e-4 * (1 - np.exp(-1.0)), rel=1e-12)
    assert r_f[-1] == pytest.approx(8.0e-4, rel=1e-9)
    assert np.all(np.diff(r_f) > 0)

    cf = law.cleanliness(t)
    assert cf[0] == 1.0
    assert np.all(np.diff(cf) < 0)
    assert cf[-1] == pytest.approx(1.0 / (1.0 + 800.0 * 8.0e-4), rel=1e-9)


def test_fouling_parameters_can_be_overridden_per_call():
    """`law(t, params)` is the protocol's signature: the fit supplies the params."""
    law = kern_seaton_fouling()
    fitted = {"R_inf": 6.2e-4, "tau_days": 200.0}
    assert law.law(np.array([1e6]), fitted)[0] == pytest.approx(6.2e-4, rel=1e-9)
    assert law.law(np.array([1e6]))[0] == pytest.approx(8.0e-4, rel=1e-9)


def test_fouling_rejects_unphysical_parameters():
    for bad in (dict(R_inf=-1.0), dict(tau_days=0.0), dict(U_clean=-5.0)):
        with pytest.raises(ValueError):
            kern_seaton_fouling(**bad)


def test_fouled_exchanger_delivers_less_duty():
    """The two objects composing, which is the point of having both."""
    law = kern_seaton_fouling(R_inf=8.0e-4, tau_days=260.0, U_clean=800.0)
    area, c_hot, c_cold = 50.0, 1.44e4, 5.0e4

    duty = [
        effectiveness_ntu(float(law.U(np.array([day]))[0]) * area, c_hot, c_cold)
        for day in (0.0, 180.0, 450.0)
    ]
    assert duty[0] > duty[1] > duty[2]
    assert duty[2] < 0.97 * duty[0]
