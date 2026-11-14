"""What-if scenarios, pinned against hand-computed expectations.

The fixed synthetic twin is chosen so that every hour is a closed form:

* a 1R1C zone, envelope 180 W/K plus ventilation 30 W/K (K = 210 W/K);
* a heat pump (COP 3) under a proportional thermostat, 8 kW over a 2 K band
  (G = 4000 W/K), set to 20 °C, never saturated and never off;
* a 150 W base load indoors, and a dishwasher drawing 1.2 kW at 21:00 whose
  heat goes down the drain (``indoors=False``);
* a gas water heater on the balcony (outdoors): 8 kW burner over a 2 K band
  (G_w = 4000 W/K), 60 °C, standby 1.1 W/K, 90 % efficient, a constant
  200 W hot-water draw;
* a constant outdoor temperature, February 2026: 28 days, 20 weekdays and 8
  weekend days, no national holiday, no DST change.

With constant conditions inside the home the state is a steady state, so:

    heat pump heat   H = G (K (T_set − T_out) − 150) / (G + K)
    electricity/h    e = 150 W + H / 3,       plus 1.2 kWh at 21:00
    burner heat      Q = G_w (U (60 − T_out) + 200) / (G_w + U)
    gas/h            Q / 0.9

and the 2.0TD split is a count of hours: weekdays give 8 h each of P1, P2
and P3, weekends 24 h of P3. The bills are the tariff's arithmetic written
out here, not called from the code under test. Every sentence is pinned
word for word from those numbers.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from otwin.runtime import engine_available

from calibration import HourlyData
from components import (
    ZERO_CELSIUS,
    Appliance,
    BaseLoad,
    HeatPump,
    Schedule,
    ThermalZone,
    WaterHeater,
    build_home,
)
from scenarios import (
    ElectricityTariff,
    GasTariff,
    Insulation,
    MoveAppliance,
    OutdoorShift,
    ScenarioStudy,
    SetpointChange,
    Tariff,
    TariffChange,
    insulated_conductance,
    period_2_0td,
)

K0 = ZERO_CELSIUS
MAD = ZoneInfo("Europe/Madrid")
FEB = datetime(2026, 2, 1, tzinfo=MAD)
DAYS, HOURS = 28, 28 * 24
WEEKDAYS, WEEKEND = 20, 8
DISHWASHER = Schedule([1200.0 if h == 21 else 0.0 for h in range(24)])

# ---------------------------------------------------------------- the hand side

G, UA, VENT, BASE, COP = 4000.0, 180.0, 30.0, 150.0, 3.0
GW, U_TANK, DRAW, ETA = 4000.0, 1.1, 200.0, 0.9
PRICES = {"P1": 0.20, "P2": 0.13, "P3": 0.08}
FLAT = 0.15
POWER_KW, POWER_EUR, METER_EUR = 4.6, 0.10, 0.0266
IEE, VAT = 0.0511269632, 0.21
GAS_EUR, GAS_FIXED, IEH, PCS, FC = 0.07, 0.20, 0.00234, 11.7, 0.98


def heat_pump_w(t_out: float, t_set: float = 20.0, ua: float = UA) -> float:
    k = ua + VENT
    h = G * (k * (t_set - t_out) - BASE) / (G + k)
    assert 0 < h < 8000.0  # never off, never saturated: the formula holds
    return h


def electricity_w(t_out: float, **kw) -> float:
    """Every hour's electricity except the dishwasher, W."""
    return BASE + heat_pump_w(t_out, **kw) / COP


def gas_kwh_per_hour(t_out: float) -> float:
    q = GW * (U_TANK * (60.0 - t_out) + DRAW) / (GW + U_TANK)
    return q / ETA / 1000.0


def by_period(t_out: float, dish_hour: int = 21, **kw) -> dict[str, float]:
    """February 2026 electricity by 2.0TD period, kWh, counted by hand."""
    e = electricity_w(t_out, **kw) / 1000.0
    out = {
        "P1": e * 8 * WEEKDAYS,
        "P2": e * 8 * WEEKDAYS,
        "P3": e * (8 * WEEKDAYS + 24 * WEEKEND),
    }
    weekday_period = (
        "P1"
        if dish_hour in (10, 11, 12, 13, 18, 19, 20, 21)
        else ("P3" if dish_hour < 8 else "P2")
    )
    out[weekday_period] += 1.2 * WEEKDAYS
    out["P3"] += 1.2 * WEEKEND
    return out


