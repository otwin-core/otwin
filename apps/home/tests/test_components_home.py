"""The catalogue homes: every component composed into one twin.

Each component is checked against its closed form in its own test file. Here
the question is whether they compose: one compiled model per home, the same
numbers on both backends, heat that balances across the whole home, meters
that add up to what the schedules say, costs that are price times energy,
and scenarios that move the way physics says they must.
"""

from __future__ import annotations

import runpy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from otwin.runtime import engine_available

from components import (
    WATER_HEAT_CAPACITY,
    Appliance,
    BaseLoad,
    Schedule,
    ThermalZone,
    WaterHeater,
    build_home,
    madrid_flat,
    seville_house,
)
from components.catalogue import KITCHEN, LIVING

K0 = 273.15
START = datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc)  # Monday 00:00 Madrid
JULY = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)  # Monday 00:00 Madrid, CEST
DAY = 86400.0
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _january(t):
    return K0 + 6.0 - 5.0 * np.cos(2 * np.pi * (t / 3600.0 - 6.0) / 24.0)


def _july(t):
    return K0 + 28.0 - 5.5 * np.cos(2 * np.pi * (t / 3600.0 - 6.0) / 24.0)


def _two_days(backend, h=600.0, **kw):
    twin = madrid_flat(backend=backend)
    t = np.arange(0, 2 * DAY + 1, h)
    return twin, twin.simulate(t, start=START, outdoor=_january(t), **kw)


# ---------------------------------------------------------------- madrid


def test_madrid_flat_is_one_model_with_named_inputs(backend):
    twin = madrid_flat(backend=backend)
    assert twin.model.backend == backend
    assert sorted(twin.input_names) == [
        "heating.setpoint",
        "kitchen",
        "living",
        "outdoor",
        "termo.draw",
    ]
    assert set(twin.model.state_names) == {
        "zone.air.heat",
        "zone.fabric.heat",
        "termo.tank.heat",
    }
    assert twin.electric_outputs == [
        "base.electric_power",
        "kitchen.electric_power",
        "living.electric_power",
        "termo.fuel_power",
    ]
    assert twin.gas_outputs == ["heating.fuel_power"]


@pytest.mark.skipif(not engine_available(), reason="needs the otwin_engine extension")
def test_numpy_and_rust_give_the_same_home():
    _, a = _two_days("numpy")
    _, b = _two_days("rust")
    for name in ("zone.temperature", "zone.fabric_temperature", "termo.temperature"):
        np.testing.assert_allclose(a[name], b[name], rtol=1e-10, atol=0)
    # outputs that read an input are compared before the last grid point;
    # see test_components_zone.py for the Rust hold-at-the-end parity bug
    for name in ("heating.heat", "zone.heat_loss", "termo.fuel_power"):
        np.testing.assert_allclose(a[name][:-1], b[name][:-1], rtol=1e-9, atol=1e-9)
    assert a.energy_kwh("electricity") == pytest.approx(
        b.energy_kwh("electricity"), rel=1e-6
    )


def test_heat_balances_across_the_whole_home(backend):
    """Heat into the zone (boiler, appliances, base load, termo standby)
    minus heat lost to outside equals the heat stored in air and fabric, to
    rounding. Step energies are the outputs at each step's midpoint state,
    which is what the implicit midpoint rule applies, so the bookkeeping is
    exact even across the 07:00 and 23:00 setpoint jumps."""
    twin, run = _two_days(backend)
    into = (
        run.energy_j("heating.heat")
        + run.energy_j("termo.standby_loss")
        + sum(run.energy_j(f"{n}.heat") for n in ("base", "kitchen", "living"))
    )
    out = run.energy_j("zone.heat_loss")
    stored = 1.5e7 * (
        run["zone.temperature"][-1] - run["zone.temperature"][0]
    ) + 1.2e8 * (run["zone.fabric_temperature"][-1] - run["zone.fabric_temperature"][0])
    assert into - out == pytest.approx(stored, rel=1e-9)
    # the termo balances too: element heat = stored + standby + draws
    termo = (
        WATER_HEAT_CAPACITY
        * 80.0
        * (run["termo.temperature"][-1] - run["termo.temperature"][0])
    )
    draw = twin.inputs(run.t, start=START, outdoor=0.0)["termo.draw"]  # held input
    drawn = float(np.sum(draw[:-1] * np.diff(run.t)))
    assert run.energy_j("termo.heat") == pytest.approx(
        termo + run.energy_j("termo.standby_loss") + drawn, rel=1e-9
    )


