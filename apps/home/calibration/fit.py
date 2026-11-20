"""Fit a home twin to one month of hourly electricity and outdoor temperature.

The search is Otwin's own :func:`otwin.hybrid.fit_parameters`: least squares
in the logarithm of each positive parameter, every candidate simulated in
the compiled engine, and :func:`otwin.estimate.identifiability` run on the
sensitivities at the optimum. Nothing here is a second optimiser.

What this module adds is the **measurement**. ``fit_parameters`` compares
model outputs at grid instants, while a smart meter reports the energy of
each hour, an integral (ARCHITECTURE.md, "Choices"). An instant and an hourly mean differ
badly for a thermostat that runs flat out for twenty minutes after a
setback and then eases off. :class:`HourlyMeter` presents the compiled home
to ``fit_parameters`` as a model whose single output, ``"electricity"``, is
the *exact* hourly mean of the meter: the simulation runs on ``substeps``
steps per hour, every meter output is evaluated at each step's midpoint
state with the step's held input (what the implicit midpoint rule applies),
and the steps of each hour are averaged. Each residual is then one hour, as
the meter saw it, and the hours are independent rows for the
identifiability bootstrap.

**The first days.** The house's state at the start of the record is not
known. The meter runs a spin-up first, replaying the record's first week
(one week for a one-node zone, six for a two-node one, whose walls take
one to two weeks to forget), so the twin enters the month in the state its
own parameters imply, the way building simulators use warm-up days. How
much the answer still depends on that start is checked afterwards, in
:mod:`calibration.calibrate`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta, timezone

import numpy as np
from otwin.hybrid import FitResult, fit_parameters

from components import BaseLoad, HomeTwin, SpaceMachine
from components.evaluate import evaluate_outputs

from .data import HourlyData, NotEnoughData

__all__ = [
    "HourlyMeter",
    "ParameterRole",
    "calibration_parameters",
    "fit_hourly",
    "bill_vector",
    "auto_substeps",
    "ELECTRICITY_SIGMA_KWH",
    "GAS_BILL_SIGMA",
    "INDOOR_SIGMA_K",
    "THERMOMETER_OFFSET",
    "OFFSET_BASE_K",
    "default_bounds",
    "default_spinup_weeks",
    "SUBSTEPS",
]

#: Simulation steps per hour. The thermostat's proportional mode is fast
#: (C / (P / band), well under an hour), and a quarter-hour step keeps its
#: discretisation error far below a meter's.
SUBSTEPS = 4

#: Physical bounds by role, (low, high), wide enough for any Spanish home.
_BOUNDS = {
    "heat_loss": (5.0, 5000.0),  # W/K
    "heat_storage": (1e5, 1e10),  # J/K
    "fabric_storage": (1e6, 1e11),  # J/K
    "machine": (100.0, 1e5),  # W
    "base_load": (1.0, 5000.0),  # W
    "sensor": (10.0 - 3.0, 10.0 + 3.0),  # OFFSET_BASE_K ± 3 K
}


@dataclass(frozen=True)
class ParameterRole:
    """What a model parameter means to the household, for fitting and reporting."""

    name: str  # the model parameter, e.g. "zone.envelope.conductance"
    role: str  # heat_loss, heat_storage, fabric_storage, machine, base_load
    component: str  # the component it belongs to
    observable: bool = True  # can the meters given see it at all?
    why_not: str = ""  # plain-language reason when not observable
    given: bool = False  # the householder told us; not fitted
    from_bills: bool = False  # seen only through bill totals, not hour by hour
    beyond_bills: bool = False  # not observable, and no number of bills would show it


_GAS_NO_BILLS = (
    "your heating runs on gas, so the electricity meter does not show how your home "
    "gains or loses heat. Add your gas bills to measure it."
)
_BILL_TOTALS_STORAGE = (
    "gas bills show totals over weeks, not how quickly your home warms up and cools "
    "down. An indoor thermometer would show it."
)
_BILL_TOTALS_SIZE = (
    "gas bills show totals over weeks, not the peaks that would show your boiler's "
    "size. It does not change what the bills say about your walls."
)
_NO_HEATING = (
    "the twin has no heating or cooling, so the meters cannot show how your home "
    "gains or loses heat."
)
_NO_ELECTRICITY = "no hourly electricity was given. Add a month of it to measure this."


def calibration_parameters(
    twin: HomeTwin,
    *,
    gas_bills: bool = False,
    electricity: bool = True,
    indoor: bool = False,
    given: Sequence[str] = (),
) -> list[ParameterRole]:
    """The parameters the data can be asked about, in this twin.

    Hourly electricity shows the thermal parameters and the machine's size
    when the home heats or cools with electricity. Gas bills show a gas-heated
    home's heat loss, but not its heat storage or the boiler's size, because
    they only give totals over weeks. Parameters in ``given`` (values the
    householder told us, such as the heater's power) are never fitted.

    An interior thermometer (``indoor``) shows what no meter does: how fast
    the home cools when the heating stops at night and how fast the heating
    warms it back in the morning. With it, the heat storage and a gas
    boiler's size can be measured, and a home's heat loss even with no
    heating at all, from how the indoor temperature follows the outdoor one.
    """
    zone = twin.zone.name
    machines = [c for c in twin.system.components if isinstance(c, SpaceMachine)]
    electric = any(m.fuel == "electricity" for m in machines)
    gas = any(m.fuel == "gas" for m in machines)
    if electric or indoor:
        loss_why = storage_why = ""
    elif gas and gas_bills:
        loss_why, storage_why = "", _BILL_TOTALS_STORAGE
    elif gas:
        loss_why = storage_why = _GAS_NO_BILLS
    else:
        loss_why = storage_why = _NO_HEATING
    by_bills = not electric and not indoor and gas and gas_bills

    def beyond(why: str) -> bool:
        return why in (_BILL_TOTALS_STORAGE, _BILL_TOTALS_SIZE)

    roles = [
        ParameterRole(
            f"{zone}.envelope.conductance",
            "heat_loss",
            zone,
            not loss_why,
            loss_why,
            from_bills=by_bills,
        ),
        ParameterRole(
            f"{zone}.air.capacity",
            "heat_storage",
            zone,
            not storage_why,
            storage_why,
            beyond_bills=beyond(storage_why),
        ),
    ]
    if twin.zone.two_node:
        roles.append(
            ParameterRole(
                f"{zone}.fabric.capacity",
                "fabric_storage",
                zone,
                not storage_why,
                storage_why,
                beyond_bills=beyond(storage_why),
            )
        )
    for m in machines:
        if m.fuel == "electricity" or indoor:
            why = ""  # the meter, or the morning warm-up on the thermometer
        else:
            why = _BILL_TOTALS_SIZE if gas_bills else _GAS_NO_BILLS
        roles.append(
            ParameterRole(
                f"{m.name}.thermostat.power",
                "machine",
                m.name,
                not why,
                why,
                beyond_bills=beyond(why),
            )
        )
    for c in twin.system.components:
        if isinstance(c, BaseLoad):
            why = "" if electricity else _NO_ELECTRICITY
            roles.append(
                ParameterRole(f"{c.name}.power", "base_load", c.name, not why, why)
            )
    if indoor:
        roles.append(ParameterRole(THERMOMETER_OFFSET, "sensor", "thermometer"))
    given = set(given)
    return [
        replace(r, observable=False, why_not="", given=True) if r.name in given else r
        for r in roles
    ]


def default_spinup_weeks(twin: HomeTwin) -> int:
    """Weeks of spin-up: one for a one-node zone (it forgets its start within
    a day, so a week is ten time constants), six for a two-node zone (walls
    and slab take one to two weeks)."""
    return 6 if twin.zone.two_node else 1


class HourlyMeter:
    """A compiled home seen through its electricity meter, hour by hour.

    Duck-types the parts of :class:`otwin.runtime.Model` that
    :func:`otwin.hybrid.fit_parameters` uses: ``param_names``,
    ``output_names``, ``parameters``, ``set_parameters``, ``with_parameters``
    and ``simulate``. ``simulate`` returns ``{"electricity": kWh per hour}``
    over the record; hours without a reading come back as zero, matching the
    zero the measurement carries there, so they add nothing to the fit.

    Args:
        twin: the home, with the parameter values to evaluate.
        data: the record.
        substeps: simulation steps per hour.
        spinup_weeks: how many times the record's first week is replayed
            before the record, so the twin enters it in a consistent state.
        spinup_offset_c: added to the outdoor temperature during the spin-up
            only. Zero for fitting; the start-state check uses ±3 K to ask
            how much the answer depends on how warm the house was at the start.
    """

    output_names = ["electricity", "gas", "indoor"]

    def __init__(
        self,
        twin: HomeTwin,
        data: HourlyData,
        *,
        substeps: int = SUBSTEPS,
        spinup_weeks: int | None = None,
        spinup_offset_c: float = 0.0,
        offset_k: float = 0.0,
    ) -> None:
        if substeps < 1:
            raise ValueError("substeps must be at least 1")
        weeks = default_spinup_weeks(twin) if spinup_weeks is None else int(spinup_weeks)
        if weeks < 0:
            raise ValueError("spinup_weeks cannot be negative")
        self.twin = twin
        self.data = data
        self.substeps = int(substeps)
        self.spinup_weeks = weeks
        self.spinup_offset_c = float(spinup_offset_c)
        #: How far the householder's thermometer reads above the room, K: where
        #: it hangs (by a window, over the oven) and its calibration. Fitted
        #: with the home, so neither is mistaken for the walls or the boiler.
        self.offset_k = float(offset_k)
        self._grid = self._build_grid()

    # ---------------------------------------------------- the Model surface
    @property
    def model(self):
        """The compiled model inside."""
        return self.twin.model

    @property
    def param_names(self) -> list[str]:
        """The compiled model's parameter names, and the thermometer's offset
        when the record has an indoor temperature."""
        extra = [THERMOMETER_OFFSET] if self.data.indoor_c is not None else []
        return list(self.model.param_names) + extra

    @property
    def parameters(self) -> dict[str, float]:
        """The current parameter values (see :attr:`param_names`)."""
        out = dict(self.model.parameters)
        if self.data.indoor_c is not None:
            out[THERMOMETER_OFFSET] = OFFSET_BASE_K + self.offset_k
        return out

    def _split(self, values: Mapping[str, float] | None, kw: Mapping[str, float]):
        values = {**(values or {}), **kw}
        offset = values.pop(THERMOMETER_OFFSET, None)
        return values, offset

    def set_parameters(self, values: Mapping[str, float] | None = None, **kw: float):
        """Change parameter values in place."""
        model_values, offset = self._split(values, kw)
        if model_values:
            self.model.set_parameters(model_values)
        if offset is not None:
            self.offset_k = float(offset) - OFFSET_BASE_K
        return self

    def with_parameters(self, values: Mapping[str, float] | None = None, **kw: float):
        """A copy with different parameter values; this one is untouched."""
        model_values, offset = self._split(values, kw)
        return self.variant(
            model=self.model.with_parameters(model_values),
            offset_k=self.offset_k if offset is None else float(offset) - OFFSET_BASE_K,
        )

    def variant(
        self,
        *,
        model=None,
        spinup_offset_c: float | None = None,
        offset_k: float | None = None,
    ) -> HourlyMeter:
        """The same meter with another model, spin-up offset or thermometer offset."""
        return HourlyMeter(
            replace(self.twin, model=model if model is not None else self.model),
            self.data,
            substeps=self.substeps,
            spinup_weeks=self.spinup_weeks,
            spinup_offset_c=(
                self.spinup_offset_c if spinup_offset_c is None else spinup_offset_c
            ),
            offset_k=self.offset_k if offset_k is None else offset_k,
        )

    def simulate(self, t=None, x0=None, inputs=None, solver: str = "midpoint", **options):
        """The meters over the record: ``{"electricity": kWh per hour, "gas": ...}``.

        ``"gas"`` is present when the record has gas bills: each bill's total
        (kWh) sits at the bill's last hour, zeros elsewhere, so it lines up
        with the record's hours as ``fit_parameters`` requires. ``t`` must be
        the record's hours (``data.t``); ``x0`` and ``inputs`` are ignored,
        because the meter carries the record's own inputs and starts from its
        spin-up.
        """
        if t is not None and np.asarray(t).size != self.data.hours:
            raise ValueError(f"expected the record's {self.data.hours} hours")
        elec, gas, indoor = self.readings(solver=solver, **options)
        out = {"electricity": np.where(self.data.observed, elec, 0.0)}
        if self.data.gas_bills:
            out["gas"] = bill_vector(self.data, self.bill_totals(gas))
        if indoor is not None:
            out["indoor"] = np.where(self.data.indoor_observed, indoor, 0.0)
        return out

    def meters(
        self, solver: str = "midpoint", **options
    ) -> tuple[np.ndarray, np.ndarray]:
        """Hourly electricity and gas over the record, kWh per hour."""
        elec, gas, _ = self.readings(solver=solver, indoor=False, **options)
        return elec, gas

    def readings(
        self, solver: str = "midpoint", indoor: bool | None = None, **options
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Hourly electricity and gas (kWh per hour) and, when the record has an
        indoor temperature (or ``indoor=True``), what the twin's interior
        thermometer reads, the hourly mean in °C; all from one simulation."""
        if indoor is None:
            indoor = self.data.indoor_c is not None
        e_names, g_names = self.twin.electric_outputs, self.twin.gas_outputs
        thermo = [self.twin.thermometer] if indoor else []
        names = list(e_names) + list(g_names) + thermo
        if not names:
            z = np.zeros(self.data.hours)
            return z, z, None
        watts = self.hourly(names, solver=solver, **options)

        def total(ns):
            if not ns:
                return np.zeros(self.data.hours)
            return np.sum([watts[n] for n in ns], axis=0) / 1000.0

        reading = watts[thermo[0]] - 273.15 + self.offset_k if thermo else None
        return total(e_names), total(g_names), reading

    def bill_totals(self, gas_hourly: np.ndarray | None = None) -> np.ndarray:
        """The twin's gas over each bill of the record, kWh."""
        if gas_hourly is None:
            gas_hourly = self.meters()[1]
        return np.array([gas_hourly[b.start : b.end].sum() for b in self.data.gas_bills])

    # --------------------------------------------------------- the meter
    def _build_grid(self):
        """One simulation grid per period of the record (one for a plain record)."""
        return [self._period_grid(i, j, when) for i, j, when in self.data.spans]

    def _period_grid(self, i0: int, i1: int, when):
        d, sub = self.data, self.substeps
        n = i1 - i0
        week = min(7 * 24, n)
        prefix = self.spinup_weeks * week
        hours = prefix + n
        t = np.arange(hours * sub + 1) * (3600.0 / sub)
        # elapsed, not wall-clock
        start = when.astimezone(timezone.utc) - timedelta(hours=prefix)

        def with_prefix(hourly: np.ndarray, offset: float = 0.0) -> np.ndarray:
            return np.concatenate(
                [np.tile(hourly[:week], self.spinup_weeks) + offset, hourly]
            )

        def expand(hourly: np.ndarray) -> np.ndarray:
            """Hourly means (plug readings): held over every step of the hour."""
            full = with_prefix(hourly)
            return np.append(np.repeat(full, sub), full[-1])

        def instants(hourly: np.ndarray, offset: float) -> np.ndarray:
            """Hourly instants (weather): each step holds the value at its
            midpoint, interpolated linearly between readings."""
            full = with_prefix(hourly, offset)
            mid = (t[:-1] + t[1:]) / 2 / 3600.0
            held = np.interp(mid, np.arange(full.size, dtype=float), full)
            return np.append(held, full[-1])

        kelvin = d.outdoor_c[i0:i1] + 273.15
        outdoor = instants(kelvin, self.spinup_offset_c)
        if self.spinup_offset_c:
            # the offset applies to the spin-up only; the record keeps its weather
            exact = instants(kelvin, 0.0)
            outdoor[prefix * sub :] = exact[prefix * sub :]
        measured = {k: expand(v[i0:i1]) for k, v in d.measured.items()}
        return t, start, outdoor, measured, prefix

    def hourly(self, names: Sequence[str], solver: str = "midpoint", **options):
        """Exact hourly means of model outputs over the record, ``{name: (hours,)}``.

        Each period is simulated on its own, from its own spin-up, and the
        hours are joined in the record's order."""
        parts = [
            self._hourly_period(grid, names, solver, **options) for grid in self._grid
        ]
        return {n: np.concatenate([p[n] for p in parts]) for n in names}

    def _hourly_period(self, grid, names, solver, **options):
        t, start, outdoor, measured, prefix = grid
        u = self.twin.inputs(t, start=start, outdoor=outdoor, **measured)
        run = self.model.simulate(t=t, inputs=u, solver=solver, **options)
        x = np.asarray(run.x)
        held = np.column_stack([u[n] for n in self.model.input_names])
        means = evaluate_outputs(
            self.model, list(names), (x[1:] + x[:-1]) / 2, held[:-1], (t[1:] + t[:-1]) / 2
        )
        sub = self.substeps
        return {n: v.reshape(-1, sub).mean(axis=1)[prefix:] for n, v in means.items()}


def bill_vector(data: HourlyData, totals) -> np.ndarray:
    """Bill totals placed at each bill's last hour, zeros elsewhere."""
    v = np.zeros(data.hours)
    for b, kwh in zip(data.gas_bills, totals, strict=True):
        v[b.end - 1] = kwh
    return v


#: Typical mismatch of one hour of electricity, kWh: what weights the hours.
ELECTRICITY_SIGMA_KWH = 0.1
#: The fitted offset of the householder's thermometer (see HourlyMeter). Its
#: value is OFFSET_BASE_K + the offset in K: the search steps each value by a
#: fraction of itself, and around zero that step would vanish.
THERMOMETER_OFFSET = "thermometer.offset"
OFFSET_BASE_K = 10.0
#: Typical mismatch of one hour of indoor temperature, K: a thermometer's
#: accuracy, where in the home it hangs, the sun through a window.
INDOOR_SIGMA_K = 0.3
#: Typical mismatch of one gas bill, as a fraction of it (estimated readings,
#: PCS changes, hot-water use): what weights the bills, and the floor on their
#: uncertainty when there are too few to estimate it.
GAS_BILL_SIGMA = 0.08


def auto_substeps(data: HourlyData) -> int:
    """Steps per hour: four for a month, fewer for a year of bills, whose totals
    over weeks do not need quarter-hour detail. Several separate periods are
    each simulated on their own, so it is the longest one that counts."""
    longest = max(j - i for i, j, _ in data.spans)
    return SUBSTEPS if longest <= 62 * 24 else 2


def fit_hourly(
    twin: HomeTwin,
    data: HourlyData,
    parameters: Sequence[str],
    *,
    guess: Mapping[str, float] | None = None,
    bounds: Mapping[str, tuple[float, float]] | None = None,
    substeps: int | None = None,
    spinup_weeks: int | None = None,
    max_evaluations: int = 300,
) -> tuple[FitResult, HourlyMeter]:
    """Run :func:`otwin.hybrid.fit_parameters` against the meters.

    The hourly electricity and, when the record has them, the gas bills and
    the indoor temperature are fitted together, each weighted by its typical
    mismatch. Returns the fit
    and the meter at the fitted values.
    """
    if not data.observed.any() and not data.gas_bills:
        raise NotEnoughData("there are no electricity readings or gas bills to fit")
    meter = HourlyMeter(
        replace(twin, model=twin.model.with_parameters(dict(guess or {}))),
        data,
        substeps=substeps or auto_substeps(data),
        spinup_weeks=spinup_weeks,
    )
    measurements = {"electricity": np.where(data.observed, data.electricity_kwh, 0.0)}
    weights = {"electricity": 1.0 / ELECTRICITY_SIGMA_KWH}
    if data.gas_bills:
        kwh = np.array([b.kwh for b in data.gas_bills])
        measurements["gas"] = bill_vector(data, kwh)
        weights["gas"] = 1.0 / (GAS_BILL_SIGMA * max(float(kwh.mean()), 1.0))
    if data.indoor_c is not None:
        measurements["indoor"] = np.where(data.indoor_observed, data.indoor_c, 0.0)
        weights["indoor"] = 1.0 / INDOOR_SIGMA_K
    fit = fit_parameters(
        meter,
        data.t,
        measurements,
        list(parameters),
        bounds=dict(bounds or {}),
        weights=weights,
        check_identifiability=True,
        max_evaluations=max_evaluations,
    )
    return fit, fit.model


def default_bounds(roles: Sequence[ParameterRole]) -> dict[str, tuple[float, float]]:
    """Physical bounds for the parameters being fitted."""
    return {r.name: _BOUNDS[r.role] for r in roles}
