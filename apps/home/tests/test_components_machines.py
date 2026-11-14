"""Machines against their closed-form solutions.

The thermostat law ``Q = clip(G (T_set − T), 0, P)`` with ``G = P / band`` is
piecewise linear, so on each piece the heated body follows a linear ODE with
an exact solution:

* **saturated** (``T ≤ T_set − band``): ``Q = P``; a lossless tank ramps
  linearly, a lossy one relaxes exponentially to ``T_room + (P − draw) / U``;
* **proportional**: ``C dT/dt = G (T_set − T) − U (T − T_room) − draw``,
  exponential with ``τ = C / (G + U)`` towards
  ``T* = (G T_set + U T_room − draw) / (G + U)``;
* **off** (``T ≥ T_set``): free cooling, ``τ = C / U``.

Each piece is tested where it holds, against the exact discrete (Padé)
solution and the continuous one. Steady states are checked by starting on
them and staying there to rounding.
"""

from __future__ import annotations

import math

import numpy as np
import otwin
import pytest
from otwin.components.thermal import Ambient, ThermalMass

from components import (
    WATER_HEAT_CAPACITY,
    AirConditioner,
    BaseLoad,
    Boiler,
    ElectricHeater,
    HeatPump,
    Outdoors,
    ThermalZone,
    Thermostat,
    WaterHeater,
)

K0 = 273.15


def _pade(z: float) -> float:
    """Midpoint amplification for dx/dt = -x/τ over one step, z = h/τ."""
    return (1 - z / 2) / (1 + z / 2)


# ---------------------------------------------------------------- thermostat


def _tank_with_thermostat(power, band, setpoint, temperature, capacity):
    tank = ThermalMass(capacity, temperature=temperature, name="tank")
    sp = Ambient(setpoint, name="setpoint")
    th = Thermostat(power, band, name="th")
    s = otwin.System(tank, sp, th)
    s.connect(sp.port, th.a)
    s.connect(th.b, tank.port)
    return s


CT = WATER_HEAT_CAPACITY * 100.0  # 100 L of water
P, BAND, TSET = 2000.0, 2.0, K0 + 60.0


def test_saturated_thermostat_ramps_the_tank_linearly(backend):
    """Below T_set − band the element gives exactly P: T = T0 + P t / C."""
    T0 = K0 + 15.0
    t1 = CT * ((TSET - BAND) - T0) / P  # when the ramp reaches the band
    model = otwin.compile(_tank_with_thermostat(P, BAND, TSET, T0, CT), backend=backend)
    h = 60.0
    t = np.arange(0, math.floor(t1 / h) * h + 1, h)
    run = model.simulate(t=t)
    np.testing.assert_allclose(
        run["tank.temperature"], T0 + P * t / CT, rtol=0, atol=1e-9
    )
    np.testing.assert_allclose(run["th.heat_flow"], P, rtol=1e-12)


def test_proportional_thermostat_approaches_the_setpoint_exponentially(backend):
    """From T_set − band, Q = G (T_set − T): T = T_set − band e^{−t/τ},
    τ = C band / P. The Padé map is exact, the exponential within its bound."""
    tau = CT * BAND / P
    model = otwin.compile(
        _tank_with_thermostat(P, BAND, TSET, TSET - BAND, CT), backend=backend
    )
    for h in (600.0, 30.0):
        t = np.arange(0, 8 * tau + 1, h)
        T = model.simulate(t=t)["tank.temperature"]
        k = np.arange(t.size)
        np.testing.assert_allclose(
            T, TSET - BAND * _pade(h / tau) ** k, rtol=0, atol=1e-10
        )
        bound = k * abs(_pade(h / tau) - math.exp(-h / tau)) * BAND
        assert np.all(np.abs(T - (TSET - BAND * np.exp(-t / tau))) <= bound + 1e-12)


def test_thermostat_never_cools(backend):
    """Above the setpoint the law clips at zero: no heat, exactly."""
    model = otwin.compile(
        _tank_with_thermostat(P, BAND, TSET, TSET + 5, CT), backend=backend
    )
    run = model.simulate(t=np.arange(0, 86400 + 1, 3600.0))
    np.testing.assert_array_equal(run["th.heat_flow"], 0.0)
    np.testing.assert_allclose(run["tank.temperature"], TSET + 5, rtol=0, atol=1e-12)


# ---------------------------------------------------------------- water heater


ROOM = K0 + 20.0


