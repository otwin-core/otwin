"""Execution backends for a compiled model.

Both backends consume the same lowered IR and expose the same interface:
``rhs``, ``jacobian``, ``energy``, ``grad_h``, ``outputs``, ``port_outputs``,
``supplied_power``, ``step`` and ``simulate``. The Rust backend
(:mod:`otwin_engine`) is the engine; the NumPy backend is the reference
implementation that runs where the extension is not installed and that the
test suite uses as the oracle for the Rust one.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from ..expr import Expr, _eval_pw
from ..ir import PHSIR

__all__ = [
    "Backend",
    "NumpyBackend",
    "RustBackend",
    "select_backend",
    "EngineNotAvailable",
]

Array = npt.NDArray[np.floating]
SOLVERS = ("euler", "rk4", "rk45", "midpoint")


class EngineNotAvailable(UserWarning):
    """The Rust engine is not installed; the NumPy backend is being used."""


_warned = False


class Backend:
    """Interface shared by the two execution backends."""

    name = "abstract"

    def __init__(self, ir: PHSIR) -> None:
        self.ir = ir
        self.n_states = ir.n_states
        self.n_inputs = ir.n_inputs
        self.n_params = ir.n_params
        self.output_names = list(ir.outputs)

    # parameters
    def get_params(self) -> Array:
        raise NotImplementedError

    def set_params(self, values: Array) -> None:
        raise NotImplementedError

    # evaluation
    def rhs(self, x: Array, u: Array, t: float) -> Array:
        raise NotImplementedError

    def jacobian(self, x: Array, u: Array, t: float) -> Array:
        raise NotImplementedError

    def energy(self, x: Array) -> float:
        raise NotImplementedError

    def grad_h(self, x: Array) -> Array:
        raise NotImplementedError

    def outputs(self, x: Array, u: Array, t: float) -> Array:
        raise NotImplementedError

    def port_outputs(self, x: Array, u: Array, t: float) -> Array:
        raise NotImplementedError

    def supplied_power(self, x: Array, u: Array, t: float) -> float:
        raise NotImplementedError

    def step(
        self, x: Array, u: Array, t: float, dt: float, method: str, **opts: Any
    ) -> Array:
        raise NotImplementedError

    def simulate(
        self,
        x0: Array,
        t: Array,
        u: Array | None,
        method: str,
        interp: str,
        **opts: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def simulate_batch(
        self,
        x0s: Array,
        t: Array,
        u: Array | None,
        params: Array | None,
        method: str,
        interp: str,
        **opts: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError


# ----------------------------------------------------------------------------
# Rust
# ----------------------------------------------------------------------------
class RustBackend(Backend):
    name = "rust"

    def __init__(self, ir: PHSIR) -> None:
        super().__init__(ir)
        import json

        import otwin_engine

        self._m = otwin_engine.Model(json.dumps(ir.lower()))

    def get_params(self) -> Array:
        return np.asarray(self._m.params, dtype=float)

    def set_params(self, values: Array) -> None:
        self._m.params = np.ascontiguousarray(values, dtype=float)

    def rhs(self, x: Array, u: Array, t: float) -> Array:
        return self._m.rhs(_c(x), _c(u), float(t))

    def jacobian(self, x: Array, u: Array, t: float) -> Array:
        return self._m.jacobian(_c(x), _c(u), float(t))

    def energy(self, x: Array) -> float:
        return float(self._m.energy(_c(x)))

    def grad_h(self, x: Array) -> Array:
        return self._m.grad_h(_c(x))

    def outputs(self, x: Array, u: Array, t: float) -> Array:
        return self._m.outputs(_c(x), _c(u), float(t))

    def port_outputs(self, x: Array, u: Array, t: float) -> Array:
        return self._m.port_outputs(_c(x), _c(u), float(t))

    def supplied_power(self, x: Array, u: Array, t: float) -> float:
        return float(self._m.supplied_power(_c(x), _c(u), float(t)))

    def step(
        self, x: Array, u: Array, t: float, dt: float, method: str, **opts: Any
    ) -> Array:
        return self._m.step(
            _c(x), _c(u), float(t), float(dt), method=method, **_engine_opts(opts)
        )

    def simulate(
        self, x0: Array, t: Array, u: Array | None, method: str, interp: str, **opts: Any
    ) -> dict[str, Any]:
        uu = None if u is None else np.ascontiguousarray(u, dtype=float)
        out = self._m.simulate(
            _c(x0),
            _c(t),
            uu,
            method=method,
            interp=interp,
            **_engine_opts(opts, sim=True),
        )
        out["backend"] = self.name
        return out

    def simulate_batch(
        self,
        x0s: Array,
        t: Array,
        u: Array | None,
        params: Array | None,
        method: str,
        interp: str,
        **opts: Any,
    ) -> dict[str, Any]:
        uu = None if u is None else np.ascontiguousarray(u, dtype=float)
        pp = None if params is None else np.ascontiguousarray(params, dtype=float)
        out = self._m.simulate_batch(
            np.ascontiguousarray(x0s, dtype=float),
            _c(t),
            uu,
            pp,
            method=method,
            interp=interp,
            **_engine_opts(opts),
        )
        out["backend"] = self.name
        return out


def _c(a: Any) -> Array:
    return np.ascontiguousarray(np.asarray(a, dtype=float).ravel())


def _engine_opts(opts: dict[str, Any], sim: bool = False) -> dict[str, Any]:
    keys = {"rtol", "atol", "newton_tol", "max_newton"}
    if sim:
        keys |= {"record_outputs", "record_energy"}
    unknown = set(opts) - keys - {"max_substeps"}
    if unknown:
        raise TypeError(f"unknown solver option(s): {sorted(unknown)}")
    return {k: v for k, v in opts.items() if k in keys}


# ----------------------------------------------------------------------------
# NumPy reference
# ----------------------------------------------------------------------------
def _sign(a: float) -> float:
    return 0.0 if a == 0 else math.copysign(1.0, a)


def _sqrt(a: float) -> float:
    return math.sqrt(a) if a >= 0 else math.nan


def _log(a: float) -> float:
    return math.log(a) if a > 0 else (-math.inf if a == 0 else math.nan)


def _exp(a: float) -> float:
    try:
        return math.exp(a)
    except OverflowError:
        return math.inf


def _pow(a: float, b: float) -> float:
    if b == 2.0:
        return a * a
    try:
        return math.pow(a, b)
    except (ValueError, OverflowError):
        return math.nan


def _div(a: float, b: float) -> float:
    if b == 0.0:
        return math.copysign(math.inf, a) if a != 0 else math.nan
    return a / b


_NS = {
    "_pw": _eval_pw,
    "_sign": _sign,
    "_sqrt": _sqrt,
    "_log": _log,
    "_exp": _exp,
    "_pow": _pow,
    "_div": _div,
    "_tanh": math.tanh,
    "_sin": math.sin,
    "_cos": math.cos,
    "_abs": abs,
}


def _codegen(e: Expr, order: dict[str, int]) -> str:
    """Python source for one expression over a flat table ``v``."""
    if e.is_const:
        return repr(float(e.value))
    if e.is_symbol:
        return f"v[{order[e.key]}]"
    a = [_codegen(x, order) for x in e.args]
    op = e.op
    if op == "add":
        return f"({a[0]} + {a[1]})"
    if op == "sub":
        return f"({a[0]} - {a[1]})"
    if op == "mul":
        return f"({a[0]} * {a[1]})"
    if op == "div":
        return f"_div({a[0]}, {a[1]})"
    if op == "pow":
        return f"_pow({a[0]}, {a[1]})"
    if op == "neg":
        return f"(-{a[0]})"
    if op == "max":
        return f"({a[0]} if {a[0]} >= {a[1]} else {a[1]})"
    if op == "min":
        return f"({a[0]} if {a[0]} <= {a[1]} else {a[1]})"
    if op == "gt":
        return f"(1.0 if {a[0]} > {a[1]} else 0.0)"
    if op == "where":
        return f"({a[1]} if {a[0]} != 0.0 else {a[2]})"
    if op == "pw":
        return f"_pw({e.value!r}, {a[0]})"
    if op in ("sqrt", "exp", "log", "abs", "tanh", "sin", "cos", "sign"):
        return f"_{op}({a[0]})"
    raise ValueError(op)


def _compile_vector(
    exprs: list[Expr], order: dict[str, int]
) -> Callable[[list[float]], list[float]]:
    if not exprs:
        return lambda v: []
    body = ", ".join(_codegen(e, order) for e in exprs)
    src = f"def _f(v):\n    return [{body}]\n"
    ns = dict(_NS)
    exec(src, ns)  # noqa: S102 - generated from our own IR, not user text
    return ns["_f"]


class NumpyBackend(Backend):
    name = "numpy"

    def __init__(self, ir: PHSIR) -> None:
        super().__init__(ir)
        order = ir.symbol_order()
        self._params = np.array(ir.param_values(), dtype=float)
        self._rhs = _compile_vector(ir.rhs, order)
        self._jac = (
            _compile_vector([e for row in ir.jacobian for e in row], order)
            if ir.jacobian
            else None
        )
        self._energy = _compile_vector([ir.energy], order)
        self._grad = _compile_vector(ir.grad_H, order)
        self._out = _compile_vector(
            [ir.outputs[k].expr for k in self.output_names], order
        )
        self._ports = _compile_vector(ir.port_outputs, order)
        self._port_vals = _compile_vector(ir.port_values, order)

    # table
    def _table(self, x: Array, u: Array | None, t: float) -> list[float]:
        n, m = self.n_states, self.n_inputs
        v = [0.0] * (n + m + self.n_params + 1)
        xs = np.asarray(x, dtype=float).ravel()
        if xs.shape[0] != n:
            raise ValueError(f"state has {xs.shape[0]} entries, the model has {n} states")
        v[:n] = xs.tolist()
        if m:
            if u is None:
                pass
            else:
                us = np.asarray(u, dtype=float).ravel()
                if us.shape[0] != m:
                    raise ValueError(
                        f"input has {us.shape[0]} entries, the model has {m} inputs"
                    )
                v[n : n + m] = us.tolist()
        v[n + m : n + m + self.n_params] = self._params.tolist()
        v[-1] = float(t)
        return v

    def get_params(self) -> Array:
        return self._params.copy()

    def set_params(self, values: Array) -> None:
        vals = np.asarray(values, dtype=float).ravel()
        if vals.shape[0] != self.n_params:
            raise ValueError(
                f"expected {self.n_params} parameter values, got {vals.shape[0]}"
            )
        self._params = vals.copy()

    def rhs(self, x: Array, u: Array, t: float) -> Array:
        return np.array(self._rhs(self._table(x, u, t)), dtype=float)

    def jacobian(self, x: Array, u: Array, t: float) -> Array:
        n = self.n_states
        if self._jac is not None:
            J = np.array(self._jac(self._table(x, u, t)), dtype=float).reshape(n, n)
            if np.all(np.isfinite(J)):
                return J
        f0 = self.rhs(x, u, t)
        J = np.zeros((n, n))
        xp = np.array(x, dtype=float)
        for j in range(n):
            h = 1e-7 * (1 + abs(xp[j]))
            xp[j] += h
            J[:, j] = (self.rhs(xp, u, t) - f0) / h
            xp[j] -= h
        return J

    def energy(self, x: Array) -> float:
        return float(self._energy(self._table(x, None, 0.0))[0])

    def grad_h(self, x: Array) -> Array:
        return np.array(self._grad(self._table(x, None, 0.0)), dtype=float)

    def outputs(self, x: Array, u: Array, t: float) -> Array:
        return np.array(self._out(self._table(x, u, t)), dtype=float)

    def port_outputs(self, x: Array, u: Array, t: float) -> Array:
        return np.array(self._ports(self._table(x, u, t)), dtype=float)

    def supplied_power(self, x: Array, u: Array, t: float) -> float:
        v = self._table(x, u, t)
        y = self._ports(v)
        uu = self._port_vals(v)
        return float(sum(a * b for a, b in zip(y, uu, strict=True)))

    # integration
    def step(
        self, x: Array, u: Array, t: float, dt: float, method: str, **opts: Any
    ) -> Array:
        _engine_opts(opts)
        f = self.rhs
        x = np.asarray(x, dtype=float)
        u = np.asarray(u, dtype=float)
        return _step(f, self.jacobian, x, lambda th: u, t, dt, method, opts)

    def simulate(
        self, x0: Array, t: Array, u: Array | None, method: str, interp: str, **opts: Any
    ) -> dict[str, Any]:
        _engine_opts(opts, sim=True)
        return _simulate_generic(
            self.rhs,
            self.jacobian,
            self.energy,
            self.supplied_power,
            self.outputs,
            self.n_inputs,
            len(self.output_names),
            x0,
            t,
            u,
            method,
            interp,
            opts,
            backend=self.name,
        )

    def simulate_batch(
        self,
        x0s: Array,
        t: Array,
        u: Array | None,
        params: Array | None,
        method: str,
        interp: str,
        **opts: Any,
    ) -> dict[str, Any]:
        x0s = np.asarray(x0s, dtype=float)
        saved = self._params.copy()
        xs, es = [], []
        try:
            for i in range(x0s.shape[0]):
                if params is not None:
                    self.set_params(np.asarray(params)[i])
                r = self.simulate(
                    x0s[i], t, u, method, interp, record_outputs=False, **opts
                )
                xs.append(r["x"])
                es.append(r["energy"])
        finally:
            self._params = saved
        return {
            "t": np.asarray(t, dtype=float),
            "x": np.stack(xs),
            "energy": np.stack(es),
            "backend": self.name,
        }


# ----------------------------------------------------------------------------
# Generic integrators over Python callables (NumPy backend and CustomDynamics)
# ----------------------------------------------------------------------------
_DP_C = np.array([0.0, 1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0])
_DP_A = np.array(
    [
        [0, 0, 0, 0, 0, 0],
        [1 / 5, 0, 0, 0, 0, 0],
        [3 / 40, 9 / 40, 0, 0, 0, 0],
        [44 / 45, -56 / 15, 32 / 9, 0, 0, 0],
        [19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729, 0, 0],
        [9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656, 0],
        [35 / 384, 0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84],
    ]
)
_DP_B = np.array([35 / 384, 0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84, 0])
_DP_E = _DP_B - np.array(
    [5179 / 57600, 0, 7571 / 16695, 393 / 640, -92097 / 339200, 187 / 2100, 1 / 40]
)


def _step(
    f: Callable[[Array, Array, float], Array],
    jac: Callable[[Array, Array, float], Array],
    x: Array,
    u_of: Callable[[float], Array],
    t: float,
    h: float,
    method: str,
    opts: dict[str, Any],
    stats: dict[str, int] | None = None,
    h_guess: list[float] | None = None,
) -> Array:
    st = stats if stats is not None else {}
    if method == "euler":
        st["rhs_evals"] = st.get("rhs_evals", 0) + 1
        return x + h * f(x, u_of(0.0), t)
    if method == "rk4":
        k1 = f(x, u_of(0.0), t)
        um = u_of(0.5)
        k2 = f(x + 0.5 * h * k1, um, t + 0.5 * h)
        k3 = f(x + 0.5 * h * k2, um, t + 0.5 * h)
        k4 = f(x + h * k3, u_of(1.0), t + h)
        st["rhs_evals"] = st.get("rhs_evals", 0) + 4
        return x + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    if method == "rk45":
        return _rk45(
            f, x, u_of, t, t + h, opts, st, h_guess if h_guess is not None else [0.0]
        )
    if method == "midpoint":
        return _midpoint_halving(f, jac, x, u_of(0.5), t, h, opts, st, 0)
    raise ValueError(f"unknown solver {method!r}; choose one of {SOLVERS}")


def _rk45(
    f: Callable[[Array, Array, float], Array],
    x: Array,
    u_of: Callable[[float], Array],
    t0: float,
    t1: float,
    opts: dict[str, Any],
    st: dict[str, int],
    h_guess: list[float],
) -> Array:
    rtol = float(opts.get("rtol", 1e-8))
    atol = float(opts.get("atol", 1e-10))
    span = t1 - t0
    t = t0
    h = min(h_guess[0], span) if h_guess[0] > 0 else span
    x = np.array(x, dtype=float)
    n_sub = 0
    while t < t1 - 1e-14 * max(abs(span), 1.0):
        h = min(h, t1 - t)
        k = np.zeros((7, x.shape[0]))
        for s in range(7):
            xs = x + h * (_DP_A[s, :s] @ k[:s]) if s else x
            th = min(max((t + _DP_C[s] * h - t0) / span, 0.0), 1.0)
            k[s] = f(xs, u_of(th), t + _DP_C[s] * h)
        st["rhs_evals"] = st.get("rhs_evals", 0) + 7
        xn = x + h * (_DP_B @ k)
        err_vec = h * (_DP_E @ k)
        sc = atol + rtol * np.maximum(np.abs(x), np.abs(xn))
        err = float(np.max(np.abs(err_vec / sc)))
        if not np.isfinite(err):
            raise RuntimeError(f"the error estimate became non-finite at t = {t}")
        if err <= 1.0:
            t += h
            x = xn
            st["steps"] = st.get("steps", 0) + 1
            h *= 5.0 if err == 0 else min(5.0, max(0.2, 0.9 * err**-0.2))
        else:
            st["rejected_steps"] = st.get("rejected_steps", 0) + 1
            h *= min(0.9, max(0.1, 0.9 * err**-0.25))
        n_sub += 1
        if n_sub > 1_000_000 or h < 1e-14 * max(abs(span), 1.0):
            raise RuntimeError(f"the adaptive step collapsed at t = {t}")
    h_guess[0] = h
    return x


def _midpoint_halving(
    f: Callable[[Array, Array, float], Array],
    jac: Callable[[Array, Array, float], Array],
    x: Array,
    um: Array,
    t: float,
    h: float,
    opts: dict[str, Any],
    st: dict[str, int],
    depth: int,
) -> Array:
    try:
        return _midpoint(f, jac, x, um, t, h, opts, st)
    except RuntimeError:
        if depth >= 6:
            raise
        st["rejected_steps"] = st.get("rejected_steps", 0) + 1
        half = 0.5 * h
        x1 = _midpoint_halving(f, jac, x, um, t, half, opts, st, depth + 1)
        return _midpoint_halving(f, jac, x1, um, t + half, half, opts, st, depth + 1)


def _midpoint(
    f: Callable[[Array, Array, float], Array],
    jac: Callable[[Array, Array, float], Array],
    x: Array,
    um: Array,
    t: float,
    h: float,
    opts: dict[str, Any],
    st: dict[str, int],
) -> Array:
    tol = float(opts.get("newton_tol", 1e-10))
    max_it = int(opts.get("max_newton", 50))
    tm = t + 0.5 * h
    n = x.shape[0]
    x1 = x + h * f(x, um, tm)
    st["rhs_evals"] = st.get("rhs_evals", 0) + 1
    lu = None
    for it in range(max_it + 1):
        xm = 0.5 * (x + x1)
        res = x1 - x - h * f(xm, um, tm)
        st["rhs_evals"] += 1
        rn = float(np.max(np.abs(res)))
        if not np.isfinite(rn):
            raise RuntimeError(f"the Newton residual became non-finite at t = {t}")
        if rn <= tol * (1 + float(np.max(np.abs(x1)))):
            return x1
        if it == max_it:
            raise RuntimeError(
                f"the implicit step at t = {t} did not converge: residual {rn:.3e} after "
                f"{it} iterations; reduce the step or use rk45"
            )
        if lu is None or it % 4 == 3:
            J = jac(xm, um, tm)
            st["jacobian_evals"] = st.get("jacobian_evals", 0) + 1
            lu = np.eye(n) - 0.5 * h * J
        try:
            dx = np.linalg.solve(lu, res)
        except np.linalg.LinAlgError:
            raise RuntimeError(
                f"the Newton iteration matrix is singular at t = {t}"
            ) from None
        x1 = x1 - dx
        st["newton_iterations"] = st.get("newton_iterations", 0) + 1
    return x1  # pragma: no cover


def _simulate_generic(
    f: Callable[[Array, Array, float], Array],
    jac: Callable[[Array, Array, float], Array],
    energy: Callable[[Array], float] | None,
    supplied: Callable[[Array, Array, float], float] | None,
    outputs: Callable[[Array, Array, float], Array] | None,
    n_inputs: int,
    n_outputs: int,
    x0: Array,
    t: Array,
    u: Array | None,
    method: str,
    interp: str,
    opts: dict[str, Any],
    backend: str,
) -> dict[str, Any]:
    if method not in SOLVERS:
        raise ValueError(f"unknown solver {method!r}; choose one of {SOLVERS}")
    if interp not in ("hold", "linear"):
        raise ValueError(f"unknown input interpolation {interp!r}; choose hold or linear")
    t = np.asarray(t, dtype=float).ravel()
    if t.shape[0] < 2:
        raise ValueError("the time grid needs at least two points")
    if np.any(np.diff(t) <= 0):
        raise ValueError("the time grid must be strictly increasing")
    x = np.asarray(x0, dtype=float).ravel().copy()
    if not np.all(np.isfinite(x)):
        raise RuntimeError("the initial state is not finite")
    nt, n = t.shape[0], x.shape[0]
    if u is not None:
        u = np.asarray(u, dtype=float)
        if u.ndim == 1:
            u = u.reshape(-1, 1)
        if u.shape != (nt, n_inputs):
            raise ValueError(
                f"inputs must have shape (len(t), n_inputs) = {(nt, n_inputs)}, got {u.shape}"
            )
    else:
        u = np.zeros((nt, n_inputs))
    record_outputs = bool(opts.get("record_outputs", True)) and outputs is not None
    record_energy = bool(opts.get("record_energy", True)) and energy is not None
    X = np.zeros((nt, n))
    E = np.zeros(nt if record_energy else 0)
    P = np.zeros(nt if record_energy else 0)
    Y = np.zeros((nt, n_outputs if record_outputs else 0))
    stats: dict[str, int] = {
        "steps": 0,
        "rhs_evals": 0,
        "newton_iterations": 0,
        "jacobian_evals": 0,
        "rejected_steps": 0,
    }
    h_guess = [0.0]

    def record(k: int) -> None:
        X[k] = x
        if record_energy:
            E[k] = energy(x)  # type: ignore[misc]
            P[k] = supplied(x, u[k], t[k]) if supplied is not None else 0.0
        if record_outputs:
            Y[k] = outputs(x, u[k], t[k])  # type: ignore[misc]

    record(0)
    for k in range(nt - 1):
        h = t[k + 1] - t[k]
        if interp == "hold":
            uk = u[k]

            def u_of(th: float, uk: Array = uk) -> Array:
                return uk
        else:
            u0, u1 = u[k], u[k + 1]

            def u_of(th: float, u0: Array = u0, u1: Array = u1) -> Array:
                return u0 + th * (u1 - u0)

        x = _step(f, jac, x, u_of, t[k], h, method, opts, stats, h_guess)
        if method != "rk45":
            stats["steps"] += 1
        if not np.all(np.isfinite(x)):
            raise RuntimeError(f"the state became non-finite at t = {t[k + 1]}")
        record(k + 1)
    stats["method"] = method  # type: ignore[assignment]
    return {
        "t": t,
        "x": X,
        "u": u,
        "energy": E,
        "supplied_power": P,
        "outputs": Y,
        "stats": stats,
        "backend": backend,
    }


# ----------------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------------
def engine_available() -> bool:
    try:
        import otwin_engine  # noqa: F401
    except ImportError:
        return False
    return True


def select_backend(ir: PHSIR, backend: str = "auto") -> Backend:
    global _warned
    if backend == "rust":
        return RustBackend(ir)
    if backend == "numpy":
        return NumpyBackend(ir)
    if backend != "auto":
        raise ValueError(f"unknown backend {backend!r}; choose auto, rust or numpy")
    if engine_available():
        return RustBackend(ir)
    if not _warned:
        _warned = True
        warnings.warn(
            "the otwin engine is not installed; running on the NumPy reference backend, "
            "which is slower. Install it with: pip install otwin[engine]",
            EngineNotAvailable,
            stacklevel=3,
        )
    return NumpyBackend(ir)
