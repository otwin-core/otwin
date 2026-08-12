"""Every model must reproduce something known in closed form.

This file is the acceptance criterion for the library, and the reason a new
system can be reviewed in ten minutes rather than two hours: CI proves the
structural properties and the analytic match, so review is a conversation about
whether the model is interesting and correctly cited.

It exists because the structural tests alone are not enough. `test_library.py`
checks that J is skew, R is PSD, the power balance holds and energy decays —
and every one of those passed against a water tank whose dissipation was
dimensionally inconsistent and which drained 3.13x too slowly. A model can be
structurally impeccable and physically wrong. Only a closed-form comparison
catches that.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from otwin.model import (
    dc_motor,
    integrate_phs,
    mass_spring_damper,
    pumped_hydro,
    water_tank,
)

# --------------------------------------------------------------------------
# Water tank — Torricelli's law has an exact solution
# --------------------------------------------------------------------------

TANK = dict(A=1.0, a=0.1, g=9.81, c_d=0.6)


def torricelli_head(
    t: float, h0: float, A: float, a: float, g: float, c_d: float
) -> float:
    """h(t) = (sqrt(h0) - c_d a sqrt(2g) t / (2A))^2, until the tank empties."""
    k = c_d * a * math.sqrt(2.0 * g) / (2.0 * A)
    root = math.sqrt(h0) - k * t
    return root**2 if root > 0 else 0.0


@pytest.mark.parametrize("h", [0.5, 1.0, 2.0, 5.0])
def test_water_tank_instantaneous_rate_matches_torricelli(h):
    """dh/dt = -c_d a sqrt(2 g h) / A, exactly.

    This is the check that catches a missing sqrt(g) or a missing factor of A.
    Both errors leave a smooth, plausible-looking decay curve behind.
    """
    tank = water_tank(**TANK)
    got = float(tank.dynamics(np.array([h]), np.zeros(1))[0])
    expected = -TANK["c_d"] * TANK["a"] * math.sqrt(2 * TANK["g"] * h) / TANK["A"]
    assert got == pytest.approx(expected, rel=1e-12), (
        f"drain rate is off by a factor of {got / expected:.4f}"
    )


def test_water_tank_trajectory_matches_the_exact_solution():
    tank = water_tank(**TANK)
    t = np.linspace(0.0, 5.0, 501)
    sol = integrate_phs(tank, np.array([2.0]), t, np.zeros((501, 1)))
    X = sol["x"] if isinstance(sol, dict) else sol
    expected = torricelli_head(5.0, 2.0, **TANK)
    assert float(X[-1, 0]) == pytest.approx(expected, rel=1e-6)


def test_water_tank_empties_at_the_analytic_time():
    """t_empty = 2 A sqrt(h0) / (c_d a sqrt(2g)) = 10.63 s for these parameters."""
    t_empty = (
        2
        * TANK["A"]
        * math.sqrt(2.0)
        / (TANK["c_d"] * TANK["a"] * math.sqrt(2 * TANK["g"]))
    )
    assert t_empty == pytest.approx(10.63, abs=0.02)

    tank = water_tank(**TANK)
    t = np.linspace(0.0, t_empty * 1.5, 800)
    sol = integrate_phs(tank, np.array([2.0]), t, np.zeros((800, 1)))
    X = sol["x"] if isinstance(sol, dict) else sol
    assert float(X[-1, 0]) == pytest.approx(0.0, abs=1e-3)


def test_an_empty_tank_stays_empty():
    """The head is clamped, so the model cannot drain below zero."""
    tank = water_tank(**TANK)
    assert float(tank.dynamics(np.array([0.0]), np.zeros(1))[0]) == 0.0
    assert tank.energy(np.array([-0.5])) == 0.0, "negative head must not store energy"


# --------------------------------------------------------------------------
# DC motor — the steady state is algebra
# --------------------------------------------------------------------------

MOTOR = dict(L=0.5, inertia=0.01, Re=1.0, b=0.1, K=0.5)


def test_dc_motor_reaches_the_closed_form_steady_state():
    """Setting xdot = 0 gives omega_ss = VK/(Re b + K^2), I_ss = Vb/(Re b + K^2)."""
    V = 10.0
    den = MOTOR["Re"] * MOTOR["b"] + MOTOR["K"] ** 2
    omega_ss = V * MOTOR["K"] / den
    i_ss = V * MOTOR["b"] / den
    phi_ss = i_ss * MOTOR["L"]
    p_ss = omega_ss * MOTOR["inertia"]

    motor = dc_motor(**MOTOR)
    t = np.linspace(0, 5, 2001)
    u = np.full((2001, 1), V)
    sol = integrate_phs(motor, np.zeros(2), t, u)
    X = sol["x"] if isinstance(sol, dict) else sol

    assert float(X[-1, 0]) == pytest.approx(phi_ss, rel=1e-5)
    assert float(X[-1, 1]) == pytest.approx(p_ss, rel=1e-5)


def test_dc_motor_gyrator_is_lossless():
    """J couples the two domains without dissipating: it must be skew."""
    motor = dc_motor(**MOTOR)
    J = motor.J(np.array([1.0, 1.0]))
    assert np.allclose(J, -J.T, atol=1e-14)
    assert J[0, 1] == pytest.approx(-MOTOR["K"])


# --------------------------------------------------------------------------
# Pumped hydro — round-trip efficiency and conservation
# --------------------------------------------------------------------------

HYDRO = dict(A_u=5.0e4, A_l=5.0e6, z_u=300.0, g=9.81, rho=1000.0)


def test_pumped_hydro_energy_matches_the_gravitational_potential():
    """H = rho g [z_u V_u + V_u^2/2A_u + V_l^2/2A_l], integrated by hand."""
    plant = pumped_hydro(**HYDRO)
    v_u, v_l = 4.0e6, 8.0e6
    expected = (
        HYDRO["rho"]
        * HYDRO["g"]
        * (HYDRO["z_u"] * v_u + v_u**2 / (2 * HYDRO["A_u"]) + v_l**2 / (2 * HYDRO["A_l"]))
    )
    assert plant.energy(np.array([v_u, v_l])) == pytest.approx(expected, rel=1e-12)


def test_pumped_hydro_gradient_is_the_pressure_head():
    """grad_H = rho g x (free-surface elevation) at each reservoir."""
    plant = pumped_hydro(**HYDRO)
    v_u, v_l = 4.0e6, 8.0e6
    gh = plant.grad_H(np.array([v_u, v_l]))
    assert gh[0] == pytest.approx(
        HYDRO["rho"] * HYDRO["g"] * (HYDRO["z_u"] + v_u / HYDRO["A_u"])
    )
    assert gh[1] == pytest.approx(HYDRO["rho"] * HYDRO["g"] * (v_l / HYDRO["A_l"]))


def test_pumped_hydro_has_no_lossless_circulation_path():
    """J = 0: water moves only through the penstock or the pump-turbine port."""
    plant = pumped_hydro(**HYDRO)
    assert np.allclose(plant.J(np.array([4.0e6, 8.0e6])), 0.0)


# --------------------------------------------------------------------------
# Mass-spring-damper — the undamped case has an exact period
# --------------------------------------------------------------------------


def test_undamped_oscillator_conserves_energy_exactly():
    """With c = 0 the system is lossless: R = 0 makes this an equality."""
    sys = mass_spring_damper(m=1.0, k=4.0, c=0.0)
    x = np.array([1.0, 0.5])
    assert sys.power_balance(x, np.zeros(1))["dH_dt"] == pytest.approx(0.0, abs=1e-12)

    t = np.linspace(0, 10, 2001)
    sol = integrate_phs(sys, x, t, np.zeros((2001, 1)))
    X = sol["x"] if isinstance(sol, dict) else sol
    E = np.array([sys.energy(xi) for xi in X])
    drift = abs(E[-1] - E[0]) / E[0]
    assert drift < 1e-6, f"a lossless system drifted by {drift:.2e}"
