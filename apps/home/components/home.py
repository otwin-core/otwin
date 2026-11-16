"""One home as one simulatable twin: zone, gains, machines, boundaries.

:func:`build_home` connects the components into an Otwin ``System`` and
compiles it. Every gain and space machine is wired to the zone's air node,
the zone to the outdoors, and each water heater's standby loss to the zone
or the outdoors. The result is a :class:`HomeTwin`, which knows

* which inputs the model has, and fills each from its component's
  :class:`~components.schedules.Schedule` unless a measured series is given
  instead;
* which outputs add up to the **electricity** meter and to the **gas**
  meter, so a run reports what the bills and the smart meter would show.

Model time is seconds since ``start`` (a UTC instant). The outdoor
temperature and every other input are held constant over each step, so a
grid aligned to whole hours reproduces hourly data exactly.

Ready-made homes live in :mod:`components.catalogue`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import numpy.typing as npt
import otwin

from .boundaries import Outdoors
from .evaluate import evaluate_outputs
from .gains import Appliance, GasAppliance, HeatGain
from .machines import SpaceMachine, WaterHeater
from .schedules import Schedule
from .zones import ThermalZone

__all__ = ["HomeTwin", "HomeRun", "build_home"]

InputValue = float | npt.ArrayLike | Schedule


@dataclass
class HomeRun:
    """A simulated period: the trajectory, the two meters and step averages.

    ``step_mean[name]`` holds, for each step ``[t_k, t_{k+1})``, the output
    evaluated at the step's midpoint state with the step's held inputs. The
    implicit midpoint rule advances the state with exactly that value, so
    ``h · step_mean`` is the energy each component exchanged in each step,
    exactly as the model saw it. Integrating the grid-point outputs instead
    would be off whenever a held input jumps, at a setpoint change say,
    because the grid-point output already shows the next step's input.
    """

    t: np.ndarray
    trajectory: otwin.runtime.Trajectory
    electricity: np.ndarray  # W at each grid point
    gas: np.ndarray  # W at each grid point
    indoor_temperature: np.ndarray  # K
    step_mean: dict[str, np.ndarray] = field(default_factory=dict)
    meters: dict[str, list[str]] = field(default_factory=dict)

    def energy_j(self, name: str, *, between: tuple[float, float] | None = None) -> float:
        """The integral of output ``name`` over the run or ``between=(t0, t1)``
        (model seconds, both on the grid), in joules for a power output."""
        if name not in self.step_mean:
            raise KeyError(
                f"{name!r} has no step averages; known: {sorted(self.step_mean)}"
            )
        i0, i1 = 0, self.t.size - 1
        if between is not None:
            i0, i1 = (int(np.searchsorted(self.t, v)) for v in between)
            if i1 >= self.t.size or self.t[i0] != between[0] or self.t[i1] != between[1]:
                raise ValueError(f"between={between} must be two points of the grid")
        h = np.diff(self.t[i0 : i1 + 1])
        return float(np.sum(self.step_mean[name][i0:i1] * h))

    def energy_kwh(
        self, meter: str, *, between: tuple[float, float] | None = None
    ) -> float:
        """Energy on ``"electricity"`` or ``"gas"`` in kWh, over the run or
        ``between=(t0, t1)``: the sum of :meth:`energy_j` over the meter's
        outputs."""
        if meter not in self.meters:
            raise KeyError(f"meter must be one of {sorted(self.meters)}")
        return sum(self.energy_j(n, between=between) for n in self.meters[meter]) / 3.6e6

    def cost_eur(
        self,
        meter: str,
        eur_per_kwh: float,
        *,
        fixed_eur_per_day: float = 0.0,
        between: tuple[float, float] | None = None,
    ) -> float:
        """What the period costs on ``meter`` at a flat price.

        ``eur_per_kwh`` multiplies :meth:`energy_kwh`; ``fixed_eur_per_day``
        adds the standing charge (*término fijo*) over the period's length.
        Time-of-use tariffs belong to the app layer, which prices the hourly
        series itself.
        """
        if eur_per_kwh < 0 or fixed_eur_per_day < 0:
            raise ValueError("prices cannot be negative")
        t0, t1 = between if between is not None else (self.t[0], self.t[-1])
        days = (t1 - t0) / 86400.0
        return (
            self.energy_kwh(meter, between=between) * eur_per_kwh
            + fixed_eur_per_day * days
        )

    def __getitem__(self, name: str) -> np.ndarray:
        return self.trajectory[name]


@dataclass
class HomeTwin:
    """A compiled home with its inputs and meters named.

    Built by :func:`build_home`; see the module docstring.
    """

    system: otwin.System
    model: otwin.runtime.Model
    zone: ThermalZone
    outdoor: str
    schedules: dict[str, Schedule] = field(default_factory=dict)
    electric_outputs: list[str] = field(default_factory=list)
    gas_outputs: list[str] = field(default_factory=list)
    #: Outputs whose step averages every run records (the meters and the
    #: zone's heat flows); others can be asked for with ``track=``.
    tracked_outputs: list[str] = field(default_factory=list)

    @property
    def thermometer(self) -> str:
        """The output an interior thermometer reads, K: the heating thermostat's
        own thermometer, else the first machine's, else the zone's air."""
        from .machines import SpaceMachine

        machines = [c for c in self.system.components if isinstance(c, SpaceMachine)]
        machines.sort(key=lambda m: m.sense != "heat")
        if machines:
            return f"{machines[0].name}.thermostat.temperature"
        return f"{self.zone.name}.temperature"

    @property
    def input_names(self) -> list[str]:
        """Every input the model takes."""
        return list(self.model.input_names)

    def inputs(
        self,
        t: npt.ArrayLike,
        *,
        start: datetime | int,
        outdoor: InputValue,
        **measured: InputValue,
    ) -> dict[str, np.ndarray]:
        """Input arrays on the grid ``t``.

        ``outdoor`` is the outdoor temperature (K): a number, an array over
        ``t``, or a :class:`Schedule`. Any other input can be given by name
        (the measured plug series for ``"kitchen"``, say). Inputs not given
        come from the component's schedule, and an input with neither is an
        error, so nothing silently runs at zero.
        """
        ts = np.asarray(t, dtype=float)
        given = {self.outdoor: outdoor, **measured}
        unknown = sorted(set(given) - set(self.input_names))
        if unknown:
            raise KeyError(
                f"{unknown} are not inputs of this home; inputs: {self.input_names}"
            )
        out: dict[str, np.ndarray] = {}
        for name in self.input_names:
            value = given.get(name, self.schedules.get(name))
            if value is None:
                raise KeyError(f"no value and no schedule for input {name!r}")
            if isinstance(value, Schedule):
                arr = value.sample(ts, start=start)
            else:
                arr = np.asarray(value, dtype=float)
                if arr.ndim == 0:
                    arr = np.full(ts.shape, float(arr))
            if arr.shape != ts.shape:
                raise ValueError(
                    f"input {name!r} has {arr.shape} values for {ts.shape} times"
                )
            out[name] = arr
        return out

    def simulate(
        self,
        t: npt.ArrayLike,
        *,
        start: datetime | int,
        outdoor: InputValue,
        x0: object = None,
        track: Sequence[str] = (),
        **measured: InputValue,
    ) -> HomeRun:
        """Run the home over ``t`` (seconds since ``start``) and read the meters.

        ``track`` names further outputs to record step averages for (see
        :class:`HomeRun`).
        """
        ts = np.asarray(t, dtype=float)
        u = self.inputs(ts, start=start, outdoor=outdoor, **measured)
        run = self.model.simulate(t=ts, inputs=u, x0=x0)
        elec = sum((run[n] for n in self.electric_outputs), np.zeros(ts.shape))
        gas = sum((run[n] for n in self.gas_outputs), np.zeros(ts.shape))
        wanted = list(dict.fromkeys([*self.tracked_outputs, *track]))
        return HomeRun(
            ts,
            run,
            elec,
            gas,
            run[f"{self.zone.name}.temperature"],
            step_mean=self._step_means(run, u, wanted),
            meters={
                "electricity": list(self.electric_outputs),
                "gas": list(self.gas_outputs),
            },
        )

    def _step_means(
        self, run: otwin.runtime.Trajectory, u: dict[str, np.ndarray], names: list[str]
    ) -> dict[str, np.ndarray]:
        x = np.asarray(run.x)
        t = np.asarray(run.t)
        held = np.column_stack([u[n] for n in self.model.input_names])
        return evaluate_outputs(
            self.model, names, (x[1:] + x[:-1]) / 2, held[:-1], (t[1:] + t[:-1]) / 2
        )


def build_home(
    zone: ThermalZone,
    *,
    gains: Sequence[HeatGain] = (),
    conditioning: Sequence[SpaceMachine] = (),
    water_heaters: Sequence[tuple[WaterHeater, str]] = (),
    outdoors: Outdoors | None = None,
    schedules: Mapping[str, Schedule] | None = None,
    backend: str = "auto",
    name: str = "home",
) -> HomeTwin:
    """Connect the components of one home and compile it.

    Args:
        zone: the heated (or cooled) space.
        gains: appliances, base loads, occupants, solar; they act on the air,
            except a gain with ``indoors=False``, whose heat goes outside.
        conditioning: space machines, heating and cooling, on the air.
        water_heaters: ``(heater, location)`` pairs, ``location`` being
            ``"indoors"`` (standby loss heats the zone) or ``"outdoors"``.
        outdoors: the outdoor air. A new :class:`Outdoors` if omitted.
        schedules: defaults for inputs, by input name, on top of the
            schedules the components themselves carry.
        backend: ``"auto"``, ``"rust"`` or ``"numpy"``.

    The electricity meter collects every :class:`Appliance` and every
    machine burning electricity; the gas meter, every machine burning gas.
    Free gains (occupants, solar) appear on no meter.
    """
    out = outdoors or Outdoors()
    system = otwin.System(zone, out, name=name)
    system.connect(zone.outside, out.port)
    air = [zone.air]
    electric: list[str] = []
    gas: list[str] = []
    sched: dict[str, Schedule] = {}
    tracked: list[str] = [f"{zone.name}.heat_loss"]
    for g in gains:
        system.add(g)
        if g.indoors:
            air.append(g.port)
        else:
            system.connect(g.port, out.port)  # its heat leaves the home
        tracked.append(f"{g.name}.heat")
        if isinstance(g, Appliance):
            electric.append(f"{g.name}.electric_power")
        elif isinstance(g, GasAppliance):
            gas.append(f"{g.name}.gas_power")
        if g.schedule is not None:
            sched[g.name] = g.schedule
    for m in conditioning:
        system.add(m)
        air.append(m.port)
        tracked.append(f"{m.name}.{m.sense}")
        (gas if m.fuel == "gas" else electric).append(f"{m.name}.fuel_power")
        if m.setpoint_schedule is not None:
            sched[f"{m.name}.setpoint"] = m.setpoint_schedule
    for wh, where in water_heaters:
        system.add(wh)
        if where == "indoors":
            air.append(wh.room)
        elif where == "outdoors":
            system.connect(wh.room, out.port)
        else:
            raise ValueError(f"{wh.name}: location must be 'indoors' or 'outdoors'")
        tracked += [f"{wh.name}.heat", f"{wh.name}.standby_loss"]
        (gas if wh.fuel == "gas" else electric).append(f"{wh.name}.fuel_power")
        if wh.draw_schedule is not None:
            sched[f"{wh.name}.draw"] = wh.draw_schedule
    if len(air) > 1:
        system.connect(*air)
    sched.update(schedules or {})
    model = otwin.compile(system, backend=backend)
    unknown = sorted(set(sched) - set(model.input_names))
    if unknown:
        raise KeyError(f"schedules for {unknown}, which are not inputs of this home")
    tracked = list(dict.fromkeys([*electric, *gas, *tracked]))
    return HomeTwin(system, model, zone, out.name, sched, electric, gas, tracked)
