"""Run what-if scenarios on a home twin and bill every month of them.

A :class:`ScenarioStudy` fixes the period, the weather and the household's
tariff. Its :attr:`~ScenarioStudy.baseline` is the home as it is. Each
scenario (:mod:`scenarios.changes`) edits a :class:`Case`, which holds the
parameter values, the hourly outdoor temperature, the schedules and the
tariff. The study simulates the case the same way the baseline was
simulated and bills both month by month. A :class:`ScenarioResult` holds
the two :class:`Outcome` s and the one sentence that compares them.

The simulation is the one calibration fits against: the record's first week
replayed as a spin-up (one week for a one-node zone, six for a two-node
one), so baseline and scenario each start from the state their own
conditions imply, a quarter-hour step, and meters integrated exactly from
the outputs at each step's midpoint. Results are deterministic, the same
numbers for the same inputs, run after run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from components import HomeTwin, Schedule

from .tariffs import PERIODS, Tariff, period_2_0td

__all__ = ["Case", "MonthBill", "Outcome", "ScenarioResult", "ScenarioStudy"]

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class Case:
    """Everything a scenario may change: what the study simulates and bills.

    Attributes:
        parameters: model parameter values that differ from the twin's.
        outdoor_c: outdoor temperature at the start of each hour, °C.
        schedules: input schedules that replace the twin's, by input name.
        tariff: the contracts the months are billed under.
    """

    parameters: Mapping[str, float]
    outdoor_c: np.ndarray
    schedules: Mapping[str, Schedule]
    tariff: Tariff

    def with_parameters(self, **changes: float) -> Case:
        """A copy with some parameters set (dotted names go in a dict: ``**{...}``)."""
        return replace(self, parameters={**self.parameters, **changes})

    def with_schedules(self, **changes: Schedule) -> Case:
        """A copy with some input schedules replaced."""
        return replace(self, schedules={**self.schedules, **changes})


@dataclass(frozen=True)
class MonthBill:
    """One calendar month (or the part of it the study covers), billed.

    Energies are in kWh and m³, money in euros, VAT and taxes included.
    """

    key: str  # "2026-02"
    label: str  # "February 2026"
    days: int
    hours: int
    electricity_kwh: float
    electricity_kwh_by_period: Mapping[str, float]
    gas_kwh: float
    gas_m3: float
    electricity_bill: Mapping[str, float]
    gas_bill: Mapping[str, float]

    @property
    def electricity_eur(self) -> float:
        """The electricity bill, €."""
        return self.electricity_bill["total"]

    @property
    def gas_eur(self) -> float:
        """The gas bill, € (zero without a gas supply)."""
        return self.gas_bill.get("total", 0.0)

    @property
    def total_eur(self) -> float:
        """Both bills, €."""
        return self.electricity_eur + self.gas_eur


@dataclass(frozen=True)
class Outcome:
    """One simulated period, billed month by month.

    The ``*_per_month`` properties are what sentences quote: the period's
    totals divided by its number of months, which for a one-month study is
    simply that month.
    """

    months: tuple[MonthBill, ...]
    tariff: Tariff
    hourly_electricity_kwh: np.ndarray = field(repr=False)
    hourly_gas_kwh: np.ndarray = field(repr=False)

    def _per_month(self, attr: str) -> float:
        return sum(getattr(m, attr) for m in self.months) / len(self.months)

    @property
    def electricity_kwh(self) -> float:
        """Electricity over the period, kWh."""
        return sum(m.electricity_kwh for m in self.months)

    @property
    def gas_m3(self) -> float:
        """Gas over the period, m³."""
        return sum(m.gas_m3 for m in self.months)

    @property
    def total_eur(self) -> float:
        """Both bills over the period, €."""
        return sum(m.total_eur for m in self.months)

    @property
    def electricity_kwh_per_month(self) -> float:
        """Electricity per month, kWh."""
        return self._per_month("electricity_kwh")

    @property
    def gas_kwh_per_month(self) -> float:
        """Gas per month, kWh."""
        return self._per_month("gas_kwh")

    @property
    def gas_m3_per_month(self) -> float:
        """Gas per month, m³."""
        return self._per_month("gas_m3")

    @property
    def eur_per_month(self) -> float:
        """Both bills per month, €."""
        return self._per_month("total_eur")

    @property
    def period(self) -> str:
        """How sentences name the period: "in February 2026" or "a month"."""
        if len(self.months) == 1:
            return f"in {self.months[0].label}"
        return "a month"


@dataclass(frozen=True)
class ScenarioResult:
    """A scenario compared with the baseline.

    Attributes:
        name: the scenario's short title ("2 °C warmer outside").
        sentence: the comparison in one plain sentence.
        baseline, outcome: the home as it is, and under the scenario.
    """

    name: str
    sentence: str
    baseline: Outcome
    outcome: Outcome
    scenario: object = field(repr=False, default=None)

    @property
    def electricity_kwh_change(self) -> float:
        """Change in electricity per month, kWh (negative: less)."""
        return (
            self.outcome.electricity_kwh_per_month
            - self.baseline.electricity_kwh_per_month
        )

    @property
    def gas_m3_change(self) -> float:
        """Change in gas per month, m³."""
        return self.outcome.gas_m3_per_month - self.baseline.gas_m3_per_month

    @property
    def eur_change(self) -> float:
        """Change in both bills per month, € (negative: saving)."""
        return self.outcome.eur_per_month - self.baseline.eur_per_month

    def table(self) -> str:
        """Month by month: kWh, m³ and €, as it is and with the change."""
        rows = [
            f"{self.name}",
            "  month            electricity kWh       gas m³            bills €",
            "                   now     then          now    then       now      then",
        ]
        for a, b in zip(self.baseline.months, self.outcome.months, strict=True):
            rows.append(
                f"  {a.label:<15} {a.electricity_kwh:6.0f}  {b.electricity_kwh:6.0f}"
                f"        {a.gas_m3:5.1f}  {b.gas_m3:5.1f}"
                f"      {a.total_eur:7.2f}  {b.total_eur:7.2f}"
            )
        return "\n".join(rows)


class ScenarioStudy:
    """The home, a period, its weather and its tariff: the ground for what-ifs.

    Args:
        twin: the (calibrated) home.
        start: first hour, timezone-aware, on the hour.
        outdoor_c: outdoor temperature at the start of each hour, °C; a
            number holds it constant (then give ``hours``).
        tariff: the household's contracts.
        hours: length of the period, if ``outdoor_c`` is a number.
        measured: other hourly inputs (plug readings, W), by input name.
        steps_per_hour: simulation steps per hour.
        spinup_weeks: replays of the first week before the period; one for a
            one-node zone, six for a two-node one by default.
        timezone_name: the zone of the tariff's clock and the months.
    """

    def __init__(
        self,
        twin: HomeTwin,
        *,
        start: datetime,
        outdoor_c: float | Sequence[float] | np.ndarray,
        tariff: Tariff,
        hours: int | None = None,
        measured: Mapping[str, np.ndarray] | None = None,
        steps_per_hour: int = 4,
        spinup_weeks: int | None = None,
        timezone_name: str = "Europe/Madrid",
    ) -> None:
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        if start.minute or start.second or start.microsecond:
            raise ValueError("start must be on the hour")
        out = np.asarray(outdoor_c, dtype=float)
        if out.ndim == 0:
            if hours is None:
                raise ValueError("give hours= when the outdoor temperature is a number")
            out = np.full(int(hours), float(out))
        elif hours is not None and hours != out.size:
            raise ValueError(f"hours={hours} but the outdoor series has {out.size}")
        if out.size < 24:
            raise ValueError("a study needs at least one day")
        if not np.all(np.isfinite(out)):
            raise ValueError("the outdoor temperature has gaps")
        if steps_per_hour < 1:
            raise ValueError("steps_per_hour must be at least 1")
        self.twin = twin
        self.start = start
        self.hours = int(out.size)
        self.tariff = tariff
        self.steps_per_hour = int(steps_per_hour)
        self.spinup_weeks = (
            (6 if twin.zone.two_node else 1)
            if spinup_weeks is None
            else int(spinup_weeks)
        )
        self.measured = {
            k: np.asarray(v, dtype=float) for k, v in (measured or {}).items()
        }
        for k, v in self.measured.items():
            if v.shape != out.shape:
                raise ValueError(
                    f"measured input {k!r} has {v.size} hours, not {out.size}"
                )
        self.zone = ZoneInfo(timezone_name)
        self._outdoor = out
        self._hours_local = [
            (start.astimezone(timezone.utc) + timedelta(hours=k)).astimezone(self.zone)
            for k in range(self.hours)
        ]
        self._periods = np.array([period_2_0td(h) for h in self._hours_local])
        self._cache: dict[object, tuple[np.ndarray, np.ndarray]] = {}
        self._baseline: Outcome | None = None

    # ------------------------------------------------------------ building
    @classmethod
    def from_calibration(
        cls, calibration, data, tariff: Tariff, **kwargs
    ) -> ScenarioStudy:
        """The study of a calibrated twin over the month it was calibrated on.

        A record of several periods is studied over its last period: a study
        runs one continuous stretch of time (``data.period(k)`` for another).
        """
        if data.periods:
            data = data.period(len(data.spans) - 1)
        return cls(
            calibration.twin,
            start=data.start,
            outdoor_c=data.outdoor_c,
            tariff=tariff,
            measured=dict(data.measured),
            **kwargs,
        )

    def base_case(self) -> Case:
        """The home as it is: the twin's parameters, the study's weather and tariff."""
        return Case({}, self._outdoor.copy(), {}, self.tariff)

    def schedule(self, case: Case, name: str) -> Schedule | None:
        """The schedule an input follows in ``case``: the case's, else the twin's."""
        return case.schedules.get(name, self.twin.schedules.get(name))

    def parameter(self, case: Case, name: str) -> float:
        """A parameter's value in ``case``."""
        if name in case.parameters:
            return float(case.parameters[name])
        return float(self.twin.model.parameters[name])

    # --------------------------------------------------------- simulating
    def _key(self, case: Case) -> object:
        return (
            tuple(sorted(case.parameters.items())),
            case.outdoor_c.tobytes(),
            tuple(sorted((k, v.values, v.timezone) for k, v in case.schedules.items())),
        )

    def _hourly(self, case: Case) -> tuple[np.ndarray, np.ndarray]:
        """Hourly electricity and gas, kWh, over the period."""
        key = self._key(case)
        if key in self._cache:
            return self._cache[key]
        twin = replace(
            self.twin, model=self.twin.model.with_parameters(dict(case.parameters))
        )
        sub = self.steps_per_hour
        week = min(7 * 24, self.hours)
        prefix = self.spinup_weeks * week
        n = prefix + self.hours
        t = np.arange(n * sub + 1) * (3600.0 / sub)
        start = self.start.astimezone(timezone.utc) - timedelta(
            hours=prefix
        )  # elapsed, not wall-clock

        def with_prefix(hourly: np.ndarray) -> np.ndarray:
            return np.concatenate([np.tile(hourly[:week], self.spinup_weeks), hourly])

        full = with_prefix(case.outdoor_c)
        mid = (t[:-1] + t[1:]) / 2 / 3600.0
        outdoor = np.append(
            np.interp(mid, np.arange(full.size, dtype=float), full), full[-1]
        )
        inputs: dict[str, object] = {}
        for k, v in self.measured.items():
            h = with_prefix(v)
            inputs[k] = np.append(np.repeat(h, sub), h[-1])
        inputs.update(case.schedules)
        run = twin.simulate(t, start=start, outdoor=outdoor + 273.15, **inputs)

        def meter(names: list[str]) -> np.ndarray:
            if not names:
                return np.zeros(self.hours)
            w = np.sum([run.step_mean[x] for x in names], axis=0)
            return w.reshape(n, sub).mean(axis=1)[prefix:] / 1000.0

        out = (meter(twin.electric_outputs), meter(twin.gas_outputs))
        self._cache[key] = out
        return out

    def evaluate(self, case: Case) -> Outcome:
        """Simulate and bill ``case``, month by month."""
        elec, gas = self._hourly(case)
        if case.tariff.gas is None and np.any(gas > 0):
            raise ValueError("this home burns gas; give the gas tariff (Tariff(gas=...))")
        months: dict[str, list[int]] = {}
        for k, h in enumerate(self._hours_local):
            months.setdefault(f"{h.year}-{h.month:02d}", []).append(k)
        bills = []
        for key, idx in months.items():
            ix = np.asarray(idx)
            days = len({self._hours_local[i].date() for i in idx})
            by_period = {
                p: float(elec[ix][self._periods[ix] == p].sum()) for p in PERIODS
            }
            kwh = float(elec[ix].sum())
            gas_kwh = float(gas[ix].sum())
            gt = case.tariff.gas
            year, month = int(key[:4]), int(key[5:])
            bills.append(
                MonthBill(
                    key=key,
                    label=f"{_MONTHS[month - 1]} {year}",
                    days=days,
                    hours=ix.size,
                    electricity_kwh=kwh,
                    electricity_kwh_by_period=by_period,
                    gas_kwh=gas_kwh,
                    gas_m3=gt.m3(gas_kwh) if gt is not None else 0.0,
                    electricity_bill=case.tariff.electricity.bill(by_period, days),
                    gas_bill=gt.bill(gas_kwh, days) if gt is not None else {"total": 0.0},
                )
            )
        return Outcome(tuple(bills), case.tariff, elec, gas)

    @property
    def baseline(self) -> Outcome:
        """The home as it is."""
        if self._baseline is None:
            self._baseline = self.evaluate(self.base_case())
        return self._baseline

    def run(self, scenario) -> ScenarioResult:
        """One scenario against the baseline, with its sentence."""
        case = scenario.apply(self, self.base_case())
        outcome = self.evaluate(case)
        return ScenarioResult(
            name=scenario.title(self),
            sentence=scenario.sentence(self, self.baseline, outcome),
            baseline=self.baseline,
            outcome=outcome,
            scenario=scenario,
        )

    def run_all(self, scenarios: Sequence[object]) -> list[ScenarioResult]:
        """Several scenarios, each against the baseline (not against each other)."""
        return [self.run(s) for s in scenarios]
