"""Units: what a file says, what the twin stores, and the check between them.

Internally every value is SI: energy in joules, volume in cubic metres,
temperature in kelvin, power in watts, irradiance in W/m^2 and money in
euros. Files say ``kWh``, ``Wh``, ``m³``, ``°C``, ``ºC`` (with the Spanish
ordinal sign), ``litros``... :func:`parse_unit` maps each spelling to one
canonical unit and refuses anything it does not know. Lookup is
case-sensitive wherever case changes the meaning: ``MWh`` and ``mWh`` differ
by a factor of 10^9, so only spellings that cannot be confused are matched
without regard to case.
"""

from __future__ import annotations

import re

import numpy as np
import numpy.typing as npt

__all__ = [
    "SI_UNIT",
    "parse_unit",
    "dimension_of",
    "to_si",
    "from_si",
    "unit_in_header",
]

#: The SI unit each dimension is stored in.
SI_UNIT: dict[str, str] = {
    "energy": "J",
    "volume": "m^3",
    "temperature": "K",
    "power": "W",
    "irradiance": "W/m^2",
    "currency": "EUR",
}

# canonical unit -> (dimension, multiplier, offset): si = value * multiplier + offset
_UNITS: dict[str, tuple[str, float, float]] = {
    "J": ("energy", 1.0, 0.0),
    "kJ": ("energy", 1e3, 0.0),
    "MJ": ("energy", 1e6, 0.0),
    "Wh": ("energy", 3600.0, 0.0),
    "kWh": ("energy", 3.6e6, 0.0),
    "MWh": ("energy", 3.6e9, 0.0),
    "m^3": ("volume", 1.0, 0.0),
    "L": ("volume", 1e-3, 0.0),
    "K": ("temperature", 1.0, 0.0),
    "degC": ("temperature", 1.0, 273.15),
    "degF": ("temperature", 5.0 / 9.0, 459.67 * 5.0 / 9.0),
    "W": ("power", 1.0, 0.0),
    "kW": ("power", 1e3, 0.0),
    "W/m^2": ("irradiance", 1.0, 0.0),
    "EUR": ("currency", 1.0, 0.0),
}

# Spellings matched exactly, after the light normalisation in _squash.
_EXACT: dict[str, str] = {
    "MWh": "MWh",
    "MJ": "MJ",
    "kJ": "kJ",
    "kW": "kW",
    "W": "W",
    "K": "K",
    "J": "J",
    "L": "L",
}

# Spellings that cannot be confused, matched without regard to case.
_ANY_CASE: dict[str, str] = {
    "wh": "Wh",
    "kwh": "kWh",
    "m3": "m^3",
    "m^3": "m^3",
    "l": "L",
    "litre": "L",
    "litres": "L",
    "liter": "L",
    "liters": "L",
    "litro": "L",
    "litros": "L",
    "°c": "degC",
    "degc": "degC",
    "celsius": "degC",
    "°f": "degF",
    "degf": "degF",
    "kelvin": "K",
    "w/m2": "W/m^2",
    "w/m^2": "W/m^2",
    "wm-2": "W/m^2",
    "eur": "EUR",
    "€": "EUR",
    "euro": "EUR",
    "euros": "EUR",
}


def _squash(text: str) -> str:
    """Drop spaces and unify the superscripts and degree signs files use."""
    return (
        text.strip()
        .replace(" ", "")
        .replace("³", "3")
        .replace("²", "2")
        .replace("º", "°")  # Spanish ordinal sign, often typed for a degree
        .replace("˚", "°")
    )


def parse_unit(text: str) -> str:
    """The canonical name of a unit as written in a file.

    Raises:
        ValueError: the unit is not one this package knows.

    >>> parse_unit("kWh"), parse_unit("m³"), parse_unit("ºC"), parse_unit("W/m²")
    ('kWh', 'm^3', 'degC', 'W/m^2')
    """
    raw = _squash(text)
    if raw in _UNITS:
        return raw
    if raw in _EXACT:
        return _EXACT[raw]
    key = raw.lower()
    if key in _ANY_CASE:
        return _ANY_CASE[key]
    known = ", ".join(sorted(_UNITS))
    raise ValueError(f"unknown unit {text!r}; known units are {known}")


def dimension_of(unit: str) -> str:
    """``"energy"``, ``"volume"``, ``"temperature"``... for a canonical unit."""
    return _UNITS[unit][0]


def to_si(values: npt.ArrayLike, unit: str) -> np.ndarray:
    """Convert values in ``unit`` (canonical name) to the SI unit of its dimension."""
    _, mult, off = _UNITS[unit]
    return np.asarray(values, dtype=float) * mult + off


def from_si(values: npt.ArrayLike, unit: str) -> np.ndarray:
    """Convert SI values to ``unit`` (canonical name); the inverse of :func:`to_si`."""
    _, mult, off = _UNITS[unit]
    return (np.asarray(values, dtype=float) - off) / mult


_BRACKETS = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]")


def unit_in_header(header: str) -> str | None:
    """The unit a column header declares, or ``None`` if it declares none.

    Reads ``"Energy Usage (kWh)"``, ``"temperature_2m (°C)"``, ``"Lectura [m3]"``
    and the suffix forms ``"Consumo_kWh"``, ``"CONSUMO Wh"``, ``"AE_kWh"``.

    >>> unit_in_header("Consumo_kWh"), unit_in_header("CONSUMO Wh")
    ('kWh', 'Wh')
    >>> unit_in_header("temperature_2m (°C)"), unit_in_header("Fecha") is None
    ('degC', True)
    """
    m = _BRACKETS.search(header)
    if m:
        try:
            return parse_unit(m.group(1))
        except ValueError:
            return None
    tokens = [t for t in re.split(r"[_\s]+", header.strip()) if t]
    if len(tokens) >= 2:
        try:
            return parse_unit(tokens[-1])
        except ValueError:
            return None
    return None
