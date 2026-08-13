"""The failure paths of otwin.io: bad frames, corrupt chains, dead links.

:mod:`tests.test_io` covers what the connector layer does when the plant is
behaving. This file covers what it does when the plant is not, which is where
a field connector actually earns its keep: a switch that drops one register
range, a device that reports a model length longer than the model it sent, a
scale-factor register holding a sentinel, a serial line that answers with
three registers when it was asked for four, a value that was good ten minutes
ago and is now too old to act on.

Everything here runs with no network, no hardware and no optional package.
The two live transports are driven through fake clients that implement the
pymodbus / pysunspec2 call signatures, and every clock is injected — there is
no ``sleep`` in this file, so the staleness ladder is tested at exactly its
boundary rather than approximately near it.

Where a test needs an optional package to mean anything (the YAML register-map
loader, the shape of the real pysunspec2 client) it is skipped when absent and
the same behaviour is covered dependency-free elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# The repository has no packaging metadata yet, so the package is imported
# from the source tree directly rather than from an installed distribution.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from otwin.io import (  # noqa: E402
    ModbusSimulator,
    ModbusSource,
    RegisterSpec,
    SunSpecSimulator,
    SunSpecSource,
    TagSpec,
    load_register_map,
    normalise,
)
from otwin.io import loader as loader_mod  # noqa: E402
from otwin.io import modbus as modbus_mod  # noqa: E402
from otwin.io import sunspec as sunspec_mod  # noqa: E402
from otwin.io.modbus import (  # noqa: E402
    DTYPE_REGISTERS,
    PymodbusTransport,
    decode_registers,
    encode_value,
)
from otwin.io.registry import Dataset  # noqa: E402
from otwin.io.simulator import (  # noqa: E402
    SimulatedFault,
    _encode_sunspec,
    _sentinel_words,
)
from otwin.io.source import (  # noqa: E402
    MissingDependencyError,
    QualityTracker,
    RegisterTransport,
    Source,
    TransportError,
)
from otwin.io.sunspec import (  # noqa: E402
    _BUILTIN_MODEL_DEFS,
    _TYPES,
    SUNSPEC_IDENTIFIER,
    ModelDef,
    PointDef,
    PySunSpec2Transport,
    compare_model_defs,
    decode_point,
    load_model_def,
)

# --------------------------------------------------------------------------
# Helpers: hand-built register images and fake wire clients
# --------------------------------------------------------------------------


def _chain(
    models: list[tuple[int, int, dict[int, list[int]]]], base: int = 40000
) -> ModbusSimulator:
    """Serve a hand-built SunSpec chain from a raw register image.

    The :class:`SunSpecSimulator` only produces well-formed devices, which is
    the point of it. Discovery failures need malformed ones, so these tests
    lay the ``"SunS"`` marker, the ``(id, length)`` headers and the end marker
    out by hand and serve them through the plain Modbus simulator, which is a
    register bank and nothing more.

    Args:
        models: ``(model_id, declared_length, {offset: words})`` per model,
            where ``declared_length`` is the device's own ``L`` — deliberately
            allowed to disagree with the model definition.
    """
    sim = ModbusSimulator(name="image-sim://local")
    sim.set_raw(base, list(SUNSPEC_IDENTIFIER))
    addr = base + 2
    for model_id, length, payload in models:
        sim.set_raw(addr, [model_id, length])
        for offset, words in payload.items():
            sim.set_raw(addr + offset, words)
        addr += length + 2
    sim.set_raw(addr, [0xFFFF, 0x0000])
    return sim


class _FakeResponse:
    """A pymodbus read result: registers plus the isError() protocol."""

    def __init__(self, registers: list[int], error: bool = False) -> None:
        self.registers = list(registers)
        self._error = error

    def isError(self) -> bool:
        return self._error


class _FakePymodbusClient:
    """Enough of a pymodbus 3.x client to drive :class:`PymodbusTransport`.

    The unit-id keyword is spelled ``device_id`` here; the subclasses below
    spell it the two older ways, which is what the transport's shim exists to
    absorb.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.connected = False
        self.connect_ok = True
        self.response: Any = _FakeResponse([0x1234])
        self.raise_on_read: Exception | None = None
        self.closes = 0
        self.calls: list[tuple[str, int, int, int]] = []

    def connect(self) -> bool:
        self.connected = self.connect_ok
        return self.connected

    def close(self) -> None:
        self.closes += 1
        self.connected = False

    def _served(self, kind: str, address: int, count: int, unit: int) -> Any:
        self.calls.append((kind, address, count, unit))
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.response

    def read_holding_registers(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> Any:
        return self._served("holding", address, count, device_id)

    def read_input_registers(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> Any:
        return self._served("input", address, count, device_id)


class _SlaveKwargClient(_FakePymodbusClient):
    """pymodbus 3.0-3.6 spelling."""

    def read_holding_registers(
        self, address: int, *, count: int = 1, slave: int = 1
    ) -> Any:  # type: ignore[override]
        return self._served("holding", address, count, slave)

    def read_input_registers(
        self, address: int, *, count: int = 1, slave: int = 1
    ) -> Any:  # type: ignore[override]
        return self._served("input", address, count, slave)


class _UnitKwargClient(_FakePymodbusClient):
    """pymodbus 2.x spelling."""

    def read_holding_registers(
        self, address: int, *, count: int = 1, unit: int = 1
    ) -> Any:  # type: ignore[override]
        return self._served("holding", address, count, unit)

    def read_input_registers(self, address: int, *, count: int = 1, unit: int = 1) -> Any:  # type: ignore[override]
        return self._served("input", address, count, unit)


class _AlienKwargClient(_FakePymodbusClient):
    """A build whose signature this shim does not recognise at all."""

    def read_holding_registers(
        self, address: int, *, count: int = 1, uid: int = 1
    ) -> Any:  # type: ignore[override]
        return self._served("holding", address, count, uid)


def _install_fake_pymodbus(
    monkeypatch: pytest.MonkeyPatch, client_cls: type[_FakePymodbusClient]
) -> None:
    """Make :func:`~otwin.io.modbus._import_pymodbus` yield a fake client."""
    module = types.SimpleNamespace(
        ModbusTcpClient=client_cls, ModbusSerialClient=client_cls
    )
    monkeypatch.setattr(modbus_mod, "_import_pymodbus", lambda: module)


class _FakeSunSpecClient:
    """Enough of ``sunspec2.modbus.modbus.ModbusClientTCP`` to drive the shim."""

    def __init__(
        self, *, slave_id: int, ipaddr: str, ipport: int, timeout: float
    ) -> None:
        self.slave_id = slave_id
        self.ipaddr = ipaddr
        self.ipport = ipport
        self.timeout = timeout
        self.connects = 0
        self.disconnects = 0
        self.raise_on_disconnect = False
        self.result: Any = b"\x00\x01"
        self.raise_on_read: Exception | None = None
        self.calls: list[tuple[int, int, int]] = []

    def connect(self) -> None:
        self.connects += 1

    def disconnect(self) -> None:
        self.disconnects += 1
        if self.raise_on_disconnect:
            raise OSError("socket already gone")

    def read(self, addr: int, count: int, op: int = 3) -> Any:
        self.calls.append((addr, count, op))
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.result


def _fake_sunspec_transport(
    monkeypatch: pytest.MonkeyPatch, **kwargs: Any
) -> PySunSpec2Transport:
    """A :class:`PySunSpec2Transport` wrapping :class:`_FakeSunSpecClient`."""
    module = types.SimpleNamespace(ModbusClientTCP=_FakeSunSpecClient)
    monkeypatch.setattr(sunspec_mod, "_import_pysunspec2_modbus", lambda: module)
    return PySunSpec2Transport("10.0.0.9", 5020, unit_id=7, **kwargs)


class _ShortReadTransport:
    """A transport that always returns one register fewer than it was asked.

    A real device does this when a gateway truncates the response frame. The
    connector must not decode the remainder as if it were complete.
    """

    name = "short://local"

    def __init__(self, words: list[int]) -> None:
        self.words = words

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        return self.words[: max(0, count - 1)]

    def close(self) -> None:
        pass


class _Clock:
    """An injectable monotonic clock, so staleness is tested at its boundary."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


# --------------------------------------------------------------------------
# Modbus codec: every dtype, both word orders, both sign boundaries
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        ("uint16", 0.0),
        ("uint16", 65535.0),
        ("int16", -32768.0),
        ("int16", 32767.0),
        ("uint32", 0.0),
        ("uint32", 4294967295.0),
        ("int32", -2147483648.0),
        ("int32", 2147483647.0),
        ("float32", -1234.5),
    ],
)
@pytest.mark.parametrize("word_order", ["big", "little"])
def test_every_dtype_round_trips_at_its_boundaries(
    dtype: str, value: float, word_order: str
) -> None:
    """encode/decode agree for every wire type at its extreme values.

    The boundaries are the whole point: ``int16`` at -32768 and ``uint32`` at
    its maximum are where a decoder that reaches for the wrong struct format,
    or masks a sign bit away, stops agreeing with the device. A round trip
    through the middle of the range would pass with either.
    """
    words = encode_value(value, dtype, DTYPE_REGISTERS[dtype], word_order)
    assert len(words) == DTYPE_REGISTERS[dtype]
    assert all(0 <= w <= 0xFFFF for w in words)
    assert decode_registers(words, dtype, word_order) == pytest.approx(value)

    # Two registers reversed is a different number unless the value happens to
    # be palindromic; one register is unaffected by word order at all.
    other = "little" if word_order == "big" else "big"
    if DTYPE_REGISTERS[dtype] == 1:
        assert decode_registers(words, dtype, other) == pytest.approx(value)
    elif words[0] != words[1]:
        assert decode_registers(words, dtype, other) != pytest.approx(value)


def test_string_decoding_stops_at_the_first_nul() -> None:
    """A serial number is NUL-padded, and the padding is not part of it."""
    words = encode_value("PCS-0042", "string", 8)
    assert decode_registers(words, "string") == "PCS-0042"

    # A device that packs two fields into one block, or that leaves rubbish
    # after the terminator, must not have the rubbish appended to the tag.
    words = encode_value("ABC", "string", 4)
    words[2] = 0x5858  # "XX" after the NUL
    assert decode_registers(words, "string") == "ABC"

    # Surrounding whitespace goes; the value is a tag, not free text.
    assert decode_registers(encode_value("  A1  ", "string", 4), "string") == "A1"

    # A string is written big-endian whatever the numeric word order is: the
    # character order is fixed by the wire format, not by the vendor.
    assert encode_value("ABCD", "string", 2, "little") == encode_value(
        "ABCD", "string", 2, "big"
    )

    # Longer than its field, it is truncated rather than overrunning the tag.
    assert decode_registers(encode_value("TOOLONGVALUE", "string", 2), "string") == "TOOL"


def test_codec_rejects_frames_it_cannot_decode() -> None:
    """Every way a caller or a transport can hand the codec nonsense."""
    with pytest.raises(ValueError, match="word_order must be"):
        decode_registers([0x0000, 0x4248], "float32", "middle")

    # A transport that hands back a signed or oversized word is broken; the
    # codec must say so rather than silently masking it to 16 bits.
    with pytest.raises(ValueError, match="not a 16-bit word"):
        decode_registers([0x1FFFF], "uint16")
    with pytest.raises(ValueError, match="not a 16-bit word"):
        decode_registers([-1], "uint16")

    with pytest.raises(ValueError, match="unknown dtype"):
        decode_registers([0, 0], "float64")
    with pytest.raises(ValueError, match="needs 2 register"):
        decode_registers([0x0001], "uint32")
    with pytest.raises(ValueError, match="needs 2 register"):
        decode_registers([0x0001, 0x0002, 0x0003], "float32")
    with pytest.raises(ValueError, match="unknown dtype"):
        encode_value(1.0, "float64", 2)


def test_register_spec_rejects_a_string_without_a_width_or_a_negative_address() -> None:
    """The two shapes a hand-written register map gets wrong most often."""
    with pytest.raises(ValueError, match="explicit count >= 1"):
        RegisterSpec("serial", 60, "string", "1")
    with pytest.raises(ValueError, match="address must be >= 0"):
        RegisterSpec("p", -1, "uint16", "kW")

    # 4xxxx notation minus one is a legal address; the manual's 40001 is 0.
    assert RegisterSpec("p", 0, "uint16", "kW").end == 1


# --------------------------------------------------------------------------
# Register maps from file
# --------------------------------------------------------------------------


def _write(path: Path, doc: Any) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_register_map_accepts_a_bare_list_and_reports_where_it_is_malformed(
    tmp_path: Path,
) -> None:
    """A register map is written by hand, so its errors must name the entry.

    Every failure below is one somebody makes editing YAML at 2 a.m. on a
    commissioning visit; a bare ``KeyError`` or ``TypeError`` at that point
    costs an hour.
    """
    listed = _write(
        tmp_path / "list.json",
        [{"name": "p", "address": 0, "dtype": "float32", "unit": "kW"}],
    )
    specs, options = load_register_map(listed)
    assert [s.name for s in specs] == ["p"]
    assert options == {}  # the bare-list form carries no connection defaults

    with pytest.raises(ValueError, match="needs a 'registers' key"):
        load_register_map(_write(tmp_path / "nokey.json", {"unit_id": 1}))
    with pytest.raises(ValueError, match="expected a mapping or a list"):
        load_register_map(_write(tmp_path / "scalar.json", "p_dc"))
    with pytest.raises(ValueError, match="'registers' must be a list"):
        load_register_map(_write(tmp_path / "notlist.json", {"registers": {"p": 1}}))
    with pytest.raises(ValueError, match="entry 0 is not a mapping"):
        load_register_map(_write(tmp_path / "entry.json", {"registers": ["p_dc"]}))

    # A misspelled key reaches RegisterSpec as an unexpected argument. The
    # loader has to translate that into something that names the file, the
    # entry and the tag.
    bad_key = _write(
        tmp_path / "typo.json",
        {"registers": [{"name": "p", "address": 0, "dtype": "float32", "units": "kW"}]},
    )
    with pytest.raises(ValueError) as exc:
        load_register_map(bad_key)
    assert "entry 0" in str(exc.value) and "'p'" in str(exc.value)

    dupes = _write(
        tmp_path / "dupe.json",
        {
            "registers": [
                {"name": "p", "address": 0, "dtype": "uint16", "unit": "kW"},
                {"name": "p", "address": 1, "dtype": "uint16", "unit": "kW"},
            ]
        },
    )
    with pytest.raises(ValueError, match="duplicate tag name 'p'"):
        load_register_map(dupes)


def test_register_map_loads_from_yaml(tmp_path: Path) -> None:
    """The YAML form is the one a commissioning engineer actually writes.

    Skipped without PyYAML, which is optional; the JSON path above covers the
    same parsing and validation with no dependency at all.
    """
    yaml = pytest.importorskip("yaml", reason="PyYAML supplies the YAML loader")
    doc = {
        "unit_id": 3,
        "registers": [{"name": "p", "address": 0, "dtype": "float32", "unit": "kW"}],
    }
    path = tmp_path / "pcs.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    specs, options = load_register_map(path)
    assert [s.name for s in specs] == ["p"]
    assert options == {"unit_id": 3}

    # .yml is the same format under a different suffix.
    alt = tmp_path / "pcs.yml"
    alt.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert load_register_map(alt) == (specs, options)


def test_from_file_applies_file_options_and_rejects_unknown_ones(tmp_path: Path) -> None:
    """Connection defaults live in the map file; typos in them must not pass.

    ``from_file`` forwards the file's options straight into the constructor,
    so an unrecognised key would otherwise surface as an opaque TypeError
    about keyword arguments.
    """
    doc = {
        "word_order": "little",
        "max_gap": 2,
        "name": "pcs-1",
        "registers": [
            {"name": "p", "address": 0, "dtype": "float32", "unit": "kW"},
            {"name": "soc", "address": 3, "dtype": "uint16", "unit": "%", "scale": 0.1},
        ],
    }
    path = _write(tmp_path / "pcs.json", doc)
    specs, _ = load_register_map(path)
    sim = ModbusSimulator(specs, word_order="little")
    sim.set_value("p", 250.0)
    sim.set_value("soc", 55.0)

    src = ModbusSource.from_file(path, transport=sim)
    assert src.name == "pcs-1"
    assert src.word_order == "little"
    assert src.max_gap == 2  # the one-register hole is bridged
    assert src.batches == [("holding", 0, 4)]
    sample = src.read()
    assert sample.values["p"] == pytest.approx(250_000.0)
    assert sample.values["soc"] == pytest.approx(0.55)

    # An argument passed here beats the file, which is what lets one map serve
    # a fleet of identical PCS units at different addresses.
    assert (
        ModbusSource.from_file(path, transport=sim, word_order="big").word_order == "big"
    )

    doc["baud"] = 19200  # not "baudrate"
    with pytest.raises(ValueError, match=r"unknown option\(s\) \['baud'\]"):
        ModbusSource.from_file(_write(tmp_path / "typo.json", doc), transport=sim)


# --------------------------------------------------------------------------
# ModbusSource: construction, batching limits, decode failures
# --------------------------------------------------------------------------


def test_modbus_source_rejects_a_map_it_cannot_read_correctly() -> None:
    """Constructor validation, all of which prevents a silent wrong answer."""
    spec = [RegisterSpec("p", 0, "float32", "kW")]
    with pytest.raises(ValueError, match="word_order must be"):
        ModbusSource(spec, transport=ModbusSimulator(spec), word_order="mixed")
    with pytest.raises(ValueError, match="reads nothing"):
        ModbusSource([], transport=ModbusSimulator())
    with pytest.raises(ValueError, match="duplicate tag names"):
        ModbusSource(
            [RegisterSpec("p", 0, "uint16", "kW"), RegisterSpec("p", 1, "uint16", "kW")],
            transport=ModbusSimulator(),
        )
    with pytest.raises(ValueError, match="max_gap must be >= 0"):
        ModbusSource(spec, transport=ModbusSimulator(spec), max_gap=-1)


def test_a_tag_wider_than_one_request_is_refused_at_construction() -> None:
    """A 130-register string cannot be fetched by a protocol capped at 125.

    Refusing at construction is the difference between a commissioning script
    that fails on the bench and a source that quietly returns half a serial
    number in the field.
    """
    long_string = [RegisterSpec("notes", 0, "string", "1", count=130)]
    with pytest.raises(ValueError, match="needs 130 registers"):
        ModbusSource(long_string, transport=ModbusSimulator())

    # It is the read limit that decides, not the dtype: lower the limit and an
    # ordinary 2-register tag hits the same wall.
    with pytest.raises(ValueError, match="max_registers_per_read is 1"):
        ModbusSource(
            [RegisterSpec("p", 0, "float32", "kW")],
            transport=ModbusSimulator(),
            max_registers_per_read=1,
        )


def test_a_short_frame_degrades_only_the_tags_it_truncates() -> None:
    """A truncated response must not be decoded as if it were complete.

    The transport here returns one register fewer than asked for, the way a
    gateway does when it truncates a frame. ``p`` loses a register and cannot
    be decoded; ``soc``, which sits earlier in the same block, still can.
    """
    specs = [
        RegisterSpec("soc", 0, "uint16", "%", scale=0.1),
        RegisterSpec("p", 1, "float32", "kW"),
    ]
    src = ModbusSource(specs, transport=_ShortReadTransport([620, 0x4348, 0x8000]))

    sample = src.read()
    assert sample.quality["soc"] == "good"
    assert sample.values["soc"] == pytest.approx(0.62)
    assert sample.quality["p"] == "bad"
    assert math.isnan(sample.values["p"])
    assert src.last_error is not None
    assert "needs 2 register" in str(src.last_error)

    # Nothing was recorded as good for p, so it cannot later be served stale.
    assert src.read().quality["p"] == "bad"


def test_a_failed_string_tag_is_stale_only_once_it_has_been_read() -> None:
    """Strings live in metadata, not values, and degrade on their own ladder."""
    specs = [RegisterSpec("serial", 60, "string", "1", count=8)]
    sim = ModbusSimulator(specs)
    sim.set_value("serial", "PCS-0042")
    src = ModbusSource(specs, transport=sim)

    sim.inject_timeout(60, 8)
    first = src.read()
    assert first.quality["serial"] == "bad"
    assert "serial" not in first.values  # a Sample holds floats only

    sim.clear_faults()
    assert src.read().quality["serial"] == "good"
    assert src.metadata["serial"] == "PCS-0042"

    sim.inject_timeout(60, 8)
    assert src.read().quality["serial"] == "stale"
    assert src.metadata["serial"] == "PCS-0042"


def test_modbus_source_closes_once_and_describes_itself() -> None:
    """A source is a context manager, and its repr is a commissioning aid."""
    specs = [
        RegisterSpec("p", 0, "float32", "kW"),
        RegisterSpec("t", 40, "int16", "degC"),
    ]
    sim = ModbusSimulator(specs)
    with ModbusSource(specs, transport=sim, name="pcs-7") as src:
        assert src.read().quality["p"] == "good"
        text = repr(src)
    assert "pcs-7" in text and "tags=2" in text and "reads_per_cycle=2" in text
    assert "word_order='big'" in text

    # The transport is closed exactly once however often close() is called,
    # because a second close on a real client is not always harmless.
    src.close()
    src.close()
    with pytest.raises(SimulatedFault, match="transport is closed"):
        sim.read_registers(0, 2)


# --------------------------------------------------------------------------
# The staleness ladder, on an injected clock
# --------------------------------------------------------------------------


def test_quality_tracker_expires_a_value_at_its_boundary() -> None:
    """good -> stale -> bad, with the transition tested exactly at the limit.

    ``max_stale_seconds`` is the setting that decides whether control code is
    allowed to act on an old number, so the boundary is the behaviour: at
    exactly the limit the value is still stale, one instant past it is bad.
    The clock is passed in, so this is exact rather than nearly.
    """
    tracker = QualityTracker(max_stale_seconds=30.0)
    t0 = 1_000_000.0

    assert tracker.last_good("p") is None
    assert tracker.resolve_failed("p", t0) == (
        pytest.approx(math.nan, nan_ok=True),
        "bad",
    )

    tracker.record_good("p", 250_000.0, t0)
    assert tracker.last_good("p") == pytest.approx(250_000.0)
    assert tracker.resolve_failed("p", t0 + 29.999) == (250_000.0, "stale")
    assert tracker.resolve_failed("p", t0 + 30.0) == (250_000.0, "stale")
    value, quality = tracker.resolve_failed("p", t0 + 30.001)
    assert quality == "bad" and math.isnan(value)

    # Without a limit an old value is served indefinitely: right for a
    # nameplate rating, wrong for a measurement, hence the explicit setting.
    forever = QualityTracker()
    forever.record_good("rating", 2e6, t0)
    assert forever.resolve_failed("rating", t0 + 86_400.0) == (2e6, "stale")

    # forget() is what a reconnect does: nothing may be served stale across a
    # link that has been down and back, because the device may have changed.
    forever.forget()
    assert forever.last_good("rating") is None
    assert forever.resolve_failed("rating", t0 + 1.0)[1] == "bad"


def test_stale_values_expire_through_the_source_on_a_controlled_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same ladder end to end, with the source's own clock injected."""
    clock = _Clock()
    monkeypatch.setattr(modbus_mod, "time", clock)

    specs = [RegisterSpec("p", 0, "float32", "kW")]
    sim = ModbusSimulator(specs)
    sim.set_value("p", 250.0)
    src = ModbusSource(specs, transport=sim, max_stale_seconds=60.0)

    assert src.read().quality["p"] == "good"
    sim.inject_timeout(0, 2)

    clock.tick(59.0)
    still = src.read()
    assert still.quality["p"] == "stale"
    assert still.values["p"] == pytest.approx(250_000.0)

    clock.tick(2.0)  # 61 s since the last good read
    expired = src.read()
    assert expired.quality["p"] == "bad"
    assert math.isnan(expired.values["p"])
    assert expired.timestamp == clock.now  # the sample is stamped, not guessed

    # Recovery re-arms the ladder rather than leaving the tag condemned.
    sim.clear_faults()
    clock.tick(1.0)
    assert src.read().quality["p"] == "good"
    sim.inject_timeout(0, 2)
    assert src.read().quality["p"] == "stale"


# --------------------------------------------------------------------------
# The pymodbus transport shim, driven through a fake client
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client_cls", "expected"),
    [
        (_FakePymodbusClient, "device_id"),
        (_SlaveKwargClient, "slave"),
        (_UnitKwargClient, "unit"),
    ],
)
def test_transport_adapts_to_every_pymodbus_unit_keyword(
    monkeypatch: pytest.MonkeyPatch, client_cls: type[_FakePymodbusClient], expected: str
) -> None:
    """pymodbus renamed the unit argument twice; all three must still work.

    Getting this wrong does not fail loudly — the request goes out to unit 1
    instead of unit 7 — so the test checks the value that arrives at the
    client, not just the keyword the shim picked.
    """
    _install_fake_pymodbus(monkeypatch, client_cls)
    transport = PymodbusTransport(host="10.0.0.7", port=502, unit_id=7)
    assert transport._unit_kwarg == expected
    assert transport.name == "modbus-tcp://10.0.0.7:502#7"

    client = transport._client
    client.response = _FakeResponse([0x0001, 0x0002])
    assert transport.read_registers(100, 2) == [0x0001, 0x0002]
    assert client.calls == [("holding", 100, 2, 7)]

    # Function 4 reaches the other method; a device that publishes its
    # measurements as input registers is common enough to matter.
    assert transport.read_registers(100, 2, "input") == [0x0001, 0x0002]
    assert client.calls[-1] == ("input", 100, 2, 7)


def test_transport_refuses_a_pymodbus_build_it_cannot_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognised signature is named at construction, not at read time."""
    _install_fake_pymodbus(monkeypatch, _AlienKwargClient)
    with pytest.raises(MissingDependencyError) as exc:
        PymodbusTransport(host="10.0.0.7")
    message = str(exc.value)
    assert "unrecognised signature" in message
    assert "pymodbus>=3,<4" in message  # says what to install instead


def test_transport_turns_every_wire_failure_into_a_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connect failure, exception response, short frame, driver exception.

    All four are what a plant network does on a bad day, and all four have to
    arrive as :class:`TransportError` — the source degrades on that and on
    nothing else.
    """
    _install_fake_pymodbus(monkeypatch, _FakePymodbusClient)
    transport = PymodbusTransport(host="10.0.0.7", unit_id=1)
    client = transport._client

    client.connect_ok = False
    with pytest.raises(TransportError, match="could not connect"):
        transport.read_registers(0, 2)
    assert client.calls == []  # no request went out on a dead socket

    client.connect_ok = True
    client.raise_on_read = OSError("connection reset by peer")
    with pytest.raises(TransportError, match="read at 0\\+2 failed") as exc:
        transport.read_registers(0, 2)
    assert isinstance(exc.value.__cause__, OSError)
    assert client.closes == 1  # the socket is dropped so the next read redials

    client.raise_on_read = None
    client.connected = True
    client.response = _FakeResponse([], error=True)
    with pytest.raises(TransportError, match="exception response"):
        transport.read_registers(0, 2)

    client.response = None
    with pytest.raises(TransportError, match="exception response"):
        transport.read_registers(0, 2)

    # A frame carrying three registers when four were asked for is the failure
    # that silently shifts every value after it if it is not caught.
    client.response = _FakeResponse([1, 2, 3])
    with pytest.raises(TransportError, match="short frame"):
        transport.read_registers(0, 4)

    transport.close()
    transport.close()  # idempotent


def test_transport_close_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing teardown must not mask the error that caused the close."""
    _install_fake_pymodbus(monkeypatch, _FakePymodbusClient)
    transport = PymodbusTransport(host="10.0.0.7")

    def explode() -> None:
        raise OSError("socket already gone")

    transport._client.close = explode
    transport.close()  # must not raise


def test_serial_transport_names_the_line_it_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RTU is half the installed base; its identity must reach Sample.source."""
    _install_fake_pymodbus(monkeypatch, _FakePymodbusClient)
    transport = PymodbusTransport(device="/dev/ttyUSB0", baudrate=9600, unit_id=3)
    assert transport.name == "modbus-rtu:///dev/ttyUSB0@9600#3"
    assert transport._client.kwargs["baudrate"] == 9600
    assert transport._client.kwargs["parity"] == "N"

    with pytest.raises(ValueError, match="exactly one of host="):
        PymodbusTransport(host="10.0.0.7", device="/dev/ttyUSB0")
    with pytest.raises(ValueError, match="exactly one of host="):
        PymodbusTransport()


def test_a_live_source_takes_its_name_from_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sample.source must identify the device, not the class."""
    _install_fake_pymodbus(monkeypatch, _FakePymodbusClient)
    specs = [RegisterSpec("p", 0, "uint16", "kW")]
    src = ModbusSource(specs, host="10.0.0.7", port=5020, unit_id=9)
    assert src.name == "modbus-tcp://10.0.0.7:5020#9"
    assert src.read().source == "modbus-tcp://10.0.0.7:5020#9"


# --------------------------------------------------------------------------
# The source contract itself
# --------------------------------------------------------------------------


def test_the_protocols_refuse_to_be_inherited_from() -> None:
    """Subclassing a protocol and forgetting a method must fail loudly.

    Otwin's protocols are for isinstance checks and static typing. Someone who
    inherits anyway gets a working object whose methods do nothing unless the
    bodies say otherwise, which is exactly the class of bug that shows up as
    an empty twin rather than an exception.
    """

    class Inherited(Source):
        pass

    obj = Inherited()
    for call in (obj.read, obj.tags, obj.close):
        with pytest.raises(NotImplementedError, match="isinstance checks"):
            call()

    class InheritedTransport(RegisterTransport):
        pass

    transport = InheritedTransport()
    with pytest.raises(NotImplementedError, match="structural typing"):
        transport.read_registers(0, 1)
    with pytest.raises(NotImplementedError):
        transport.close()


def test_tag_and_unit_helpers_reject_what_they_cannot_describe() -> None:
    """A tag with no name is unaddressable; normalise() answers in one call."""
    with pytest.raises(ValueError, match="must be non-empty"):
        TagSpec("", "W", "nameless", "float32")

    assert normalise(1.5, "kW") == (pytest.approx(1500.0), "W")
    assert normalise(25.0, "degC") == (pytest.approx(298.15), "K")
    assert normalise(50.0, "%") == (pytest.approx(0.5), "1")


# --------------------------------------------------------------------------
# Dataset loader
# --------------------------------------------------------------------------


@pytest.fixture
def fake_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A registered dataset whose bytes are on disk and whose hash matches."""
    monkeypatch.setenv("OTWIN_DATA_DIR", str(tmp_path))
    path = tmp_path / "demo.csv"
    path.write_text("cycle,capacity\n1,2.0\n2,1.9\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(
        loader_mod.DATASETS,
        "demo",
        Dataset(
            name="demo",
            description="two discharge cycles",
            source="tests",
            license="public domain",
            sha256=digest,
            size_bytes=path.stat().st_size,
            citation="nobody (2026)",
            url="https://example.invalid/demo.zip",
        ),
    )
    return path


def test_verify_reports_a_missing_or_substituted_file(
    fake_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dataset that is not what it claims to be is an error, not a warning.

    Results computed from the wrong file are wrong in a way nothing downstream
    can detect, so both failure modes — absent and altered — have to stop the
    run and say which file to delete.
    """
    assert loader_mod.verify("demo") is True

    missing = fake_dataset.parent / "gone.csv"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        loader_mod.verify("demo", missing)

    fake_dataset.write_text("cycle,capacity\n1,2.0\n2,1.8\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        loader_mod.verify("demo")
    message = str(exc.value)
    assert "checksum mismatch" in message
    assert str(fake_dataset) in message  # says which file to delete


def test_load_verifies_before_reading_and_can_be_told_not_to(
    fake_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The checksum is checked before pandas ever sees the file.

    pandas is not an otwin dependency, so this drives ``load`` through a
    stand-in that records the path it was handed. What is under test is the
    order of operations: a corrupted file must be rejected *before* it is
    parsed, and ``verify_checksum=False`` must still read it, because that
    switch exists for people working on a file they know is not registered.
    """
    read: list[Path] = []
    fake_pandas = types.ModuleType("pandas")
    fake_pandas.read_csv = lambda path, **kw: read.append(Path(path)) or "frame"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pandas", fake_pandas)

    assert loader_mod.load("demo") == "frame"
    assert read == [fake_dataset]

    fake_dataset.write_text("cycle,capacity\n1,9.9\n", encoding="utf-8")
    read.clear()
    with pytest.raises(ValueError, match="checksum mismatch"):
        loader_mod.load("demo")
    assert read == []  # nothing was parsed

    assert loader_mod.load("demo", verify_checksum=False) == "frame"
    assert read == [fake_dataset]

    # A dataset that has not been downloaded says where to get it, and says so
    # without needing pandas at all.
    monkeypatch.delitem(sys.modules, "pandas")
    fake_dataset.unlink()
    with pytest.raises(FileNotFoundError) as exc:
        loader_mod.load("demo")
    assert "https://example.invalid/demo.zip" in str(exc.value)


# --------------------------------------------------------------------------
# SunSpec point codec and sentinels
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ptype", sorted(_TYPES))
def test_the_simulator_and_the_decoder_agree_on_every_sentinel(ptype: str) -> None:
    """Every not-implemented pattern the simulator writes must decode to None.

    SunSpec says "I do not have this measurement" with a per-type sentinel:
    all-ones for unsigned, most-negative for signed, zero for accumulators, a
    quiet NaN for float32. A decoder that misses one reports 0xFFFF as a state
    of charge of 65535 %, or -32768 as a cabinet temperature. Pairing the two
    tables in one test is what stops them drifting apart.
    """
    _, size, sentinel = _TYPES[ptype]
    point = PointDef(name="X", offset=0, ptype=ptype, size=size)
    words = _sentinel_words(point)
    assert len(words) == size
    assert all(0 <= w <= 0xFFFF for w in words)

    if sentinel is None and ptype != "float32":
        # count and pad have no sentinel: they decode to an ordinary number.
        assert decode_point(words, ptype) is not None
    else:
        assert decode_point(words, ptype) is None


def test_decode_point_rejects_a_block_that_is_the_wrong_size() -> None:
    """A point decoded from the wrong number of registers is not a value."""
    assert decode_point([0x0001], "uint32") is None
    assert decode_point([0x0001, 0x0002, 0x0003], "uint32") is None
    assert decode_point([0x0001, 0x0002], "uint32") == 65538.0
    assert decode_point([0x0001], "nosuchtype") is None

    # float32 is the type whose sentinel is a value rather than a bit pattern.
    quiet_nan = _sentinel_words(PointDef("X", 0, "float32", 2))
    assert decode_point(quiet_nan, "float32") is None
    real = [int(w) for w in struct.unpack(">HH", struct.pack(">f", -12.5))]
    assert decode_point(real, "float32") == pytest.approx(-12.5)


def test_the_simulator_cannot_encode_a_point_that_is_not_an_integer_field() -> None:
    """pin_raw is for numeric points; a string point has no raw integer."""
    with pytest.raises(ValueError, match="cannot encode point"):
        _encode_sunspec(1, PointDef("Mn", 2, "string", 16))

    # A negative value written to an unsigned point lands as two's complement,
    # which is how the not-implemented sentinel is spelled on the wire.
    assert _encode_sunspec(-1, PointDef("SoC", 11, "uint16", 1)) == [0xFFFF]
    assert _encode_sunspec(-2, PointDef("SoC_SF", 56, "sunssf", 1)) == [0xFFFE]


# --------------------------------------------------------------------------
# Model definitions
# --------------------------------------------------------------------------


def test_unknown_models_and_empty_definitions_resolve_to_none(tmp_path: Path) -> None:
    """A model with no definition is not an error; it is simply not decoded."""
    assert load_model_def(64_000) is None
    assert load_model_def(64_000, prefer_installed=False) is None

    # The official-JSON path: no such file, and a file with an empty group.
    assert sunspec_mod._parse_official(1, tmp_path) is None
    (tmp_path / "model_1.json").write_text(json.dumps({"group": {}}), encoding="utf-8")
    assert sunspec_mod._parse_official(1, tmp_path) is None

    assert ModelDef(1, "common", 4, ()).point("SoC") is None
    assert PointDef("WRmp", 5, "uint16", 1, units=None).deliverable is False
    assert PointDef("SoC", 11, "uint16", 1, units="percent").deliverable is True
    assert PointDef("Mn", 2, "string", 16).deliverable is False


def test_compare_model_defs_catches_a_transcription_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check that guards the hand-typed fallback table must actually fire.

    :data:`_BUILTIN_MODEL_DEFS` was transcribed by hand from the official
    SunSpec JSON, and a one-register offset error in it would shift every
    field after it while every other test still passed — the simulator and the
    source would share the mistake. So the comparison is checked against a
    definition that is wrong on purpose, in all three ways it can be wrong.
    """
    official = {
        "group": {
            "name": "battery",
            "points": [
                {"name": "ID", "type": "uint16", "size": 1},
                {"name": "L", "type": "uint16", "size": 1},
                {
                    "name": "SoC",
                    "type": "uint16",
                    "size": 1,
                    "sf": "SoC_SF",
                    "units": "%",
                },
                {"name": "SoC_SF", "type": "sunssf", "size": 1},
            ],
        }
    }
    (tmp_path / "model_999.json").write_text(json.dumps(official), encoding="utf-8")
    monkeypatch.setattr(sunspec_mod, "_pysunspec2_model_dir", lambda: tmp_path)
    monkeypatch.setitem(
        _BUILTIN_MODEL_DEFS,
        999,
        (
            "battery",
            9,
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 3 SoC uint16 1 SoC_SF %; "
            "3 SoC_SF sunssf 1 - -; 2 Ghost uint16 1 - -",
        ),
    )

    problems = compare_model_defs(999)
    assert any("fixed_len 9 != official 4" in p for p in problems)
    assert any("Ghost is not in the official definition" in p for p in problems)
    assert any("999.SoC: offset 3 != official 2" in p for p in problems)

    # A model the official set does not define at all is reported as such
    # rather than passing silently.
    monkeypatch.setitem(_BUILTIN_MODEL_DEFS, 998, ("ghost", 2, "0 ID uint16 1 - -"))
    assert compare_model_defs(998) == [
        f"model 998: no official definition found in {tmp_path}"
    ]

    # And without pysunspec2 there is nothing to compare against, which the
    # caller has to be told rather than reading an empty list as success.
    monkeypatch.setattr(sunspec_mod, "_pysunspec2_model_dir", lambda: None)
    assert compare_model_defs(802) == [
        "pysunspec2 is not installed; nothing to compare against"
    ]


def test_a_fallback_definition_drives_a_full_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The built-in table's packed format, end to end on a device image.

    This exercises the parts of the format the shipped models do not use: a
    literal scale-factor exponent rather than a named ``sunssf`` register, a
    unit that cannot be mapped to an SI quantity, and a stray empty record.
    A point whose unit is unmappable must be dropped and reported, never
    delivered unconverted — an unchecked unit is the one thing this package
    refuses to pass downstream.
    """
    monkeypatch.setitem(
        _BUILTIN_MODEL_DEFS,
        999,
        (
            "vendor_meter",
            4,
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 W int16 1 -2 kW; "
            "3 Flow uint16 1 - furlongs; ;",
        ),
    )
    sim = _chain([(999, 2, {2: [12345], 3: [7]})])
    src = SunSpecSource(transport=sim, name="vendor")

    assert [m.model_id for m in src.models] == [999]
    assert src.unmapped_points == [(999, "Flow", "furlongs")]

    sample = src.read()
    # 12345 with a literal exponent of -2 is 123.45 kW, i.e. 123450 W.
    assert sample.values["m999.W"] == pytest.approx(123_450.0)
    assert "m999.Flow" not in sample.values
    assert [t.name for t in src.tags()] == ["m999.W"]
    assert src.tags()[0].unit == "W"


# --------------------------------------------------------------------------
# SunSpec discovery failures
# --------------------------------------------------------------------------


def test_discovery_survives_a_base_address_that_refuses_reads() -> None:
    """A device that rejects 40000 must still be found at 50000.

    Some gateways answer illegal-data-address rather than returning zeros for
    an unmapped range, so the probe has to treat an exception as "not here"
    and keep going, not as a fatal error.
    """
    sim = SunSpecSimulator(soc=0.44, base_address=50000)
    sim.inject_timeout(40000, 2)
    src = SunSpecSource(transport=sim)

    assert src.base_address == 50000
    assert src.soc() == pytest.approx(0.44, abs=1e-6)


def test_a_corrupt_model_chain_is_reported_rather_than_walked() -> None:
    """An implausible length would otherwise walk the address space forever."""
    sim = _chain([(802, 5000, {})])
    with pytest.raises(TransportError, match="implausible length 5000"):
        SunSpecSource(transport=sim)

    # A chain that runs off the end of the register image reads zeros, which
    # look like model 0 of length 0 — the walk has to stop somewhere, and the
    # 128-model cap is what stops it.
    blank = ModbusSimulator(name="blank://local")
    blank.set_raw(40000, list(SUNSPEC_IDENTIFIER))
    src = SunSpecSource(transport=blank)
    assert len(src.models) == 128
    assert {m.model_id for m in src.models} == {0}
    assert src.read().values == {}  # nothing decodable, and nothing invented


def test_a_model_this_library_does_not_know_is_carried_but_not_decoded() -> None:
    """An unknown model must not stop the models around it being read.

    Vendors publish private models in the same chain as the standard ones.
    Discovery has to record them, skip them, and go on to the 802 behind them.
    """
    sim = _chain(
        [
            (64_000, 4, {2: [1, 2, 3, 4]}),
            (713, 7, {2: [2000], 4: [8542], 7: [3], 8: [0x10000 - 2]}),
        ]
    )
    src = SunSpecSource(transport=sim)

    by_id = {m.model_id: m for m in src.models}
    assert sorted(by_id) == [713, 64_000]
    assert by_id[64_000].definition is None
    assert by_id[64_000].length == 4
    assert src.unmapped_points == []  # an unknown model has no unmapped units

    sample = src.read()
    assert not [k for k in sample.values if k.startswith("m64000")]
    assert sample.values["m713.SoC"] == pytest.approx(0.8542, abs=1e-9)
    assert sample.values["m713.WHRtg"] == pytest.approx(2_000_000.0)
    assert src.device_info == {}  # no common model in this chain


def test_a_truncated_common_model_yields_the_fields_it_does_publish() -> None:
    """A device whose L is shorter than the definition is read to its own end.

    Older firmware publishes a common model with fewer registers than the
    current definition. Reading past the declared length would decode whatever
    the next model has at that address as a serial number.
    """
    manufacturer = encode_value("Otwin", "string", 16)
    sim = _chain([(1, 20, {2: manufacturer})])
    src = SunSpecSource(transport=sim)

    assert src.device_info == {"manufacturer": "Otwin"}
    assert "serial" not in src.device_info  # SN sits past the declared end
    assert src.models[0].total_registers == 22


def test_a_common_model_that_stops_answering_does_not_abort_discovery() -> None:
    """Device identity is useful, not essential; losing it must not be fatal."""
    sim = SunSpecSimulator(soc=0.61)
    sim.inject_timeout(sim.address_of(1) + 10, 2)
    src = SunSpecSource(transport=sim)

    assert src.device_info == {}
    assert src.last_error is not None
    assert src.soc() == pytest.approx(0.61, abs=1e-6)


def test_restricting_the_models_leaves_the_rest_undecoded() -> None:
    """A twin that only wants the battery should not pay for the whole chain."""
    sim = SunSpecSimulator(soc=0.5)
    src = SunSpecSource(transport=sim, models={802}, discover_now=False)

    assert src._models is None
    assert repr(src) == f"SunSpecSource('{sim.name}', not discovered, base=None)"

    # Touching .models runs discovery, which is what makes discover_now=False
    # usable from a constructor that must not do I/O.
    assert [m.model_id for m in src.models] == [1, 802, 713, 701]
    assert [m.model_id for m in src.models if m.definition is not None] == [802]
    assert src.device_info == {}  # the common model was not decoded either
    assert src.unmapped_points == []

    sample = src.read()
    assert {k.split(".")[0] for k in sample.values} == {"m802"}
    assert {t.name.split(".")[0] for t in src.tags()} == {"m802"}
    assert "4 models" in repr(src) and "base=40000" in repr(src)


def test_unmappable_units_are_reported_rather_than_delivered() -> None:
    """Model 704 publishes ramp rates in %Max/Sec, which is not an SI quantity.

    The point is dropped and recorded, because passing a number on under a
    unit nothing downstream can convert is how a twin ends up off by a factor
    nobody can find.
    """
    sim = SunSpecSimulator(soc=0.5, models=(1, 704))
    src = SunSpecSource(transport=sim)

    unmapped = {name: unit for _, name, unit in src.unmapped_points}
    assert unmapped.get("WRmp") == "%Max/Sec"
    assert all(model == 704 for model, _, _ in src.unmapped_points)
    assert "m704.WRmp" not in src.read().values
    assert "m704.WRmp" not in {t.name for t in src.tags()}

    # The model is otherwise decoded: its points are all not-implemented in
    # this simulated device, which is 'bad', not a crash and not a zero.
    sample = src.read()
    assert sample.quality["m704.WSet"] == "bad"
    assert math.isnan(sample.values["m704.WSet"])


def test_a_model_published_twice_becomes_two_independent_tag_sets() -> None:
    """Devices legitimately publish one model per string, bank or meter.

    Two 713s at different addresses are two different measurements. Collapsing
    them onto one tag name would silently hide half the plant, and reporting
    the second one's address as the first's would make the manifest lie.
    """
    sim = _chain(
        [
            (713, 7, {2: [2000], 4: [8542], 7: [3], 8: [0x10000 - 2]}),
            (713, 7, {2: [2000], 4: [3100], 7: [3], 8: [0x10000 - 2]}),
        ]
    )
    src = SunSpecSource(transport=sim)

    assert [(m.model_id, m.index, m.prefix) for m in src.models] == [
        (713, 0, "m713"),
        (713, 1, "m713#1"),
    ]
    sample = src.read()
    assert sample.values["m713.SoC"] == pytest.approx(0.8542, abs=1e-9)
    assert sample.values["m713#1.SoC"] == pytest.approx(0.31, abs=1e-9)

    addresses = {t.name: t.address for t in src.tags() if t.sunspec_point == "SoC"}
    assert addresses["m713.SoC"] == 40006
    assert addresses["m713#1.SoC"] == 40015


def test_a_scale_factor_at_its_legal_extremes_still_decodes() -> None:
    """sunssf is a base-10 exponent, and both ends of its range must survive.

    IEEE 1547 devices use exponents from about -10 to +10; the raw register is
    unchanged when only the scale factor moves, so the delivered value has to
    move by exactly the decade the device asked for.
    """
    sim = SunSpecSimulator(soc=0.5)
    src = SunSpecSource(transport=sim)
    raw = sim.get_raw(sim.address_of(802, "SoC"), 1)[0]
    assert raw == 5000

    sim.pin_raw(802, "SoC_SF", 10)
    high = src.read()
    assert high.quality["m802.SoC"] == "good"
    assert high.values["m802.SoC"] == pytest.approx(raw * 1e10 * 0.01)

    sim.pin_raw(802, "SoC_SF", -10)
    low = src.read()
    assert low.quality["m802.SoC"] == "good"
    assert low.values["m802.SoC"] == pytest.approx(raw * 1e-10 * 0.01)


# --------------------------------------------------------------------------
# Known defects, pinned so that fixing them is visible
# --------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: SunSpecSource.read() propagates OverflowError when a sunssf "
        "register holds a large positive exponent. _scale() computes "
        "10.0**exponent unguarded and outside the per-model try block, so one "
        "corrupt register loses the whole sample, every other model included. "
        "Left unfixed deliberately; remove this marker with the fix."
    ),
)
def test_a_corrupt_scale_factor_register_must_not_take_the_sample_down() -> None:
    """read() promises never to raise for a wire-level problem. It does.

    A ``sunssf`` register holding 400 is out of the SunSpec range and can only
    be corruption or a mis-mapped address — which is exactly the case the
    quality ladder exists for. The point should degrade to 'bad' or 'stale'
    and the rest of the chain should still be read.
    """
    sim = SunSpecSimulator(soc=0.62)
    src = SunSpecSource(transport=sim)
    assert src.read().quality["m802.SoC"] == "good"

    sim.pin_raw(802, "SoC_SF", 400)
    sample = src.read()  # currently raises OverflowError

    assert sample.quality["m802.SoC"] in ("stale", "bad")
    assert sample.quality["m713.SoC"] == "good"  # the other models are innocent


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: SunSpecSource.soc() picks between models 713 and 802 on "
        "publication alone and then raises TransportError if the chosen one is "
        "unreadable, instead of falling back to the model that is answering. "
        "Left unfixed deliberately; remove this marker with the fix."
    ),
)
def test_soc_falls_back_to_802_when_713_stops_answering() -> None:
    """The fallback exists for exactly this: one of two views going dark.

    713 is the grid-interface view and 802 the BMS view of the same battery.
    When the 713 block stops answering and 802 is reading cleanly, a twin that
    loses its state of charge altogether has thrown away good data.
    """
    sim = SunSpecSimulator(soc=0.62)
    src = SunSpecSource(transport=sim)
    sim.inject_timeout_for_model(713)

    sample = src.read()
    assert sample.quality["m713.SoC"] == "bad"
    assert sample.quality["m802.SoC"] == "good"

    assert src.soc(sample) == pytest.approx(0.62, abs=1e-6)


