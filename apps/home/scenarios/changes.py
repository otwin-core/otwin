"""The what-ifs: each one edits a :class:`~scenarios.study.Case` and says what changed.

=========================  =====================================================
scenario                   what it changes in the twin
=========================  =====================================================
:class:`OutdoorShift`      every hour of outdoor temperature, by ``delta_c``
:class:`SetpointChange`    the heating (or cooling) thermostat, by ``delta_c``:
                           its setpoint parameter, or every hour of its schedule
:class:`MoveAppliance`     an appliance's schedule: the use at ``from_hours`` is
                           moved, every day, to ``to_hours`` (to the cheap night
                           hours of a 2.0TD tariff, say)
:class:`Insulation`        the envelope's conductance, from an insulation board's
                           R-value (m²·K/W) over the area it covers
:class:`TariffChange`      nothing in the home: the same hours, billed under
                           another tariff
=========================  =====================================================

Every scenario writes its comparison as one sentence from the same mould::

    If <what changes>, your home would <use X kWh less electricity and Y m³
    less gas> in February 2026, and your bills would be €Z lower (€new
    instead of €old).

Numbers in sentences are rounded the same way everywhere, kWh to the unit,
m³ to a tenth, euros to the cent. Changes that round to nothing are not
mentioned, so a sentence never claims "0 kWh less".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from components import AirConditioner, Schedule, SpaceMachine

from .study import Case, Outcome, ScenarioStudy
from .tariffs import Tariff

__all__ = [
    "Scenario",
    "OutdoorShift",
    "SetpointChange",
    "MoveAppliance",
    "Insulation",
    "TariffChange",
    "insulated_conductance",
]


# ---------------------------------------------------------------- wording


def _eur(x: float) -> str:
    return f"€{x:.2f}"


def _degrees(x: float) -> str:
    return f"{x:g} °C"


def _energy_phrase(base: Outcome, new: Outcome) -> str | None:
    """'use 75 kWh less electricity and 0.4 m³ less gas', or None if unchanged."""
    parts = []
    de = new.electricity_kwh_per_month - base.electricity_kwh_per_month
    if round(abs(de)) >= 1:
        parts.append(f"{abs(de):.0f} kWh {'less' if de < 0 else 'more'} electricity")
    dg = new.gas_m3_per_month - base.gas_m3_per_month
    if round(abs(dg), 1) >= 0.1:
        parts.append(f"{abs(dg):.1f} m³ {'less' if dg < 0 else 'more'} gas")
    if not parts:
        return None
    return "use " + " and ".join(parts)


def _money_phrase(base: Outcome, new: Outcome) -> str | None:
    """'€21.30 lower (€150.20 instead of €171.50)', or None if unchanged."""
    old, now = base.eur_per_month, new.eur_per_month
    if round(abs(now - old), 2) < 0.01:
        return None
    word = "lower" if now < old else "higher"
    return f"{_eur(abs(now - old))} {word} ({_eur(now)} instead of {_eur(old)})"


def compare(condition: str, base: Outcome, new: Outcome, *, because: str = "") -> str:
    """The one-sentence comparison of ``new`` against ``base``."""
    energy = _energy_phrase(base, new)
    money = _money_phrase(base, new)
    period = new.period
    if energy is None and money is None:
        return (
            f"If {condition}, nothing would change: your home would use the same "
            f"energy {period} and your bills would stay at {_eur(base.eur_per_month)}."
        )
    if energy is None:
        return (
            f"If {condition}, your home would use the same energy {period}, but your "
            f"bills would be {money}{because}."
        )
    if money is None:
        return (
            f"If {condition}, your home would {energy} {period}, and your bills would "
            f"stay at {_eur(base.eur_per_month)}."
        )
    return f"If {condition}, your home would {energy} {period}, and your bills would be {money}{because}."


def _hours(hours: tuple[int, ...]) -> str:
    labels = [f"{h:02d}:00" for h in hours]
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


# ---------------------------------------------------------------- scenarios


class Scenario:
    """A what-if. Subclasses define :meth:`apply`, :meth:`title` and :meth:`condition`."""

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """The case with this change made."""
        raise NotImplementedError

    def title(self, study: ScenarioStudy) -> str:
        """A short name for tables ("2 °C warmer outside")."""
        raise NotImplementedError

    def condition(self, study: ScenarioStudy) -> str:
        """The "if" clause of the sentence ("it were 2 °C warmer outside")."""
        raise NotImplementedError

    def sentence(self, study: ScenarioStudy, base: Outcome, new: Outcome) -> str:
        """The comparison in one sentence."""
        return compare(self.condition(study), base, new)


@dataclass(frozen=True)
class OutdoorShift(Scenario):
    """Every hour ``delta_c`` warmer (positive) or colder (negative) outside."""

    delta_c: float

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """Shift every hour of the outdoor temperature."""
        return replace(case, outdoor_c=case.outdoor_c + self.delta_c)

    def title(self, study: ScenarioStudy) -> str:
        """'2 °C warmer outside'."""
        word = "warmer" if self.delta_c >= 0 else "colder"
        return f"{_degrees(abs(self.delta_c))} {word} outside"

    def condition(self, study: ScenarioStudy) -> str:
        """'it were 2 °C warmer outside'."""
        return f"it were {self.title(study)}"


def _machines(study: ScenarioStudy, which: str) -> list[SpaceMachine]:
    found = [c for c in study.twin.system.components if isinstance(c, SpaceMachine)]
    if which == "heating":
        chosen = [m for m in found if m.sense == "heat"]
    elif which == "cooling":
        chosen = [m for m in found if m.sense == "cool"]
    else:
        chosen = [m for m in found if m.name == which]
    if not chosen:
        what = (
            "heating"
            if which == "heating"
            else "air conditioning"
            if which == "cooling"
            else which
        )
        raise ValueError(f"this home has no {what} to change the thermostat of")
    return chosen


@dataclass(frozen=True)
class SetpointChange(Scenario):
    """The thermostat set ``delta_c`` higher (positive) or lower (negative).

    ``machine`` is ``"heating"`` (every heating machine), ``"cooling"`` (every
    air conditioner) or one machine's name. A setpoint that is a parameter is
    moved; a scheduled one is moved at every hour of its schedule.
    """

    delta_c: float
    machine: str = "heating"

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """Move each chosen machine's setpoint (parameter or schedule)."""
        for m in _machines(study, self.machine):
            name = f"{m.name}.setpoint"
            sched = study.schedule(case, name)
            if name in study.twin.model.input_names:
                if sched is None:
                    raise ValueError(f"{m.name}'s setpoint has no schedule to move")
                moved = Schedule([v + self.delta_c for v in sched.values], sched.timezone)
                case = case.with_schedules(**{name: moved})
            else:
                p = f"{name}.temperature"
                case = case.with_parameters(
                    **{p: study.parameter(case, p) + self.delta_c}
                )
        return case

    def _what(self, study: ScenarioStudy) -> str:
        ms = _machines(study, self.machine)
        return (
            "air conditioning"
            if all(isinstance(m, AirConditioner) for m in ms)
            else "heating"
        )

    def title(self, study: ScenarioStudy) -> str:
        """'heating 1 °C lower'."""
        word = "higher" if self.delta_c >= 0 else "lower"
        return f"{self._what(study)} {_degrees(abs(self.delta_c))} {word}"

    def condition(self, study: ScenarioStudy) -> str:
        """'you turned the heating down by 1 °C'."""
        what = self._what(study)
        if what == "air conditioning":
            word = "warmer" if self.delta_c >= 0 else "cooler"
            return f"you set the air conditioning {_degrees(abs(self.delta_c))} {word}"
        word = "up" if self.delta_c >= 0 else "down"
        return f"you turned the heating {word} by {_degrees(abs(self.delta_c))}"


