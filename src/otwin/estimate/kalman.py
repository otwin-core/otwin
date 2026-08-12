"""Extended Kalman filtering for continuous-time twin models.

The models in :mod:`otwin.model` are continuous — they expose ``rhs(x, u, t)``,
not a one-step map. Measurements, on the other hand, arrive on a clock. This
module bridges the two: the state is propagated through each sampling interval
with classical RK4, and the transition Jacobian used by the covariance
recursion is the Jacobian *of that RK4 map*, not of the continuous vector
field. That choice matters. Using ``I + A·dt`` while integrating with RK4 makes
the covariance disagree with the state propagation at order ``dt²``, and the
resulting filter is no longer the exact Kalman filter on a linear system —
which is precisely the property the acceptance test in ``tests/test_estimate.py``
checks to 1e-10.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

__all__ = ["ExtendedKalmanFilter", "FilterResult", "rk4_jacobian", "rk4_step"]

Array = npt.NDArray[np.floating]
Dynamics = Callable[[Array, Array, float], Array]
Jacobian = Callable[[Array, Array, float], Array]


@dataclass
class FilterResult:
    """Output of a full filtering pass.

    Every estimator in :mod:`otwin.estimate` returns this, so downstream code
    (plots, reports, consistency checks) does not branch on which filter
    produced the trajectory.

    Args:
        x: Posterior state estimates, shape ``(n_steps, n_states)``.
        P: Posterior covariances, shape ``(n_steps, n_states, n_states)``.
        innovation: Measurement residuals ``y - h(x⁻)``, shape
            ``(n_steps, n_obs)``.
        nis: Normalised innovation squared, ``νᵀ S⁻¹ ν``, shape ``(n_steps,)``.
            Under a correctly specified filter this is chi-squared with
            ``n_obs`` degrees of freedom, so ``nis.mean() ≈ n_obs``. A mean far
            above ``n_obs`` means ``Q`` or ``R_meas`` is too small.
        t: Time stamps, shape ``(n_steps,)``.

    Example:
        >>> import numpy as np
        >>> r = FilterResult(x=np.zeros((3, 2)), P=np.zeros((3, 2, 2)),
        ...                  innovation=np.zeros((3, 1)), nis=np.zeros(3),
        ...                  t=np.arange(3))
        >>> r.x.shape, r.nis.dtype
        ((3, 2), dtype('float64'))
    """

    x: Array
    P: Array
    innovation: Array
    nis: Array
    t: Array = field(default_factory=lambda: np.empty(0, dtype=float))

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float)
        self.P = np.asarray(self.P, dtype=float)
        self.innovation = np.asarray(self.innovation, dtype=float)
        self.nis = np.asarray(self.nis, dtype=float)
        self.t = np.asarray(self.t, dtype=float)

    @property
    def n_steps(self) -> int:
        """Number of filtered samples."""
        return int(self.x.shape[0])


def _numerical_jacobian(
    func: Callable[[Array], Array], x: Array, eps: float = 1e-6
) -> Array:
    """Central-difference Jacobian of ``func`` at ``x``.

    Step sizes are scaled per component, ``h_i = eps·max(1, |x_i|)``, so that
    the filter behaves the same on a state measured in volts and one measured
    in microvolts. ``eps = 1e-6`` is near the optimum for central differences
    in double precision (``≈ ε_mach^{1/3}``), giving roughly 1e-10 relative
    accuracy.

    Args:
        func: Map from ``(n,)`` to ``(m,)``.
        x: Evaluation point, shape ``(n,)``.
        eps: Relative finite-difference step.

    Returns:
        Jacobian, shape ``(m, n)``.

    Example:
        >>> import numpy as np
        >>> f = lambda z: np.array([z[0] * z[1], z[1] ** 2])
        >>> J = _numerical_jacobian(f, np.array([2.0, 3.0]))
        >>> np.allclose(J, [[3.0, 2.0], [0.0, 6.0]], atol=1e-6)
        True
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    f0 = np.atleast_1d(np.asarray(func(x), dtype=float))
    jac = np.zeros((f0.size, n), dtype=float)
    for i in range(n):
        h = eps * max(1.0, abs(float(x[i])))
        xp = x.copy()
        xm = x.copy()
        xp[i] += h
        xm[i] -= h
        fp = np.atleast_1d(np.asarray(func(xp), dtype=float))
        fm = np.atleast_1d(np.asarray(func(xm), dtype=float))
        jac[:, i] = (fp - fm) / (2.0 * h)
    return jac