# --------------------------------------------------------------------------
# SunSpecSource construction, scaling and soc()
# --------------------------------------------------------------------------


def test_sunspec_source_rejects_impossible_construction() -> None:
    """Neither a device nor a transport is not a source."""
    with pytest.raises(ValueError, match="max_registers_per_read must be 1..125"):
        SunSpecSource(transport=SunSpecSimulator(), max_registers_per_read=126)
    with pytest.raises(ValueError, match="give either host="):
        SunSpecSource()
    with pytest.raises(ValueError, match="prefer must be"):
        SunSpecSource(host="10.0.0.7", prefer="dnp3")


def test_a_live_sunspec_source_names_its_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Built from host=, the source identifies the device it is talking to."""
    module = types.SimpleNamespace(ModbusClientTCP=_FakeSunSpecClient)
    monkeypatch.setattr(sunspec_mod, "_import_pysunspec2_modbus", lambda: module)
    src = SunSpecSource(host="10.0.0.7", port=5020, unit_id=4, discover_now=False)
    assert src.name == "sunspec-tcp://10.0.0.7:5020#4"
    assert src.base_address is None


def test_scale_factors_resolve_from_a_register_a_literal_or_nothing() -> None:
    """The three forms a SunSpec scale factor comes in, including the trap.

    A ``sunssf`` register holding its own not-implemented sentinel would give
    an exponent of -32768, i.e. a multiplier of 10**-32768, which is zero. It
    has to be read as "no scaling" instead.
    """
    src = SunSpecSource(transport=SunSpecSimulator(soc=0.5))

    assert src._scale(PointDef("NCyc", 14, "uint32", 2), {}) == 1.0
    assert src._scale(PointDef("W", 2, "int16", 1, sf=-2), {}) == pytest.approx(0.01)
    assert src._scale(PointDef("W", 2, "int16", 1, sf=3), {}) == pytest.approx(1000.0)
    named = PointDef("SoC", 11, "uint16", 1, sf="SoC_SF")
    assert src._scale(named, {"SoC_SF": -2.0}) == pytest.approx(0.01)
    assert src._scale(named, {"SoC_SF": None}) == 1.0
    assert src._scale(named, {}) == 1.0


def test_soc_reports_an_unreadable_point_rather_than_a_number() -> None:
    """With no previous value and both models dead, soc() must not invent one."""
    sim = SunSpecSimulator(soc=0.5)
    src = SunSpecSource(transport=sim)
    sim.inject_timeout_for_model(713)
    sim.inject_timeout_for_model(802)

    with pytest.raises(TransportError, match="not readable"):
        src.soc()

    # Once a good value exists the same failure is stale rather than fatal:
    # an SoC from ten seconds ago is still the best information available.
    sim.clear_faults()
    assert src.soc() == pytest.approx(0.5, abs=1e-6)
    sim.inject_timeout_for_model(713)
    sim.inject_timeout_for_model(802)
    assert src.soc() == pytest.approx(0.5, abs=1e-6)
    assert src.read().quality["m713.SoC"] == "stale"


def test_soc_without_unit_normalisation_still_returns_a_fraction() -> None:
    """normalise_units=False delivers percent, and soc() has to know that.

    Turning normalisation off is for someone comparing against a vendor tool
    that shows raw engineering units. It must not turn a state of charge of
    85.42 % into the number 85.42 in the twin.
    """
    sim = SunSpecSimulator(soc=0.8542)
    src = SunSpecSource(transport=sim, normalise_units=False)

    sample = src.read()
    assert sample.values["m713.SoC"] == pytest.approx(85.42, abs=1e-6)
    assert src.soc(sample) == pytest.approx(0.8542, abs=1e-6)
    assert src.tags()[0].unit == src.tags()[0].raw_unit

    # And the out-of-range guard still applies on that path.
    sim.inject_out_of_range(713, "SoC", 45000)
    sim.inject_out_of_range(802, "SoC", 45000)
    with pytest.raises(ValueError, match="scale-factor"):
        src.soc()


def test_sunspec_source_is_a_context_manager_and_describes_itself() -> None:
    """Closing releases the link exactly once, and repr says what was found."""
    sim = SunSpecSimulator(soc=0.5)
    with SunSpecSource(transport=sim, name="bess-1") as src:
        assert src.soc() == pytest.approx(0.5, abs=1e-6)
        assert repr(src) == "SunSpecSource('bess-1', 4 models, base=40000)"

    with pytest.raises(SimulatedFault, match="transport is closed"):
        sim.read_registers(40000, 2)
    src.close()  # idempotent


# --------------------------------------------------------------------------
# The pysunspec2 transport shim
# --------------------------------------------------------------------------


def test_pysunspec2_transport_decodes_both_result_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pysunspec2 returns bytes; a client that returns registers also works."""
    transport = _fake_sunspec_transport(monkeypatch)
    client = transport._client
    assert transport.name == "sunspec-tcp://10.0.0.9:5020#7"
    assert client.slave_id == 7 and client.ipport == 5020

    client.result = struct.pack(">HH", 0x1234, 0xABCD)
    assert transport.read_registers(40000, 2) == [0x1234, 0xABCD]
    assert client.calls == [(40000, 2, 3)]
    assert client.connects == 1

    # Function 4, and no second connect: the link is opened once and reused.
    assert transport.read_registers(40000, 2, "input") == [0x1234, 0xABCD]
    assert client.calls[-1] == (40000, 2, 4)
    assert client.connects == 1

    client.result = [0x0001, 0x0002]
    assert transport.read_registers(0, 2) == [1, 2]