@dataclass(frozen=True)
class MoveAppliance(Scenario):
    """Run an appliance at other hours: its use at ``from_hours[i]`` moves to
    ``to_hours[i]``, every day, keeping its daily energy.

    Example: ``MoveAppliance("dishwasher", from_hours=(21,), to_hours=(2,))``
    runs the dishwasher at 02:00 (2.0TD valle) instead of 21:00 (punta).
    """

    appliance: str
    from_hours: tuple[int, ...]
    to_hours: tuple[int, ...]

    def __post_init__(self) -> None:
        f, t = tuple(self.from_hours), tuple(self.to_hours)
        object.__setattr__(self, "from_hours", f)
        object.__setattr__(self, "to_hours", t)
        if len(f) != len(t) or not f:
            raise ValueError("give as many hours to move to as hours to move from")
        if any(not 0 <= h <= 23 for h in f + t):
            raise ValueError("hours are 0 to 23")
        if len(set(f)) != len(f):
            raise ValueError("each hour can be moved once")

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """Move the use within the appliance's schedule, day by day."""
        sched = study.schedule(case, self.appliance)
        if self.appliance not in study.twin.model.input_names:
            raise ValueError(f"this home has no appliance called {self.appliance!r}")
        if sched is None:
            raise ValueError(
                f"{self.appliance} has no schedule; describe when it runs "
                "(a Schedule) to move its use"
            )
        old = np.asarray(sched.values, dtype=float).reshape(-1, 24)
        new = old.copy()
        for f, t in zip(self.from_hours, self.to_hours, strict=True):
            new[:, f] -= old[:, f]
            new[:, t] += old[:, f]
        return case.with_schedules(
            **{self.appliance: Schedule(new.ravel().tolist(), sched.timezone)}
        )

    def title(self, study: ScenarioStudy) -> str:
        """'dishwasher at 02:00 instead of 21:00'."""
        return f"{self.appliance} at {_hours(self.to_hours)} instead of {_hours(self.from_hours)}"

    def condition(self, study: ScenarioStudy) -> str:
        """'you ran the dishwasher at 02:00 instead of 21:00'."""
        return f"you ran the {self.title(study)}"

    def sentence(self, study: ScenarioStudy, base: Outcome, new: Outcome) -> str:
        """Same energy, other hours: say why the bill moves."""
        tariff = new.tariff.electricity
        because = ""
        if tariff.time_of_use and new.eur_per_month < base.eur_per_month:
            because = ", because electricity is cheaper at those hours"
        return compare(self.condition(study), base, new, because=because)


