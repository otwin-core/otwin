"""SunSpec Modbus — the DER interface named by IEEE 1547-2018.

IEEE 1547-2018 permits three DER communication interfaces: SunSpec Modbus,
IEEE 1815 (DNP3) and IEEE 2030.5. Only the first has a permissively licensed
Python path, so it is the one Otwin implements natively; see the package
docstring for what happens to the other two.

What SunSpec adds to raw Modbus is self-description. A device publishes a
chain of numbered models from a well-known base address, each a fixed layout
of named points with declared types and units. Discovery therefore replaces
the vendor PDF, and every tag carries its model number and point name.

**Scale factors.** SunSpec sends most measurements as integers with a
companion ``sunssf`` point holding a base-10 exponent: ``SoC = 8542`` with
``SoC_SF = -2`` means 85.42 %. A decoder that ignores it is wrong by 10^x, and
10^-2 on a state of charge still looks like a number. Every point with a
declared ``sf`` is multiplied by ``10**sf`` before unit normalisation, and a
scale-factor register holding the not-implemented sentinel ``0x8000`` is
treated as an exponent of zero rather than as -32768.

Implemented
-----------
Discovery from bases 40000, 50000 and 0; the common model (1) for device
identity; and decoding of the **fixed, non-repeating point block** of every
model, with scale factors, not-implemented sentinels and unit normalisation.
Named and supported explicitly: 701 ``DERMeasureAC``, 702 ``DERCapacity``,
704 ``DERCtlAC``, 713 ``DERStorageCapacity``, 802 ``battery``,
803 ``lithium_ion_bank``, 804 ``lithium_ion_string``,
805 ``lithium-ion-module``.

Not implemented, deliberately
-----------------------------
* **Repeating groups.** 803, 804 and 805 append a variable number of
  string/module/cell sub-groups after their fixed block. These are not
  enumerated; only the fixed header points (bank, string and module
  aggregates) are decoded. A 400-cell bank would produce 400 more tags per
  cycle than most twins want, and doing it correctly needs per-vendor testing
  this module has not had.
* **Nested fixed groups.** Model 704's ``PFWInj``/``PFWAbs`` power-factor
  sub-groups are not decoded; its scalar setpoints are.
* **Writing.** Everything here is read-only. 704 is a control model, and
  writing to it changes what a plant does; that belongs behind an interlock,
  not in a twin's data-acquisition layer.
* **String, IP-address and EUI-48 points** are not delivered as values.
  Strings from the common model become :attr:`SunSpecSource.device_info`.

Model definitions come from pysunspec2's bundled official SunSpec JSON when it
is installed, covering every point of every model. Without it, a curated
subset transcribed from those same files is used — see
:data:`_BUILTIN_MODEL_DEFS` for exactly which points. Both paths give
identical values for shared points; :func:`compare_model_defs` checks that,
and the test suite runs it whenever pysunspec2 is present.
"""

from __future__ import annotations

import contextlib
import importlib
import struct
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .source import (
    MissingDependencyError,
    QualityTracker,
    RegisterTransport,
    Sample,
    TagSpec,
    TransportError,
    UnknownUnitError,
    si_unit,
    to_si,
)

__all__ = [
    "SunSpecSource",
    "PointDef",
    "ModelDef",
    "ModelInstance",
    "PySunSpec2Transport",
    "decode_point",
    "load_model_def",
    "compare_model_defs",
    "SUNSPEC_BASE_ADDRESSES",
    "SUNSPEC_IDENTIFIER",
    "SUNSSF_RANGE",
    "SUPPORTED_MODELS",
    "MODEL_NAMES",
    "ScaleFactorError",
]

#: Base addresses a SunSpec device may publish its chain at, in probe order.
SUNSPEC_BASE_ADDRESSES: tuple[int, ...] = (40000, 50000, 0)

#: ``"SunS"`` as two registers — the marker preceding the model chain.
SUNSPEC_IDENTIFIER: tuple[int, int] = (0x5375, 0x6E53)

_END_MODEL_ID = 0xFFFF

#: Range the SunSpec specification allows a ``sunssf`` scale factor to take.
#: The register is a signed 16-bit integer, so a device can put anything in
#: it; the specification restricts the *meaning* to base-10 exponents in this
#: band. A register outside it is corruption or a mis-mapped address, and the
#: points it scales are reported as unreadable rather than multiplied by
#: 10**400.
SUNSSF_RANGE: tuple[int, int] = (-10, 10)


class ScaleFactorError(ValueError):
    """A ``sunssf`` register holds a value outside :data:`SUNSSF_RANGE`.

    Raised inside :meth:`SunSpecSource._scale`, where :meth:`SunSpecSource.read`
    catches it and degrades the affected points. It reaches a caller only
    through :attr:`SunSpecSource.last_error`.
    """


#: Models this module names explicitly. Others found on the wire are still
#: decoded when a definition is available.
SUPPORTED_MODELS: tuple[int, ...] = (1, 701, 702, 704, 713, 802, 803, 804, 805)

MODEL_NAMES: dict[int, str] = {
    1: "common",
    701: "DERMeasureAC",
    702: "DERCapacity",
    704: "DERCtlAC",
    713: "DERStorageCapacity",
    802: "battery",
    803: "lithium_ion_bank",
    804: "lithium_ion_string",
    805: "lithium-ion-module",
}

_MAX_REGISTERS_PER_READ = 125
_MAX_MODELS = 128


# --------------------------------------------------------------------------
# Point codec
# --------------------------------------------------------------------------