def electricity_bill(kwh: dict[str, float], days: int = DAYS, prices=PRICES) -> float:
    energy = sum(prices[p] * kwh[p] for p in kwh)
    power = POWER_KW * POWER_EUR * days
    tax = IEE * (energy + power)
    meter = METER_EUR * days
    return (energy + power + tax + meter) * (1 + VAT)


def gas_bill(kwh: float, days: int = DAYS) -> float:
    return (GAS_EUR * kwh + GAS_FIXED * days + IEH * kwh) * (1 + VAT)


def gas_m3(kwh: float) -> float:
    return kwh / (FC * PCS)


def month(t_out: float, **kw) -> tuple[dict[str, float], float, float]:
    """(kWh by period, gas kWh, total €) of February at a constant ``t_out``."""
    kwh = by_period(t_out, **kw)
    gas = gas_kwh_per_hour(t_out) * HOURS
    return kwh, gas, electricity_bill(kwh) + gas_bill(gas)


# ---------------------------------------------------------------- the twin side

TARIFF = Tariff(
    ElectricityTariff(
        "2.0TD",
        PRICES,
        power_kw=POWER_KW,
        power_eur_per_kw_day=POWER_EUR,
        meter_eur_per_day=METER_EUR,
    ),
    GasTariff("RL.1", GAS_EUR, fixed_eur_per_day=GAS_FIXED),
)
FLAT_TARIFF = Tariff(
    ElectricityTariff(
        "Tarifa Plana",
        FLAT,
        power_kw=POWER_KW,
        power_eur_per_kw_day=POWER_EUR,
        meter_eur_per_day=METER_EUR,
    ),
    TARIFF.gas,
)


def fixed_twin(backend: str, *, scheduled_setpoint: bool = False):
    heating = HeatPump(
        8000.0,
        cop=COP,
        band=2.0,
        setpoint=None if scheduled_setpoint else K0 + 20.0,
        setpoint_schedule=Schedule.constant(K0 + 20.0) if scheduled_setpoint else None,
        name="heating",
    )
    return build_home(
        ThermalZone(UA, 1.2e7, ventilation=VENT, temperature=K0 + 19.0),
        gains=[
            BaseLoad(BASE),
            Appliance(schedule=DISHWASHER, indoors=False, name="dishwasher"),
        ],
        conditioning=[heating],
        water_heaters=[
            (
                WaterHeater(
                    80.0,
                    power=8000.0,
                    band=2.0,
                    loss_ua=U_TANK,
                    efficiency=ETA,
                    fuel="gas",
                    draw_schedule=Schedule.constant(DRAW),
                    name="boiler",
                ),
                "outdoors",
            )
        ],
        backend=backend,
    )


def study(
    backend: str, *, t_out: float = 5.0, tariff: Tariff = TARIFF, **kw
) -> ScenarioStudy:
    return ScenarioStudy(
        fixed_twin(backend, **kw), start=FEB, outdoor_c=t_out, hours=HOURS, tariff=tariff
    )


def assert_month(outcome, kwh: dict[str, float], gas: float, eur: float) -> None:
    [m] = outcome.months
    assert (m.label, m.days, m.hours) == ("February 2026", DAYS, HOURS)
    for p, v in kwh.items():
        assert m.electricity_kwh_by_period[p] == pytest.approx(v, rel=1e-10)
    assert m.electricity_kwh == pytest.approx(sum(kwh.values()), rel=1e-10)
    assert m.gas_kwh == pytest.approx(gas, rel=1e-8)  # the solver's Newton tolerance
    assert m.gas_m3 == pytest.approx(gas_m3(gas), rel=1e-8)
    assert m.total_eur == pytest.approx(eur, rel=1e-9)


def eur(x: float) -> str:
    return f"€{x:.2f}"


# ---------------------------------------------------------------- tariffs


