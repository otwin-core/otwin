"""The compiled Model: parameters, states, outputs, closed loops, persistence, estimators."""

import numpy as np
import pytest

import otwin
from otwin import CustomDynamics, State, System
from otwin.components import catalogue
from otwin.components.mechanical import Damper, Fixed, ForceSource, Mass, Spring
from otwin.components.rotational import Housing, Inertia, RotationalDamper
from otwin.estimate import ExtendedKalmanFilter, MovingHorizonEstimator
from otwin.runtime import engine_available


def oscillator(backend="auto"):
    return otwin.compile(
        catalogue.mass_spring_damper(1.0, 20.0, 0.3, position=1.0), backend=backend
    )


def test_parameters_change_without_recompiling(backend):
    m = oscillator(backend)
    assert m.parameters["spring.stiffness"] == 20.0
    tr1 = m.simulate(t_span=(0, 1), dt=0.01)
    m.set_parameters({"spring.stiffness": 40.0})
    tr2 = m.simulate(t_span=(0, 1), dt=0.01)
    assert not np.allclose(tr1.x, tr2.x)
    m2 = (
        m.with_parameters(stiffness=20.0)
        if False
        else m.with_parameters({"spring.stiffness": 20.0})
    )
    assert np.allclose(m2.simulate(t_span=(0, 1), dt=0.01).x, tr1.x)
    with pytest.raises(KeyError, match="spring.stiffness"):
        m.set_parameters(stiffness=1.0)


def test_state_helpers(backend):
    m = oscillator(backend)
    s0 = m.initial_state()
    assert isinstance(s0, State) and s0["spring.extension"] == 1.0
    s = m.state({"mass.momentum": 2.0})
    assert s["mass.momentum"] == 2.0 and s["spring.extension"] == 1.0
    nxt = m.step(s, {"force": 0.0}, dt=0.01)
    assert nxt.time == pytest.approx(0.01)
    assert nxt["spring.extension"] == pytest.approx(1.0 + 0.01 * 2.0, rel=2e-3)


def test_outputs_and_trajectory_indexing(backend):
    m = oscillator(backend)
    out = m.outputs(m.initial_state())
    assert out["spring.force"] == pytest.approx(20.0)
    assert out["mass.velocity"] == 0.0
    tr = m.simulate(t_span=(0, 1), dt=0.01, inputs={"force": np.ones(101)})
    assert tr["force"].shape == (101,) and tr["force"][0] == 1.0
    assert tr["damper.power"].shape == (101,)
    assert set(["t", "energy", "mass.momentum"]) <= set(tr.keys())
    with pytest.raises(KeyError, match="not a state"):
        tr["nothing"]
    assert tr.final().time == pytest.approx(1.0)


def test_input_forms(backend):
    m = oscillator(backend)
    t = np.linspace(0, 1, 11)
    a = m.simulate(t=t, inputs={"force": 2.0})
    b = m.simulate(t=t, inputs=np.full((11, 1), 2.0))
    c = m.simulate(t=t, inputs={"force": lambda tt: 2.0})
    d = m.simulate(t=t, inputs=2.0)
    for other in (b, c, d):
        assert np.allclose(a.x, other.x)
    with pytest.raises(KeyError, match="not an input"):
        m.simulate(t=t, inputs={"torque": 1.0})
    with pytest.raises(ValueError, match="shape"):
        m.simulate(t=t, inputs=np.zeros((5, 1)))


def test_feedback_callable_is_sample_and_hold(backend):
    m = oscillator(backend)
    t = np.linspace(0, 2, 201)
    tr = m.simulate(t=t, inputs={"force": lambda tt, x: -5.0 * x[1]})
    assert tr.stats.get("feedback") is True
    # extra damping: energy falls faster than without the law
    ref = m.simulate(t=t)
    assert tr.energy[-1] < ref.energy[-1]


