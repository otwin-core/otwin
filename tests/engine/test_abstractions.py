"""Component, Port, Connection and PhysicalSystem: the engineer's surface.

These tests pin down what the three abstractions mean, independently of any
physics: a port knows its domain and its two variables, a connection refuses
mixed domains, a system can be inspected before it is compiled, and the
fundamental components compile to the same model as their domain-specific
conveniences.
"""

from __future__ import annotations

import numpy as np
import pytest

import otwin
from otwin.components.base import Connection, Port
from otwin.components.electrical import Capacitor, Ground, Resistor, VoltageSource
from otwin.components.fundamental import Dissipator, Reference, Source, Storage
from otwin.components.mechanical import Damper, Fixed, Mass, Spring
from otwin.components.thermal import ThermalMass
from otwin.system import ConnectionError_, PhysicalSystem


def test_port_knows_its_domain_and_variables():
    m = Mass(1.0, name="m")
    assert isinstance(m.flange, Port)
    assert m.flange.domain == "mechanical"
    assert (m.flange.across, m.flange.through) == ("velocity", "force")
    assert m.flange.qualified == "m.flange"
    assert m.ports["flange"] is m.flange


def test_connection_joins_ports_of_one_domain_and_iterates_like_a_tuple():
    a, b, g = Spring(1.0, name="a"), Damper(1.0, name="b"), Fixed(name="g")
    c = Connection(a.b, b.b, g.port)
    assert c.domain == "mechanical"
    assert tuple(c) == (a.b, b.b, g.port)
    assert len(c) == 3 and a.b in c and c[0] is a.b


def test_connection_refuses_mixed_domains_and_single_ports():
    r, t = Resistor(1.0, name="r"), ThermalMass(1.0, name="t")
    with pytest.raises(ValueError, match="Transformer or a Gyrator"):
        Connection(r.p, t.port)
    with pytest.raises(ValueError, match="at least two"):
        Connection(r.p)


def test_system_is_inspectable_before_compiling():
    m, k, c, w = (
        Mass(1.0, name="m"),
        Spring(20.0, name="k"),
        Damper(0.3, name="c"),
        Fixed(name="w"),
    )
    s = otwin.System(m, k, c, w, name="osc")
    s.connect(m.flange, k.a, c.a).connect(k.b, c.b, w.port)
    assert isinstance(s, PhysicalSystem) and otwin.System is PhysicalSystem
    assert [x.name for x in s.components] == ["m", "k", "c", "w"]
    assert len(s.connections) == 2 and all(
        isinstance(x, Connection) for x in s.connections
    )
    assert s.domains == {"mechanical"}
    assert set(s.parameters) == {"m.mass", "k.stiffness", "c.damping"}
    assert s.parameters["k.stiffness"].value == 20.0
    assert s.unconnected() == []
    text = s.summary()
    assert "m.flange = k.a = c.a" in text and "stiffness=20 N/m" in text


def test_system_reports_loose_ports_and_mixed_domains():
    r, c = Resistor(1.0, name="r"), Capacitor(1.0, name="c")
    s = otwin.System(r, c)
    s.connect(r.n, c.p)
    assert {p.qualified for p in s.unconnected()} == {"r.p", "c.n"}
    with pytest.raises(ConnectionError_, match="different domains"):
        s.connect(r.p, ThermalMass(1.0, name="t").port)


def test_step_uses_the_time_step_given_at_compile(backend):
    m, k, c, w = (
        Mass(1.0, name="m"),
        Spring(20.0, name="k"),
        Damper(0.3, name="c"),
        Fixed(name="w"),
    )
    s = otwin.System(m, k, c, w).connect(m.flange, k.a, c.a).connect(k.b, c.b, w.port)
    model = otwin.compile(s, backend=backend, dt=0.01)
    state = model.initial_state()
    assert state.time == 0.0
    for _ in range(100):
        state = model.step(state)
    ref = otwin.compile(s, backend=backend).simulate(t_span=(0, 1), dt=0.01)
    np.testing.assert_allclose(state.values, ref.x[-1], atol=1e-12)
    assert state.time == pytest.approx(1.0)
    with pytest.raises(TypeError, match="dt"):
        otwin.compile(s, backend=backend).step(state)


def test_fundamental_components_match_their_domain_conveniences(backend):
    def rc(generic: bool):
        if generic:
            C = Storage("electrical", 1e-3, kind="across", name="C")
            R = Dissipator("electrical", 2.0, name="R")
            V = Source("electrical", None, kind="across", name="V")
            g = Reference(name="g")
        else:
            C, R, V, g = (
                Capacitor(1e-3, name="C"),
                Resistor(2.0, name="R"),
                VoltageSource(None, name="V"),
                Ground(name="g"),
            )
        s = otwin.System(V, R, C, g)
        s.connect(V.p, R.p).connect(R.n, C.p).connect(C.n, V.n, g.port)
        return otwin.compile(s, backend=backend).simulate(
            t_span=(0, 0.01), dt=1e-4, inputs={"V": 10.0}
        )

    a, b = rc(True), rc(False)
    np.testing.assert_allclose(a.x, b.x, atol=1e-12)
    assert a["C.voltage"][-1] == pytest.approx(b["C.voltage"][-1])


def test_fundamental_components_validate_their_arguments():
    with pytest.raises(ValueError, match="unknown domain"):
        Storage("magnetic", 1.0)
    with pytest.raises(ValueError, match="thermal has no through storage"):
        Storage("thermal", 1.0, kind="through")
    with pytest.raises(ValueError, match="kind"):
        Source("electrical", kind="sideways")


def test_outputs_of_a_stepped_state_see_the_inputs_of_that_step(backend):
    R, C = Resistor(2.0, name="R"), Capacitor(1e-3, name="C")
    V, g = VoltageSource(None, name="V"), Ground(name="g")
    s = otwin.System(V, R, C, g)
    s.connect(V.p, R.p).connect(R.n, C.p).connect(C.n, V.n, g.port)
    model = otwin.compile(s, backend=backend, dt=1e-5)
    state = model.step(model.initial_state(), {"V": 10.0})
    assert state.inputs is not None and state.inputs.tolist() == [10.0]
    out = model.outputs(state)
    # the resistor sees the 10 V minus the few millivolts on the capacitor
    assert 40.0 < out["R.power"] < 50.0
    assert model.outputs(state, {"V": 0.0})["R.power"] < 0.01  # the capacitor alone
    assert model.initial_state().inputs is None


def test_parameters_read_back_by_their_own_name():
    """The number given at construction is the number you read back, so a
    hand check uses exactly what the model uses."""
    from otwin.components.battery import Battery
    from otwin.components.hydraulic import Filter

    spring, mass = Spring(20.0, name="k"), Mass(1.5, name="m")
    assert spring.stiffness == 20.0 and mass.mass == 1.5
    assert Resistor(2.0).resistance == 2.0 and Filter(1e6, fouling=0.5).fouling == 0.5
    assert Battery(capacity=100.0, ocv=[(0.0, 3.0), (1.0, 4.0)]).capacity == 100.0
    # the short symbols used inside laws are untouched
    assert not isinstance(spring.k, float)
    with pytest.raises(AttributeError):
        _ = spring.length
