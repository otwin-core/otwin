"""Moving-horizon estimation with hard state constraints.

An extended Kalman filter has no idea that a state of charge lives in ``[0, 1]``
or that an absolute temperature cannot be negative. Fed a biased sensor it will
report an SoC of 1.03 with a tight covariance, and every downstream decision —
charge current limits, remaining-range, warranty logic — inherits the
impossible number. Clipping the EKF output afterwards does not fix it: the
covariance and the next prediction still come from the infeasible state.

Moving-horizon estimation solves the same estimation problem as a constrained
optimisation over the last ``N`` samples, so the bounds are part of the problem
rather than an afterthought. The price is a nonlinear program per sample
instead of a matrix inversion.
"""

from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

from .kalman import (
    FilterResult,
    _numerical_jacobian,
    _symmetrise,
    rk4_jacobian,
    rk4_step,
)

__all__ = ["MovingHorizonEstimator"]

Array = npt.NDArray[np.floating]
Jacobian = Callable[[Array, Array, float], Array]


class MovingHorizonEstimator:
    """Constrained state estimation over a sliding window of measurements.

    At sample ``k`` the estimator solves, over the window states
    ``x_{k-N} … x_k``,

    .. math::

        \\min \\; \\|x_{k-N} - \\bar{x}\\|^2_{P^{-1}}
        + \\sum_{i} \\|y_i - h(x_i)\\|^2_{R_{meas}^{-1}}
        + \\sum_{i} \\|x_{i+1} - f(x_i, u_i)\\|^2_{Q^{-1}}

    subject to ``lo ≤ x_i ≤ hi`` for every state in the window. The first term
    is the *arrival cost*: everything the data before the window said, condensed
    into a prior mean and covariance. The second penalises disagreement with the
    measurements, the third disagreement with the model. Drop the bounds and, on
    a linear system with an exact arrival cost, the solution is the Kalman
    estimate — MHE is not a different estimator, it is the same estimator with
    the feasible set written down.

    Arrival cost, honestly:
        The prior covariance is propagated by the same EKF recursion the
        unconstrained filter uses. That is standard practice and it is an
        approximation: it discards the information that the *earlier* states
        were themselves constrained, so the arrival cost is looser than the true
        constrained posterior. The consequence is conservative — slightly wider
        implied uncertainty — never a bounds violation, because the bounds are
        enforced on the decision variables directly.

    Args:
        model: Object exposing ``rhs(x, u, t)`` and ``observe(x, u, t)``.
        Q: Process-noise covariance per step, shape ``(n, n)``.
        R_meas: Measurement-noise covariance, shape ``(m, m)``. Named
            ``R_meas`` because ``R`` is the dissipation matrix in this library.
        P0: Initial arrival-cost covariance, shape ``(n, n)``.
        x0: Initial state estimate, shape ``(n,)``. Defaults to zeros.
        horizon: Number of *intervals* ``N`` in the window; the window holds
            ``N + 1`` states. Larger ``N`` costs more per sample and buys more
            robustness to a bad prior.
        bounds: Per-state ``(lo, hi)`` pairs, length ``n``. Use ``None`` or
            ``±np.inf`` on a component to leave it free. Omitting ``bounds``
            entirely gives an unconstrained MHE, which is a legitimate but
            expensive way to reproduce an EKF.
        jac_f: Optional analytic ``∂rhs/∂x``.
        jac_h: Optional analytic ``∂observe/∂x``.
        method: ``scipy.optimize.minimize`` method. ``"SLSQP"`` (default) and
            ``"trust-constr"`` both honour box bounds.
        max_iter: Solver iteration cap per window.
        tol: Solver convergence tolerance.

    Example:
        >>> import numpy as np
        >>> class Leak:
        ...     def rhs(self, x, u, t):
        ...         return -0.05 * x
        ...     def observe(self, x, u, t):
        ...         return x.copy()
        >>> mhe = MovingHorizonEstimator(
        ...     Leak(), Q=np.array([[1e-5]]), R_meas=np.array([[4e-2]]),
        ...     P0=np.array([[1e-2]]), x0=np.array([0.9]),
        ...     horizon=4, bounds=[(0.0, 1.0)])
        >>> ts = np.linspace(0.0, 1.0, 11)
        >>> ys = np.full((11, 1), 1.25)          # sensor insists on 125% SoC
        >>> res = mhe.filter(ys, None, ts)
        >>> bool(res.x.max() <= 1.0 + 1e-9)
        True
    """

    def __init__(
        self,
        model: object,
        Q: Array,
        R_meas: Array,
        P0: Array,
        x0: Array | None = None,
        horizon: int = 5,
        bounds: Sequence[tuple[float | None, float | None]] | None = None,
        jac_f: Jacobian | None = None,
        jac_h: Jacobian | None = None,
        method: str = "SLSQP",
        max_iter: int = 200,
        tol: float = 1e-10,
    ) -> None:
        if not (hasattr(model, "rhs") and hasattr(model, "observe")):
            raise TypeError(
                "model must expose rhs(x, u, t) and observe(x, u, t); got "
                f"{type(model).__name__}"
            )
        if horizon < 1:
            raise ValueError(f"horizon must be >= 1, got {horizon}")

        self.model = model
        self.Q = np.atleast_2d(np.asarray(Q, dtype=float))
        self.R_meas = np.atleast_2d(np.asarray(R_meas, dtype=float))
        self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))
        self.n_states = int(self.Q.shape[0])
        self.n_obs = int(self.R_meas.shape[0])
        self.x0 = (
            np.zeros(self.n_states)
            if x0 is None
            else np.asarray(x0, dtype=float).reshape(self.n_states)
        )
        self.horizon = int(horizon)
        self.jac_f = jac_f
        self.jac_h = jac_h
        self.method = method
        self.max_iter = int(max_iter)
        self.tol = float(tol)

        self.lo, self.hi = self._parse_bounds(bounds)
        self.Q_inv = np.linalg.pinv(self.Q)
        self.R_inv = np.linalg.pinv(self.R_meas)
        self.reset()

    def _parse_bounds(
        self, bounds: Sequence[tuple[float | None, float | None]] | None
    ) -> tuple[Array, Array]:
        if bounds is None:
            return (
                np.full(self.n_states, -np.inf),
                np.full(self.n_states, np.inf),
            )
        if len(bounds) != self.n_states:
            raise ValueError(
                f"bounds has {len(bounds)} entries, expected {self.n_states}"
            )
        lo = np.array(
            [-np.inf if b is None or b[0] is None else float(b[0]) for b in bounds]
        )
        hi = np.array(
            [np.inf if b is None or b[1] is None else float(b[1]) for b in bounds]
        )
        if np.any(lo > hi):
            raise ValueError("every bound must satisfy lo <= hi")
        return lo, hi

    def reset(self, x0: Array | None = None, P0: Array | None = None) -> None:
        """Clear the window, the warm start and the arrival cost."""
        if x0 is not None:
            self.x0 = np.asarray(x0, dtype=float).reshape(self.n_states)
        if P0 is not None:
            self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))
        self.x = np.clip(self.x0.copy(), self.lo, self.hi)
        self.P = _symmetrise(self.P0.copy())
        self._prior_x = self.x.copy()
        self._prior_P = self.P.copy()
        self._warm: Array | None = None
        self._warm_lo = 0

    # -- model wrappers -------------------------------------------------

    def _f(self, x: Array, u: Array, t: float) -> Array:
        return np.asarray(self.model.rhs(x, u, t), dtype=float)

    def _h(self, x: Array, u: Array, t: float) -> Array:
        return np.atleast_1d(np.asarray(self.model.observe(x, u, t), dtype=float))

    def _H(self, x: Array, u: Array, t: float) -> Array:
        if self.jac_h is not None:
            return np.atleast_2d(np.asarray(self.jac_h(x, u, t), dtype=float))
        return _numerical_jacobian(lambda z: self._h(z, u, t), x)

    # -- window objective ------------------------------------------------

    def _cost_and_grad(
        self,
        z: Array,
        ys: Array,
        us: Array,
        ts: Array,
        dts: Array,
        prior_x: Array,
        prior_inv: Array,
    ) -> tuple[float, Array]:
        """Objective and analytic gradient for one window.

        The gradient is exact given the Jacobians, which are analytic when the
        user supplied them and central-difference otherwise. Handing SLSQP a
        gradient rather than letting it difference the whole objective cuts the
        number of model evaluations by a factor of ``n·(N+1)``.
        """
        n = self.n_states
        w = len(ts)
        X = z.reshape(w, n)
        grad = np.zeros((w, n))

        e = X[0] - prior_x
        cost = float(e @ prior_inv @ e)
        grad[0] += 2.0 * prior_inv @ e

        for i in range(w):
            r = ys[i] - self._h(X[i], us[i], float(ts[i]))
            cost += float(r @ self.R_inv @ r)
            H = self._H(X[i], us[i], float(ts[i]))
            grad[i] -= 2.0 * H.T @ (self.R_inv @ r)

        for i in range(w - 1):
            x_next = rk4_step(self._f, X[i], us[i], float(ts[i]), float(dts[i]))
            wres = X[i + 1] - x_next
            cost += float(wres @ self.Q_inv @ wres)
            F = rk4_jacobian(
                self._f, self.jac_f, X[i], us[i], float(ts[i]), float(dts[i])
            )
            grad[i + 1] += 2.0 * self.Q_inv @ wres
            grad[i] -= 2.0 * F.T @ (self.Q_inv @ wres)

        return cost, grad.ravel()

    def _warm_start(
        self, lo_idx: int, w: int, us: Array, ts: Array, dts: Array, prior_x: Array
    ) -> Array:
        """Initial guess for one window, shape ``(w, n)``.

        States the previous window already solved for are reused by *absolute*
        sample index, which is what makes this correct both while the window is
        still growing (nothing shifts) and once it slides (everything shifts by
        one). Any samples the previous window did not cover — normally just the
        newest one — are extrapolated with the model. A cold start costs roughly
        three times the solver iterations.
        """
        if self._warm is None:
            return np.tile(prior_x, (w, 1))
        prev, prev_lo = self._warm, self._warm_lo
        guess = np.zeros((w, self.n_states))
        filled = 0
        for i in range(w):
            j = (lo_idx + i) - prev_lo
            if 0 <= j < prev.shape[0]:
                guess[i] = prev[j]
                filled = i + 1
            else:
                break
        if filled == 0:  # windows do not overlap; nothing to reuse
            return np.tile(prior_x, (w, 1))
        for i in range(filled, w):
            guess[i] = rk4_step(
                self._f, guess[i - 1], us[i - 1], float(ts[i - 1]), float(dts[i - 1])
            )
        return guess

    def _solve_window(
        self,
        lo_idx: int,
        ys: Array,
        us: Array,
        ts: Array,
        dts: Array,
        prior_x: Array,
        prior_P: Array,
    ) -> Array:
        """Solve one window, returning the ``(w, n)`` state trajectory."""
        n = self.n_states
        w = len(ts)
        prior_inv = np.linalg.pinv(_symmetrise(prior_P))

        guess = self._warm_start(lo_idx, w, us, ts, dts, prior_x)
        z0 = np.clip(guess, self.lo, self.hi).ravel()

        box = [
            (
                float(self.lo[j]) if np.isfinite(self.lo[j]) else None,
                float(self.hi[j]) if np.isfinite(self.hi[j]) else None,
            )
            for _ in range(w)
            for j in range(n)
        ]

        res = minimize(
            self._cost_and_grad,
            z0,
            args=(ys, us, ts, dts, prior_x, prior_inv),
            jac=True,
            method=self.method,
            bounds=box,
            options={"maxiter": self.max_iter, "ftol": self.tol}
            if self.method == "SLSQP"
            else {"maxiter": self.max_iter, "gtol": self.tol},
        )
        # SLSQP can return components a few ulp outside the box. Clipping is not
        # a substitute for constraining — the optimum was computed inside the
        # feasible set — it only removes solver round-off, so the public
        # guarantee "every returned estimate satisfies the bounds" is exact.
        return np.clip(res.x.reshape(w, n), self.lo, self.hi)

    # -- arrival cost ----------------------------------------------------

    def _advance_arrival(self, x: Array, y: Array, u: Array, t: float, dt: float) -> None:
        """Slide the arrival cost forward one sample (EKF recursion)."""
        F = rk4_jacobian(self._f, self.jac_f, x, u, t, dt)
        x_pred = rk4_step(self._f, x, u, t, dt)
        P_pred = _symmetrise(F @ self._prior_P @ F.T + self.Q)
        H = self._H(x_pred, u, t + dt)
        S = _symmetrise(H @ P_pred @ H.T + self.R_meas)
        K = np.linalg.solve(S, H @ P_pred).T
        A_cl = np.eye(self.n_states) - K @ H
        self._prior_P = _symmetrise(A_cl @ P_pred @ A_cl.T + K @ self.R_meas @ K.T)
        self._prior_x = np.clip(
            x_pred + K @ (y - self._h(x_pred, u, t + dt)), self.lo, self.hi
        )

    # -- public API ------------------------------------------------------

    def filter(
        self, ys: Array, us: Array | None, ts: Array, reset: bool = True
    ) -> FilterResult:
        """Run constrained estimation over a full measurement record.

        The window grows from one sample up to ``horizon + 1`` and then slides.
        The reported estimate at each sample is the *last* state of that
        sample's window (filtered, not smoothed), so the output is comparable
        sample-for-sample with :class:`~otwin.estimate.kalman.ExtendedKalmanFilter`.

        Args:
            ys: Measurements, shape ``(n_steps, n_obs)``.
            us: Inputs, shape ``(n_steps, n_inputs)``, or ``None``.
            ts: Time stamps, shape ``(n_steps,)``.
            reset: Restart from ``x0``/``P0`` first.

        Returns:
            A :class:`~otwin.estimate.kalman.FilterResult`. ``P`` carries the
            arrival-cost covariance, which is the EKF covariance and therefore
            does *not* reflect the truncation imposed by the bounds — read it as
            an upper bound on confidence, and read ``x`` as the constrained
            estimate.
        """
        ys = np.atleast_2d(np.asarray(ys, dtype=float))
        ts = np.asarray(ts, dtype=float).ravel()
        n_steps = ys.shape[0]
        if ts.size != n_steps:
            raise ValueError(f"ts has {ts.size} entries but ys has {n_steps} rows")
        us_arr = (
            np.zeros((n_steps, 0))
            if us is None
            else np.asarray(us, dtype=float).reshape(n_steps, -1)
        )
        if reset:
            self.reset()

        dts_all = np.diff(ts, prepend=ts[0])
        xs = np.zeros((n_steps, self.n_states))
        Ps = np.zeros((n_steps, self.n_states, self.n_states))
        nus = np.zeros((n_steps, self.n_obs))
        nis = np.zeros(n_steps)

        for k in range(n_steps):
            lo_idx = max(0, k - self.horizon)
            idx = np.arange(lo_idx, k + 1)
            w_ts = ts[idx]
            w_dts = np.diff(w_ts, append=w_ts[-1])  # last entry unused
            sol = self._solve_window(
                lo_idx, ys[idx], us_arr[idx], w_ts, w_dts, self._prior_x, self._prior_P
            )
            self._warm, self._warm_lo = sol, lo_idx
            self.x = sol[-1]

            innovation = ys[k] - self._h(self.x, us_arr[k], float(ts[k]))
            H = self._H(self.x, us_arr[k], float(ts[k]))
            S = _symmetrise(H @ self._prior_P @ H.T + self.R_meas)
            nus[k] = innovation
            nis[k] = float(innovation @ np.linalg.solve(S, innovation))

            if k >= self.horizon:
                # The window is about to drop its oldest sample; roll the
                # arrival cost onto the state that will become the new oldest.
                self._advance_arrival(
                    sol[0],
                    ys[lo_idx + 1],
                    us_arr[lo_idx],
                    float(ts[lo_idx]),
                    float(dts_all[lo_idx + 1]),
                )
            self.P = _symmetrise(self._prior_P.copy())
            xs[k] = self.x
            Ps[k] = self.P

        return FilterResult(x=xs, P=Ps, innovation=nus, nis=nis, t=ts)