def test_closed_loop_expression(backend):
    m = oscillator(backend)
    v = m.symbol("mass.velocity")
    closed = m.closed_loop(force=-5.0 * v)
    assert closed.n_inputs == 0 and "force" in closed.output_names
    t = np.linspace(0, 2, 201)
    tr = closed.simulate(t=t)
    assert np.allclose(tr["force"], -5.0 * tr["mass.velocity"])
    # the same via simulate(inputs=Expr)
    tr2 = m.simulate(t=t, inputs={"force": -5.0 * v})
    assert np.allclose(tr.x, tr2.x)
    with pytest.raises(ValueError, match="depends on itself"):
        m.closed_loop(force=m.symbol("force") + 1)


def test_save_and_load(tmp_path, backend):
    m = oscillator(backend)
    m.set_parameters({"damper.damping": 0.7})
    p = m.save(tmp_path / "osc.otwin.json")
    m2 = otwin.Model.load(p, backend=backend)
    assert m2.parameters["damper.damping"] == 0.7
    t = np.linspace(0, 1, 51)
    assert np.allclose(m.simulate(t=t).x, m2.simulate(t=t).x)
    text = m.to_json()
    assert '"level": "phs"' in text


def test_structure_and_power_balance(backend):
    m = oscillator(backend)
    chk = m.check_structure()
    assert chk["J_skew"][0] and chk["R_psd"][0]
    S = m.structure()
    assert np.allclose(S["J"], [[0, 1], [-1, 0]]) and np.allclose(
        S["R"], [[0, 0], [0, 0.3]]
    )
    pb = m.power_balance([0.5, 2.0], {"force": 3.0})
    assert pb["dH_dt"] == pytest.approx(pb["dissipated"] + pb["supplied"])
    assert pb["supplied"] == pytest.approx(3.0 * 2.0)
    assert pb["dissipated"] == pytest.approx(-0.3 * 4.0)


def test_batch(backend):
    m = oscillator(backend)
    t = np.linspace(0, 1, 21)
    x0s = np.array([[1.0, 0.0], [0.5, 0.0], [0.0, 1.0]])
    out = m.simulate_batch(x0s, t)
    assert out["x"].shape == (3, 21, 2) and out["energy"].shape == (3, 21)
    single = m.simulate(t=t, x0=x0s[1])
    assert np.allclose(out["x"][1], single.x)
    out2 = m.simulate_batch(
        x0s, t, parameters=[{"spring.stiffness": k} for k in (10.0, 20.0, 40.0)]
    )
    assert not np.allclose(out2["x"][0], out2["x"][2])
    assert np.allclose(out2["x"][1], out["x"][1])


def test_model_is_a_twin_model_for_the_estimators(backend):
    """Notebook 05: a tachometer on a flywheel, filtered by the EKF and the MHE."""
    I_fw, C1, C2 = 1200.0, 0.020, 2.0e-6
    rotor = Inertia(I_fw, speed=700.0, name="rotor")
    bearing = RotationalDamper(law=lambda w: (C1 + C2 * w**2) * w, name="bearing")
    housing = Housing()
    s = (
        System(rotor, bearing, housing)
        .connect(rotor.shaft, bearing.a)
        .connect(bearing.b, housing.terminal)
    )
    model = otwin.compile(s, backend=backend, measurements=["rotor.angular_velocity"])
    tf = np.linspace(0, 3600, 361)
    truth = model.simulate(t=tf).x[:, 0]
    rng = np.random.default_rng(3)
    yw = (truth / I_fw + rng.normal(0, 8.0, len(tf))).reshape(-1, 1)
    Q, R, P = np.array([[1e2]]), np.array([[16.0]]), np.array([[1e6]])
    ekf = ExtendedKalmanFilter(model, Q, R, P, x0=np.array([I_fw * 700.0])).filter(
        yw, None, tf
    )
    err_meas = np.sqrt(np.mean((yw[:, 0] - truth / I_fw) ** 2))
    err_ekf = np.sqrt(np.mean((ekf.x[:, 0] / I_fw - truth / I_fw) ** 2))
    assert err_ekf < 0.5 * err_meas
    mhe = MovingHorizonEstimator(
        model, Q, R, P, x0=np.array([I_fw * 700.0]), horizon=5, bounds=[(0.0, None)]
    )
    res = mhe.filter(yw[:60], None, tf[:60])
    assert res.x.shape[0] == 60


