"""The wizard's session, end to end, natively: the logic the page drives.

The browser run (``web/verify_wizard.py``) proves the page; these tests pin
what the page shows, without a browser: the sample month is read, the
weather station's CSV goes through the column mapper, the data is judged
ready, and calibration finds the sample home. Every format of the ingest
fixtures is read or explained. Calibration runs on the fastest backend
installed (the browser itself always uses NumPy).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from otwin.runtime import engine_available

WEB = Path(__file__).resolve().parents[1] / "web"
for extra in (WEB / "py", WEB / "samples"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import make_samples  # noqa: E402
import webmain  # noqa: E402

import ingest  # noqa: E402

SAMPLES = WEB / "samples"
FIXTURES = WEB.parent / "tests" / "fixtures" / "data"
ANSWERS = json.loads((SAMPLES / "home.json").read_text())


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    webmain.SESSION.clear()
    monkeypatch.setattr(webmain, "BACKEND", "rust" if engine_available() else "numpy")
    yield
    webmain.SESSION.clear()


def read(name: str, file_id: str | None = None) -> dict:
    return webmain.dispatch(
        "read_file",
        {"file_id": file_id or name, "name": name},
        (SAMPLES / name).read_bytes(),
    )


def test_the_electricity_file_is_recognised_in_plain_words():
    out = read("consumo_horario_enero_2026.csv")
    assert out["status"] == "ok"
    assert out["message"] == (
        "Read as hourly electricity from Datadis or your distributor: hourly electricity "
        "from the grid, 744 readings from 1 Jan 2026 to 31 Jan 2026, 982 kWh."
    )


def test_an_unknown_csv_gets_the_column_mapper_with_good_guesses():
    out = read("estacion_meteo_enero_2026.csv")
    assert out["status"] == "needs_mapping"
    m = out["mapping"]
    assert m["headers"] == [
        "Fecha y hora",
        "Temperatura exterior (ºC)",
        "Humedad relativa (%)",
    ]
    assert m["guess"] == {
        "time": "Fecha y hora",
        "value": "Temperatura exterior (ºC)",
        "quantity": "outdoor_temperature",
        "unit": "°C",
        "cumulative": False,
        "label": "start",
    }
    assert len(m["preview"]) == 5 and m["preview"][0][1] == "5,8"
    done = webmain.map_file(out["id"], m["guess"])
    assert (
        done["status"] == "ok" and "outdoor temperature, 744 readings" in done["message"]
    )


def test_wrong_mapping_choices_are_explained_not_crashed():
    out = read("estacion_meteo_enero_2026.csv")
    bad = dict(out["mapping"]["guess"], value="Fecha y hora")
    again = webmain.map_file(out["id"], bad)
    assert again["status"] == "needs_mapping"
    assert again["error"].startswith("Those columns did not work:")
    assert "mapping" in again  # the mapper stays on screen


def test_data_status_guides_the_householder():
    st = webmain.data_status(ANSWERS)
    assert not st["ready"] and "Datadis" in st["messages"][0]
    read("consumo_horario_enero_2026.csv")
    st = webmain.data_status(ANSWERS)
    assert not st["ready"]
    req = st["weather_request"]
    assert req["province"] == "Madrid" and req["first"] == "2026-01-01"
    assert req["url"].startswith(
        "https://archive-api.open-meteo.com/v1/archive?latitude=40.42"
    )
    assert "timeformat=unixtime" in req["url"]
    read("open_meteo_enero_2026.json")
    st = webmain.data_status(ANSWERS)
    assert st["ready"] and st["days"] == 31.0
    assert st["messages"][0] == (
        "Ready: 31 days of hourly electricity and outdoor temperature, "
        "01/01/2026 to 31/01/2026."
    )


def test_too_little_data_is_refused_with_the_reason():
    webmain.read_file("e", "cnmc.csv", (FIXTURES / "cnmc_consumo.csv").read_bytes())
    webmain.read_file(
        "w", "meteo.json", (SAMPLES / "open_meteo_enero_2026.json").read_bytes()
    )
    st = webmain.data_status(ANSWERS)
    assert not st["ready"]
    assert "do not cover the same days" in " ".join(st["messages"])
    out = webmain.calibrate_home(ANSWERS)
    assert out["ok"] is False


def test_the_wizard_calibrates_the_sample_home():
    """The page's three steps, as calls: the sample answers, the files (the
    station's log through the mapper's own confident guess, as the page
    would), one click. The sample home loses 187.5 W/K and has a 5.2 kW heat
    pump; the survey guessed 150 and 4.5."""
    samples = webmain.load_samples()
    assert samples["answers"] == ANSWERS
    assert [f["status"] for f in samples["files"]] == ["ok", "ok", "ok"]
    station = next(f for f in samples["files"] if "estacion" in f["name"])
    assert station["format"] == "your own columns"  # read with the mapper's guess
    assert webmain.data_status(ANSWERS)["ready"]
    report = webmain.dispatch("calibrate_home", {"answers": ANSWERS})
    assert report["ok"] and report["verdict"] in ("good", "usable")
    found = {f["label"]: f for f in report["findings"]}
    assert set(found) == {
        "How fast your home loses heat",
        "How long your home keeps its warmth",
        "Size of your heat pump",
        "Always-on electricity",
        "Your thermometer",
    }
    assert "18" in found["How fast your home loses heat"]["sentence"]  # 18x W per °C
    # the heat pump's power came from its nameplate: kept as given, not fitted
    pump = found["Size of your heat pump"]
    assert pump["sentence"] == "Size of your heat pump: 5.0 kW, as you told us"
    assert pump["verdict"] == "good"
    assert len(report["daily"]) == 31 and report["period"] == "01/01/2026 to 31/01/2026"
    measured = np.array([d["measured"] for d in report["daily"]])
    twin = np.array([d["twin"] for d in report["daily"]])
    assert measured.sum() == pytest.approx(982, abs=1)
    assert np.abs(twin - measured).max() < 0.15 * measured.mean()
    assert report["notes"] == []
    assert report["gas"] is None and report["water"] is None  # all electric, no bills


def test_air_conditioning_is_left_out_of_a_winter_fit():
    webmain.load_samples()  # the station's log is read with the mapper's guess
    report = webmain.calibrate_home({**ANSWERS, "cooling": "yes"})
    assert report["ok"]
    assert any("air conditioning was left out" in n for n in report["notes"])
    assert all("air conditioner" not in f["label"] for f in report["findings"])


def test_every_ingest_fixture_is_read_or_explained():
    statuses = {}
    for f in sorted(FIXTURES.iterdir()):
        out = webmain.read_file(f.name, f.name, f.read_bytes())
        statuses[f.name] = out["status"]
        assert out["message"], f.name
    assert statuses.pop("generic_water_logger.csv") == "needs_mapping"
    assert statuses.pop("ha_history.csv") == "error"  # no units: explained, not guessed
    assert set(statuses.values()) == {"ok"}


def test_quarter_hours_become_hours():
    t0 = 1767222000  # 2026-01-01 00:00 Madrid
    starts = t0 + 900 * np.arange(8)
    s = ingest.Series(
        "electricity_import",
        "x",
        "interval",
        starts,
        starts + 900,
        np.full(8, 0.25 * 3.6e6),
    )
    h = webmain._hourly(s)
    assert h.start.tolist() == [t0, t0 + 3600] and np.allclose(
        h.values_in("kWh"), [1.0, 1.0]
    )


def test_dispatch_is_an_allowlist():
    with pytest.raises(KeyError, match="no such function"):
        webmain.dispatch("__import__", {})
    assert webmain.dispatch("ping", {})["status"] == "ok"


def test_the_samples_regenerate():
    """Same generator, same files: values may differ only in the last printed
    digit across platforms (libm), never in shape or substance."""
    fresh = make_samples.generate()
    on_disk = {
        str(p.relative_to(SAMPLES))
        for p in SAMPLES.rglob("*")
        if p.suffix in (".csv", ".json")
    }
    assert set(fresh) == on_disk
    for name in ("home.json", "gas_home/home.json"):
        assert fresh[name] == (SAMPLES / name).read_bytes()
    for name in [n for n in fresh if "consumo_horario" in n]:
        a = ingest.load(fresh[name])[0]
        b = ingest.load((SAMPLES / name).read_bytes())[0]
        np.testing.assert_array_equal(a.start, b.start)
        np.testing.assert_allclose(a.values_in("kWh"), b.values_in("kWh"), atol=0.0011)
    for name in [n for n in fresh if "factura" in n]:  # whole m³: exact
        assert fresh[name] == (SAMPLES / name).read_bytes(), name


# ---------------------------------------------------------------- gas and water

GAS_HOME = SAMPLES / "gas_home"
GAS_ANSWERS = json.loads((GAS_HOME / "home.json").read_text())
#: (sample id, folder, days, gas bill m³, kWh)
GAS_PERIODS = [
    ("gas_dec_jan", "15dic-15ene", 31, 245, 2714),
    ("gas_feb_mar", "15feb-15mar", 28, 150, 1656),
    ("gas_oct_nov", "15oct-15nov", 31, 117, 1302),
]


def test_every_sample_set_and_demo_home_has_its_files():
    assert list(webmain.DEMO_HOMES) == ["gas_winter", "electric"]
    for key, (label, home, names) in webmain.SAMPLE_SETS.items():
        assert (SAMPLES / home).is_file() and label
        assert all((SAMPLES / n).is_file() for n in names), key


@pytest.mark.parametrize("sample, folder, days, m3, kwh", GAS_PERIODS)
def test_the_gas_samples_cover_three_winter_periods(sample, folder, days, m3, kwh):
    """Each period's bills are as printed: whole m³, kWh = m³ × Fc × PCS, and
    the electricity and weather cover the bill's dates exactly."""
    out = webmain.load_samples(sample)
    assert out["answers"] == GAS_ANSWERS
    assert all(f["status"] == "ok" for f in out["files"]), out["files"]
    gas = ingest.load((GAS_HOME / folder / f"factura_gas_{folder}.csv").read_bytes())
    vol = next(s for s in gas if s.quantity == "gas_volume")
    energy = next(s for s in gas if s.quantity == "gas_energy")
    assert vol.values_in("m3").tolist() == [m3]
    assert energy.values_in("kWh").tolist() == [kwh]
    elec = ingest.load(
        (GAS_HOME / folder / f"consumo_horario_{folder}.csv").read_bytes()
    )[0]
    assert int(elec.start[0]) == int(vol.start[0]) and int(elec.end[-1]) == int(
        vol.end[0]
    )
    assert (elec.end[-1] - elec.start[0]) / 86400 == days + (
        1 / 24 if folder == "15oct-15nov" else 0
    )
    st = webmain.data_status(GAS_ANSWERS)
    assert st["ready"], st["messages"]
    assert any("Your gas bill will be used too" in m for m in st["messages"])
    assert any("water bill will be compared" in m for m in st["messages"])


