"""A port whose value depends on the state.

`u` as an array indexed by time covers a schedule. It does not cover a machine
that holds a set point: a converter at constant power, a thermostat, a droop
control, a pump-turbine holding rated electrical power against a head that the
state determines. Those are feedback, and writing them as a schedule is not an
approximation, it is a different system.

The tests here pin three things: that a law which ignores the state gives back
exactly the array path, that the discrete power balance survives feedback (which
is the whole reason the law is evaluated at the midpoint and not at the step
start), and that the closed-form path refuses the job rather than answering it
wrongly.
"""

import numpy as np
import pytest

from otwin.model import (
    PortHamiltonianSystem,
    implicit_midpoint,
    integrate_phs,
    integrate_with_inputs,
    mass_spring_damper,
    water_tank,
)


def _tank_field(tank):
    return lambda t, x, u: tank.dynamics(x, u)


def test_state_independent_law_matches_the_array_path():
    """A law that ignores x is a schedule, and must integrate to the same thing."""
    tank = water_tank()
    t = np.linspace(0, 10, 101)
    u_arr = np.full((101, 1), 0.03)

    by_array = implicit_midpoint(_tank_field(tank), np.array([2.0]), t, u_arr)
    by_law = implicit_midpoint(
        _tank_field(tank), np.array([2.0]), t, lambda tv, x: np.array([0.03])
    )

    assert by_array["success"] and by_law["success"]
    np.testing.assert_allclose(by_law["x"], by_array["x"], rtol=1e-10, atol=1e-12)


def test_dissipative_feedback_never_increases_energy():
    """The structural test, and the reason the law is evaluated at the midpoint.

    With ``u = -K y`` the port supplies ``yᵀu = -K‖y‖² ≤ 0``, so on top of R the
    stored energy must be non-increasing. Evaluating the law at the *step start*
    instead makes the port term explicit and the balance only second-order
    accurate, which lets H tick back up at a coarse step. Here the step is
    deliberately coarse so that the difference has somewhere to show.
    """
    osc = mass_spring_damper(m=1.0, k=4.0, c=0.05)
    K = 3.0

    def law(t, x):
        y = osc.g(x).T @ osc.grad_H(x)  # the port output, collocated with u
        return -K * y

    t = np.linspace(0, 40, 201)  # dt = 0.2 s against a ~0.5 s period: coarse
    res = integrate_phs(osc, np.array([1.0, 0.0]), t, u=law)

    assert res["success"]
    energy = np.array([osc.energy(x) for x in res["x"]])
    assert np.max(np.diff(energy)) <= 1e-9 * energy[0]
    assert energy[-1] < 1e-3 * energy[0]  # the feedback really is damping it


def test_constant_power_port_reproduces_the_closed_form_round_trip():
    """The case that motivated this: a machine holding rated power.

    A pump-turbine at rated electrical power P moves a volumetric flow
    ``Q = ηP/(ρ g Δh)`` — fixed by the head, hence by the state. Charging for a
    fixed time and discharging back to the starting volume must return a
    round-trip efficiency of exactly ``η_p·η_t``, and that closed form is what
    the numeric answer is checked against.
    """
    rho, g_acc = 1000.0, 9.81
    A1 = A2 = 2.0e5
    z1b, z2b = 0.0, 300.0
    P, eta_p, eta_t = 100e6, 0.90, 0.90

    def head(x):
        return (z2b + x[1] / A2) - (z1b + x[0] / A1)

    store = PortHamiltonianSystem(
        H=lambda x: (
            rho
            * g_acc
            * (x[0] * (z1b + x[0] / (2 * A1)) + x[1] * (z2b + x[1] / (2 * A2)))
        ),
        grad_H=lambda x: np.array(
            [rho * g_acc * (z1b + x[0] / A1), rho * g_acc * (z2b + x[1] / A2)]
        ),
        J=lambda x: np.zeros((2, 2)),
        R=lambda x: np.zeros((2, 2)),
        g=lambda x: np.array([[-1.0], [1.0]]),  # port flow moves water uphill
        n_states=2,
        n_inputs=1,
    )

    t_charge = 6 * 3600.0
    x0 = np.array([1.0e6, 1.0e5])

    pump = lambda tv, x: np.array([eta_p * P / (rho * g_acc * head(x))])
    t_up = np.linspace(0.0, t_charge, 1441)
    up = integrate_phs(store, x0, t_up, u=pump)
    assert up["success"]
    x_full = up["x"][-1]

    turbine = lambda tv, x: np.array([-P / (eta_t * rho * g_acc * head(x))])
    t_down = np.linspace(0.0, 10 * t_charge, 14401)
    down = integrate_phs(store, x_full, t_down, u=turbine)
    assert down["success"]

    back = np.argmax(down["x"][:, 1] <= x0[1])
    t_discharge = float(np.interp(x0[1], down["x"][back::-1, 1], t_down[back::-1]))
    rte = (P * t_discharge) / (P * t_charge)
    assert rte == pytest.approx(eta_p * eta_t, rel=2e-4)


def test_realised_port_trajectory_is_returned():
    """A port law leaves no schedule behind, so the integrator has to record it."""
    tank = water_tank()
    t = np.linspace(0, 20, 201)
    res = integrate_phs(
        tank,
        np.array([1.0]),
        t,
        u=lambda tv, x: np.array([0.4 * max(0.0, 4.0 - float(x[0]))]),
    )
    assert res["u"].shape == (201, 1)
    # The valve closes as the tank fills, so the inlet flow falls monotonically.
    assert res["u"][0, 0] > res["u"][-1, 0] > 0.0
    np.testing.assert_allclose(
        res["u"][:, 0], 0.4 * np.maximum(0.0, 4.0 - res["x"][:, 0]), atol=1e-12
    )


def test_closed_form_path_is_refused_not_downgraded():
    """A wrong Jacobian costs iterations; a wrong affine matrix costs the answer."""
    osc = mass_spring_damper()
    t = np.linspace(0, 5, 51)
    law = lambda tv, x: np.array([-0.5 * float(x[1])])

    with pytest.raises(ValueError, match="port law"):
        implicit_midpoint(
            lambda tv, x, u: osc.dynamics(x, u),
            np.array([1.0, 0.0]),
            t,
            law,
            method="linear",
        )
    with pytest.raises(ValueError, match="port law"):
        integrate_phs(osc, np.array([1.0, 0.0]), t, u=law, method="linear")


def test_port_law_works_through_integrate_with_inputs_on_both_paths():
    """The generic entry point takes a law on the explicit path too."""
    tank = water_tank()
    t = np.linspace(0, 10, 101)
    law = lambda tv, x: np.array([0.2 * max(0.0, 3.0 - float(x[0]))])

    explicit = integrate_with_inputs(_tank_field(tank), np.array([1.0]), t, law)
    implicit = integrate_with_inputs(
        _tank_field(tank), np.array([1.0]), t, law, method="implicit_midpoint"
    )
    assert explicit["success"] and implicit["success"]
    # Same system, two integrators: they must agree to solver tolerance.
    np.testing.assert_allclose(implicit["x"], explicit["x"], rtol=2e-3, atol=1e-5)