# wire type -> (struct format, registers, not-implemented sentinel)
_TYPES: dict[str, tuple[str, int, int | None]] = {
    "int16": (">h", 1, -0x8000),
    "sunssf": (">h", 1, -0x8000),
    "uint16": (">H", 1, 0xFFFF),
    "enum16": (">H", 1, 0xFFFF),
    "bitfield16": (">H", 1, 0xFFFF),
    "count": (">H", 1, None),
    "acc16": (">H", 1, 0),
    "pad": (">H", 1, None),
    "int32": (">i", 2, -0x80000000),
    "uint32": (">I", 2, 0xFFFFFFFF),
    "enum32": (">I", 2, 0xFFFFFFFF),
    "bitfield32": (">I", 2, 0xFFFFFFFF),
    "acc32": (">I", 2, 0),
    "ipaddr": (">I", 2, 0),
    "float32": (">f", 2, None),
    "int64": (">q", 4, -0x8000000000000000),
    "uint64": (">Q", 4, 0xFFFFFFFFFFFFFFFF),
    "acc64": (">Q", 4, 0),
    "bitfield64": (">Q", 4, 0xFFFFFFFFFFFFFFFF),
}

_NUMERIC_TYPES = frozenset(
    [
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "acc16",
        "acc32",
        "acc64",
        "float32",
        "sunssf",
        "count",
    ]
)
#: Opaque state rather than a physical quantity: decoded, reported unitless.
_STATUS_TYPES = frozenset(["enum16", "enum32", "bitfield16", "bitfield32", "bitfield64"])


def _to_bytes(words: Sequence[int]) -> bytes:
    """SunSpec is always big-endian across registers — no word-order choice."""
    return b"".join(struct.pack(">H", int(w) & 0xFFFF) for w in words)


def decode_point(words: Sequence[int], ptype: str) -> float | None:
    """Decode one SunSpec point from exactly the registers it occupies.

    Returns ``None`` if the point holds the not-implemented sentinel for its
    type — SunSpec's way of saying the device has no such measurement — or if
    the type is one this module does not decode.
    """
    spec = _TYPES.get(ptype)
    if spec is None:
        return None
    fmt, nregs, sentinel = spec
    if len(words) != nregs:
        return None
    value = struct.unpack(fmt, _to_bytes(words))[0]
    if ptype == "float32":
        return None if value != value else float(value)  # NaN means not implemented
    if sentinel is not None and value == sentinel:
        return None
    return float(value)


# --------------------------------------------------------------------------
# Model definitions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PointDef:
    """One point within a SunSpec model's fixed block.

    Attributes:
        name: SunSpec point name, e.g. ``"SoC"``.
        offset: Register offset from the model's ID register.
        ptype: SunSpec wire type.
        size: Width in registers.
        sf: Scale factor — the name of a ``sunssf`` point in the same model, a
            literal exponent, or ``None``.
        units: Unit translated to one :func:`~otwin.io.source.to_si` accepts,
            ``"1"`` if unitless, or ``None`` if the device's unit could not be
            mapped — in which case the point is not delivered at all, because
            an unchecked unit is what this package refuses to pass on.
        raw_units: The unit string as the definition declared it.
        label: Human-readable label, when the definition supplies one.
    """

    name: str
    offset: int
    ptype: str
    size: int
    sf: str | int | None = None
    units: str | None = "1"
    raw_units: str = ""
    label: str = ""

    @property
    def deliverable(self) -> bool:
        """Whether this point becomes a tag with a numeric value."""
        if self.units is None:
            return False
        return self.ptype in _NUMERIC_TYPES or self.ptype in _STATUS_TYPES


@dataclass(frozen=True)
class ModelDef:
    """The fixed-block layout of one SunSpec model.

    Attributes:
        model_id: SunSpec model number.
        name: Model name from the definition, e.g. ``"battery"``.
        fixed_len: Registers in the fixed block, *including* ID and L. The
            device's own ``L`` may be larger (repeating groups) or smaller (an
            older revision); decoding uses whichever is smaller, so a short
            model is never read past its end.
        points: Every point in the fixed block, in offset order. May be a
            subset — see the module docstring.
        subset: True when this definition came from
            :data:`_BUILTIN_MODEL_DEFS` and omits official points.
    """

    model_id: int
    name: str
    fixed_len: int
    points: tuple[PointDef, ...]
    subset: bool = False

    def point(self, name: str) -> PointDef | None:
        """Look a point up by name, or ``None``."""
        for p in self.points:
            if p.name == name:
                return p
        return None


# SunSpec unit strings otwin.io.source does not spell the same way. Anything
# absent here goes to to_si() as-is; a unit neither knows makes the point
# undeliverable and lands in SunSpecSource.unmapped_points.
_SUNSPEC_UNITS: dict[str, str] = {
    "WH": "Wh",
    "Wh": "Wh",
    "VAh": "Wh",
    "Var": "var",
    "VAr": "var",
    "Varh": "varh",
    "VArh": "varh",
    "Pct": "percent",
    "%": "percent",
    "%WHRtg": "percent",
    "%ARtg": "percent",
    "%Max": "percent",
    "%Hz": "percent",
    "C": "degC",
    "Secs": "s",
    "ohms": "ohm",
    "bps": "1",
    "": "1",
}


def _translate_unit(raw: str | None) -> str | None:
    """SunSpec unit string to an otwin unit, or ``None`` if unmappable."""
    if not raw:
        return "1"
    mapped = _SUNSPEC_UNITS.get(raw, raw)
    try:
        si_unit(mapped)
    except UnknownUnitError:
        return None
    return mapped


