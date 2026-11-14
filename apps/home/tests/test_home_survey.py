"""The survey: selectors in, a twin with typical values out, pinned by hand."""

from __future__ import annotations

import pytest

from components import AirConditioner, Boiler, ElectricHeater, HeatPump, WaterHeater
from survey import (
    FLOOR_AREA,
    PROVINCES,
    QUESTIONS,
    HomeDescription,
    assumptions,
    build_twin,
    questions_json,
)


def machines(twin):
    return {type(c) for c in twin.system.components}


def test_every_question_is_a_selector_with_a_valid_default():
    for q in QUESTIONS:
        assert q.kind in ("single", "multi") and q.options
        values = q.values()
        defaults = q.default if q.kind == "multi" else (q.default,)
        assert all(d in values for d in defaults), q.id
        assert len(set(values)) == len(values), q.id
    data = questions_json()
    assert [q["id"] for q in data["questions"]] == [q.id for q in QUESTIONS]
    assert len(data["provinces"]) == 52  # 50 provinces, Ceuta and Melilla
    canary = {p.value for p in PROVINCES if p.timezone == "Atlantic/Canary"}
    assert canary == {"las_palmas", "santa_cruz"}


def test_defaults_build_the_typical_flat(backend):
    """75 m² flat, 1980-2006: envelope 2.0 W/K per m², ventilation 0.45,
    air and furniture 1.6e5 J/K per m², heat pump 60 W per m²."""
    twin = build_twin(HomeDescription(), backend=backend)
    p = twin.model.parameters
    assert p["zone.envelope.conductance"] == pytest.approx(2.0 * 75)
    assert p["zone.ventilation.conductance"] == pytest.approx(0.45 * 75)
    assert p["zone.air.capacity"] == pytest.approx(1.6e5 * 75)
    assert p["heating.thermostat.power"] == pytest.approx(4500.0)
    assert p["base.power"] == pytest.approx(100 + 15 * 2)
    assert p["occupants.power"] == pytest.approx(2 * 60.0)
    assert sorted(twin.input_names) == sorted(
        [
            "outdoor",
            "heating.setpoint",
            "dishwasher",
            "washing_machine",
            "oven",
            "tv",
            "water_heater.draw",
        ]
    )


@pytest.mark.parametrize(
    "home_type, built, size, ua",
    [
        ("flat", "pre1980", "s", 2.6 * 50),
        ("terraced", "post2007", "l", 1.1 * 1.5 * 105),
        ("detached", "1980_2006", "xl", 2.0 * 2.0 * 140),
    ],
)
def test_envelope_follows_type_age_and_size(home_type, built, size, ua):
    d = HomeDescription(home_type=home_type, built=built, size=size)
    assert d.envelope_ua == pytest.approx(ua)
    assert d.area == FLOOR_AREA[size]


def test_heating_and_cooling_choices(backend):
    assert HeatPump in machines(
        build_twin(HomeDescription(heating="heat_pump"), backend=backend)
    )
    assert ElectricHeater in machines(
        build_twin(HomeDescription(heating="electric"), backend=backend)
    )
    gas = build_twin(HomeDescription(heating="gas"), backend=backend)
    assert Boiler in machines(gas) and gas.gas_outputs == ["heating.fuel_power"]
    none = build_twin(HomeDescription(heating="none", water="unknown"), backend=backend)
    assert not none.gas_outputs and "heating.setpoint" not in none.input_names
    cool = build_twin(HomeDescription(cooling="yes"), backend=backend)
    assert AirConditioner in machines(cool)
    assert cool.model.parameters["cooling.setpoint.temperature"] == pytest.approx(298.15)
    winter = build_twin(
        HomeDescription(cooling="yes"), backend=backend, with_cooling=False
    )
    assert AirConditioner not in machines(winter)


def test_setpoints_and_people_scale_the_schedules(backend):
    lower = build_twin(HomeDescription(thermostat="21", night="lower"), backend=backend)
    s = lower.schedules["heating.setpoint"].values
    assert s[12] == pytest.approx(294.15) and s[3] == pytest.approx(289.15)
    same = build_twin(HomeDescription(night="same"), backend=backend)
    assert set(same.schedules["heating.setpoint"].values) == {293.15}
    four = build_twin(HomeDescription(people="4"), backend=backend)
    two = build_twin(HomeDescription(people="2"), backend=backend)
    assert four.schedules["dishwasher"].daily_sum() == pytest.approx(
        2 * two.schedules["dishwasher"].daily_sum()
    )
    assert four.schedules["water_heater.draw"].daily_sum() == pytest.approx(
        2 * two.schedules["water_heater.draw"].daily_sum()
    )


def test_drained_appliances_heat_nothing_indoors(backend):
    twin = build_twin(
        HomeDescription(appliances=("dishwasher", "oven", "ev")), backend=backend
    )
    by_name = {c.name: c for c in twin.system.components}
    assert not by_name["dishwasher"].indoors and not by_name["ev"].indoors
    assert by_name["oven"].indoors
    assert all(
        isinstance(c, WaterHeater)
        for c in twin.system.components
        if c.name == "water_heater"
    )


def test_canary_homes_keep_canary_time(backend):
    twin = build_twin(HomeDescription(province="las_palmas"), backend=backend)
    assert twin.schedules["heating.setpoint"].timezone == "Atlantic/Canary"


def test_answers_are_validated_and_explained():
    with pytest.raises(ValueError, match="size: 'huge' is not one of"):
        HomeDescription(size="huge")
    with pytest.raises(ValueError, match="appliances: 'sauna'"):
        HomeDescription(appliances=("dishwasher", "sauna"))
    d = HomeDescription.from_answers(
        {"size": "l", "unknown_key": 1, "appliances": ["tv"]}
    )
    assert d.size == "l" and d.appliances == ("tv",)
    text = assumptions(HomeDescription(heating="gas"))
    assert text[0].startswith("A typical flat of about 75 m²")
    assert any("gas does not show on the electricity meter" in t for t in text)
    assert text[-1].startswith("These are starting points.")