def test_custom_dynamics_surface():
    cd = CustomDynamics(
        lambda x, u, t: np.array([-x[0] + u[0]]),
        1,
        1,
        energy=lambda x: 0.5 * x[0] ** 2,
        x0=[1.0],
    )
    tr = cd.simulate(t_span=(0, 1), dt=0.01, inputs=0.0)
    assert tr.x[-1, 0] == pytest.approx(np.exp(-1), abs=1e-4)
    assert tr.energy[0] == pytest.approx(0.5)
    tr2 = cd.simulate(t_span=(0, 1), dt=0.01, inputs=lambda t, x: np.array([1.0]))
    assert tr2.x[-1, 0] > tr.x[-1, 0]
    assert "user-supplied" in cd.summary()


@pytest.mark.skipif(not engine_available(), reason="needs otwin_engine")
def test_rust_and_numpy_agree_on_nonlinear_model():
    """Same IR, both backends, every solver."""
    from otwin.components.catalogue import water_tank

    t = np.linspace(0, 50, 201)
    for solver in ("euler", "rk4", "rk45", "midpoint"):
        rs = otwin.compile(water_tank(level=2.0), backend="rust").simulate(
            t=t, solver=solver, inputs={"inlet": 0.1}
        )
        nm = otwin.compile(water_tank(level=2.0), backend="numpy").simulate(
            t=t, solver=solver, inputs={"inlet": 0.1}
        )
        assert np.allclose(rs.x, nm.x, rtol=1e-11, atol=1e-13), solver
        assert np.allclose(rs.energy, nm.energy, rtol=1e-11, atol=1e-10), solver
        assert np.allclose(rs["drain.flow"], nm["drain.flow"], rtol=1e-10, atol=1e-13), (
            solver
        )


def test_solver_errors_are_physical(backend):
    m = oscillator(backend)
    with pytest.raises(ValueError, match="unknown solver"):
        m.simulate(t_span=(0, 1), dt=0.1, solver="magic")
    with pytest.raises(ValueError, match="strictly increasing"):
        m.simulate(t=np.array([0.0, 1.0, 0.5]))
    with pytest.raises(TypeError, match="unknown solver option"):
        m.simulate(t_span=(0, 1), dt=0.1, tolerance=1e-3)


def test_free_mass_with_weight_only():
    """A mass under a constant force and nothing else: constant acceleration."""
    mass, weight = Mass(2.0, name="m"), ForceSource(4.0, name="F")
    s = System(mass, weight).connect(mass.flange, weight.flange)
    tr = otwin.compile(s).simulate(t_span=(0, 3), dt=0.1)
    assert tr["m.velocity"][-1] == pytest.approx(2.0 * 3.0)
    assert tr.energy_balance()["max_violation"] < 1e-9


def test_chain_syntax():
    from otwin.components.electrical import Capacitor, Ground, Resistor, VoltageSource

    v, r, c, g = (
        VoltageSource(1.0, name="V"),
        Resistor(1.0, name="R"),
        Capacitor(1.0, name="C"),
        Ground(),
    )
    s = v >> r >> c  # V.n - R.p, R.n - C.p
    s.connect(c.n, v.p, g.terminal)  # close the loop back to the source
    m = otwin.compile(s)
    tr = m.simulate(t_span=(0, 5), dt=0.01, solver="rk45")
    # the source's p terminal sits on the capacitor's n side, so the capacitor charges negative
    assert tr["C.voltage"][-1] == pytest.approx(-(1 - np.exp(-5)), abs=1e-8)


def test_unused_fixed_component_still_compiles():
    mass, spring, damper, wall = (
        Mass(name="m"),
        Spring(name="k"),
        Damper(name="c"),
        Fixed(name="w"),
    )
    s = (
        System(mass, spring, damper, wall)
        .connect(mass.flange, spring.a, damper.a)
        .connect(spring.b, damper.b, wall.terminal)
    )
    assert otwin.compile(s).n_states == 2
