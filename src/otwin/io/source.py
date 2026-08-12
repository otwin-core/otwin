"""The common field-source contract: samples, tags, quality and units.

Every live source in :mod:`otwin.io` — raw Modbus, SunSpec, or a simulator —
produces the same thing: a :class:`Sample`, a timestamped dictionary of
SI-normalised floats plus a per-tag quality flag. Downstream estimators never
learn which protocol a number came from.

**Units are mandatory.** A :class:`TagSpec` cannot be built without one, and
:func:`to_si` raises on a unit it does not recognise rather than passing the
value through. A twin fed kW where it expects W is off by 1000 and still
produces a smooth, plausible trajectory; the error is invisible until someone
compares it against a meter.

**Quality is per tag, not per sample.** On a plant network one register times
out while the other 200 are fine, and a connector that raises then takes the
twin down for a cabling fault. See :class:`QualityTracker`.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias, runtime_checkable

__all__ = [
    "Quality",
    "Sample",
    "TagSpec",
    "Source",
    "RegisterTransport",
    "QualityTracker",
    "MissingDependencyError",
    "UnknownUnitError",
    "TransportError",
    "to_si",
    "si_unit",
    "normalise",
    "KNOWN_UNITS",
]

#: Per-tag data quality. ``"good"`` = read this cycle; ``"stale"`` = last known
#: good value, retained across a failed read; ``"bad"`` = no usable value, and
#: the entry in :attr:`Sample.values` is NaN.
Quality: TypeAlias = Literal["good", "stale", "bad"]

_NO_INHERIT = (
    "Otwin protocols are for isinstance checks and static typing, not for "
    "inheritance. Write a plain class with the required methods — structural "
    "typing will recognise it. See otwin.interfaces.protocols."
)


class MissingDependencyError(ImportError):
    """An optional connector dependency is not installed.

    Raised only when a live connection is attempted, never at import time. The
    message names both the package and the extra to install.
    """


class UnknownUnitError(ValueError):
    """A unit string is not in :data:`KNOWN_UNITS`. Deliberately an error."""


class TransportError(OSError):
    """A read failed at the wire level: timeout, exception code, short frame.

    Sources catch this (and anything else a transport raises) and degrade
    quality rather than propagating it.
    """


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

# Canonical unit -> (multiplier, additive offset, resulting SI unit), so that
# value_si = value * multiplier + offset.
_SI: dict[str, tuple[float, float, str]] = {
    "mW": (1e-3, 0.0, "W"),
    "W": (1.0, 0.0, "W"),
    "kW": (1e3, 0.0, "W"),
    "MW": (1e6, 0.0, "W"),
    "GW": (1e9, 0.0, "W"),
    # Apparent and reactive power keep their own names: the SI unit is the
    # watt, but confusing them with active power is a different, worse error.
    "VA": (1.0, 0.0, "VA"),
    "kVA": (1e3, 0.0, "VA"),
    "MVA": (1e6, 0.0, "VA"),
    "var": (1.0, 0.0, "var"),
    "kvar": (1e3, 0.0, "var"),
    "Mvar": (1e6, 0.0, "var"),
    "Wh": (1.0, 0.0, "Wh"),
    "kWh": (1e3, 0.0, "Wh"),
    "MWh": (1e6, 0.0, "Wh"),
    "GWh": (1e9, 0.0, "Wh"),
    "varh": (1.0, 0.0, "varh"),
    "kvarh": (1e3, 0.0, "varh"),
    "Mvarh": (1e6, 0.0, "varh"),
    "J": (1.0, 0.0, "J"),
    "kJ": (1e3, 0.0, "J"),
    "MJ": (1e6, 0.0, "J"),
    "mA": (1e-3, 0.0, "A"),
    "A": (1.0, 0.0, "A"),
    "kA": (1e3, 0.0, "A"),
    # Charge normalises to coulombs, which is what SI says even though a
    # battery engineer thinks in amp-hours. 100 Ah arrives as 360000 C.
    "mAh": (3.6, 0.0, "C"),
    "Ah": (3600.0, 0.0, "C"),
    "kAh": (3.6e6, 0.0, "C"),
    "mV": (1e-3, 0.0, "V"),
    "V": (1.0, 0.0, "V"),
    "kV": (1e3, 0.0, "V"),
    "degC": (1.0, 273.15, "K"),
    "K": (1.0, 0.0, "K"),
    "mHz": (1e-3, 0.0, "Hz"),
    "Hz": (1.0, 0.0, "Hz"),
    "kHz": (1e3, 0.0, "Hz"),
    "s": (1.0, 0.0, "s"),
    "ms": (1e-3, 0.0, "s"),
    "min": (60.0, 0.0, "s"),
    "h": (3600.0, 0.0, "s"),
    "mohm": (1e-3, 0.0, "ohm"),
    "ohm": (1.0, 0.0, "ohm"),
    "S": (1.0, 0.0, "S"),
    "percent": (0.01, 0.0, "1"),
    "1": (1.0, 0.0, "1"),
    "count": (1.0, 0.0, "1"),
}

# Vendor and SunSpec spellings mapped onto the canonical names above. Lookup is
# exact and case-sensitive throughout: a case-insensitive table would make
# "mW" and "MW" the same unit, a factor of 10^9.
_ALIASES: dict[str, str] = {
    "": "1",
    "-": "1",
    "none": "1",
    "None": "1",
    "fraction": "1",
    "pu": "1",
    "pct": "percent",
    "Pct": "percent",
    "%": "percent",
    "%WHRtg": "percent",
    "%Max": "percent",
    "C": "degC",
    "°C": "degC",
    "degc": "degC",
    "Celsius": "degC",
    "WH": "Wh",
    "KWH": "kWh",
    "kwh": "kWh",
    "Var": "var",
    "VAr": "var",
    "VAR": "var",
    "kVar": "kvar",
    "Varh": "varh",
    "VArh": "varh",
    "Secs": "s",
    "sec": "s",
    "Sec": "s",
    "Hours": "h",
    "hr": "h",
    "Ohms": "ohm",
    "Siemens": "S",
    "AH": "Ah",
}

#: Every unit string accepted by :func:`to_si`, canonical names and aliases.
KNOWN_UNITS: frozenset[str] = frozenset(_SI) | frozenset(_ALIASES)


def _canonical(unit: str) -> str:
    if unit in _SI:
        return unit
    if unit in _ALIASES:
        return _ALIASES[unit]
    raise UnknownUnitError(
        f"unknown unit {unit!r}. otwin.io refuses to pass an unrecognised unit "
        f"through unconverted, because a silent kW/W mix-up is undetectable "
        f"downstream. Known units: {', '.join(sorted(KNOWN_UNITS - {''}))}. "
        f"If this unit is real, add it to otwin.io.source._SI."
    )


def to_si(value: float, unit: str) -> float:
    """Convert ``value`` from ``unit`` to SI: W, Wh, A, C, V, K, Hz, s, or a
    bare fraction for percentages.

    Raises:
        UnknownUnitError: If ``unit`` is not recognised.

    Example:
        >>> to_si(1.5, "kW"), to_si(50.0, "percent"), round(to_si(25.0, "degC"), 2)
        (1500.0, 0.5, 298.15)
    """
    mult, offset, _ = _SI[_canonical(unit)]
    return float(value) * mult + offset


def si_unit(unit: str) -> str:
    """The SI unit :func:`to_si` produces for ``unit``.

    Example:
        >>> si_unit("MWh"), si_unit("%"), si_unit("degC")
        ('Wh', '1', 'K')
    """
    return _SI[_canonical(unit)][2]


def normalise(value: float, unit: str) -> tuple[float, str]:
    """Return ``(value_in_si, si_unit)`` in one call."""
    return to_si(value, unit), si_unit(unit)


# --------------------------------------------------------------------------
# Samples and tags
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TagSpec:
    """The identity, unit and provenance of one measured quantity.

    Attributes:
        name: Tag name as it appears in :attr:`Sample.values`.
        unit: Unit of the *delivered* value — the SI unit when the source
            normalises, which it does by default.
        description: What the number means.
        dtype: Wire type it was decoded from (``"uint16"``, ``"float32"``,
            ``"string"``, ...). Provenance, not dispatch.
        raw_unit: The unit the device declared, before normalisation.
        sunspec_model: SunSpec model number, e.g. ``802``. ``None`` for raw
            Modbus tags.
        sunspec_point: SunSpec point name, e.g. ``"SoC"``. ``None`` for raw
            Modbus tags.
        address: Register address the value was decoded from, where known.

    Raises:
        UnknownUnitError: If ``unit`` is not recognised. A tag without a
            meaningful unit cannot be constructed at all.
    """

    name: str
    unit: str
    description: str
    dtype: str
    raw_unit: str | None = None
    sunspec_model: int | None = None
    sunspec_point: str | None = None
    address: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TagSpec.name must be non-empty")
        _canonical(self.unit)
        if self.raw_unit is not None:
            _canonical(self.raw_unit)


@dataclass(frozen=True)
class Sample:
    """One timestamped read of every tag a source exposes.

    Attributes:
        timestamp: UTC epoch seconds when the read cycle started (host clock,
            not a device timestamp).
        values: Tag name to value, in the unit of the matching
            :class:`TagSpec`. A tag whose quality is ``"bad"`` is present with
            value ``nan``, so the key set is stable and callers can build
            arrays without checking membership. Tags whose wire type is
            ``"string"`` are absent — this dict is floats only.
        quality: Tag name to ``"good"`` / ``"stale"`` / ``"bad"``, for every
            tag including the string ones.
        source: Human-readable origin, e.g. ``"modbus-tcp://10.0.0.7:502#1"``.
    """

    timestamp: float
    values: dict[str, float]
    quality: dict[str, str]
    source: str

    def __post_init__(self) -> None:
        bad = {q for q in self.quality.values() if q not in ("good", "stale", "bad")}
        if bad:
            raise ValueError(
                f"invalid quality flags {sorted(bad)}; expected good/stale/bad"
            )
        missing = set(self.values) - set(self.quality)
        if missing:
            raise ValueError(f"values without a quality flag: {sorted(missing)}")

    def good(self) -> dict[str, float]:
        """Only the values read successfully this cycle."""
        return {k: v for k, v in self.values.items() if self.quality.get(k) == "good"}

    def usable(self) -> dict[str, float]:
        """Values that are ``"good"`` or ``"stale"`` — i.e. finite and known."""
        return {
            k: v
            for k, v in self.values.items()
            if self.quality.get(k) in ("good", "stale")
        }


@runtime_checkable
class Source(Protocol):
    """Anything that yields :class:`Sample` objects from a field device.

    Structural, like every Otwin protocol: do not inherit, just implement the
    three methods.

    Example:
        >>> import time
        >>> class Flat:
        ...     def read(self):
        ...         return Sample(time.time(), {"p": 0.0}, {"p": "good"}, "flat")
        ...     def tags(self):
        ...         return [TagSpec("p", "W", "constant zero", "float32")]
        ...     def close(self):
        ...         pass
        >>> isinstance(Flat(), Source)
        True
    """

    def read(self) -> Sample:
        """Read every tag once. Must not raise on a wire failure; degrade."""
        raise NotImplementedError(_NO_INHERIT)

    def tags(self) -> list[TagSpec]:
        """Describe every tag this source produces, in a stable order."""
        raise NotImplementedError(_NO_INHERIT)

    def close(self) -> None:
        """Release the connection. Idempotent."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class RegisterTransport(Protocol):
    """The one thing live connectors and simulators share: 16-bit registers.

    Splitting this out is what makes CI possible without hardware. The
    simulators implement exactly this, so a simulated read travels through the
    same decoding, scale-factor and unit code as a real one.
    """

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        """Return ``count`` words from ``address``.

        Args:
            address: Zero-based Modbus protocol address, not 4xxxx notation.
            count: Number of 16-bit registers.
            register_type: ``"holding"`` (function 3) or ``"input"`` (4).

        Raises:
            TransportError: On timeout, exception response or short frame.
        """
        raise NotImplementedError(_NO_INHERIT)

    def close(self) -> None:
        """Release the connection. Idempotent."""
        raise NotImplementedError(_NO_INHERIT)


