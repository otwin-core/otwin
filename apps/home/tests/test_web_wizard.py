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
        "from the grid, 744 readings from 1 Jan 2026 to 31 Jan 2026, 980 kWh."
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
    """The page's three steps, as calls: the sample answers, the two files
    (the station through the mapper), one click. The sample home loses 187.5
    W/K and has a 5.2 kW heat pump; the survey guessed 150 and 4.5."""
    samples = webmain.load_samples()
    assert samples["answers"] == ANSWERS
    station = next(f for f in samples["files"] if f["status"] == "needs_mapping")
    webmain.map_file(station["id"], station["mapping"]["guess"])
    assert webmain.data_status(ANSWERS)["ready"]
    report = webmain.dispatch("calibrate_home", {"answers": ANSWERS})
    assert report["ok"] and report["verdict"] in ("good", "usable")
    found = {f["label"]: f for f in report["findings"]}
    assert set(found) == {
        "How fast your home loses heat",
        "How long your home keeps its warmth",
        "Size of your heat pump",
        "Always-on electricity",
    }
    assert "18" in found["How fast your home loses heat"]["sentence"]  # 18x W per °C
    assert "5.1 kW" in found["Size of your heat pump"]["sentence"] or (
        "5.2 kW" in found["Size of your heat pump"]["sentence"]
    )
    assert len(report["daily"]) == 31 and report["period"] == "01/01/2026 to 31/01/2026"
    measured = np.array([d["measured"] for d in report["daily"]])
    twin = np.array([d["twin"] for d in report["daily"]])
    assert measured.sum() == pytest.approx(980, abs=1)
    assert np.abs(twin - measured).max() < 0.15 * measured.mean()
    assert report["notes"] == []


def test_air_conditioning_is_left_out_of_a_winter_fit():
    webmain.load_samples()
    station = next(e for k, e in webmain.SESSION.items() if e.status == "needs_mapping")
    webmain.map_file(
        next(k for k, e in webmain.SESSION.items() if e is station),
        station.mapping["guess"],
    )
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
    assert set(fresh) == {
        p.name for p in SAMPLES.iterdir() if p.suffix in (".csv", ".json")
    }
    assert fresh["home.json"] == (SAMPLES / "home.json").read_bytes()
    a = ingest.load(fresh["consumo_horario_enero_2026.csv"])[0]
    b = ingest.load((SAMPLES / "consumo_horario_enero_2026.csv").read_bytes())[0]
    np.testing.assert_array_equal(a.start, b.start)
    np.testing.assert_allclose(a.values_in("kWh"), b.values_in("kWh"), atol=0.0011)
