"""In-process fake devices, so the connectors can be tested without a plant.

These are not mocks. A mock would stub out :meth:`ModbusSource.read` and prove
nothing; the interesting code in this package is the decoding, the scale
factors, the word order and the degradation logic. Both simulators implement
:class:`~otwin.io.source.RegisterTransport` — they serve 16-bit registers and
nothing else — so a simulated read travels through exactly the same path as a
real one. If a test passes here and fails on hardware, the difference is on
the wire, not in this library.

Both support fault injection, because what matters most on a plant network is
what happens when a device stops answering:

* :meth:`_SimulatorBase.inject_timeout` — a register range that raises on
  read, the way a device behind a flapping switch does.
* ``freeze`` — a value that stops updating while still reading cleanly. This
  is the nastier failure: nothing errors, the number is just old.
* ``inject_out_of_range`` — a physically impossible raw value, which is what a
  mis-set scale factor looks like from the outside.
"""

from __future__ import annotations

import math
import struct
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .modbus import RegisterSpec, encode_value
from .source import TransportError
from .sunspec import SUNSPEC_IDENTIFIER, ModelDef, PointDef, load_model_def

__all__ = ["ModbusSimulator", "SunSpecSimulator", "SimulatedFault"]


class SimulatedFault(TransportError):
    """Raised by a simulator for a register range under an injected timeout."""


@dataclass(frozen=True)
class _Range:
    start: int
    count: int
    register_type: str

    def overlaps(self, address: int, count: int, register_type: str) -> bool:
        if register_type != self.register_type:
            return False
        return address < self.start + self.count and self.start < address + count


class _SimulatorBase:
    """Register banks, fault injection and request accounting.

    Attributes:
        read_count: Reads served. Tests use it to prove that batching in
            :class:`~otwin.io.modbus.ModbusSource` really cuts round trips.
        requests: Every request as ``(register_type, address, count)``.
    """

    def __init__(self, name: str, strict_addresses: bool = False) -> None:
        self.name = name
        self.strict_addresses = bool(strict_addresses)
        self.read_count = 0
        self.requests: list[tuple[str, int, int]] = []
        self._banks: dict[str, dict[int, int]] = {"holding": {}, "input": {}}
        self._faults: list[_Range] = []
        self._closed = False

    def _bank(self, register_type: str) -> dict[int, int]:
        try:
            return self._banks[register_type]
        except KeyError:
            raise ValueError(
                f"register_type must be 'holding' or 'input', got {register_type!r}"
            ) from None

    def set_raw(
        self, address: int, words: Sequence[int], register_type: str = "holding"
    ) -> None:
        """Write raw 16-bit words into a register bank."""
        bank = self._bank(register_type)
        for i, w in enumerate(words):
            value = int(w)
            if not 0 <= value <= 0xFFFF:
                raise ValueError(
                    f"register value {w!r} at {address + i} is not a 16-bit word"
                )
            bank[address + i] = value

    def get_raw(
        self, address: int, count: int = 1, register_type: str = "holding"
    ) -> list[int]:
        """Read raw words from the bank, ignoring injected faults."""
        bank = self._bank(register_type)
        return [bank.get(address + i, 0) for i in range(count)]

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        """Serve a read, honouring any injected timeout that overlaps it.

        Raises:
            SimulatedFault: If the request touches an injected timeout range,
                or, in ``strict_addresses`` mode, an address never written.
        """
        if self._closed:
            raise SimulatedFault(f"{self.name}: transport is closed")
        if count < 1:
            raise ValueError("count must be >= 1")
        self.read_count += 1
        self.requests.append((register_type, address, count))
        for fault in self._faults:
            if fault.overlaps(address, count, register_type):
                raise SimulatedFault(
                    f"{self.name}: simulated timeout reading {register_type} "
                    f"registers {address}..{address + count - 1}"
                )
        bank = self._bank(register_type)
        if self.strict_addresses:
            missing = [a for a in range(address, address + count) if a not in bank]
            if missing:
                raise SimulatedFault(
                    f"{self.name}: illegal data address; {len(missing)} of "
                    f"{count} registers from {address} are not mapped"
                )
        return [bank.get(address + i, 0) for i in range(count)]

    def inject_timeout(
        self, address: int, count: int = 1, register_type: str = "holding"
    ) -> None:
        """Make reads touching ``address``..``address+count-1`` raise."""
        self._faults.append(_Range(int(address), int(count), register_type))

    def clear_faults(self) -> None:
        """Remove every injected timeout. Frozen values are unaffected."""
        self._faults.clear()

    @property
    def faults(self) -> list[tuple[str, int, int]]:
        """Injected timeout ranges as ``(register_type, start, count)``."""
        return [(f.register_type, f.start, f.count) for f in self._faults]

    def close(self) -> None:
        """Mark the simulated link closed. Further reads raise."""
        self._closed = True

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, reads={self.read_count})"