@pytest.mark.parametrize(
    "when, period",
    [
        (datetime(2026, 2, 2, 7), "P3"),
        (datetime(2026, 2, 2, 8), "P2"),
        (datetime(2026, 2, 2, 10), "P1"),
        (datetime(2026, 2, 2, 13), "P1"),
        (datetime(2026, 2, 2, 14), "P2"),
        (datetime(2026, 2, 2, 18), "P1"),
        (datetime(2026, 2, 2, 21), "P1"),
        (datetime(2026, 2, 2, 22), "P2"),
        (datetime(2026, 2, 7, 19), "P3"),  # Saturday
        (datetime(2026, 1, 6, 19), "P3"),  # Epiphany, a national holiday
        (datetime(2026, 4, 3, 19), "P1"),  # Good Friday: movable, an ordinary day
    ],
)
def test_2_0td_periods(when, period):
    assert period_2_0td(when) == period
    assert period_2_0td(date(when.year, when.month, when.day), when.hour) == period


def test_bills_itemise_like_a_spanish_bill():
    e = TARIFF.electricity.bill({"P1": 100.0, "P2": 50.0, "P3": 200.0}, 30)
    energy = 0.20 * 100 + 0.13 * 50 + 0.08 * 200
    power = 4.6 * 0.10 * 30
    assert e["energy"] == pytest.approx(energy)
    assert e["electricity_tax"] == pytest.approx(IEE * (energy + power))
    assert e["total"] == pytest.approx(
        (energy + power + IEE * (energy + power) + 0.0266 * 30) * 1.21
    )
    g = TARIFF.gas.bill(500.0, 30)
    assert g["total"] == pytest.approx((0.07 * 500 + 0.20 * 30 + 0.00234 * 500) * 1.21)
    assert TARIFF.gas.m3(1146.6) == pytest.approx(100.0)  # 100 m³ × 0.98 × 11.7
    assert TARIFF.electricity.time_of_use and not FLAT_TARIFF.electricity.time_of_use
    with pytest.raises(ValueError, match="each of"):
        ElectricityTariff("x", {"P1": 0.2})
    with pytest.raises(ValueError, match="negative"):
        GasTariff("x", -0.1)


# ---------------------------------------------------------------- insulation arithmetic


def test_insulated_conductance_by_hand():
    # 120 m² of envelope at U = 1.5 W/m²K; 40 m² get R 2: 80·1.5 + 40/(1/1.5 + 2) = 135
    assert insulated_conductance(180.0, 2.0, 40.0, 120.0) == pytest.approx(135.0)
    # the whole envelope: resistances in series, 1/UA' = 1/UA + R/A
    assert insulated_conductance(180.0, 2.0, 120.0) == pytest.approx(
        1 / (1 / 180 + 2 / 120)
    )
    with pytest.raises(ValueError, match="larger than the envelope"):
        insulated_conductance(180.0, 2.0, 130.0, 120.0)
    with pytest.raises(ValueError, match="positive"):
        insulated_conductance(180.0, 0.0, 40.0, 120.0)


# ---------------------------------------------------------------- the baseline


def test_baseline_month_by_hand(backend):
    st = study(backend)
    kwh, gas, total = month(5.0)
    assert_month(st.baseline, kwh, gas, total)
    m = st.baseline.months[0]
    assert m.electricity_eur == pytest.approx(electricity_bill(kwh), rel=1e-10)
    assert m.gas_eur == pytest.approx(gas_bill(gas), rel=1e-8)


# ---------------------------------------------------------------- each scenario


@pytest.mark.parametrize("delta", [2.0, -3.0])
def test_outdoor_shift(backend, delta):
    st = study(backend)
    r = st.run(OutdoorShift(delta))
    kwh0, gas0, eur0 = month(5.0)
    kwh1, gas1, eur1 = month(5.0 + delta)
    assert_month(r.outcome, kwh1, gas1, eur1)
    dk = sum(kwh1.values()) - sum(kwh0.values())
    dm = gas_m3(gas1) - gas_m3(gas0)
    word, more_less, lower_higher = (
        ("warmer", "less", "lower") if delta > 0 else ("colder", "more", "higher")
    )
    assert r.name == f"{abs(delta):g} °C {word} outside"
    assert r.sentence == (
        f"If it were {abs(delta):g} °C {word} outside, your home would use "
        f"{abs(dk):.0f} kWh {more_less} electricity and {abs(dm):.1f} m³ {more_less} gas "
        f"in February 2026, and your bills would be {eur(abs(eur1 - eur0))} {lower_higher} "
        f"({eur(eur1)} instead of {eur(eur0)})."
    )
    assert r.electricity_kwh_change == pytest.approx(dk, rel=1e-9)