# --------------------------------------------------------------------------
# Quality bookkeeping
# --------------------------------------------------------------------------


@dataclass
class QualityTracker:
    """Turns per-tag read outcomes into values and quality flags.

    The ladder both connectors share: ``good`` (decoded this cycle);
    ``stale`` (the read failed but a previous value exists, and is served
    again with the flag set, so control code that must not act on an old
    number can check while a trend plot can ignore it); ``bad`` (no previous
    value, or one older than :attr:`max_stale_seconds` — the value is NaN).

    Attributes:
        max_stale_seconds: How long a value may be served as ``"stale"``.
            ``None`` (default) serves it indefinitely, which is right for
            capacity ratings and wrong for fast measurements — set it
            explicitly when the tags are fast.
    """

    max_stale_seconds: float | None = None
    _last_good: dict[str, float] = field(default_factory=dict, repr=False)
    _last_good_at: dict[str, float] = field(default_factory=dict, repr=False)

    def record_good(self, name: str, value: float, now: float | None = None) -> None:
        """Store a freshly decoded value for ``name``."""
        self._last_good[name] = float(value)
        self._last_good_at[name] = time.time() if now is None else now

    def resolve_failed(
        self, name: str, now: float | None = None
    ) -> tuple[float, Quality]:
        """Return ``(value, quality)`` for a tag whose read failed this cycle."""
        if name not in self._last_good:
            return math.nan, "bad"
        if self.max_stale_seconds is not None:
            age = (time.time() if now is None else now) - self._last_good_at[name]
            if age > self.max_stale_seconds:
                return math.nan, "bad"
        return self._last_good[name], "stale"

    def last_good(self, name: str) -> float | None:
        """The last value recorded as good for ``name``, or ``None``."""
        return self._last_good.get(name)

    def forget(self) -> None:
        """Drop all retained values. The next failed read yields ``"bad"``."""
        self._last_good.clear()
        self._last_good_at.clear()
