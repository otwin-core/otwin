"""ThermalZone against its closed-form solutions.

Every expected number is computed here from the equations of the RC network,
never from a recorded run. Two kinds of check:

* **The exact discrete solution.** The implicit midpoint rule applied to a
  linear system is the (1,1) Padé map ``x_{k+1} = (I - hA/2)^{-1}(I + hA/2) x_k``.
  For a 1R1C zone that is ``ΔT_k = ΔT_0 a^k`` with
  ``a = (1 - h/2τ)/(1 + h/2τ)``. The engine must reproduce it to rounding.
* **The continuous solution** (exponential decay, the periodic response to a
  sinusoidal outdoor temperature, the two-mode response of a 2R2C zone),
  within a bound derived from the step size, not a loosely chosen tolerance.
"""

from __future__ import annotations

import math

import numpy as np
import otwin
import pytest

from components import BaseLoad, Outdoors, ThermalZone

K0 = 273.15


def _zone_system(zone: ThermalZone, *extra) -> otwin.System:
    out = Outdoors()
    s = otwin.System(zone, out, *extra)
    s.connect(zone.outside, out.port)
    if extra:
        s.connect(zone.air, *(e.port for e in extra))
    return s


# ---------------------------------------------------------------- 1R1C


C, UA = 1.0e7, 100.0  # tau = 1e5 s, about 28 h
TAU = C / UA


def test_1r1c_free_cooling_is_the_exact_pade_map(backend):
    model = otwin.compile(
        _zone_system(ThermalZone(UA, C, temperature=K0 + 20)), backend=backend
    )
    h = 3600.0
    t = np.arange(0, 72 * h + 1, h)
    run = model.simulate(t=t, inputs={"outdoor": K0})
    a = (1 - h / (2 * TAU)) / (1 + h / (2 * TAU))
    expected = K0 + 20.0 * a ** np.arange(t.size)
    np.testing.assert_allclose(run["zone.temperature"], expected, rtol=0, atol=1e-10)


def test_1r1c_free_cooling_matches_the_exponential_within_the_step_bound(backend):
    model = otwin.compile(
        _zone_system(ThermalZone(UA, C, temperature=K0 + 20)), backend=backend
    )
    h = 600.0
    t = np.arange(0, 3 * TAU + 1, h)
    run = model.simulate(t=t, inputs={"outdoor": K0})
    exact = K0 + 20.0 * np.exp(-t / TAU)
    # |a^k - e^{-kz}| <= k |a - e^{-z}| because both are in (0, 1).
    z = h / TAU
    a = (1 - z / 2) / (1 + z / 2)
    bound = np.arange(t.size) * abs(a - math.exp(-z)) * 20.0
    err = np.abs(run["zone.temperature"] - exact)
    assert np.all(err <= bound + 1e-12)
    assert err[-1] < 1e-3  # the bound is not vacuous: under a millikelvin


def test_1r1c_steady_state_is_gain_over_conductance(backend):
    """T = T_out + P / (UA + ventilation), and all of P leaves as heat loss."""
    P, vent = 900.0, 50.0
    zone = ThermalZone(UA, C, ventilation=vent)
    model = otwin.compile(_zone_system(zone, BaseLoad(P)), backend=backend)
    t_ss = K0 + 5.0 + P / (UA + vent)
    run = model.simulate(
        t=np.arange(0, 86400 + 1, 3600.0),
        inputs={"outdoor": K0 + 5.0},
        x0={"zone.air.heat": C * t_ss},
    )
    np.testing.assert_allclose(run["zone.temperature"], t_ss, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["zone.heat_loss"], P, rtol=1e-12)


def test_ventilation_is_a_parallel_conductance(backend):
    """ua=a with ventilation=b is the same zone as ua=a+b."""
    t = np.arange(0, 2 * 86400 + 1, 1800.0)
    outdoor = K0 + 5 + 8 * np.sin(2 * np.pi * t / 86400)
    a = otwin.compile(
        _zone_system(ThermalZone(70.0, C, ventilation=30.0, temperature=K0 + 18)),
        backend=backend,
    ).simulate(t=t, inputs={"outdoor": outdoor})
    b = otwin.compile(
        _zone_system(ThermalZone(100.0, C, temperature=K0 + 18)), backend=backend
    ).simulate(t=t, inputs={"outdoor": outdoor})
    np.testing.assert_allclose(
        a["zone.temperature"], b["zone.temperature"], rtol=0, atol=1e-10
    )
    np.testing.assert_allclose(
        a["zone.heat_loss"], b["zone.heat_loss"], rtol=1e-10, atol=1e-9
    )


