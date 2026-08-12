"""Exact Kalman filter for discrete linear-Gaussian systems.

This exists to be *right*, not to be fast or general. On a linear system the
Kalman filter is the closed-form minimum-variance estimator, so it is the
reference against which :class:`~otwin.estimate.kalman.ExtendedKalmanFilter` is
verified: linearise nothing, and the EKF must reproduce this filter to machine
precision. If it does not, the discretisation and the covariance recursion have
drifted apart, and every nonlinear result from the EKF is suspect for reasons
that will never show up in a nonlinear test.
"""

import numpy as np
import numpy.typing as npt

from .kalman import FilterResult, _symmetrise

__all__ = ["KalmanFilter"]

Array = npt.NDArray[np.floating]


class KalmanFilter:
    """Kalman filter for ``x_{k+1} = A x_k + B u_k + w``, ``y_k = C x_k + v``.

    Note that ``A``, ``B`` and ``C`` here are **discrete-time** matrices. If you
    have a continuous model, discretise it first with whatever scheme your EKF
    uses — mixing an exact matrix-exponential discretisation here with an RK4
    one there is the usual reason a "should be identical" comparison lands at
    1e-4 instead of 1e-14.

    The measurement noise is ``R_meas``, not ``R``, for the reason given in
    :class:`~otwin.estimate.kalman.ExtendedKalmanFilter`: ``R`` is the
    port-Hamiltonian dissipation matrix throughout this library.

    Args:
        A: State transition, shape ``(n, n)``.
        B: Input matrix, shape ``(n, m_in)``. Pass ``None`` for autonomous.
        C: Observation matrix, shape ``(m, n)``.
        Q: Process-noise covariance per step, shape ``(n, n)``.
        R_meas: Measurement-noise covariance, shape ``(m, m)``.
        P0: Initial covariance, shape ``(n, n)``.
        x0: Initial state, shape ``(n,)``. Defaults to zeros.

    Attributes:
        x: Current state estimate.
        P: Current covariance.

    Example:
        >>> import numpy as np
        >>> kf = KalmanFilter(A=np.array([[1.0]]), B=None, C=np.array([[1.0]]),
        ...                   Q=np.array([[1e-4]]), R_meas=np.array([[1.0]]),
        ...                   P0=np.array([[1.0]]), x0=np.array([0.0]))
        >>> ys = np.full((50, 1), 2.0)
        >>> res = kf.filter(ys, None)
        >>> bool(abs(res.x[-1, 0] - 2.0) < 0.05)
        True
    """

    def __init__(
        self,
        A: Array,
        B: Array | None,
        C: Array,
        Q: Array,
        R_meas: Array,
        P0: Array,
        x0: Array | None = None,
    ) -> None:
        self.A = np.atleast_2d(np.asarray(A, dtype=float))
        self.C = np.atleast_2d(np.asarray(C, dtype=float))
        self.Q = np.atleast_2d(np.asarray(Q, dtype=float))
        self.R_meas = np.atleast_2d(np.asarray(R_meas, dtype=float))
        self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))

        self.n_states = int(self.A.shape[0])
        self.n_obs = int(self.C.shape[0])
        self.B = (
            np.zeros((self.n_states, 0))
            if B is None
            else np.atleast_2d(np.asarray(B, dtype=float))
        )
        self.n_inputs = int(self.B.shape[1])

        if self.A.shape != (self.n_states, self.n_states):
            raise ValueError(f"A must be square, got {self.A.shape}")
        if self.C.shape[1] != self.n_states:
            raise ValueError(f"C has {self.C.shape[1]} columns, expected {self.n_states}")
        if self.Q.shape != self.A.shape:
            raise ValueError(
                f"Q shape {self.Q.shape} does not match A shape {self.A.shape}"
            )
        if self.R_meas.shape != (self.n_obs, self.n_obs):
            raise ValueError(
                f"R_meas shape {self.R_meas.shape} does not match C rows {self.n_obs}"
            )

        self.x0 = (
            np.zeros(self.n_states)
            if x0 is None
            else np.asarray(x0, dtype=float).reshape(self.n_states)
        )
        self.reset()

    def reset(self, x0: Array | None = None, P0: Array | None = None) -> None:
        """Restore the filter to its initial state and covariance."""
        if x0 is not None:
            self.x0 = np.asarray(x0, dtype=float).reshape(self.n_states)
        if P0 is not None:
            self.P0 = np.atleast_2d(np.asarray(P0, dtype=float))
        self.x = self.x0.copy()
        self.P = _symmetrise(self.P0.copy())

    def predict(self, u: Array | None = None) -> Array:
        """Advance one step: ``x ← A x + B u``, ``P ← A P Aᵀ + Q``.

        Args:
            u: Input applied over the step, shape ``(n_inputs,)``.

        Returns:
            The predicted state, shape ``(n_states,)``.
        """
        self.x = self.A @ self.x
        if self.n_inputs:
            u = np.atleast_1d(np.asarray(u, dtype=float)).reshape(self.n_inputs)
            self.x = self.x + self.B @ u
        self.P = _symmetrise(self.A @ self.P @ self.A.T + self.Q)
        return self.x.copy()

    def update(self, y: Array) -> Array:
        """Correct with one measurement, Joseph-form covariance.

        Args:
            y: Measurement, shape ``(n_obs,)``.

        Returns:
            The corrected state, shape ``(n_states,)``.
        """
        y = np.atleast_1d(np.asarray(y, dtype=float)).reshape(self.n_obs)
        S = _symmetrise(self.C @ self.P @ self.C.T + self.R_meas)
        K = np.linalg.solve(S, self.C @ self.P).T
        innovation = y - self.C @ self.x
        self.x = self.x + K @ innovation
        A_cl = np.eye(self.n_states) - K @ self.C
        self.P = _symmetrise(A_cl @ self.P @ A_cl.T + K @ self.R_meas @ K.T)
        self._last_innovation = innovation
        self._last_nis = float(innovation @ np.linalg.solve(S, innovation))
        return self.x.copy()

    def step(self, y: Array, u: Array | None = None) -> Array:
        """Predict one step then correct with ``y``."""
        self.predict(u)
        return self.update(y)

    def filter(
        self, ys: Array, us: Array | None = None, reset: bool = True
    ) -> FilterResult:
        """Run over a full record, matching the EKF timing convention.

        ``x0``/``P0`` are the prior at sample 0, so sample 0 is an update with
        no preceding prediction; sample ``k > 0`` predicts with ``us[k-1]``,
        then updates with ``ys[k]``.

        Args:
            ys: Measurements, shape ``(n_steps, n_obs)``.
            us: Inputs, shape ``(n_steps, n_inputs)``, or ``None``.
            reset: Restart from ``x0``/``P0`` first.

        Returns:
            A :class:`~otwin.estimate.kalman.FilterResult`. The ``t`` field is
            the sample index, since a discrete filter has no physical clock.
        """
        ys = np.atleast_2d(np.asarray(ys, dtype=float))
        n_steps = ys.shape[0]
        us_arr = (
            np.zeros((n_steps, 0))
            if us is None
            else np.asarray(us, dtype=float).reshape(n_steps, -1)
        )
        if reset:
            self.reset()

        xs = np.zeros((n_steps, self.n_states))
        Ps = np.zeros((n_steps, self.n_states, self.n_states))
        nus = np.zeros((n_steps, self.n_obs))
        nis = np.zeros(n_steps)

        for k in range(n_steps):
            if k > 0:
                self.predict(us_arr[k - 1] if self.n_inputs else None)
            self.update(ys[k])
            xs[k] = self.x
            Ps[k] = self.P
            nus[k] = self._last_innovation
            nis[k] = self._last_nis

        return FilterResult(
            x=xs, P=Ps, innovation=nus, nis=nis, t=np.arange(n_steps, dtype=float)
        )