def test_the_gas_bill_measures_how_fast_the_home_loses_heat():
    """The gas home loses 218.4 W per °C; the survey guesses 273. Without the
    thermometer, its gas bill, fitted with the hourly electricity, finds it;
    a boiler's size and the home's heat storage cannot show in a bill and are
    said not to."""
    webmain.load_samples("gas_dec_jan")
    webmain.remove_file(
        next(k for k, e in webmain.SESSION.items() if "termometro" in e.name)
    )
    report = webmain.calibrate_home(GAS_ANSWERS)
    assert report["ok"] and report["verdict"] == "usable", report["headline"]
    found = {f["label"]: f for f in report["findings"]}
    loss = found["How fast your home loses heat"]
    assert loss["verdict"] in ("good", "usable")
    assert loss["value"] == pytest.approx(218.4, rel=0.05)
    # the boiler's power came from its nameplate: given, not something bills measure
    assert found["Size of your boiler"]["verdict"] == "good"
    assert found["Size of your boiler"]["value"] == 24.0
    assert "your gas bill (within" in report["headline"]
    assert "Bills cannot show" in report["headline"]

    gas = report["gas"]
    assert gas["used_in_fit"]
    (bill,) = gas["bills"]
    assert bill["period"] == "15 Dec 2025 to 15 Jan 2026"
    assert (bill["bill_m3"], bill["bill_kwh"]) == (245, 2714)
    assert bill["kwh_per_m3"] == pytest.approx(
        2714 / 245, abs=1e-3
    )  # the bill's Fc × PCS
    assert abs(bill["off"]) < 0.02
    assert bill["twin_m3"] == pytest.approx(bill["twin_kwh"] / (2958 / 267), abs=0.1)
    assert set(gas["by_use_kwh"]) == {"heating", "hot water", "cooking"}
    assert gas["sentences"][0] == (
        "Your gas bill, 15 Dec 2025 to 15 Jan 2026: 245 m³, charged as 2,714 kWh "
        "(11.08 kWh per m³, the conversion printed on your bill)."
    )
    assert "fitted to this bill" in gas["sentences"][1]

    water = report["water"]
    assert water["m3"] == 11 and water["days"] == 31
    assert water["litres_per_person_day"] == pytest.approx(11000 / 31 / 3, abs=1)
    assert "about what a typical Spanish home uses" in water["sentences"][1]