# Curated fallback definitions, transcribed from the official SunSpec model
# JSON and verified against it by compare_model_defs. One record per point,
# ";"-separated, fields space-separated:
#
#     <offset> <name> <type> <size> <sf-or-dash> <units-or-dash>
#
# Value per model: (model name, fixed block length in registers, records).
# Used only when pysunspec2 is not installed.
_BUILTIN_MODEL_DEFS: dict[int, tuple[str, int, str]] = {
    1: (
        "common",
        68,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 Mn string 16 - -; 18 Md string 16 - -; "
            "34 Opt string 8 - -; 42 Vr string 8 - -; 50 SN string 16 - -; 66 DA uint16 1 - -"
        ),
    ),
    701: (
        "DERMeasureAC",
        155,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 10 W int16 1 W_SF W; "
            "11 VA int16 1 VA_SF VA; 12 Var int16 1 Var_SF Var; 13 PF int16 1 PF_SF -; "
            "14 A int16 1 A_SF A; 15 LLV uint16 1 V_SF V; 16 LNV uint16 1 V_SF V; "
            "17 Hz uint32 2 Hz_SF Hz; 19 TotWhInj uint64 4 TotWh_SF Wh; "
            "23 TotWhAbs uint64 4 TotWh_SF Wh; 35 TmpAmb int16 1 Tmp_SF C; "
            "37 TmpSnk int16 1 Tmp_SF C; 113 A_SF sunssf 1 - -; 114 V_SF sunssf 1 - -; "
            "115 Hz_SF sunssf 1 - -; 116 W_SF sunssf 1 - -; 117 PF_SF sunssf 1 - -; "
            "118 VA_SF sunssf 1 - -; 119 Var_SF sunssf 1 - -; 120 TotWh_SF sunssf 1 - -; "
            "122 Tmp_SF sunssf 1 - -"
        ),
    ),
    702: (
        "DERCapacity",
        52,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 WMaxRtg uint16 1 W_SF W; "
            "7 VAMaxRtg uint16 1 VA_SF VA; 10 WChaRteMaxRtg uint16 1 W_SF W; "
            "11 WDisChaRteMaxRtg uint16 1 W_SF W; 14 VNomRtg uint16 1 V_SF V; "
            "17 AMaxRtg uint16 1 A_SF A; 26 WMax uint16 1 W_SF W; "
            "34 WChaRteMax uint16 1 W_SF W; 35 WDisChaRteMax uint16 1 W_SF W; "
            "45 W_SF sunssf 1 - -; 47 VA_SF sunssf 1 - -; 49 V_SF sunssf 1 - -; "
            "50 A_SF sunssf 1 - -"
        ),
    ),
    704: (
        "DERCtlAC",
        59,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 15 WMaxLimPct uint16 1 WMaxLimPct_SF Pct; "
            "24 WSet int32 2 WSet_SF W; 28 WSetPct int16 1 WSetPct_SF Pct; "
            "38 VarSet int32 2 VarSet_SF Var; 42 VarSetPct int16 1 VarSetPct_SF Pct; "
            "54 WMaxLimPct_SF sunssf 1 - -; 55 WSet_SF sunssf 1 - -; "
            "56 WSetPct_SF sunssf 1 - -; 57 VarSet_SF sunssf 1 - -; "
            "58 VarSetPct_SF sunssf 1 - -"
        ),
    ),
    713: (
        "DERStorageCapacity",
        9,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 WHRtg uint16 1 WH_SF WH; "
            "3 WHAvail uint16 1 WH_SF WH; 4 SoC uint16 1 Pct_SF Pct; "
            "5 SoH uint16 1 Pct_SF Pct; 6 Sta enum16 1 - -; 7 WH_SF sunssf 1 - -; "
            "8 Pct_SF sunssf 1 - -"
        ),
    ),
    802: (
        "battery",
        64,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 AHRtg uint16 1 AHRtg_SF Ah; "
            "3 WHRtg uint16 1 WHRtg_SF Wh; 4 WChaRteMax uint16 1 WChaDisChaMax_SF W; "
            "5 WDisChaRteMax uint16 1 WChaDisChaMax_SF W; 7 SoCMax uint16 1 SoC_SF %WHRtg; "
            "8 SoCMin uint16 1 SoC_SF %WHRtg; 11 SoC uint16 1 SoC_SF %WHRtg; "
            "12 DoD uint16 1 DoD_SF %; 13 SoH uint16 1 SoH_SF %; 14 NCyc uint32 2 - -; "
            "34 V uint16 1 V_SF V; 37 CellVMax uint16 1 CellV_SF V; "
            "40 CellVMin uint16 1 CellV_SF V; 43 CellVAvg uint16 1 CellV_SF V; "
            "44 A int16 1 A_SF A; 47 W int16 1 W_SF W; 52 AHRtg_SF sunssf 1 - -; "
            "53 WHRtg_SF sunssf 1 - -; 54 WChaDisChaMax_SF sunssf 1 - -; "
            "56 SoC_SF sunssf 1 - -; 57 DoD_SF sunssf 1 - -; 58 SoH_SF sunssf 1 - -; "
            "59 V_SF sunssf 1 - -; 60 CellV_SF sunssf 1 - -; 61 A_SF sunssf 1 - -; "
            "63 W_SF sunssf 1 - -"
        ),
    ),
    803: (
        "lithium_ion_bank",
        28,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 NStr uint16 1 - -; "
            "3 NStrCon uint16 1 - -; 4 ModTmpMax int16 1 ModTmp_SF C; "
            "7 ModTmpMin int16 1 ModTmp_SF C; 10 ModTmpAvg int16 1 ModTmp_SF C; "
            "11 StrVMax uint16 1 V_SF V; 13 StrVMin uint16 1 V_SF V; "
            "15 StrVAvg uint16 1 V_SF V; 16 StrAMax int16 1 A_SF A; "
            "18 StrAMin int16 1 A_SF A; 20 StrAAvg int16 1 A_SF A; 21 NCellBal uint16 1 - -; "
            "23 ModTmp_SF sunssf 1 - -; 24 A_SF sunssf 1 - -; 27 V_SF sunssf 1 - -"
        ),
    ),
    804: (
        "lithium_ion_string",
        48,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 Idx uint16 1 - -; 3 NMod uint16 1 - -; "
            "8 SoC uint16 1 SoC_SF %; 9 DoD uint16 1 DoD_SF %; 10 NCyc uint32 2 - -; "
            "12 SoH uint16 1 SoH_SF %; 13 A int16 1 A_SF A; 14 V uint16 1 V_SF V; "
            "15 CellVMax uint16 1 CellV_SF V; 17 CellVMin uint16 1 CellV_SF V; "
            "19 CellVAvg uint16 1 CellV_SF V; 20 ModTmpMax int16 1 ModTmp_SF C; "
            "22 ModTmpMin int16 1 ModTmp_SF C; 24 ModTmpAvg int16 1 ModTmp_SF C; "
            "38 SoC_SF sunssf 1 - -; 39 SoH_SF sunssf 1 - -; 40 DoD_SF sunssf 1 - -; "
            "41 A_SF sunssf 1 - -; 42 V_SF sunssf 1 - -; 43 CellV_SF sunssf 1 - -; "
            "44 ModTmp_SF sunssf 1 - -"
        ),
    ),
    805: (
        "lithium-ion-module",
        44,
        (
            "0 ID uint16 1 - -; 1 L uint16 1 - -; 2 StrIdx uint16 1 - -; "
            "3 ModIdx uint16 1 - -; 4 NCell uint16 1 - -; 5 SoC uint16 1 SoC_SF %; "
            "6 DoD uint16 1 DoD_SF %; 7 SoH uint16 1 SoH_SF %; 8 NCyc uint32 2 - -; "
            "10 V uint16 1 V_SF V; 11 CellVMax uint16 1 CellV_SF V; "
            "13 CellVMin uint16 1 CellV_SF V; 15 CellVAvg uint16 1 CellV_SF V; "
            "16 CellTmpMax int16 1 Tmp_SF C; 18 CellTmpMin int16 1 Tmp_SF C; "
            "20 CellTmpAvg int16 1 Tmp_SF C; 38 SoC_SF sunssf 1 - -; 39 SoH_SF sunssf 1 - -; "
            "40 DoD_SF sunssf 1 - -; 41 V_SF sunssf 1 - -; 42 CellV_SF sunssf 1 - -; "
            "43 Tmp_SF sunssf 1 - -"
        ),
    ),
}


