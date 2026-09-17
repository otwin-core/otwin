"""The compiled model and what a simulation returns.

:class:`Model` is what :func:`otwin.compile` gives back. It owns the
compiled representation, the current parameter values and a backend, and it
answers the questions a digital twin needs answered: where does the state
go from here (``simulate``, ``step``, ``forecast``), what is the derivative
(``rhs``, ``jacobian``), how much energy is stored (``energy``), what would a
sensor read (``outputs``, ``observe``), and what is in the model
(``summary``, ``states``, ``parameters``, ``ir``).

It satisfies :class:`otwin.interfaces.TwinModel`, so the estimators in
:mod:`otwin.estimate` and the protocols in :mod:`otwin.forecast` take it as
they take any other model.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from .. import expr as ex
from ..expr import Expr
from ..ir import PHSIR, OutputVar, ParamVar
from . import backends as _bk

__all__ = ["Model", "State", "Trajectory", "Inputs"]

Array = npt.NDArray[np.floating]
Inputs = Mapping[str, Any] | Array | Callable[..., Any] | None


class State:
    """The state of a compiled model at one instant: values and a time.

    A state returned by :meth:`Model.step` also remembers the inputs that were
    applied over the step, so ``model.outputs(state)`` reads the model with
    those inputs (a resistor's power needs the current that was flowing).
    """

    __slots__ = ("values", "time", "names", "inputs")

    def __init__(
        self,
        values: Array,
        time: float,
        names: Sequence[str],
        inputs: Array | None = None,
    ) -> None:
        self.values = np.asarray(values, dtype=float).ravel().copy()
        self.time = float(time)
        self.names = tuple(names)
        self.inputs = None if inputs is None else np.asarray(inputs, dtype=float).copy()
        if self.values.shape[0] != len(self.names):
            raise ValueError(
                f"state has {self.values.shape[0]} values for {len(self.names)} names"
            )

    def __getitem__(self, key: str | int) -> float:
        if isinstance(key, int):
            return float(self.values[key])
        return float(self.values[self.names.index(key)])

    def as_dict(self) -> dict[str, float]:
        """The state as ``{name: value}``."""
        return {n: float(v) for n, v in zip(self.names, self.values, strict=True)}

    def __array__(self, dtype: Any = None, copy: Any = None) -> Array:
        return self.values.astype(dtype) if dtype is not None else self.values

    def __len__(self) -> int:
        return len(self.names)

    def __repr__(self) -> str:
        body = ", ".join(
            f"{n}={v:.6g}" for n, v in zip(self.names, self.values, strict=True)
        )
        return f"State(t={self.time:g}; {body})"


class Trajectory:
    """What ``simulate`` returns: the state over time and everything derived from it.

    Index it by name: ``trajectory["tank.level"]``, ``trajectory["energy"]``,
    ``trajectory["t"]``. ``trajectory.x`` is the raw ``(len(t), n_states)`` array
    and ``trajectory["x"]`` returns the same, so code written for the 0.x
    ``integrate_phs`` result dict keeps working.
    """

    def __init__(self, raw: dict[str, Any], model: Model) -> None:
        self.t: Array = np.asarray(raw["t"], dtype=float)
        self.x: Array = np.asarray(raw["x"], dtype=float)
        self.u: Array = np.asarray(raw["u"], dtype=float)
        self.energy: Array = np.asarray(raw.get("energy", []), dtype=float)
        self.supplied_power: Array = np.asarray(
            raw.get("supplied_power", []), dtype=float
        )
        self._outputs: Array = np.asarray(
            raw.get("outputs", np.zeros((len(self.t), 0))), dtype=float
        )
        self.stats: dict[str, Any] = dict(raw.get("stats", {}))
        self.backend: str = raw.get("backend", "")
        self.state_names = tuple(model.state_names)
        self.input_names = tuple(model.input_names)
        self.output_names = tuple(model.output_names) if self._outputs.shape[1] else ()

    def __getitem__(self, key: str) -> Array:
        if key == "t":
            return self.t
        if key == "x":
            return self.x
        if key == "u":
            return self.u
        if key == "energy" and self.energy.size:
            return self.energy
        if key == "supplied_power":
            return self.supplied_power
        if key in self.state_names:
            return self.x[:, self.state_names.index(key)]
        if key in self.input_names:
            return self.u[:, self.input_names.index(key)]
        if key in self.output_names:
            return self._outputs[:, self.output_names.index(key)]
        raise KeyError(
            f"{key!r} is not a state, input or output of this model. States: "
            f"{list(self.state_names)}. Outputs: model.output_names."
        )

    def keys(self) -> list[str]:
        """Every key ``__getitem__`` accepts: the arrays, then state and output names."""
        names = [
            "t",
            "x",
            "u",
            "energy",
            "supplied_power",
            *self.state_names,
            *self.output_names,
        ]
        return list(dict.fromkeys(names))

    def outputs(self) -> dict[str, Array]:
        """The recorded named outputs as ``{name: array over t}``."""
        return {k: self._outputs[:, i] for i, k in enumerate(self.output_names)}

    def final(self) -> State:
        """The state at the last grid point."""
        return State(self.x[-1], self.t[-1], self.state_names)

    def energy_balance(self) -> dict[str, float]:
        """How well the discrete power balance held: the largest step on which
        stored energy rose by more than the ports supplied.

        For a model with quadratic energy under the midpoint rule this is zero
        to rounding. A positive value means the integrator, not the physics,
        created energy.
        """
        if self.energy.size < 2:
            return {"max_violation": float("nan"), "steps": 0}
        dH = np.diff(self.energy)
        dt = np.diff(self.t)
        supplied = 0.5 * (self.supplied_power[1:] + self.supplied_power[:-1]) * dt
        excess = dH - supplied
        return {
            "max_violation": float(max(np.max(excess), 0.0)),
            "worst_step": int(np.argmax(excess)),
            "steps": int(dH.size),
        }

    def __repr__(self) -> str:
        return (
            f"Trajectory({len(self.t)} points, t in [{self.t[0]:g}, {self.t[-1]:g}], "
            f"{len(self.state_names)} states, backend={self.backend}, "
            f"solver={self.stats.get('method', '?')})"
        )


class Model:
    """A compiled physical system. Create it with :func:`otwin.compile`."""

    def __init__(
        self,
        ir: PHSIR,
        backend: str = "auto",
        measurements: Sequence[str] | None = None,
        dt: float | None = None,
    ) -> None:
        self._ir = ir
        self._backend = _bk.select_backend(ir, backend)
        self.dt: float | None = None if dt is None else float(dt)
        self.state_names: list[str] = ir.state_names()
        self.input_names: list[str] = ir.input_names()
        self.param_names: list[str] = ir.param_names()
        self.output_names: list[str] = list(ir.outputs)
        self.port_names: list[str] = list(ir.ports)
        self.n_states = ir.n_states
        self.n_inputs = ir.n_inputs
        self._x0 = np.array(ir.initial_state(), dtype=float)
        self._measurements: list[str] | None = None
        if measurements is not None:
            self.measurements = list(measurements)
        self._last_solver: str | None = None

    # ------------------------------------------------------------ identity
    @property
    def name(self) -> str:
        """Name of the system the model was compiled from."""
        return self._ir.name

    @property
    def backend(self) -> str:
        """Name of the execution backend in use: ``"rust"`` or ``"numpy"``."""
        return self._backend.name

    @property
    def representation(self) -> str:
        """The mathematical form, e.g. ``"port-hamiltonian"`` or
        ``"port-hamiltonian + residual"``."""
        return self._ir.representation

    def ir(self) -> PHSIR:
        """The intermediate representation. Advanced: for inspection and debugging."""
        return self._ir

    def __repr__(self) -> str:
        return (
            f"Model({self.name!r}, {self.n_states} states, {self.n_inputs} inputs, "
            f"{len(self.param_names)} parameters, backend={self.backend})"
        )

    # ---------------------------------------------------------- parameters
    @property
    def parameters(self) -> dict[str, float]:
        """Current parameter values as ``{name: value}``.

        Change them with :meth:`set_parameters`.
        """
        vals = self._backend.get_params()
        return {n: float(v) for n, v in zip(self.param_names, vals, strict=True)}

    def set_parameters(
        self, values: Mapping[str, float] | None = None, **kw: float
    ) -> Model:
        """Change parameter values in place. Structure is untouched; nothing is recompiled."""
        updates = dict(values or {})
        updates.update(kw)
        current = self._backend.get_params()
        for name, v in updates.items():
            if name not in self.param_names:
                close = [p for p in self.param_names if p.endswith("." + name)]
                hint = f" Did you mean {close[0]!r}?" if len(close) == 1 else ""
                raise KeyError(f"{name!r} is not a parameter of this model.{hint}")
            current[self.param_names.index(name)] = float(v)
        self._backend.set_params(current)
        return self

    def with_parameters(
        self, values: Mapping[str, float] | None = None, **kw: float
    ) -> Model:
        """A copy of the model with different parameter values."""
        m = Model(self._ir, backend=self.backend, dt=self.dt)
        m.set_parameters(self.parameters)
        m.set_parameters(values, **kw)
        m._measurements = self._measurements
        return m

    # --------------------------------------------------------------- state
    def initial_state(self) -> State:
        """The state the components were declared with (``voltage=``, ``level=`` ...)."""
        return State(self._x0, 0.0, self.state_names)

    def reset(self) -> State:
        """The initial state again; an alias of :meth:`initial_state`."""
        return self.initial_state()

    def state(
        self,
        values: Mapping[str, float] | Sequence[float] | Array | State | None = None,
        time: float = 0.0,
    ) -> State:
        """Build a :class:`State`, from a dict by name, a sequence, or the initial state."""
        if values is None:
            return State(self._x0, time, self.state_names)
        if isinstance(values, State):
            return values
        if isinstance(values, Mapping):
            x = self._x0.copy()
            for k, v in values.items():
                if k not in self.state_names:
                    raise KeyError(f"{k!r} is not a state; states are {self.state_names}")
                x[self.state_names.index(k)] = float(v)
            return State(x, time, self.state_names)
        return State(np.asarray(values, dtype=float), time, self.state_names)

    # ----------------------------------------------------------- evaluation
    def _u(self, u: Any) -> Array:
        """Input vector of length ``n_inputs`` from ``None`` (zeros), a dict by name,
        or an array."""
        if u is None:
            return np.zeros(self.n_inputs)
        if isinstance(u, Mapping):
            out = np.zeros(self.n_inputs)
            for k, v in u.items():
                out[self.input_names.index(k)] = float(v)
            return out
        return np.asarray(u, dtype=float).ravel()

    def rhs(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> Array:
        """dx/dt. The contract name in :class:`otwin.interfaces.TwinModel`."""
        return self._backend.rhs(np.asarray(x, dtype=float), self._u(u), t)

    dynamics = rhs

    def jacobian(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> Array:
        """Jacobian ``df/dx`` of :meth:`rhs`, shape ``(n_states, n_states)``."""
        return self._backend.jacobian(np.asarray(x, dtype=float), self._u(u), t)

    def energy(self, x: Array | State) -> float:
        """Stored energy H(x)."""
        return self._backend.energy(np.asarray(x, dtype=float))

    H = energy

    def grad_H(self, x: Array | State) -> Array:
        """Gradient of the stored energy, ``dH/dx``."""
        return self._backend.grad_h(np.asarray(x, dtype=float))

    def outputs(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> dict[str, float]:
        """Every named quantity at one state.

        With a :class:`State` from :meth:`step` and no ``u``, the inputs of
        that step and its time are used.
        """
        if isinstance(x, State):
            if u is None and x.inputs is not None:
                u = x.inputs
            if t == 0.0:
                t = x.time
            x = x.values
        vals = self._backend.outputs(np.asarray(x, dtype=float), self._u(u), t)
        return {k: float(v) for k, v in zip(self.output_names, vals, strict=True)}

    def output(
        self,
        name: str,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> float:
        """One named output at a state; ``outputs(x, u, t)[name]``."""
        return self.outputs(x, u, t)[name]

    def port_outputs(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> Array:
        """The conjugate of every port: ``y = G^T grad_H + D u``."""
        return self._backend.port_outputs(np.asarray(x, dtype=float), self._u(u), t)

    @property
    def measurements(self) -> list[str]:
        """The outputs :meth:`observe` returns. Defaults to the port outputs."""
        return list(self._measurements) if self._measurements is not None else []

    @measurements.setter
    def measurements(self, names: Sequence[str]) -> None:
        """Select the outputs :meth:`observe` returns; each name must be in ``output_names``."""
        bad = [n for n in names if n not in self.output_names]
        if bad:
            raise KeyError(f"not outputs of this model: {bad}. See model.output_names.")
        self._measurements = list(names)

    def observe(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> Array:
        """What the sensors read: the selected ``measurements``, or the port outputs.

        The contract name in :class:`otwin.interfaces.TwinModel`.
        """
        if self._measurements is None:
            return self.port_outputs(x, u, t)
        vals = self._backend.outputs(np.asarray(x, dtype=float), self._u(u), t)
        idx = [self.output_names.index(n) for n in self._measurements]
        return np.asarray(vals)[idx]

    output_fn = observe

    def power_balance(
        self,
        x: Array | State,
        u: Array | Mapping[str, float] | None = None,
        t: float = 0.0,
    ) -> dict[str, float]:
        """``dH/dt``, the power dissipated and the power supplied through the ports."""
        xx = np.asarray(x, dtype=float)
        g = self.grad_H(xx)
        dx = self.rhs(xx, u, t)
        supplied = self._backend.supplied_power(xx, self._u(u), t)
        dH = float(g @ dx)
        return {"dH_dt": dH, "dissipated": dH - supplied, "supplied": supplied}

    def check_structure(
        self, x: Array | State | None = None, tol: float = 1e-10
    ) -> dict[str, tuple[bool, float]]:
        """Skew-symmetry of J and positive semidefiniteness of R at a state."""
        env = self._ir.environment(
            np.asarray(x if x is not None else self._x0, dtype=float),
            params=self._backend.get_params(),
        )
        J = np.array([[e.evaluate(env) for e in row] for row in self._ir.J], dtype=float)
        R = np.array([[e.evaluate(env) for e in row] for row in self._ir.R], dtype=float)
        skew = float(np.max(np.abs(J + J.T))) if J.size else 0.0
        eig = float(np.min(np.linalg.eigvalsh((R + R.T) / 2))) if R.size else 0.0
        return {"J_skew": (skew <= tol, skew), "R_psd": (eig >= -tol, eig)}

    def structure(self, x: Array | State | None = None) -> dict[str, Array]:
        """Numerical J, R, G, D at a state."""
        env = self._ir.environment(
            np.asarray(x if x is not None else self._x0, dtype=float),
            params=self._backend.get_params(),
        )

        def mat(m: list[list[Any]]) -> Array:
            return np.array([[e.evaluate(env) for e in row] for row in m], dtype=float)

        return {
            "J": mat(self._ir.J),
            "R": mat(self._ir.R),
            "G": mat(self._ir.G),
            "D": mat(self._ir.D),
        }

    # ------------------------------------------------------------ dynamics
    def step(
        self,
        state: State | Array,
        inputs: Any = None,
        dt: float | None = None,
        *,
        solver: str = "midpoint",
        **options: Any,
    ) -> State:
        """Advance the model one time step and return the new :class:`State`.

        ::

            state = model.initial_state()
            for u in schedule:
                state = model.step(state, {"supply": u})

        ``dt`` defaults to the one given at ``otwin.compile(system, dt=...)``
        or to ``model.dt``. For long runs prefer :meth:`simulate`, which
        stays inside the engine for the whole horizon.
        """
        if dt is None:
            dt = self.dt
        if dt is None:
            raise TypeError(
                "step needs a time step: pass dt=..., set model.dt, or compile "
                "with otwin.compile(system, dt=...)"
            )
        s = self.state(state)
        u = self._u(inputs)
        xn = self._backend.step(s.values, u, s.time, float(dt), solver, **options)
        return State(xn, s.time + float(dt), self.state_names, inputs=u)

    def _time_grid(
        self, t_span: tuple[float, float] | None, dt: float | None, t: Array | None
    ) -> Array:
        """The grid for ``simulate``: ``t`` as given, or uniform from ``t_span`` and ``dt``.

        The uniform grid has ``round((t1 - t0) / dt) + 1`` points.
        """
        if t is not None:
            return np.asarray(t, dtype=float).ravel()
        if t_span is None:
            raise TypeError("simulate needs either t=... or t_span=(t0, t1) with dt=...")
        t0, t1 = float(t_span[0]), float(t_span[1])
        if dt is None:
            raise TypeError("give dt with t_span, e.g. simulate(t_span=(0, 10), dt=0.01)")
        n = int(round((t1 - t0) / dt))
        if n < 1:
            raise ValueError("t_span is shorter than dt")
        return t0 + dt * np.arange(n + 1)

    def _input_matrix(
        self, inputs: Any, t: Array, x0: Array
    ) -> tuple[Array | None, Callable[..., Array] | None]:
        """Expand the user's inputs to a (len(t), m) array, or return a feedback law."""
        nt, m = t.shape[0], self.n_inputs
        if inputs is None:
            return None, None
        if callable(inputs):
            return None, inputs
        if isinstance(inputs, Mapping):
            U = np.zeros((nt, m))
            laws: dict[int, Callable[..., Any]] = {}
            for k, v in inputs.items():
                if k not in self.input_names:
                    raise KeyError(
                        f"{k!r} is not an input; inputs are {self.input_names}"
                    )
                j = self.input_names.index(k)
                if callable(v):
                    laws[j] = v
                else:
                    arr = np.asarray(v, dtype=float)
                    U[:, j] = arr if arr.ndim else float(arr)
            if not laws:
                return U, None
            for j, law in laws.items():
                n_args = _n_positional(law)
                if n_args <= 1:
                    U[:, j] = [float(law(tt)) for tt in t]
                    laws[j] = None  # type: ignore[assignment]
            laws = {j: f for j, f in laws.items() if f is not None}
            if not laws:
                return U, None

            def combined(
                tt: float,
                x: Array,
                U: Array = U,
                laws: dict[int, Callable[..., Any]] = laws,
            ) -> Array:
                k = int(np.searchsorted(t, tt, side="right") - 1)
                u = U[min(max(k, 0), nt - 1)].copy()
                for j, f in laws.items():
                    u[j] = float(f(tt, x))
                return u

            return None, combined
        arr = np.asarray(inputs, dtype=float)
        if arr.ndim == 0:
            return np.full((nt, m), float(arr)), None
        if arr.ndim == 1:
            if arr.shape[0] == m and m != nt:
                return np.tile(arr, (nt, 1)), None
            if m == 1:
                if arr.shape[0] != nt:
                    raise ValueError(
                        f"inputs has {arr.shape[0]} samples for {nt} time points"
                    )
                return arr.reshape(nt, 1), None
            raise ValueError(
                "a 1-D inputs array is ambiguous here; pass shape (len(t), n_inputs)"
            )
        if arr.shape != (nt, m):
            raise ValueError(
                f"inputs must have shape (len(t), n_inputs) = {(nt, m)}, got {arr.shape}"
            )
        return arr, None

    # --------------------------------------------------------- closed loops
    def symbol(self, name: str) -> Expr:
        """A symbolic handle on a state, output, input or parameter, for writing
        control laws the engine can run: ``model.symbol("tank.level")``.
        ``"t"`` is time."""
        if name == "t":
            return ex.symbol("time", "t")
        if name in self.state_names:
            return ex.symbol("state", name)
        if name in self.output_names:
            return self._ir.outputs[name].expr
        if name in self.input_names:
            return ex.symbol("input", name)
        if name in self.param_names:
            return ex.symbol("param", name)
        raise KeyError(
            f"{name!r} is not a state, output, input or parameter of this model"
        )

    def closed_loop(self, laws: Mapping[str, Any] | None = None, **kw: Any) -> Model:
        """Close inputs with control laws written as expressions.

        Each law is an :class:`~otwin.expr.Expr` built from ``model.symbol(...)``
        and the functions in :mod:`otwin.expr`. It is compiled into the model,
        so the solver evaluates it at every stage and the loop stays in the
        engine. The closed input becomes an output of the new model::

            level = model.symbol("tank.level")
            closed = model.closed_loop(inlet=maximum(0, 5 * (1.5 - level)))
        """
        all_laws = dict(laws or {})
        all_laws.update(kw)
        if not all_laws:
            return self
        mapping: dict[Expr, Expr] = {}
        for name, law in all_laws.items():
            if name not in self.input_names:
                raise KeyError(f"{name!r} is not an input; inputs are {self.input_names}")
            if not isinstance(law, Expr):
                raise TypeError(
                    f"the law for {name!r} must be an expression built from model.symbol(); "
                    "for a Python callable pass it to simulate(inputs=...) instead"
                )
            mapping[ex.symbol("input", name)] = law
        # laws may refer to other closed inputs: resolve until stable
        for _ in range(len(mapping) + 1):
            new = {k: v.substitute(mapping) for k, v in mapping.items()}
            if new == mapping:
                break
            mapping = new
        for k, v in mapping.items():
            if v.depends_on_symbol(k):
                raise ValueError(f"the law for {k.name!r} depends on itself")
        ir = self._ir

        def sub(e: Expr) -> Expr:
            return e.substitute(mapping)

        def mat(m: list[list[Expr]]) -> list[list[Expr]]:
            return [[sub(e) for e in row] for row in m]

        rhs = [sub(e) for e in ir.rhs]
        states = [ex.symbol("state", n) for n in self.state_names]
        outputs = {k: OutputVar(k, o.unit, sub(o.expr)) for k, o in ir.outputs.items()}
        for i in ir.inputs:
            if ex.symbol("input", i.name) in mapping:
                outputs[i.name] = OutputVar(
                    i.name, i.unit, mapping[ex.symbol("input", i.name)]
                )
        new_ir = PHSIR(
            name=ir.name,
            states=list(ir.states),
            params=list(ir.params),
            inputs=[i for i in ir.inputs if ex.symbol("input", i.name) not in mapping],
            energy=ir.energy,
            grad_H=list(ir.grad_H),
            J=mat(ir.J),
            R=mat(ir.R),
            ports=list(ir.ports),
            port_values=[sub(e) for e in ir.port_values],
            G=mat(ir.G),
            D=mat(ir.D),
            rhs=rhs,
            port_outputs=[sub(e) for e in ir.port_outputs],
            outputs=outputs,
            jacobian=[[e.diff(s) for s in states] for e in rhs]
            if ir.jacobian is not None
            else None,
            representation=ir.representation,
            physical=ir.physical,
            metadata={**ir.metadata, "closed_loop": sorted(k.name for k in mapping)},
        )
        m = Model(new_ir, backend=self.backend, dt=self.dt)
        m.set_parameters(self.parameters)
        if self._measurements is not None:
            m._measurements = list(self._measurements)
        return m

    # ------------------------------------------------------------ grey box
    def parameter(self, name: str) -> Expr:
        """The symbol of a parameter, existing or new, for use in a residual term."""
        return ex.symbol("param", name)

    def with_residual(
        self,
        terms: Mapping[str, Any] | None = None,
        *,
        parameters: Mapping[str, float] | None = None,
        **kw: Any,
    ) -> Model:
        """A grey-box copy: the compiled physics plus symbolic residual terms.

        ``terms`` maps a state name to an expression added to its derivative.
        Expressions are built from :meth:`symbol` and :meth:`parameter`; new
        parameters get their values from ``parameters``. The result is compiled
        like the original, runs in the engine, and its new parameters can be
        estimated with :func:`otwin.hybrid.fit_parameters`::

            v = model.symbol("mass.velocity")
            drag = model.parameter("drag")
            grey = model.with_residual({"mass.momentum": -drag * v * abs(v)}, parameters={"drag": 0.5})
        """
        all_terms = dict(terms or {})
        all_terms.update(kw)
        if not all_terms:
            return self
        ir = self._ir
        rhs = list(ir.rhs)
        new_params = dict(parameters or {})
        for state, term in all_terms.items():
            if state not in self.state_names:
                raise KeyError(f"{state!r} is not a state; states are {self.state_names}")
            e = ex.as_expr(term)
            for sym in e.symbols():
                if (
                    sym.kind == "param"
                    and sym.name not in self.param_names
                    and sym.name not in new_params
                ):
                    raise KeyError(
                        f"the residual for {state!r} uses parameter {sym.name!r}; give its "
                        "value with parameters={...}"
                    )
                if sym.kind == "input" and sym.name not in self.input_names:
                    raise KeyError(f"{sym.name!r} is not an input of the model")
            i = self.state_names.index(state)
            rhs[i] = rhs[i] + e
        params = list(ir.params) + [
            ParamVar(k, float(v), "", "residual", "residual coefficient")
            for k, v in new_params.items()
        ]
        states = [ex.symbol("state", n) for n in self.state_names]
        new_ir = PHSIR(
            name=ir.name,
            states=list(ir.states),
            params=params,
            inputs=list(ir.inputs),
            energy=ir.energy,
            grad_H=list(ir.grad_H),
            J=ir.J,
            R=ir.R,
            ports=list(ir.ports),
            port_values=list(ir.port_values),
            G=ir.G,
            D=ir.D,
            rhs=rhs,
            port_outputs=list(ir.port_outputs),
            outputs=dict(ir.outputs),
            jacobian=[[e.diff(s) for s in states] for e in rhs]
            if ir.jacobian is not None
            else None,
            representation=ir.representation
            if "residual" in ir.representation
            else ir.representation + " + residual",
            physical=ir.physical,
            metadata={
                **ir.metadata,
                "residual": {k: repr(ex.as_expr(v)) for k, v in all_terms.items()},
            },
        )
        m = Model(new_ir, backend=self.backend, dt=self.dt)
        m.set_parameters(self.parameters)
        if self._measurements is not None:
            m._measurements = list(self._measurements)
        return m

    def simulate(
        self,
        t_span: tuple[float, float] | None = None,
        dt: float | None = None,
        *,
        t: Array | None = None,
        x0: State | Mapping[str, float] | Array | None = None,
        inputs: Any = None,
        solver: str = "midpoint",
        interp: str = "hold",
        record: bool = True,
        **options: Any,
    ) -> Trajectory:
        """Run the model forward and return a :class:`Trajectory`.

        Args:
            t_span, dt: a uniform grid from ``t_span[0]`` to ``t_span[1]``; or
            t: an explicit, strictly increasing grid.
            x0: initial state (a ``State``, a dict by name, an array). Defaults
                to the initial conditions given to the components.
            inputs: per input name, a number, an array over the grid, a function
                of time ``f(t)``, or a feedback law ``f(t, x)``. A bare array of
                shape ``(len(t), n_inputs)`` also works. Inputs left out are zero.
            solver: ``"midpoint"`` (implicit, structure-preserving, default),
                ``"rk45"`` (adaptive), ``"rk4"``, ``"euler"``.
            interp: how inputs vary inside a step: ``"hold"`` or ``"linear"``.
            record: record the named outputs along the trajectory.
            options: ``rtol``, ``atol`` (rk45); ``newton_tol``, ``max_newton`` (midpoint).
        """
        if isinstance(inputs, Mapping) and any(
            isinstance(v, Expr) for v in inputs.values()
        ):
            laws = {k: v for k, v in inputs.items() if isinstance(v, Expr)}
            rest = {k: v for k, v in inputs.items() if not isinstance(v, Expr)}
            return self.closed_loop(laws).simulate(
                t_span,
                dt,
                t=t,
                x0=x0,
                inputs=rest or None,
                solver=solver,
                interp=interp,
                record=record,
                **options,
            )
        grid = self._time_grid(t_span, dt, t)
        s0 = self.state(x0, grid[0])
        U, law = self._input_matrix(inputs, grid, s0.values)
        self._last_solver = solver
        if law is None:
            raw = self._backend.simulate(
                s0.values, grid, U, solver, interp, record_outputs=record, **options
            )
            return Trajectory(raw, self)
        return self._simulate_feedback(s0.values, grid, law, solver, record, options)

    def _simulate_feedback(
        self,
        x0: Array,
        t: Array,
        law: Callable[..., Array],
        solver: str,
        record: bool,
        options: dict[str, Any],
    ) -> Trajectory:
        """A control law that reads the state: sample it at each grid point and
        step with the input held. Runs one engine call per step."""
        nt, n, m = t.shape[0], self.n_states, self.n_inputs
        X = np.zeros((nt, n))
        U = np.zeros((nt, m))
        E = np.zeros(nt)
        P = np.zeros(nt)
        Y = np.zeros((nt, len(self.output_names) if record else 0))
        x = np.asarray(x0, dtype=float).copy()
        for k in range(nt):
            u = np.asarray(law(float(t[k]), x), dtype=float).ravel()
            if u.shape[0] != m:
                raise ValueError(
                    f"the control law returned {u.shape[0]} values for {m} inputs"
                )
            X[k], U[k] = x, u
            E[k] = self._backend.energy(x)
            P[k] = self._backend.supplied_power(x, u, t[k])
            if record:
                Y[k] = self._backend.outputs(x, u, t[k])
            if k < nt - 1:
                x = self._backend.step(x, u, t[k], t[k + 1] - t[k], solver, **options)
        raw = {
            "t": t,
            "x": X,
            "u": U,
            "energy": E,
            "supplied_power": P,
            "outputs": Y,
            "stats": {"method": solver, "steps": nt - 1, "feedback": True},
            "backend": self.backend,
        }
        return Trajectory(raw, self)

    def simulate_batch(
        self,
        x0s: Array,
        t: Array,
        *,
        inputs: Array | None = None,
        parameters: Array | Sequence[Mapping[str, float]] | None = None,
        solver: str = "midpoint",
        interp: str = "hold",
        **options: Any,
    ) -> dict[str, Any]:
        """Many runs at once: ``x0s`` is ``(N, n_states)``; ``parameters`` is
        ``(N, n_params)`` or a list of dicts. Returns ``{"t", "x": (N, len(t), n), "energy"}``."""
        grid = np.asarray(t, dtype=float).ravel()
        x0s = np.asarray(x0s, dtype=float)
        if x0s.ndim == 1:
            x0s = x0s.reshape(-1, self.n_states)
        P = None
        if parameters is not None:
            if isinstance(parameters, np.ndarray) or (
                parameters and not isinstance(parameters[0], Mapping)
            ):
                P = np.asarray(parameters, dtype=float)
            else:
                base = self._backend.get_params()
                rows = []
                for d in parameters:
                    row = base.copy()
                    for k, v in d.items():
                        row[self.param_names.index(k)] = float(v)
                    rows.append(row)
                P = np.array(rows)
        U = None
        if inputs is not None:
            U, law = self._input_matrix(inputs, grid, x0s[0])
            if law is not None:
                raise TypeError("simulate_batch takes input schedules, not feedback laws")
        return self._backend.simulate_batch(x0s, grid, U, P, solver, interp, **options)

    def forecast(
        self,
        x0: Array | State,
        t: Array,
        u: Array | None = None,
        method: str = "midpoint",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run forward from ``x0`` over ``t``. Returns a dict with ``"x"`` of shape
        ``(len(t), n_states)``, the same shape as :func:`otwin.model.integrate_phs`.
        """
        solver = (
            "midpoint" if method in ("auto", "linear", "newton", "fsolve") else method
        )
        tr = self.simulate(t=t, x0=x0, inputs=u, solver=solver, **kwargs)
        return {
            "t": tr.t,
            "x": tr.x,
            "u": tr.u,
            "energy": tr.energy,
            "method": f"{solver} ({tr.backend})",
            "trajectory": tr,
        }

    # ---------------------------------------------------------- inspection
    def summary(self) -> str:
        """Human-readable description of the system, its structure and the last solver used."""
        from ..compiler import summary_text

        return summary_text(self._ir, solver=self._last_solver, backend=self.backend)

    def states(self) -> list[dict[str, Any]]:
        """One dict per state with ``name``, ``unit``, ``component``, ``quantity``
        and ``initial``."""
        return [
            {
                "name": s.name,
                "unit": s.unit,
                "component": s.component,
                "quantity": s.quantity,
                "initial": s.initial,
            }
            for s in self._ir.states
        ]

    def inputs(self) -> list[dict[str, Any]]:
        """One dict per input with ``name``, ``unit``, ``component`` and ``quantity``."""
        return [
            {
                "name": i.name,
                "unit": i.unit,
                "component": i.component,
                "quantity": i.quantity,
            }
            for i in self._ir.inputs
        ]

    def ports(self) -> list[str]:
        """Names of the ports, one per source, inputs first."""
        return list(self.port_names)

    def components(self) -> list[dict[str, Any]]:
        """One dict per component with ``name``, ``type`` and ``domain``; empty when
        the model has no physical description."""
        if self._ir.physical is None:
            return []
        return [
            {"name": c.name, "type": c.type, "domain": c.domain}
            for c in self._ir.physical.components
        ]

    def manifest(
        self,
        name: str | None = None,
        *,
        estimated: Sequence[str] = (),
        seed: int | None = None,
        **extra: Any,
    ) -> Any:
        """A :class:`~otwin.interfaces.TwinManifest` for this model: structure
        ``"compiled"``, the current parameter values, and which of them were
        estimated from data. Add validation, calibration and identification
        records afterwards with the manifest's own helpers."""
        import datetime as _dt

        from .. import __version__
        from ..interfaces import Provenance, TwinManifest

        return TwinManifest(
            name=name or self.name,
            model_class="compiled",
            model_kind=self.representation,
            n_states=self.n_states,
            n_inputs=self.n_inputs,
            parameters=self.parameters,
            estimated=tuple(estimated),
            provenance=Provenance(
                created=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                otwin_version=__version__,
                seed=seed,
            ),
            extra={"components": self.components(), "states": self.state_names, **extra},
        )

    def to_json(self, **kw: Any) -> str:
        """The model definition (not the state) as human-readable JSON."""
        d = self._ir.to_dict()
        d["params"] = [
            dict(p, value=v)
            for p, v in zip(d["params"], self._backend.get_params().tolist(), strict=True)
        ]
        return json.dumps(d, **kw)

    def save(self, path: str | Path) -> Path:
        """Write :meth:`to_json` to ``path`` and return it as a :class:`~pathlib.Path`."""
        p = Path(path)
        p.write_text(self.to_json(indent=1))
        return p

    @classmethod
    def load(cls, path: str | Path, backend: str = "auto") -> Model:
        """Rebuild a model from a file written by :meth:`save`."""
        ir = PHSIR.from_json(Path(path).read_text())
        return cls(ir, backend=backend)

    @classmethod
    def from_json(cls, text: str, backend: str = "auto") -> Model:
        """Rebuild a model from the JSON text of :meth:`to_json`."""
        return cls(PHSIR.from_json(text), backend=backend)


def _n_positional(fn: Callable[..., Any]) -> int:
    """Number of positional parameters ``fn`` takes, to tell ``f(t)`` from ``f(t, x)``.

    Returns 2 when the signature cannot be read or takes ``*args``.
    """
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return 2
    n = 0
    for p in sig.parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            n += 1
        elif p.kind == p.VAR_POSITIONAL:
            return 2
    return n