def test_the_thermometer_shows_what_bills_cannot():
    """With the interior thermometer, the same month measures how long the
    home keeps its warmth (21.1 h: 1.2 × 1.68e7 J/K over 218.4 + 47.25 W/K)
    and the boiler's size (24 kW), from the night cool-down and the morning
    warm-up; the thermometer's own offset is found and allowed for."""
    webmain.load_samples("gas_dec_jan")
    st = webmain.data_status(GAS_ANSWERS)
    assert any("interior thermometer will be used" in m for m in st["messages"])
    report = webmain.calibrate_home(GAS_ANSWERS)
    assert report["ok"] and report["verdict"] in ("good", "usable"), report["headline"]
    assert "your indoor temperature (a typical hour within" in report["headline"]
    found = {f["label"]: f for f in report["findings"]}
    tau = 1.2 * 1.68e7 / (218.4 + 0.45 * 105) / 3600
    keeps = found["How long your home keeps its warmth"]
    assert keeps["verdict"] == "good" and keeps["value"] == pytest.approx(tau, rel=0.05)
    boiler = found["Size of your boiler"]
    assert boiler["verdict"] == "good" and boiler["value"] == 24.0  # given
    assert abs(found["Your thermometer"]["value"]) < 0.5
    assert report["indoor_error"] < 0.3
    week = report["periods"][0]["indoor"]
    assert len(week) == 7 * 24 and week[0]["time"] == "2025-12-15 00:00"
    night = [p["measured"] for p in week[4:7]]  # 04:00-06:00, deep in the setback
    day = [p["measured"] for p in week[12:20]]
    assert max(night) < min(day) - 2  # the night setback shows
    heating = " ".join(report["heating"])
    assert "radiates about" in heating and "through its facades" in heating
    assert "Your thermostat called for heat about" in heating
    assert 0 < report["periods"][0]["heating_running"] < 1