class ModbusSimulator(_SimulatorBase):
    """Serves a raw Modbus register map described by :class:`RegisterSpec`.

    The image is built from the same specs the source under test reads, so a
    test writes an engineering value in, reads it back out through the source,
    and any encode/decode asymmetry — word order above all — shows up as a
    wrong number rather than a passing test.

    Args:
        registers: The map to serve. May be empty if only :meth:`set_raw` is
            used.
        word_order: The word order the *device* uses. Set it differently from
            the source's to reproduce the classic field bug on purpose.
        name: Reported as :attr:`Sample.source` by a source using it.
        strict_addresses: Raise on reads of registers never written, the way a
            device returns illegal-data-address. Off by default, so unwritten
            registers read as zero.

    Example:
        >>> specs = [RegisterSpec("p", 0, "float32", "kW"),
        ...          RegisterSpec("soc", 2, "uint16", "%", scale=0.1)]
        >>> sim = ModbusSimulator(specs)
        >>> sim.set_value("p", 250.0)
        >>> sim.set_value("soc", 62.0)
        >>> sim.get_raw(2, 1)
        [620]
    """

    def __init__(
        self,
        registers: Iterable[RegisterSpec] = (),
        *,
        word_order: str = "big",
        name: str = "modbus-sim://local",
        strict_addresses: bool = False,
    ) -> None:
        if word_order not in ("big", "little"):
            raise ValueError(f"word_order must be 'big' or 'little', got {word_order!r}")
        super().__init__(name=name, strict_addresses=strict_addresses)
        self.word_order = word_order
        self.registers = {s.name: s for s in registers}
        self._values: dict[str, float | str] = {}
        self._frozen: set[str] = set()
        for spec in self.registers.values():
            self.set_value(spec.name, "" if spec.dtype == "string" else 0.0)

    def _spec(self, name: str) -> RegisterSpec:
        try:
            return self.registers[name]
        except KeyError:
            raise KeyError(
                f"{name!r} is not in this simulator's register map ({sorted(self.registers)})"
            ) from None

    def set_value(self, name: str, value: float | str) -> None:
        """Write an engineering value for a named tag into the registers.

        The value is divided by :attr:`RegisterSpec.scale` and encoded with
        the simulator's own ``word_order`` — the exact inverse of what the
        source does. A :meth:`freeze`-d tag records the value but leaves its
        registers alone.
        """
        spec = self._spec(name)
        if spec.name in self._frozen:
            self._values[name] = value
            return
        if spec.dtype == "string":
            words = encode_value(str(value), "string", spec.count, self.word_order)
        else:
            raw = float(value) / spec.scale
            words = encode_value(
                raw if spec.dtype == "float32" else round(raw),
                spec.dtype,
                spec.count,
                self.word_order,
            )
        self.set_raw(spec.address, words, spec.register_type)
        self._values[name] = value

    def get_value(self, name: str) -> float | str:
        """The last engineering value written for ``name``."""
        self._spec(name)
        return self._values[name]

    def freeze(self, name: str) -> None:
        """Stop :meth:`set_value` updating this tag's registers.

        They keep their contents and keep reading cleanly, which is what a
        device with a hung acquisition task looks like: no error anywhere,
        just a number that has quietly stopped moving.
        """
        self._frozen.add(self._spec(name).name)

    def unfreeze(self, name: str) -> None:
        """Undo :meth:`freeze` and write back the most recent value."""
        spec = self._spec(name)
        self._frozen.discard(spec.name)
        self.set_value(spec.name, self._values[spec.name])

    def inject_out_of_range(self, name: str, raw: float) -> None:
        """Write a physically impossible *raw* value, bypassing ``scale``.

        This is what a device with a mis-set scale factor puts on the wire.
        """
        spec = self._spec(name)
        if spec.dtype == "string":
            raise TypeError(f"{name}: out-of-range injection is for numeric tags")
        value = float(raw) if spec.dtype == "float32" else round(float(raw))
        self.set_raw(
            spec.address,
            encode_value(value, spec.dtype, spec.count, self.word_order),
            spec.register_type,
        )


