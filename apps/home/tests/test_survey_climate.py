"""An average year per province, the sun through the windows, numeric
answers, and the twelve-month forecast built on the fitted model."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from survey import HomeDescription, build_twin
from survey.climate import normals_of, solar_profile, typical_year
from survey.questions import QUESTIONS

WEB = Path(__file__).resolve().parents[1] / "web"
for extra in (WEB / "py",):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def test_every_province_has_a_plausible_typical_year():
    for q in QUESTIONS:
        if q.id == "province":
            provinces = [o.value for o in q.options]
    for p in provinces:
        n = normals_of(p)
        assert len(n.monthly_c) == 12 and len(n.solar_kwh_day) == 12
        assert n.monthly_c[6] > n.monthly_c[0]  # July warmer than January
        start, out = typical_year(p)
        assert out.size == 8760 and np.all(np.isfinite(out))
        assert abs(out[:744].mean() - n.monthly_c[0]) < 0.6  # January holds its mean
        _, sun = solar_profile(p)
        assert sun.min() >= 0 and 500 < sun.max() < 1100  # W/m²
        assert sun[:744].sum() / 1000 / 31 == pytest.approx(n.solar_kwh_day[0], rel=0.08)


def test_madrid_reads_like_madrid():
    n = normals_of("madrid")
    assert n.monthly_c[0] == 6.3 and 24.5 < n.monthly_c[6] < 26.5
    assert n.swing_k == 11.0 and n.solar_kwh_day[6] > 7


def test_numeric_answers_are_accepted_beside_the_old_names():
    d = HomeDescription(
        size="92",
        built="1975",
        thermostat="20.5",
        cooling_setpoint="24.5",
        people="3",
        heating_power="12",
    )
    assert d.area == 92 and d.size_class == "l" and d.era == "pre1980"
    assert d.setpoint_c == 20.5 and d.people_count == 3 and d.heating_kw == 12
    old = HomeDescription(size="m", built="1980_2006", heating_power="auto")
    assert old.area == 75 and old.era == "1980_2006" and old.heating_kw is None
    assert (
        HomeDescription(heating_power="0").heating_kw is None
    )  # 0 on the slider: typical
    with pytest.raises(ValueError, match="size"):
        HomeDescription(size="12")  # under the slider's floor
    with pytest.raises(ValueError, match="thermostat"):
        HomeDescription(thermostat="31")


def test_the_twin_has_the_sun_as_an_input_with_a_calendar_schedule():
    twin = build_twin(HomeDescription(), backend="numpy")
    assert "solar" in twin.input_names
    sched = twin.schedules["solar"]
    from datetime import datetime, timezone

    jan = sched.sample(
        np.arange(0, 24 * 3600, 3600), start=datetime(2026, 1, 15, tzinfo=timezone.utc)
    )
    jul = sched.sample(
        np.arange(0, 24 * 3600, 3600), start=datetime(2026, 7, 15, tzinfo=timezone.utc)
    )
    assert jan.max() > 0 and jul.sum() > 2 * jan.sum()  # three times the sun in July
    assert jan[2] == 0.0  # none at night


def test_the_forecast_runs_twelve_months_on_the_fitted_model():
    import webmain

    webmain.forget()
    answers = webmain.load_samples("gas_dec_jan")["answers"]
    assert webmain.analyse(answers)["ok"]
    f = webmain.forecast(answers)
    assert f["ok"] and len(f["months"]) == 12 and f["seen"] == [1, 12]
    jan, jul = f["months"][0], f["months"][6]
    assert jan["seen"] and not jul["seen"]
    assert (
        jan["gas_kwh"] > 5 * jul["gas_kwh"]
    )  # heating in winter, hot water only in summer
    assert jan["eur"] > jul["eur"] and f["totals"]["eur"] == sum(
        m["eur"] for m in f["months"]
    )
    assert f["prices"]["gas"] < 0.1  # from the bills
    # a heat pump with air conditioning: no gas for heating, electricity in summer
    g = webmain.forecast(
        answers,
        {
            "heating": "heat_pump",
            "heating_power": "8",
            "cooling": "yes",
            "cooling_setpoint": "25",
        },
    )
    assert g["ok"] and g["heater"] == "heat_pump" and g["cooling"]
    assert g["months"][6]["conditioning_kwh"] > 100 > f["months"][6]["conditioning_kwh"]
    assert g["totals"]["gas_kwh"] < f["totals"]["gas_kwh"] / 2
    # insulating cuts the gas, not the electricity
    h = webmain.forecast(answers, {"insulation": "walls_windows"})
    assert h["totals"]["gas_kwh"] < 0.75 * f["totals"]["gas_kwh"]
    assert h["totals"]["electricity_kwh"] == f["totals"]["electricity_kwh"]
    with pytest.raises(ValueError, match="insulation"):
        webmain.forecast(answers, {"insulation": "roof"})
    webmain.forget()
    assert webmain.forecast(answers)["ok"] is False  # no model yet


def test_the_demo_home_comes_with_its_own_files():
    import webmain

    d = webmain.demo_home("gas_winter")
    assert d["answers"]["heating"] == "gas" and d["name"].startswith("Demo:")
    kinds = [f["kind"] for f in d["files"]]
    assert kinds.count("gas") == 3 and "electricity" in kinds and "weather" in kinds
    assert all(len(f["data"]) > 100 for f in d["files"])
    with pytest.raises(KeyError):
        webmain.demo_home("mansion")