def test_an_example_home_follows_the_thermostat_chosen():
    """The example's records are made again from the answers: no night
    setback and 19 °C burns less gas, and the thermometer stays flat, so the
    home's heat storage no longer shows, and the report says why."""
    webmain.load_samples("gas_dec_jan")
    own = webmain.prepare_example(GAS_ANSWERS)
    assert own["example"] and not own["changed"]  # the files are already these
    answers = {**GAS_ANSWERS, "thermostat": "19", "night": "same"}
    st = webmain.data_status(answers)
    assert any(m.startswith("Example home: when you calibrate") for m in st["messages"])
    out = webmain.prepare_example(answers)
    assert out["changed"] and "19 °C by day, 19 °C at night too" in out["message"]
    assert {f["name"] for f in out["files"]} == {
        "consumo_horario_15dic-15ene.csv",
        "factura_gas_15dic-15ene.csv",
        "termometro_interior_15dic-15ene.csv",
    }
    bill = next(f for f in out["files"] if f["name"].startswith("factura_gas"))
    kwh = int(bill["message"].split("charged as ")[1].split(" kWh")[0].replace(",", ""))
    assert kwh < 2958 * 0.97  # cooler and no setback... less gas than 21/16
    thermo = webmain._best_indoor().values_in("degC")
    assert np.percentile(thermo, 95) - np.percentile(thermo, 5) < 1.5  # flat
    report = webmain.calibrate_home(answers)
    found = {f["label"]: f for f in report["findings"]}
    keeps = found["How long your home keeps its warmth"]
    assert keeps["verdict"] == "not enough data"
    assert "night would show it" in keeps["reason"]
    assert report["example"] is None  # already made by prepare_example


