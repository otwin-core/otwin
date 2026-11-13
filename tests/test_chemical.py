"""Chemistry components, checked against closed forms.

Species are across storages whose across variable is the concentration;
reactions and outflows are one-way rate branches. The compiler writes the
mass balances. Every kinetic case here has an exact solution, and the
reactor cases have the textbook steady states. The compiler additions (the
rate branch, the recursive renaming of nested composites) are pinned too.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

import otwin
from otwin.compiler import CompileError
from otwin.components.base import DOMAINS, Ground, RateBranch
from otwin.components.chemical import (
    Accumulator,
    Dose,
    MixedReactor,
    Outflow,
    Reaction,
    Species,
    TanksInSeries,
)

K = 0.5


def compile_quiet(system: otwin.System) -> otwin.Model:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return otwin.compile(system)


# ------------------------------------------------------------------ kinetics


def test_first_order_a_to_b():
    a, b = Species(2.0, concentration=1.0, name="A"), Species(2.0, name="B")
    r = Reaction({"A": -1, "B": 1}, K, volume=2.0, name="r1")
    s = otwin.System(a, b, r)
    s.connect(a.port, r.A)
    s.connect(b.port, r.B)
    m = compile_quiet(s)
    assert m.representation == "pseudo-port-hamiltonian"
    assert r.parameters["k"].unit == "1/s"
    tr = m.simulate((0, 10), 0.01)
    assert np.max(np.abs(tr["A.amount"] - 2.0 * np.exp(-K * tr.t))) < 1e-5
    assert np.max(np.abs(tr["B.amount"] - 2.0 * (1 - np.exp(-K * tr.t)))) < 1e-5
    assert np.max(np.abs(tr["A.amount"] + tr["B.amount"] - 2.0)) < 1e-12
    assert tr["r1.rate"][0] == pytest.approx(K * 2.0)  # k V c0 = k n0
    assert tr["r1.A.rate"][0] == pytest.approx(K * 2.0)  # leaving A
    assert tr["r1.B.rate"][0] == pytest.approx(-K * 2.0)  # arriving at B
    assert tr["A.concentration"][0] == 1.0


def test_second_order_a_plus_b_to_p():
    """For c_A0 = c_B0 = c0: c = c0 / (1 + k c0 t). The rate is a product of two states."""
    a, b, p = (
        Species(2.0, concentration=1.0, name="A"),
        Species(2.0, concentration=1.0, name="B"),
        Species(2.0, name="P"),
    )
    r = Reaction({"A": -1, "B": -1, "P": 1}, K, volume=2.0, name="r")
    assert r.parameters["k"].unit == "m^3/(mol s)"
    assert r.order == {"A": 1.0, "B": 1.0}
    s = otwin.System(a, b, p, r)
    s.connect(a.port, r.A)
    s.connect(b.port, r.B)
    s.connect(p.port, r.P)
    tr = compile_quiet(s).simulate((0, 10), 0.01)
    assert np.max(np.abs(tr["A.concentration"] - 1 / (1 + K * tr.t))) < 1e-5
    assert np.max(np.abs(tr["A.amount"] + tr["P.amount"] - 2.0)) < 1e-12
    assert np.array_equal(tr["A.amount"], tr["B.amount"])


def test_dimerisation_2a_to_q_is_second_order_in_a():
    """2A -> Q: dc/dt = -2 k c^2, so c = c0 / (1 + 2 k c0 t), and n_A + 2 n_Q is conserved."""
    a, q = Species(1.0, concentration=1.0, name="A"), Species(1.0, name="Q")
    r = Reaction({"A": -2, "Q": 1}, K, name="dim")
    assert r.order == {"A": 2.0}
    s = otwin.System(a, q, r)
    s.connect(a.port, r.A)
    s.connect(q.port, r.Q)
    tr = compile_quiet(s).simulate((0, 10), 0.01)
    assert np.max(np.abs(tr["A.concentration"] - 1 / (1 + 2 * K * tr.t))) < 1e-5
    assert np.max(np.abs(tr["A.amount"] + 2 * tr["Q.amount"] - 1.0)) < 1e-12


def test_consecutive_reactions():
    k1, k2 = 0.5, 0.2
    a, b, c = (
        Species(1.0, concentration=1.0, name="A"),
        Species(1.0, name="B"),
        Species(1.0, name="C"),
    )
    r1, r2 = (
        Reaction({"A": -1, "B": 1}, k1, name="r1"),
        Reaction({"B": -1, "C": 1}, k2, name="r2"),
    )
    s = otwin.System(a, b, c, r1, r2)
    s.connect(a.port, r1.A)
    s.connect(b.port, r1.B, r2.B)
    s.connect(c.port, r2.C)
    tr = compile_quiet(s).simulate((0, 20), 0.01)
    t = tr.t
    closed = k1 / (k2 - k1) * (np.exp(-k1 * t) - np.exp(-k2 * t))
    assert np.max(np.abs(tr["B.amount"] - closed)) < 1e-5
    assert np.max(np.abs(tr["A.amount"] + tr["B.amount"] + tr["C.amount"] - 1.0)) < 1e-12


def test_a_custom_rate_law_and_an_explicit_order():
    a = Species(2.0, concentration=1.0, name="A")
    monod = Reaction(
        {"A": -1}, 0.5, volume=2.0, rate=lambda c, k: k * c["A"] / (1 + c["A"]), name="m"
    )
    s = otwin.System(a, monod)
    s.connect(a.port, monod.A)
    tr = compile_quiet(s).simulate((0, 1), 0.01)
    assert tr["m.rate"][0] == pytest.approx(0.5 * 2.0 * 1.0 / 2.0)
    first_in_a = Reaction({"A": -2, "Q": 1}, K, order={"A": 1})
    assert first_in_a.order == {"A": 1.0} and first_in_a.parameters["k"].unit == "1/s"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"stoichiometry": {"A": 1}}, "no reactant"),
        ({"stoichiometry": {"A": -1}, "order": {"Z": 1}}, "not in the reaction"),
        ({"stoichiometry": {"ports": -1}}, "cannot be a species name"),
        ({"stoichiometry": {"A": 0}}, "coefficient 0"),
        ({"stoichiometry": {"a-b": -1}}, "plain identifier"),
        ({"stoichiometry": {}}, "at least one species"),
    ],
)
def test_a_malformed_reaction_is_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Reaction(**kwargs)


# ------------------------------------------------------------------ reactors


def test_a_dosed_mixed_reactor_with_accumulated_outflows():
    q, c_in, v = 1.0, 3.0, 2.0
    tau = v / q
    rx = Reaction({"A": -1, "B": 1}, K, name="decay")
    cstr = MixedReactor(v, q, {"A": 0.0, "B": 0.0}, [rx], name="cstr")
    assert rx.parameters["volume"].value == v  # the reactor set it
    feed, acc_a, acc_b = (
        Dose(None, name="feed"),
        Accumulator(name="accA"),
        Accumulator(name="accB"),
    )
    s = otwin.System(cstr, feed, acc_a, acc_b)
    s.connect(feed.port, cstr.in_A)
    s.connect(cstr.out_A, acc_a.port)
    s.connect(cstr.out_B, acc_b.port)
    m = compile_quiet(s)
    assert m.input_names == ["feed"]
    assert m.state_names == [
        "cstr.A.amount",
        "cstr.B.amount",
        "accA.amount",
        "accB.amount",
    ]
    tr = m.simulate((0, 30), 0.01, inputs={"feed": q * c_in})
    c_ss = c_in / (1 + K * tau)
    c = tr["cstr.A.concentration"]
    assert np.max(np.abs(c - c_ss * (1 - np.exp(-tr.t * (1 / tau + K))))) < 1e-5
    assert tr["cstr.B.concentration"][-1] == pytest.approx(c_in - c_ss, abs=1e-5)
    assert tr["accA.amount"][-1] == pytest.approx(
        np.trapezoid(tr["cstr.out_A.rate"], tr.t), rel=1e-6
    )
    assert tr["cstr.decay.rate"][-1] == pytest.approx(K * v * c_ss, rel=1e-5)


def test_a_dose_into_an_accumulator_integrates_the_schedule():
    d, acc = Dose(2.0, name="d"), Accumulator(name="acc")
    s = otwin.System(d, acc)
    s.connect(d.port, acc.port)
    tr = compile_quiet(s).simulate((0, 5), 0.1)
    assert tr["acc.amount"][-1] == pytest.approx(10.0)


@pytest.mark.parametrize("n", [1, 4, 16])
def test_tanks_in_series_approach_plug_flow(n: int):
    """Outlet of a first-order reaction: (1 + k tau / n)^-n, tending to exp(-k tau)."""
    q, c_in, v = 1.0, 3.0, 2.0
    train = TanksInSeries(
        n, v, q, {"A": 0.0}, [Reaction({"A": -1}, K, name="decay")], name="pfr"
    )
    feed, sink = Dose(q * c_in, name="feed"), Ground(name="sink")
    s = otwin.System(train, feed, sink)
    s.connect(feed.port, train.in_A)
    s.connect(train.out_A, sink.port)
    m = compile_quiet(s)
    assert m.n_states == n
    assert (
        m.state_names[0] == "pfr.tank0.A.amount"
    )  # nested composites are fully prefixed
    tr = m.simulate((0, 40), 0.005)
    ratio = tr[f"pfr.tank{n - 1}.A.concentration"][-1] / c_in
    assert ratio == pytest.approx((1 + K * (v / q) / n) ** (-n), abs=2e-4)


def test_an_unconnected_outlet_is_refused():
    cstr, feed = MixedReactor(2.0, 1.0, {"A": 1.0}, name="c"), Dose(1.0, name="feed")
    s = otwin.System(cstr, feed)
    s.connect(feed.port, cstr.in_A)
    with pytest.raises(CompileError, match="c.out_A.b"):
        compile_quiet(s)


def test_a_reaction_naming_a_species_the_reactor_lacks_is_refused():
    with pytest.raises(ValueError, match="names species \\['B'\\]"):
        MixedReactor(1.0, 1.0, {"A": 1.0}, [Reaction({"A": -1, "B": 1}, K)])


def test_clone_is_independent():
    r1 = Reaction({"A": -1, "B": 1}, 0.3, volume=4.0, name="x")
    r2 = r1.clone("y")
    assert (r2.parameters["k"].value, r2.parameters["volume"].value, r2.name) == (
        0.3,
        4.0,
        "y",
    )
    assert r1.ports["A"] is not r2.ports["A"]


# ------------------------------------------------------------- the compiler


def test_the_rate_branch_is_one_way_and_outside_j_and_r():
    """An outflow carries Q c_a from a to b whatever c_b is, and J = R = 0."""
    up, down = (
        Species(1.0, concentration=1.0, name="up"),
        Species(1.0, concentration=5.0, name="down"),
    )
    flow, sink = Outflow(0.5, name="flow"), Ground(name="sink")
    out2 = Outflow(0.5, name="flow2")
    s = otwin.System(up, down, flow, out2, sink)
    s.connect(up.port, flow.a)
    s.connect(flow.b, down.port, out2.a)
    s.connect(out2.b, sink.port)
    m = compile_quiet(s)
    assert isinstance(flow.branches()[0], RateBranch)
    tr = m.simulate((0, 10), 0.01)
    assert (
        np.max(np.abs(tr["up.amount"] - np.exp(-0.5 * tr.t))) < 1e-5
    )  # unaffected by the 5 downstream
    env = m._ir.environment(m._ir.initial_state())
    for mat in (m._ir.J, m._ir.R):
        assert all(e.evaluate(env) == 0.0 for row in mat for e in row)
    assert m.representation == "pseudo-port-hamiltonian"
    assert DOMAINS["chemical"].power_conjugate is False


@pytest.mark.parametrize("dt", [0.1, 1.0, 3.0, 10.0, 100.0])
def test_patankar_keeps_amounts_non_negative_and_mass_exact_at_any_step(dt: float):
    """A -> B: euler fails at k dt > 1, midpoint at k dt > 2; patankar never does,
    and n_A + n_B stays 2 to round-off. The first step is Patankar-Euler exactly."""
    a, b = Species(2.0, concentration=1.0, name="A"), Species(2.0, name="B")
    r = Reaction({"A": -1, "B": 1}, K, volume=2.0, name="r")
    s = otwin.System(a, b, r)
    s.connect(a.port, r.A)
    s.connect(b.port, r.B)
    tr = compile_quiet(s).simulate((0, 200), dt, solver="patankar")
    assert tr["A.amount"].min() >= 0
    assert np.max(np.abs(tr["A.amount"] + tr["B.amount"] - 2.0)) < 1e-12
    assert tr["A.amount"][1] == pytest.approx(2.0 / (1 + K * dt), rel=1e-12)
    assert np.all(np.diff(tr["A.amount"]) <= 0) and tr["A.amount"][-1] < tr["A.amount"][1]
    assert tr.stats["rejected_steps"] == 0  # no halving needed at any k dt


def test_patankar_is_first_order():
    a = Species(1.0, concentration=1.0, name="A")
    r = Reaction({"A": -1}, 1.0, name="r")
    s = otwin.System(a, r)
    s.connect(a.port, r.A)
    m = compile_quiet(s)
    errs = [
        abs(m.simulate((0, 1), dt, solver="patankar")["A.amount"][-1] - np.exp(-1))
        for dt in (0.1, 0.05, 0.025)
    ]
    ratios = np.array(errs[:-1]) / np.array(errs[1:])
    assert np.all((ratios > 1.8) & (ratios < 2.2))


def test_patankar_keeps_every_invariant_of_a_second_order_reaction():
    """A + B -> P with excess A, at k c dt = 5: B runs out without going negative,
    and both n_A - n_B and n_A + n_P are exact."""
    a, b, p = (
        Species(2.0, concentration=1.0, name="A"),
        Species(2.0, concentration=0.5, name="B"),
        Species(2.0, name="P"),
    )
    r = Reaction({"A": -1, "B": -1, "P": 1}, 2.0, volume=2.0, name="r")
    s = otwin.System(a, b, p, r)
    s.connect(a.port, r.A)
    s.connect(b.port, r.B)
    s.connect(p.port, r.P)
    tr = compile_quiet(s).simulate((0, 50), 5.0, solver="patankar")
    assert tr["B.amount"].min() >= 0 and tr["B.amount"][-1] < 1e-6
    assert tr["A.amount"][-1] == pytest.approx(1.0, abs=1e-6)  # the excess
    assert np.ptp(tr["A.amount"] - tr["B.amount"]) < 1e-12
    assert np.ptp(tr["A.amount"] + tr["P.amount"]) < 1e-12


def test_patankar_reaches_the_reactor_steady_state_with_a_large_step():
    rx = Reaction({"A": -1, "B": 1}, K, name="decay")
    cstr = MixedReactor(2.0, 1.0, {"A": 0.0, "B": 0.0}, [rx], name="cstr")
    feed, sink = Dose(3.0, name="feed"), Ground(name="sink")
    s = otwin.System(cstr, feed, sink)
    s.connect(feed.port, cstr.in_A)
    s.connect(cstr.out_A, sink.port)
    s.connect(cstr.out_B, sink.port)
    tr = compile_quiet(s).simulate((0, 200), 4.0, solver="patankar")  # dt = 2 tau
    assert tr["cstr.A.concentration"][-1] == pytest.approx(1.5, abs=1e-9)
    assert tr["cstr.B.concentration"][-1] == pytest.approx(1.5, abs=1e-9)
    assert tr["cstr.A.concentration"].min() >= 0


def test_rate_groups_survive_a_save_and_load():
    a, b = Species(2.0, concentration=1.0, name="A"), Species(2.0, name="B")
    r = Reaction({"A": -1, "B": 1}, K, volume=2.0, name="r")
    s = otwin.System(a, b, r)
    s.connect(a.port, r.A)
    s.connect(b.port, r.B)
    m = compile_quiet(s)
    m2 = otwin.Model.from_json(m._ir.to_json(), backend="numpy")
    assert [g.component for g in m2._ir.rate_groups] == ["r"]
    assert [(i, j) for i, j, _ in m2._ir.rate_groups[0].flows] == [(0, None), (1, None)]
    t1 = m.simulate((0, 10), 2.0, solver="patankar")["A.amount"]
    t2 = m2.simulate((0, 10), 2.0, solver="patankar")["A.amount"]
    assert np.array_equal(t1, t2)


def test_patankar_on_a_model_without_rate_groups_is_the_patankar_trick():
    """An RC circuit: no reaction groups, so each state's own destruction is
    weighted. Positive and first order, but there is nothing to conserve."""
    from otwin.components.electrical import Capacitor, Resistor
    from otwin.components.electrical import Ground as Gnd

    c, res, g = (
        Capacitor(1.0, voltage=1.0, name="c"),
        Resistor(1.0, name="r"),
        Gnd(name="g"),
    )
    s = otwin.System(c, res, g)
    s.connect(c.p, res.p)
    s.connect(c.n, res.n, g.port)
    tr = compile_quiet(s).simulate((0, 5), 0.5, solver="patankar")
    assert tr.x[-1, 0] == pytest.approx((1 / 1.5) ** 10, rel=1e-9)


def test_positivity_depends_on_the_step_and_a_rate_never_goes_negative():
    """With the general solvers, whether n undershoots zero depends on k dt:
    at k dt = 1 every solver stays non-negative; euler at k dt = 1.5 does not,
    and the rate then reads max(n, 0), so it stops rather than reverses. This
    is why chemistry uses solver="patankar"."""
    a = Species(2.0, concentration=1.0, name="A")
    r = Reaction({"A": -1}, K, volume=2.0, name="r")
    s = otwin.System(a, r)
    s.connect(a.port, r.A)
    m = compile_quiet(s)
    for solver in ("euler", "rk4", "midpoint"):
        assert m.simulate((0, 30), 1 / K, solver=solver)["A.amount"].min() >= 0, solver
    bad = m.simulate((0, 30), 3.0, solver="euler")
    assert bad["A.amount"].min() < 0
    assert np.all(bad["r.rate"] >= 0)
