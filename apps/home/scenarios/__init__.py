"""Otwin Home scenarios: what if it were colder, the thermostat lower, the walls insulated?

A :class:`ScenarioStudy` holds a (calibrated) home twin, a period with its
weather, and the household's :class:`Tariff`. Each what-if is a small object
(:mod:`scenarios.changes`); running it gives the month-by-month kWh, m³ and
euros, as the home is and as it would be, and one plain sentence comparing
them::

    study = ScenarioStudy.from_calibration(result, data, tariff)
    for r in study.run_all([OutdoorShift(-3), SetpointChange(-1),
                            MoveAppliance("dishwasher", (21,), (2,)),
                            Insulation(r_value=2.0, area_m2=40, envelope_area_m2=120),
                            TariffChange(other_tariff)]):
        print(r.sentence)
"""

from __future__ import annotations

from .changes import (
    Insulation,
    MoveAppliance,
    OutdoorShift,
    Scenario,
    SetpointChange,
    TariffChange,
    insulated_conductance,
)
from .study import Case, MonthBill, Outcome, ScenarioResult, ScenarioStudy
from .tariffs import (
    IEE_RATE,
    NATIONAL_HOLIDAYS,
    PERIODS,
    VAT_RATE,
    ElectricityTariff,
    GasTariff,
    Tariff,
    period_2_0td,
)

__all__ = [
    "ScenarioStudy",
    "ScenarioResult",
    "Outcome",
    "MonthBill",
    "Case",
    "Scenario",
    "OutdoorShift",
    "SetpointChange",
    "MoveAppliance",
    "Insulation",
    "TariffChange",
    "insulated_conductance",
    "Tariff",
    "ElectricityTariff",
    "GasTariff",
    "period_2_0td",
    "PERIODS",
    "NATIONAL_HOLIDAYS",
    "IEE_RATE",
    "VAT_RATE",
]