def _parse_builtin(model_id: int) -> ModelDef:
    """Expand one packed record string into a :class:`ModelDef`."""
    name, fixed_len, packed = _BUILTIN_MODEL_DEFS[model_id]
    points = []
    for record in packed.split(";"):
        record = record.strip()
        if not record:
            continue
        offset, pname, ptype, size, sf, units = record.split()
        sf_val: str | int | None = (
            None if sf == "-" else (int(sf) if sf.lstrip("-").isdigit() else sf)
        )
        raw_units = "" if units == "-" else units
        points.append(
            PointDef(
                name=pname,
                offset=int(offset),
                ptype=ptype,
                size=int(size),
                sf=sf_val,
                units=_translate_unit(raw_units),
                raw_units=raw_units,
                label=pname,
            )
        )
    return ModelDef(model_id, name, fixed_len, tuple(points), subset=True)


def _pysunspec2_model_dir() -> Path | None:
    """Directory of bundled official model JSON, if pysunspec2 is installed."""
    try:
        mod = importlib.import_module("sunspec2")
    except ImportError:
        return None
    root = Path(mod.__file__ or "").parent / "models" / "json"
    return root if root.is_dir() else None


def _parse_official(model_id: int, directory: Path) -> ModelDef | None:
    """Parse the fixed block of an official SunSpec model JSON definition."""
    import json

    path = directory / f"model_{model_id}.json"
    if not path.is_file():
        return None
    group = json.loads(path.read_text(encoding="utf-8")).get("group") or {}
    offset = 0
    points = []
    for p in group.get("points", []):
        size = int(p.get("size", 1))
        raw_units = str(p.get("units") or "")
        points.append(
            PointDef(
                name=p["name"],
                offset=offset,
                ptype=p.get("type", "uint16"),
                size=size,
                sf=p.get("sf"),
                units=_translate_unit(raw_units),
                raw_units=raw_units,
                label=p.get("label", p["name"]),
            )
        )
        offset += size
    if not points:
        return None
    return ModelDef(
        model_id, group.get("name", f"model_{model_id}"), offset, tuple(points)
    )


def load_model_def(model_id: int, prefer_installed: bool = True) -> ModelDef | None:
    """Return a model's fixed-block definition, or ``None`` if unknown.

    Args:
        model_id: SunSpec model number.
        prefer_installed: Use pysunspec2's official model JSON when available.
            ``False`` forces the curated built-in subset, which is what CI
            without the optional extra exercises.
    """
    if prefer_installed:
        directory = _pysunspec2_model_dir()
        if directory is not None:
            official = _parse_official(model_id, directory)
            if official is not None:
                return official
    if model_id in _BUILTIN_MODEL_DEFS:
        return _parse_builtin(model_id)
    return None