def test_pysunspec2_transport_turns_every_wire_failure_into_a_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short frames in either shape, and a driver exception, all degrade."""
    transport = _fake_sunspec_transport(monkeypatch)
    client = transport._client

    client.result = b"\x12\x34"  # two bytes where four were asked for
    with pytest.raises(TransportError, match="wanted 4 bytes, got 2"):
        transport.read_registers(40000, 2)

    client.result = [0x0001]
    with pytest.raises(TransportError, match="short frame"):
        transport.read_registers(40000, 2)

    client.result = None
    with pytest.raises(TransportError, match="short frame"):
        transport.read_registers(40000, 2)

    client.raise_on_read = OSError("connection reset by peer")
    with pytest.raises(TransportError, match="read at 40000\\+2 failed") as exc:
        transport.read_registers(40000, 2)
    assert isinstance(exc.value.__cause__, OSError)

    # The failure dropped the connection flag, so the next read reconnects
    # rather than writing into a dead socket.
    client.raise_on_read = None
    client.result = b"\x00\x01\x00\x02"
    assert transport.read_registers(40000, 2) == [1, 2]
    assert client.connects == 2

    client.raise_on_disconnect = True
    transport.close()  # a failing teardown must not raise
    transport.close()
    assert client.disconnects == 2


def test_pysunspec2_client_signature_is_the_one_the_shim_calls() -> None:
    """The shim's call shape is checked against the real package when present."""
    modbus = pytest.importorskip(
        "sunspec2.modbus.modbus", reason="live pysunspec2 signature check"
    )
    import inspect

    init = inspect.signature(modbus.ModbusClientTCP.__init__).parameters
    assert {"slave_id", "ipaddr", "ipport", "timeout"} <= set(init)
    read = inspect.signature(modbus.ModbusClientTCP.read).parameters
    assert {"addr", "count", "op"} <= set(read)
    assert hasattr(modbus.ModbusClientTCP, "disconnect")


