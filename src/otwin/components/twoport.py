"""Lossless two-ports: the elements that couple domains.

A ``Transformer`` scales across against through in the same or different
domains: a gearbox, a lever, an electrical transformer, a hydraulic piston, an
electric machine written with its constant on the through side. A ``Gyrator``
swaps them: a gyroscope, or an electric machine written the other way round.

Both conserve power exactly, so they contribute to ``J`` and never to ``R``.
"""

from __future__ import annotations

from .base import Branch, Component, TwoPortBranch

__all__ = ["Transformer", "Gyrator"]


class Transformer(Component):
    """``across_2 = ratio * across_1`` and ``through_1 = -ratio * through_2``.

    Terminals ``p1, n1`` on side 1 and ``p2, n2`` on side 2. Give the domain of
    each side; the default is electrical on both.
    """

    type_name = "transformer"

    def __init__(
        self,
        ratio: float = 1.0,
        *,
        domain_1: str = "electrical",
        domain_2: str = "electrical",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.domain = domain_1
        self.add_port("p1", domain_1)
        self.add_port("n1", domain_1)
        self.add_port("p2", domain_2)
        self.add_port("n2", domain_2)
        self.n = self.add_parameter(
            "ratio", ratio, "", "across_2 = ratio * across_1", positive=False
        )

    def branches(self) -> list[Branch]:
        return [
            TwoPortBranch(
                self,
                self.p1,
                self.n1,
                kind="transformer",
                a2=self.p2,
                b2=self.n2,
                ratio=self.n,
                label=f"{self.name}.side1",
                label2=f"{self.name}.side2",
            )
        ]


class Gyrator(Component):
    """``across_2 = ratio * through_1`` and ``across_1 = -ratio * through_2``."""

    type_name = "gyrator"

    def __init__(
        self,
        ratio: float = 1.0,
        *,
        domain_1: str = "electrical",
        domain_2: str = "rotational",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.domain = domain_1
        self.add_port("p1", domain_1)
        self.add_port("n1", domain_1)
        self.add_port("p2", domain_2)
        self.add_port("n2", domain_2)
        self.r = self.add_parameter(
            "ratio", ratio, "", "across_2 = ratio * through_1", positive=False
        )

    def branches(self) -> list[Branch]:
        return [
            TwoPortBranch(
                self,
                self.p1,
                self.n1,
                kind="gyrator",
                a2=self.p2,
                b2=self.n2,
                ratio=self.r,
                label=f"{self.name}.side1",
                label2=f"{self.name}.side2",
            )
        ]
