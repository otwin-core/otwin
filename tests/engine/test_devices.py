"""Device components (Battery, Pump, Filter, Losses) and what makes them
compile: heat from losses, resistors written flow-first, series chains with
one-port ends.

Every number here is checked against a hand calculation, not against a
recorded run.
"""

from __future__ import annotations

import numpy as np
import pytest

import otwin
from otwin.compiler import CompileError
from otwin.components.base import Component, ResistorBranch
from otwin.components.battery import Battery
from otwin.components.electrical import (
    Capacitor,
    CurrentSource,
    Ground,
    Resistor,
    VoltageSource,
)
from otwin.components.hydraulic import (
    Atmosphere,
    Filter,
    FluidInertance,
    Orifice,
    Pipe,
    Pump,
    Tank,
)
from otwin.components.thermal import Ambient, Convection, Losses, ThermalMass

# ---------------------------------------------------------------- losses


def _rc_with_heat():
    r, c = Resistor(2.0, name="r"), Capacitor(1e-3, name="c")
    v, g = VoltageSource(None, name="v"), Ground(name="g")
    cell, q = ThermalMass(100.0, name="cell"), Losses(r, name="q")
    h, amb = Convection(1.0, name="h"), Ambient(293.15, name="amb")
    s = otwin.System(v, r, c, g, cell, q, h, amb)
    s.connect(v.p, r.p).connect(r.n, c.p).connect(c.n, v.n, g.port)
    s.connect(q.port, cell.port, h.a).connect(h.b, amb.port)
    return s


def test_losses_deliver_the_resistor_power_as_heat(backend):
    model = otwin.compile(_rc_with_heat(), backend=backend)
    run = model.simulate(t_span=(0, 0.01), dt=1e-5, inputs={"v": 10.0})
    # 10 V over 2 ohm at t = 0: 50 W into the cell
    assert run["q.heat_flow"][0] == pytest.approx(50.0)
    # the whole charging loss is C V^2 / 2 = 0.05 J, so dT = 0.05 / 100 K
    # (convection removes ~1e-6 of it in 10 ms)
    dT = run["cell.temperature"][-1] - 293.15
    assert dT == pytest.approx(5e-4, rel=1e-2)
    assert "pseudo" in model.summary()


def test_losses_need_a_dissipative_source():
    c, g = Capacitor(1.0, name="c"), Ground(name="g")
    i = CurrentSource(1.0, name="i")
    cell, q = ThermalMass(1.0, name="cell"), Losses(c, name="q")
    s = otwin.System(c, i, g, cell, q).connect(i.p, c.p).connect(c.n, i.n, g.port)
    s.connect(q.port, cell.port)
    with pytest.raises(CompileError, match="no resistor or damper"):
        otwin.compile(s)
    with pytest.raises(ValueError, match="at least one"):
        Losses()


# ---------------------------------------------------------------- battery

OCV = [(0.0, 3.0), (0.1, 3.4), (0.5, 3.7), (0.9, 3.95), (1.0, 4.15)]


def _battery_system(thermal=True):
    bat = Battery(
        capacity=2.5,
        ocv=OCV,
        resistance=0.03,
        rc_branches=[(0.02, 2000.0), (0.01, 20000.0)],
        thermal=50.0 if thermal else None,
        name="bat",
    )
    load, g = CurrentSource(None, name="load"), Ground(name="g")
    s = otwin.System(bat, load, g)
    # load.p -> load.n is the direction of the source current: out of bat.p
    s.connect(bat.p, load.n).connect(load.p, bat.n, g.port)
    if thermal:
        h, amb = Convection(0.5, name="h"), Ambient(298.15, name="amb")
        s.connect(bat.thermal, h.a).connect(h.b, amb.port)
    return s