# --------------------------------------------------------------------------
# Simulator behaviour and fault injection
# --------------------------------------------------------------------------


def test_simulator_rejects_requests_a_device_would_reject() -> None:
    """Register banks, word counts and register types, as a device sees them."""
    sim = ModbusSimulator([RegisterSpec("p", 0, "uint16", "kW")])

    with pytest.raises(ValueError, match="must be 'holding' or 'input'"):
        sim.read_registers(0, 1, "coil")
    with pytest.raises(ValueError, match="must be 'holding' or 'input'"):
        sim.get_raw(0, 1, "discrete")
    with pytest.raises(ValueError, match="count must be >= 1"):
        sim.read_registers(0, 0)
    with pytest.raises(ValueError, match="not a 16-bit word"):
        sim.set_raw(0, [0x10000])
    with pytest.raises(ValueError, match="word_order must be"):
        ModbusSimulator(word_order="mixed")
    with pytest.raises(KeyError, match="not in this simulator's register map"):
        sim.set_value("q", 1.0)

    assert "ModbusSimulator" in repr(sim) and "reads=" in repr(sim)


def test_strict_addresses_reproduces_illegal_data_address() -> None:
    """Reading past a device's map is an exception response, not zeros.

    Off by default, because most maps are sparse and most tests do not care.
    On, it catches a register map whose addresses are one out — which
    otherwise reads as a plausible zero.
    """
    specs = [RegisterSpec("p", 100, "uint16", "kW")]
    sim = ModbusSimulator(specs, strict_addresses=True)
    sim.set_value("p", 42.0)

    assert sim.read_registers(100, 1) == [42]
    with pytest.raises(SimulatedFault, match="illegal data address"):
        sim.read_registers(99, 2)

    src = ModbusSource([RegisterSpec("p", 99, "uint16", "kW")], transport=sim)
    sample = src.read()
    assert sample.quality["p"] == "bad"
    assert isinstance(src.last_error, SimulatedFault)


