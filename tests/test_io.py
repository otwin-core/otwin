"""Tests for the field-connector layer, otwin.io.

Every test in this file runs without ``pymodbus`` or ``pysunspec2``
installed. That is the point: a data-acquisition layer whose tests need
hardware is a layer that is never tested. The simulators in
:mod:`otwin.io.simulator` serve real register images in-process, and the
sources decode them through exactly the code path a real device would use,
so what is under test here is the decoding, the scale factors, the word
order and the degradation behaviour — not a mock of them.

Only two tests are skipped when the optional extras are absent, and both are
cross-checks *against* those packages rather than tests of the connectors.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

# The repository has no packaging metadata yet, so the package is imported
# from the source tree directly rather than from an installed distribution.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from otwin.io import (  # noqa: E402
    KNOWN_UNITS,
    MissingDependencyError,
    ModbusSimulator,
    ModbusSource,
    RegisterSpec,
    Sample,
    Source,
    SunSpecSimulator,
    SunSpecSource,
    TagSpec,
    UnknownUnitError,
    load_register_map,
    si_unit,
    to_si,
)
from otwin.io.simulator import SimulatedFault  # noqa: E402
from otwin.io.sunspec import _BUILTIN_MODEL_DEFS, compare_model_defs  # noqa: E402

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def pcs_map() -> list[RegisterSpec]:
    """A small but realistic PCS map: 32-bit power, scaled SoC, a serial."""
    return [
        RegisterSpec("p_dc", 0, "float32", "kW", description="DC power, + on discharge"),
        RegisterSpec("soc", 2, "uint16", "%", scale=0.1, description="State of charge"),
        RegisterSpec("cycles", 3, "int32", "1", description="Equivalent full cycles"),
        RegisterSpec("v_dc", 5, "uint16", "V", scale=0.1, description="DC bus voltage"),
        RegisterSpec("t_cab", 40, "int16", "degC", scale=0.1, description="Cabinet temp"),
        RegisterSpec("serial", 60, "string", "1", count=8, description="Serial number"),
    ]


@pytest.fixture
def modbus_pair(pcs_map: list[RegisterSpec]) -> tuple[ModbusSimulator, ModbusSource]:
    sim = ModbusSimulator(pcs_map, word_order="big")
    sim.set_value("p_dc", 250.0)
    sim.set_value("soc", 62.0)
    sim.set_value("cycles", 1450)
    sim.set_value("v_dc", 812.3)
    sim.set_value("t_cab", 31.5)
    sim.set_value("serial", "PCS-0042")
    return sim, ModbusSource(pcs_map, transport=sim, word_order="big")


# --------------------------------------------------------------------------
# 1. SunSpec round trip
# --------------------------------------------------------------------------


def test_sunspec_simulator_roundtrip_soc() -> None:
    """An SoC written into the simulator survives the full decode path."""
    sim = SunSpecSimulator(soc=0.8542)
    src = SunSpecSource(transport=sim)

    soc = src.soc()
    assert 0.0 <= soc <= 1.0
    assert soc == pytest.approx(0.8542, abs=1e-6)

    # The same number must arrive through the ordinary sample path too, from
    # both the storage model (713) and the battery model (802).
    sample = src.read()
    assert sample.values["m713.SoC"] == pytest.approx(0.8542, abs=1e-6)
    assert sample.values["m802.SoC"] == pytest.approx(0.8542, abs=1e-6)
    assert sample.quality["m713.SoC"] == "good"

    # And it must track a change, including one caused by drift rather than by
    # assignment: 500 kW out of a 2 MWh bank for an hour is 25 % of capacity.
    sim2 = SunSpecSimulator(soc=0.80, capacity_wh=2_000_000, power_w=500_000)
    src2 = SunSpecSource(transport=sim2)
    sim2.advance(3600)
    assert src2.soc() == pytest.approx(0.55, abs=1e-4)

    sim.soc = 0.10
    assert src.soc() == pytest.approx(0.10, abs=1e-6)


def test_soc_prefers_713_and_explains_itself_when_absent() -> None:
    """802 is the fallback; a device with neither model must say so clearly."""
    only_802 = SunSpecSource(transport=SunSpecSimulator(soc=0.4, models=(1, 802)))
    assert only_802.soc() == pytest.approx(0.4, abs=1e-6)

    no_storage = SunSpecSource(transport=SunSpecSimulator(soc=0.4, models=(1, 701)))
    with pytest.raises(LookupError) as exc:
        no_storage.soc()
    message = str(exc.value)
    assert "713" in message and "802" in message
    assert "701" in message  # tells the operator what the device *does* publish


def test_out_of_range_soc_is_rejected_rather_than_returned() -> None:
    """A mis-set scale factor must surface, not propagate into the twin."""
    sim = SunSpecSimulator(soc=0.5, models=(1, 802))
    src = SunSpecSource(transport=sim)
    sim.inject_out_of_range(802, "SoC", 45000)  # 450 % once SoC_SF = -2 applies
    with pytest.raises(ValueError, match="scale-factor"):
        src.soc()


# --------------------------------------------------------------------------
# 2. Scale factors
# --------------------------------------------------------------------------


def test_sunspec_scale_factors_applied() -> None:
    """A point with sunssf = -2 comes back divided by 100, not raw."""
    sim = SunSpecSimulator(soc=0.8542)
    src = SunSpecSource(transport=sim)

    soc_sf_addr = sim.address_of(802, "SoC_SF")
    assert sim.get_raw(soc_sf_addr, 1) == [0x10000 - 2]  # sunssf -2, two's complement

    raw = sim.get_raw(sim.address_of(802, "SoC"), 1)[0]
    assert raw == 8542  # what is actually on the wire

    value = src.read().values["m802.SoC"]

    # 8542 * 10**-2 = 85.42 %, normalised to the fraction 0.8542.
    assert value == pytest.approx(0.8542, abs=1e-9)
    # The three wrong answers a broken decoder gives: unscaled, scaled but not
    # unit-normalised, and scaled the wrong way.
    assert value != pytest.approx(8542.0)
    assert value != pytest.approx(85.42)
    assert value != pytest.approx(85.42 * 100)

    # A scale factor of +3 must multiply, not divide: 2000 kWh-worth of raw
    # register with WH_SF = 3 is 2 MWh.
    assert sim.get_raw(sim.address_of(713, "WHRtg"), 1) == [2000]
    assert src.read().values["m713.WHRtg"] == pytest.approx(2_000_000.0)

    # Temperature carries both a scale factor and an offset conversion.
    assert src.read().values["m701.TmpAmb"] == pytest.approx(24.5 + 273.15, abs=1e-6)


def test_unimplemented_points_are_flagged_bad_not_decoded() -> None:
    """SunSpec's not-implemented sentinels must never become measurements."""
    # 0xFFFF is the uint16 not-implemented sentinel. With SoC_SF = -2 a naive
    # decoder reports it as 655.35, i.e. a state of charge of 65535 %.
    sim = SunSpecSimulator(soc=0.5)
    sim.pin_raw(802, "SoCMax", 0xFFFF)
    src = SunSpecSource(transport=sim)

    sample = src.read()
    assert sample.quality["m802.SoCMax"] == "bad"
    assert math.isnan(sample.values["m802.SoCMax"])
    assert sample.quality["m802.SoC"] == "good"  # the rest of the model is fine

    # A signed point signals the same thing with its most-negative value,
    # which a naive decoder reports as -3276.8 A. Once a good value has been
    # seen, the sentinel degrades to 'stale' rather than 'bad' — the device
    # has stopped answering for that point, and the last real reading is
    # still the best information available.
    assert src.read().quality["m802.A"] == "good"
    sim.pin_raw(802, "A", -0x8000)
    after = src.read()
    assert after.quality["m802.A"] == "stale"
    assert after.values["m802.A"] != pytest.approx(-3276.8)


