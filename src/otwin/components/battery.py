"""A battery cell or pack, built from the primitives.

::

    from otwin.components.battery import Battery
    bat = Battery(capacity=2.5, ocv=[(0.0, 3.0), (0.5, 3.6), (1.0, 4.1)],
                  resistance=0.03, rc_branches=[(0.02, 2000.0)], thermal=50.0)

Inside there is nothing a battery engineer would not draw on a whiteboard: an
open-circuit voltage source that depends on the state of charge, a series
resistance, one RC pair per polarisation branch, and, when ``thermal`` is
given, a thermal mass warmed by the ohmic losses.

Ports: ``p``, ``n`` (electrical) and, with ``thermal``, ``thermal`` (the cell
temperature node, to connect to a ``Convection`` and an ``Ambient``).

Outputs: ``<name>.soc``, ``<name>.voltage``, ``<name>.current`` and, with
``thermal``, ``<name>.temperature`` and ``<name>.heat_flow``; plus every state
and quantity of the parts (``<name>.r0.power`` ...).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .. import expr as ex
from ..expr import Expr
from .base import Branch, Component, ComponentQuantities, Composite, StorageBranch
from .electrical import Capacitor, Resistor
from .thermal import Losses, ThermalMass

__all__ = ["Battery"]

Curve = Sequence[tuple[float, float]] | Callable[[float], float]


class Battery(Composite):
    """An equivalent-circuit battery: OCV(soc) + R0 + RC pairs, optional thermal.

    Args:
        capacity: nominal capacity in ampere-hours. Fixes the charge scale of
            the OCV table; it is not a tunable parameter.
        ocv: the open-circuit voltage against state of charge (0 to 1), as a
            list of ``(soc, volts)`` points or a function ``soc -> volts``
            (sampled at ``ocv_points`` points). Linear between points.
        resistance: series (ohmic) resistance in ohms.
        rc_branches: polarisation branches as ``(R, C)`` pairs, ohms and farads.
        thermal: heat capacity of the cell in J/K. ``None`` for no thermal model.
        soc: initial state of charge, 0 to 1.
        temperature: initial cell temperature in kelvin (with ``thermal``).
        ocv_points: number of samples when ``ocv`` is a function.

    Current is positive when discharging (flowing out of ``p``).
    """

    type_name = "battery"
    domain = "electrical"
    series_ports = ("n", "p")

    def __init__(
        self,
        capacity: float,
        ocv: Curve,
        *,
        resistance: float = 0.01,
        rc_branches: Sequence[tuple[float, float]] = (),
        thermal: float | None = None,
        soc: float = 1.0,
        temperature: float = 298.15,
        ocv_points: int = 21,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if capacity <= 0:
            raise ValueError(f"{self.name}: capacity must be positive (ampere-hours)")
        if not 0.0 <= soc <= 1.0:
            raise ValueError(f"{self.name}: soc must be between 0 and 1")
        self.capacity = float(capacity)  # Ah, readable back as bat.capacity
        self.charge_full = self.capacity * 3600.0  # coulombs
        socs, volts = _sample(ocv, ocv_points, self.name)
        self.ocv_table = (socs, volts)
        q_knots = [s * self.charge_full for s in socs]

        store = _OpenCircuit(q_knots, volts, initial=soc * self.charge_full, name="ocv")
        r0 = Resistor(resistance, name="r0")
        self.add(store, r0)
        self.connect(r0.n, store.p)
        tail = r0.p
        heaters = [r0]
        for k, (r, c) in enumerate(rc_branches, start=1):
            rk = Resistor(r, name=f"r{k}")
            ck = Capacitor(c, name=f"c{k}")
            self.add(rk, ck)
            self.connect(tail, rk.n, ck.n)
            self.connect(rk.p, ck.p)
            tail = rk.p
            heaters.append(rk)
        self.expose("p", tail)
        self.expose("n", store.n)
        self.thermal = thermal is not None
        if thermal is not None:
            if temperature < 0:
                raise ValueError(f"{self.name}: temperature is absolute, in kelvin")
            cell = ThermalMass(thermal, temperature=temperature, name="cell")
            losses = Losses(*heaters, name="losses")
            self.add(cell, losses)
            self.connect(losses.port, cell.port)
            self.expose("thermal", cell.port)

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``soc`` (charge over full charge), terminal ``voltage`` (V, the OCV
        plus the drop across every series resistor), ``current`` (A, positive
        discharging) and, with ``thermal``, ``temperature`` (K) and ``heat_flow`` (W)."""
        n = self.name
        charge = q.state[f"{n}.ocv.charge"]
        current = -q.through[f"{n}.ocv"]
        voltage = q.across[f"{n}.ocv"]
        # terminal voltage v_p - v_n: the OCV plus the drop across every
        # resistor in series with it (negative while discharging)
        for part in self.parts:
            if isinstance(part, Resistor):
                voltage = voltage + q.across[part.name]
        out = {
            "soc": ("", charge / self.charge_full),
            "voltage": ("V", voltage),
            "current": ("A", current),
        }
        if self.thermal:
            out["temperature"] = ("K", q.across[f"{n}.cell"])
            out["heat_flow"] = ("W", -q.through[f"{n}.losses"])
        return out


class _OpenCircuit(Component):
    """The charge store of a battery: ``v = ocv(q)`` read from a table.

    The energy is the exact integral of the interpolated OCV over the charge,
    so its gradient is the OCV itself.
    """

    domain = "electrical"
    type_name = "open_circuit"

    def __init__(
        self,
        charge_knots: Sequence[float],
        volts: Sequence[float],
        *,
        initial: float,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("p")
        self.add_port("n")
        self.charge_knots = list(charge_knots)
        self.volts = list(volts)
        self.initial = float(initial)

    def branches(self) -> list[Branch]:
        """One across storage ``p`` to ``n``, state ``charge`` (C): energy is
        the integral of the interpolated OCV table, so ``v = ocv(q)``."""
        knots, volts = self.charge_knots, self.volts
        return [
            StorageBranch(
                self,
                self.p,
                self.n,
                kind="across",
                state="charge",
                state_unit="C",
                quantity="charge",
                initial=self.initial,
                energy=lambda q: ex.interp_integral(q, knots, volts),
            )
        ]


def _sample(ocv: Curve, points: int, name: str) -> tuple[list[float], list[float]]:
    """Turn an OCV curve into sorted ``(socs, volts)`` lists: a function is
    sampled at ``points`` evenly spaced socs, a table is sorted and checked for
    distinct socs. Every voltage must be positive."""
    if callable(ocv):
        if points < 2:
            raise ValueError(f"{name}: ocv_points must be at least 2")
        socs = [i / (points - 1) for i in range(points)]
        volts = [float(ocv(s)) for s in socs]
    else:
        pairs = sorted((float(s), float(v)) for s, v in ocv)
        if len(pairs) < 2:
            raise ValueError(f"{name}: ocv needs at least two (soc, volts) points")
        socs = [s for s, _ in pairs]
        volts = [v for _, v in pairs]
        if any(b <= a for a, b in zip(socs[:-1], socs[1:], strict=True)):
            raise ValueError(f"{name}: ocv soc values must be distinct")
    if any(v <= 0 for v in volts):
        raise ValueError(f"{name}: open-circuit voltage must be positive")
    return socs, volts