def rk4_step(f: Dynamics, x: Array, u: Array, t: float, dt: float) -> Array:
    """One classical Runge-Kutta 4 step of ``ẋ = f(x, u, t)``.

    The input ``u`` is held constant across the interval (zero-order hold),
    which is what a sampled-data twin actually sees.

    Args:
        f: Continuous dynamics ``f(x, u, t) -> dx/dt``.
        x: State at ``t``, shape ``(n,)``.
        u: Input held over ``[t, t + dt]``, shape ``(m,)``.
        t: Start time.
        dt: Step size. ``dt = 0`` returns ``x`` unchanged.

    Returns:
        State at ``t + dt``, shape ``(n,)``.

    Example:
        >>> import numpy as np
        >>> f = lambda x, u, t: -x
        >>> round(float(rk4_step(f, np.array([1.0]), np.empty(0), 0.0, 0.1)[0]), 7)
        0.9048375
    """
    k1 = np.asarray(f(x, u, t), dtype=float)
    k2 = np.asarray(f(x + 0.5 * dt * k1, u, t + 0.5 * dt), dtype=float)
    k3 = np.asarray(f(x + 0.5 * dt * k2, u, t + 0.5 * dt), dtype=float)
    k4 = np.asarray(f(x + dt * k3, u, t + dt), dtype=float)
    return np.asarray(x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4), dtype=float)


def rk4_jacobian(
    f: Dynamics,
    jac_f: Jacobian | None,
    x: Array,
    u: Array,
    t: float,
    dt: float,
) -> Array:
    """Jacobian ``∂x(t+dt)/∂x(t)`` of the RK4 map in :func:`rk4_step`.

    With an analytic continuous Jacobian this is exact: the chain rule is
    applied through the four RK4 stages. Without one, the whole RK4 map is
    differentiated numerically, which costs ``2n`` extra dynamics evaluations
    per stage but needs nothing from the model beyond ``rhs``.

    On a linear system ``ẋ = A x + B u`` the result is the truncated matrix
    exponential ``Σ_{k=0}^{4} (A dt)^k / k!`` — exactly the transition matrix
    that RK4 realises, which is why the EKF built on it reproduces the
    closed-form Kalman filter.

    Args:
        f: Continuous dynamics.
        jac_f: Optional analytic ``∂f/∂x``, shape ``(n, n)``.
        x: State, shape ``(n,)``.
        u: Input held over the step.
        t: Start time.
        dt: Step size.

    Returns:
        Transition Jacobian, shape ``(n, n)``.

    Example:
        >>> import math
        >>> import numpy as np
        >>> A = np.array([[0.0, 1.0], [-4.0, -0.3]])
        >>> f = lambda x, u, t: A @ x
        >>> F = rk4_jacobian(f, lambda x, u, t: A, np.zeros(2), np.empty(0), 0.0, 0.05)
        >>> M = A * 0.05
        >>> ref = sum(np.linalg.matrix_power(M, k) / math.factorial(k) for k in range(5))
        >>> bool(np.allclose(F, ref))
        True
    """
    n = np.asarray(x, dtype=float).size
    if jac_f is None:
        return _numerical_jacobian(lambda z: rk4_step(f, z, u, t, dt), x)

    eye = np.eye(n)
    k1 = np.asarray(f(x, u, t), dtype=float)
    x2 = x + 0.5 * dt * k1
    k2 = np.asarray(f(x2, u, t + 0.5 * dt), dtype=float)
    x3 = x + 0.5 * dt * k2
    k3 = np.asarray(f(x3, u, t + 0.5 * dt), dtype=float)
    x4 = x + dt * k3

    a1 = np.asarray(jac_f(x, u, t), dtype=float)
    a2 = np.asarray(jac_f(x2, u, t + 0.5 * dt), dtype=float)
    a3 = np.asarray(jac_f(x3, u, t + 0.5 * dt), dtype=float)
    a4 = np.asarray(jac_f(x4, u, t + dt), dtype=float)

    dk1 = a1
    dk2 = a2 @ (eye + 0.5 * dt * dk1)
    dk3 = a3 @ (eye + 0.5 * dt * dk2)
    dk4 = a4 @ (eye + dt * dk3)
    return eye + (dt / 6.0) * (dk1 + 2.0 * dk2 + 2.0 * dk3 + dk4)