def test_an_injected_fault_is_confined_to_its_own_register_type() -> None:
    """A failing holding-register range must not condemn the input registers."""
    sim = ModbusSimulator()
    sim.set_raw(0, [7], "input")
    sim.inject_timeout(0, 4, "holding")

    assert sim.faults == [("holding", 0, 4)]
    assert sim.read_registers(0, 1, "input") == [7]
    with pytest.raises(SimulatedFault, match="simulated timeout"):
        sim.read_registers(0, 1, "holding")

    sim.clear_faults()
    assert sim.faults == []
    assert sim.read_registers(0, 1, "holding") == [0]


def test_modbus_simulator_freeze_records_the_value_but_not_the_registers() -> None:
    """The quiet failure: a register that reads cleanly and stops moving.

    Nothing raises and quality stays 'good', because nothing is wrong from the
    connector's point of view. Detecting it belongs to condition monitoring
    downstream, so the simulator has to be able to produce it.
    """
    specs = [RegisterSpec("soc", 0, "uint16", "%", scale=0.1)]
    sim = ModbusSimulator(specs)
    sim.set_value("soc", 62.0)
    src = ModbusSource(specs, transport=sim)

    sim.freeze("soc")
    sim.set_value("soc", 20.0)
    assert sim.get_value("soc") == 20.0  # the device knows
    assert src.read().values["soc"] == pytest.approx(0.62)  # the wire does not
    assert src.read().quality["soc"] == "good"

    sim.unfreeze("soc")
    assert src.read().values["soc"] == pytest.approx(0.20)