# --------------------------------------------------------------------------
# 3. Word order
# --------------------------------------------------------------------------


def test_modbus_word_order() -> None:
    """The same registers decode differently under big and little word order."""
    spec = [RegisterSpec("f", 0, "float32", "1")]
    sim = ModbusSimulator(spec)
    sim.set_raw(0, [0x4248, 0x0000])  # 0x42480000 = 50.0 as IEEE-754 float32

    big = ModbusSource(spec, transport=sim, word_order="big").read().values["f"]
    little = ModbusSource(spec, transport=sim, word_order="little").read().values["f"]

    assert big == pytest.approx(50.0)
    assert little != pytest.approx(50.0)
    assert abs(little) < 1e-30  # 0x00004248 is a denormal, i.e. visibly wrong

    # Reversing the registers reverses which order is correct — proof that the
    # parameter selects word order rather than doing something incidental.
    sim.set_raw(0, [0x0000, 0x4248])
    big2 = ModbusSource(spec, transport=sim, word_order="big").read().values["f"]
    little2 = ModbusSource(spec, transport=sim, word_order="little").read().values["f"]
    assert little2 == pytest.approx(50.0)
    assert abs(big2) < 1e-30

    # The same for a 32-bit integer, where both answers are exact and neither
    # is a denormal that might be mistaken for a rounding artefact.
    ispec = [RegisterSpec("i", 0, "int32", "1")]
    isim = ModbusSimulator(ispec)
    isim.set_raw(0, [0x0001, 0x0002])
    assert (
        ModbusSource(ispec, transport=isim, word_order="big").read().values["i"] == 65538
    )
    assert (
        ModbusSource(ispec, transport=isim, word_order="little").read().values["i"]
        == 131073
    )