def _symmetrise(P: Array) -> Array:
    """Return ``(P + Pᵀ)/2``. Cheap insurance against round-off drift."""
    return 0.5 * (P + P.T)


class ExtendedKalmanFilter:
    """Extended Kalman filter for a continuous-time, discretely observed twin.

    The model is duck-typed: anything with ``rhs(x, u, t)`` and
    ``observe(x, u, t)`` works, including
    :class:`~otwin.model.phs.PortHamiltonianSystem`, a neural surrogate, or a
    three-line test double. Do **not** inherit from
    :class:`~otwin.interfaces.protocols.TwinModel` — see that module's
    docstring for why.

    Why the argument is called ``R_meas``:
        In this codebase ``R`` is the *dissipation matrix* of a port-Hamiltonian
        system, ``ẋ = (J − R)∇H + g u``. In the Kalman literature ``R`` is the
        measurement-noise covariance. Both appear in this file's call sites, and
        a filter that silently used the dissipation matrix as measurement noise
        would produce plausible-looking, wrong estimates. The name is therefore
        ``R_meas`` everywhere in :mod:`otwin.estimate`, without exception.

    Noise conventions:
        ``Q`` is the **discrete-time** process-noise covariance added once per
        :meth:`predict` call, and ``R_meas`` the measurement-noise covariance of
        a single sample. If what you have is a continuous spectral density
        ``Q_c``, pass ``Q_c · dt`` for a fixed sample rate. The filter does not
        rescale ``Q`` by ``dt`` on your behalf, because doing so silently would
        make the two conventions indistinguishable at the call site.

    Args:
        model: Object exposing ``rhs(x, u, t)`` and ``observe(x, u, t)``.
        Q: Process-noise covariance per step, shape ``(n, n)``.
        R_meas: Measurement-noise covariance, shape ``(m, m)``.
        P0: Initial state covariance, shape ``(n, n)``.
        x0: Initial state estimate, shape ``(n,)``. Defaults to zeros.
        jac_f: Optional analytic ``∂rhs/∂x``, signature ``(x, u, t) -> (n, n)``.
            Falls back to central differences.
        jac_h: Optional analytic ``∂observe/∂x``, signature
            ``(x, u, t) -> (m, n)``. Falls back to central differences.

    Attributes:
        x: Current state estimate, shape ``(n,)``.
        P: Current state covariance, shape ``(n, n)``.

    Example:
        >>> import numpy as np
        >>> class Decay:
        ...     def rhs(self, x, u, t):
        ...         return -0.5 * x
        ...     def observe(self, x, u, t):
        ...         return x.copy()
        >>> ekf = ExtendedKalmanFilter(Decay(), Q=np.array([[1e-6]]),
        ...                            R_meas=np.array([[1e-2]]),
        ...                            P0=np.array([[1.0]]), x0=np.array([0.0]))
        >>> ts = np.linspace(0.0, 2.0, 21)
        >>> ys = np.exp(-0.5 * ts).reshape(-1, 1)
        >>> us = np.zeros((21, 0))
        >>> res = ekf.filter(ys, us, ts)
        >>> bool(abs(res.x[-1, 0] - np.exp(-1.0)) < 1e-2)
        True
    """

    def __init__(
        self,
        model: object,
        Q: Array,
        R_meas: Array,
        P0: Array,
        x0: Array | None = None,
        jac_f: Jacobian | None = None,
        jac_h: Jacobian | None = None,
    ) -> None:
        if not (hasattr(model, "rhs") and hasattr(model, "observe")):
            raise TypeError(
                "model must expose rhs(x, u, t) and observe(x, u, t); got "
                f"{type(model).__name__}"
            )
        self.model = model
        self.Q = np.atleast_2d(np.asarray(Q, dtype=float))
        self.R_meas = np.atleast_2d(np.asarray(R_meas, dtype=float))
        self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))

        if self.Q.shape[0] != self.Q.shape[1]:
            raise ValueError(f"Q must be square, got {self.Q.shape}")
        if self.R_meas.shape[0] != self.R_meas.shape[1]:
            raise ValueError(f"R_meas must be square, got {self.R_meas.shape}")
        if self.P0.shape != self.Q.shape:
            raise ValueError(
                f"P0 shape {self.P0.shape} does not match Q shape {self.Q.shape}"
            )

        self.n_states = int(self.Q.shape[0])
        self.n_obs = int(self.R_meas.shape[0])
        self.x0 = (
            np.zeros(self.n_states)
            if x0 is None
            else np.asarray(x0, dtype=float).reshape(self.n_states)
        )
        self.jac_f = jac_f
        self.jac_h = jac_h
        self.reset()

    # Exposed as a static method so subclasses and sibling estimators can reuse
    # the exact same differencing scheme rather than inventing a second one.
    _numerical_jacobian = staticmethod(_numerical_jacobian)

    def reset(self, x0: Array | None = None, P0: Array | None = None) -> None:
        """Restore the filter to its initial state and covariance.

        Args:
            x0: Optional replacement initial state.
            P0: Optional replacement initial covariance.
        """
        if x0 is not None:
            self.x0 = np.asarray(x0, dtype=float).reshape(self.n_states)
        if P0 is not None:
            self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))
        self.x = self.x0.copy()
        self.P = _symmetrise(self.P0.copy())

    def _f(self, x: Array, u: Array, t: float) -> Array:
        return np.asarray(self.model.rhs(x, u, t), dtype=float)

    def _h(self, x: Array, u: Array, t: float) -> Array:
        return np.atleast_1d(np.asarray(self.model.observe(x, u, t), dtype=float))

    def _H(self, x: Array, u: Array, t: float) -> Array:
        """Measurement Jacobian at ``x``, analytic if available."""
        if self.jac_h is not None:
            return np.atleast_2d(np.asarray(self.jac_h(x, u, t), dtype=float))
        return _numerical_jacobian(lambda z: self._h(z, u, t), x)

    def predict(self, u: Array, dt: float, t: float = 0.0) -> Array:
        """Propagate state and covariance across one sampling interval.

        Args:
            u: Input held over ``[t, t + dt]``, shape ``(n_inputs,)``.
            dt: Interval length. ``dt = 0`` still adds ``Q``; call it only when
                you mean "a step happened with no elapsed time".
            t: Time at the start of the interval.

        Returns:
            The predicted state ``x⁻``, shape ``(n_states,)``.
        """
        u = np.atleast_1d(np.asarray(u, dtype=float))
        F = rk4_jacobian(self._f, self.jac_f, self.x, u, t, dt)
        self.x = rk4_step(self._f, self.x, u, t, dt)
        self.P = _symmetrise(F @ self.P @ F.T + self.Q)
        return self.x.copy()

    def _gain(self, u: Array, t: float) -> tuple[Array, Array, Array]:
        """Return ``(H, S, K)`` at the current prior."""
        H = self._H(self.x, u, t)
        S = _symmetrise(H @ self.P @ H.T + self.R_meas)
        K = np.linalg.solve(S, H @ self.P).T
        return H, S, K

    def update(self, y: Array, u: Array, t: float = 0.0) -> Array:
        """Correct the state with one measurement.

        The covariance uses the Joseph form
        ``P⁺ = (I − KH) P⁻ (I − KH)ᵀ + K R_meas Kᵀ``, which stays symmetric
        positive semidefinite even when ``K`` is slightly off — unlike the
        shorter ``(I − KH)P⁻``, which loses positive definiteness after a few
        thousand steps in single-digit-condition-number problems.

        Args:
            y: Measurement, shape ``(n_obs,)``.
            u: Current input, shape ``(n_inputs,)``.
            t: Measurement time.

        Returns:
            The corrected state ``x⁺``, shape ``(n_states,)``.
        """
        y = np.atleast_1d(np.asarray(y, dtype=float))
        u = np.atleast_1d(np.asarray(u, dtype=float))
        H, S, K = self._gain(u, t)
        innovation = y - self._h(self.x, u, t)
        self.x = self.x + K @ innovation
        eye = np.eye(self.n_states)
        A = eye - K @ H
        self.P = _symmetrise(A @ self.P @ A.T + K @ self.R_meas @ K.T)
        self._last_innovation = innovation
        self._last_nis = float(innovation @ np.linalg.solve(S, innovation))
        return self.x.copy()

    def step(self, y: Array, u: Array, dt: float, t: float = 0.0) -> Array:
        """One predict/update cycle: predict across ``dt``, then correct.

        The measurement is taken to arrive at ``t + dt``, i.e. at the *end* of
        the interval the prediction covers.

        Args:
            y: Measurement at ``t + dt``.
            u: Input held over ``[t, t + dt]``.
            dt: Interval length.
            t: Time at the start of the interval.

        Returns:
            The corrected state, shape ``(n_states,)``.
        """
        self.predict(u, dt, t)
        return self.update(y, u, t + dt)

    def _empty_inputs(self, n_steps: int, us: Array | None) -> Array:
        if us is None:
            return np.zeros((n_steps, 0))
        us = np.asarray(us, dtype=float)
        if us.ndim == 1:
            us = us.reshape(n_steps, -1)
        return us

    def filter(
        self, ys: Array, us: Array | None, ts: Array, reset: bool = True
    ) -> FilterResult:
        """Run the filter over a full measurement record.

        Timing convention: ``x0``/``P0`` are the prior *at* ``ts[0]``, so the
        first sample is an update with no preceding prediction. Sample ``k > 0``
        predicts across ``ts[k] − ts[k-1]`` holding ``us[k-1]``, then updates
        with ``ys[k]``.

        Args:
            ys: Measurements, shape ``(n_steps, n_obs)``.
            us: Inputs, shape ``(n_steps, n_inputs)``, or ``None`` for an
                autonomous system.
            ts: Time stamps, shape ``(n_steps,)``, strictly increasing.
            reset: Restart from ``x0``/``P0`` first. Set ``False`` to continue
                a previous pass.

        Returns:
            A :class:`FilterResult`.
        """
        ys = np.atleast_2d(np.asarray(ys, dtype=float))
        ts = np.asarray(ts, dtype=float).ravel()
        n_steps = ys.shape[0]
        if ts.size != n_steps:
            raise ValueError(f"ts has {ts.size} entries but ys has {n_steps} rows")
        us = self._empty_inputs(n_steps, us)
        if reset:
            self.reset()

        xs = np.zeros((n_steps, self.n_states))
        Ps = np.zeros((n_steps, self.n_states, self.n_states))
        nus = np.zeros((n_steps, self.n_obs))
        nis = np.zeros(n_steps)

        for k in range(n_steps):
            if k > 0:
                self.predict(us[k - 1], float(ts[k] - ts[k - 1]), float(ts[k - 1]))
            self.update(ys[k], us[k], float(ts[k]))
            xs[k] = self.x
            Ps[k] = self.P
            nus[k] = self._last_innovation
            nis[k] = self._last_nis

        return FilterResult(x=xs, P=Ps, innovation=nus, nis=nis, t=ts)
