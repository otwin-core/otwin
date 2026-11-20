"""The "My home" page's engine calls, natively.

What the page shows on its one screen comes from these calls: the first
estimate from the answers alone, the five data cards and the next best
step, the analysis (letter, money, confidence, what-ifs) and the
hidden-month test, each in English or Spanish.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from otwin.runtime import engine_available

WEB = Path(__file__).resolve().parents[1] / "web"
for extra in (WEB / "py", WEB / "samples"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import webmain  # noqa: E402

SAMPLES = WEB / "samples"
GAS = json.loads((SAMPLES / "gas_home" / "home.json").read_text())


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    webmain.forget()
    webmain.set_language("en")
    monkeypatch.setattr(webmain, "BACKEND", "rust" if engine_available() else "numpy")
    yield
    webmain.forget()
    webmain.set_language("en")


def read(path: str):
    p = SAMPLES / path
    return webmain.read_file(p.name, p.name, p.read_bytes())


def test_a_first_estimate_from_the_answers_alone():
    out = webmain.home(GAS)
    assert out["ok"] and out["header"] == "Madrid · flat · 105 m² · gas boiler"
    assert out["typical_letter"] == "F"  # 2.6 + 0.45 W/K per m², before 1980
    e = out["estimate"]
    assert e["province"] == "Madrid" and e["january_c"] == 6.3
    assert 150 < e["eur"] < 600 and 0.5 < e["heating_share"] < 0.95
    assert {r["use"] for r in e["by_use"]} >= {"heating", "hot water", "cooking"}
    # the house drawn: what comes in, the heat made, what gets out
    f = e["flows"]
    assert f["heater"] == "gas" and f["gas_kwh"] > f["electricity_kwh"] > 0
    assert f["water_typical"] and f["water_m3"] == pytest.approx(
        130 * 3 * 31 / 1000, abs=0.1
    )
    assert f["loss_kwh"] == pytest.approx(f["loss_fabric_kwh"] + f["loss_air_kwh"], abs=1)
    assert f["loss_fabric_kwh"] > f["loss_air_kwh"] > 0
    # the heat made is what the loss needs, less the free gains
    assert 0.8 * f["loss_kwh"] < f["heat_kwh"] < f["loss_kwh"]
    assert 10 < f["delta_c"] < 16 and f["hours"] == 744
    webmain.set_language("es")
    es = webmain.home(GAS)
    assert es["header"] == "Madrid · piso · 105 m² · caldera de gas"
    assert es["summary"][0]["topic"] == "Tu casa"


def test_the_cards_say_what_is_there_and_what_to_do_next():
    first = webmain.cards(GAS)
    status = {c["kind"]: c["status"] for c in first["cards"]}
    assert status == {
        "electricity": "empty",
        "gas": "empty",
        "water": "empty",
        "thermometer": "empty",
        "weather": "waiting",
    }
    assert first["next"] == "add_electricity" and not first["ready"]
    read("gas_home/15dic-15ene/consumo_horario_15dic-15ene.csv")
    c = webmain.cards(GAS)
    weather = next(x for x in c["cards"] if x["kind"] == "weather")
    assert weather["status"] == "needs_ok" and "open-meteo" in weather["request"]["url"]
    assert c["next"] == "allow_weather"
    read("gas_home/15dic-15ene/open_meteo_15dic-15ene.json")
    c = webmain.cards(GAS)
    assert c["ready"] and c["next"] == "add_gas_heating"
    read("gas_home/15dic-15ene/factura_gas_15dic-15ene.csv")
    assert webmain.cards(GAS)["next"] == "add_thermometer"
    elec = next(x for x in webmain.cards(GAS)["cards"] if x["kind"] == "electricity")
    assert elec["lines"] == ["15 Dec 2025 – 14 Jan 2026 · 239 kWh"]
    # an all-electric home needs no gas
    webmain.forget()
    electric = json.loads((SAMPLES / "home.json").read_text())
    gas_card = next(x for x in webmain.cards(electric)["cards"] if x["kind"] == "gas")
    assert gas_card["status"] == "not_needed"


def test_the_analysis_is_the_dashboard_and_speaks_both_languages():
    webmain.load_samples("gas_dec_jan")
    r = webmain.analyse(GAS)
    assert r["ok"]
    assert r["letter"] == "E" and r["typical_letter"] == "F"  # better than its age
    assert r["confidence"] in ("reliable", "approximate")
    assert r["money"]["eur_per_month"] > 100 and r["money"]["from_bills"]
    uses = {u["use"] for u in r["money"]["by_use"]}
    assert {"heating", "hot water", "cooking", "always_on"} <= uses
    assert (
        r["boiler"] == "given" and r["boiler_kw"] == 24.0
    )  # from the nameplate, not fitted
    assert r["keeps_warm_hours"] == pytest.approx(21.1, rel=0.1)
    f = r["flows"]  # a month, from the data: the water bill, not a typical one
    assert f["hours"] == 730 and not f["water_typical"] and 5 < f["water_m3"] < 20
    assert f["gas_kwh"] > 1000 and f["heat_kwh"] < f["loss_kwh"]
    assert sum(u["kwh"] for u in f["by_use"]) == pytest.approx(
        f["gas_kwh"] + f["electricity_kwh"], abs=2
    )
    keys = [w["key"] for w in r["whatif"]]
    assert keys == ["thermostat_down", "thermostat_up", "insulate", "colder"]
    down = r["whatif"][0]
    assert down["eur_month_change"] < 0 and down["effect"].startswith("saves about")
    assert r["whatif"][1]["eur_month_change"] > 0
    assert r["confidence_text"].startswith(("Reliable:", "Approximate:"))
    # the same analysis in Spanish, without fitting again
    webmain.set_language("es")
    es = webmain.report()
    assert es["letter"] == r["letter"] and es["money"] == {
        **r["money"],
        "by_use": es["money"]["by_use"],
    }
    assert es["confidence_text"].startswith(("Fiable:", "Aproximado:"))
    assert es["whatif"][0]["title"] == "Termostato 1 °C más bajo"
    assert es["whatif"][0]["effect"].startswith("ahorra unos")
    labels = {f["label"] for f in es["findings"]}
    assert "Cuánto tiempo guarda el calor" in labels
    assert es["gas"]["sentences"][0].startswith(
        "Tu factura de gas, 15 dic 2025 a 15 ene 2026"
    )


def test_the_hidden_month_test():
    webmain.load_samples("gas_winter")
    webmain.analyse(GAS)
    t = webmain.trust_test(GAS)
    assert t["status"] == "done" and t["passed"]
    guess, real = t["gas"]
    assert abs(guess / real - 1) < 0.05
    assert t["sentences"][0].startswith(
        "We hid 15 Feb 2026 to 15 Mar 2026 from the model"
    )
    assert t["sentences"][-1] == "Passed: the model predicts a month it never saw."
    assert webmain.report()["trust"]["passed"]
    # one period: nothing to hide
    webmain.load_samples("gas_dec_jan")
    assert webmain.trust_test(GAS)["status"] == "needs_two"


def test_the_language_changes_every_sentence_of_the_files():
    read("gas_home/15dic-15ene/factura_gas_15dic-15ene.csv")
    webmain.set_language("es")
    (f,) = webmain.files()["files"]
    assert f["message"] == (
        "Leída 1 factura de gas: del 15 dic 2025 al 15 ene 2026, 245 m³ facturados como 2714 kWh."
    )
    with pytest.raises(ValueError, match="lang must be"):
        webmain.set_language("fr")
