"""Conditioning: irregular, gappy, mixed-unit field data into a clean grid.

Nothing here is clever. All of it is load-bearing. Every failure this module
prevents is silent -- a resample that interpolates across a four-hour outage,
a tag in kW averaged with a tag in W, a batch of samples that arrived out of
order because two RTUs disagree about the time. None of those raise. They
just produce a number that is slightly wrong, and it survives all the way to
a maintenance decision.

The policy throughout: **do not invent data.** A gap longer than the stated
tolerance is a gap, and it comes back as NaN with a record of where it was.
Filling it silently is how a model learns to forecast the interpolator.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Gap:
    """A stretch of time with no measurement.

    Attributes:
        start: Timestamp of the last sample before the gap.
        end: Timestamp of the first sample after it.
        duration: ``end - start``, in the same units as the timestamps.
        n_missing: How many grid points fall inside it.
    """

    start: float
    end: float
    duration: float
    n_missing: int


def find_gaps(
    t: npt.ArrayLike,
    max_gap: float,
) -> list[Gap]:
    """Locate every interval longer than ``max_gap``.

    Args:
        t: Timestamps, strictly increasing.
        max_gap: Longest interval treated as continuous.

    Returns:
        Gaps, in time order.

    Example:
        >>> find_gaps([0.0, 1.0, 2.0, 60.0, 61.0], max_gap=5.0)
        [Gap(start=2.0, end=60.0, duration=58.0, n_missing=0)]
    """
    t = np.asarray(t, dtype=float)
    if t.ndim != 1:
        raise ValueError("timestamps must be one-dimensional")
    if t.size < 2:
        return []
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError(
            "timestamps are not strictly increasing -- run sort_samples first"
        )
    return [
        Gap(start=float(t[i]), end=float(t[i + 1]), duration=float(dt[i]), n_missing=0)
        for i in np.flatnonzero(dt > max_gap)
    ]


def sort_samples(
    t: npt.ArrayLike,
    y: npt.ArrayLike,
    drop_duplicates: bool = True,
) -> tuple[npt.NDArray[np.floating], npt.NDArray[np.floating]]:
    """Put out-of-order samples back in order.

    Two RTUs on the same bus will disagree about the time, and a historian
    export will happily hand you the result unsorted. Every other function in
    this module assumes increasing timestamps, so this runs first.

    Args:
        t: Timestamps, in any order.
        y: Values, shape ``(n,)`` or ``(n, k)``.
        drop_duplicates: Keep only the last sample at each repeated timestamp.

    Returns:
        ``(t_sorted, y_sorted)``.

    Example:
        >>> t, y = sort_samples([2.0, 0.0, 1.0], [20.0, 0.0, 10.0])
        >>> t.tolist(), y.tolist()
        ([0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.shape[0] != t.shape[0]:
        raise ValueError(f"got {t.shape[0]} timestamps and {y.shape[0]} values")

    order = np.argsort(t, kind="stable")
    t, y = t[order], y[order]

    if drop_duplicates and t.size > 1:
        # Keep the last occurrence of each timestamp: a later write to the same
        # instant is a correction, not a duplicate.
        keep = np.append(np.diff(t) > 0, True)
        t, y = t[keep], y[keep]
    return t, y


def resample(
    t: npt.ArrayLike,
    y: npt.ArrayLike,
    dt: float,
    max_gap: float | None = None,
    method: str = "linear",
) -> tuple[npt.NDArray[np.floating], npt.NDArray[np.floating], list[Gap]]:
    """Put irregular samples on a uniform grid, without inventing data.

    Args:
        t: Timestamps, strictly increasing (run :func:`sort_samples` first).
        y: Values, shape ``(n,)`` or ``(n, k)``.
        dt: Target grid spacing.
        max_gap: Intervals longer than this are not interpolated across --
            the grid points inside them come back NaN. Defaults to ``3 * dt``,
            which is deliberately conservative. Pass ``float("inf")`` to
            interpolate across everything, and understand what you are asking
            for.
        method: ``"linear"`` or ``"previous"`` (zero-order hold). Use
            ``"previous"`` for anything that is really a setpoint or a state,
            where a linear ramp between two values never physically happened.

    Returns:
        ``(t_grid, y_grid, gaps)``. ``y_grid`` is NaN inside every gap, and
        ``gaps`` carries ``n_missing`` filled in so you can report how much of
        the window was actually measured.

    Example:
        >>> t_g, y_g, gaps = resample([0., 1., 2., 10.], [0., 1., 2., 10.],
        ...                           dt=1.0, max_gap=3.0)
        >>> len(gaps), gaps[0].n_missing
        (1, 7)
        >>> bool(np.isnan(y_g[5]))
        True
        >>> y_g[1]
        1.0
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    squeeze = y.ndim == 1
    if squeeze:
        y = y[:, None]
    if t.size < 2:
        raise ValueError("need at least two samples to resample")
    if dt <= 0:
        raise ValueError(f"dt must be positive, got {dt}")
    if max_gap is None:
        max_gap = 3.0 * dt

    gaps = find_gaps(t, max_gap)
    t_grid = np.arange(t[0], t[-1] + 0.5 * dt, dt)

    if method == "linear":
        cols = [np.interp(t_grid, t, y[:, j]) for j in range(y.shape[1])]
    elif method == "previous":
        idx = np.searchsorted(t, t_grid, side="right") - 1
        idx = np.clip(idx, 0, len(t) - 1)
        cols = [y[idx, j] for j in range(y.shape[1])]
    else:
        raise ValueError(f"unknown method {method!r}; use 'linear' or 'previous'")
    y_grid = np.column_stack(cols)

    # Blank the interior of every gap. The endpoints are real measurements and
    # stay; only the invented middle is removed.
    filled_gaps = []
    for gap in gaps:
        inside = (t_grid > gap.start) & (t_grid < gap.end)
        n = int(inside.sum())
        y_grid[inside, :] = np.nan
        filled_gaps.append(
            Gap(start=gap.start, end=gap.end, duration=gap.duration, n_missing=n)
        )

    return t_grid, (y_grid[:, 0] if squeeze else y_grid), filled_gaps


def coverage(y: npt.ArrayLike) -> float:
    """Fraction of a conditioned series that is a real measurement.

    Report this next to any metric computed on resampled data. A skill score
    over a window that was 40 percent interpolated is not a skill score.

    Example:
        >>> coverage([1.0, np.nan, 3.0, 4.0])
        0.75
    """
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return 0.0
    return float(np.mean(~np.isnan(y)))