def test_1r1c_periodic_response_to_a_daily_outdoor_wave(backend):
    """τ dT/dt = T_out - T with T_out = T_m + A sin ωt has the periodic solution
    T = T_m + A / sqrt(1 + (ωτ)²) · sin(ωt - atan ωτ): damped and late."""
    tau = 2.0e4  # a light zone, so the wave shows indoors
    zone = ThermalZone(UA, UA * tau)
    model = otwin.compile(_zone_system(zone), backend=backend)
    w, A, Tm = 2 * np.pi / 86400, 8.0, K0 + 10
    amp, lag = A / math.sqrt(1 + (w * tau) ** 2), math.atan(w * tau)
    h = 120.0
    t = np.arange(0, 3 * 86400 + 1, h)

    def periodic(tt):
        return Tm + amp * np.sin(w * tt - lag)

    run = model.simulate(
        t=t,
        inputs={"outdoor": Tm + A * np.sin(w * t)},
        interp="linear",
        x0={"zone.air.heat": UA * tau * periodic(0.0)},
    )
    err = np.max(np.abs(run["zone.temperature"] - periodic(t)))
    # Midpoint and the trapezoidal input are second order: the error is a few
    # (ωh)² of the forcing amplitude, (ωh)² = 7.6e-5 here.
    assert err <= A * (w * h) ** 2
    # amplitude and lag read off the simulated day match the closed form
    day3 = (t >= 2 * 86400) & (t < 3 * 86400)
    T3 = run["zone.temperature"][day3]
    assert (T3.max() - T3.min()) / 2 == pytest.approx(amp, rel=1e-3)
    t_peak = t[day3][np.argmax(T3)] - 2 * 86400
    assert t_peak == pytest.approx((np.pi / 2 + lag) / w, abs=h)


def test_heat_balance_closes_exactly_on_the_grid(backend):
    """The midpoint step is exact bookkeeping: over step k the zone stores
    h·(P − K·(T_mid − T_out,k)), with T_mid the mean of the step's end
    temperatures and T_out,k the held input. Summed, that is C ΔT to rounding,
    whatever the inputs do, a stepped outdoor temperature included."""
    K = UA + 40.0
    zone = ThermalZone(UA, C, ventilation=40.0, temperature=K0 + 21)
    load = BaseLoad(350.0)
    model = otwin.compile(_zone_system(zone, load), backend=backend)
    h = 900.0
    t = np.arange(0, 3 * 86400 + 1, h)
    outdoor = K0 + 2 + 6 * np.sin(2 * np.pi * t / 86400) + np.where(t > 86400, -4.0, 0.0)
    run = model.simulate(t=t, inputs={"outdoor": outdoor})
    T = run["zone.temperature"]
    t_mid = (T[1:] + T[:-1]) / 2
    lost = np.sum(h * K * (t_mid - outdoor[:-1]))
    stored = C * (T[-1] - T[0])
    assert stored == pytest.approx(350.0 * t[-1] - lost, rel=1e-10)
    # and the zone's heat_loss output is that conductance law at each point.
    # The final point is left out: with interp="hold" the Rust engine
    # evaluates outputs at the last grid point with the previous input
    # (otwin-core solver.rs, `record`), a core parity bug reported separately.
    np.testing.assert_allclose(
        run["zone.heat_loss"][:-1], K * (T - outdoor)[:-1], rtol=1e-12
    )


# ---------------------------------------------------------------- 2R2C

CA, CF, HC, U, V = 1.5e7, 1.2e8, 600.0, 160.0, 40.0


def _a_matrix():
    return np.array(
        [[-(HC + V) / CA, HC / CA], [HC / CF, -(HC + U) / CF]],
    )


def _two_node(temperature, fabric_temperature, *extra):
    zone = ThermalZone(
        U,
        CA,
        ventilation=V,
        fabric_capacity=CF,
        fabric_coupling=HC,
        temperature=temperature,
        fabric_temperature=fabric_temperature,
    )
    return _zone_system(zone, *extra)