def _water_heater(*, temperature=None, fuel="electricity", efficiency=1.0, where="room"):
    wh = WaterHeater(
        80.0,
        power=1500.0,
        setpoint=TSET,
        band=2.0,
        loss_ua=1.1,
        fuel=fuel,
        efficiency=efficiency,
        temperature=temperature,
        name="wh",
    )
    room = Ambient(ROOM, name="room")
    s = otwin.System(wh, room)
    s.connect(wh.room, room.port)
    return wh, s


CW = WATER_HEAT_CAPACITY * 80.0
G = 1500.0 / 2.0
U = 1.1


def test_standby_cooling_with_the_element_off(backend):
    """Hot above the setpoint, the tank cools freely towards the room:
    ΔT_k = ΔT_0 a^k with τ = C / U, and the standby loss is U (T − T_room)."""
    T0 = K0 + 70.0
    tau = CW / U
    t_cross = tau * math.log((T0 - ROOM) / (TSET - ROOM))  # when it reaches 60 °C
    _, s = _water_heater(temperature=T0)
    model = otwin.compile(s, backend=backend)
    h = 3600.0
    t = np.arange(0, math.floor(t_cross / h) * h + 1, h)
    run = model.simulate(t=t, inputs={"wh.draw": 0.0})
    expected = ROOM + (T0 - ROOM) * _pade(h / tau) ** np.arange(t.size)
    np.testing.assert_allclose(run["wh.temperature"], expected, rtol=0, atol=1e-10)
    np.testing.assert_allclose(run["wh.standby_loss"], U * (expected - ROOM), rtol=1e-10)
    np.testing.assert_array_equal(run["wh.heat"], 0.0)
    # 80 L at 70 °C in a 20 °C room loses U·50 K = 55 W at first: 1.3 kWh a day
    assert run["wh.standby_loss"][0] == pytest.approx(55.0)


@pytest.mark.parametrize("fuel, efficiency", [("electricity", 1.0), ("gas", 0.88)])
def test_steady_state_under_a_constant_draw(backend, fuel, efficiency):
    """G (T_set − T*) = draw + U (T* − T_room), so
    T* = (G T_set + U T_room − draw) / (G + U); fuel = heat / efficiency."""
    draw = 500.0
    t_star = (G * TSET + U * ROOM - draw) / (G + U)
    heat = G * (TSET - t_star)
    assert 0 < heat < 1500.0  # on the proportional piece
    _, s = _water_heater(temperature=t_star, fuel=fuel, efficiency=efficiency)
    run = otwin.compile(s, backend=backend).simulate(
        t=np.arange(0, 86400 + 1, 600.0), inputs={"wh.draw": draw}
    )
    np.testing.assert_allclose(run["wh.temperature"], t_star, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["wh.heat"], heat, rtol=1e-9)
    np.testing.assert_allclose(run["wh.fuel_power"], heat / efficiency, rtol=1e-9)
    assert heat == pytest.approx(draw + U * (t_star - ROOM), rel=1e-12)


def test_a_draw_beyond_the_power_runs_the_tank_cold(backend):
    """A 3 kW draw on a 1.5 kW element: saturated, C dT/dt = P − D − U (T − T_room),
    so T relaxes towards T_room + (P − D)/U and falls about 1.6 K per 10 minutes.
    Exact Padé map while saturated."""
    D = 3000.0
    t_inf = ROOM + (1500.0 - D) / U
    tau = CW / U
    T0 = TSET - 2.0  # start at the edge of the band: saturated from t = 0
    _, s = _water_heater(temperature=T0)
    h = 300.0
    t = np.arange(0, 4 * 3600 + 1, h)
    run = otwin.compile(s, backend=backend).simulate(t=t, inputs={"wh.draw": D})
    expected = t_inf + (T0 - t_inf) * _pade(h / tau) ** np.arange(t.size)
    np.testing.assert_allclose(run["wh.temperature"], expected, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["wh.heat"], 1500.0, rtol=1e-12)
    assert run["wh.temperature"][-1] < K0 + 45  # after 4 h of showers: lukewarm


