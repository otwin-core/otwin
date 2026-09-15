"""Grey-box models: known physics plus an unknown remainder.

Almost every useful twin sits here. The structure is fixed by physics and
compiled; what the physics leaves out is a *residual*::

    dx/dt = f_physics(x, u; theta) + f_residual(x, u; phi)

Three ways to write the residual, in increasing order of flexibility:

1. **A symbolic term with new parameters**, compiled into the model and run in
   the engine: :meth:`otwin.Model.with_residual`. The right choice when you
   can name the missing phenomenon (quadratic drag, a leak) but not its
   coefficient. The coefficient is a parameter like any other, so
   :func:`fit_parameters` can estimate it and the identifiability check can
   say whether the data determined it.

2. **A learned residual**: :class:`HybridModel` adds a Gaussian process
   (:class:`otwin.forecast.GPPHS`), a neural network, or any callable to the
   compiled physics. The physics stays in the engine; the residual is Python,
   so the time loop is Python too. Use it when you cannot name the phenomenon.

3. **Your own function**: :class:`HybridModel` with a plain callable.

In all three the physical model is never rewritten. That is the point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from .runtime.custom import CustomDynamics
from .runtime.model import Model

__all__ = ["HybridModel", "fit_parameters", "FitResult", "residual_data"]

Array = npt.NDArray[np.floating]


class HybridModel(CustomDynamics):
    """Compiled physics plus a residual evaluated in Python.

    Args:
        physics: a compiled :class:`~otwin.Model`.
        residual: one of
            a callable ``r(x, u, t) -> dx`` of shape ``(n_states,)``;
            an object with ``predict(X, U)`` such as a fitted
            :class:`~otwin.forecast.GPPHS` (``return_std`` is handled);
            an object with ``rhs(x, u, t)``, such as a
            :class:`~otwin.model.PortHamiltonianNN`.
        mask: optional boolean or index array selecting which states the
            residual may touch. Others get exactly the physics.

    The result satisfies :class:`~otwin.interfaces.TwinModel`, has the same
    state and input names as the physics, and reports the physics' stored
    energy. ``hybrid.physics`` and ``hybrid.residual`` stay accessible.
    """

    representation = "compiled + residual"

    def __init__(
        self,
        physics: Model,
        residual: Any,
        *,
        mask: Sequence[int] | Array | None = None,
        name: str | None = None,
    ) -> None:
        self.physics = physics
        self.residual = residual
        self._res_fn = _as_residual_fn(residual, physics.n_states, physics.n_inputs)
        n = physics.n_states
        if mask is None:
            self._mask = np.ones(n, dtype=bool)
        else:
            m = np.zeros(n, dtype=bool)
            arr = np.asarray(mask)
            if arr.dtype == bool:
                m[:] = arr
            else:
                m[arr] = True
            self._mask = m

        def f(x: Array, u: Array, t: float) -> Array:
            dx = physics.rhs(x, u, t)
            r = np.asarray(self._res_fn(x, u, t), dtype=float).ravel()
            if r.shape[0] != n:
                raise ValueError(
                    f"the residual returned {r.shape[0]} values for {n} states"
                )
            return dx + np.where(self._mask, r, 0.0)

        super().__init__(
            f,
            physics.n_states,
            physics.n_inputs,
            energy=physics.energy,
            observe=physics.observe,
            state_names=physics.state_names,
            input_names=physics.input_names,
            x0=physics.initial_state().values,
            name=name or f"{physics.name}+residual",
        )
        self.output_names = list(physics.output_names)
        self.param_names = list(physics.param_names)

    def physics_rhs(self, x: Array, u: Array | None = None, t: float = 0.0) -> Array:
        return self.physics.rhs(x, u, t)

    def residual_rhs(self, x: Array, u: Array | None = None, t: float = 0.0) -> Array:
        r = np.asarray(
            self._res_fn(x, np.zeros(self.n_inputs) if u is None else u, t), dtype=float
        )
        return np.where(self._mask, r, 0.0)

    def summary(self) -> str:
        return (
            self.physics.summary()
            + f"\nResidual: {type(self.residual).__name__} on states "
            f"{[n for n, m in zip(self.state_names, self._mask, strict=True) if m]}"
            + "\nBackend: numpy (physics in the engine, residual in Python)"
        )


def _as_residual_fn(
    residual: Any, n_states: int, n_inputs: int
) -> Callable[[Array, Array, float], Array]:
    if hasattr(residual, "predict"):

        def gp(x: Array, u: Array, t: float) -> Array:
            X = np.asarray(x, dtype=float).reshape(1, -1)
            U = np.asarray(u, dtype=float).reshape(1, -1) if n_inputs else None
            try:
                out = (
                    residual.predict(X, U, return_std=False)
                    if n_inputs
                    else residual.predict(X, return_std=False)
                )
            except TypeError:
                out = residual.predict(X, U) if n_inputs else residual.predict(X)
            if isinstance(out, tuple):
                out = out[0]
            return np.asarray(out, dtype=float).reshape(-1)[:n_states]

        return gp
    if hasattr(residual, "rhs") and not callable(residual):
        return lambda x, u, t: np.asarray(residual.rhs(x, u, t), dtype=float)
    if hasattr(residual, "rhs"):
        return lambda x, u, t: np.asarray(residual.rhs(x, u, t), dtype=float)
    if callable(residual):
        return residual
    raise TypeError(
        "residual must be a callable r(x, u, t), an object with predict(X[, U]) such as "
        "GPPHS, or an object with rhs(x, u, t)"
    )


def residual_data(
    physics: Model, X: Array, dXdt: Array, U: Array | None = None, t: Array | None = None
) -> Array:
    """What the physics leaves unexplained: ``dXdt - f_physics(X, U)`` row by row.

    This is the training target for a learned residual. ``X`` is
    ``(n_samples, n_states)``, ``dXdt`` the measured or finite-differenced
    derivatives, ``U`` the inputs if any.
    """
    X = np.asarray(X, dtype=float)
    dXdt = np.asarray(dXdt, dtype=float)
    out = np.empty_like(dXdt)
    for i in range(X.shape[0]):
        u = None if U is None else np.asarray(U)[i]
        tt = 0.0 if t is None else float(np.asarray(t)[i])
        out[i] = dXdt[i] - physics.rhs(X[i], u, tt)
    return out


# ----------------------------------------------------------------------------
# Parameter estimation on the compiled model
# ----------------------------------------------------------------------------
@dataclass
class FitResult:
    """What :func:`fit_parameters` returns."""

    values: dict[str, float]
    model: Model
    cost: float
    residuals: Array
    n_evaluations: int
    success: bool
    message: str
    sensitivities: Array = field(repr=False, default_factory=lambda: np.zeros((0, 0)))
    identifiability: Any = None

    def __repr__(self) -> str:
        vals = ", ".join(f"{k}={v:.6g}" for k, v in self.values.items())
        ident = ""
        if self.identifiability is not None:
            ident = f", identified={self.identifiability.verdicts}"
        return f"FitResult({vals}; cost={self.cost:.4g}, evaluations={self.n_evaluations}{ident})"


def fit_parameters(
    model: Model,
    t: Array,
    measurements: Mapping[str, Array],
    parameters: Sequence[str],
    *,
    inputs: Any = None,
    x0: Any = None,
    bounds: Mapping[str, tuple[float | None, float | None]] | None = None,
    weights: Mapping[str, float] | None = None,
    solver: str = "midpoint",
    check_identifiability: bool = True,
    max_evaluations: int = 500,
    **options: Any,
) -> FitResult:
    """Estimate parameters of a compiled model from measured outputs.

    The structure is the compiled model's; only the named parameters move.
    Every candidate is simulated in the engine and compared with the
    measurements; ``scipy.optimize.least_squares`` drives the search in the
    logarithm of each positive parameter so scales differ by orders of
    magnitude without trouble.

    Args:
        model: the compiled model. It is not modified; the returned
            ``FitResult.model`` carries the fitted values.
        t: the measurement times (also the simulation grid).
        measurements: ``{output_name: values over t}``. Any output of the
            model, including states.
        parameters: names of the parameters to estimate.
        inputs, x0, solver, options: as for :meth:`Model.simulate`.
        bounds: ``{name: (low, high)}``; ``None`` for a side means unbounded.
            Parameters that start positive default to ``(0, inf)``.
        weights: per output, multiplies its residuals.
        check_identifiability: run :func:`otwin.estimate.identifiability` on
            the sensitivity matrix at the optimum, so the result says whether
            the data determined each value.

    Returns:
        A :class:`FitResult`.
    """
    from scipy.optimize import least_squares

    t = np.asarray(t, dtype=float).ravel()
    names = list(parameters)
    for n in names:
        if n not in model.param_names:
            raise KeyError(
                f"{n!r} is not a parameter; parameters are {model.param_names}"
            )
    ys = {k: np.asarray(v, dtype=float).ravel() for k, v in measurements.items()}
    for k, v in ys.items():
        if k not in model.output_names:
            raise KeyError(f"{k!r} is not an output of the model")
        if v.shape[0] != t.shape[0]:
            raise ValueError(
                f"measurement {k!r} has {v.shape[0]} samples for {t.shape[0]} times"
            )
    w = {k: float((weights or {}).get(k, 1.0)) for k in ys}
    start = model.parameters
    theta0 = np.array([start[n] for n in names])
    positive = theta0 > 0
    lo = np.full(len(names), -np.inf)
    hi = np.full(len(names), np.inf)
    for i, n in enumerate(names):
        b = (bounds or {}).get(n)
        if b is not None:
            lo[i] = -np.inf if b[0] is None else b[0]
            hi[i] = np.inf if b[1] is None else b[1]
        elif positive[i]:
            lo[i] = 0.0
    work = model.with_parameters()

    def unpack(z: Array) -> Array:
        return np.where(positive, np.exp(z), z)

    def pack(theta: Array) -> Array:
        return np.where(positive, np.log(np.maximum(theta, 1e-300)), theta)

    n_eval = [0]

    def resid(z: Array) -> Array:
        theta = unpack(z)
        work.set_parameters(dict(zip(names, theta, strict=True)))
        n_eval[0] += 1
        try:
            tr = work.simulate(t=t, x0=x0, inputs=inputs, solver=solver, **options)
        except RuntimeError:
            return np.full(sum(v.shape[0] for v in ys.values()), 1e6)
        parts = [w[k] * (tr[k] - v) for k, v in ys.items()]
        return np.concatenate(parts)

    z_lo = np.where(positive, np.log(np.maximum(lo, 1e-300)), lo)
    z_hi = np.where(
        positive, np.where(np.isinf(hi), np.inf, np.log(np.maximum(hi, 1e-300))), hi
    )
    res = least_squares(
        resid, pack(theta0), bounds=(z_lo, z_hi), max_nfev=max_evaluations
    )
    theta = unpack(res.x)
    values = dict(zip(names, (float(v) for v in theta), strict=True))
    fitted = model.with_parameters(values)
    residuals = resid(res.x)
    sens = np.zeros((residuals.shape[0], len(names)))
    ident = None
    if check_identifiability:
        from .estimate.identifiability import identifiability

        for i in range(len(names)):
            h = 1e-5 * max(abs(theta[i]), 1e-8)
            zp = theta.copy()
            zp[i] += h
            sens[:, i] = (resid(pack(zp)) - residuals) / h
        y_lin = sens @ theta - residuals
        ident = identifiability(sens, y_lin, names=names, n_boot=100)
    return FitResult(
        values=values,
        model=fitted,
        cost=float(res.cost),
        residuals=residuals,
        n_evaluations=n_eval[0],
        success=bool(res.success),
        message=str(res.message),
        sensitivities=sens,
        identifiability=ident,
    )
