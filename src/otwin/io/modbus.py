"""Raw Modbus TCP and RTU.

Modbus is the lowest common denominator of the storage industry: every PCS,
BMS and meter speaks it, and none of them agree on what the registers mean.
So the two problems are separated. :class:`RegisterSpec` says what a register
*is* — address, width, scale, unit — and loads from YAML or JSON, so
describing a new PCS does not require writing Python. :class:`ModbusSource`
does the reading, batching, decoding and degradation.

**Word order.** Modbus registers are big-endian on the wire; a 32-bit value
occupies two of them and the standard says nothing about which comes first.
Roughly half the devices in the field send the high word first (ABCD) and half
send it last (CDAB). Getting it wrong yields a plausible wrong number rather
than an error, so ``word_order`` is a visible parameter here, not a buried
assumption. Byte order *within* a register is fixed by the wire format and is
deliberately not configurable.

**Addressing.** ``RegisterSpec.address`` is the zero-based protocol address
that goes on the wire, not 4xxxx/3xxxx data-model notation: holding register
40001 in a vendor manual is address 0 here. No offset arithmetic is applied
anywhere. When a value comes back one register out, check this first.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import struct
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .source import (
    MissingDependencyError,
    QualityTracker,
    RegisterTransport,
    Sample,
    TagSpec,
    TransportError,
    si_unit,
    to_si,
)

__all__ = [
    "RegisterSpec",
    "ModbusSource",
    "PymodbusTransport",
    "decode_registers",
    "encode_value",
    "load_register_map",
    "MODBUS_MAX_REGISTERS_PER_READ",
    "DTYPE_REGISTERS",
]

#: Largest number of registers one Modbus read may return (the function 3/4
#: response is a byte-counted frame with a single-byte count).
MODBUS_MAX_REGISTERS_PER_READ = 125

#: Register width of each supported wire type. ``"string"`` is variable and
#: takes its width from :attr:`RegisterSpec.count`.
DTYPE_REGISTERS: dict[str, int] = {
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
}

_REGISTER_TYPES = ("holding", "input")
_STRUCT_FORMATS = {
    "uint16": ">H",
    "int16": ">h",
    "uint32": ">I",
    "int32": ">i",
    "float32": ">f",
}

WordOrder = Literal["big", "little"]


# --------------------------------------------------------------------------
# Codec
# --------------------------------------------------------------------------


def _words_to_bytes(words: Sequence[int], word_order: str) -> bytes:
    if word_order not in ("big", "little"):
        raise ValueError(f"word_order must be 'big' or 'little', got {word_order!r}")
    ordered = list(words) if word_order == "big" else list(reversed(list(words)))
    out = bytearray()
    for w in ordered:
        if not 0 <= int(w) <= 0xFFFF:
            raise ValueError(f"register value {w!r} is not a 16-bit word")
        out += struct.pack(">H", int(w))
    return bytes(out)


def decode_registers(
    words: Sequence[int], dtype: str, word_order: str = "big"
) -> float | str:
    """Decode raw registers into a value.

    Args:
        words: Registers as the transport returned them, in wire order.
        dtype: A key of :data:`DTYPE_REGISTERS`, or ``"string"``.
        word_order: ``"big"`` = high word first (ABCD), ``"little"`` = low
            word first (CDAB). Ignored for single-register types and for
            strings, whose character order is fixed.

    Returns:
        A float, or a ``str`` for ``"string"`` (NUL- and space-trimmed,
        decoded as latin-1 so no byte can fail).

    Raises:
        ValueError: On an unknown dtype or the wrong number of registers.

    Example:
        >>> decode_registers([0x4248, 0x0000], "float32", "big")
        50.0
        >>> decode_registers([0x0000, 0x4248], "float32", "little")
        50.0
    """
    if dtype == "string":
        return _words_to_bytes(words, "big").decode("latin-1").split("\x00", 1)[0].strip()
    if dtype not in DTYPE_REGISTERS:
        raise ValueError(
            f"unknown dtype {dtype!r}; expected one of {sorted(DTYPE_REGISTERS)} or 'string'"
        )
    need = DTYPE_REGISTERS[dtype]
    if len(words) != need:
        raise ValueError(f"{dtype} needs {need} register(s), got {len(words)}")
    raw = _words_to_bytes(words, word_order)
    return float(struct.unpack(_STRUCT_FORMATS[dtype], raw)[0])


def encode_value(
    value: float | str, dtype: str, count: int, word_order: str = "big"
) -> list[int]:
    """Encode a value into registers — the inverse of :func:`decode_registers`.

    Used by the simulators to build a register image, and by anyone writing a
    round-trip test against real hardware.
    """
    if dtype == "string":
        data = str(value).encode("latin-1")[: count * 2].ljust(count * 2, b"\x00")
        return [
            int(struct.unpack(">H", data[i : i + 2])[0]) for i in range(0, len(data), 2)
        ]
    if dtype not in DTYPE_REGISTERS:
        raise ValueError(f"unknown dtype {dtype!r}")
    payload = float(value) if dtype == "float32" else int(value)
    raw = struct.pack(_STRUCT_FORMATS[dtype], payload)
    words = [int(struct.unpack(">H", raw[i : i + 2])[0]) for i in range(0, len(raw), 2)]
    return words if word_order == "big" else list(reversed(words))


# --------------------------------------------------------------------------
# Register map
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterSpec:
    """One tag's worth of Modbus registers.

    Attributes:
        name: Tag name, unique within a map.
        address: Zero-based protocol address of the first register.
        dtype: A key of :data:`DTYPE_REGISTERS`, or ``"string"``.
        unit: Unit as the *device* reports it, e.g. ``"kW"``. Mandatory, and
            validated at construction. Use ``"1"`` for dimensionless counts.
        count: Registers occupied. Inferred from ``dtype`` for numeric types;
            required for ``"string"``.
        scale: Vendor fixed-point multiplier applied before unit
            normalisation, e.g. ``0.1`` for a register reporting tenths.
        register_type: ``"holding"`` (function 3) or ``"input"`` (function 4).
        description: What the tag means; ends up in :class:`TagSpec`.

    Raises:
        ValueError: On an unknown dtype, a count contradicting the dtype, a
            negative address or an unknown register type.
        UnknownUnitError: On an unrecognised unit.
    """

    name: str
    address: int
    dtype: str
    unit: str
    count: int = 0
    scale: float = 1.0
    register_type: str = "holding"
    description: str = ""

    def __post_init__(self) -> None:
        if self.dtype != "string" and self.dtype not in DTYPE_REGISTERS:
            raise ValueError(
                f"{self.name}: unknown dtype {self.dtype!r}; expected one of "
                f"{sorted(DTYPE_REGISTERS)} or 'string'"
            )
        if self.dtype == "string":
            if self.count < 1:
                raise ValueError(
                    f"{self.name}: string dtype needs an explicit count >= 1"
                )
        else:
            need = DTYPE_REGISTERS[self.dtype]
            if self.count == 0:
                object.__setattr__(self, "count", need)
            elif self.count != need:
                raise ValueError(
                    f"{self.name}: dtype {self.dtype} occupies {need} register(s) "
                    f"but count={self.count} was given"
                )
        if self.address < 0:
            raise ValueError(f"{self.name}: address must be >= 0, got {self.address}")
        if self.register_type not in _REGISTER_TYPES:
            raise ValueError(
                f"{self.name}: register_type must be one of {_REGISTER_TYPES}, "
                f"got {self.register_type!r}"
            )
        si_unit(self.unit)

    @property
    def end(self) -> int:
        """One past the last register address this spec covers."""
        return self.address + self.count


def load_register_map(path: str | Path) -> tuple[list[RegisterSpec], dict[str, Any]]:
    """Load a register map from a YAML or JSON file.

    The format is a mapping of optional connection defaults plus a
    ``registers`` list; a bare list of register entries is also accepted, in
    which case the options dict comes back empty::

        unit_id: 1
        word_order: little
        registers:
          - {name: p_dc, address: 100, dtype: float32, unit: kW}
          - {name: soc, address: 110, dtype: uint16, scale: 0.1, unit: "%"}

    Returns:
        ``(specs, options)``, where ``options`` may hold ``host``, ``port``,
        ``device``, ``baudrate``, ``unit_id``, ``word_order``,
        ``max_registers_per_read``, ``max_gap``, ``name`` and so on.

    Raises:
        ImportError: For a YAML file when PyYAML is not installed.
        ValueError: On a malformed file, a duplicate tag name, or an entry
            :class:`RegisterSpec` rejects.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            yaml = importlib.import_module("yaml")
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError(
                "reading a YAML register map requires PyYAML: pip install pyyaml. "
                "A JSON register map needs no extra dependency."
            ) from exc
        doc = yaml.safe_load(text)
    else:
        doc = json.loads(text)

    if isinstance(doc, list):
        entries, options = doc, {}
    elif isinstance(doc, dict):
        if "registers" not in doc:
            raise ValueError(f"{p}: mapping form needs a 'registers' key")
        entries = doc["registers"]
        options = {k: v for k, v in doc.items() if k != "registers"}
    else:
        raise ValueError(f"{p}: expected a mapping or a list at the top level")
    if not isinstance(entries, list):
        raise ValueError(f"{p}: 'registers' must be a list")

    specs: list[RegisterSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{p}: register entry {i} is not a mapping")
        try:
            spec = RegisterSpec(**entry)
        except TypeError as exc:
            raise ValueError(
                f"{p}: register entry {i} ({entry.get('name')!r}): {exc}"
            ) from exc
        if spec.name in seen:
            raise ValueError(f"{p}: duplicate tag name {spec.name!r}")
        seen.add(spec.name)
        specs.append(spec)
    return specs, options


@dataclass(frozen=True)
class _Batch:
    """A contiguous run of registers fetched in one request."""

    register_type: str
    address: int
    count: int
    specs: tuple[RegisterSpec, ...]


def _plan_batches(
    specs: Iterable[RegisterSpec], max_per_read: int, max_gap: int
) -> list[_Batch]:
    """Group specs into as few reads as the limits allow.

    Specs are grouped by register type, sorted by address, and merged while
    the block stays within ``max_per_read`` and the hole to the next spec is
    at most ``max_gap``. Reading across a hole saves a round trip but is not
    always legal — some devices reject the whole request with an illegal-data-
    address exception — hence the default of 0.
    """
    batches: list[_Batch] = []
    for rtype in _REGISTER_TYPES:
        group = sorted(
            (s for s in specs if s.register_type == rtype),
            key=lambda s: (s.address, s.count),
        )
        for spec in group:
            if spec.count > max_per_read:
                raise ValueError(
                    f"{spec.name}: needs {spec.count} registers but "
                    f"max_registers_per_read is {max_per_read}"
                )
            if batches and batches[-1].register_type == rtype:
                last = batches[-1]
                end = last.address + last.count
                new_count = max(end, spec.end) - last.address
                if spec.address - end <= max_gap and new_count <= max_per_read:
                    batches[-1] = _Batch(
                        rtype, last.address, new_count, last.specs + (spec,)
                    )
                    continue
            batches.append(_Batch(rtype, spec.address, spec.count, (spec,)))
    return batches


# --------------------------------------------------------------------------
# Live transport
# --------------------------------------------------------------------------


def _import_pymodbus() -> Any:
    """Import ``pymodbus.client``, or explain how to install it.

    A function rather than a module-level import so the failure happens when a
    connection is attempted, not at ``import otwin.io``.
    """
    try:
        return importlib.import_module("pymodbus.client")
    except ImportError as exc:
        raise MissingDependencyError(
            "live Modbus I/O requires the 'pymodbus' package, which is not "
            "installed. Install it with:\n"
            "    pip install 'otwin[modbus]'\n"
            "or directly:\n"
            "    pip install pymodbus\n"
            "pymodbus is BSD-3-Clause licensed and is an optional extra, so "
            "otwin.io imports and its simulators run without it. To develop or "
            "test without hardware, use otwin.io.ModbusSimulator instead — it "
            "drives the identical decode path."
        ) from exc


class PymodbusTransport:
    """A :class:`~otwin.io.source.RegisterTransport` backed by pymodbus.

    TCP if ``host`` is given, RTU if ``device`` is. Connects lazily on the
    first read and reconnects after a failure, so a source survives the plant
    network being restarted underneath it.

    Raises:
        MissingDependencyError: When pymodbus is not installed, or when its
            read signature is one this shim does not recognise.
        ValueError: If neither or both of ``host`` and ``device`` are given.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = 502,
        *,
        device: str | None = None,
        baudrate: int = 19200,
        unit_id: int = 1,
        timeout: float = 3.0,
        parity: str = "N",
        stopbits: int = 1,
        bytesize: int = 8,
    ) -> None:
        if (host is None) == (device is None):
            raise ValueError(
                "give exactly one of host= (Modbus TCP) or device= (Modbus RTU)"
            )
        client_mod = _import_pymodbus()
        self.unit_id = int(unit_id)
        if host is not None:
            self.name = f"modbus-tcp://{host}:{port}#{unit_id}"
            self._client = client_mod.ModbusTcpClient(host, port=port, timeout=timeout)
        else:
            self.name = f"modbus-rtu://{device}@{baudrate}#{unit_id}"
            self._client = client_mod.ModbusSerialClient(
                device,
                baudrate=baudrate,
                timeout=timeout,
                parity=parity,
                stopbits=stopbits,
                bytesize=bytesize,
            )
        self._unit_kwarg = self._detect_unit_kwarg()

    def _detect_unit_kwarg(self) -> str:
        """pymodbus renamed this argument twice: unit -> slave -> device_id."""
        import inspect

        params = inspect.signature(self._client.read_holding_registers).parameters
        for candidate in ("device_id", "slave", "unit"):
            if candidate in params:
                return candidate
        raise MissingDependencyError(
            "this pymodbus build exposes read_holding_registers with an "
            f"unrecognised signature ({sorted(params)}); otwin.io supports "
            "pymodbus 3.x. Install a supported version with: "
            "pip install 'pymodbus>=3,<4'"
        )

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        """Read ``count`` registers, connecting first if necessary."""
        if not self._client.connected and not self._client.connect():
            raise TransportError(f"could not connect to {self.name}")
        fn = (
            self._client.read_holding_registers
            if register_type == "holding"
            else self._client.read_input_registers
        )
        try:
            rr = fn(address, count=count, **{self._unit_kwarg: self.unit_id})
        except Exception as exc:  # pymodbus raises its own exception hierarchy
            self._client.close()
            raise TransportError(
                f"{self.name}: read at {address}+{count} failed: {exc}"
            ) from exc
        if rr is None or (hasattr(rr, "isError") and rr.isError()):
            raise TransportError(
                f"{self.name}: exception response at {address}+{count}: {rr}"
            )
        regs = list(getattr(rr, "registers", []) or [])
        if len(regs) != count:
            raise TransportError(
                f"{self.name}: short frame at {address}: wanted {count} registers, got {len(regs)}"
            )
        return regs

    def close(self) -> None:
        """Close the underlying client. Safe to call repeatedly."""
        # close must never raise: a failing teardown would mask the real
        # error that caused the caller to close in the first place.
        with contextlib.suppress(Exception):
            self._client.close()


# --------------------------------------------------------------------------
# Source
# --------------------------------------------------------------------------


class ModbusSource:
    """Read a described register map from a Modbus device.

    Args:
        registers: The register map. Every tag must have a unit.
        host, port: Modbus TCP endpoint.
        device, baudrate: Modbus RTU serial line.
        unit_id: Modbus unit/slave identifier.
        word_order: ``"big"`` (ABCD) or ``"little"`` (CDAB) for 32-bit values.
            Read the module docstring before choosing: there is no safe
            default, only a common one.
        transport: Supply a ready-made
            :class:`~otwin.io.source.RegisterTransport` — a simulator, or a
            client you already own — instead of host/device. Connection
            arguments are then ignored and no optional package is needed.
        max_registers_per_read: Batching limit, capped at the Modbus maximum
            of 125. Lower it for devices that lie about their buffer size.
        max_gap: Unused registers that may be swallowed into a batch to save a
            round trip. 0 (default) never reads an address outside the map.
        normalise_units: Convert every value to SI. :meth:`tags` reports
            whichever unit the values are actually in.
        max_stale_seconds: See :class:`~otwin.io.source.QualityTracker`.
        name: Overrides the string recorded in :attr:`Sample.source`.
        timeout: Per-request timeout, live transports only.

    Attributes:
        last_error: The most recent read failure, or ``None`` after a clean
            cycle. Cleared at the start of every :meth:`read`.
        metadata: Decoded ``string`` tags, refreshed each read. Strings cannot
            live in :attr:`Sample.values`, which is floats only.

    Example:
        >>> from otwin.io import ModbusSimulator
        >>> specs = [RegisterSpec("p_dc", 0, "float32", "kW", description="DC power")]
        >>> sim = ModbusSimulator(specs, word_order="big")
        >>> sim.set_value("p_dc", 250.0)
        >>> src = ModbusSource(specs, transport=sim, word_order="big")
        >>> s = src.read()
        >>> s.values["p_dc"], s.quality["p_dc"]
        (250000.0, 'good')
    """

    def __init__(
        self,
        registers: Sequence[RegisterSpec],
        *,
        host: str | None = None,
        port: int = 502,
        device: str | None = None,
        baudrate: int = 19200,
        unit_id: int = 1,
        word_order: str = "big",
        transport: RegisterTransport | None = None,
        max_registers_per_read: int = MODBUS_MAX_REGISTERS_PER_READ,
        max_gap: int = 0,
        normalise_units: bool = True,
        max_stale_seconds: float | None = None,
        name: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        if word_order not in ("big", "little"):
            raise ValueError(f"word_order must be 'big' or 'little', got {word_order!r}")
        self.registers = list(registers)
        if not self.registers:
            raise ValueError("a register map with no registers reads nothing")
        names = [s.name for s in self.registers]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate tag names in register map: {dupes}")
        if not 1 <= max_registers_per_read <= MODBUS_MAX_REGISTERS_PER_READ:
            raise ValueError(
                f"max_registers_per_read must be 1..{MODBUS_MAX_REGISTERS_PER_READ}"
            )
        if max_gap < 0:
            raise ValueError("max_gap must be >= 0")

        self.word_order = word_order
        self.normalise_units = bool(normalise_units)
        self.max_registers_per_read = int(max_registers_per_read)
        self.max_gap = int(max_gap)
        self.last_error: Exception | None = None
        self.metadata: dict[str, str] = {}
        self._quality = QualityTracker(max_stale_seconds=max_stale_seconds)
        self._closed = False

        if transport is not None:
            self._transport: RegisterTransport = transport
            default_name = getattr(transport, "name", type(transport).__name__)
        else:
            self._transport = PymodbusTransport(
                host=host,
                port=port,
                device=device,
                baudrate=baudrate,
                unit_id=unit_id,
                timeout=timeout,
            )
            default_name = self._transport.name
        self.name = name or str(default_name)
        self._batches = _plan_batches(
            self.registers, self.max_registers_per_read, self.max_gap
        )

    @classmethod
    def from_file(cls, path: str | Path, **overrides: Any) -> ModbusSource:
        """Build a source from a YAML/JSON register map.

        Connection options in the file become constructor defaults; keyword
        arguments passed here win.
        """
        specs, options = load_register_map(path)
        allowed = {
            "host",
            "port",
            "device",
            "baudrate",
            "unit_id",
            "word_order",
            "max_registers_per_read",
            "max_gap",
            "normalise_units",
            "max_stale_seconds",
            "name",
            "timeout",
        }
        unknown = set(options) - allowed
        if unknown:
            raise ValueError(f"{path}: unknown option(s) {sorted(unknown)}")
        return cls(specs, **{**options, **overrides})

    @property
    def batches(self) -> list[tuple[str, int, int]]:
        """Planned reads as ``(register_type, address, count)``.

        Exposed so a commissioning script can show how many round trips per
        cycle a map costs before it is deployed.
        """
        return [(b.register_type, b.address, b.count) for b in self._batches]

    def tags(self) -> list[TagSpec]:
        """One :class:`TagSpec` per register spec, in map order."""
        out = []
        for s in self.registers:
            if s.dtype == "string":
                unit = "1"
            else:
                unit = si_unit(s.unit) if self.normalise_units else s.unit
            out.append(
                TagSpec(
                    name=s.name,
                    unit=unit,
                    description=s.description
                    or f"Modbus {s.register_type} register {s.address}",
                    dtype=s.dtype,
                    raw_unit=s.unit,
                    address=s.address,
                )
            )
        return out

    def _degrade(
        self,
        spec: RegisterSpec,
        now: float,
        values: dict[str, float],
        quality: dict[str, str],
    ) -> None:
        """Record a failed tag as stale (previous value) or bad (NaN)."""
        if spec.dtype == "string":
            quality[spec.name] = "stale" if spec.name in self.metadata else "bad"
            return
        value, q = self._quality.resolve_failed(spec.name, now)
        values[spec.name] = value
        quality[spec.name] = q

    def read(self) -> Sample:
        """Read every batch once and assemble a :class:`Sample`.

        Never raises for a wire-level failure. A failed batch marks its tags
        ``"stale"`` or ``"bad"`` and records the exception in
        :attr:`last_error`; the other batches still go out.
        """
        now = time.time()
        self.last_error = None
        values: dict[str, float] = {}
        quality: dict[str, str] = {}

        for batch in self._batches:
            try:
                words = self._transport.read_registers(
                    batch.address, batch.count, batch.register_type
                )
            except Exception as exc:  # transports may raise anything
                self.last_error = exc
                for spec in batch.specs:
                    self._degrade(spec, now, values, quality)
                continue

            for spec in batch.specs:
                lo = spec.address - batch.address
                try:
                    decoded = decode_registers(
                        words[lo : lo + spec.count], spec.dtype, self.word_order
                    )
                except Exception as exc:
                    self.last_error = exc
                    self._degrade(spec, now, values, quality)
                    continue
                if spec.dtype == "string":
                    self.metadata[spec.name] = str(decoded)
                    quality[spec.name] = "good"
                    continue
                scaled = float(decoded) * spec.scale
                value = to_si(scaled, spec.unit) if self.normalise_units else scaled
                values[spec.name] = value
                quality[spec.name] = "good"
                self._quality.record_good(spec.name, value, now)

        return Sample(timestamp=now, values=values, quality=quality, source=self.name)

    def close(self) -> None:
        """Close the transport. Idempotent."""
        if not self._closed:
            self._closed = True
            self._transport.close()

    def __enter__(self) -> ModbusSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"ModbusSource({self.name!r}, tags={len(self.registers)}, "
            f"reads_per_cycle={len(self._batches)}, word_order={self.word_order!r})"
        )