def test_water_heater_energy_balance(backend):
    """Over a day of draws: ∫heat = C ΔT + ∫standby + ∫draw. The heater's
    heat follows the state within a step, so the trapezoid closes the
    balance to a step-size tolerance, not to rounding."""
    _, s = _water_heater(temperature=TSET)
    model = otwin.compile(s, backend=backend)
    h = 60.0
    t = np.arange(0, 86400 + 1, h)
    hour = (t // 3600).astype(int)
    draw = np.where(np.isin(hour, [7, 8, 21]), 1800.0, 0.0)
    run = model.simulate(t=t, inputs={"wh.draw": draw})

    def trap(y):
        return float(np.sum((y[1:] + y[:-1]) / 2 * h))

    stored = CW * (run["wh.temperature"][-1] - run["wh.temperature"][0])
    supplied = trap(run["wh.heat"])
    used = stored + trap(run["wh.standby_loss"]) + float(np.sum(draw[:-1] * h))
    assert supplied == pytest.approx(used, rel=1e-4)
    assert supplied / 3.6e6 == pytest.approx(3 * 1.8 + 24 * U * 40 / 1000, rel=0.02)


def test_water_heater_parameters_are_fittable(backend):
    wh, s = _water_heater()
    names = set(otwin.compile(s, backend=backend).param_names)
    assert {
        "wh.tank.capacity",
        "wh.thermostat.power",
        "wh.thermostat.band",
        "wh.standby.conductance",
        "wh.setpoint.temperature",
    } <= names
    assert wh.volume == 80.0


# ---------------------------------------------------------------- space heater


UAZ, CZ = 200.0, 1.0e7


def _heated_zone(heater, *, temperature, gains=0.0):
    zone, out = ThermalZone(UAZ, CZ, temperature=temperature), Outdoors()
    parts = [heater] + ([BaseLoad(gains)] if gains else [])
    s = otwin.System(zone, out, *parts)
    s.connect(zone.outside, out.port)
    s.connect(zone.air, *(p.port for p in parts))
    return s


def test_space_heater_steady_state(backend):
    """G (T_set − T*) + gains = UA (T* − T_out):
    T* = (G T_set + UA T_out + gains) / (G + UA). Gas fuel = heat / 0.9."""
    Gz, tset, tout, gains = 10e3 / 1.0, K0 + 20.0, K0 + 5.0, 300.0
    t_star = (Gz * tset + UAZ * tout + gains) / (Gz + UAZ)
    heat = Gz * (tset - t_star)
    heater = Boiler(10e3, setpoint=tset, band=1.0, efficiency=0.9)
    run = otwin.compile(
        _heated_zone(heater, temperature=t_star, gains=gains), backend=backend
    ).simulate(t=np.arange(0, 86400 + 1, 900.0), inputs={"outdoor": tout})
    np.testing.assert_allclose(run["zone.temperature"], t_star, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["heating.heat"], heat, rtol=1e-9)
    np.testing.assert_allclose(run["heating.fuel_power"], heat / 0.9, rtol=1e-9)
    assert heat == pytest.approx(UAZ * (t_star - tout) - gains, rel=1e-12)


def test_setpoint_schedule_is_an_input_and_the_change_is_exponential(backend):
    """A setpoint step from 16 to 19 °C with a 5 K band, so the 4 K deficit
    asks for G·4 K = 8 kW of a 10 kW heater and stays on the proportional
    piece. The zone moves from one steady state to the next with
    τ = C / (G + UA), exactly the Padé map from the step on."""
    band = 5.0
    Gz, tout = 10e3 / band, K0 + 5.0
    lo, hi = K0 + 16.0, K0 + 19.0

    def t_star(sp):
        return (Gz * sp + UAZ * tout) / (Gz + UAZ)

    heater = ElectricHeater(10e3, setpoint=None, band=band)
    model = otwin.compile(_heated_zone(heater, temperature=t_star(lo)), backend=backend)
    assert "heating.setpoint" in model.input_names
    h, k_step = 60.0, 30
    t = np.arange(0, 3 * 3600 + 1, h)
    sp = np.where(np.arange(t.size) < k_step, lo, hi)
    run = model.simulate(t=t, inputs={"outdoor": tout, "heating.setpoint": sp})
    tau = CZ / (Gz + UAZ)
    k = np.arange(t.size) - k_step
    expected = np.where(
        k <= 0,
        t_star(lo),
        t_star(hi) + (t_star(lo) - t_star(hi)) * _pade(h / tau) ** np.maximum(k, 0),
    )
    np.testing.assert_allclose(run["zone.temperature"], expected, rtol=0, atol=1e-9)
    assert run["heating.heat"].max() < 10e3  # never saturated


# ---------------------------------------------------------------- air conditioner


def test_air_conditioner_steady_state_in_a_heat_balance(backend):
    """Hot outside, gains inside: G (T* − T_set) = UA (T_out − T*) + gains, so
    T* = (G T_set + UA T_out + gains) / (G + UA), the heating formula with the
    flows reversed. Electricity is the heat removed over the EER."""
    Gz, tset, tout, gains = 5e3 / 1.0, K0 + 25.0, K0 + 33.0, 500.0
    t_star = (Gz * tset + UAZ * tout + gains) / (Gz + UAZ)
    assert t_star > tset  # the proportional piece: a little above the setpoint
    cool = Gz * (t_star - tset)
    assert 0 < cool < 5e3
    ac = AirConditioner(5e3, eer=2.8, setpoint=tset, band=1.0, name="aircon")
    run = otwin.compile(
        _heated_zone(ac, temperature=t_star, gains=gains), backend=backend
    ).simulate(t=np.arange(0, 86400 + 1, 900.0), inputs={"outdoor": tout})
    np.testing.assert_allclose(run["zone.temperature"], t_star, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["aircon.cool"], cool, rtol=1e-9)
    np.testing.assert_allclose(run["aircon.fuel_power"], cool / 2.8, rtol=1e-9)
    assert cool == pytest.approx(UAZ * (tout - t_star) + gains, rel=1e-12)


def test_air_conditioner_never_heats(backend):
    """Below its setpoint the clipped law gives exactly zero."""
    ac = AirConditioner(5e3, setpoint=K0 + 25.0, name="aircon")
    model = otwin.compile(_heated_zone(ac, temperature=K0 + 21.0), backend=backend)
    run = model.simulate(t=np.arange(0, 86400 + 1, 3600.0), inputs={"outdoor": K0 + 21.0})
    np.testing.assert_array_equal(run["aircon.cool"], 0.0)
    np.testing.assert_allclose(run["zone.temperature"], K0 + 21.0, rtol=0, atol=1e-12)


def test_saturated_air_conditioner_cools_at_full_power(backend):
    """Far above the setpoint the unit gives exactly P: with a mild outside,
    the zone relaxes towards T_out − P/UA at τ = C/UA, the exact Padé map,
    until it re-enters the band."""
    P = 5e3
    t0, tout = K0 + 30.0, K0 + 28.0
    t_inf = tout - P / UAZ  # 3 °C: far below, so it stays saturated for hours
    tau = CZ / UAZ
    ac = AirConditioner(P, setpoint=K0 + 25.0, band=1.0, name="aircon")
    model = otwin.compile(_heated_zone(ac, temperature=t0), backend=backend)
    h = 300.0
    t = np.arange(0, 2 * 3600 + 1, h)
    run = model.simulate(t=t, inputs={"outdoor": tout})
    expected = t_inf + (t0 - t_inf) * _pade(h / tau) ** np.arange(t.size)
    assert expected[-1] > K0 + 26.0  # still saturated at the end of the window
    np.testing.assert_allclose(run["zone.temperature"], expected, rtol=0, atol=1e-9)
    np.testing.assert_allclose(run["aircon.cool"], P, rtol=1e-12)


def test_heat_pump_and_air_conditioner_share_a_deadband(backend):
    """A reversible split set to heat at 20 and cool at 25: between the two
    setpoints both are off and the zone floats."""
    hp = HeatPump(4e3, cop=3.2, setpoint=K0 + 20.0, name="hp")
    ac = AirConditioner(5e3, eer=2.8, setpoint=K0 + 25.0, name="ac")
    zone, out = ThermalZone(UAZ, CZ, temperature=K0 + 22.0), Outdoors()
    s = otwin.System(zone, out, hp, ac)
    s.connect(zone.outside, out.port)
    s.connect(zone.air, hp.port, ac.port)
    model = otwin.compile(s, backend=backend)
    run = model.simulate(
        t=np.arange(0, 6 * 3600 + 1, 600.0), inputs={"outdoor": K0 + 22.0}
    )
    np.testing.assert_array_equal(run["hp.heat"], 0.0)
    np.testing.assert_array_equal(run["ac.cool"], 0.0)
    # and the COP and EER are what the meters divide by
    assert hp.cop == 3.2 and ac.eer == 2.8


def test_machines_validate_their_arguments():
    with pytest.raises(ValueError, match="fuel"):
        WaterHeater(fuel="oil")
    with pytest.raises(ValueError, match="not physical"):
        WaterHeater(fuel="gas", efficiency=1.5)
    with pytest.raises(ValueError, match="not physical"):
        Boiler(efficiency=1.5)
    with pytest.raises(ValueError, match="positive"):
        HeatPump(cop=0.0)
    with pytest.raises(ValueError, match="litres"):
        WaterHeater(0.0)
    with pytest.raises(ValueError, match="kelvin"):
        Boiler(setpoint=-20.0)
    with pytest.raises(ValueError, match="kelvin"):
        AirConditioner(setpoint=0.0)
