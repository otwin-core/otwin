"""Electrical primitives: across is voltage [V], through is current [A].

Two-terminal elements have terminals ``p`` and ``n``; current is positive from
``p`` to ``n`` inside the element. Sources deliver into ``p``.
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
    "Resistor",
    "Capacitor",
    "Inductor",
    "VoltageSource",
    "CurrentSource",
    "Ground",
]


class _TwoTerminal(Component):
    domain = "electrical"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("p")
        self.terminal("n")


class Resistor(_TwoTerminal):
    """Ohm's law, ``v = R i``. Dissipates ``i^2 R``.

    Pass ``law`` for a nonlinear element: a function of the voltage returning
    the current, e.g. ``law=lambda v: 1e-9 * (exp(v / 0.026) - 1)`` for a diode.
    """

    type_name = "resistor"

    def __init__(
        self,
        resistance: float = 1.0,
        *,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.R = self.param("resistance", resistance, "ohm")
        self._law = law

    def branches(self) -> list[Branch]:
        law = self._law if self._law is not None else (lambda v: v / self.R)
        return [ResistorBranch(self, self.p, self.n, law=law)]


class Capacitor(_TwoTerminal):
    """Stores charge: ``H = q^2 / (2 C)``, ``v = q / C``."""

    type_name = "capacitor"

    def __init__(
        self,
        capacitance: float = 1.0,
        *,
        voltage: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.C = self.param("capacitance", capacitance, "F")
        self.initial_voltage = float(voltage)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.p,
                self.n,
                kind="across",
                state="charge",
                state_unit="C",
                quantity="charge",
                initial=self.initial_voltage * self.value("capacitance"),
                energy=lambda q: q * q / (2 * self.C),
            )
        ]


class Inductor(_TwoTerminal):
    """Stores flux: ``H = phi^2 / (2 L)``, ``i = phi / L``."""

    type_name = "inductor"

    def __init__(
        self,
        inductance: float = 1.0,
        *,
        current: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.L = self.param("inductance", inductance, "H")
        self.initial_current = float(current)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.p,
                self.n,
                kind="through",
                state="flux",
                state_unit="Wb",
                quantity="flux linkage",
                initial=self.initial_current * self.value("inductance"),
                energy=lambda phi: phi * phi / (2 * self.L),
            )
        ]


class VoltageSource(_TwoTerminal):
    """Imposes ``v_p - v_n``. With ``voltage=None`` it is an input of the model."""

    type_name = "voltage_source"

    def __init__(self, voltage: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.voltage = None if voltage is None else float(voltage)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self, self.p, self.n, kind="across", value=self.voltage, unit="V",
                quantity="voltage",
            )
        ]


class CurrentSource(_TwoTerminal):
    """Delivers a current out of ``p``. With ``current=None`` it is an input."""

    type_name = "current_source"

    def __init__(self, current: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.current = None if current is None else float(current)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self, self.p, self.n, kind="through", value=self.current, unit="A",
                quantity="current",
            )
        ]