# --------------------------------------------------------------------------
# SunSpec
# --------------------------------------------------------------------------

# Scale factors the simulated device publishes, chosen to be awkward: SoC at
# 10^-2 exposes an unscaled decoder, and the energy and power factors differ
# so a decoder applying one model's factor to another's point is visibly wrong.
_SIM_SF: dict[int, dict[str, int]] = {
    701: {
        "A_SF": -1,
        "V_SF": -1,
        "Hz_SF": -2,
        "W_SF": 2,
        "PF_SF": -3,
        "VA_SF": 2,
        "Var_SF": 2,
        "TotWh_SF": 0,
        "Tmp_SF": -1,
    },
    713: {"WH_SF": 3, "Pct_SF": -2},
    802: {
        "AHRtg_SF": 0,
        "WHRtg_SF": 3,
        "WChaDisChaMax_SF": 3,
        "SoC_SF": -2,
        "DoD_SF": -2,
        "SoH_SF": -2,
        "V_SF": -1,
        "CellV_SF": -3,
        "A_SF": -1,
        "W_SF": 2,
    },
}

_SIM_STRINGS: dict[str, str] = {
    "Mn": "Otwin",
    "Md": "SunSpecSimulator",
    "Opt": "BESS",
    "Vr": "1.0.0",
    "SN": "SIM-0000001",
}

_SIGNED_FORMATS: dict[tuple[str, int], str] = {
    ("int16", 1): ">h",
    ("sunssf", 1): ">h",
    ("int32", 2): ">i",
    ("int64", 4): ">q",
}
_UNSIGNED_FORMATS: dict[int, str] = {1: ">H", 2: ">I", 4: ">Q"}


def _encode_sunspec(value: int, point: PointDef) -> list[int]:
    """Encode an integer into a SunSpec point's registers, big-endian."""
    fmt = _SIGNED_FORMATS.get((point.ptype, point.size)) or _UNSIGNED_FORMATS.get(
        point.size
    )
    if fmt is None:
        raise ValueError(f"cannot encode point {point.name} of size {point.size}")
    if fmt in (">H", ">I", ">Q") and value < 0:
        value += 1 << (point.size * 16)
    raw = struct.pack(fmt, value)
    return [int(struct.unpack(">H", raw[i : i + 2])[0]) for i in range(0, len(raw), 2)]


def _sentinel_words(point: PointDef) -> list[int]:
    """The SunSpec not-implemented pattern for a point, as registers.

    Signed types use the most-negative value, unsigned all-ones, accumulators
    zero, float32 a quiet NaN, strings and padding zero. A decoder that
    ignores these reports -32768 as a temperature.
    """
    if point.ptype in (
        "string",
        "pad",
        "ipv6addr",
        "eui48",
        "acc16",
        "acc32",
        "acc64",
        "count",
        "ipaddr",
    ):
        return [0x0000] * point.size
    if point.ptype == "float32":
        return [0x7FC0, 0x0000]
    if point.ptype in ("int16", "sunssf"):
        return [0x8000]
    if point.ptype in ("int32", "int64"):
        return [0x8000] + [0x0000] * (point.size - 1)
    return [0xFFFF] * point.size


