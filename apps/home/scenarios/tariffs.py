"""Household tariffs: what a month of kWh and m³ costs, as the bill computes it.

**Electricity** (:class:`ElectricityTariff`). Spanish households are on the
2.0TD access tariff, whose energy price depends on the local hour:

=====  ===========  ===============================================
period name         hours (Monday to Friday, local time)
=====  ===========  ===============================================
P1     punta        10-14 and 18-22
P2     llano        08-10, 14-18 and 22-24
P3     valle        00-08, and all day on weekends and national holidays
=====  ===========  ===============================================

A free-market contract may charge one flat price for every hour; give one
number. A bill then adds the power term (contracted kW × €/kW per day),
the meter rental, the electricity tax (*impuesto especial sobre la
electricidad*, on energy plus power) and VAT on the lot.

**Gas** (:class:`GasTariff`). The meter reads m³; the bill converts them to
kWh with the conversion factor and the gross calorific value printed on it
(``kWh = m³ × Fc × PCS``, as in :mod:`ingest.bills`), charges a price per kWh
and a standing charge per day, the hydrocarbon tax per kWh, and VAT.

The national holidays are the fixed-date ones the 2.0TD calendar uses (1 and
6 January, 1 May, 15 August, 12 October, 1 November, 6, 8 and 25 December);
regional and movable holidays are ordinary days for the tariff.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

__all__ = [
    "ElectricityTariff",
    "GasTariff",
    "Tariff",
    "period_2_0td",
    "NATIONAL_HOLIDAYS",
    "PERIODS",
    "IEE_RATE",
    "VAT_RATE",
]

PERIODS = ("P1", "P2", "P3")
#: (month, day) of the fixed-date national holidays: all P3 under 2.0TD.
NATIONAL_HOLIDAYS = frozenset(
    {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}
)
#: Impuesto especial sobre la electricidad, as a fraction of energy + power.
IEE_RATE = 0.0511269632
#: Value added tax on energy bills.
VAT_RATE = 0.21

_P1_HOURS = frozenset({10, 11, 12, 13, 18, 19, 20, 21})
_P3_HOURS = frozenset(range(8))


def period_2_0td(local: datetime | date, hour: int | None = None) -> str:
    """The 2.0TD period ("P1", "P2" or "P3") of a local hour.

    ``local`` is a local datetime (its hour is used), or a date with ``hour``.

    >>> from datetime import datetime
    >>> period_2_0td(datetime(2026, 2, 2, 19)), period_2_0td(datetime(2026, 2, 7, 19))
    ('P1', 'P3')
    """
    d = local.date() if isinstance(local, datetime) else local
    h = local.hour if hour is None else hour  # type: ignore[union-attr]
    if d.weekday() >= 5 or (d.month, d.day) in NATIONAL_HOLIDAYS:
        return "P3"
    if h in _P1_HOURS:
        return "P1"
    if h in _P3_HOURS:
        return "P3"
    return "P2"


def _check_prices(prices: Mapping[str, float]) -> dict[str, float]:
    out = {p: float(prices[p]) for p in PERIODS if p in prices}
    if set(prices) - set(PERIODS):
        raise ValueError(
            f"periods are {PERIODS}, not {sorted(set(prices) - set(PERIODS))}"
        )
    if set(out) != set(PERIODS):
        raise ValueError(f"give a price for each of {PERIODS}")
    if any(v < 0 for v in out.values()):
        raise ValueError("prices cannot be negative")
    return out


@dataclass(frozen=True)
class ElectricityTariff:
    """An electricity contract.

    Args:
        name: what the household calls it ("Tarifa Noche", "PVPC").
        energy_eur_per_kwh: one price for every hour, or a price per 2.0TD
            period, ``{"P1": .., "P2": .., "P3": ..}``.
        power_kw: contracted power, kW.
        power_eur_per_kw_day: power term, € per kW per day (P1 and P2 power
            terms summed, as most retailers quote them).
        meter_eur_per_day: meter rental, € per day.
        electricity_tax: IEE rate on energy plus power.
        vat: VAT rate on the whole bill.
    """

    name: str
    energy_eur_per_kwh: float | Mapping[str, float]
    power_kw: float = 4.6
    power_eur_per_kw_day: float = 0.0
    meter_eur_per_day: float = 0.0
    electricity_tax: float = IEE_RATE
    vat: float = VAT_RATE
    _prices: dict[str, float] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        e = self.energy_eur_per_kwh
        if isinstance(e, Mapping):
            prices = _check_prices(e)
        else:
            if float(e) < 0:
                raise ValueError("prices cannot be negative")
            prices = {p: float(e) for p in PERIODS}
        for label, v in (
            ("power_kw", self.power_kw),
            ("power_eur_per_kw_day", self.power_eur_per_kw_day),
            ("meter_eur_per_day", self.meter_eur_per_day),
            ("electricity_tax", self.electricity_tax),
            ("vat", self.vat),
        ):
            if v < 0:
                raise ValueError(f"{label} cannot be negative")
        object.__setattr__(self, "_prices", prices)

    @property
    def time_of_use(self) -> bool:
        """True when the price depends on the hour."""
        return len(set(self._prices.values())) > 1

    def price(self, period: str) -> float:
        """Energy price of a period, €/kWh."""
        return self._prices[period]

    def bill(self, kwh_by_period: Mapping[str, float], days: float) -> dict[str, float]:
        """The month's bill, itemised: energy, power, tax, meter, VAT, total (€)."""
        energy = sum(self._prices[p] * kwh_by_period.get(p, 0.0) for p in PERIODS)
        power = self.power_kw * self.power_eur_per_kw_day * days
        tax = self.electricity_tax * (energy + power)
        meter = self.meter_eur_per_day * days
        vat = self.vat * (energy + power + tax + meter)
        return {
            "energy": energy,
            "power": power,
            "electricity_tax": tax,
            "meter": meter,
            "vat": vat,
            "total": energy + power + tax + meter + vat,
        }


