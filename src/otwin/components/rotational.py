"""Rotational mechanics: across is angular velocity [rad/s], through is torque [N m].

``Inertia`` has one port, ``shaft``. ``TorsionSpring`` and
``RotationalDamper`` act between ``a`` and ``b``. ``TorqueSource`` drives a shaft.
"""

from __future__ import annotations

from .base import (
    Branch,
    Component,
    Ground,
    Law,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
)

__all__ = [
    "Inertia",
    "TorsionSpring",
    "RotationalDamper",
    "TorqueSource",
    "SpeedSource",
    "Housing",
]


class Housing(Ground):
    """A shaft housing that does not rotate. The rotational reference."""

    type_name = "housing"


class Inertia(Component):
    """A rotating mass: ``H = p^2 / (2 I)``, angular velocity ``omega = p / I``."""

    domain = "rotational"
    type_name = "inertia"

    def __init__(
        self, inertia: float = 1.0, *, speed: float = 0.0, name: str | None = None
    ) -> None:
        super().__init__(name)
        self.add_port("shaft")
        self.I = self.add_parameter("inertia", inertia, "kg m^2", "L = I w")  # noqa: E741
        self.initial_speed = float(speed)

    def branches(self) -> list[Branch]:
        """One across storage against the housing, state ``angular_momentum``
        (kg m^2/s): ``omega = p / I``, energy ``p^2 / 2I``."""
        return [
            StorageBranch(
                self,
                self.shaft,
                None,
                kind="across",
                state="angular_momentum",
                state_unit="kg m^2/s",
                quantity="angular momentum",
                initial=self.initial_speed * self.value("inertia"),
                energy=lambda p: p * p / (2 * self.I),
            )
        ]


class TorsionSpring(Component):
    """A torsion spring: ``H = k theta^2 / 2``, torque ``tau = k theta``."""

    domain = "rotational"
    type_name = "torsion_spring"

    def __init__(
        self, stiffness: float = 1.0, *, twist: float = 0.0, name: str | None = None
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.k = self.add_parameter("stiffness", stiffness, "N m/rad", "T = k theta")
        self.initial_twist = float(twist)

    def branches(self) -> list[Branch]:
        """One through storage ``a`` to ``b``, state ``twist`` (rad):
        ``tau = k theta``, energy ``k theta^2 / 2``."""
        return [
            StorageBranch(
                self,
                self.a,
                self.b,
                kind="through",
                state="twist",
                state_unit="rad",
                quantity="twist",
                initial=self.initial_twist,
                energy=lambda th: self.k * th * th / 2,
            )
        ]


class RotationalDamper(Component):
    """Viscous friction ``tau = b omega``, or a nonlinear ``law(omega) -> tau``.

    A bearing whose loss grows with speed is ``law=lambda w: c1 * w + c2 * w**3``.
    """

    domain = "rotational"
    type_name = "rotational_damper"

    def __init__(
        self,
        damping: float = 1.0,
        *,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self._law = law
        if law is None:
            self.b_ = self.add_parameter(
                "damping", damping, "N m s/rad", "T = b w", nonneg=True, positive=False
            )

    def branches(self) -> list[Branch]:
        """One resistor branch ``a`` to ``b``: ``tau = b omega`` of the relative
        speed, or ``law(omega)`` when a law was given."""
        law = self._law if self._law is not None else (lambda w: self.b_ * w)
        return [ResistorBranch(self, self.a, self.b, law=law)]


class TorqueSource(Component):
    """An external torque on ``shaft``. ``torque=None`` makes it an input."""

    domain = "rotational"
    type_name = "torque"

    def __init__(self, torque: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("shaft")
        self.torque = None if torque is None else float(torque)

    def branches(self) -> list[Branch]:
        """One through source into ``shaft``: the torque (N m), an input when ``None``."""
        return [
            SourceBranch(
                self,
                self.shaft,
                None,
                kind="through",
                value=self.torque,
                unit="N m",
                quantity="torque",
            )
        ]


class SpeedSource(Component):
    """Imposes the angular velocity of ``shaft``."""

    domain = "rotational"
    type_name = "speed_source"

    def __init__(self, speed: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("shaft")
        self.speed = None if speed is None else float(speed)

    def branches(self) -> list[Branch]:
        """One across source: the angular velocity (rad/s) of ``shaft`` against
        the housing, an input when ``None``."""
        return [
            SourceBranch(
                self,
                self.shaft,
                None,
                kind="across",
                value=self.speed,
                unit="rad/s",
                quantity="angular velocity",
            )
        ]