def test_the_example_files_are_the_example_for_its_own_answers():
    """Simulating the example again for its own answers writes exactly the
    files on disk: one code, survey.example, makes both."""
    webmain.load_samples("gas_feb_mar")
    before = {k: e.data for k, e in webmain.SESSION.items()}
    webmain.EXAMPLE["made_for"] = None  # force it
    webmain.prepare_example(GAS_ANSWERS)
    after = {k: e.data for k, e in webmain.SESSION.items()}
    assert before == after


def test_gas_only_for_hot_water_is_compared_not_fitted():
    """A heat pump heats the home and a gas calentador the water: the gas bill
    cannot measure the walls, so it is set against the twin, not fitted."""
    webmain.load_samples("gas_feb_mar")
    answers = {
        **GAS_ANSWERS,
        "heating": "heat_pump",
        "water": "gas",
        "cooking": "electric",
    }
    st = webmain.data_status(answers)
    assert st["ready"]
    assert any("compared with the twin's typical hot water" in m for m in st["messages"])
    report = webmain.calibrate_home(answers)
    assert report["ok"]
    gas = report["gas"]
    assert not gas["used_in_fit"]
    assert set(gas["by_use_kwh"]) == {"hot water"}
    assert any("not used to fit the twin" in t for t in gas["sentences"])


def test_a_gas_home_without_its_bill_is_told_what_to_add():
    read("gas_home/15dic-15ene/consumo_horario_15dic-15ene.csv", "e")
    read("gas_home/15dic-15ene/open_meteo_15dic-15ene.json", "w")
    st = webmain.data_status(GAS_ANSWERS)
    assert st["ready"]
    assert any(
        m.startswith("Add your gas bill for the same dates.") for m in st["messages"]
    )
    assert any("not about your walls" in m for m in st["messages"])


def test_a_bill_outside_the_electricity_is_explained():
    read("gas_home/15dic-15ene/consumo_horario_15dic-15ene.csv", "e")
    read("gas_home/15dic-15ene/open_meteo_15dic-15ene.json", "w")
    read("gas_home/15feb-15mar/factura_gas_15feb-15mar.csv", "g")
    st = webmain.data_status(GAS_ANSWERS)
    assert any(
        "Your gas bill (15 Feb 2026 to 15 Mar 2026) is outside the dates" in m
        for m in st["messages"]
    )


def test_bills_typed_in_are_checked_like_files():
    ok = webmain.dispatch(
        "add_bill",
        {
            "file_id": "t1",
            "kind": "gas",
            "bill": {
                "start": "2025-12-15",
                "end": "2026-01-15",
                "m3": "252",
                "fc": "0,95",
                "pcs": "11,66",
                "kwh": "2791",
                "eur": "210,15",
            },
        },
    )
    assert ok["status"] == "ok"
    assert ok["name"] == "Gas bill, 15/12/2025 to 15/01/2026 (typed in)"
    assert ok["message"] == (
        "Read 1 gas bill: 15 Dec 2025 to 15 Jan 2026, 252 m³ charged as 2,791 kWh."
    )
    # no kWh typed: computed from the bill's own Fc and PCS
    computed = webmain.add_bill(
        "t2",
        "gas",
        {
            "start": "2025-12-15",
            "end": "2026-01-15",
            "m3": "252",
            "fc": "0.95",
            "pcs": "11.66",
        },
    )
    assert "charged as 2,791 kWh" in computed["message"]
    wrong = webmain.add_bill(
        "t3",
        "gas",
        {
            "start": "2025-12-15",
            "end": "2026-01-15",
            "m3": "252",
            "fc": "0.95",
            "pcs": "11.66",
            "kwh": "3000",
        },
    )
    assert wrong["status"] == "error"
    assert wrong["message"] == (
        "This bill could not be read. Check the kWh: 3000 kWh but m³ × Fc × PCS = "
        "252 × 0.95 × 11.66 = 2791.4 kWh"
    )
    mj = webmain.add_bill(
        "t4",
        "gas",
        {
            "start": "2025-12-15",
            "end": "2026-01-15",
            "m3": "252",
            "fc": "0.95",
            "pcs": "42",
        },
    )
    assert "Check the calorific value (PCS)" in mj["message"] and "MJ/m³" in mj["message"]
    water = webmain.add_bill(
        "t5", "water", {"start": "2025-12-15", "end": "2026-01-15", "m3": "11"}
    )
    assert water["message"] == "Read 1 water bill: 15 Dec 2025 to 15 Jan 2026, 11 m³."
    with pytest.raises(ValueError, match="kind must be"):
        webmain.add_bill("t6", "petrol", {})
    # an electricity bill is a kind of its own: the kWh billed and the amount
    e = webmain.add_bill(
        "t7",
        "electricity",
        {"start": "2026-01-01", "end": "2026-02-01", "kwh": "1051", "eur": "178,40"},
    )
    assert e["status"] == "ok" and "1,051 kWh" in e["message"]