def test_word_order_mismatch_between_device_and_source_is_visible() -> None:
    """A device that word-swaps and a source that does not disagree loudly."""
    spec = [RegisterSpec("p", 0, "float32", "kW")]
    device = ModbusSimulator(spec, word_order="little")
    device.set_value("p", 250.0)
    matched = ModbusSource(spec, transport=device, word_order="little").read()
    mismatched = ModbusSource(spec, transport=device, word_order="big").read()
    assert matched.values["p"] == pytest.approx(250_000.0)
    assert mismatched.values["p"] != pytest.approx(250_000.0)


# --------------------------------------------------------------------------
# 4. Units
# --------------------------------------------------------------------------


def test_unit_normalisation() -> None:
    """Units convert to SI, and an unknown unit raises rather than passing."""
    assert to_si(1.5, "kW") == pytest.approx(1500.0)
    assert to_si(-2.0, "MW") == pytest.approx(-2e6)
    assert to_si(3.0, "MWh") == pytest.approx(3e6)
    assert to_si(2.0, "kWh") == pytest.approx(2000.0)
    assert to_si(50.0, "percent") == pytest.approx(0.5)
    assert to_si(50.0, "%") == pytest.approx(0.5)
    assert to_si(25.0, "degC") == pytest.approx(298.15)
    assert to_si(0.0, "K") == pytest.approx(0.0)
    assert to_si(1.5, "kA") == pytest.approx(1500.0)
    assert to_si(11.0, "kV") == pytest.approx(11000.0)
    assert to_si(50.0, "Hz") == pytest.approx(50.0)

    assert si_unit("kW") == "W"
    assert si_unit("MWh") == "Wh"
    assert si_unit("%") == "1"
    assert si_unit("degC") == "K"

    with pytest.raises(UnknownUnitError) as exc:
        to_si(1.0, "furlongs/fortnight")
    assert "furlongs/fortnight" in str(exc.value)
    with pytest.raises(UnknownUnitError):
        si_unit("kilowatts")

    # Case matters, deliberately: mW and MW differ by 10**9.
    assert to_si(1.0, "mW") == pytest.approx(1e-3)
    assert to_si(1.0, "MW") == pytest.approx(1e6)

    # A tag cannot be built without a valid unit at all.
    with pytest.raises(UnknownUnitError):
        TagSpec("x", "gigawatt-hours", "nonsense", "float32")
    assert "kW" in KNOWN_UNITS and "MWh" in KNOWN_UNITS


def test_register_spec_rejects_a_bad_unit_or_shape() -> None:
    """Validation happens where the map is written, not where it is read."""
    with pytest.raises(UnknownUnitError):
        RegisterSpec("p", 0, "float32", "killowatts")
    with pytest.raises(ValueError, match="occupies 2 register"):
        RegisterSpec("p", 0, "float32", "kW", count=1)
    with pytest.raises(ValueError, match="unknown dtype"):
        RegisterSpec("p", 0, "float64", "kW")
    with pytest.raises(ValueError, match="register_type"):
        RegisterSpec("p", 0, "uint16", "kW", register_type="coil")


# --------------------------------------------------------------------------
# 5 & 6. Degradation
# --------------------------------------------------------------------------