def test_2r2c_free_response_is_the_exact_pade_map(backend):
    model = otwin.compile(_two_node(K0 + 21, K0 + 15), backend=backend)
    h = 3600.0
    t = np.arange(0, 96 * h + 1, h)
    run = model.simulate(t=t, inputs={"outdoor": K0})
    A, eye = _a_matrix(), np.eye(2)
    M = np.linalg.solve(eye - h * A / 2, eye + h * A / 2)
    x = np.array([21.0, 15.0])
    expected = []
    for _ in t:
        expected.append(x.copy())
        x = M @ x
    expected = np.array(expected) + K0
    np.testing.assert_allclose(run["zone.temperature"], expected[:, 0], rtol=0, atol=1e-9)
    np.testing.assert_allclose(
        run["zone.fabric_temperature"], expected[:, 1], rtol=0, atol=1e-9
    )


def test_2r2c_free_response_matches_its_two_modes(backend):
    """x(t) = Σ c_i v_i e^{λ_i t}, eigenvalues from the 2x2 characteristic
    polynomial written out by hand; one fast mode (air), one slow (fabric)."""
    A = _a_matrix()
    tr, det = A[0, 0] + A[1, 1], A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
    disc = math.sqrt(tr * tr / 4 - det)
    lams = [tr / 2 - disc, tr / 2 + disc]  # fast, slow; both negative
    vecs = [np.array([A[0, 1], lam - A[0, 0]]) for lam in lams]
    x0 = np.array([21.0, 15.0])
    c = np.linalg.solve(np.column_stack(vecs), x0)
    h = 300.0
    t = np.arange(0, 5 * 86400 + 1, h)
    exact = sum(
        ci * np.outer(np.exp(lam * t), v)
        for ci, lam, v in zip(c, lams, vecs, strict=True)
    )
    run = otwin.compile(_two_node(K0 + 21, K0 + 15), backend=backend).simulate(
        t=t, inputs={"outdoor": K0}
    )
    # per mode: |a^k - e^{kz}| <= k |a - e^{z}|, z = λh
    bound = 0.0
    for ci, lam, v in zip(c, lams, vecs, strict=True):
        z = lam * h
        a = (1 + z / 2) / (1 - z / 2)
        bound = bound + np.outer(np.arange(t.size) * abs(a - math.exp(z)), np.abs(ci * v))
    got = np.column_stack([run["zone.temperature"], run["zone.fabric_temperature"]]) - K0
    assert np.all(np.abs(got - exact) <= bound + 1e-9)
    assert -1 / lams[0] < 86400 < -1 / lams[1]  # hours for the air, days for the fabric


def test_2r2c_steady_state_is_series_then_parallel(backend):
    """Gain P at the air node: the fabric path is coupling and envelope in
    series, in parallel with ventilation. T_air = T_out + P / K with
    K = 1/(1/h_c + 1/ua) + ventilation, and the fabric sits where the fabric
    path's heat flow puts it."""
    P, To = 2000.0, K0 + 3.0
    ua_series = 1.0 / (1.0 / HC + 1.0 / U)
    t_air = To + P / (ua_series + V)
    t_fab = To + ua_series * (t_air - To) / U
    model = otwin.compile(_two_node(t_air, t_fab, BaseLoad(P)), backend=backend)
    run = model.simulate(t=np.arange(0, 86400 + 1, 3600.0), inputs={"outdoor": To})
    np.testing.assert_allclose(run["zone.temperature"], t_air, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["zone.fabric_temperature"], t_fab, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["zone.heat_loss"], P, rtol=1e-12)


def test_zone_parameters_are_named_and_fittable(backend):
    model = otwin.compile(_two_node(K0 + 20, K0 + 20), backend=backend)
    assert {
        "zone.air.capacity",
        "zone.fabric.capacity",
        "zone.envelope.conductance",
        "zone.coupling.conductance",
        "zone.ventilation.conductance",
    } <= set(model.param_names)
    better = model.with_parameters({"zone.envelope.conductance": U / 2})
    t = np.arange(0, 86400 + 1, 3600.0)
    cold = {"outdoor": K0}
    assert (
        better.simulate(t=t, inputs=cold)["zone.temperature"][-1]
        > model.simulate(t=t, inputs=cold)["zone.temperature"][-1]
    )


def test_zone_validates_its_arguments():
    with pytest.raises(ValueError, match="together"):
        ThermalZone(100.0, 1e7, fabric_capacity=1e8)
    with pytest.raises(ValueError, match="kelvin"):
        ThermalZone(100.0, 1e7, temperature=20.0 - 300)
    with pytest.raises(ValueError, match="2R2C"):
        ThermalZone(100.0, 1e7, fabric_temperature=K0)
    with pytest.raises(ValueError, match="positive"):
        otwin.compile(_zone_system(ThermalZone(-1.0, 1e7)))
