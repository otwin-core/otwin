"""The survey: selectors in, a twin with typical values out, pinned by hand."""

from __future__ import annotations

import pytest

from components import (
    AirConditioner,
    Appliance,
    Boiler,
    ElectricHeater,
    GasAppliance,
    HeatGain,
    HeatPump,
    WaterHeater,
)
from survey import (
    FLOOR_AREA,
    PROVINCES,
    QUESTIONS,
    HomeDescription,
    assumptions,
    build_twin,
    home_summary,
    questions_json,
)


def machines(twin):
    return {type(c) for c in twin.system.components}


def test_every_question_is_a_selector_with_a_valid_default():
    for q in QUESTIONS:
        assert q.kind in ("single", "multi", "switch", "slider", "gauge") and q.options
        if q.numeric:
            assert q.minimum < q.maximum and q.step and q.accepts(q.default)
        values = q.values()
        defaults = q.default if q.kind == "multi" else (q.default,)
        assert all(q.accepts(d) for d in defaults), q.id
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
    # people are an input: 70 W of sensible heat each, home half the time
    # on average (all night, one in four by day), not a constant all day
    assert "occupants.power" not in p
    presence = twin.schedules["occupants"].values
    assert presence[3] == pytest.approx(2 * 70.0) and presence[12] == pytest.approx(
        2 * 70.0 / 4
    )
    assert sum(presence) / 24 == pytest.approx(2 * 70.0 / 2)
    assert sorted(twin.input_names) == sorted(
        [
            "outdoor",
            "solar",
            "heating.setpoint",
            "occupants",
            "dishwasher",
            "washing_machine",
            "oven",
            "tv",
            "hob",
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
    with pytest.raises(ValueError, match="size: 'huge' is not a number from 30 to 250"):
        HomeDescription(size="huge")
    with pytest.raises(ValueError, match="appliances: 'sauna'"):
        HomeDescription(appliances=("dishwasher", "sauna"))
    d = HomeDescription.from_answers(
        {"size": "l", "unknown_key": 1, "appliances": ["tv"]}
    )
    assert d.size == "l" and d.appliances == ("tv",)
    # answers saved before cooking had its own question
    old = HomeDescription.from_answers({"appliances": ["hob", "tv"]})
    assert old.appliances == ("tv",) and old.cooking == "electric"


@pytest.mark.parametrize(
    "heating, water, cooking, gas, electric",
    [
        # a combi boiler for everything: three things on the gas meter
        ("gas", "boiler", "gas", {"heating", "water_heater", "hob"}, set()),
        # gas heating, an electric termo, induction
        ("gas", "electric", "electric", {"heating"}, {"water_heater", "hob"}),
        # heat pump, a gas calentador, a gas hob
        ("heat_pump", "gas", "gas", {"water_heater", "hob"}, {"heating"}),
        # all electric with aerotermia for the water
        ("heat_pump", "heat_pump", "electric", set(), {"heating", "water_heater", "hob"}),
        # electric heaters and butane: butane is on no meter
        ("electric", "electric", "butane", set(), {"heating", "water_heater"}),
    ],
)
def test_heating_hot_water_and_cooking_combine_freely(
    backend, heating, water, cooking, gas, electric
):
    d = HomeDescription(heating=heating, water=water, cooking=cooking)
    twin = build_twin(d, backend=backend)
    on = lambda outs: {o.split(".")[0] for o in outs}  # noqa: E731
    assert on(twin.gas_outputs) == gas
    appliances = {"base", "dishwasher", "washing_machine", "oven", "tv"}
    assert on(twin.electric_outputs) - appliances == electric
    assert d.uses_gas == bool(gas)


def test_hot_water_and_hob_machines(backend):
    by = lambda d: {c.name: c for c in build_twin(d, backend=backend).system.components}  # noqa: E731
    combi = by(HomeDescription(heating="gas", water="boiler", cooking="gas"))
    assert combi["water_heater"].fuel == "gas" and combi["water_heater"].efficiency == 0.9
    assert isinstance(combi["hob"], GasAppliance)
    calentador = by(HomeDescription(water="gas"))["water_heater"]
    assert calentador.fuel == "gas" and calentador.efficiency == 0.85
    aerotermia = by(HomeDescription(water="heat_pump"))["water_heater"]
    assert aerotermia.fuel == "electricity" and aerotermia.efficiency == 2.5
    assert isinstance(by(HomeDescription())["hob"], Appliance)
    butane = by(HomeDescription(cooking="butane"))["hob"]
    assert type(butane) is HeatGain and butane.indoors  # warms, never billed


def test_a_gas_hob_burns_twice_what_an_induction_hob_draws(backend):
    induction = build_twin(HomeDescription(cooking="electric"), backend=backend)
    gas = build_twin(HomeDescription(cooking="gas"), backend=backend)
    e = induction.schedules["hob"].daily_sum()
    assert e == pytest.approx(900.0)  # 400 W at 14:00 and 500 W at 21:00, two people
    assert gas.schedules["hob"].daily_sum() == pytest.approx(2 * e)


def test_the_home_summary_is_plain_words():
    rows = dict(
        home_summary(
            HomeDescription(
                province="valladolid",
                heating="gas",
                water="boiler",
                cooking="gas",
                people="3",
                built="pre1980",
            )
        )
    )
    assert list(rows) == [
        "Your home",
        "Insulation",
        "Heat lost to the sky",
        "Heating",
        "Hot water",
        "Cooking",
        "Air conditioning",
        "Appliances",
        "Bills to bring",
    ]
    assert rows["Your home"] == (
        "A flat of about 75 m² in Valladolid, built before 1980. 3 people live there."
    )
    assert rows["Heating"] == "A gas boiler, at 20 °C by day and 16 °C at night."
    assert rows["Hot water"] == "From the gas boiler that heats the home."
    assert "gas bill for the same month" in rows["Bills to bring"]
    assert "heating, hot water and cooking are on gas" in rows["Bills to bring"]
    electric = dict(home_summary(HomeDescription()))
    assert "no gas bill is needed" in electric["Bills to bring"]
    # nothing an engineer would write
    text = " ".join(t for _, t in home_summary(HomeDescription()))
    for jargon in ("W/K", "W per °C", "kW", "COP", "conductance", "starting point"):
        assert jargon not in text
    sentences = assumptions(HomeDescription())
    assert sentences[0].startswith("Your home: A flat of about 75 m² in Madrid")
    assert sentences[-1].startswith("These are typical figures for a home like yours.")


def test_radiation_to_the_sky_is_iso_13790_and_a_house_loses_more(backend):
    """ISO 13790 §11.4.6: Φ_r = R_se · UA · h_r · Δθ_er · F_r, with R_se 0.04,
    h_r = 4εσT³ (ε 0.9, 10 °C), Δθ_er 11 K. A flat's facades see half the sky;
    a house's roof sees all of it, and a house has more envelope."""
    from components.exchanges import H_R, R_SE, SKY_DIFFERENCE_K

    assert pytest.approx(4 * 0.9 * 5.670374e-8 * 283.15**3) == H_R
    flat = HomeDescription(home_type="flat")
    house = HomeDescription(home_type="detached")
    assert flat.sky_view == 0.5
    assert house.sky_view == pytest.approx(0.55 * 0.5 + 0.30 * 1.0)
    assert flat.sky_depression == pytest.approx(R_SE * H_R * SKY_DIFFERENCE_K * 0.5)
    assert flat.radiation_w == pytest.approx(flat.envelope_ua * flat.sky_depression)
    assert house.radiation_w > 2 * flat.radiation_w
    twin = build_twin(flat, backend=backend)
    assert twin.model.parameters["zone.sky.depression"] == pytest.approx(
        flat.sky_depression
    )
    rows = dict(home_summary(flat))
    assert rows["Heat lost to the sky"].startswith(
        "About 150 W, through the facades only"
    )
    assert "a house loses much more" in dict(home_summary(house))["Heat lost to the sky"]


def test_the_thermostat_has_a_thermometer(backend):
    twin = build_twin(HomeDescription(heating="gas"), backend=backend)
    assert twin.thermometer == "heating.thermostat.temperature"
    for out in ("temperature", "on", "duty"):
        assert f"heating.thermostat.{out}" in twin.model.output_names
    none = build_twin(HomeDescription(heating="none", water="unknown"), backend=backend)
    assert none.thermometer == "zone.temperature"