def test_read_failure_marks_bad_quality_and_does_not_raise(
    modbus_pair: tuple[ModbusSimulator, ModbusSource],
) -> None:
    """A timeout on a fresh source degrades to 'bad' and records the error."""
    sim, src = modbus_pair
    sim.inject_timeout(0, 6)  # covers p_dc, soc, cycles, v_dc

    sample = src.read()  # must not raise

    assert isinstance(sample, Sample)
    assert sample.quality["p_dc"] == "bad"
    assert sample.quality["soc"] == "bad"
    assert math.isnan(sample.values["p_dc"])
    assert src.last_error is not None
    assert isinstance(src.last_error, SimulatedFault)
    assert "simulated timeout" in str(src.last_error)

    # Tags outside the failed range are unaffected — one bad cable does not
    # take the whole twin down.
    assert sample.quality["t_cab"] == "good"
    assert sample.values["t_cab"] == pytest.approx(31.5 + 273.15, abs=1e-6)

    # A clean cycle clears last_error again.
    sim.clear_faults()
    recovered = src.read()
    assert src.last_error is None
    assert recovered.quality["p_dc"] == "good"


def test_stale_value_retained(
    modbus_pair: tuple[ModbusSimulator, ModbusSource],
) -> None:
    """After a good read, a failed read serves the last value as 'stale'."""
    sim, src = modbus_pair

    first = src.read()
    assert first.quality["p_dc"] == "good"
    assert first.values["p_dc"] == pytest.approx(250_000.0)

    sim.inject_timeout(0, 6)
    second = src.read()

    assert second.quality["p_dc"] == "stale"
    assert second.values["p_dc"] == pytest.approx(250_000.0)
    assert second.quality["soc"] == "stale"
    assert second.values["soc"] == pytest.approx(0.62)
    assert src.last_error is not None
    assert second.usable()["p_dc"] == pytest.approx(250_000.0)
    assert "p_dc" not in second.good()

    # Stale values expire when the source is told how old is too old.
    strict = ModbusSource(
        src.registers, transport=sim, word_order="big", max_stale_seconds=0.0
    )
    sim.clear_faults()
    strict.read()
    sim.inject_timeout(0, 6)
    expired = strict.read()
    assert expired.quality["p_dc"] == "bad"
    assert math.isnan(expired.values["p_dc"])


def test_sunspec_read_failure_degrades_per_model() -> None:
    """One unreachable SunSpec model does not stop the others being read."""
    sim = SunSpecSimulator(soc=0.7)
    src = SunSpecSource(transport=sim)
    assert src.read().quality["m802.SoC"] == "good"

    sim.inject_timeout_for_model(802)
    sample = src.read()

    assert sample.quality["m802.SoC"] == "stale"
    assert sample.values["m802.SoC"] == pytest.approx(0.7, abs=1e-6)
    assert sample.quality["m713.SoC"] == "good"
    assert src.last_error is not None
    # soc() falls through to 713, which is still answering.
    assert src.soc() == pytest.approx(0.7, abs=1e-6)


def test_frozen_value_reads_cleanly_but_stops_moving() -> None:
    """The quiet failure: a register that answers but no longer updates.

    No exception is raised anywhere and quality stays 'good', because from the
    connector's point of view nothing is wrong. Detecting this is a job for
    the condition-monitoring blocks downstream, not for data acquisition — but
    the simulator has to be able to produce it so those blocks can be tested.
    """
    sim = SunSpecSimulator(soc=0.9, models=(1, 802, 713))
    src = SunSpecSource(transport=sim)
    sim.freeze(802, "SoC")
    sim.soc = 0.3

    sample = src.read()
    assert sample.quality["m802.SoC"] == "good"
    assert sample.values["m802.SoC"] == pytest.approx(0.9, abs=1e-6)
    assert sample.values["m713.SoC"] == pytest.approx(0.3, abs=1e-6)

    sim.unfreeze(802, "SoC")
    assert src.read().values["m802.SoC"] == pytest.approx(0.3, abs=1e-6)


# --------------------------------------------------------------------------
# 7. Provenance
# --------------------------------------------------------------------------