def compare_model_defs(model_id: int) -> list[str]:
    """Check the built-in subset against the official definition.

    Returns a list of discrepancies; empty means every built-in point has the
    same offset, type, size and scale factor as the official definition and
    the fixed lengths agree. Returns a one-item explanation if pysunspec2 is
    not installed.

    This exists because the built-in table was transcribed by hand, and a
    one-register error would silently shift every field after it.
    """
    directory = _pysunspec2_model_dir()
    if directory is None:
        return ["pysunspec2 is not installed; nothing to compare against"]
    official = _parse_official(model_id, directory)
    builtin = _parse_builtin(model_id)
    if official is None:
        return [f"model {model_id}: no official definition found in {directory}"]
    problems: list[str] = []
    if official.fixed_len != builtin.fixed_len:
        problems.append(
            f"model {model_id}: fixed_len {builtin.fixed_len} != official {official.fixed_len}"
        )
    for bp in builtin.points:
        op = official.point(bp.name)
        if op is None:
            problems.append(
                f"model {model_id}: point {bp.name} is not in the official definition"
            )
            continue
        for attr in ("offset", "ptype", "size", "sf"):
            if getattr(bp, attr) != getattr(op, attr):
                problems.append(
                    f"model {model_id}.{bp.name}: {attr} "
                    f"{getattr(bp, attr)!r} != official {getattr(op, attr)!r}"
                )
    return problems


@dataclass(frozen=True)
class ModelInstance:
    """One model found on the wire during discovery.

    Attributes:
        model_id: SunSpec model number read from the chain.
        address: Protocol address of this model's ID register.
        length: The device's own ``L`` — registers after ID and L.
        index: 0 for the first instance of this model number, 1 for the next.
            Devices legitimately publish several 804s, one per string.
        definition: The layout used to decode it, or ``None`` if unknown.
    """

    model_id: int
    address: int
    length: int
    index: int
    definition: ModelDef | None

    @property
    def prefix(self) -> str:
        """Tag-name prefix: ``"m802"``, or ``"m804#1"`` for repeats."""
        return (
            f"m{self.model_id}" if self.index == 0 else f"m{self.model_id}#{self.index}"
        )

    @property
    def total_registers(self) -> int:
        """Registers occupied including the ID and L header."""
        return self.length + 2


# --------------------------------------------------------------------------
# pysunspec2-backed transport
# --------------------------------------------------------------------------


def _import_pysunspec2_modbus() -> Any:
    try:
        return importlib.import_module("sunspec2.modbus.modbus")
    except ImportError as exc:
        raise MissingDependencyError(
            "the pysunspec2 transport requires the 'pysunspec2' package, which "
            "is not installed. Install it with:\n"
            "    pip install 'otwin[sunspec]'\n"
            "or directly:\n"
            "    pip install pysunspec2\n"
            "pysunspec2 is Apache-2.0 licensed and is an optional extra. "
            "SunSpecSource also works over the pymodbus transport "
            "(pip install 'otwin[modbus]'), and otwin.io.SunSpecSimulator needs "
            "neither."
        ) from exc


class PySunSpec2Transport:
    """A :class:`~otwin.io.source.RegisterTransport` backed by pysunspec2.

    Wraps ``sunspec2.modbus.modbus.ModbusClientTCP``. TCP only: pysunspec2
    models an RTU line as a shared bus rather than a per-device client, so for
    SunSpec over RTU pass a :class:`~otwin.io.modbus.PymodbusTransport`.

    Raises:
        MissingDependencyError: When pysunspec2 is not installed.
    """

    def __init__(
        self, host: str, port: int = 502, *, unit_id: int = 1, timeout: float = 3.0
    ) -> None:
        modbus = _import_pysunspec2_modbus()
        self.name = f"sunspec-tcp://{host}:{port}#{unit_id}"
        self._client = modbus.ModbusClientTCP(
            slave_id=unit_id, ipaddr=host, ipport=port, timeout=timeout
        )
        self._connected = False

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        """Read ``count`` registers via pysunspec2's Modbus client."""
        op = 3 if register_type == "holding" else 4
        try:
            if not self._connected:
                self._client.connect()
                self._connected = True
            data = self._client.read(address, count, op=op)
        except Exception as exc:
            self._connected = False
            raise TransportError(
                f"{self.name}: read at {address}+{count} failed: {exc}"
            ) from exc
        if isinstance(data, (bytes, bytearray)):
            if len(data) != count * 2:
                raise TransportError(
                    f"{self.name}: short frame at {address}: wanted {count * 2} "
                    f"bytes, got {len(data)}"
                )
            return [
                int(struct.unpack(">H", bytes(data[i : i + 2]))[0])
                for i in range(0, len(data), 2)
            ]
        regs = list(data or [])
        if len(regs) != count:
            raise TransportError(f"{self.name}: short frame at {address}")
        return [int(r) & 0xFFFF for r in regs]

    def close(self) -> None:
        """Disconnect. Idempotent."""
        # close must never raise: a failing teardown would mask the real
        # error that caused the caller to close in the first place.
        with contextlib.suppress(Exception):
            self._client.disconnect()
        self._connected = False


# --------------------------------------------------------------------------
# Source
# --------------------------------------------------------------------------


