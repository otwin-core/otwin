"""Translational mechanics: across is velocity [m/s], through is force [N].

A ``Mass`` has one terminal, ``flange``; its velocity is measured against the
inertial frame. ``Spring`` and ``Damper`` act between terminals ``a`` and
``b``; nail one of them to a :class:`Fixed` point when it is attached to the
world. ``ForceSource`` pushes on its flange in the positive direction.
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

__all__ = ["Mass", "Spring", "Damper", "ForceSource", "VelocitySource", "Fixed"]


class Fixed(Ground):
    """A point that does not move. The mechanical reference."""

    type_name = "fixed"


class Mass(Component):
    """A rigid mass: ``H = p^2 / (2 m)``, velocity ``v = p / m``.

    Extra outputs: ``velocity`` (the across variable) and ``kinetic_energy``.
    """

    domain = "mechanical"
    type_name = "mass"

    def __init__(
        self, mass: float = 1.0, *, velocity: float = 0.0, name: str | None = None
    ) -> None:
        super().__init__(name)
        self.terminal("flange")
        self.m = self.param("mass", mass, "kg")
        self.initial_velocity = float(velocity)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.flange,
                None,
                kind="across",
                state="momentum",
                state_unit="kg m/s",
                quantity="momentum",
                initial=self.initial_velocity * self.value("mass"),
                energy=lambda p: p * p / (2 * self.m),
            )
        ]


class Spring(Component):
    """A linear spring: ``H = k x^2 / 2``, force ``F = k x``.

    The state is the extension ``x`` from the natural length, positive when
    ``a`` moves away from ``b``. ``extension`` sets the initial value.
    """

    domain = "mechanical"
    type_name = "spring"

    def __init__(
        self,
        stiffness: float = 1.0,
        *,
        extension: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.terminal("a")
        self.terminal("b")
        self.k = self.param("stiffness", stiffness, "N/m")
        self.initial_extension = float(extension)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.a,
                self.b,
                kind="through",
                state="extension",
                state_unit="m",
                quantity="extension",
                initial=self.initial_extension,
                energy=lambda x: self.k * x * x / 2,
            )
        ]


class Damper(Component):
    """Viscous damping, ``F = c v``.

    Pass ``law`` for a nonlinear damper: a function of the relative velocity
    returning the force, e.g. ``law=lambda v: 0.9 * v * abs(v)`` for quadratic drag.
    """

    domain = "mechanical"
    type_name = "damper"

    def __init__(
        self,
        damping: float = 1.0,
        *,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.terminal("a")
        self.terminal("b")
        self.c = self.param("damping", damping, "N s/m", nonneg=True, positive=False)
        self._law = law

    def branches(self) -> list[Branch]:
        law = self._law if self._law is not None else (lambda v: self.c * v)
        return [ResistorBranch(self, self.a, self.b, law=law)]


class ForceSource(Component):
    """An external force on ``flange``, positive in the positive direction.

    ``force=None`` makes it an input of the compiled model. A number makes it
    a constant, which is how a weight ``m g`` is applied.
    """

    domain = "mechanical"
    type_name = "force"

    def __init__(self, force: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("flange")
        self.force = None if force is None else float(force)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.flange,
                None,
                kind="through",
                value=self.force,
                unit="N",
                quantity="force",
            )
        ]


class VelocitySource(Component):
    """Imposes the velocity of ``flange`` (a kinematic drive)."""

    domain = "mechanical"
    type_name = "velocity_source"

    def __init__(self, velocity: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("flange")
        self.velocity = None if velocity is None else float(velocity)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.flange,
                None,
                kind="across",
                value=self.velocity,
                unit="m/s",
                quantity="velocity",
            )
        ]