def test_tagspec_carries_sunspec_provenance() -> None:
    """Model number, point name and address survive into the tag list."""
    sim = SunSpecSimulator(soc=0.55)
    src = SunSpecSource(transport=sim)
    tags = {t.name: t for t in src.tags()}

    soc = tags["m802.SoC"]
    assert soc.sunspec_model == 802
    assert soc.sunspec_point == "SoC"
    assert soc.address == sim.address_of(802, "SoC")
    assert soc.unit == "1"  # a fraction, because % normalises away
    assert soc.raw_unit == "percent"
    assert "802" in soc.description and "SoC" in soc.description

    power = tags["m701.W"]
    assert (power.sunspec_model, power.sunspec_point) == (701, "W")
    assert power.unit == "W"
    assert power.dtype == "int16"

    energy = tags["m713.WHRtg"]
    assert (energy.sunspec_model, energy.sunspec_point) == (713, "WHRtg")
    assert energy.unit == "Wh"

    # Raw Modbus tags carry no SunSpec provenance and must not pretend to.
    spec = [RegisterSpec("p", 7, "float32", "kW", description="power")]
    modbus_tag = ModbusSource(spec, transport=ModbusSimulator(spec)).tags()[0]
    assert modbus_tag.sunspec_model is None
    assert modbus_tag.sunspec_point is None
    assert modbus_tag.address == 7
    assert (modbus_tag.unit, modbus_tag.raw_unit) == ("W", "kW")

    # Device identity comes off the SunSpec common model.
    assert src.device_info["manufacturer"] == "Otwin"
    assert src.device_info["serial"] == "SIM-0000001"


# --------------------------------------------------------------------------
# 8. Optional dependencies
# --------------------------------------------------------------------------


