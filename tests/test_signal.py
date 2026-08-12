"""Tests for :mod:`otwin.signal` — the ISO 13374 Data Manipulation block.

This module has one rule and it is written on the tin: **do not invent data.**
A resample that quietly interpolates across a four-hour outage does not raise,
does not warn, and does not look wrong on a plot. It produces a number that is
slightly false and survives all the way to a maintenance decision.

So the tests here are written the way the module is: every test that asserts a
gap comes back NaN also asserts that the *same call with the policy relaxed*
returns a finite, plausible number. Without that second half, the first half
passes just as happily against a function that returns NaN for everything, and
tells you nothing about whether the policy is the thing doing the work.
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from otwin.signal import Gap, coverage, find_gaps, resample, sort_samples

# --------------------------------------------------------------------------
# 1. the core promise: a gap is a gap
# --------------------------------------------------------------------------


def test_long_gap_is_nan_inside_and_real_at_the_endpoints() -> None:
    """The interior of a gap is blanked; its endpoints are measurements and stay.

    This is the acceptance gate for the module. Both halves are load-bearing.
    Blanking the endpoints too would throw away two real readings — the last
    one before the link dropped and the first one after it came back — which
    are exactly the samples an operator wants when reconstructing an outage.
    Blanking nothing is the silent interpolation this module exists to prevent.

    The teeth are at the bottom: the identical call with ``max_gap=inf`` fills
    the same interval with a clean ramp. The NaNs are therefore a policy, not
    an inability, and a regression that dropped the policy would show up here
    as a finite value where a NaN belongs.
    """
    t = np.array([0.0, 1.0, 2.0, 3.0, 40.0, 41.0, 42.0])
    y = t.copy()  # y == t makes every interpolated value trivially predictable

    t_grid, y_grid, gaps = resample(t, y, dt=1.0, max_gap=5.0)

    assert t_grid.shape == (43,)
    assert len(gaps) == 1
    assert gaps[0] == Gap(start=3.0, end=40.0, duration=37.0, n_missing=36)

    # Interior: every grid point strictly between the two real samples is NaN.
    assert np.all(np.isnan(y_grid[4:40]))
    assert int(np.isnan(y_grid).sum()) == gaps[0].n_missing

    # Endpoints: the last measurement before the outage and the first one after
    # it are real readings and must survive untouched.
    assert y_grid[3] == 3.0
    assert y_grid[40] == 40.0
    assert np.all(np.isfinite(y_grid[:4]))
    assert np.all(np.isfinite(y_grid[40:]))

    # Teeth: the same interval is perfectly interpolable. Refusing to fill it is
    # a decision, and this is the value the module is declining to invent.
    _, y_filled, gaps_filled = resample(t, y, dt=1.0, max_gap=float("inf"))
    assert gaps_filled == []
    assert np.all(np.isfinite(y_filled))
    assert y_filled[20] == pytest.approx(20.0)


def test_infinite_max_gap_interpolates_across_everything() -> None:
    """``max_gap=inf`` is the documented escape hatch and must really escape.

    An operator who has read the docstring and decided that a linear fill is
    appropriate for their tag must get one — with no gaps reported, because a
    reported gap that was filled anyway is a lie in the coverage number.
    """
    t = np.array([0.0, 1.0, 500.0])
    y = np.array([0.0, 1.0, 500.0])

    t_grid, y_grid, gaps = resample(t, y, dt=1.0, max_gap=float("inf"))

    assert gaps == []
    assert not np.isnan(y_grid).any()
    assert coverage(y_grid) == 1.0
    assert y_grid == pytest.approx(t_grid)


def test_default_max_gap_is_three_steps() -> None:
    """Omitting ``max_gap`` must mean ``3 * dt``, not "no limit".

    A default that silently meant "interpolate across anything" would make the
    safe-looking call the dangerous one. The two spacings below straddle the
    documented threshold: 2.5 steps is continuous, 3.5 steps is an outage.
    """
    dt = 2.0
    below = np.array([0.0, 2.5 * dt])  # 5.0 s apart: under the 6.0 s threshold
    above = np.array([0.0, 3.5 * dt])  # 7.0 s apart: over it

    _, y_below, gaps_below = resample(below, np.array([0.0, 1.0]), dt=dt)
    assert gaps_below == []
    assert np.all(np.isfinite(y_below))

    _, y_above, gaps_above = resample(above, np.array([0.0, 1.0]), dt=dt)
    assert len(gaps_above) == 1
    assert gaps_above[0].duration == 7.0
    assert np.isnan(y_above).any()

    # And the default is exactly `3 * dt`, not merely "something conservative":
    # passing it explicitly must reproduce the default result bit for bit.
    t = np.array([0.0, 1.0, 2.0, 30.0, 31.0])
    y = np.array([0.0, 1.0, 2.0, 30.0, 31.0])
    _, y_default, gaps_default = resample(t, y, dt=dt)
    _, y_explicit, gaps_explicit = resample(t, y, dt=dt, max_gap=3.0 * dt)
    assert gaps_default == gaps_explicit
    np.testing.assert_array_equal(np.isnan(y_default), np.isnan(y_explicit))
    np.testing.assert_array_equal(
        y_default[~np.isnan(y_default)], y_explicit[~np.isnan(y_explicit)]
    )


# --------------------------------------------------------------------------
# 2. interpolation method: a setpoint is not a ramp
# --------------------------------------------------------------------------


def test_previous_holds_values_the_signal_actually_took() -> None:
    """A setpoint must never be linearly ramped through values it never held.

    A breaker position, a control mode, a commanded power setpoint: these are
    piecewise constant. Ramping one from 0 to 1 over ten grid points invents
    nine operating states the plant was never in, and any feature computed
    from them — a rate of change, a dwell time, a transition count — is then
    a property of the interpolator rather than the machine.

    Both halves are asserted, because the "previous" half alone would pass
    against an implementation that ignored ``method`` and always held.
    """
    t = np.array([0.0, 10.0, 20.0])
    y = np.array([0.0, 1.0, 1.0])  # a setpoint that steps once, at t = 10

    _, y_hold, _ = resample(t, y, dt=1.0, max_gap=float("inf"), method="previous")
    _, y_ramp, _ = resample(t, y, dt=1.0, max_gap=float("inf"), method="linear")

    # Zero-order hold: every returned value is a value the signal really took.
    assert set(np.unique(y_hold)) <= {0.0, 1.0}
    assert y_hold[9] == 0.0  # still at the old setpoint one second before the step
    assert y_hold[10] == 1.0  # and at the new one from the step onwards

    # Teeth: `linear` on the same data does invent the intermediate states, so
    # the two methods are genuinely different code paths and not an alias.
    assert np.any((y_ramp > 0.0) & (y_ramp < 1.0))
    assert y_ramp[5] == pytest.approx(0.5)
    assert not np.array_equal(y_hold, y_ramp)


def test_previous_still_refuses_to_fill_a_gap() -> None:
    """Zero-order hold is not a licence to hold across an outage.

    Holding the last known value across four hours of lost telemetry is the
    same fabrication as ramping across it, and is easier to miss because the
    result looks like a plausible flat line.
    """
    t = np.array([0.0, 1.0, 2.0, 40.0])
    y = np.array([5.0, 5.0, 5.0, 9.0])

    _, y_grid, gaps = resample(t, y, dt=1.0, max_gap=3.0, method="previous")

    assert len(gaps) == 1
    assert np.all(np.isnan(y_grid[3:40]))
    assert y_grid[2] == 5.0
    assert y_grid[40] == 9.0


# --------------------------------------------------------------------------
# 3. sort_samples: order and corrections
# --------------------------------------------------------------------------


def test_sort_samples_restores_shuffled_records() -> None:
    """A historian export arrives unsorted; everything downstream assumes sorted.

    The pairing matters as much as the order: a sort that reordered ``t`` but
    not ``y`` would pass a test that only checked the timestamps, and would
    silently attach every reading to the wrong instant.
    """
    rng = np.random.default_rng(0)
    t_true = np.arange(50, dtype=float)
    y_true = t_true * 10.0

    order = rng.permutation(50)
    t_sorted, y_sorted = sort_samples(t_true[order], y_true[order])

    np.testing.assert_array_equal(t_sorted, t_true)
    np.testing.assert_array_equal(y_sorted, y_true)
    # The invariant every other function in the module relies on.
    assert np.all(np.diff(t_sorted) > 0)
    # And `find_gaps`, which refuses unsorted input, now accepts it.
    assert find_gaps(t_sorted, max_gap=1.5) == []


def test_duplicate_timestamps_keep_the_last_write() -> None:
    """A second value at the same instant is a correction, not a duplicate.

    Historians re-issue a sample when a bad reading is fixed upstream. Keeping
    the first occurrence would preserve the value that was already known to be
    wrong; keeping the mean would invent a third value that was never written.
    """
    t = np.array([0.0, 1.0, 1.0, 1.0, 2.0])
    y = np.array([0.0, -99.0, -50.0, 10.0, 20.0])

    t_out, y_out = sort_samples(t, y)

    np.testing.assert_array_equal(t_out, [0.0, 1.0, 2.0])
    np.testing.assert_array_equal(y_out, [0.0, 10.0, 20.0])
    assert -99.0 not in y_out and -50.0 not in y_out

    # Order of arrival, not order in the array, decides which one is "last":
    # the stable sort must not reshuffle equal timestamps.
    t_shuffled = np.array([2.0, 1.0, 1.0, 0.0, 1.0])
    y_shuffled = np.array([20.0, -99.0, -50.0, 0.0, 10.0])
    t_out2, y_out2 = sort_samples(t_shuffled, y_shuffled)
    np.testing.assert_array_equal(t_out2, [0.0, 1.0, 2.0])
    np.testing.assert_array_equal(y_out2, [0.0, 10.0, 20.0])


def test_drop_duplicates_false_keeps_every_sample() -> None:
    """Deduplication is opt-out, and opting out must really keep both rows.

    Two sensors written to the same tag at the same instant are a data-quality
    finding, and an analyst chasing one needs to see both values.
    """
    t = np.array([1.0, 0.0, 1.0])
    y = np.array([10.0, 0.0, 11.0])

    t_out, y_out = sort_samples(t, y, drop_duplicates=False)

    np.testing.assert_array_equal(t_out, [0.0, 1.0, 1.0])
    np.testing.assert_array_equal(y_out, [0.0, 10.0, 11.0])
    # Not strictly increasing any more, so the downstream refusal still fires.
    with pytest.raises(ValueError, match="strictly increasing"):
        find_gaps(t_out, max_gap=0.5)


def test_sort_samples_rejects_mismatched_lengths() -> None:
    """Timestamps and values that disagree in length is a caller bug, not data.

    Silently truncating to the shorter of the two would shift every reading
    onto the wrong timestamp from the mismatch onwards.
    """
    with pytest.raises(ValueError, match="3 timestamps and 2 values"):
        sort_samples([0.0, 1.0, 2.0], [0.0, 1.0])


def test_single_sample_survives_sort_samples() -> None:
    """One sample is a degenerate but legal record and must not raise.

    The deduplication step works on ``np.diff``, which is empty here; a naive
    implementation indexes past the end or returns an empty array instead.
    """
    t_out, y_out = sort_samples([7.0], [3.0])
    np.testing.assert_array_equal(t_out, [7.0])
    np.testing.assert_array_equal(y_out, [3.0])


# --------------------------------------------------------------------------
# 4. shapes
# --------------------------------------------------------------------------


def test_multicolumn_input_round_trips_and_1d_input_squeezes() -> None:
    """A ``(n, k)`` block resamples column-wise; a ``(n,)`` series stays 1-D.

    Tags are conditioned in blocks — voltage, current, temperature from one
    device on one grid — and a shape that came back ``(m, 1)`` for a single
    tag would break every caller that indexes it as a series. Column-wise
    independence is asserted against the one-column-at-a-time result, so a
    transposed or broadcast bug cannot hide behind a correct shape.
    """
    t = np.array([0.0, 1.0, 2.0, 3.0, 30.0, 31.0])
    Y = np.column_stack([t, t * 2.0, -t])

    t_grid, y_grid, gaps = resample(t, Y, dt=1.0, max_gap=5.0)

    assert y_grid.ndim == 2
    assert y_grid.shape == (t_grid.size, 3)
    assert len(gaps) == 1

    for j in range(3):
        _, y_col, gaps_col = resample(t, Y[:, j], dt=1.0, max_gap=5.0)
        assert y_col.ndim == 1
        assert gaps_col == gaps
        np.testing.assert_array_equal(np.isnan(y_col), np.isnan(y_grid[:, j]))
        finite = ~np.isnan(y_col)
        np.testing.assert_allclose(y_col[finite], y_grid[finite, j])

    # A gap is a gap for the whole device: rows are blanked, not cells.
    blanked = np.isnan(y_grid)
    assert np.all(blanked.any(axis=1) == blanked.all(axis=1))

    # 1-D in, 1-D out, at the original sample instants.
    t_g1, y_g1, _ = resample(t, t, dt=1.0, max_gap=float("inf"))
    assert y_g1.shape == t_g1.shape


# --------------------------------------------------------------------------
# 5. find_gaps and coverage
# --------------------------------------------------------------------------


def test_find_gaps_refuses_unsorted_timestamps_and_names_the_remedy() -> None:
    """Out-of-order input must raise, and the message must say what to run.

    Unsorted timestamps produce negative ``diff``, which compares false against
    any positive ``max_gap`` — so an implementation without this guard reports
    "no gaps" on the worst data it will ever see. The remedy is named in the
    message because the caller who hits this has a historian export in hand and
    no reason to know which function fixes it.
    """
    with pytest.raises(ValueError, match="sort_samples"):
        find_gaps([0.0, 2.0, 1.0, 3.0], max_gap=0.5)

    # Repeated timestamps are non-increasing too, and equally not "no gap".
    with pytest.raises(ValueError, match="strictly increasing"):
        find_gaps([0.0, 1.0, 1.0], max_gap=0.5)

    with pytest.raises(ValueError, match="one-dimensional"):
        find_gaps(np.zeros((3, 2)), max_gap=0.5)


def test_find_gaps_on_records_too_short_to_have_one() -> None:
    """Zero or one sample has no interval, so it has no gap — and no exception.

    This runs on whatever the last poll returned. A window that happened to
    contain one sample must not take the pipeline down.
    """
    assert find_gaps([], max_gap=1.0) == []
    assert find_gaps([5.0], max_gap=1.0) == []


def test_find_gaps_reports_the_interval_it_found() -> None:
    """Gap bounds are the surrounding measurements, and ``n_missing`` is not yet
    known.

    ``find_gaps`` has no grid, so it cannot say how many points fall inside;
    it reports ``0`` and :func:`resample` fills the real count in. Asserting
    that here pins the division of labour, so a caller reading ``n_missing``
    off ``find_gaps`` output is reading a documented placeholder rather than a
    number that quietly became wrong.
    """
    gaps = find_gaps([0.0, 1.0, 2.0, 60.0, 61.0, 200.0], max_gap=5.0)

    assert [(g.start, g.end) for g in gaps] == [(2.0, 60.0), (61.0, 200.0)]
    assert [g.duration for g in gaps] == [58.0, 139.0]
    assert all(g.n_missing == 0 for g in gaps)
    # Time order, so a report reads chronologically.
    assert gaps[0].start < gaps[1].start

    # The threshold is exclusive: an interval of exactly max_gap is continuous.
    assert find_gaps([0.0, 5.0, 10.0], max_gap=5.0) == []
    assert len(find_gaps([0.0, 5.001, 10.0], max_gap=5.0)) == 1


def test_coverage_measures_what_was_really_measured() -> None:
    """Coverage counts real samples, and an all-NaN window scores zero.

    This number is meant to be reported next to a skill score. If it read high
    on a window that was mostly interpolated, it would certify exactly the
    thing it exists to expose.
    """
    assert coverage([1.0, np.nan, 3.0, 4.0]) == 0.75
    assert coverage([np.nan, np.nan, np.nan]) == 0.0
    assert coverage([1.0, 2.0]) == 1.0

    # An empty window is not "fully covered". Returning 1.0 here would let a
    # window with no data at all pass a coverage threshold.
    assert coverage([]) == 0.0

    # And it agrees with the gap accounting on real conditioned output.
    t = np.array([0.0, 1.0, 2.0, 3.0, 40.0, 41.0, 42.0])
    t_grid, y_grid, gaps = resample(t, t, dt=1.0, max_gap=5.0)
    expected = 1.0 - sum(g.n_missing for g in gaps) / t_grid.size
    assert coverage(y_grid) == pytest.approx(expected)
    assert coverage(y_grid) < 0.2  # this window really was mostly an outage

    # Multi-column input is counted cell-wise, which is what a block of tags on
    # one grid needs.
    assert coverage(np.array([[1.0, np.nan], [2.0, 3.0]])) == 0.75


# --------------------------------------------------------------------------
# 6. error paths
# --------------------------------------------------------------------------


def test_resample_refuses_impossible_requests() -> None:
    """Each refusal names the offending argument.

    A non-positive ``dt`` produces an empty or infinite grid, one sample gives
    a grid with no span, and an unrecognised method would otherwise fall
    through to whichever branch was written last. All three are caller errors
    that must surface at the call, not as a strange array three functions
    downstream.
    """
    t = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])

    with pytest.raises(ValueError, match="dt must be positive"):
        resample(t, y, dt=0.0)
    with pytest.raises(ValueError, match="dt must be positive"):
        resample(t, y, dt=-1.0)
    with pytest.raises(ValueError, match="at least two samples"):
        resample([1.0], [1.0], dt=1.0)
    with pytest.raises(ValueError, match="unknown method"):
        resample(t, y, dt=1.0, method="cubic")
    # The message must offer the alternatives, not just reject the input.
    with pytest.raises(ValueError, match="'linear' or 'previous'"):
        resample(t, y, dt=1.0, method="spline")

    # Unsorted input reaches the same guard `find_gaps` uses, so `resample`
    # cannot be used as a way around it.
    with pytest.raises(ValueError, match="sort_samples"):
        resample([0.0, 2.0, 1.0], [0.0, 2.0, 1.0], dt=1.0)


# --------------------------------------------------------------------------
# 7. property
# --------------------------------------------------------------------------


@given(
    t0=st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
    steps=st.lists(
        st.floats(min_value=1e-3, max_value=10.0, allow_nan=False),
        min_size=1,
        max_size=20,
    ),
    n_steps=st.integers(min_value=1, max_value=200),
)
def test_resampled_grid_is_uniform_and_covers_the_record(
    t0: float, steps: list[float], n_steps: int
) -> None:
    """For any strictly increasing record and any positive ``dt``, the grid is
    uniform, strictly increasing, and covers the measured span.

    Everything downstream — a windowed feature, an FFT, a fixed-step
    integrator — assumes the returned grid is exactly uniform. It is built by
    ``arange`` over an arbitrary origin and span, so this is a floating-point
    claim rather than an obvious one: the property is stated once here instead
    of being spot-checked at whichever spacings happened to occur to the author
    of an example-based test.

    The end of the grid is stated as "within half a step of the last sample"
    rather than "at or before it", which is what the ``+ 0.5 * dt`` in the
    ``arange`` stop actually produces: the grid may run up to half a step past
    the final measurement, holding that measurement's value.
    """
    t = t0 + np.concatenate([[0.0], np.cumsum(steps)])
    span = float(t[-1] - t[0])
    dt = span / n_steps

    t_grid, y_grid, gaps = resample(t, t, dt=dt, max_gap=float("inf"))

    # Scale-aware tolerance: `arange` computes start + i*step, so the error
    # floor is the ULP of the timestamps themselves, not of the spacing.
    tol = 1e-9 * max(1.0, abs(t0), abs(float(t[-1])))

    assert t_grid.size >= 2
    assert t_grid[0] == t[0]
    assert np.all(np.diff(t_grid) > 0.0)
    assert np.allclose(np.diff(t_grid), dt, rtol=1e-9, atol=tol)

    # Covers the record: the first sample is on the grid, and the grid runs to
    # within half a step of the last one.
    assert t_grid[-1] >= t[-1] - 0.5 * dt - tol
    assert t_grid[-1] <= t[-1] + 0.5 * dt + tol

    # And the values ride along: same length, no gaps declared, nothing NaN.
    assert y_grid.shape == t_grid.shape
    assert gaps == []
    assert not np.isnan(y_grid).any()
    assert coverage(y_grid) == 1.0