def insulated_conductance(
    ua: float, r_value: float, area_m2: float, envelope_area_m2: float | None = None
) -> float:
    """The envelope's conductance after insulating part of it, W/K.

    The envelope's ``ua`` (W/K) is taken as spread evenly over
    ``envelope_area_m2`` (the insulated area itself when not given). The
    insulated part, ``area_m2``, gets ``r_value`` (m²·K/W) added in series:

        UA' = UA · (A − a) / A  +  a / (A / UA + R)

    >>> round(insulated_conductance(180.0, 2.0, 40.0, 120.0), 6)
    135.0
    """
    env = area_m2 if envelope_area_m2 is None else envelope_area_m2
    if r_value <= 0 or area_m2 <= 0 or env <= 0:
        raise ValueError("R-value and areas must be positive")
    if area_m2 > env * (1 + 1e-12):
        raise ValueError("the insulated area cannot be larger than the envelope")
    return ua * (env - area_m2) / env + area_m2 / (env / ua + r_value)


@dataclass(frozen=True)
class Insulation(Scenario):
    """Insulation of ``r_value`` m²·K/W (printed on the board) over ``area_m2``.

    ``envelope_area_m2`` is the area of everything that loses heat (walls,
    roof, windows, floor); when omitted, the insulation covers all of it.
    See :func:`insulated_conductance`.
    """

    r_value: float
    area_m2: float
    envelope_area_m2: float | None = None

    def _ua_name(self, study: ScenarioStudy) -> str:
        return f"{study.twin.zone.name}.envelope.conductance"

    def new_conductance(self, study: ScenarioStudy, case: Case | None = None) -> float:
        """The envelope's conductance with the insulation, W/K."""
        c = case or study.base_case()
        ua = study.parameter(c, self._ua_name(study))
        return insulated_conductance(
            ua, self.r_value, self.area_m2, self.envelope_area_m2
        )

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """Set the envelope conductance to the insulated value."""
        return case.with_parameters(
            **{self._ua_name(study): self.new_conductance(study, case)}
        )

    def title(self, study: ScenarioStudy) -> str:
        """'insulation R 2 m²·K/W over 40 m²'."""
        return f"insulation R {self.r_value:g} m²·K/W over {self.area_m2:g} m²"

    def condition(self, study: ScenarioStudy) -> str:
        """'you added insulation of R 2 m²·K/W over 40 m² (heat loss 180 → 135 W per °C)'."""
        before = study.parameter(study.base_case(), self._ua_name(study))
        after = self.new_conductance(study)
        return (
            f"you added insulation of R {self.r_value:g} m²·K/W over {self.area_m2:g} m², "
            f"cutting your home's heat loss from {before:.0f} to {after:.0f} W per °C"
        )


@dataclass(frozen=True)
class TariffChange(Scenario):
    """The same home and the same hours, billed under ``tariff``."""

    tariff: Tariff

    def apply(self, study: ScenarioStudy, case: Case) -> Case:
        """Swap the tariff; nothing physical changes."""
        return replace(case, tariff=self.tariff)

    def title(self, study: ScenarioStudy) -> str:
        """'on the “Tarifa Plana” tariff'."""
        return f"on the “{self.tariff.name}” tariff"

    def condition(self, study: ScenarioStudy) -> str:
        """'you were on the “Tarifa Plana” tariff'."""
        return f"you were {self.title(study)}"

    def sentence(self, study: ScenarioStudy, base: Outcome, new: Outcome) -> str:
        """Same energy, another price: only the bill moves."""
        old, now = base.eur_per_month, new.eur_per_month
        if round(abs(now - old), 2) < 0.01:
            return (
                f"On the “{self.tariff.name}” tariff the same use would cost the same "
                f"{new.period}: {_eur(old)}."
            )
        word = "less" if now < old else "more"
        return (
            f"On the “{self.tariff.name}” tariff the same use would cost "
            f"{_eur(abs(now - old))} {word} {new.period} ({_eur(now)} instead of {_eur(old)})."
        )