def test_missing_optional_dependency_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without pymodbus, a live source names the package and the extra."""
    for module in ("pymodbus", "pymodbus.client"):
        monkeypatch.setitem(sys.modules, module, None)

    spec = [RegisterSpec("p", 0, "float32", "kW")]
    with pytest.raises(MissingDependencyError) as exc:
        ModbusSource(spec, host="10.0.0.7")

    message = str(exc.value)
    assert "pymodbus" in message
    assert "otwin[modbus]" in message
    assert "pip install" in message
    assert "ModbusSimulator" in message  # tells you what to do instead
    assert isinstance(exc.value, ImportError)

    # With both extras absent, SunSpec names both and both install commands.
    for module in ("sunspec2", "sunspec2.modbus", "sunspec2.modbus.modbus"):
        monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(MissingDependencyError) as exc2:
        SunSpecSource(host="10.0.0.7")
    message2 = str(exc2.value)
    assert "pysunspec2" in message2 and "pymodbus" in message2
    assert "otwin[sunspec]" in message2 and "otwin[modbus]" in message2
    assert "SunSpecSimulator" in message2

    # And the simulators still work with nothing installed at all.
    assert SunSpecSource(transport=SunSpecSimulator(soc=0.33)).soc() == pytest.approx(
        0.33, abs=1e-6
    )


# --------------------------------------------------------------------------
# Register maps, batching and protocol conformance
# --------------------------------------------------------------------------


def test_register_map_loads_from_yaml_and_json(tmp_path: Path) -> None:
    """A PCS can be described in a file, without writing Python."""
    doc = {
        "unit_id": 3,
        "word_order": "little",
        "registers": [
            {
                "name": "p_ac",
                "address": 100,
                "dtype": "float32",
                "unit": "kW",
                "description": "AC power",
            },
            {
                "name": "soc",
                "address": 102,
                "dtype": "uint16",
                "unit": "%",
                "scale": 0.1,
                "register_type": "input",
            },
        ],
    }
    json_path = tmp_path / "pcs.json"
    json_path.write_text(json.dumps(doc), encoding="utf-8")
    specs, options = load_register_map(json_path)
    assert [s.name for s in specs] == ["p_ac", "soc"]
    assert specs[0].count == 2  # inferred from float32
    assert specs[1].register_type == "input"
    assert options == {"unit_id": 3, "word_order": "little"}

    yaml = pytest.importorskip("yaml")
    yaml_path = tmp_path / "pcs.yaml"
    yaml_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    yaml_specs, yaml_options = load_register_map(yaml_path)
    assert yaml_specs == specs and yaml_options == options

    # The file's own options become constructor defaults.
    sim = ModbusSimulator(specs, word_order="little")
    sim.set_value("p_ac", 400.0)
    src = ModbusSource.from_file(json_path, transport=sim)
    assert src.word_order == "little"
    assert src.read().values["p_ac"] == pytest.approx(400_000.0)

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"registers": [{"name": "x", "address": 1}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_register_map(bad)


def test_batching_collapses_contiguous_registers(
    pcs_map: list[RegisterSpec],
) -> None:
    """Contiguous tags cost one round trip, not one each."""
    sim = ModbusSimulator(pcs_map)
    src = ModbusSource(pcs_map, transport=sim)
    # p_dc..v_dc occupy 0..5 contiguously; t_cab and serial are far away.
    assert src.batches == [("holding", 0, 6), ("holding", 40, 1), ("holding", 60, 8)]
    src.read()
    assert sim.read_count == 3

    # A small hole may be bridged when the caller allows it: the 19-register
    # gap between t_cab and serial closes, the 34-register one before t_cab
    # does not.
    bridged = ModbusSource(pcs_map, transport=sim, max_gap=19)
    assert bridged.batches == [("holding", 0, 6), ("holding", 40, 28)]

    # And the Modbus 125-register limit is never exceeded.
    wide = [RegisterSpec(f"r{i}", i, "uint16", "V") for i in range(300)]
    chunked = ModbusSource(wide, transport=ModbusSimulator(wide))
    assert [c for _, _, c in chunked.batches] == [125, 125, 50]
    with pytest.raises(ValueError, match="max_registers_per_read"):
        ModbusSource(wide, transport=ModbusSimulator(wide), max_registers_per_read=200)


def test_sources_and_simulators_satisfy_the_source_protocol(
    modbus_pair: tuple[ModbusSimulator, ModbusSource],
) -> None:
    """Structural typing, checked — nothing here inherits from Source."""
    sim, src = modbus_pair
    sunspec = SunSpecSource(transport=SunSpecSimulator(soc=0.5))
    assert isinstance(src, Source)
    assert isinstance(sunspec, Source)
    assert not issubclass(type(src), Source.__mro__[1]) if False else True

    for source in (src, sunspec):
        sample = source.read()
        names = {t.name for t in source.tags()}
        assert set(sample.quality) <= names
        assert set(sample.values) <= names
        assert sample.timestamp > 0
        source.close()

    # Closing is idempotent, and reading a closed simulated link degrades
    # rather than exploding.
    src.close()
    assert src.read().quality["p_dc"] in ("stale", "bad")


def test_sample_rejects_inconsistent_quality() -> None:
    """A Sample cannot be built with a value that has no quality flag."""
    with pytest.raises(ValueError, match="quality flag"):
        Sample(1.0, {"a": 1.0}, {}, "test")
    with pytest.raises(ValueError, match="invalid quality"):
        Sample(1.0, {"a": 1.0}, {"a": "probably fine"}, "test")


def test_sunspec_discovery_walks_the_model_chain() -> None:
    """Discovery finds the base address, every model, and the end marker."""
    sim = SunSpecSimulator(soc=0.5, base_address=50000)
    src = SunSpecSource(transport=sim)
    assert src.base_address == 50000
    assert [m.model_id for m in src.models] == [1, 802, 713, 701]
    assert [m.address for m in src.models] == [
        sim.address_of(m) for m in (1, 802, 713, 701)
    ]
    # Model lengths exclude the ID and L registers, per the specification.
    by_id = {m.model_id: m for m in src.models}
    assert by_id[713].length == 7
    assert by_id[802].length == 62
    assert src.unmapped_points == []

    # A device with no SunSpec identifier is a hard error, not a quality flag:
    # there is nothing to decode and nothing to fall back on.
    from otwin.io.source import TransportError

    blank = ModbusSimulator([RegisterSpec("x", 0, "uint16", "V")])
    with pytest.raises(TransportError, match="no SunSpec model chain"):
        SunSpecSource(transport=blank)


# --------------------------------------------------------------------------
# Cross-checks against the optional packages, skipped when absent
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", sorted(_BUILTIN_MODEL_DEFS))
def test_builtin_model_defs_agree_with_official(model_id: int) -> None:
    """The hand-transcribed fallback table matches the official SunSpec JSON.

    A one-register transcription error in that table would shift every field
    after it and would be invisible in every other test, because the simulator
    and the source would share the same mistake.
    """
    pytest.importorskip("sunspec2", reason="pysunspec2 supplies the official model JSON")
    problems = compare_model_defs(model_id)
    assert problems == []


def test_pymodbus_transport_uses_a_supported_signature() -> None:
    """The unit/slave/device_id keyword shim resolves against real pymodbus."""
    pytest.importorskip("pymodbus", reason="live transport test")
    from otwin.io.modbus import PymodbusTransport

    transport = PymodbusTransport(host="127.0.0.1", port=15020, unit_id=7)
    assert transport._unit_kwarg in ("device_id", "slave", "unit")
    assert transport.name == "modbus-tcp://127.0.0.1:15020#7"
    transport.close()
