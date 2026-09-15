"""Physical properties that must hold for every model the compiler produces."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import otwin
from otwin import System
from otwin.components.electrical import Capacitor, Ground, Inductor, Resistor

positive = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)


def ladder(rs, cs, ls):
    """Ground - R - C || L - R - C || L ... a passive RLC ladder with no sources."""
    parts = []
    g = Ground(name="g")
    s = System(g)
    prev = g.terminal
    for i, (r, c, ind) in enumerate(zip(rs, cs, ls, strict=True)):
        R = Resistor(r, name=f"R{i}")
        C = Capacitor(c, voltage=1.0 + i, name=f"C{i}")
        L = Inductor(ind, current=0.5, name=f"L{i}")
        s.add(R, C, L)
        s.connect(prev, R.p)
        s.connect(R.n, C.p, L.p)
        s.connect(C.n, L.n, g.terminal)
        prev = R.n
        parts.append((R, C, L))
    return s


@settings(deadline=None, max_examples=25)
@given(
    st.integers(min_value=1, max_value=4).flatmap(
        lambda n: st.tuples(
            st.lists(positive, min_size=n, max_size=n),
            st.lists(positive, min_size=n, max_size=n),
            st.lists(positive, min_size=n, max_size=n),
        )
    )
)
def test_passive_networks_never_gain_energy(params):
    rs, cs, ls = params
    m = otwin.compile(ladder(rs, cs, ls))
    chk = m.check_structure()
    assert chk["J_skew"][0] and chk["R_psd"][0]
    tr = m.simulate(t_span=(0, 5), dt=0.01)
    assert np.all(np.diff(tr.energy) <= 1e-9 * max(1.0, tr.energy[0]))
    assert tr.energy_balance()["max_violation"] <= 1e-9 * max(1.0, tr.energy[0])


@settings(deadline=None, max_examples=15)
@given(
    positive, positive, positive, st.floats(min_value=-5, max_value=5, allow_nan=False)
)
def test_rc_source_power_accounting(r, c, v, x0):
    """Supplied power equals dH/dt plus dissipation at every state."""
    from otwin.components.electrical import VoltageSource

    V, R, C, g = (
        VoltageSource(v, name="V"),
        Resistor(r, name="R"),
        Capacitor(c, voltage=x0, name="C"),
        Ground(),
    )
    s = (
        System(V, R, C, g)
        .connect(V.p, R.p)
        .connect(R.n, C.p)
        .connect(C.n, V.n, g.terminal)
    )
    m = otwin.compile(s)
    pb = m.power_balance(m.initial_state())
    assert pb["dH_dt"] == pytest.approx(
        pb["supplied"] + pb["dissipated"], rel=1e-9, abs=1e-12
    )
    assert pb["dissipated"] <= 1e-12


@settings(deadline=None, max_examples=15)
@given(positive, positive)
def test_dimensions_are_consistent(m, k):
    from otwin.components.mechanical import Fixed, Mass, Spring

    mass, spring, wall = Mass(m, name="m"), Spring(k, extension=1.0, name="k"), Fixed()
    s = (
        System(mass, spring, wall)
        .connect(mass.flange, spring.a)
        .connect(spring.b, wall.terminal)
    )
    model = otwin.compile(s)
    assert model.n_states == 2
    assert [d["unit"] for d in model.states()] == ["kg m/s", "m"]
    ir = model.ir()
    assert [i.unit for i in ir.inputs] == []
    # energy of the initial state is the spring energy alone
    assert model.energy(model.initial_state()) == pytest.approx(0.5 * k)
