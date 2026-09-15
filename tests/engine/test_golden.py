"""Golden models: component systems against closed-form solutions, on every backend."""

import numpy as np
import pytest

import otwin
from otwin import System
from otwin.components.electrical import (
    Capacitor,
    Ground,
    Inductor,
    Resistor,
    VoltageSource,
)
from otwin.components.hydraulic import Atmosphere, Orifice, Tank
from otwin.components.mechanical import Damper, Fixed, ForceSource, Mass, Spring
from otwin.components.thermal import Ambient, HeatSource, ThermalMass, ThermalResistance


def test_mass_spring_damper_underdamped(backend):
    m, k, c = 1.0, 20.0, 0.3
    mass, spring, damper, wall = (
        Mass(m, name="m"),
        Spring(k, extension=1.0, name="k"),
        Damper(c, name="c"),
        Fixed(),
    )
    s = System(mass, spring, damper, wall).connect(mass.flange, spring.a, damper.a)
    s.connect(spring.b, damper.b, wall.terminal)
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 10, 2001)
    tr = model.simulate(t=t, solver="rk45", rtol=1e-10, atol=1e-12)
    w0, zeta = np.sqrt(k / m), c / (2 * np.sqrt(k * m))
    wd = w0 * np.sqrt(1 - zeta**2)
    q = np.exp(-zeta * w0 * t) * (np.cos(wd * t) + zeta * w0 / wd * np.sin(wd * t))
    assert np.max(np.abs(tr["k.extension"] - q)) < 1e-7
    # the midpoint rule keeps the energy inequality exactly
    tr2 = model.simulate(t=t, solver="midpoint")
    assert np.all(np.diff(tr2.energy) <= 1e-12)
    assert tr2.energy_balance()["max_violation"] <= 1e-12


def test_forced_mass_reaches_static_equilibrium(backend):
    mass, spring, damper, wall = (
        Mass(1.0, name="m"),
        Spring(20.0, name="k"),
        Damper(0.3, name="c"),
        Fixed(),
    )
    weight = ForceSource(9.81, name="g")
    s = System(mass, spring, damper, wall, weight)
    s.connect(mass.flange, spring.a, damper.a, weight.flange).connect(
        spring.b, damper.b, wall.terminal
    )
    model = otwin.compile(s, backend=backend)
    tr = model.simulate(t_span=(0, 200), dt=0.05)
    assert tr["k.extension"][-1] == pytest.approx(9.81 / 20.0, abs=1e-6)
    # power supplied by the weight balances the energy change plus dissipation
    assert tr.energy_balance()["max_violation"] < 1e-8


def test_rc_circuit(backend):
    V, R, C, g = (
        VoltageSource(5.0, name="V"),
        Resistor(100.0, name="R"),
        Capacitor(1e-3, name="C"),
        Ground(),
    )
    s = (
        System(V, R, C, g)
        .connect(V.p, R.p)
        .connect(R.n, C.p)
        .connect(C.n, V.n, g.terminal)
    )
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 0.5, 501)
    tr = model.simulate(t=t, solver="rk45")
    assert np.max(np.abs(tr["C.voltage"] - 5 * (1 - np.exp(-t / 0.1)))) < 1e-9
    assert np.max(np.abs(tr["R.current"] - 5 / 100 * np.exp(-t / 0.1))) < 1e-9
    # the source delivers what the resistor burns plus what the capacitor stores
    assert np.allclose(tr["V.power"], -tr["R.power"] - tr["C.power"], atol=1e-12)


def test_rl_circuit(backend):
    V, R, L, g = (
        VoltageSource(5.0, name="V"),
        Resistor(2.0, name="R"),
        Inductor(0.5, name="L"),
        Ground(),
    )
    s = (
        System(V, R, L, g)
        .connect(V.p, R.p)
        .connect(R.n, L.p)
        .connect(L.n, V.n, g.terminal)
    )
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 2, 401)
    tr = model.simulate(t=t, solver="rk45")
    assert np.max(np.abs(tr["L.current"] - 2.5 * (1 - np.exp(-t / 0.25)))) < 1e-9


def test_lc_tank_conserves_energy(backend):
    L, C, g = Inductor(0.5, current=1.0, name="L"), Capacitor(2e-3, name="C"), Ground()
    s = System(L, C, g).connect(L.p, C.p).connect(L.n, C.n, g.terminal)
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 1, 2001)
    tr = model.simulate(t=t, solver="midpoint")
    assert np.max(np.abs(tr.energy - tr.energy[0])) < 1e-12 * max(1.0, tr.energy[0])
    w = 1 / np.sqrt(0.5 * 2e-3)
    assert (
        np.max(np.abs(tr["L.current"] - np.cos(w * t))) < 2e-3
    )  # midpoint phase error only


def test_thermal_rc(backend):
    body = ThermalMass(500.0, temperature=350.0, name="body")
    wall, amb, heater = (
        ThermalResistance(0.05, name="wall"),
        Ambient(300.0, name="ambient"),
        HeatSource(None, name="heater"),
    )
    s = (
        System(body, wall, amb, heater)
        .connect(body.port, wall.a, heater.port)
        .connect(wall.b, amb.port)
    )
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 200, 201)
    tr = model.simulate(t=t, inputs={"heater": 100.0}, solver="rk45")
    Tinf, tau = 300 + 100 * 0.05, 500 * 0.05
    assert np.max(np.abs(tr["body.temperature"] - (Tinf + 45 * np.exp(-t / tau)))) < 1e-7
    assert model.representation == "pseudo-port-hamiltonian"


def test_draining_tank_follows_torricelli(backend):
    A, a, cd = 1.0, 0.01, 0.6
    tank, drain, atm = (
        Tank(A, level=2.0, name="tank"),
        Orifice(a, discharge_coefficient=cd, name="drain"),
        Atmosphere(),
    )
    s = (
        System(tank, drain, atm)
        .connect(tank.port, drain.a)
        .connect(drain.b, atm.terminal)
    )
    model = otwin.compile(s, backend=backend)
    t = np.linspace(0, 100, 1001)
    tr = model.simulate(t=t, solver="rk45")
    kk = cd * a * np.sqrt(2 * 9.81) / A
    h = (np.sqrt(2.0) - kk * t / 2) ** 2
    assert np.max(np.abs(tr["tank.level"] - h)) < 1e-6
    # empties and stays empty
    t2 = np.linspace(0, 1000, 1001)
    tr2 = model.simulate(t=t2)
    assert tr2["tank.level"][-1] == pytest.approx(0.0, abs=1e-4)
    assert np.all(np.diff(tr2.energy) <= 1e-12)


def test_dc_motor_steady_state(backend):
    from otwin.components.catalogue import dc_motor

    L, J, Re, b, K = 0.5, 0.01, 1.0, 0.1, 0.5
    model = otwin.compile(dc_motor(L, J, Re, b, K), backend=backend)
    tr = model.simulate(t_span=(0, 5), dt=0.005, inputs={"supply": 12.0})
    omega_ss = K * 12.0 / (Re * b + K**2)
    i_ss = b * omega_ss / K
    assert tr["motor.rotor.angular_velocity"][-1] == pytest.approx(omega_ss, rel=1e-6)
    assert tr["motor.armature.current"][-1] == pytest.approx(i_ss, rel=1e-6)
    # electrical power in = mechanical loss + copper loss at steady state
    p_in = tr["supply.power"][-1]
    assert -p_in == pytest.approx(Re * i_ss**2 + b * omega_ss**2, rel=1e-6)
