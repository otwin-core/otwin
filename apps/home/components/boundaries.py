"""Boundaries: temperatures the home does not control.

In Otwin's terms these are *across sources* in the thermal domain: they fix a
temperature regardless of how much heat flows. A home has two kinds:

* :class:`Outdoors`: the weather. An input of the compiled model, fed from a
  measured series (Open-Meteo through :mod:`ingest`) or a scenario.
* :class:`Setpoint`: a dial somebody chose: the thermostat on the wall, the
  knob on the water heater. A parameter (so a scenario can turn it), or an
  input when it follows a schedule (night setback, away mode).

All temperatures are kelvin, like every Otwin thermal component;
:data:`ZERO_CELSIUS` converts.
"""

from __future__ import annotations

from otwin.components.thermal import Ambient

__all__ = ["Outdoors", "Setpoint", "ZERO_CELSIUS"]

#: 0 °C in kelvin.
ZERO_CELSIUS = 273.15


class Outdoors(Ambient):
    """Outside air. Its temperature is an input of the model by default, so a
    weather series drives the twin. The input is named after the component,
    ``"outdoor"`` unless renamed."""

    type_name = "outdoors"

    def __init__(
        self, temperature: float | None = None, *, name: str = "outdoor"
    ) -> None:
        super().__init__(temperature, name=name)


class Setpoint(Ambient):
    """A chosen temperature: what a thermostat aims at.

    A number makes it the parameter ``<name>.temperature``, which scenarios
    and fits may move. ``None`` makes it an input, for schedules.
    """

    type_name = "setpoint"

    def __init__(self, temperature: float | None, *, name: str = "setpoint") -> None:
        if temperature is not None and temperature <= 0:
            raise ValueError(f"{name}: a setpoint is absolute temperature, in kelvin")
        super().__init__(temperature, name=name)
