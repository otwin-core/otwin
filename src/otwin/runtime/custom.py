"""Custom dynamics: the escape hatch.

When the physics is not a network of the components the library ships, or
when you want to hand the runtime a right-hand side you wrote yourself,
:class:`CustomDynamics` wraps ``f(x, u, t)`` with the same ``simulate``,
``step``, ``rhs`` and ``observe`` surface as a compiled :class:`Model`. It runs
on the NumPy backend (the function is Python, so the loop is Python) and
satisfies :class:`otwin.interfaces.TwinModel`, so estimators and forecast
protocols accept it.

A :class:`~otwin.model.PortHamiltonianSystem` can be wrapped the same way::

    custom = CustomDynamics.from_phs(otwin.model.water_tank())
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from . import backends as _bk
from .model import State, Trajectory

__all__ = ["CustomDynamics"]

Array = npt.NDArray[np.floating]


class CustomDynamics:
    """A model given as functions rather than components.

    Args:
        f: ``f(x, u, t) -> dx/dt``.
        n_states, n_inputs: dimensions.
        energy: optional ``H(x)``; enables ``trajectory.energy`` and the
            energy balance.
        observe: optional ``h(x, u, t)``; defaults to the identity.
        jacobian: optional ``df/dx``; finite differences otherwise.
        state_names, input_names: for labelled trajectories.
    """

    backend = "numpy"
    representation = "custom"

    def __init__(
        self,
        f: Callable[[Array, Array, float], Array],
        n_states: int,
        n_inputs: int = 0,
        *,
        energy: Callable[[Array], float] | None = None,
        observe: Callable[[Array, Array, float], Array] | None = None,
        jacobian: Callable[[Array, Array, float], Array] | None = None,
        state_names: Sequence[str] | None = None,
        input_names: Sequence[str] | None = None,
        x0: Array | None = None,
        name: str = "custom",
    ) -> None:
        self._f = f
        self._H = energy
        self._h = observe
        self._jac = jacobian
        self.n_states = int(n_states)
        self.n_inputs = int(n_inputs)
        self.name = name
        self.state_names = list(state_names or [f"x{i}" for i in range(self.n_states)])
        self.input_names = list(input_names or [f"u{i}" for i in range(self.n_inputs)])
        self.output_names: list[str] = []
        self.param_names: list[str] = []
        self._x0 = np.zeros(self.n_states) if x0 is None else np.asarray(x0, dtype=float)

    @classmethod
    def from_phs(cls, phs: Any, name: str = "phs") -> CustomDynamics:
        """Wrap a :class:`~otwin.model.PortHamiltonianSystem` or ``IrreversiblePHS``."""
        return cls(
            lambda x, u, t: np.asarray(phs.rhs(x, u, t), dtype=float),
            phs.n_states,
            phs.n_inputs,
            energy=getattr(phs, "energy", None),
            observe=lambda x, u, t: np.asarray(phs.observe(x, u, t), dtype=float),
            name=name,
        )

    # --- TwinModel surface
    def _u(self, u: Any) -> Array:
        return (
            np.zeros(self.n_inputs) if u is None else np.asarray(u, dtype=float).ravel()
        )

    def rhs(self, x: Array, u: Array | None = None, t: float = 0.0) -> Array:
        return np.asarray(self._f(np.asarray(x, dtype=float), self._u(u), t), dtype=float)

    dynamics = rhs

    def jacobian(self, x: Array, u: Array | None = None, t: float = 0.0) -> Array:
        x = np.asarray(x, dtype=float)
        uu = self._u(u)
        if self._jac is not None:
            return np.asarray(self._jac(x, uu, t), dtype=float)
        f0 = self.rhs(x, uu, t)
        J = np.zeros((self.n_states, self.n_states))
        xp = x.copy()
        for j in range(self.n_states):
            h = 1e-7 * (1 + abs(xp[j]))
            xp[j] += h
            J[:, j] = (self.rhs(xp, uu, t) - f0) / h
            xp[j] -= h
        return J

    def energy(self, x: Array) -> float:
        if self._H is None:
            raise AttributeError("this CustomDynamics has no energy function")
        return float(self._H(np.asarray(x, dtype=float)))

    def observe(self, x: Array, u: Array | None = None, t: float = 0.0) -> Array:
        if self._h is None:
            return np.asarray(x, dtype=float)
        return np.asarray(self._h(np.asarray(x, dtype=float), self._u(u), t), dtype=float)

    def initial_state(self) -> State:
        return State(self._x0, 0.0, self.state_names)

    def state(self, values: Any = None, time: float = 0.0) -> State:
        if values is None:
            return State(self._x0, time, self.state_names)
        if isinstance(values, State):
            return values
        if isinstance(values, dict):
            x = self._x0.copy()
            for k, v in values.items():
                x[self.state_names.index(k)] = float(v)
            return State(x, time, self.state_names)
        return State(np.asarray(values, dtype=float), time, self.state_names)

    def step(
        self,
        state: Any,
        inputs: Any = None,
        dt: float = 1e-3,
        *,
        solver: str = "midpoint",
        **options: Any,
    ) -> State:
        s = self.state(state)
        u = self._u(inputs)
        xn = _bk._step(
            self.rhs, self.jacobian, s.values, lambda th: u, s.time, dt, solver, options
        )
        return State(xn, s.time + dt, self.state_names)

    def simulate(
        self,
        t_span: tuple[float, float] | None = None,
        dt: float | None = None,
        *,
        t: Array | None = None,
        x0: Any = None,
        inputs: Any = None,
        solver: str = "midpoint",
        interp: str = "hold",
        **options: Any,
    ) -> Trajectory:
        if t is None:
            if t_span is None or dt is None:
                raise TypeError("simulate needs t=... or t_span=(t0, t1) with dt=...")
            n = int(round((t_span[1] - t_span[0]) / dt))
            t = t_span[0] + dt * np.arange(n + 1)
        grid = np.asarray(t, dtype=float).ravel()
        s0 = self.state(x0, grid[0])
        if callable(inputs):
            return self._feedback(s0.values, grid, inputs, solver, options)
        U = None
        if inputs is not None:
            U = np.asarray(inputs, dtype=float)
            if U.ndim == 0:
                U = np.full((grid.shape[0], self.n_inputs), float(U))
            elif U.ndim == 1 and self.n_inputs == 1:
                U = U.reshape(-1, 1)
        raw = _bk._simulate_generic(
            self.rhs,
            self.jacobian,
            self.energy if self._H is not None else None,
            None,
            None,
            self.n_inputs,
            0,
            s0.values,
            grid,
            U,
            solver,
            interp,
            options,
            backend="numpy",
        )
        return Trajectory(raw, self)  # type: ignore[arg-type]

    def _feedback(
        self,
        x0: Array,
        t: Array,
        law: Callable[..., Array],
        solver: str,
        options: dict[str, Any],
    ) -> Trajectory:
        nt = t.shape[0]
        X = np.zeros((nt, self.n_states))
        U = np.zeros((nt, self.n_inputs))
        E = np.zeros(nt if self._H is not None else 0)
        x = np.asarray(x0, dtype=float).copy()
        for k in range(nt):
            u = np.asarray(law(float(t[k]), x), dtype=float).ravel()
            X[k], U[k] = x, u
            if self._H is not None:
                E[k] = self.energy(x)
            if k < nt - 1:
                x = _bk._step(
                    self.rhs,
                    self.jacobian,
                    x,
                    lambda th, u=u: u,
                    t[k],
                    t[k + 1] - t[k],
                    solver,
                    options,
                )
        raw = {
            "t": t,
            "x": X,
            "u": U,
            "energy": E,
            "supplied_power": np.zeros(0),
            "outputs": np.zeros((nt, 0)),
            "stats": {"method": solver, "steps": nt - 1, "feedback": True},
            "backend": "numpy",
        }
        return Trajectory(raw, self)  # type: ignore[arg-type]

    def forecast(
        self,
        x0: Array,
        t: Array,
        u: Array | None = None,
        method: str = "midpoint",
        **kw: Any,
    ) -> dict[str, Any]:
        solver = (
            "midpoint" if method in ("auto", "linear", "newton", "fsolve") else method
        )
        tr = self.simulate(t=t, x0=x0, inputs=u, solver=solver, **kw)
        return {
            "t": tr.t,
            "x": tr.x,
            "u": tr.u,
            "energy": tr.energy,
            "method": f"{solver} (numpy)",
            "trajectory": tr,
        }

    def summary(self) -> str:
        return (
            f"CustomDynamics: {self.name}\n  {self.n_states} states {self.state_names}\n"
            f"  {self.n_inputs} inputs {self.input_names}\n  representation: user-supplied f(x, u, t)\n"
            f"  backend: numpy (Python callable)"
        )

    def __repr__(self) -> str:
        return f"CustomDynamics({self.name!r}, {self.n_states} states, {self.n_inputs} inputs)"