def test_modbus_simulator_injects_a_raw_value_no_scale_factor_explains() -> None:
    """A mis-set vendor scale factor, seen from outside: a wrong big number."""
    specs = [
        RegisterSpec("soc", 0, "uint16", "%", scale=0.1),
        RegisterSpec("serial", 10, "string", "1", count=4),
    ]
    sim = ModbusSimulator(specs)
    sim.set_value("soc", 62.0)
    src = ModbusSource(specs, transport=sim)
    assert src.read().values["soc"] == pytest.approx(0.62)

    sim.inject_out_of_range("soc", 45000)  # 4500 % once scale 0.1 applies
    assert src.read().values["soc"] == pytest.approx(45.0)  # 4500 % as a fraction

    with pytest.raises(TypeError, match="for numeric tags"):
        sim.inject_out_of_range("serial", 1)
    with pytest.raises(KeyError, match="not in this simulator's register map"):
        sim.freeze("nope")


def test_sunspec_simulator_rejects_states_a_battery_cannot_be_in() -> None:
    """Nonsense goes in through inject_out_of_range, never through the state."""
    with pytest.raises(ValueError, match="does not publish models"):
        SunSpecSimulator(models=(1, 999))

    sim = SunSpecSimulator(soc=0.5)
    with pytest.raises(ValueError, match=r"fraction in \[0, 1\]"):
        sim.soc = 1.4
    with pytest.raises(ValueError, match="does not run backwards"):
        sim.advance(-60.0)

    with pytest.raises(KeyError, match="does not publish model 705"):
        sim.address_of(705)
    with pytest.raises(KeyError, match="has no point 'Nope'"):
        sim.address_of(802, "Nope")
    with pytest.raises(KeyError, match="does not publish model 705"):
        sim.inject_timeout_for_model(705)
    with pytest.raises(KeyError, match="does not publish model 705"):
        sim.pin_raw(705, "SoC", 1)
    with pytest.raises(KeyError, match="has no point 'Nope'"):
        sim.pin_raw(802, "Nope", 1)

    assert sim.published_models == [1, 802, 713, 701]
    assert SunSpecSimulator(soc=0.5, models=(802,)).published_models == [802]


