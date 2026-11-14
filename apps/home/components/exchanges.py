"""Exchanges: the paths heat takes between two temperatures.

In Otwin's terms these are *resistors* in the thermal domain: no state, heat
flows down the temperature difference, ``Q = conductance × ΔT``. Every one
is a :class:`~otwin.components.thermal.Convection` under the name of the
path it is in a house, and its conductance (W/K) is a fittable parameter:
these are the numbers a calibration recovers from bills and weather, and the
numbers an insulation or ventilation scenario turns.

* :class:`Envelope`: walls, roof, windows, floor to outside. The ``UA`` of
  an energy certificate.
* :class:`Ventilation`: air change to outside, ρc_p·(air changes × volume)/3600.
  Kept apart from the envelope so "open the windows" and "insulate the
  walls" are different knobs.
* :class:`InteriorSurface`: room air to the building fabric (internal
  surface area × film coefficient).
* :class:`StandbyLoss`: a hot-water cylinder's skin to the room it stands in.
"""

from __future__ import annotations

from otwin.components.thermal import Convection

__all__ = ["Envelope", "Ventilation", "InteriorSurface", "StandbyLoss"]


class Envelope(Convection):
    """Heat loss through walls, roof, windows and floor, in W/K.

    A 90 m² Spanish flat from the 1970s is typically 150-300 W/K; a
    well-insulated one 60-120 W/K. Ports ``a`` (inside) and ``b`` (outside).
    """

    type_name = "envelope"

    def __init__(self, ua: float = 200.0, *, name: str = "envelope") -> None:
        super().__init__(ua, name=name)


class Ventilation(Convection):
    """Air change to the outside, in W/K: about 0.34 W/K per m³/h of air."""

    type_name = "ventilation"

    def __init__(self, ua: float = 40.0, *, name: str = "ventilation") -> None:
        super().__init__(ua, name=name)


class InteriorSurface(Convection):
    """Room air to building fabric, in W/K: hundreds of W/K for a flat."""

    type_name = "interior_surface"

    def __init__(self, ua: float = 600.0, *, name: str = "coupling") -> None:
        super().__init__(ua, name=name)


class StandbyLoss(Convection):
    """A cylinder's skin loss, in W/K. An 80 L *termo* losing 1.2 kWh a day
    at 45 K above the room is about 1.1 W/K."""

    type_name = "standby_loss"

    def __init__(self, ua: float = 1.1, *, name: str = "standby") -> None:
        super().__init__(ua, name=name)