def test_battery_discharges_at_1c_in_one_hour(backend):
    model = otwin.compile(_battery_system(), backend=backend, dt=1.0)
    run = model.simulate(t_span=(0, 3600), dt=1.0, inputs={"load": 2.5})
    assert run["bat.soc"][0] == pytest.approx(1.0)
    assert run["bat.soc"][-1] == pytest.approx(0.0, abs=1e-9)
    assert run["bat.current"][-1] == pytest.approx(2.5)
    # terminal voltage: OCV minus the drops. At t = 0 only R0 has a drop.
    assert run["bat.voltage"][0] == pytest.approx(4.15 - 2.5 * 0.03)
    # after an hour the RC pairs are charged: all 0.06 ohm show
    assert run["bat.voltage"][-1] == pytest.approx(3.0 - 2.5 * 0.06, abs=1e-6)
    # heat: I^2 R0 at first, I^2 (R0 + R1 + R2) once the RC pairs settle
    assert run["bat.heat_flow"][0] == pytest.approx(2.5**2 * 0.03)
    assert run["bat.heat_flow"][-1] == pytest.approx(2.5**2 * 0.06, rel=1e-6)
    # thermal steady state: 0.375 W over 0.5 W/K = 0.75 K (tau = 100 s)
    assert run["bat.temperature"][-1] - 298.15 == pytest.approx(0.75, rel=1e-6)


def test_battery_without_thermal_has_no_thermal_port(backend):
    bat = Battery(capacity=1.0, ocv=OCV, name="bat")
    assert set(bat.ports) == {"p", "n"}
    model = otwin.compile(_battery_system(thermal=False), backend=backend, dt=1.0)
    names = set(model.outputs(model.initial_state()))
    assert {"bat.soc", "bat.voltage", "bat.current"} <= names
    assert "bat.temperature" not in names


def test_battery_ocv_can_be_a_function(backend):
    bat = Battery(capacity=1.0, ocv=lambda soc: 3.0 + soc, ocv_points=11, name="bat")
    load, g = CurrentSource(0.0, name="load"), Ground(name="g")
    s = otwin.System(bat, load, g).connect(bat.p, load.n).connect(load.p, bat.n, g.port)
    model = otwin.compile(s, backend=backend, dt=1.0)
    assert model.outputs(model.initial_state())["bat.voltage"] == pytest.approx(4.0)


def test_battery_validates_its_arguments():
    with pytest.raises(ValueError, match="capacity"):
        Battery(capacity=0.0, ocv=OCV)
    with pytest.raises(ValueError, match="soc"):
        Battery(capacity=1.0, ocv=OCV, soc=1.5)
    with pytest.raises(ValueError, match="at least two"):
        Battery(capacity=1.0, ocv=[(0.0, 3.0)])
    with pytest.raises(ValueError, match="positive"):
        Battery(capacity=1.0, ocv=[(0.0, -1.0), (1.0, 4.0)])


# ---------------------------------------------------------------- pump line


def _pump_line(pump):
    return (
        Tank(area=20.0, level=2.0, name="tank")
        >> Pipe(resistance=2e6, name="pipe")
        >> pump
        >> Filter(resistance=1e6, name="filter")
        >> Atmosphere(name="out")
    )


def test_tank_pipe_pump_compiles_and_steps_without_equations(backend):
    system = _pump_line(Pump(shutoff=3e5, max_flow=0.05, name="pump"))
    assert system.unconnected() == []
    model = otwin.compile(system, backend=backend, dt=1.0)
    state = model.initial_state()
    for _ in range(600):
        state = model.step(state)
    out = model.outputs(state)
    Q, h = out["pump.flow"], out["tank.level"]
    # the operating point: tank head + pump curve = line losses, up to the
    # small inertial term while the tank keeps draining
    balance = 1000 * 9.81 * h + 3e5 * (1 - (Q / 0.05) ** 2) - (2e6 + 1e6) * Q
    assert abs(balance) < 5.0  # Pa, against ~1e5 Pa in play
    assert out["filter.pressure_drop"] == pytest.approx(1e6 * Q)
    assert out["pump.hydraulic_power"] == pytest.approx(out["pump.pressure_rise"] * Q)
    assert state.time == pytest.approx(600.0)


def test_fouled_filter_makes_the_pump_work_harder(backend):
    model = otwin.compile(
        _pump_line(Pump(shutoff=3e5, max_flow=0.05, name="pump")), backend=backend, dt=1.0
    )
    fouled = model.with_parameters({"filter.fouling": 2.0})
    outs = []
    for m in (model, fouled):
        st = m.initial_state()
        for _ in range(600):
            st = m.step(st)
        outs.append(m.outputs(st))
    clean, dirty = outs
    assert dirty["pump.flow"] < clean["pump.flow"]
    assert dirty["pump.pressure_rise"] > clean["pump.pressure_rise"]
    assert dirty["filter.pressure_drop"] == pytest.approx(3e6 * dirty["pump.flow"])