@pytest.mark.parametrize("scheduled", [False, True], ids=["parameter", "schedule"])
def test_setpoint_change(backend, scheduled):
    """A setpoint parameter and a constant schedule are moved alike, to the same result."""
    st = study(backend, scheduled_setpoint=scheduled)
    r = st.run(SetpointChange(-1.0))
    kwh0, gas0, eur0 = month(5.0)
    kwh1, gas1, eur1 = month(5.0, t_set=19.0)
    assert_month(r.outcome, kwh1, gas1, eur1)
    dk = sum(kwh0.values()) - sum(kwh1.values())
    assert r.sentence == (
        f"If you turned the heating down by 1 °C, your home would use {dk:.0f} kWh less "
        f"electricity in February 2026, and your bills would be {eur(eur0 - eur1)} lower "
        f"({eur(eur1)} instead of {eur(eur0)})."
    )
    assert r.gas_m3_change == pytest.approx(
        0.0, abs=1e-9
    )  # the water heater does not care


def test_moving_the_dishwasher_to_the_night(backend):
    st = study(backend)
    r = st.run(MoveAppliance("dishwasher", from_hours=(21,), to_hours=(2,)))
    kwh0, gas0, eur0 = month(5.0)
    kwh1, gas1, eur1 = month(5.0, dish_hour=2)
    assert_month(r.outcome, kwh1, gas1, eur1)
    # by hand: 1.2 kWh × 20 weekdays moves from P1 (0.20) to P3 (0.08)
    saving = 1.2 * WEEKDAYS * (0.20 - 0.08) * (1 + IEE) * (1 + VAT)
    assert eur0 - eur1 == pytest.approx(saving, rel=1e-9)
    assert r.sentence == (
        "If you ran the dishwasher at 02:00 instead of 21:00, your home would use the same "
        f"energy in February 2026, but your bills would be {eur(saving)} lower "
        f"({eur(eur1)} instead of {eur(eur0)}), because electricity is cheaper at those hours."
    )


def test_moving_an_appliance_on_a_flat_tariff_changes_nothing(backend):
    st = study(backend, tariff=FLAT_TARIFF)
    r = st.run(MoveAppliance("dishwasher", from_hours=(21,), to_hours=(2,)))
    kwh0, gas0, _ = month(5.0)
    total = electricity_bill(kwh0, prices={p: FLAT for p in PRICES}) + gas_bill(gas0)
    assert r.sentence == (
        "If you ran the dishwasher at 02:00 instead of 21:00, nothing would change: your "
        f"home would use the same energy in February 2026 and your bills would stay at "
        f"{eur(total)}."
    )


def test_insulation(backend):
    st = study(backend)
    r = st.run(Insulation(r_value=2.0, area_m2=40.0, envelope_area_m2=120.0))
    kwh0, gas0, eur0 = month(5.0)
    kwh1, gas1, eur1 = month(5.0, ua=135.0)  # 180 → 135 W/K, by hand above
    assert_month(r.outcome, kwh1, gas1, eur1)
    dk = sum(kwh0.values()) - sum(kwh1.values())
    assert r.sentence == (
        "If you added insulation of R 2 m²·K/W over 40 m², cutting your home's heat loss "
        f"from 180 to 135 W per °C, your home would use {dk:.0f} kWh less electricity in "
        f"February 2026, and your bills would be {eur(eur0 - eur1)} lower "
        f"({eur(eur1)} instead of {eur(eur0)})."
    )


def test_tariff_change(backend):
    st = study(backend)
    r = st.run(TariffChange(FLAT_TARIFF))
    kwh0, gas0, eur0 = month(5.0)
    eur1 = electricity_bill(kwh0, prices={p: FLAT for p in PRICES}) + gas_bill(gas0)
    assert_month(r.outcome, kwh0, gas0, eur1)
    assert r.sentence == (
        f"On the “Tarifa Plana + RL.1” tariff the same use would cost {eur(eur1 - eur0)} more "
        f"in February 2026 ({eur(eur1)} instead of {eur(eur0)})."
    )


# ---------------------------------------------------------------- months, determinism