def test_electricity_meter_is_the_schedules_plus_the_termo(backend):
    """The input-driven part of the meter is exact: two days of
    base (120 W) + kitchen (3.9 kWh) + living room (0.75 kWh)."""
    _, run = _two_days(backend)
    loads = sum(run.energy_j(f"{n}.heat") for n in ("base", "kitchen", "living"))
    expected = 2 * (120.0 * 24 + KITCHEN.daily_sum() + LIVING.daily_sum()) * 3600.0
    assert loads == pytest.approx(expected, rel=1e-12)
    termo = run.energy_kwh("electricity") - expected / 3.6e6
    assert termo == pytest.approx(run.energy_j("termo.fuel_power") / 3.6e6, rel=1e-12)
    # the termo heats 170 L/day of tap water from 15 to 40 °C and loses
    # about U·40 K of standby: about 6 kWh a day
    draws = 2 * 170 * WATER_HEAT_CAPACITY * 25 / 3.6e6
    standby = 2 * 24 * 1.1 * 40 / 1000
    assert termo == pytest.approx(draws + standby, rel=0.03)


def test_daily_windows_and_costs_add_up(backend):
    _, run = _two_days(backend)
    for meter in ("electricity", "gas"):
        days = [run.energy_kwh(meter, between=(d * DAY, (d + 1) * DAY)) for d in range(2)]
        assert sum(days) == pytest.approx(run.energy_kwh(meter), rel=1e-12)
    # a cost is price × energy plus the standing charge, nothing else
    assert run.cost_eur("gas", 0.07, fixed_eur_per_day=0.30) == pytest.approx(
        0.07 * run.energy_kwh("gas") + 0.60, rel=1e-12
    )
    assert run.cost_eur("electricity", 0.0) == 0.0
    with pytest.raises(ValueError, match="grid"):
        run.energy_kwh("gas", between=(1.0, DAY))
    with pytest.raises(KeyError, match="meter"):
        run.energy_kwh("water")
    with pytest.raises(ValueError, match="negative"):
        run.cost_eur("gas", -0.1)


def test_a_measured_series_replaces_a_schedule(backend):
    """Feeding the kitchen input a measured 500 W puts exactly 500 W × 48 h on
    the meter for the kitchen. Its heat warms the flat, so the boiler burns
    less gas, and the termo, standing in a warmer kitchen, loses less."""
    _, base = _two_days(backend)
    twin = madrid_flat(backend=backend)
    t = base.t
    measured = twin.simulate(
        t, start=START, outdoor=_january(t), kitchen=np.full(t.size, 500.0)
    )
    assert measured.energy_j("kitchen.heat") == pytest.approx(500.0 * 48 * 3600)
    assert measured.energy_kwh("gas") < base.energy_kwh("gas")
    assert measured.energy_j("termo.standby_loss") < base.energy_j("termo.standby_loss")
    assert measured.energy_j("termo.fuel_power") < base.energy_j("termo.fuel_power")


def test_scenarios_move_the_way_physics_says(backend):
    """Colder outside: more gas. Better envelope: less gas. Neither changes
    the appliances."""
    twin, base = _two_days(backend)
    t = base.t
    cold = twin.simulate(t, start=START, outdoor=_january(t) - 6.0)
    twin.model.set_parameters({"zone.envelope.conductance": 100.0})
    insulated = twin.simulate(t, start=START, outdoor=_january(t))
    g0, gc, gi = (r.energy_kwh("gas") for r in (base, cold, insulated))
    assert gc > g0 > gi > 0
    # Upper bound on the cold spell's extra gas: outdoor air 6 K colder can at
    # most add (UA + ventilation)·6 K of loss, which is what it adds the
    # moment the fabric is still warm. It adds less as the fabric cools, and
    # nothing at night while the heating is off.
    assert gc - g0 < (160.0 + 40.0) * 6.0 * 48 / 1000 / 0.9
    assert base.energy_kwh("electricity") == pytest.approx(
        cold.energy_kwh("electricity"), rel=1e-2
    )


def test_madrid_flat_keeps_itself_comfortable(backend):
    """Sanity for the bundled example: 20 °C by day, 16 °C setback at night."""
    _, run = _two_days(backend)
    T = run.indoor_temperature - K0
    assert T.min() > 16.0 and T.max() < 20.5
    assert 30 < run.energy_kwh("gas") / 2 < 80  # kWh a day at 6 °C mean


# ---------------------------------------------------------------- seville


def test_seville_house_runs_on_electricity_alone(backend):
    twin = seville_house(backend=backend)
    assert twin.gas_outputs == []
    assert {"heatpump.fuel_power", "aircon.fuel_power", "termo.fuel_power"} <= set(
        twin.electric_outputs
    )
    assert sorted(twin.input_names) == ["kitchen", "living", "outdoor", "termo.draw"]