def test_the_home_summary_reaches_the_page():
    out = webmain.dispatch("assumptions", {"answers": GAS_ANSWERS})
    rows = {r["topic"]: r["text"] for r in out["summary"]}
    assert rows["Hot water"] == "From the gas boiler that heats the home."
    assert rows["Cooking"] == "On a gas hob, with piped gas."
    assert out["uses_gas"] is True


# ---------------------------------------------------------------- several periods


def test_three_winter_periods_are_found_in_the_files():
    out = webmain.load_samples("gas_winter")
    assert len(out["files"]) == 15 and all(f["status"] == "ok" for f in out["files"])
    st = webmain.data_status(GAS_ANSWERS)
    assert st["ready"] and st["days"] == 90.0
    assert [(p["label"], p["days"], p["gas_bill"]) for p in st["periods"]] == [
        ("15 Oct 2025 to 15 Nov 2025", 31.0, True),
        ("15 Dec 2025 to 15 Jan 2026", 31.0, True),
        ("15 Feb 2026 to 15 Mar 2026", 28.0, True),
    ]
    oct_, dec, feb = (p["mean_c"] for p in st["periods"])
    assert dec < feb < oct_  # quite different winters
    assert st["messages"][0].startswith("Ready: 3 periods of hourly electricity")
    assert "We calibrate on all of them together" in st["messages"][1]
    assert not any("cover more than" in m for m in st["messages"])


def test_all_periods_together_and_each_alone():
    """The same files, calibrated on all three periods and on each: every run
    finds the home (218.4 W per °C); together, one twin reproduces all three
    bills and the answer is the narrowest."""
    webmain.load_samples("gas_winter")
    together = webmain.calibrate_home(GAS_ANSWERS, period="all")
    assert together["ok"] and together["chosen"] == "all"
    assert [p["label"] for p in together["periods"]] == [
        "15 Oct 2025 to 15 Nov 2025",
        "15 Dec 2025 to 15 Jan 2026",
        "15 Feb 2026 to 15 Mar 2026",
    ]
    assert len(together["daily"]) == 90
    gas = together["gas"]
    assert [b["bill_kwh"] for b in gas["bills"]] == [1302, 2714, 1656]
    for p, b in zip(together["periods"], gas["bills"], strict=True):
        assert p["gas_bill_kwh"] == b["bill_kwh"]
        assert abs(p["twin_gas_kwh"] / p["gas_bill_kwh"] - 1) < 0.03
    assert any(
        "fitted to all 3 bills at once, reproduces each" in t for t in gas["sentences"]
    )
    assert "3 bills" not in together["water"]["sentences"][0]
    assert together["water"]["sentences"][0].startswith("Your water bills (15 Oct 2025")

    loss = lambda r: next(f for f in r["findings"] if f["label"].startswith("How fast"))  # noqa: E731
    assert loss(together)["value"] == pytest.approx(218.4, rel=0.05)
    for k in range(3):
        alone = webmain.calibrate_home(GAS_ANSWERS, period=k)
        assert alone["ok"] and len(alone["periods"]) == 1
        assert alone["periods"][0]["label"] == together["periods"][k]["label"]
        assert loss(alone)["value"] == pytest.approx(218.4, rel=0.05)
        # narrower together (with the thermometer each period alone is
        # already tight, about ±6 %, so the gain is smaller than with bills alone)
        assert loss(together)["uncertainty"] < loss(alone)["uncertainty"]
    with pytest.raises(ValueError, match="there is no period 3"):
        webmain._record(webmain.HomeDescription.from_answers(GAS_ANSWERS), 3)


def test_one_downloaded_month_is_still_one_period():
    webmain.load_samples("gas_dec_jan")
    st = webmain.data_status(GAS_ANSWERS)
    assert len(st["periods"]) == 1
    assert "We calibrate on all of them together" not in " ".join(st["messages"])
