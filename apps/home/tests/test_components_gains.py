"""Gains and schedules against hand-computed energies.

A gain is a through source of heat, so what it delivers to the zone is known
exactly: the schedule's watts, held over each hour. Every expected number
below is a sum of the schedule's values or a steady state of the zone.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import otwin
import pytest

from components import (
    Appliance,
    BaseLoad,
    Occupants,
    Outdoors,
    Schedule,
    SolarGain,
    ThermalZone,
    hot_water_heat,
)

K0 = 273.15
UA, C = 120.0, 1.0e7
#: 2026-01-12 00:00 Madrid (CET, UTC+1) is 2026-01-11 23:00 UTC: a Monday.
MONDAY = datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc)
PROFILE = Schedule(
    [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        350,
        250,
        0,
        0,
        0,
        0,
        600,
        900,
        300,
        0,
        0,
        0,
        0,
        700,
        500,
        300,
        0,
    ]
)


def _home(*loads, ua=UA, capacity=C, temperature=K0 + 20):
    zone, out = ThermalZone(ua, capacity, temperature=temperature), Outdoors()
    s = otwin.System(zone, out, *loads)
    s.connect(zone.outside, out.port)
    s.connect(zone.air, *(ld.port for ld in loads))
    return s


def test_appliance_energy_is_the_profile_sum(backend):
    """Hourly grid, held input: the day's delivered heat is Σ profile × 1 h
    exactly, and the zone stores that heat minus what the envelope loses."""
    kitchen = Appliance(schedule=PROFILE, name="kitchen")
    model = otwin.compile(_home(kitchen), backend=backend)
    h = 3600.0
    t = np.arange(0, 24 * h + 1, h)
    u = {"outdoor": K0 + 5.0, "kitchen": PROFILE.sample(t, start=MONDAY)}
    run = model.simulate(t=t, inputs=u)
    p = run["kitchen.electric_power"]
    np.testing.assert_array_equal(p[:-1], np.array(PROFILE.values))
    assert np.sum(p[:-1] * h) == pytest.approx(3900.0 * 3600.0, rel=1e-15)  # 3.9 kWh
    T = run["zone.temperature"]
    lost = np.sum(h * UA * ((T[1:] + T[:-1]) / 2 - (K0 + 5.0)))
    assert C * (T[-1] - T[0]) == pytest.approx(3900.0 * 3600.0 - lost, rel=1e-10)


def test_base_load_is_a_named_parameter_and_sets_the_steady_state(backend):
    """T = T_out + P_base / UA, and changing the parameter moves it."""
    model = otwin.compile(_home(BaseLoad(150.0)), backend=backend)
    assert "base.power" in model.param_names
    assert model.parameters["base.power"] == 150.0
    t = np.arange(0, 86400 + 1, 3600.0)
    for p in (150.0, 240.0):
        m = model.with_parameters({"base.power": p})
        t_ss = K0 + 4.0 + p / UA
        run = m.simulate(
            t=t, inputs={"outdoor": K0 + 4.0}, x0={"zone.air.heat": C * t_ss}
        )
        np.testing.assert_allclose(run["zone.temperature"], t_ss, rtol=0, atol=1e-9)
        np.testing.assert_allclose(run["base.electric_power"], p, rtol=0)


def test_loads_add_up_at_the_air_node(backend):
    """Two appliances and a base load heat the zone as their sum would."""
    a, b = (
        Appliance(schedule=PROFILE, name="a"),
        Appliance(schedule=PROFILE.scaled(0.5), name="b"),
    )
    t = np.arange(0, 2 * 86400 + 1, 1800.0)
    sep = otwin.compile(_home(a, b, BaseLoad(100.0)), backend=backend).simulate(
        t=t,
        inputs={
            "outdoor": K0,
            "a": PROFILE.sample(t, start=MONDAY),
            "b": PROFILE.scaled(0.5).sample(t, start=MONDAY),
        },
    )
    one = Appliance(name="all")
    joint = otwin.compile(_home(one), backend=backend).simulate(
        t=t,
        inputs={"outdoor": K0, "all": 1.5 * PROFILE.sample(t, start=MONDAY) + 100.0},
    )
    np.testing.assert_allclose(
        sep["zone.temperature"], joint["zone.temperature"], rtol=0, atol=1e-10
    )


def test_free_gains_heat_the_zone_but_not_the_meter(backend):
    """Three people give 270 W like a 270 W appliance would, but only the
    appliance shows on the electricity meter."""
    t = np.arange(0, 86400 + 1, 3600.0)
    people = Occupants(people=3.0, watts_each=90.0)
    a = otwin.compile(_home(people), backend=backend).simulate(
        t=t, inputs={"outdoor": K0}
    )
    heater = BaseLoad(270.0, name="fake")
    b = otwin.compile(_home(heater), backend=backend).simulate(
        t=t, inputs={"outdoor": K0}
    )
    np.testing.assert_allclose(a["zone.temperature"], b["zone.temperature"], atol=1e-10)
    np.testing.assert_allclose(a["occupants.heat"], 270.0, rtol=0)
    assert (
        "occupants.power"
        in otwin.compile(_home(Occupants(people=3.0)), backend=backend).param_names
    )
    out = otwin.compile(_home(people), backend=backend).output_names
    assert "occupants.electric_power" not in out and "fake.electric_power" not in out


def test_solar_gain_is_an_input_of_free_heat(backend):
    solar = SolarGain()
    model = otwin.compile(_home(solar), backend=backend)
    assert "solar" in model.input_names
    t = np.arange(0, 7200 + 1, 3600.0)
    run = model.simulate(t=t, inputs={"outdoor": K0, "solar": 400.0})
    np.testing.assert_allclose(run["solar.heat"], 400.0, rtol=0)
    assert "solar.electric_power" not in model.output_names
    with pytest.raises(ValueError, match="not both"):
        Occupants(people=2.0, schedule=PROFILE)


# ---------------------------------------------------------------- schedules


def test_schedule_follows_the_local_clock():
    # Monday 07:00 Madrid in January is 06:00 UTC: the kitchen's 350 W.
    t = np.array([7 * 3600.0, 7 * 3600.0 + 3599, 8 * 3600.0])
    assert PROFILE.sample(t, start=MONDAY).tolist() == [350.0, 350.0, 250.0]


def test_schedule_on_the_dst_days():
    """29 March 2026 is 23 hours long (02:00 skipped) and 26 October 2025 is
    25 (02:00 twice). Sampled hourly over those days, a profile sums to its
    daily total minus, or plus, its 02:00 value."""
    p = Schedule([float(h + 1) for h in range(24)])  # hour h is worth h + 1
    assert p.daily_sum() == 300.0
    march = datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)  # 29 Mar 00:00 CET
    assert p.sample(np.arange(23) * 3600.0, start=march).sum() == 300.0 - 3.0
    october = datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc)  # 26 Oct 00:00 CEST
    assert p.sample(np.arange(25) * 3600.0, start=october).sum() == 300.0 + 3.0


def test_weekly_schedule_uses_the_weekday():
    weekly = Schedule([100.0] * 120 + [300.0] * 48)  # weekend draws more
    t = np.arange(0, 7 * 24) * 3600.0
    s = weekly.sample(t, start=MONDAY)
    assert s[:120].tolist() == [100.0] * 120 and s[120:].tolist() == [300.0] * 48
    assert weekly.daily_sum(5) == 7200.0 and weekly.weekly


def test_schedule_validates_its_values():
    with pytest.raises(ValueError, match="24 hourly values"):
        Schedule([1.0] * 23)
    with pytest.raises(ValueError, match="finite"):
        Schedule([float("nan")] * 24)
    with pytest.raises(ValueError, match="timezone-aware"):
        PROFILE.sample([0.0], start=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="negative"):
        Appliance(schedule=Schedule([-1.0] * 24), name="x")
    with pytest.raises(ValueError, match="negative"):
        BaseLoad(-5.0)


def test_hot_water_heat_is_rho_c_vdot_dt():
    # 3600 L/h is 1 L/s: 4186 W per kelvin.
    assert float(hot_water_heat(3600.0, tap=K0 + 41, cold=K0 + 40)) == pytest.approx(
        4186.0
    )
    np.testing.assert_allclose(
        hot_water_heat([0.0, 36.0], tap=K0 + 45, cold=K0 + 15), [0.0, 0.01 * 4186.0 * 30]
    )
    with pytest.raises(ValueError, match="negative"):
        hot_water_heat(-1.0)
    with pytest.raises(ValueError, match="above"):
        hot_water_heat(10.0, tap=K0 + 10, cold=K0 + 15)