def test_seville_summer_costs_more_than_spring(backend):
    """A July week needs cooling; a mild late-April week (18 °C mean, between
    both setpoints) needs nothing. The whole difference on the meter is the
    air conditioner, and the cost scales with it."""
    twin = seville_house(backend=backend)
    t = np.arange(0, 7 * DAY + 1, 1800.0)
    july = twin.simulate(t, start=JULY, outdoor=_july(t))
    mild = twin.simulate(t, start=JULY, outdoor=K0 + 18.0)
    assert np.all(mild["heatpump.heat"] == 0.0) and np.all(mild["aircon.cool"] == 0.0)
    ac_kwh = july.energy_j("aircon.fuel_power") / 3.6e6
    assert ac_kwh > 20.0  # a July week in Seville is real money
    assert july.energy_kwh("electricity") - mild.energy_kwh(
        "electricity"
    ) == pytest.approx(
        ac_kwh
        + (july.energy_j("termo.fuel_power") - mild.energy_j("termo.fuel_power")) / 3.6e6,
        rel=1e-9,
    )
    price = 0.25
    assert july.cost_eur("electricity", price) - mild.cost_eur("electricity", price) == (
        pytest.approx(
            price * (july.energy_kwh("electricity") - mild.energy_kwh("electricity"))
        )
    )


def test_seville_cooling_balance_and_eer(backend):
    """In a hot week: heat in (gains, through the envelope) = heat pumped out
    plus heat stored; electricity for cooling = heat removed / EER."""
    twin = seville_house(backend=backend)
    t = np.arange(0, 7 * DAY + 1, 600.0)
    run = twin.simulate(t, start=JULY, outdoor=_july(t))
    gains = sum(
        run.energy_j(f"{n}.heat") for n in ("base", "kitchen", "living", "occupants")
    )
    stored = 1.6e7 * (
        run["zone.temperature"][-1] - run["zone.temperature"][0]
    ) + 1.5e8 * (run["zone.fabric_temperature"][-1] - run["zone.fabric_temperature"][0])
    # zone.heat_loss is negative in summer: heat comes *in* from outside
    into = gains - run.energy_j("zone.heat_loss") + run.energy_j("heatpump.heat")
    assert into - run.energy_j("aircon.cool") == pytest.approx(stored, rel=1e-9)
    assert run.energy_j("aircon.fuel_power") == pytest.approx(
        run.energy_j("aircon.cool") / 2.8, rel=1e-12
    )


def test_raising_the_cooling_setpoint_saves_electricity(backend):
    twin = seville_house(backend=backend)
    t = np.arange(0, 7 * DAY + 1, 1800.0)
    base = twin.simulate(t, start=JULY, outdoor=_july(t))
    twin.model.set_parameters({"aircon.setpoint.temperature": K0 + 26.0})
    milder = twin.simulate(t, start=JULY, outdoor=_july(t))
    assert milder.energy_kwh("electricity") < base.energy_kwh("electricity")
    assert milder.indoor_temperature.max() > base.indoor_temperature.max()


# ---------------------------------------------------------------- plumbing


def test_water_heater_outdoors_loses_to_the_outdoor_air(backend):
    zone = ThermalZone(150.0, 2e7)
    termo = WaterHeater(80.0, draw_schedule=Schedule.constant(0.0), name="termo")
    twin = build_home(
        zone,
        gains=[BaseLoad(100.0)],
        water_heaters=[(termo, "outdoors")],
        backend=backend,
    )
    t = np.arange(0, 3600.0 + 1, 600.0)
    run = twin.simulate(t, start=START, outdoor=K0 + 5.0)
    assert run["termo.standby_loss"][0] == pytest.approx(1.1 * (60.0 - 5.0))


def test_build_home_refuses_what_it_cannot_run(backend):
    zone = ThermalZone(150.0, 2e7)
    t = np.arange(0, 7200.0 + 1, 600.0)
    twin = build_home(zone, gains=[Appliance(name="tv")], backend=backend)
    with pytest.raises(KeyError, match="no value and no schedule"):
        twin.simulate(t, start=START, outdoor=K0)
    with pytest.raises(KeyError, match="not inputs"):
        twin.simulate(t, start=START, outdoor=K0, tv=0.0, oven=1.0)
    with pytest.raises(ValueError, match="values for"):
        twin.simulate(t, start=START, outdoor=K0, tv=np.zeros(3))
    with pytest.raises(ValueError, match="location"):
        build_home(
            ThermalZone(), water_heaters=[(WaterHeater(), "garage")], backend=backend
        )
    with pytest.raises(KeyError, match="not inputs of this home"):
        build_home(
            ThermalZone(), schedules={"oven": Schedule.constant(1.0)}, backend=backend
        )


# ---------------------------------------------------------------- examples


def test_the_madrid_example_runs_offline(capsys):
    script = runpy.run_path(str(EXAMPLES / "example_home.py"), run_name="example")
    results = script["main"]("numpy")
    out = capsys.readouterr().out
    assert "insulated envelope" in out and "cold spell" in out
    built, insulated, cold = (results[k][1] for k in results)
    assert insulated < built < cold


def test_the_seville_example_runs_offline(capsys):
    script = runpy.run_path(str(EXAMPLES / "seville_summer.py"), run_name="example")
    results = script["main"]("numpy")
    out = capsys.readouterr().out
    assert "cooling at 26" in out and "heatwave" in out
    assert results["cooling at 26 °C"] < results["as built, 25 °C"]
    assert results["August heatwave, +4 °C"] > results["as built, 25 °C"]
