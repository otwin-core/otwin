"""The compiler: nodes, structure extraction and physical error messages."""

import warnings

import numpy as np
import pytest

import otwin
from otwin import CompileError, System
from otwin.compiler import compile_system
from otwin.components.electrical import (
    Capacitor,
    CurrentSource,
    Ground,
    Inductor,
    Resistor,
    VoltageSource,
)
from otwin.components.hydraulic import Atmosphere, Orifice, Tank
from otwin.components.mechanical import Damper, Fixed, ForceSource, Mass, Spring
from otwin.components.rotational import Housing, Inertia, RotationalDamper
from otwin.components.twoport import Transformer
from otwin.ir import PHSIR


def msd(force=None):
    m, k, c, w = (
        Mass(2.0, name="m"),
        Spring(8.0, extension=0.1, name="k"),
        Damper(0.5, name="c"),
        Fixed(),
    )
    f = ForceSource(force, name="F")
    s = System(k, m, c, w, f)
    s.connect(m.flange, k.a, c.a, f.flange)
    s.connect(k.b, c.b, w.terminal)
    return s


def test_msd_structure():
    ir = compile_system(msd())
    assert ir.state_names() == ["k.extension", "m.momentum"]
    assert ir.input_names() == ["F"]
    env = ir.environment([0.1, 0.4])
    J = np.array([[e.evaluate(env) for e in row] for row in ir.J])
    R = np.array([[e.evaluate(env) for e in row] for row in ir.R])
    G = np.array([[e.evaluate(env) for e in row] for row in ir.G])
    assert np.allclose(J, [[0, 1], [-1, 0]])
    assert np.allclose(R, [[0, 0], [0, 0.5]])
    assert np.allclose(G, [[0], [1]])
    assert ir.energy.evaluate(env) == pytest.approx(0.5 * 8 * 0.01 + 0.16 / 4)
    dx = [e.evaluate(ir.environment([0.1, 0.4], [3.0])) for e in ir.rhs]
    assert dx == pytest.approx([0.2, 3.0 - 0.8 - 0.5 * 0.2])


def test_ir_json_roundtrip():
    ir = compile_system(msd())
    back = PHSIR.from_json(ir.to_json())
    assert back.rhs == ir.rhs
    assert back.state_names() == ir.state_names()
    assert back.physical is not None and len(back.physical.components) == 5


def test_lowered_table_is_symbol_free():
    low = compile_system(msd()).lower()
    assert "sym" not in str(low["rhs"])
    assert low["n_states"] == 2 and low["n_inputs"] == 1


def test_domain_mismatch_is_rejected_at_connect():
    m, r = Mass(), Resistor()
    with pytest.raises(ValueError, match="incompatible connection"):
        System(m, r).connect(m.flange, r.p)


def test_dangling_terminal():
    v, r, c, g = VoltageSource(1.0), Resistor(1.0), Capacitor(1.0), Ground()
    s = System(v, r, c, g).connect(v.p, r.p).connect(v.n, c.n, g.terminal)
    with pytest.raises(CompileError, match="not connected"):
        compile_system(s)


def test_dependent_storages_are_named():
    c1, c2, g = Capacitor(1.0, name="c1"), Capacitor(2.0, name="c2"), Ground()
    s = System(c1, c2, g).connect(c1.p, c2.p).connect(c1.n, c2.n, g.terminal)
    with pytest.raises(CompileError, match="dependent storages or sources") as info:
        compile_system(s)
    assert "c1" in str(info.value) and "c2" in str(info.value)


def test_voltage_source_across_capacitor_is_dependent():
    v, c, g = VoltageSource(1.0, name="V"), Capacitor(1.0, name="C"), Ground()
    s = System(v, c, g).connect(v.p, c.p).connect(v.n, c.n, g.terminal)
    with pytest.raises(CompileError, match="dependent"):
        compile_system(s)


def test_no_storage():
    v, r, g = VoltageSource(1.0), Resistor(1.0), Ground()
    s = System(v, r, g).connect(v.p, r.p).connect(v.n, r.n, g.terminal)
    with pytest.raises(CompileError, match="stores no energy"):
        compile_system(s)


