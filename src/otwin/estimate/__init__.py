"""State estimation — the ISO 13374 **State Detection (SD)** block.

ISO 13374 lays out six processing blocks for condition monitoring: Data
Acquisition, Data Manipulation, **State Detection**, Health Assessment,
Prognostic Assessment, and Advisory Generation. This package is the third. It
is the block that turns a *simulation* into a *twin*.

Without it, :mod:`otwin.model` gives you a physically correct trajectory that
drifts away from the real machine the moment the initial condition, a
parameter, or an unmodelled disturbance is slightly wrong — and nothing ever
pulls it back. State detection closes that loop: measurements come in, the
estimated state is corrected, and the twin tracks the asset instead of merely
resembling it. Everything downstream depends on it. Health assessment scores a
state; prognostics extrapolate one; advisory generation acts on one. If the
state is wrong, all three are confidently wrong.

What is here
------------

:class:`ExtendedKalmanFilter`
    The workhorse. Continuous model, discrete measurements, RK4 propagation
    with a matched transition Jacobian, Joseph-form covariance.

:class:`KalmanFilter`
    The exact linear filter. Its job is to be the closed-form answer that the
    EKF is verified against, and to be the right tool when the model really is
    linear.

:class:`MovingHorizonEstimator`
    When the state has hard physical limits — state of charge in ``[0, 1]``,
    non-negative absolute temperature, a valve between shut and open — and an
    estimate outside them would be acted on downstream.

:class:`EnergyConsistentObserver`
    For port-Hamiltonian twins. A Kalman correction knows nothing about the
    stored energy ``H(x)`` and will happily push it uphill with no input to
    have supplied it, destroying the passivity guarantee that the model was
    built to provide. This observer bounds every correction by the energy that
    actually flowed through the ports. See :mod:`otwin.estimate.energy`.

A note on ``R_meas``
--------------------

Throughout this package the measurement-noise covariance is called ``R_meas``,
never ``R``. In :mod:`otwin.model` ``R`` is the dissipation matrix of a
port-Hamiltonian system. Both objects appear in the same call sites here, they
are both square, both symmetric, and both positive semidefinite, so a mix-up
type-checks, runs, and produces wrong estimates that look right. The name is
ugly on purpose.

Example:
    >>> import numpy as np
    >>> from otwin.estimate import ExtendedKalmanFilter
    >>> class Decay:
    ...     def rhs(self, x, u, t):
    ...         return -0.5 * x
    ...     def observe(self, x, u, t):
    ...         return x.copy()
    >>> ekf = ExtendedKalmanFilter(Decay(), Q=np.array([[1e-6]]),
    ...                            R_meas=np.array([[1e-2]]),
    ...                            P0=np.array([[1.0]]), x0=np.array([0.0]))
    >>> ts = np.linspace(0.0, 2.0, 21)
    >>> res = ekf.filter(np.exp(-0.5 * ts).reshape(-1, 1), None, ts)
    >>> res.x.shape
    (21, 1)
"""

from .energy import EnergyConsistentObserver, EnergyFilterResult
from .identifiability import IdentifiabilityReport, ParameterVerdict, identifiability
from .kalman import ExtendedKalmanFilter, FilterResult
from .linear import KalmanFilter
from .mhe import MovingHorizonEstimator

__all__ = [
    "EnergyConsistentObserver",
    "EnergyFilterResult",
    "ExtendedKalmanFilter",
    "FilterResult",
    "IdentifiabilityReport",
    "ParameterVerdict",
    "identifiability",
    "KalmanFilter",
    "MovingHorizonEstimator",
]
