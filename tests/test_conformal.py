"""Conformal band construction.

`otwin.forecast` could measure a band long before it could build one, so every
worked example hand-rolled its own. The tests here pin the two properties that
make the construction worth having — the finite-sample guarantee, and the
refusal to pretend when there is not enough calibration data — and the failure
mode that makes it worth having *in the library*: calibrating on in-sample
residuals, which is the mistake everyone makes once.
"""

import warnings

import numpy as np
import pytest

from otwin.forecast import (
    AdaptiveConformal,
    ConformalBand,
    conformal_quantile,
    horizon_conformal,
    picp,
    rolling_origin_residuals,
    split_conformal,
)


def test_finite_sample_quantile_uses_the_rank_correction():
    """⌈level(n+1)⌉/n, not the plain empirical quantile. That is the guarantee."""
    scores = np.arange(1.0, 101.0)  # n = 100
    # rank = ceil(0.9 * 101) = 91 -> the 91st smallest, which is 91.0
    assert conformal_quantile(scores, 0.9) == 91.0
    # The naive np.quantile(scores, 0.9) is 90.1: narrower, and not the guarantee.
    assert conformal_quantile(scores, 0.9) > float(np.quantile(scores, 0.9))


def test_the_boundary_is_not_moved_by_floating_point():
    """0.9 * 10 is 9.000000000000002, so a bare ceil rejects a set that is exact.

    Nine residuals is precisely enough for a 90 % band. Getting this wrong costs
    the sparsest horizons of a rolling-origin calibration set, which are the ones
    that set the extrapolated end of a horizon-aware band.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert conformal_quantile(np.arange(1.0, 10.0), 0.9) == 9.0  # n = 9
        assert conformal_quantile(np.arange(1.0, 20.0), 0.95) == 19.0  # n = 19
        assert conformal_quantile(np.arange(1.0, 100.0), 0.99) == 99.0  # n = 99


def test_too_few_residuals_returns_infinity_and_says_so():
    """The silent failure this replaces: clipping the rank and returning the max."""
    with pytest.warns(UserWarning, match="cannot support"):
        q = conformal_quantile([0.1, 0.2, 0.3], 0.9)
    assert q == float("inf")
    with pytest.warns(UserWarning, match="at least 9 residuals"):
        conformal_quantile(np.arange(1.0, 9.0), 0.9)  # n = 8
    # The boundary is exact: a 95% band needs ceil(0.95(n+1)) <= n, i.e. n >= 19.
    with pytest.warns(UserWarning):
        assert conformal_quantile(np.arange(1.0, 19.0), 0.95) == float("inf")  # n = 18
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert np.isfinite(conformal_quantile(np.arange(1.0, 20.0), 0.95))  # n = 19


def test_split_conformal_delivers_its_nominal_coverage_on_exchangeable_data():
    """The guarantee is finite-sample, so test it as a rate over many replicates."""
    rng = np.random.default_rng(0)
    hits = []
    for _ in range(400):
        calibration = rng.normal(0.0, 0.05, 60)
        band = split_conformal(calibration, level=0.9)
        lower, upper = band.apply(np.zeros(20))
        hits.append(picp(rng.normal(0.0, 0.05, 20), lower, upper))
    assert 0.88 < float(np.mean(hits)) < 0.96


def test_in_sample_residuals_are_the_documented_trap():
    """The 1.5%-coverage failure, reproduced small and pinned.

    An interpolating fit has in-sample residuals an order of magnitude below its
    h-step-ahead errors. Calibrating on them is not conservative, it is wrong,
    and no amount of data fixes it because the quantity itself is different.
    """
    rng = np.random.default_rng(3)
    truth = np.cumsum(rng.normal(0, 0.02, 200))
    in_sample = rng.normal(0, 0.002, 200)  # what an interpolator leaves behind
    forecast_errors = rng.normal(0, 0.05, 200)  # what it will actually do at horizon

    naive = split_conformal(in_sample, level=0.9)
    honest = split_conformal(forecast_errors, level=0.9)

    test_err = rng.normal(0, 0.05, 500)
    naive_cov = picp(test_err, *naive.apply(np.zeros(500)))
    honest_cov = picp(test_err, *honest.apply(np.zeros(500)))

    assert naive_cov < 0.15  # catastrophic, not marginal
    assert 0.85 < honest_cov < 0.95
    assert naive.half_width[0] < 0.2 * honest.half_width[0]
    assert truth.size == 200  # the series is only here to make the story concrete


def test_horizon_band_grows_and_flags_extrapolation():
    rng = np.random.default_rng(1)
    horizons = np.repeat(np.arange(1, 13), 60)
    errors = rng.normal(0, 0.01, horizons.size) * np.sqrt(horizons)

    band = horizon_conformal(errors, horizons, level=0.9, max_horizon=30)
    assert band.half_width.size == 30
    assert np.all(np.diff(band.half_width) > 0)
    # Everything past the calibrated range is a model of the band, not a
    # measurement, and has to be marked as such.
    assert not band.extrapolated[:12].any()
    assert band.extrapolated[12:].all()
    # sqrt growth recovered from data: the exponent should land near 0.5.
    ratio = band.half_width[15] / band.half_width[3]
    assert 1.6 < ratio < 2.8


def test_sparse_horizons_are_dropped_rather_than_faked():
    """The fix, pinned. A rolling-origin calibration set is sparse at the far end.

    Origins spaced through a training window produce many residuals at h = 1 and
    a handful at the longest horizons. Below nine residuals a 90 % conformal
    quantile does not exist, and an implementation that clips the rank returns
    the sample maximum instead — so the growth law gets fitted through points
    that are not quantiles at all, and they are exactly the far points that set
    the extrapolated end of the band.
    """
    dense = [np.full(30, h) for h in range(1, 11)]  # h = 1..10
    sparse = [np.full(n, h) for h, n in zip(range(11, 19), range(8, 0, -1), strict=True)]
    horizons = np.concatenate(dense + sparse)  # h = 11..18, n = 8..1
    rng = np.random.default_rng(11)
    errors = rng.normal(0, 0.01, horizons.size) * np.sqrt(horizons)

    band = horizon_conformal(errors, horizons, level=0.9, max_horizon=25)
    # h = 11..18 carry 8 residuals or fewer and cannot support the level, so the
    # calibrated range stops at 10 and everything past it is marked extrapolated.
    assert band.extrapolated[:10].sum() == 0
    assert band.extrapolated[10:].all()

    # A permissive threshold cannot buy those horizons back: the quantile does
    # not exist, and the floor is derived from the level, not from the argument.
    permissive = horizon_conformal(
        errors, horizons, level=0.9, max_horizon=25, min_per_horizon=2
    )
    np.testing.assert_allclose(permissive.half_width, band.half_width, rtol=1e-12)

    # A lower level needs fewer residuals, so more horizons become usable.
    at_80 = horizon_conformal(errors, horizons, level=0.8, max_horizon=25)
    assert at_80.extrapolated.sum() < band.extrapolated.sum()


def test_the_fit_space_is_a_real_choice_and_is_reported():
    """log vs linear least squares change the band, so the argument earns itself."""
    horizons = np.repeat(np.arange(1, 21), 30)
    rng = np.random.default_rng(13)
    errors = rng.normal(0, 0.01, horizons.size) * horizons**0.7

    log_fit = horizon_conformal(errors, horizons, level=0.9, max_horizon=60)
    lin_fit = horizon_conformal(errors, horizons, level=0.9, max_horizon=60, fit="linear")
    assert not np.allclose(log_fit.half_width, lin_fit.half_width)
    # Linear least squares is dominated by the far end, where the quantiles are
    # largest, so it fits the tail more closely and the near horizon less.
    assert lin_fit.half_width[-1] != log_fit.half_width[-1]

    with pytest.raises(ValueError, match="fit must be"):
        horizon_conformal(errors, horizons, level=0.9, fit="spline")


def test_horizon_band_refuses_when_there_is_nothing_to_fit():
    with pytest.raises(ValueError, match="at least two horizons"):
        horizon_conformal(np.zeros(20), np.ones(20, dtype=int), level=0.9)


def test_a_pooled_band_is_wrong_at_both_ends_when_error_grows():
    """Why horizon_conformal exists: pooling is a compromise, not a summary."""
    rng = np.random.default_rng(5)
    horizons = np.repeat(np.arange(1, 21), 40)
    errors = rng.normal(0, 0.01, horizons.size) * horizons

    pooled = split_conformal(errors, level=0.9)
    aware = horizon_conformal(errors, horizons, level=0.9)

    assert aware.half_width[0] < pooled.half_width[0]  # too wide early
    assert aware.half_width[-1] > pooled.half_width[0]  # too narrow late


def test_adaptive_conformal_walks_back_to_its_target():
    """Start it badly calibrated and check the level moves the right way."""
    rng = np.random.default_rng(7)
    # Calibrated on a quiet stretch, deployed on a noisy one: the band starts
    # far too narrow, which is the distribution shift ACI is for.
    aci = AdaptiveConformal(rng.normal(0, 0.01, 300), level=0.9, gamma=0.01)
    covered = []
    for y in rng.normal(0, 0.05, 600):
        aci.interval(0.0)
        covered.append(aci.update(y))

    early, late = float(np.mean(covered[:20])), float(np.mean(covered[-200:]))
    assert early < 0.60  # it really did start wrong
    assert late > 0.85  # and it really did walk back
    assert len(aci.history) == 600
    # A fixed band calibrated on the same quiet stretch never recovers: it
    # delivers about 27 % over the whole run. That gap is the point of ACI.
    fixed = split_conformal(np.random.default_rng(7).normal(0, 0.01, 300), level=0.9)
    assert fixed.half_width[0] < 0.05


def test_adaptive_conformal_requires_an_interval_before_an_update():
    aci = AdaptiveConformal(np.linspace(0.01, 0.5, 100), level=0.9)
    with pytest.raises(RuntimeError, match="call interval"):
        aci.update(0.0)


def test_rolling_origin_residuals_refit_and_never_look_forward():
    """The residuals must be reproducible from history alone, at every origin."""
    y = np.concatenate([np.linspace(1.0, 0.9, 60), np.linspace(0.9, 0.6, 60)])
    seen = []

    def refit(history, horizon):
        seen.append(len(history))
        slope = (history[-1] - history[-10]) / 9.0
        return history[-1] + slope * np.arange(1, horizon + 1)

    residuals, horizons = rolling_origin_residuals(refit, y, step=10, min_train=40)
    assert residuals.size == horizons.size > 0
    assert horizons.min() == 1
    # Every call saw only history, and no origin reached past the series.
    assert all(0 < n < len(y) for n in seen)
    assert seen == sorted(seen)
    # And the band built from them is usable.
    band = split_conformal(residuals, level=0.9)
    assert np.isfinite(band.half_width[0])


def test_rolling_origin_residuals_reject_a_forecaster_that_returns_the_wrong_length():
    y = np.linspace(1.0, 0.5, 100)
    with pytest.raises(ValueError, match="exactly the number of steps"):
        rolling_origin_residuals(lambda h, n: np.zeros(n + 1), y, step=20, min_train=40)


def test_band_to_interval_is_unvalidated_until_coverage_is_measured():
    """A conformal guarantee is not a measurement of this deployment."""
    band = split_conformal(np.random.default_rng(0).normal(0, 0.05, 200), level=0.9)
    interval = band.to_interval(np.zeros(10))
    assert interval.method == "split_conformal"
    assert not interval.is_validated
    assert interval.empirical_coverage is None

    measured = band.to_interval(np.zeros(10), empirical_coverage=0.88)
    assert measured.is_validated
    assert measured.coverage_error() == pytest.approx(-0.02)


def test_horizon_band_refuses_to_be_applied_past_its_horizon():
    rng = np.random.default_rng(2)
    horizons = np.repeat(np.arange(1, 11), 30)
    band = horizon_conformal(rng.normal(0, 0.02, horizons.size), horizons, level=0.9)
    with pytest.raises(ValueError, match="past the horizon"):
        band.apply(np.zeros(50))


def test_conformal_band_rejects_a_negative_half_width():
    with pytest.raises(ValueError, match="non-negative"):
        ConformalBand(half_width=np.array([-1.0]), level=0.9, method="x", n_calibration=1)
