"""Conformal prediction intervals: construction, not only measurement.

The rest of :mod:`otwin.forecast` can tell you a band is wrong — ``picp``,
``mpiw``, ``interval_score``, ``coverage_curve``, ``expected_calibration_error``
all measure one. Until this module there was nothing here that *built* one, and
``Interval.method`` listed ``"conformal"`` as a legal value that nothing
produced. That gap is why the band in every worked example was hand-rolled.

Why conformal rather than the model's own uncertainty
-----------------------------------------------------
A conformal band needs one assumption — that the calibration errors and the test
errors are exchangeable — and in exchange it makes no assumption about the model
at all. It works the same on a Gaussian process, a fade law, a neural network or
a lookup table. The likelihood does not have to be right, which matters because
on a physical asset it usually is not.

The trap, stated once and loudly
--------------------------------
**The residuals you calibrate on must be forecast errors of the same kind you
are about to make.** The tempting shortcut — take the fitted model's own
in-sample residuals and quantile them — is not a smaller version of the right
thing, it is a different quantity. A model that interpolates its training data
has in-sample residuals an order of magnitude smaller than its h-step-ahead
errors, so the band comes out roughly ten times too narrow. Measured on a
lithium-ion capacity twin: 1.5 % delivered coverage at a 90 % target.

:func:`rolling_origin_residuals` exists to make the honest thing the easy thing.
It refits the whole pipeline at earlier origins *inside* the training window and
collects genuine h-step-ahead errors. It costs one refit per origin, and that
cost is the entire difference between a band that means something and one that
does not.

Three constructions
-------------------
:func:`split_conformal`
    One half-width for every horizon. Correct on average over the horizons in
    the calibration set, and too narrow early / too wide late whenever error
    grows with horizon — which for a degradation forecast it always does.

:func:`horizon_conformal`
    A half-width that grows with the horizon, fitted as a power law over the
    calibrated range and extrapolated beyond it. Honest about which part is
    which: :attr:`ConformalBand.extrapolated` marks the steps no calibration
    residual reached.

:class:`AdaptiveConformal`
    Online. The level is nudged after every observation, so a band that starts
    miscalibrated walks toward its target instead of being wrong for the whole
    horizon. Needs feedback, so it only applies where outcomes arrive.

References:
    Vovk, Gammerman & Shafer (2005), *Algorithmic Learning in a Random World*.
    Lei et al. (2018), *Distribution-Free Predictive Inference for Regression*, JASA.
    Gibbs & Candès (2021), *Adaptive Conformal Inference Under Distribution Shift*.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from otwin.interfaces.results import Interval

__all__ = [
    "AdaptiveConformal",
    "ConformalBand",
    "conformal_quantile",
    "horizon_conformal",
    "rolling_origin_residuals",
    "split_conformal",
]

Array = npt.NDArray[np.floating]

#: Round the rank product to this many decimals before taking the ceiling.
#: ``0.9 * 10`` is ``9.000000000000002`` in binary floating point, so a bare
#: ``ceil`` asks for rank 10 out of 10 calibration points and declares a set that
#: is exactly large enough to be too small. Twelve decimals is far below any
#: level anyone states and far above the round-off being removed.
_RANK_DECIMALS = 12


def _rank(level: float, n: int) -> int:
    """The conformal rank ``⌈level·(n+1)⌉``, without the floating-point burr."""
    return int(np.ceil(round(level * (n + 1), _RANK_DECIMALS)))


def _min_calibration_size(level: float) -> int:
    """Smallest ``n`` for which a conformal quantile at ``level`` exists.

    Solved by the definition rather than by ``⌈level/(1−level)⌉``, which is the
    same number in exact arithmetic and one too many in binary floating point at
    exactly the levels people use.
    """
    n = 1
    while _rank(level, n) > n:
        n += 1
    return n


def conformal_quantile(scores: Array | Sequence[float], level: float) -> float:
    """The finite-sample conformal quantile of ``|scores|``.

    Split conformal takes the ``⌈level·(n+1)⌉ / n`` empirical quantile, not the
    ``level`` one. The correction is what turns an asymptotic statement into a
    finite-sample guarantee: with exchangeable scores the resulting band covers
    with probability at least ``level`` for *any* n, however small.

    When ``⌈level·(n+1)⌉ > n`` there are not enough calibration points to make
    the guarantee at that level, and the honest answer is an infinite band. This
    function returns ``inf`` and says so, rather than clipping the quantile to 1
    and returning the sample maximum — which looks like an answer, is narrower
    than the guarantee requires, and is the silent failure mode of every
    hand-rolled implementation.

    Args:
        scores: Non-conformity scores. Absolute values are taken.
        level: Target coverage in (0, 1).

    Returns:
        The half-width, or ``inf`` when n is too small for ``level``.

    Raises:
        ValueError: If ``level`` is outside (0, 1) or ``scores`` is empty.

    Example:
        >>> import numpy as np
        >>> conformal_quantile(np.arange(1.0, 101.0), 0.9)
        91.0
        >>> conformal_quantile([1.0, 2.0, 3.0], 0.9)   # n too small for 90%
        inf
    """
    arr = np.abs(np.asarray(scores, dtype=float).ravel())
    if arr.size == 0:
        raise ValueError("conformal calibration needs at least one residual, got none")
    if not np.isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError(f"level must be a finite number in (0, 1), got {level!r}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("calibration residuals contain NaN or Inf")

    n = arr.size
    rank = _rank(level, n)
    if rank > n:
        warnings.warn(
            f"{n} calibration residuals cannot support a {level:.0%} conformal band: "
            f"the finite-sample rank is {rank} of {n}. Returning an infinite "
            f"half-width, which is the honest answer. You need at least "
            f"{_min_calibration_size(level)} residuals for this level.",
            UserWarning,
            stacklevel=2,
        )
        return float("inf")
    return float(np.partition(arr, rank - 1)[rank - 1])


@dataclass(frozen=True)
class ConformalBand:
    """A conformal half-width, and where it came from.

    A band is not a number, it is a number plus the conditions under which it
    means anything. Carrying the calibration count and the calibrated horizon
    range with it is what lets a downstream reader tell a 90 % band built on 390
    genuine h-step-ahead errors from a 90 % band built on 12.

    Attributes:
        half_width: Scalar, or one value per forecast step.
        level: Nominal coverage.
        method: Which construction produced it.
        n_calibration: How many residuals it was calibrated on.
        extrapolated: For a horizon-aware band, ``True`` at every step beyond
            the calibrated range. Those steps are a model of the band, not a
            measurement of it.
    """

    half_width: Array
    level: float
    method: str
    n_calibration: int
    extrapolated: npt.NDArray[np.bool_] = field(
        default_factory=lambda: np.zeros(0, dtype=bool)
    )

    def __post_init__(self) -> None:
        hw = np.atleast_1d(np.asarray(self.half_width, dtype=float))
        if np.any(hw < 0):
            raise ValueError("half_width must be non-negative")
        object.__setattr__(self, "half_width", hw)
        object.__setattr__(
            self, "extrapolated", np.atleast_1d(np.asarray(self.extrapolated, dtype=bool))
        )

    def apply(self, prediction: Array | Sequence[float]) -> tuple[Array, Array]:
        """Return ``(lower, upper)`` around ``prediction``.

        Example:
            >>> import numpy as np
            >>> band = split_conformal(np.array([0.1, -0.2, 0.3, -0.4] * 30), level=0.9)
            >>> lo, hi = band.apply(np.array([1.0, 1.0]))
            >>> bool(np.all(hi - lo > 0))
            True
        """
        pred = np.asarray(prediction, dtype=float)
        hw = self.half_width
        if hw.size == 1:
            return pred - hw[0], pred + hw[0]
        if hw.size < pred.size:
            raise ValueError(
                f"band covers {hw.size} steps but {pred.size} predictions were given; "
                "a horizon-aware band cannot be applied past the horizon it was built for"
            )
        return pred - hw[: pred.size], pred + hw[: pred.size]

    def to_interval(
        self,
        prediction: Array | Sequence[float],
        empirical_coverage: float | None = None,
    ) -> Interval:
        """Package the band around a prediction as an :class:`~otwin.interfaces.Interval`.

        ``empirical_coverage`` stays ``None`` unless you pass a measurement.
        A conformal guarantee is a statement about exchangeable data; whether
        this deployment is exchangeable with its calibration set is a question
        only held-out data answers, so the interval reports itself as
        unvalidated until it has been.
        """
        lower, upper = self.apply(prediction)
        return Interval(
            lower=lower,
            upper=upper,
            level=self.level,
            method=self.method,
            empirical_coverage=empirical_coverage,
        )

    @property
    def mean_width(self) -> float:
        """Mean full width of the band."""
        return float(2.0 * np.mean(self.half_width))


def split_conformal(
    residuals: Array | Sequence[float], level: float = 0.9
) -> ConformalBand:
    """One half-width for every horizon, from h-step-ahead calibration residuals.

    Args:
        residuals: Forecast errors of the same kind you are about to make. See
            the module docstring on why in-sample residuals are not those, and
            :func:`rolling_origin_residuals` for producing the right ones.
        level: Target coverage.

    Returns:
        A :class:`ConformalBand` with a scalar half-width.

    Example:
        >>> import numpy as np
        >>> rng = np.random.default_rng(0)
        >>> band = split_conformal(rng.normal(0, 0.05, 500), level=0.9)
        >>> band.n_calibration
        500
        >>> bool(0.07 < band.half_width[0] < 0.11)   # ~1.645 sigma
        True
    """
    arr = np.asarray(residuals, dtype=float).ravel()
    return ConformalBand(
        half_width=np.array([conformal_quantile(arr, level)]),
        level=level,
        method="split_conformal",
        n_calibration=arr.size,
    )


def horizon_conformal(
    residuals: Array | Sequence[float],
    horizons: Array | Sequence[int],
    level: float = 0.9,
    max_horizon: int | None = None,
    min_per_horizon: int | None = None,
    fit: str = "log",
) -> ConformalBand:
    """A half-width that grows with the forecast horizon.

    A one-step error and a sixty-step error are not draws from the same
    distribution, so pooling them gives a band that is too wide at the start of
    the horizon and too narrow at the end — the end being where the decision
    usually is. This fits ``q(h) = a·h^b`` to the per-horizon conformal
    quantiles and evaluates it at every step.

    A power law rather than a spline because it extrapolates without oscillating,
    and because ``b`` is readable: ``b = 0.5`` is a random walk, ``b = 1`` is a
    drift error accumulating linearly, and anything above 1 is a model whose
    error is compounding.

    Args:
        residuals: Forecast errors.
        horizons: The horizon each residual belongs to, same length.
        level: Target coverage.
        max_horizon: Extend the band this far. Defaults to the largest
            calibrated horizon. Steps beyond it are flagged in
            :attr:`ConformalBand.extrapolated`.
        min_per_horizon: Horizons with fewer residuals than this are dropped
            from the fit. Defaults to the smallest sample for which a conformal
            quantile at ``level`` exists at all — nine at the 90 % level. A **lower** value is raised to that minimum
            rather than honoured, because below it the quantile does not exist
            and no argument makes it exist. This matters more than it sounds:
            on a rolling-origin calibration set the far horizons are the sparse
            ones, so a permissive threshold fits the growth law through
            precisely the points that cannot support it. An implementation that
            clips the rank instead of refusing will happily fit 60 horizons of
            which 40 are the sample maximum wearing a quantile's name.
        fit: Where the least squares is done, and this is not a detail.
            ``"log"`` (default) fits the straight line in log-log space, which
            weights every horizon equally in *relative* terms. ``"linear"`` fits
            ``a·h^b`` directly, which weights it in absolute terms and so is
            dominated by the far end of the horizon, where the quantiles are an
            order of magnitude larger. On a real capacity twin the two differ by
            thirteen points of delivered coverage at the same 90 % target. The log
            fit is the default because the near horizon is where most decisions
            are made and a fit that effectively ignores it produces a band that
            is visibly wrong there.

    Returns:
        A :class:`ConformalBand` with one half-width per step.

    Raises:
        ValueError: If fewer than two horizons survive ``min_per_horizon``,
            which leaves nothing to fit a growth law to, or if ``fit`` is
            neither ``"log"`` nor ``"linear"``.

    Example:
        >>> import numpy as np
        >>> rng = np.random.default_rng(1)
        >>> h = np.repeat(np.arange(1, 11), 40)
        >>> err = rng.normal(0, 0.01, h.size) * np.sqrt(h)   # random-walk growth
        >>> band = horizon_conformal(err, h, level=0.9, max_horizon=20)
        >>> bool(band.half_width[19] > band.half_width[0])
        True
        >>> bool(band.extrapolated[19]) and not bool(band.extrapolated[0])
        True
    """
    err = np.asarray(residuals, dtype=float).ravel()
    hor = np.asarray(horizons, dtype=int).ravel()
    if err.size != hor.size:
        raise ValueError(
            f"residuals and horizons must be the same length, got {err.size} and {hor.size}"
        )

    required = _min_calibration_size(level)
    floor_n = required if min_per_horizon is None else max(int(min_per_horizon), required)

    grid, quantiles = [], []
    for h in np.unique(hor):
        block = err[hor == h]
        if block.size >= floor_n:
            grid.append(float(h))
            quantiles.append(conformal_quantile(block, level))
    if len(grid) < 2:
        raise ValueError(
            f"a horizon-aware band needs at least two horizons with {floor_n}+ residuals "
            f"each (the minimum a {level:.0%} conformal quantile exists at); got "
            f"{len(grid)}. Use split_conformal, which pools every horizon together."
        )

    h_grid = np.asarray(grid)
    q_grid = np.asarray(quantiles)
    if fit == "log":
        # A power law is a straight line in log-log space, so this is a
        # two-parameter least squares with no optimiser and no starting guess.
        slope, intercept = np.polyfit(np.log(h_grid), np.log(q_grid), 1)
        a, b = float(np.exp(intercept)), float(slope)
    elif fit == "linear":
        from scipy.optimize import curve_fit

        params, _ = curve_fit(
            lambda h, a_, b_: a_ * h**b_, h_grid, q_grid, p0=[1e-3, 1.0], maxfev=100000
        )
        a, b = float(params[0]), float(params[1])
    else:
        raise ValueError(f"fit must be 'log' or 'linear', got {fit!r}")

    h_max_cal = int(max(grid))
    n_steps = int(max_horizon) if max_horizon is not None else h_max_cal
    steps = np.arange(1, n_steps + 1, dtype=float)
    return ConformalBand(
        half_width=a * steps**b,
        level=level,
        method="horizon_conformal",
        n_calibration=err.size,
        extrapolated=steps > h_max_cal,
    )


class AdaptiveConformal:
    """Online conformal inference (ACI): a band that corrects itself.

    A fixed band is calibrated once and then hopes the world holds still. This
    one carries a working level that moves after every observation: miss, and it
    widens; cover, and it tightens by ``gamma·(1 − level)``. Over a long run the
    delivered coverage converges to the target whatever the residuals do — which
    is a much weaker claim than the split-conformal guarantee and holds under
    much weaker conditions, including distribution shift.

    What it cannot do is help before the first outcome arrives. It is for a twin
    in service with feedback, not for a one-shot forecast.

    Args:
        residuals: Initial calibration residuals.
        level: Target coverage.
        gamma: Step size. Larger adapts faster and is noisier; 0.01 to 0.05 is
            the usual range.

    Example:
        >>> import numpy as np
        >>> rng = np.random.default_rng(2)
        >>> aci = AdaptiveConformal(rng.normal(0, 0.05, 200), level=0.9, gamma=0.02)
        >>> covered = []
        >>> for y in rng.normal(0, 0.05, 400):
        ...     lo, hi = aci.interval(0.0)
        ...     covered.append(aci.update(y))
        >>> bool(0.82 < np.mean(covered) < 0.98)
        True
    """

    def __init__(
        self,
        residuals: Array | Sequence[float],
        level: float = 0.9,
        gamma: float = 0.01,
    ) -> None:
        arr = np.abs(np.asarray(residuals, dtype=float).ravel())
        if arr.size == 0:
            raise ValueError("AdaptiveConformal needs initial calibration residuals")
        if not 0.0 < gamma < 1.0:
            raise ValueError(f"gamma must be in (0, 1), got {gamma!r}")
        self._scores = arr
        self.level = float(level)
        self.gamma = float(gamma)
        self._alpha = 1.0 - float(level)
        self._last: tuple[float, float] | None = None
        self.history: list[dict[str, float]] = []

    @property
    def alpha(self) -> float:
        """Current working miscoverage level. Drifts away from ``1 − level``."""
        return self._alpha

    def interval(self, prediction: float) -> tuple[float, float]:
        """Return ``(lower, upper)`` for the next step at the current level."""
        alpha = float(np.clip(self._alpha, 1e-3, 1.0 - 1e-3))
        with warnings.catch_warnings():
            # A working level driven near 1 by a run of misses is the mechanism
            # doing its job, not a calibration-size problem worth a warning per
            # step. The size warning still fires on construction paths.
            warnings.simplefilter("ignore", UserWarning)
            half = conformal_quantile(self._scores, 1.0 - alpha)
        self._last = (prediction - half, prediction + half)
        return self._last

    def update(self, observation: float) -> bool:
        """Record the outcome, nudge the level, and report whether it was covered.

        Raises:
            RuntimeError: If called before :meth:`interval`. The update is
                defined against the interval that was actually offered, so
                there has to have been one.
        """
        if self._last is None:
            raise RuntimeError(
                "call interval() before update(): ACI updates the level "
                "against the band it just offered"
            )
        lower, upper = self._last
        covered = bool(lower <= observation <= upper)
        target = 1.0 - self.level
        self._alpha = self._alpha + self.gamma * (target - (0.0 if covered else 1.0))
        self.history.append(
            {"alpha": self._alpha, "width": upper - lower, "covered": float(covered)}
        )
        self._last = None
        return covered


def rolling_origin_residuals(
    refit_forecast: Callable[[Array, int], Array],
    series: Array | Sequence[float],
    origins: Iterable[int] | None = None,
    step: int = 5,
    min_train: int | None = None,
    max_horizon: int | None = None,
) -> tuple[Array, Array]:
    """Generate honest h-step-ahead calibration residuals.

    This is the expensive, correct alternative to quantiling a fitted model's own
    residuals. At each origin the *whole pipeline* is refitted on the history up
    to that origin and asked to forecast forward; the errors that come back are
    the same kind of error the deployed twin will make.

    Everything happens strictly inside the data you pass. Nothing after the last
    origin is used for anything but scoring the forecast that reached it, so the
    residuals carry no information from the window you are about to forecast.

    Args:
        refit_forecast: ``f(history, horizon) -> forecast`` — the same
            leakage-free signature :func:`otwin.forecast.evaluate` requires. It
            must refit; passing a closure over an already-fitted model
            reintroduces exactly the leak this function exists to avoid.
        series: The calibration series.
        origins: Explicit origins (indices into ``series``). Defaults to a
            regular grid from ``min_train`` to the end.
        step: Spacing of the default origin grid.
        min_train: First origin. Defaults to ``max(20, len(series) // 3)``.
        max_horizon: Truncate each forecast to this many steps.

    Returns:
        ``(residuals, horizons)`` — flat arrays of the same length, ready for
        :func:`split_conformal` or :func:`horizon_conformal`.

    Example:
        >>> import numpy as np
        >>> y = 1.0 - 0.002 * np.arange(120)
        >>> def refit(history, horizon):
        ...     n = len(history)
        ...     slope = (history[-1] - history[0]) / (n - 1)
        ...     return history[-1] + slope * np.arange(1, horizon + 1)
        >>> res, hor = rolling_origin_residuals(refit, y, step=10)
        >>> bool(res.size == hor.size and res.size > 0)
        True
        >>> bool(np.max(np.abs(res)) < 1e-9)      # a line, forecast by a line
        True
    """
    y = np.asarray(series, dtype=float).ravel()
    n = y.size
    if min_train is None:
        min_train = max(20, n // 3)
    if origins is None:
        origins = range(int(min_train), n, int(step))

    all_err: list[Array] = []
    all_hor: list[npt.NDArray[np.integer]] = []
    for origin in origins:
        origin = int(origin)
        if origin < 1 or origin >= n:
            continue
        horizon = n - origin
        if max_horizon is not None:
            horizon = min(horizon, int(max_horizon))
        if horizon < 1:
            continue
        pred = np.asarray(refit_forecast(y[:origin], horizon), dtype=float).ravel()
        if pred.size != horizon:
            raise ValueError(
                f"refit_forecast returned {pred.size} steps for a horizon of {horizon}. "
                "A forecaster must return exactly the number of steps it was asked for."
            )
        all_err.append(y[origin : origin + horizon] - pred)
        all_hor.append(np.arange(1, horizon + 1))

    if not all_err:
        raise ValueError(
            "no usable origins: check min_train, step and the length of the series"
        )
    return np.concatenate(all_err), np.concatenate(all_hor)