def test_a_two_month_study_bills_each_month(backend):
    """February and March 2026. March has 31 days, 22 weekdays and 9 weekend
    days, one of them the 23-hour DST Sunday (29 March): 743 hours, of which
    176 P1, 176 P2 and 391 P3. Sentences quote the average month."""
    hours = 672 + 743
    st = ScenarioStudy(
        fixed_twin(backend), start=FEB, outdoor_c=5.0, hours=hours, tariff=TARIFF
    )
    feb, mar = st.baseline.months
    assert (feb.label, feb.days, feb.hours) == ("February 2026", 28, 672)
    assert (mar.label, mar.days, mar.hours) == ("March 2026", 31, 743)
    e = electricity_w(5.0) / 1000.0
    mar_kwh = {"P1": e * 176 + 1.2 * 22, "P2": e * 176, "P3": e * 391 + 1.2 * 9}
    for p, v in mar_kwh.items():
        assert mar.electricity_kwh_by_period[p] == pytest.approx(v, rel=1e-10)
    mar_gas = gas_kwh_per_hour(5.0) * 743
    assert mar.gas_m3 == pytest.approx(gas_m3(mar_gas), rel=1e-8)
    assert mar.total_eur == pytest.approx(
        electricity_bill(mar_kwh, days=31) + gas_bill(mar_gas, days=31), rel=1e-9
    )
    r = st.run(SetpointChange(-1.0))
    assert " a month, and your bills would be " in r.sentence
    assert r.eur_change == pytest.approx(
        (r.outcome.total_eur - st.baseline.total_eur) / 2, rel=1e-12
    )
    table = r.table()
    assert "February 2026" in table and "March 2026" in table


def test_results_are_deterministic(backend):
    a = study(backend).run_all([OutdoorShift(2.0), SetpointChange(-1.0)])
    b = study(backend).run_all([OutdoorShift(2.0), SetpointChange(-1.0)])
    for x, y in zip(a, b, strict=True):
        assert x.sentence == y.sentence
        np.testing.assert_array_equal(
            x.outcome.hourly_electricity_kwh, y.outcome.hourly_electricity_kwh
        )
        assert x.outcome.total_eur == y.outcome.total_eur


@pytest.mark.skipif(not engine_available(), reason="needs the otwin_engine extension")
def test_both_backends_say_the_same():
    scenarios = [
        OutdoorShift(2.0),
        SetpointChange(-1.0),
        TariffChange(FLAT_TARIFF),
        MoveAppliance("dishwasher", (21,), (2,)),
        Insulation(2.0, 40.0, 120.0),
    ]
    a = study("numpy").run_all(scenarios)
    b = study("rust").run_all(scenarios)
    assert [r.sentence for r in a] == [r.sentence for r in b]


# ---------------------------------------------------------------- what cannot be asked


def test_scenarios_refuse_what_the_home_does_not_have(backend):
    st = study(backend)
    with pytest.raises(ValueError, match="no air conditioning"):
        st.run(SetpointChange(1.0, machine="cooling"))
    with pytest.raises(ValueError, match="no appliance called 'oven'"):
        st.run(MoveAppliance("oven", (13,), (3,)))
    with pytest.raises(ValueError, match="hours are 0 to 23"):
        MoveAppliance("dishwasher", (21,), (24,))
    with pytest.raises(ValueError, match="as many hours"):
        MoveAppliance("dishwasher", (21, 22), (2,))
    with pytest.raises(ValueError, match="gas tariff"):
        no_gas = study(backend, tariff=Tariff(TARIFF.electricity))
        no_gas.evaluate(no_gas.base_case())


def test_from_calibration_uses_the_calibrated_twin_and_its_month(backend):
    twin = fixed_twin(backend)
    data = HourlyData(FEB, np.full(HOURS, 1.0), np.full(HOURS, 5.0))
    st = ScenarioStudy.from_calibration(SimpleNamespace(twin=twin), data, TARIFF)
    kwh, gas, total = month(5.0)
    assert_month(st.baseline, kwh, gas, total)


def test_the_what_if_example_runs_offline(capsys):
    import runpy
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "examples" / "what_if.py"
    fit_backend = "rust" if engine_available() else "numpy"
    results = runpy.run_path(str(script), run_name="example")["main"](fit_backend)
    out = capsys.readouterr().out
    assert len(results) == 5 and all(r.sentence in out for r in results)
    colder, lower, night, insulated, flat = results
    assert colder.eur_change > 0 > lower.eur_change
    assert (
        night.electricity_kwh_change == pytest.approx(0.0, abs=1e-9)
        and night.eur_change < 0
    )
    assert insulated.eur_change < 0 and flat.eur_change > 0