def test_a_pinned_register_survives_the_device_changing_state() -> None:
    """A stuck register stays stuck when everything around it moves.

    The simulator rebuilds its whole image whenever the state changes, so a
    pinned point that did not survive the rebuild would make every
    not-implemented test accidentally time-dependent.
    """
    sim = SunSpecSimulator(soc=0.5)
    src = SunSpecSource(transport=sim)
    sim.pin_raw(802, "SoC", 0xFFFF)  # not implemented
    assert src.read().quality["m802.SoC"] == "bad"

    sim.soc = 0.75  # full rebuild
    sample = src.read()
    assert sample.quality["m802.SoC"] == "bad"
    assert sample.values["m713.SoC"] == pytest.approx(0.75, abs=1e-6)

    sim.unfreeze(802, "SoC")
    assert src.read().values["m802.SoC"] == pytest.approx(0.75, abs=1e-6)


def test_auto_advance_drifts_the_device_on_the_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device that keeps discharging between reads, without a sleep.

    ``auto_advance`` is off by default so tests are deterministic; with the
    clock injected it is deterministic anyway, which is the only way to test
    a rate as a rate rather than as an approximation.
    """
    clock = _Clock()
    monkeypatch.setattr(sunspec_mod.time, "time", clock.time)

    import otwin.io.simulator as simulator_mod

    monkeypatch.setattr(simulator_mod.time, "time", clock.time)

    sim = SunSpecSimulator(
        soc=0.80, capacity_wh=2_000_000, power_w=500_000, auto_advance=True
    )
    src = SunSpecSource(transport=sim)
    assert src.soc() == pytest.approx(0.80, abs=1e-4)

    clock.tick(1800.0)  # half an hour at 500 kW out of 2 MWh is 12.5 %
    assert src.soc() == pytest.approx(0.675, abs=1e-4)

    # The drift rate is a parameter, not a hard-coded consequence of power.
    slow = SunSpecSimulator(soc=0.50, drift_per_hour=-0.02, auto_advance=True)
    slow_src = SunSpecSource(transport=slow)
    clock.tick(3600.0)
    assert slow_src.soc() == pytest.approx(0.48, abs=1e-4)


def test_a_model_the_simulator_has_no_physics_for_is_still_well_formed() -> None:
    """Publishing 803 gives a correct, entirely not-implemented model.

    The chain must stay walkable — right ID, right length, sentinels
    throughout — because that is what a real device does for a model it
    supports structurally but has no data for.
    """
    sim = SunSpecSimulator(soc=0.5, models=(1, 803, 713))
    src = SunSpecSource(transport=sim)

    assert [m.model_id for m in src.models] == [1, 803, 713]
    definition = load_model_def(803)
    assert definition is not None
    assert sim.get_raw(sim.address_of(803), 2) == [803, definition.fixed_len - 2]

    sample = src.read()
    bank = {k: v for k, v in sample.quality.items() if k.startswith("m803.")}
    assert bank and set(bank.values()) == {"bad"}
    assert sample.values["m713.SoC"] == pytest.approx(0.5, abs=1e-6)
