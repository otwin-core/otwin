"""The compiled systems reproduce the hand-written port-Hamiltonian models of 0.4."""

import numpy as np
import pytest

import otwin
from otwin import CustomDynamics, System
from otwin import expr as ex
from otwin.components import catalogue
from otwin.components.hydraulic import FlowSource, Tank
from otwin.components.rotational import Housing, Inertia, RotationalDamper
from otwin.model import (
    PortHamiltonianSystem,
    dc_motor,
    integrate_phs,
    mass_spring_damper,
    pumped_hydro,
    water_tank,
)


def test_mass_spring_damper_matches(backend):
    t = np.linspace(0, 20, 401)
    old = integrate_phs(
        mass_spring_damper(1.0, 20.0, 0.3), np.array([1.0, 0.0]), t, np.zeros((401, 1))
    )
    new = otwin.compile(
        catalogue.mass_spring_damper(1.0, 20.0, 0.3, position=1.0), backend=backend
    ).simulate(t=t)
    assert np.max(np.abs(new.x - old["x"])) < 1e-10
    e_old = np.array([mass_spring_damper(1.0, 20.0, 0.3).energy(x) for x in old["x"]])
    assert np.max(np.abs(new.energy - e_old)) < 1e-10


def test_water_tank_matches_free_drain(backend):
    t = np.linspace(0, 600, 601)
    old = integrate_phs(water_tank(), np.array([2.0]), t, np.zeros((601, 1)))
    new = otwin.compile(catalogue.water_tank(level=2.0), backend=backend).simulate(t=t)
    assert np.max(np.abs(new["tank.level"] - old["x"][:, 0])) < 1e-8


def test_water_tank_matches_level_feedback(backend):
    t = np.linspace(0, 600, 601)
    old = integrate_phs(
        water_tank(),
        np.array([2.0]),
        t,
        u=lambda t, x: np.array([max(0.0, 5.0 * (1.5 - float(x[0])))]),
    )
    model = otwin.compile(catalogue.water_tank(level=2.0), backend=backend)
    level = model.symbol("tank.level")
    new = model.simulate(t=t, inputs={"inlet": ex.maximum(0.0, 5.0 * (1.5 - level))})
    assert np.max(np.abs(new["tank.level"] - old["x"][:, 0])) < 1e-8
    assert np.max(np.abs(new["inlet"] - old["u"][:, 0])) < 1e-8


def test_dc_motor_matches(backend):
    t = np.linspace(0, 5, 501)
    old = integrate_phs(dc_motor(), np.array([0.0, 0.0]), t, np.full((501, 1), 12.0))
    new = otwin.compile(catalogue.dc_motor(), backend=backend).simulate(
        t=t, inputs={"supply": 12.0}
    )
    assert np.max(np.abs(new.x - old["x"])) < 1e-7


def test_pumped_hydro_matches(backend):
    t = np.linspace(0, 3600, 361)
    x0 = np.array([1.0e6, 1.0e7])
    u = np.full((361, 1), 20.0)
    old = integrate_phs(pumped_hydro(), x0, t, u)
    new = otwin.compile(
        catalogue.pumped_hydro(V_u=1.0e6, V_l=1.0e7), backend=backend
    ).simulate(t=t, inputs={"pump": 20.0})
    assert np.max(np.abs(new.x - old["x"]) / np.abs(old["x"])) < 1e-8
    assert new.energy[0] == pytest.approx(pumped_hydro().energy(x0), rel=1e-12)


def test_flywheel_with_speed_dependent_loss(backend):
    """Notebook 01: R = C1 + C2 omega^2, written as a nonlinear damper law."""
    I_fw, C1, C2 = 1200.0, 0.020, 2.0e-6
    fly_old = PortHamiltonianSystem(
        H=lambda x: x[0] ** 2 / (2 * I_fw),
        grad_H=lambda x: np.array([x[0] / I_fw]),
        J=lambda x: np.zeros((1, 1)),
        R=lambda x: np.array([[C1 + C2 * (abs(x[0]) / I_fw) ** 2]]),
        g=lambda x: np.array([[1.0]]),
        n_states=1,
        n_inputs=1,
    )
    rotor = Inertia(I_fw, speed=700.0, name="rotor")
    bearing = RotationalDamper(law=lambda w: (C1 + C2 * w**2) * w, name="bearing")
    housing = Housing()
    s = (
        System(rotor, bearing, housing)
        .connect(rotor.shaft, bearing.a)
        .connect(bearing.b, housing.port)
    )
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 7200, 7201)
    old = integrate_phs(fly_old, np.array([I_fw * 700.0]), t, np.zeros((7201, 1)))
    new = model.simulate(t=t)
    assert np.max(np.abs(new.x[:, 0] - old["x"][:, 0]) / old["x"][:, 0]) < 1e-9
    assert np.all(np.diff(new.energy) <= 0.0)


def test_pumped_hydro_with_power_law_port(backend):
    """Notebook 01: a pump holding rated power, the flow following from the head."""
    rho, g = 1000.0, 9.81
    A1, A2, z2b = 2.0e5, 2.0e5, 300.0
    P, ETA_P = 5.0e7, 0.9
    upper = Tank(A2, level=7.6e5 / A2, base_elevation=z2b, name="upper")
    lower = Tank(A1, level=1.0e6 / A1, name="lower")
    pump = FlowSource(None, name="pump")
    s = System(upper, lower, pump).connect(upper.port, pump.a).connect(lower.port, pump.b)
    model = otwin.compile(s, backend=backend)
    head = model.symbol("upper.pressure") - model.symbol("lower.pressure")
    tc = np.linspace(0, 6 * 3600, 2161)
    new = model.simulate(t=tc, inputs={"pump": ETA_P * P / head})

    def H_h(x):
        return rho * g * (x[0] * (x[0] / (2 * A1)) + x[1] * (z2b + x[1] / (2 * A2)))

    hydro = PortHamiltonianSystem(
        H=H_h,
        grad_H=lambda x: np.array([rho * g * (x[0] / A1), rho * g * (z2b + x[1] / A2)]),
        J=lambda x: np.zeros((2, 2)),
        R=lambda x: np.zeros((2, 2)),
        g=lambda x: np.array([[-1.0], [1.0]]),
        n_states=2,
        n_inputs=1,
    )

    def head_old(v1, v2):
        return (z2b + v2 / A2) - (v1 / A1)

    old = integrate_phs(
        hydro,
        np.array([1.0e6, 7.6e5]),
        tc,
        lambda t, x: np.array([ETA_P * P / (rho * g * head_old(x[0], x[1]))]),
    )
    assert np.max(np.abs(new["lower.volume"] - old["x"][:, 0]) / old["x"][:, 0]) < 1e-8
    assert np.max(np.abs(new["upper.volume"] - old["x"][:, 1]) / old["x"][:, 1]) < 1e-8
    stored_new = new.energy[-1] - new.energy[0]
    stored_old = hydro.energy(old["x"][-1]) - hydro.energy(old["x"][0])
    assert stored_new == pytest.approx(stored_old, rel=1e-8)


def test_custom_dynamics_wraps_a_phs():
    phs = water_tank()
    custom = CustomDynamics.from_phs(phs)
    t = np.linspace(0, 100, 101)
    old = integrate_phs(phs, np.array([2.0]), t, np.zeros((101, 1)))
    new = custom.simulate(t=t, x0=[2.0])
    assert np.max(np.abs(new.x - old["x"])) < 1e-8
    assert new.energy[0] == pytest.approx(phs.energy(np.array([2.0])))