class SunSpecSource:
    """Discover and read a SunSpec device.

    Discovery runs on construction (or on first :meth:`read` if
    ``discover_now=False``) and populates :attr:`models`; each subsequent read
    fetches every discovered model's fixed block and decodes it.

    Args:
        host, port, unit_id: Live Modbus TCP endpoint.
        transport: A ready-made :class:`~otwin.io.source.RegisterTransport` —
            a simulator, or one you built. Connection arguments are then
            ignored and no optional package is needed.
        prefer: ``"pysunspec2"`` (default) or ``"pymodbus"``, choosing which
            optional package supplies the wire transport when ``transport`` is
            not given. Whichever is installed is used; if neither is, the
            error names both.
        base_addresses: Addresses to probe for the ``"SunS"`` marker.
        models: Restrict decoding to these model numbers.
        prefer_installed_defs: See :func:`load_model_def`.
        normalise_units: Convert every value to SI, so a state of charge
            arrives as a fraction whatever the device's scale factors say.
        max_stale_seconds: See :class:`~otwin.io.source.QualityTracker`.
        max_registers_per_read: Block read size, capped at the Modbus limit.
        name: Overrides the string recorded in :attr:`Sample.source`.
        discover_now: Run discovery in the constructor.
        timeout: Per-request timeout, live transports only.

    Attributes:
        last_error: Most recent read failure, or ``None`` after a clean cycle.
        device_info: Manufacturer, model, version and serial from the common
            model, if the device publishes one.
        unmapped_points: ``(model_id, point, unit)`` for points dropped
            because their unit could not be mapped to an SI quantity. Empty
            for the models this module names.

    Example:
        >>> from otwin.io import SunSpecSimulator
        >>> src = SunSpecSource(transport=SunSpecSimulator(soc=0.62))
        >>> round(src.soc(), 4)
        0.62
        >>> sorted({m.model_id for m in src.models})
        [1, 701, 713, 802]
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = 502,
        *,
        unit_id: int = 1,
        transport: RegisterTransport | None = None,
        prefer: str = "pysunspec2",
        base_addresses: Sequence[int] = SUNSPEC_BASE_ADDRESSES,
        models: Iterable[int] | None = None,
        prefer_installed_defs: bool = True,
        normalise_units: bool = True,
        max_stale_seconds: float | None = None,
        max_registers_per_read: int = _MAX_REGISTERS_PER_READ,
        name: str | None = None,
        discover_now: bool = True,
        timeout: float = 3.0,
    ) -> None:
        if not 1 <= max_registers_per_read <= _MAX_REGISTERS_PER_READ:
            raise ValueError(
                f"max_registers_per_read must be 1..{_MAX_REGISTERS_PER_READ}"
            )
        self.base_addresses = tuple(int(a) for a in base_addresses)
        self.model_filter = None if models is None else {int(m) for m in models}
        self.prefer_installed_defs = bool(prefer_installed_defs)
        self.normalise_units = bool(normalise_units)
        self.max_registers_per_read = int(max_registers_per_read)
        self.last_error: Exception | None = None
        self.device_info: dict[str, str] = {}
        self.unmapped_points: list[tuple[int, str, str]] = []
        self._quality = QualityTracker(max_stale_seconds=max_stale_seconds)
        self._models: list[ModelInstance] | None = None
        self._base: int | None = None
        self._closed = False

        if transport is not None:
            self._transport: RegisterTransport = transport
            default_name = getattr(transport, "name", type(transport).__name__)
        elif host is not None:
            self._transport = self._build_transport(prefer, host, port, unit_id, timeout)
            default_name = getattr(self._transport, "name", host)
        else:
            raise ValueError("give either host= for a live device or transport=")
        self.name = name or str(default_name)
        if discover_now:
            self.discover()

    @staticmethod
    def _build_transport(
        prefer: str, host: str, port: int, unit_id: int, timeout: float
    ) -> RegisterTransport:
        """Pick a wire transport, preferring whichever extra is installed."""
        if prefer not in ("pysunspec2", "pymodbus"):
            raise ValueError(f"prefer must be 'pysunspec2' or 'pymodbus', got {prefer!r}")
        from .modbus import PymodbusTransport

        order = (
            [PySunSpec2Transport, PymodbusTransport]
            if prefer == "pysunspec2"
            else [PymodbusTransport, PySunSpec2Transport]
        )
        errors: list[str] = []
        for factory in order:
            try:
                if factory is PySunSpec2Transport:
                    return PySunSpec2Transport(
                        host, port, unit_id=unit_id, timeout=timeout
                    )
                return PymodbusTransport(host, port, unit_id=unit_id, timeout=timeout)
            except MissingDependencyError as exc:
                errors.append(str(exc).splitlines()[0])
        raise MissingDependencyError(
            "live SunSpec I/O needs one of the optional packages 'pysunspec2' "
            "or 'pymodbus', and neither is installed. Install one with:\n"
            "    pip install 'otwin[sunspec]'      # pysunspec2, Apache-2.0\n"
            "    pip install 'otwin[modbus]'       # pymodbus, BSD-3-Clause\n"
            "Neither is needed for otwin.io.SunSpecSimulator, which drives the "
            "identical decode path.\nUnderlying errors: " + "; ".join(errors)
        )

    # -- discovery --------------------------------------------------------

    def discover(self) -> list[ModelInstance]:
        """Walk the SunSpec model chain and cache the result.

        Probes each base address for the ``"SunS"`` identifier, then follows
        the ``(model id, length)`` headers to the ``0xFFFF`` end marker, an
        implausible length, or 128 models — whichever comes first, because a
        device that mis-reports a length would otherwise walk the address
        space forever.

        Raises:
            TransportError: If no base address carries the identifier. Unlike
                a read failure this is fatal: there is nothing to decode and
                no previous value to fall back on.
        """
        base = self._find_base()
        addr = base + 2
        found: list[ModelInstance] = []
        counts: dict[int, int] = {}
        for _ in range(_MAX_MODELS):
            header = self._transport.read_registers(addr, 2, "holding")
            model_id, length = int(header[0]), int(header[1])
            if model_id == _END_MODEL_ID:
                break
            if length < 0 or length > 4096:
                raise TransportError(
                    f"{self.name}: model {model_id} at {addr} reports an "
                    f"implausible length {length}; the chain is corrupt"
                )
            index = counts.get(model_id, 0)
            counts[model_id] = index + 1
            definition = None
            if self.model_filter is None or model_id in self.model_filter:
                definition = load_model_def(model_id, self.prefer_installed_defs)
            found.append(ModelInstance(model_id, addr, length, index, definition))
            addr += length + 2
        self._models = found
        self._base = base
        self._collect_unmapped()
        self._read_device_info()
        return found

    def _find_base(self) -> int:
        errors: list[str] = []
        for base in self.base_addresses:
            try:
                words = self._transport.read_registers(base, 2, "holding")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
                continue
            if tuple(int(w) for w in words[:2]) == SUNSPEC_IDENTIFIER:
                return base
            errors.append(f"{base}: no 'SunS' marker (read {words[:2]})")
        raise TransportError(
            f"{self.name}: no SunSpec model chain at any of "
            f"{list(self.base_addresses)}. Details: {'; '.join(errors)}"
        )

    def _collect_unmapped(self) -> None:
        seen: set[tuple[int, str]] = set()
        self.unmapped_points = []
        for inst in self._models or []:
            if inst.definition is None:
                continue
            for p in inst.definition.points:
                if p.units is None and (inst.model_id, p.name) not in seen:
                    seen.add((inst.model_id, p.name))
                    self.unmapped_points.append((inst.model_id, p.name, p.raw_units))

    def _read_device_info(self) -> None:
        """Decode the common model's strings into :attr:`device_info`."""
        for inst in self._models or []:
            if inst.model_id != 1 or inst.definition is None:
                continue
            try:
                words = self._read_block(inst)
            except Exception as exc:
                self.last_error = exc
                return
            labels = {
                "Mn": "manufacturer",
                "Md": "model",
                "Vr": "version",
                "SN": "serial",
            }
            for p in inst.definition.points:
                if p.ptype != "string" or p.name not in labels:
                    continue
                chunk = words[p.offset : p.offset + p.size]
                if len(chunk) != p.size:
                    continue
                text = _to_bytes(chunk).decode("latin-1").split("\x00", 1)[0].strip()
                if text:
                    self.device_info[labels[p.name]] = text
            return

    @property
    def models(self) -> list[ModelInstance]:
        """The discovered chain, running discovery if it has not run."""
        if self._models is None:
            self.discover()
        assert self._models is not None
        return self._models

    @property
    def base_address(self) -> int | None:
        """The address the ``"SunS"`` marker was found at."""
        return self._base

    # -- tags and reading -------------------------------------------------

    def _deliverable(self, inst: ModelInstance) -> list[PointDef]:
        """Points of ``inst`` that become tags, in offset order.

        Excludes the ID/L header (structure, not measurement), ``sunssf``
        points (metadata about other points, already applied), strings and
        padding, anything with an unmappable unit, and anything beyond the
        length the device itself reports.
        """
        if inst.definition is None:
            return []
        limit = min(inst.definition.fixed_len, inst.total_registers)
        return [
            p
            for p in inst.definition.points
            if p.deliverable
            and p.ptype != "sunssf"
            and not (p.offset < 2 and p.name in ("ID", "L"))
            and p.offset + p.size <= limit
        ]

    def tags(self) -> list[TagSpec]:
        """One :class:`TagSpec` per deliverable point, carrying provenance.

        ``sunspec_model`` and ``sunspec_point`` are what let a manifest say
        "this number is model 802 point SoC at register 40123", which is the
        difference between a twin you can audit and one you cannot.
        """
        out: list[TagSpec] = []
        for inst in self.models:
            for p in self._deliverable(inst):
                raw_unit = p.units or "1"
                model_name = MODEL_NAMES.get(
                    inst.model_id, inst.definition.name if inst.definition else ""
                )
                out.append(
                    TagSpec(
                        name=f"{inst.prefix}.{p.name}",
                        unit=si_unit(raw_unit) if self.normalise_units else raw_unit,
                        description=(
                            f"{p.label or p.name} — SunSpec model {inst.model_id} "
                            f"({model_name}) point {p.name}"
                        ),
                        dtype=p.ptype,
                        raw_unit=raw_unit,
                        sunspec_model=inst.model_id,
                        sunspec_point=p.name,
                        address=inst.address + p.offset,
                    )
                )
        return out

    def _read_block(self, inst: ModelInstance) -> list[int]:
        """Read a whole model, in chunks of at most 125 registers."""
        total = inst.total_registers
        words: list[int] = []
        offset = 0
        while offset < total:
            count = min(self.max_registers_per_read, total - offset)
            words.extend(
                self._transport.read_registers(inst.address + offset, count, "holding")
            )
            offset += count
        return words

    def _scale(self, point: PointDef, raw: dict[str, float | None]) -> float:
        """Resolve a point's scale factor to a multiplier.

        A named scale factor whose register holds the not-implemented
        sentinel is treated as an exponent of zero; the alternative is
        multiplying by 10**-32768.

        Raises:
            ScaleFactorError: If the exponent falls outside
                :data:`SUNSSF_RANGE`. ``10.0 ** 400`` raises ``OverflowError``
                in CPython, which used to escape :meth:`read` and lose the
                whole sample -- every other model on the chain included --
                because one register on one model was corrupt. The exponent is
                now checked before it is used, and the caller degrades the
                points that depend on it.
        """
        if point.sf is None:
            return 1.0
        exponent = point.sf if isinstance(point.sf, int) else raw.get(point.sf)
        if exponent is None:
            return 1.0
        low, high = SUNSSF_RANGE
        e = int(exponent)
        if not low <= e <= high:
            raise ScaleFactorError(
                f"scale factor {point.sf!r} for point {point.name!r} reads {e}, "
                f"outside the SunSpec range [{low}, {high}]. This is a corrupt "
                f"or mis-mapped sunssf register, not an exponent."
            )
        return float(10.0**e)

    def read(self) -> Sample:
        """Read every discovered model once and return a :class:`Sample`.

        A model whose block read fails degrades all of its tags to ``"stale"``
        or ``"bad"`` and records the exception in :attr:`last_error`; other
        models are still read. Points holding the SunSpec not-implemented
        sentinel degrade the same way, because the device is saying it has no
        such measurement, and so do points whose scale-factor register is
        outside :data:`SUNSSF_RANGE`.

        This method does not raise for a wire-level problem. Everything it can
        say about a link that is misbehaving, it says through ``quality``.
        """
        now = time.time()
        self.last_error = None
        values: dict[str, float] = {}
        quality: dict[str, str] = {}

        for inst in self.models:
            points = self._deliverable(inst)
            if inst.definition is None or not points:
                continue
            try:
                words = self._read_block(inst)
            except Exception as exc:
                self.last_error = exc
                for p in points:
                    tag = f"{inst.prefix}.{p.name}"
                    values[tag], quality[tag] = self._quality.resolve_failed(tag, now)
                continue

            raw: dict[str, float | None] = {}
            for p in inst.definition.points:
                if p.offset + p.size <= len(words):
                    raw[p.name] = decode_point(
                        words[p.offset : p.offset + p.size], p.ptype
                    )

            for p in points:
                tag = f"{inst.prefix}.{p.name}"
                value = raw.get(p.name)
                if value is None:
                    values[tag], quality[tag] = self._quality.resolve_failed(tag, now)
                    continue
                try:
                    scaled = value * self._scale(p, raw)
                except ScaleFactorError as exc:
                    # Same treatment as a failed block read: this point is not
                    # readable, the rest of the chain is unaffected. A corrupt
                    # scale factor is a wire-level problem, and read() does not
                    # raise for those.
                    self.last_error = exc
                    values[tag], quality[tag] = self._quality.resolve_failed(tag, now)
                    continue
                final = to_si(scaled, p.units or "1") if self.normalise_units else scaled
                values[tag] = final
                quality[tag] = "good"
                self._quality.record_good(tag, final, now)

        return Sample(timestamp=now, values=values, quality=quality, source=self.name)

    def soc(self, sample: Sample | None = None) -> float:
        """State of charge as a fraction in ``[0, 1]``.

        Prefers model 713 (``DERStorageCapacity.SoC``, the grid-interface view
        defined by IEEE 1547-2018) and falls back to model 802
        (``battery.SoC``, the BMS view). The two can legitimately differ: 713
        is what the DER reports to the grid operator and may apply usable-
        window limits to 802's number.

        The fallback is on readability, not only on publication. Among the
        models that publish an ``SoC``, the first one reading ``"good"`` is
        used; if none is good, the first one reading ``"stale"`` is used,
        because a state of charge from the last cycle is better information
        than none. Only when every published view is ``"bad"`` does this
        raise.

        A value outside ``[0, 1]`` is *not* a reason to fall back. It means a
        scale factor is misapplied on a link that is otherwise answering, and
        quietly reading the other model would leave that broken for as long as
        the second view held up.

        Args:
            sample: Reuse an existing sample instead of reading again.

        Raises:
            LookupError: If the device publishes neither model with a
                decodable ``SoC``.
            TransportError: If every published view is unreadable.
            ValueError: If the value falls outside ``[0, 1]`` — almost always
                a misapplied scale factor, and a twin fed SoC = 85.4 produces
                nonsense quietly.
        """
        sample = self.read() if sample is None else sample
        candidates = [
            f"{inst.prefix}.SoC"
            for model_id in (713, 802)
            for inst in self.models
            if inst.model_id == model_id
            and inst.definition is not None
            and inst.definition.point("SoC") is not None
        ]
        candidates = [c for c in candidates if c in sample.values]
        if not candidates:
            raise LookupError(
                f"{self.name}: no state of charge available. SoC is read from "
                f"SunSpec model 713 (DERStorageCapacity) or model 802 "
                f"(battery); this device publishes models "
                f"{sorted({m.model_id for m in self.models})}. If the battery "
                f"is behind a separate BMS, point a second SunSpecSource at it."
            )
        # Rank by readability, then by the model preference already encoded in
        # the order of `candidates`. Picking candidates[0] and giving up if it
        # read badly threw away a working second view: a bank publishing both
        # models, whose 713 block stops answering while 802 reads cleanly, lost
        # its state of charge entirely -- which is the exact case the fallback
        # was written for.
        readable = [c for c in candidates if sample.quality.get(c) == "good"]
        readable += [c for c in candidates if sample.quality.get(c) == "stale"]
        if not readable:
            reported = ", ".join(
                f"{c}={sample.quality.get(c, 'unknown')}" for c in candidates
            )
            raise TransportError(
                f"{self.name}: state of charge is not readable from any model "
                f"that publishes it ({reported}); last error: {self.last_error}"
            )
        tag = readable[0]
        value = sample.values[tag]
        if not self.normalise_units:
            value = value / 100.0
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{self.name}: {tag} decoded to {value!r}, which is not a "
                f"fraction in [0, 1]. This is almost always a scale-factor "
                f"problem: check the device's SoC_SF / Pct_SF register."
            )
        return float(value)

    def close(self) -> None:
        """Close the transport. Idempotent."""
        if not self._closed:
            self._closed = True
            self._transport.close()

    def __enter__(self) -> SunSpecSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        found = (
            "not discovered" if self._models is None else f"{len(self._models)} models"
        )
        return f"SunSpecSource({self.name!r}, {found}, base={self._base})"
