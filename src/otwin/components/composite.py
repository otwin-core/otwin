"""Components assembled from primitives.

A composite is the recommended way to add a high-level device: build it out of
primitives and two-ports and the compiler treats it like any other part of the
graph. Nothing inside it is special-cased.
"""

from __future__ import annotations

from .base import Composite
from .electrical import Inductor, Resistor
from .rotational import Housing, Inertia, RotationalDamper
from .twoport import Transformer

__all__ = ["DCMotor"]


class DCMotor(Composite):
    """A permanent-magnet DC motor: armature resistance and inductance, the
    electromechanical coupling, rotor inertia and viscous friction.

    Terminals: electrical ``p``, ``n``; rotational ``shaft``.

    Internally the coupling is a transformer with ratio ``1 / k`` between the
    armature branch and the shaft, so that back-emf is ``k omega`` and torque
    is ``k i``. States: ``<name>.armature.flux`` and ``<name>.rotor.angular_momentum``.
    """

    type_name = "dc_motor"
    domain = "electrical"

    def __init__(
        self,
        resistance: float = 1.0,
        inductance: float = 0.5,
        torque_constant: float = 0.5,
        inertia: float = 0.01,
        friction: float = 0.1,
        *,
        current: float = 0.0,
        speed: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        r = Resistor(resistance, name="armature_resistance")
        ind = Inductor(inductance, current=current, name="armature")
        coupling = Transformer(
            1.0 / torque_constant,
            domain_1="electrical",
            domain_2="rotational",
            name="coupling",
        )
        rotor = Inertia(inertia, speed=speed, name="rotor")
        bearing = RotationalDamper(friction, name="bearing")
        housing = Housing(name="housing")
        self.add(r, ind, coupling, rotor, bearing, housing)
        self.connect(r.n, ind.p)
        self.connect(ind.n, coupling.p1)
        self.connect(coupling.p2, rotor.shaft, bearing.a)
        self.connect(coupling.n2, bearing.b, housing.port)
        self.expose("p", r.p)
        self.expose("n", coupling.n1)
        self.expose("shaft", rotor.shaft)