class SunSpecSimulator(_SimulatorBase):
    """A plausible grid-scale battery published as a SunSpec model chain.

    Serves the common model (1), 802 ``battery``, 713 ``DERStorageCapacity``
    and 701 ``DERMeasureAC`` at base 40000, with the ``"SunS"`` identifier,
    correct model lengths, correct ``sunssf`` registers and the SunSpec
    not-implemented sentinel in every point the device does not have.
    :class:`~otwin.io.sunspec.SunSpecSource` runs against it unmodified.

    :meth:`advance` drifts the state of charge at :attr:`drift_per_hour` and
    rebuilds every derived quantity — depth of discharge, available energy,
    bank and cell voltages, DC current, AC power — so the device stays
    self-consistent rather than reporting an SoC that contradicts its own
    power flow.

    Args:
        soc: Initial state of charge as a fraction.
        soh: State of health as a fraction.
        base_address: Where to publish the chain.
        capacity_wh: Nameplate energy in watt-hours.
        power_w: DC power, positive on discharge.
        drift_per_hour: SoC change per hour applied by :meth:`advance`.
            Defaults to ``-power_w / capacity_wh``, i.e. the battery
            discharges at the rate it claims to.
        models: Which models to publish — restrict it to test a device with
            no 713, for example.
        name: Reported as :attr:`Sample.source`.
        auto_advance: Advance from the wall clock on every read. Off by
            default so tests are deterministic.

    Example:
        >>> sim = SunSpecSimulator(soc=0.80, capacity_wh=2_000_000, power_w=500_000)
        >>> sim.advance(3600)          # one hour at 500 kW out of 2 MWh
        >>> round(sim.soc, 3)
        0.55
    """

    def __init__(
        self,
        soc: float = 0.65,
        *,
        soh: float = 0.973,
        base_address: int = 40000,
        capacity_wh: float = 2_000_000.0,
        power_w: float = 250_000.0,
        drift_per_hour: float | None = None,
        models: Sequence[int] = (1, 802, 713, 701),
        name: str = "sunspec-sim://local",
        auto_advance: bool = False,
    ) -> None:
        super().__init__(name=name)
        unknown = [
            m for m in models if m not in (1, 701, 702, 704, 713, 802, 803, 804, 805)
        ]
        if unknown:
            raise ValueError(f"SunSpecSimulator does not publish models {unknown}")
        self.base_address = int(base_address)
        self.capacity_wh = float(capacity_wh)
        self.power_w = float(power_w)
        self.soh = float(soh)
        self.drift_per_hour = (
            drift_per_hour
            if drift_per_hour is not None
            else -self.power_w / self.capacity_wh
        )
        self.model_ids = tuple(models)
        self.auto_advance = bool(auto_advance)
        self._soc = 0.0
        self._frozen: set[str] = set()
        self._pinned: dict[str, int] = {}
        self._layout: dict[int, tuple[int, ModelDef]] = {}
        self._clock = time.time()
        self.soc = float(soc)  # triggers the first full build

    @property
    def soc(self) -> float:
        """State of charge as a fraction in ``[0, 1]``."""
        return self._soc

    @soc.setter
    def soc(self, value: float) -> None:
        v = float(value)
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"soc must be a fraction in [0, 1], got {v!r}. To simulate a "
                f"device reporting nonsense, use inject_out_of_range()."
            )
        self._soc = v
        self._rebuild()

    def advance(self, seconds: float) -> None:
        """Move the clock on, drifting the SoC and everything derived from it."""
        if seconds < 0:
            raise ValueError("time does not run backwards on a plant")
        self._clock += float(seconds)
        self._soc = min(
            1.0, max(0.0, self._soc + self.drift_per_hour * (seconds / 3600.0))
        )
        self._rebuild()

    def freeze(self, model_id: int, point: str) -> None:
        """Stop a point being updated, while it keeps reading cleanly."""
        self._frozen.add(f"{model_id}.{point}")

    def unfreeze(self, model_id: int, point: str) -> None:
        """Undo :meth:`freeze` or :meth:`pin_raw` for one point."""
        key = f"{model_id}.{point}"
        self._frozen.discard(key)
        self._pinned.pop(key, None)
        self._rebuild()

    def pin_raw(self, model_id: int, point: str, raw: int) -> None:
        """Hold a point's raw register at ``raw`` until :meth:`unfreeze`.

        ``raw`` is the integer on the wire, before the scale factor. Use it to
        simulate a point reported as not implemented (write the sentinel for
        its type, e.g. ``0xFFFF`` for a ``uint16``), or a mis-set scale factor.
        """
        key = f"{model_id}.{point}"
        self._pinned[key] = int(raw)
        self._frozen.add(key)
        self._write_point(model_id, point, int(raw))

    def inject_out_of_range(self, model_id: int, point: str, raw: int) -> None:
        """Pin a point to a physically impossible raw value.

        A thin alias for :meth:`pin_raw` that says why you are doing it.

        Example:
            >>> sim = SunSpecSimulator(soc=0.5)
            >>> sim.inject_out_of_range(802, "SoC", 45000)   # 450 % with SF -2
        """
        self.pin_raw(model_id, point, raw)

    def inject_timeout_for_model(self, model_id: int) -> None:
        """Make every read of ``model_id``'s registers raise."""
        for mid, (address, definition) in self._layout.items():
            if mid == model_id:
                self.inject_timeout(address, definition.fixed_len, "holding")
                return
        raise KeyError(f"this simulator does not publish model {model_id}")

    def address_of(self, model_id: int, point: str | None = None) -> int:
        """Protocol address of a model's ID register, or of one of its points."""
        if model_id not in self._layout:
            raise KeyError(f"this simulator does not publish model {model_id}")
        address, definition = self._layout[model_id]
        if point is None:
            return address
        pd = definition.point(point)
        if pd is None:
            raise KeyError(f"model {model_id} has no point {point!r}")
        return address + pd.offset

    @property
    def published_models(self) -> list[int]:
        """Model numbers currently published, in chain order."""
        return [m for m in self.model_ids if m in self._layout]

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        """Serve a read, first advancing the clock if ``auto_advance`` is set."""
        if self.auto_advance:
            elapsed = max(0.0, time.time() - self._clock)
            if elapsed > 0:
                self.advance(elapsed)
        return super().read_registers(address, count, register_type)

    def _raw_points(self, model_id: int) -> dict[str, int]:
        """Raw register values for the points this device implements."""
        sf = _SIM_SF.get(model_id, {})
        soc, soh = self._soc, self.soh
        if model_id == 1:
            return {"DA": 1}
        if model_id == 802:
            volts = 780.0 + 60.0 * soc
            cell_avg = 3.35 + 0.35 * soc
            return {
                **sf,
                "AHRtg": round(self.capacity_wh / volts),
                "WHRtg": round(self.capacity_wh / 10 ** sf["WHRtg_SF"]),
                "WChaRteMax": round(1_000_000 / 10 ** sf["WChaDisChaMax_SF"]),
                "WDisChaRteMax": round(1_000_000 / 10 ** sf["WChaDisChaMax_SF"]),
                "SoCMax": 9500,
                "SoCMin": 500,
                "SoC": round(soc * 100 / 10 ** sf["SoC_SF"]),
                "DoD": round((1.0 - soc) * 100 / 10 ** sf["DoD_SF"]),
                "SoH": round(soh * 100 / 10 ** sf["SoH_SF"]),
                "NCyc": 1450,
                "V": round(volts / 10 ** sf["V_SF"]),
                "CellVMax": round((cell_avg + 0.022) / 10 ** sf["CellV_SF"]),
                "CellVMin": round((cell_avg - 0.021) / 10 ** sf["CellV_SF"]),
                "CellVAvg": round(cell_avg / 10 ** sf["CellV_SF"]),
                "A": round(self.power_w / volts / 10 ** sf["A_SF"]),
                "W": round(self.power_w / 10 ** sf["W_SF"]),
            }
        if model_id == 713:
            return {
                **sf,
                "WHRtg": round(self.capacity_wh / 10 ** sf["WH_SF"]),
                "WHAvail": round(self.capacity_wh * soc * soh / 10 ** sf["WH_SF"]),
                "SoC": round(soc * 100 / 10 ** sf["Pct_SF"]),
                "SoH": round(soh * 100 / 10 ** sf["Pct_SF"]),
                "Sta": 0,
            }
        if model_id == 701:
            ac_w = self.power_w * 0.985  # inverter efficiency, discharge sign
            v_ll, v_ln = 400.0, 231.0
            return {
                **sf,
                "W": round(ac_w / 10 ** sf["W_SF"]),
                "VA": round(abs(ac_w) / 10 ** sf["VA_SF"]),
                "Var": 0,
                "PF": round(1.0 / 10 ** sf["PF_SF"]),
                "A": round(abs(ac_w) / (math.sqrt(3.0) * v_ll) / 10 ** sf["A_SF"]),
                "LLV": round(v_ll / 10 ** sf["V_SF"]),
                "LNV": round(v_ln / 10 ** sf["V_SF"]),
                "Hz": round(50.0 / 10 ** sf["Hz_SF"]),
                "TotWhInj": 4_812_000,
                "TotWhAbs": 5_231_000,
                "TmpAmb": round(24.5 / 10 ** sf["Tmp_SF"]),
                "TmpSnk": round(41.2 / 10 ** sf["Tmp_SF"]),
            }
        return dict(sf)

    def _rebuild(self) -> None:
        """Lay the whole chain out again from the current state.

        The layout is deterministic, so the previous image can be carried over
        register-for-register wherever a point is frozen.
        """
        previous = dict(self._banks["holding"])
        self._banks["holding"] = {}
        self._layout = {}
        addr = self.base_address
        self.set_raw(addr, list(SUNSPEC_IDENTIFIER))
        addr += 2
        for model_id in self.model_ids:
            definition = load_model_def(model_id, prefer_installed=True)
            if definition is None:  # pragma: no cover - all published ids resolve
                continue
            self._layout[model_id] = (addr, definition)
            self._write_model(addr, definition, previous)
            addr += definition.fixed_len
        self.set_raw(addr, [0xFFFF, 0x0000])

    def _write_model(
        self, address: int, definition: ModelDef, previous: dict[int, int] | None = None
    ) -> None:
        """Fill one model: sentinels everywhere, then the implemented points."""
        for point in definition.points:
            self.set_raw(address + point.offset, _sentinel_words(point))
        self.set_raw(address, [definition.model_id, definition.fixed_len - 2])
        if definition.model_id == 1:
            for name, text in _SIM_STRINGS.items():
                pd = definition.point(name)
                if pd is not None:
                    self.set_raw(
                        address + pd.offset, encode_value(text, "string", pd.size, "big")
                    )
        for name, raw in self._raw_points(definition.model_id).items():
            key = f"{definition.model_id}.{name}"
            if key not in self._frozen:
                self._write_point(definition.model_id, name, raw, definition, address)
            elif key in self._pinned:
                self._write_point(
                    definition.model_id, name, self._pinned[key], definition, address
                )
            elif previous:
                self._restore_point(address, definition, name, previous)

    def _restore_point(
        self, address: int, definition: ModelDef, point: str, previous: dict[int, int]
    ) -> None:
        """Carry a frozen point's registers over from the previous image."""
        pd = definition.point(point)
        if pd is None:
            return
        words = [previous.get(address + pd.offset + i) for i in range(pd.size)]
        if all(w is not None for w in words):
            self.set_raw(address + pd.offset, [int(w) for w in words if w is not None])

    def _write_point(
        self,
        model_id: int,
        point: str,
        raw: int,
        definition: ModelDef | None = None,
        address: int | None = None,
    ) -> None:
        """Encode one raw integer into a point's registers."""
        if definition is None or address is None:
            if model_id not in self._layout:
                raise KeyError(f"this simulator does not publish model {model_id}")
            address, definition = self._layout[model_id]
        pd = definition.point(point)
        if pd is None:
            raise KeyError(f"model {model_id} has no point {point!r}")
        self.set_raw(address + pd.offset, _encode_sunspec(int(raw), pd))
