"""The fundamental components: one class per physical role, any domain.

Every component in the library is one of six things. These classes are those
six things, written once, with the domain as an argument. The domain-specific
classes (``Capacitor``, ``Mass``, ``Tank``, ``Resistor``, ``Damper`` ...) are
conveniences over these, with the right names, units and defaults filled in.

Use them when the library has no name for what you need yet, or to see the
whole set of roles in one place:

    >>> from otwin.components.fundamental import Storage, Dissipator, Source, Reference
    >>> c = Storage("electrical", 2.0, kind="across", name="cap")     # a capacitor
    >>> r = Dissipator("electrical", 10.0, name="res")                # a resistor
    >>> v = Source("electrical", kind="across", name="supply")        # a voltage input
    >>> g = Reference(name="gnd")
    >>> c.ports.keys(), c.parameters["coefficient"].unit
    (dict_keys(['p', 'n']), 'F')

The roles:

* :class:`Storage` — one state. ``kind="across"``: stores the integral of the
  through variable and sets the across variable (capacitor, mass, tank,
  thermal mass). ``kind="through"``: stores the integral of the across variable
  and sets the through variable (inductor, spring, fluid inertance).
* :class:`Dissipator` — ``through = law(across)``; linear by default.
* :class:`Source` — imposes the across or the through variable. ``None`` makes
  it an input of the compiled model; a number a constant parameter.
* :class:`Reference` — the zero of the across variable.
* :class:`Transformer`, :class:`Gyrator` — lossless couplings between two
  ports, possibly of different domains (see :mod:`otwin.components.twoport`).
"""

from __future__ import annotations

from .base import (
    DOMAINS,
    Branch,
    Component,
    Ground,
    Law,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
)
from .twoport import Gyrator, Transformer

__all__ = ["Storage", "Dissipator", "Source", "Reference", "Transformer", "Gyrator"]

# Units of the coefficient of each role, per domain. Across storage: state per
# across (F = C/V, kg = (kg m/s)/(m/s) ...). Through storage: state per through.
# Dissipator: across per through (a resistance).
_UNITS = {
    "electrical": {
        "across": "F",
        "through": "H",
        "resistance": "ohm",
        "state_a": "C",
        "state_t": "Wb",
    },
    "mechanical": {
        "across": "kg",
        "through": "m/N",
        "resistance": "N s/m",
        "state_a": "kg m/s",
        "state_t": "m",
    },
    "rotational": {
        "across": "kg m^2",
        "through": "rad/(N m)",
        "resistance": "N m s",
        "state_a": "kg m^2/s",
        "state_t": "rad",
    },
    "hydraulic": {
        "across": "m^3/Pa",
        "through": "Pa s^2/m^3",
        "resistance": "Pa s/m^3",
        "state_a": "m^3",
        "state_t": "Pa s",
    },
    "thermal": {
        "across": "J/K",
        "through": "",
        "resistance": "K/W",
        "state_a": "J",
        "state_t": "",
    },
}


def _check_domain(domain: str) -> None:
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r}; one of {sorted(DOMAINS)}")


class _TwoPort(Component):
    def __init__(self, domain: str, name: str | None) -> None:
        _check_domain(domain)
        self.domain = domain
        super().__init__(name)
        self.add_port("p")
        self.add_port("n")


class Storage(_TwoPort):
    """An energy store of either kind, in any domain.

    Args:
        domain: ``"electrical"``, ``"mechanical"``, ``"rotational"``,
            ``"hydraulic"`` or ``"thermal"``.
        coefficient: capacitance, mass, inertia, compliance ... The energy is
            ``H = x^2 / (2 coefficient)`` for an across storage and the same
            form for a through storage with the through-type coefficient
            (inductance, 1/stiffness, inertance).
        kind: ``"across"`` (capacitor-like) or ``"through"`` (inductor-like).
        initial: initial value of the *state* (charge, momentum, flux ...).
        energy: replace the quadratic energy with your own function of the
            state, e.g. a nonlinear spring or a battery's open-circuit curve.
    """

    type_name = "storage"

    def __init__(
        self,
        domain: str,
        coefficient: float = 1.0,
        *,
        kind: str = "across",
        initial: float = 0.0,
        energy=None,
        name: str | None = None,
    ) -> None:
        if kind not in ("across", "through"):
            raise ValueError("kind must be 'across' or 'through'")
        if kind == "through" and domain == "thermal":
            raise ValueError("thermal has no through storage (heat has no inertia)")
        super().__init__(domain, name)
        self.kind = kind
        units = _UNITS[domain]
        self.coef = self.add_parameter(
            "coefficient", coefficient, units[kind], "state = coefficient * effort"
        )
        self.initial = float(initial)
        self._energy = energy
        self.state_unit = units["state_a" if kind == "across" else "state_t"]

    def branches(self) -> list[Branch]:
        c = self.coef
        energy = self._energy if self._energy is not None else (lambda x: x * x / (2 * c))
        return [
            StorageBranch(
                self,
                self.p,
                self.n,
                kind=self.kind,
                state="state",
                state_unit=self.state_unit,
                quantity="stored quantity",
                initial=self.initial,
                energy=energy,
            )
        ]


class Dissipator(_TwoPort):
    """``through = law(across)``; by default ``across / resistance``.

    Args:
        domain: the physical domain.
        resistance: across per through (ohm, N s/m, Pa s/m^3, K/W ...).
        law: a function of the across variable returning the through variable,
            for a nonlinear element. Then ``resistance`` is ignored.
    """

    type_name = "dissipator"

    def __init__(
        self,
        domain: str,
        resistance: float = 1.0,
        *,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(domain, name)
        self._law = law
        if law is None:
            self.R = self.add_parameter(
                "resistance",
                resistance,
                _UNITS[domain]["resistance"],
                "across = resistance * through",
            )

    def branches(self) -> list[Branch]:
        law = self._law if self._law is not None else (lambda e: e / self.R)
        return [ResistorBranch(self, self.p, self.n, law=law)]


class Source(_TwoPort):
    """Imposes the across variable (``kind="across"``) or the through variable.

    ``value=None`` makes the source an input of the compiled model, named after
    the component. A number makes it a constant that can still be changed with
    ``model.set_parameters``.
    """

    type_name = "source"
    series_ports = ("n", "p")

    def __init__(
        self,
        domain: str,
        value: float | None = None,
        *,
        kind: str = "across",
        name: str | None = None,
    ) -> None:
        if kind not in ("across", "through"):
            raise ValueError("kind must be 'across' or 'through'")
        super().__init__(domain, name)
        self.kind = kind
        self.value_ = None if value is None else float(value)
        d = DOMAINS[domain]
        self.unit = d.across_unit if kind == "across" else d.through_unit
        self.quantity = d.across if kind == "across" else d.through

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.p,
                self.n,
                kind=self.kind,
                value=self.value_,
                unit=self.unit,
                quantity=self.quantity,
            )
        ]


class Reference(Ground):
    """The zero of the across variable, in any domain. Same as ``Ground``."""

    type_name = "reference"