@dataclass(frozen=True)
class GasTariff:
    """A natural-gas contract (TUR RL.1-RL.3 or free market).

    Args:
        name: what the household calls it.
        energy_eur_per_kwh: price per kWh.
        fixed_eur_per_day: standing charge (*término fijo*), € per day.
        pcs_kwh_m3: gross calorific value, kWh per m³, from the bill.
        conversion_factor: Fc, from the bill (altitude and pressure).
        hydrocarbon_tax_eur_per_kwh: *impuesto especial sobre hidrocarburos*.
        vat: VAT rate.
    """

    name: str
    energy_eur_per_kwh: float
    fixed_eur_per_day: float = 0.0
    pcs_kwh_m3: float = 11.7
    conversion_factor: float = 0.98
    hydrocarbon_tax_eur_per_kwh: float = 0.00234
    vat: float = VAT_RATE

    def __post_init__(self) -> None:
        if self.pcs_kwh_m3 <= 0 or self.conversion_factor <= 0:
            raise ValueError("PCS and the conversion factor must be positive")
        if (
            min(
                self.energy_eur_per_kwh,
                self.fixed_eur_per_day,
                self.hydrocarbon_tax_eur_per_kwh,
                self.vat,
            )
            < 0
        ):
            raise ValueError("prices cannot be negative")

    def m3(self, kwh: float) -> float:
        """Meter m³ for ``kwh`` billed: ``kWh / (Fc × PCS)``."""
        return kwh / (self.conversion_factor * self.pcs_kwh_m3)

    def bill(self, kwh: float, days: float) -> dict[str, float]:
        """The month's gas bill, itemised (€)."""
        energy = self.energy_eur_per_kwh * kwh
        fixed = self.fixed_eur_per_day * days
        tax = self.hydrocarbon_tax_eur_per_kwh * kwh
        vat = self.vat * (energy + fixed + tax)
        return {
            "energy": energy,
            "fixed": fixed,
            "hydrocarbon_tax": tax,
            "vat": vat,
            "total": energy + fixed + tax + vat,
        }


@dataclass(frozen=True)
class Tariff:
    """The household's contracts: electricity and, if it has a gas supply, gas.

    A home without a gas supply pays no gas standing charge, so ``gas=None``
    bills its gas meter (always zero) at nothing.
    """

    electricity: ElectricityTariff
    gas: GasTariff | None = None

    @property
    def name(self) -> str:
        """The contracts' names, as the household would say them."""
        if self.gas is None:
            return self.electricity.name
        return f"{self.electricity.name} + {self.gas.name}"