def test_tabulated_curve_matches_its_parabola(backend):
    pts = [(q, 3e5 * (1 - (q / 0.05) ** 2)) for q in np.linspace(0, 0.05, 51)]
    a = otwin.compile(
        _pump_line(Pump(shutoff=3e5, max_flow=0.05, name="pump")), backend=backend
    )
    b = otwin.compile(_pump_line(Pump(curve=pts, name="pump")), backend=backend)
    ra = a.simulate(t_span=(0, 600), dt=1.0)
    rb = b.simulate(t_span=(0, 600), dt=1.0)
    # the table is piecewise linear in Q: a 2% band is a fair check
    np.testing.assert_allclose(ra["pump.flow"], rb["pump.flow"], rtol=0.02)


def test_pump_validates_its_curve():
    with pytest.raises(ValueError, match="not both"):
        Pump(curve=[(0, 1.0), (1, 0.5)], shutoff=1.0)
    with pytest.raises(ValueError, match="flow 0"):
        Pump(curve=[(0.1, 1.0), (1, 0.5)])
    with pytest.raises(ValueError, match="must fall"):
        Pump(curve=[(0, 1.0), (1, 1.5)])
    with pytest.raises(ValueError, match="shutoff"):
        Pump()
    with pytest.raises(ValueError, match="must not be negative"):
        Filter(1.0, fouling=-0.1)


# -------------------------------------------- resistors written flow-first


class _TurbulentPipe(Component):
    """dp = K Q |Q| written the natural way, with no law of dp at all."""

    domain = "hydraulic"
    type_name = "turbulent_pipe"

    def __init__(self, friction: float, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.K = self.add_parameter("friction", friction, "Pa s^2/m^6")

    def branches(self):
        return [
            ResistorBranch(
                self, self.a, self.b, law=None, inverse=lambda q: self.K * q * abs(q)
            )
        ]


def _drain(pipe):
    return (
        Tank(area=2.0, level=3.0, name="tank")
        >> FluidInertance(1e6, name="water")
        >> pipe
        >> Atmosphere(name="atm")
    )


def test_flow_first_law_in_series_with_an_inertance_matches_the_inverted_one(backend):
    K = 5e7
    a = otwin.compile(_drain(_TurbulentPipe(K, name="pipe")), backend=backend)
    b = otwin.compile(_drain(Pipe(friction=K, name="pipe")), backend=backend)
    c = otwin.compile(_drain(Orifice(0.005, name="pipe")), backend=backend)
    ra = a.simulate(t_span=(0, 200), dt=0.5)
    rb = b.simulate(t_span=(0, 200), dt=0.5)
    np.testing.assert_allclose(ra.x, rb.x, rtol=1e-9, atol=1e-12)
    # the dissipation read off the structure is K |Q| >= 0
    R = (
        a.ir()
        .R[1][1]
        .evaluate(
            {
                "state:water.flow_momentum": 2e4,
                "param:water.inertance": 1e6,
                "param:pipe.friction": K,
            }
        )
    )
    assert pytest.approx(K * 0.02) == R  # dp/dQ secant: K |Q|
    assert c.simulate(t_span=(0, 10), dt=0.5)["tank.level"][-1] < 3.0


def test_flow_first_law_without_a_series_element_is_refused():
    t, pipe, atm = (
        Tank(1.0, level=1.0, name="tank"),
        _TurbulentPipe(1.0, name="pipe"),
        Atmosphere(name="atm"),
    )
    s = t >> pipe >> atm
    with pytest.raises(CompileError, match="series element"):
        otwin.compile(s)


# ---------------------------------------------------------------- chains


def test_chain_accepts_one_port_components_at_the_ends_and_in_the_middle():
    t1, p1 = Tank(1.0, level=1.0, name="t1"), Pipe(resistance=1.0, name="p1")
    t2, p2 = Tank(1.0, level=0.0, name="t2"), Pipe(resistance=1.0, name="p2")
    atm = Atmosphere(name="atm")
    s = t1 >> p1 >> t2 >> p2 >> atm
    assert s.unconnected() == []
    assert [tuple(p.qualified for p in c) for c in s.connections] == [
        ("t1.port", "p1.a"),
        ("p1.b", "t2.port"),
        ("t2.port", "p2.a"),
        ("p2.b", "atm.port"),
    ]
    model = otwin.compile(s)
    assert len(model.ir().states) == 2
