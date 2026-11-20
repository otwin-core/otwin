"""A typical year's weather for each province: the normals the forecast runs on.

AEMET publishes 1991-2020 normals for every capital; the numbers here are
rounded from them. Each province follows one of seven climate shapes (the
monthly means of a representative capital, °C, and the typical daily swing),
shifted so that its January matches the province's own January mean, and
takes the daily solar radiation of its band (kWh/m² a day, monthly). From
these, :func:`typical_year` writes an hourly outdoor temperature for a whole
year, and :func:`solar_profile` the global irradiance on the horizontal
(W/m²) hour by hour, which the twin turns into sun through the windows.

Nothing here is a forecast of the weather: it is what an average year looks
like, which is what a yearly budget needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from .questions import PROVINCES

__all__ = ["Normals", "normals_of", "typical_year", "solar_profile", "monthly_means"]

#: Monthly mean temperatures (°C) of a representative capital, Jan to Dec,
#: the typical daily swing (K) and the band of solar radiation.
_SHAPES: dict[str, tuple[tuple[float, ...], float, str]] = {
    # A Coruña: mild, wet, little swing
    "atlantic": (
        (10.2, 10.6, 12.0, 12.9, 15.0, 17.6, 19.4, 19.9, 18.8, 16.1, 12.9, 11.0),
        6.0,
        "north",
    ),
    # Bilbao, Santander, Oviedo, San Sebastián
    "cantabrian": (
        (9.0, 9.5, 11.2, 12.5, 15.3, 18.0, 20.2, 20.6, 18.8, 16.0, 12.2, 9.8),
        8.0,
        "north",
    ),
    # Valladolid: the northern plateau, cold winters, hot dry summers
    "plateau_north": (
        (4.3, 6.0, 9.1, 11.1, 14.9, 19.8, 22.9, 22.6, 19.0, 13.6, 8.0, 4.9),
        12.0,
        "interior",
    ),
    # Madrid: the southern plateau and the Ebro valley
    "plateau_south": (
        (6.3, 7.9, 11.2, 12.9, 16.7, 22.2, 25.6, 25.1, 20.9, 15.1, 9.9, 6.9),
        11.0,
        "interior",
    ),
    # Sevilla: the Guadalquivir valley
    "south": (
        (11.0, 12.5, 15.3, 17.1, 20.8, 25.1, 28.2, 28.0, 25.0, 20.2, 15.1, 12.0),
        12.0,
        "south",
    ),
    # Valencia: the Mediterranean coast and the islands
    "mediterranean": (
        (11.9, 12.6, 14.5, 16.4, 19.5, 23.4, 26.1, 26.5, 23.8, 19.9, 15.3, 12.6),
        8.0,
        "south",
    ),
    # Las Palmas: the Canaries
    "canary": (
        (18.2, 18.3, 19.0, 19.5, 20.6, 22.4, 24.2, 24.8, 24.5, 23.2, 21.1, 19.3),
        6.0,
        "canary",
    ),
}

#: Daily global horizontal radiation, kWh/m² a day, Jan to Dec, by band.
_SOLAR: dict[str, tuple[float, ...]] = {
    "north": (1.4, 2.2, 3.4, 4.5, 5.4, 6.0, 6.1, 5.4, 4.3, 2.8, 1.6, 1.2),
    "interior": (2.0, 3.0, 4.4, 5.6, 6.6, 7.5, 7.8, 6.9, 5.4, 3.6, 2.4, 1.8),
    "south": (2.5, 3.4, 4.8, 5.9, 6.9, 7.6, 7.7, 6.9, 5.5, 4.0, 2.8, 2.2),
    "canary": (3.6, 4.4, 5.5, 6.2, 6.8, 7.0, 7.2, 6.7, 5.8, 4.6, 3.7, 3.3),
}

_SHAPE_OF: dict[str, str] = {
    "a_coruna": "atlantic",
    "pontevedra": "atlantic",
    "lugo": "cantabrian",
    "asturias": "cantabrian",
    "cantabria": "cantabrian",
    "bizkaia": "cantabrian",
    "gipuzkoa": "cantabrian",
    "alava": "plateau_north",
    "navarra": "plateau_north",
    "la_rioja": "plateau_north",
    "burgos": "plateau_north",
    "leon": "plateau_north",
    "palencia": "plateau_north",
    "valladolid": "plateau_north",
    "zamora": "plateau_north",
    "salamanca": "plateau_north",
    "avila": "plateau_north",
    "segovia": "plateau_north",
    "soria": "plateau_north",
    "ourense": "plateau_north",
    "huesca": "plateau_north",
    "teruel": "plateau_north",
    "cuenca": "plateau_north",
    "guadalajara": "plateau_south",
    "madrid": "plateau_south",
    "toledo": "plateau_south",
    "ciudad_real": "plateau_south",
    "albacete": "plateau_south",
    "caceres": "plateau_south",
    "badajoz": "plateau_south",
    "zaragoza": "plateau_south",
    "lleida": "plateau_south",
    "sevilla": "south",
    "cordoba": "south",
    "jaen": "south",
    "granada": "south",
    "huelva": "south",
    "cadiz": "mediterranean",
    "malaga": "mediterranean",
    "almeria": "mediterranean",
    "murcia": "mediterranean",
    "alicante": "mediterranean",
    "valencia": "mediterranean",
    "castellon": "mediterranean",
    "tarragona": "mediterranean",
    "barcelona": "mediterranean",
    "girona": "mediterranean",
    "baleares": "mediterranean",
    "ceuta": "mediterranean",
    "melilla": "mediterranean",
    "las_palmas": "canary",
    "santa_cruz": "canary",
}

_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@dataclass(frozen=True)
class Normals:
    """A province's typical year: monthly means (°C), daily swing (K), daily
    solar radiation (kWh/m²) and latitude, for the day length."""

    province: str
    monthly_c: tuple[float, ...]
    swing_k: float
    solar_kwh_day: tuple[float, ...]
    latitude: float
    timezone: str


def normals_of(province: str) -> Normals:
    """The normals of ``province`` (a value of :data:`survey.PROVINCES`)."""
    p = next((x for x in PROVINCES if x.value == province), None)
    if p is None:
        raise KeyError(f"unknown province {province!r}")
    shape, swing, band = _SHAPES[_SHAPE_OF.get(province, "plateau_south")]
    offset = p.january_c - shape[0]
    return Normals(
        province,
        tuple(round(m + offset, 1) for m in shape),
        swing,
        _SOLAR[band],
        p.latitude,
        p.timezone,
    )


def monthly_means(province: str) -> list[float]:
    """The twelve monthly mean temperatures, °C, January first."""
    return list(normals_of(province).monthly_c)


def _smooth_monthly(values: tuple[float, ...], day_of_year: np.ndarray) -> np.ndarray:
    """A monthly series read at any day, interpolated between mid-months so
    the year has no steps at the first of each month."""
    mids = (
        np.cumsum((0,) + _DAYS[:-1]) + np.asarray(_DAYS) / 2.0
    )  # day of year of each mid-month
    x = np.concatenate([[mids[-1] - 365.0], mids, [mids[0] + 365.0]])
    y = np.concatenate([[values[-1]], values, [values[0]]])
    return np.interp(day_of_year, x, y)


def _day_length_hours(latitude: float, day_of_year: np.ndarray) -> np.ndarray:
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + day_of_year) / 365.0)
    lat = math.radians(latitude)
    cos_h = np.clip(-np.tan(lat) * np.tan(decl), -1.0, 1.0)
    return 24.0 / np.pi * np.arccos(cos_h)


def _hours(province: str, year: int) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    """Every local hour of ``year``, its day of year and its local hour."""
    n = normals_of(province)
    zone = ZoneInfo(n.timezone)
    first = datetime(year, 1, 1, tzinfo=zone)
    count = int((datetime(year + 1, 1, 1, tzinfo=zone) - first).total_seconds() // 3600)
    stamps = [first + timedelta(hours=k) for k in range(count)]
    doy = np.array([s.timetuple().tm_yday + s.hour / 24.0 for s in stamps])
    hour = np.array([s.hour + s.minute / 60.0 for s in stamps], dtype=float)
    return stamps, doy, hour


def typical_year(province: str, year: int = 2026) -> tuple[datetime, np.ndarray]:
    """An average year's outdoor temperature, °C, hour by hour from 1 January
    local time: the monthly means, smoothed, with the daily swing (coldest
    about 6:00, warmest about 15:00). Returns ``(start, outdoor_c)``."""
    n = normals_of(province)
    stamps, doy, hour = _hours(province, year)
    mean = _smooth_monthly(n.monthly_c, doy)
    swing = (
        n.swing_k / 2.0 * -np.cos(2 * np.pi * (hour - 15.0 + 9.0) / 24.0)
    )  # min at 6 h, max at 15 h
    return stamps[0], mean + swing


def solar_profile(province: str, year: int = 2026) -> tuple[datetime, np.ndarray]:
    """Global horizontal irradiance, W/m², hour by hour over an average year:
    the band's daily radiation spread as a half-sine over the day, whose
    length follows the latitude and the season. Returns ``(start, w_m2)``."""
    n = normals_of(province)
    stamps, doy, hour = _hours(province, year)
    daily = _smooth_monthly(n.solar_kwh_day, doy) * 1000.0  # Wh/m² a day
    length = _day_length_hours(n.latitude, doy)
    noon = 13.0  # solar noon in Spain's clock, roughly (CET is ahead of the sun)
    rise = noon - length / 2.0
    x = (hour + 0.5 - rise) / length  # fraction of the day, at mid-hour
    shape = np.where((x > 0) & (x < 1), np.sin(np.pi * np.clip(x, 0, 1)), 0.0)
    peak = daily / (
        length * 2.0 / np.pi
    )  # so the half-sine integrates to the day's energy
    return stamps[0], peak * shape


def solar_at(province: str, stamps: list[datetime]) -> np.ndarray:
    """Typical global irradiance, W/m², at given local hours (any year)."""
    n = normals_of(province)
    doy = np.array([s.timetuple().tm_yday + s.hour / 24.0 for s in stamps])
    hour = np.array([s.hour + s.minute / 60.0 for s in stamps], dtype=float)
    daily = _smooth_monthly(n.solar_kwh_day, doy) * 1000.0
    length = _day_length_hours(n.latitude, doy)
    rise = 13.0 - length / 2.0
    x = (hour + 0.5 - rise) / length
    shape = np.where((x > 0) & (x < 1), np.sin(np.pi * np.clip(x, 0, 1)), 0.0)
    return daily / (length * 2.0 / np.pi) * shape