def test_nonlinear_algebraic_loop_is_refused():
    # source - nonlinear resistor - linear resistor - inductor: the middle node is
    # not pinned and the nonlinear law sits on it
    v, r1, r2, ind, g = (
        VoltageSource(1.0, name="V"),
        Resistor(1.0, law=lambda u: u * abs(u), name="nl"),
        Resistor(1.0, name="lin"),
        Inductor(1.0, name="L"),
        Ground(),
    )
    s = (
        System(v, r1, r2, ind, g)
        .connect(v.p, r1.p)
        .connect(r1.n, r2.p)
        .connect(r2.n, ind.p)
    )
    s.connect(ind.n, v.n, g.terminal)
    with pytest.raises(CompileError, match="nonlinear algebraic loop"):
        compile_system(s)


def test_singular_network_is_refused():
    # a current source feeding only an inductor: the node potential is undetermined
    i, ind, g = CurrentSource(1.0, name="I"), Inductor(1.0, name="L"), Ground()
    s = System(i, ind, g).connect(i.p, ind.p).connect(i.n, ind.n, g.terminal)
    with pytest.raises(CompileError, match="singular"):
        compile_system(s)


def test_duplicate_names():
    with pytest.raises(ValueError, match="named"):
        System(Mass(name="m"), Mass(name="m"))


def test_bad_parameter():
    with pytest.raises(ValueError, match="must be positive"):
        Mass(-1.0)


def test_unconnected_ground_warns():
    m = Mass(name="m")
    s = System(m, Fixed(name="wall"))
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        compile_system(s)
    assert any("not connected" in str(x.message) for x in w)


def test_transformer_couples_domains():
    v, r, tf, j, b, g, h = (
        VoltageSource(None, name="V"),
        Resistor(1.0, name="R"),
        Transformer(2.0, domain_1="electrical", domain_2="rotational", name="tf"),
        Inertia(0.5, name="J"),
        RotationalDamper(0.1, name="b"),
        Ground(),
        Housing(),
    )
    s = System(v, r, tf, j, b, g, h)
    s.connect(v.p, r.p).connect(r.n, tf.p1).connect(tf.n1, v.n, g.terminal)
    s.connect(tf.p2, j.shaft, b.a).connect(tf.n2, b.b, h.terminal)
    ir = compile_system(s)
    # the electrical side has no inductor, so the current is algebraic:
    # i = (V - omega/2) / R, torque on the shaft = -i2 = i / 2 ... check power balance
    env = ir.environment([0.5 * 3.0], [4.0])  # omega = 3 rad/s, V = 4 V
    i = (4.0 - 3.0 / 2.0) / 1.0  # across_2 = ratio * across_1 -> omega = 2 v1 -> v1 = 1.5
    dp = [e.evaluate(env) for e in ir.rhs][0]
    torque_from_tf = i / 2.0  # through_1 = -ratio * through_2, delivered to the shaft
    assert dp == pytest.approx(torque_from_tf - 0.1 * 3.0)


def test_thermal_is_flagged_pseudo():
    from otwin.components.thermal import Ambient, ThermalMass, ThermalResistance

    b, w, a = ThermalMass(10.0, temperature=300.0), ThermalResistance(1.0), Ambient(290.0)
    s = System(b, w, a).connect(b.port, w.a).connect(w.b, a.port)
    assert compile_system(s).representation == "pseudo-port-hamiltonian"


def test_tank_compiles_to_torricelli():
    tank, drain, atm = (
        Tank(2.0, level=1.0, name="tank"),
        Orifice(0.01, name="drain"),
        Atmosphere(),
    )
    s = (
        System(tank, drain, atm)
        .connect(tank.port, drain.a)
        .connect(drain.b, atm.terminal)
    )
    ir = compile_system(s)
    env = ir.environment([2.0 * 1.0])
    dv = ir.rhs[0].evaluate(env)
    assert dv == pytest.approx(-0.6 * 0.01 * np.sqrt(2 * 9.81 * 1.0))
    R = ir.R[0][0].evaluate(env)
    assert R > 0


def test_compile_accepts_single_component_and_sequences():
    m = otwin.compile(Mass(1.0, velocity=1.0, name="free"))
    assert m.n_states == 1
    tr = m.simulate(t_span=(0, 1), dt=0.1)
    assert np.allclose(tr["free.momentum"], 1.0)


def test_summary_mentions_representation_and_states():
    m = otwin.compile(msd())
    text = m.summary()
    assert "k.extension" in text and "port-hamiltonian" in text and "Inputs:" in text
