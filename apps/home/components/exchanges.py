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

from otwin.components.base import Branch, Component, SourceBranch
from otwin.components.thermal import Convection

__all__ = [
    "Envelope",
    "Ventilation",
    "InteriorSurface",
    "StandbyLoss",
    "SkyRadiation",
    "sky_depression",
    "R_SE",
    "H_R",
    "SKY_DIFFERENCE_K",
    "VIEW_FACTOR",
]

# ------------------------------------------------- radiation to the sky
# ISO 13790 §11.4.6 (ISO 52016-1 the same): a building element that sees
# the sky loses, on top of its transmission loss, Φ_r = R_se · U · A · h_r ·
# Δθ_er · F_r, because the sky is colder than the outdoor air.

#: External surface resistance, m²·K/W (ISO 6946).
R_SE = 0.04
#: External radiative coefficient, W/(m²·K): 4·ε·σ·T³ for ε = 0.9 at 10 °C.
H_R = 4 * 0.9 * 5.670374e-8 * (273.15 + 10.0) ** 3
#: Mean difference between the outdoor air and the apparent sky, K. ISO 13790
#: gives 9 K in the tropics, 13 K in sub-polar climates, 11 K in between.
SKY_DIFFERENCE_K = 11.0
#: How much of the sky an element sees, F_r: a flat roof all of it, a wall
#: half (the other half is the ground and the street), a ground floor none.
VIEW_FACTOR = {"roof": 1.0, "wall": 0.5, "ground": 0.0}


def sky_depression(
    view_factor: float, sky_difference_k: float = SKY_DIFFERENCE_K
) -> float:
    """How much colder than the air the envelope's surroundings are, K.

    Summed over an envelope of conductance ``UA`` whose elements see the sky
    with the UA-weighted view factor ``view_factor``, the radiation loss is
    ``UA · R_se · h_r · Δθ_er · F_r``: as if the envelope faced air colder by
    this many kelvin. About 1 K for a flat's facades, 1.2 K for a house
    whose roof sees the whole sky.
    """
    if not 0.0 <= view_factor <= 1.0:
        raise ValueError(f"a view factor is between 0 and 1, not {view_factor}")
    return R_SE * H_R * sky_difference_k * view_factor


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


class SkyRadiation(Component):
    """Long-wave radiation from the envelope to the night sky, in K.

    A fixed temperature step between the outdoor air (port ``a``) and the
    envelope's outer face (port ``b``): the face sits ``depression`` kelvin
    below the air (see :func:`sky_depression`). Everything the envelope loses
    flows through it, so the extra loss is exactly ``UA · depression`` and
    follows the envelope's conductance when a fit changes it. The parameter
    is ``<name>.depression``.
    """

    domain = "thermal"
    type_name = "sky_radiation"

    def __init__(self, depression: float, *, name: str = "sky") -> None:
        super().__init__(name)
        if depression < 0:
            raise ValueError(f"{self.name}: the sky is colder than the air, not warmer")
        self.add_port("a")
        self.add_port("b")
        self.depression = float(depression)

    def branches(self) -> list[Branch]:
        """One across source: ``T_a − T_b = depression``."""
        return [
            SourceBranch(
                self,
                self.a,
                self.b,
                kind="across",
                value=self.depression,
                unit="K",
                quantity="depression",
            )
        ]
