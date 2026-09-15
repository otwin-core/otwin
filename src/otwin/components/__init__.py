"""Physical primitives, one module per domain.

Import the domain you need::

    from otwin.components.mechanical import Mass, Spring, Damper, Fixed
    from otwin.components.electrical import Resistor, Capacitor, VoltageSource, Ground

Every component declares terminals and parameters, and a constitutive law the
compiler turns into equations. Adding a component means subclassing
:class:`~otwin.components.base.Component`; see ``docs/developer/components.md``.
"""

from . import (
    base,
    catalogue,
    composite,
    electrical,
    hydraulic,
    mechanical,
    rotational,
    thermal,
    twoport,
)
from .base import Component, Composite, Ground, Terminal

__all__ = [
    "Component",
    "Composite",
    "Ground",
    "Terminal",
    "base",
    "electrical",
    "mechanical",
    "rotational",
    "hydraulic",
    "thermal",
    "twoport",
    "composite",
    "catalogue",
]
