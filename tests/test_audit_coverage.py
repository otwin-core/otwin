"""Coverage audit, overall and by horizon tranche.

These tests check five things. The default report is one overall row and no
tranches. Tranches split the contrasts by horizon on ``(lo, hi]``, and the
count of contrasts outside every tranche is reported. Each row's coverage,
Clopper-Pearson interval, median signed error and mean width match a hand
computation. A row with fewer contrasts than the minimum is refused with the
count and carries no number. The JSON and HTML sections have stable shapes.
"""

import json

import numpy as np
import pytest
from scipy.stats import beta

from otwin.audit import CoverageAudit, coverage_audit, default_min_contrasts


def _horizon_growing_errors(seed=0, n_origins=200, steps=24):
    """A band with a fixed half-width over errors that grow like sqrt(h)."""
    rng = np.random.default_rng(seed)
    h = np.tile(np.arange(1, steps + 1), n_origins).astype(float)
    pred = np.zeros(h.size)
    obs = rng.normal(0.0, 0.5 * np.sqrt(h))
    half = np.full(h.size, 1.645 * 0.5 * np.sqrt(steps / 2))  # right on average only
    return obs, pred, pred - half, pred + half, h


# -------------------------------------------------------------- the default


def test_default_is_the_single_overall_row():
    obs, pred, lo, up, h = _horizon_growing_errors()
    a = coverage_audit(obs, pred, lo, up, level=0.9)
    assert isinstance(a, CoverageAudit)
    assert a.tranches is None and a.boundaries is None and a.n_outside is None
    assert a.overall.label == "all" and a.overall.n_contrasts == obs.size


def test_horizons_alone_do_not_switch_tranches_on():
    obs, pred, lo, up, h = _horizon_growing_errors()
    a = coverage_audit(obs, pred, lo, up, level=0.9, horizons=h)
    assert a.tranches is None


def test_overall_row_is_the_same_with_and_without_tranches():
    obs, pred, lo, up, h = _horizon_growing_errors()
    plain = coverage_audit(obs, pred, lo, up, level=0.9)
    split = coverage_audit(obs, pred, lo, up, level=0.9, horizons=h, tranches=[0, 8, 24])
    assert plain.overall == split.overall


# ---------------------------------------------------------- the row numbers


def test_row_numbers_match_a_hand_computation():
    obs = np.array([0.0, 1.0, 2.0, 3.0, 10.0, -5.0, 0.5, 0.2, 0.1, 0.0, 4.0, 2.0])
    pred = np.array([0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0])
    lo = pred - 2.0
    up = pred + np.array([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0])
    a = coverage_audit(obs, pred, lo, up, level=0.8, min_contrasts=12)
    r = a.overall
    covered = (lo <= obs) & (obs <= up)
    k, n = int(covered.sum()), obs.size
    assert (r.n_covered, r.n_contrasts) == (k, n) == (9, 12)
    assert r.coverage == pytest.approx(9 / 12)
    assert r.ci_low == pytest.approx(beta.ppf(0.025, k, n - k + 1))
    assert r.ci_high == pytest.approx(beta.ppf(0.975, k + 1, n - k))
    assert r.median_error == pytest.approx(np.median(obs - pred))
    assert r.mean_width == pytest.approx(np.mean(up - lo))


def test_the_ends_of_the_range_count_as_covered():
    obs = np.array([-1.0, 1.0] * 10)
    a = coverage_audit(obs, np.zeros(20), -np.ones(20), np.ones(20), level=0.9)
    assert a.overall.coverage == 1.0


def test_interval_ends_are_exact_at_zero_and_full_coverage():
    y = np.zeros(30)
    full = coverage_audit(y, y, y - 1, y + 1, level=0.9).overall
    assert full.ci_high == 1.0
    assert full.ci_low == pytest.approx(0.025 ** (1 / 30))
    none = coverage_audit(y, y, y + 1, y + 2, level=0.9).overall
    assert none.ci_low == 0.0 and none.coverage == 0.0


def test_bias_is_median_of_observed_minus_prediction():
    """A positive bias means the forecast runs low; the median ignores one outlier."""
    obs = np.full(21, 2.0)
    obs[0] = 1000.0
    a = coverage_audit(obs, np.ones(21), np.zeros(21), np.full(21, 3.0), level=0.9)
    assert a.overall.median_error == 1.0


def test_verdicts():
    y = np.zeros(200)
    wide = coverage_audit(y, y, y - 1, y + 1, level=0.9).overall
    assert wide.verdict == "wider than stated"  # 100 % covered is not a success
    narrow = coverage_audit(y, y, y + 1, y + 2, level=0.9).overall
    assert narrow.verdict == "narrower than stated"
    hit = np.r_[np.zeros(180), np.full(20, 5.0)]  # 90 % exactly
    ok = coverage_audit(hit, y, y - 1, y + 1, level=0.9).overall
    assert ok.verdict == "consistent with stated"


def test_confidence_changes_only_the_interval():
    obs, pred, lo, up, _ = _horizon_growing_errors()
    a95 = coverage_audit(obs, pred, lo, up, level=0.9).overall
    a99 = coverage_audit(obs, pred, lo, up, level=0.9, confidence=0.99).overall
    assert a99.coverage == a95.coverage
    assert a99.ci_low < a95.ci_low and a99.ci_high > a95.ci_high


# ------------------------------------------------------------------ tranches


def test_tranches_reveal_what_the_overall_number_hides():
    """Calibrated on the average horizon: too wide early, too narrow late."""
    obs, pred, lo, up, h = _horizon_growing_errors()
    a = coverage_audit(obs, pred, lo, up, level=0.9, horizons=h, tranches=[0, 6, 18, 24])
    early, middle, late = a.tranches
    assert early.verdict == "wider than stated"
    assert late.verdict == "narrower than stated"
    assert early.coverage > a.overall.coverage > late.coverage


def test_tranche_boundaries_are_open_below_and_closed_above():
    h = np.array([1, 2, 3, 4, 5, 6] * 10, dtype=float)
    y = np.zeros(h.size)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 3, 6])
    assert [t.label for t in a.tranches] == ["(0, 3]", "(3, 6]"]
    assert [t.n_contrasts for t in a.tranches] == [30, 30]
    assert [(t.lo, t.hi) for t in a.tranches] == [(0.0, 3.0), (3.0, 6.0)]


def test_contrasts_outside_every_tranche_are_counted_not_dropped_silently():
    h = np.arange(1.0, 41.0)
    y = np.zeros(40)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[10, 30])
    assert a.tranches[0].n_contrasts == 20  # 11 ... 30
    assert a.n_outside == 20  # 1 ... 10 and 31 ... 40
    assert a.overall.n_contrasts == 40


def test_horizons_in_time_not_steps():
    h = np.tile([0.5, 1.5, 2.5, 3.5], 10)
    y = np.zeros(h.size)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 2, 4])
    assert [t.n_contrasts for t in a.tranches] == [20, 20]


# ------------------------------------------------------------------ refusal


def test_default_minimum_follows_the_level():
    assert default_min_contrasts(0.9) == 10
    assert default_min_contrasts(0.95) == 20
    assert default_min_contrasts(0.8) == 5
    assert default_min_contrasts(0.5) == 2


def test_a_thin_tranche_is_refused_with_its_count():
    h = np.r_[np.ones(40), np.full(7, 2.0)]
    y = np.zeros(h.size)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 1, 2])
    thick, thin = a.tranches
    assert thick.answered and thick.n_contrasts == 40
    assert not thin.answered
    assert thin.refusal == "7 contrasts; the minimum is 10"
    assert thin.n_contrasts == 7 and thin.n_required == 10
    for field in ("n_covered", "coverage", "ci_low", "ci_high"):
        assert getattr(thin, field) is None, field
    for field in ("median_error", "mean_width", "verdict"):
        assert getattr(thin, field) is None, field


def test_a_stated_minimum_is_used_as_given():
    h = np.r_[np.ones(40), np.full(30, 2.0)]
    y = np.zeros(h.size)
    a = coverage_audit(
        y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 1, 2], min_contrasts=35
    )
    assert a.min_contrasts == 35
    assert a.tranches[0].answered
    assert a.tranches[1].refusal == "30 contrasts; the minimum is 35"
    low = coverage_audit(y[:3], y[:3], y[:3] - 1, y[:3] + 1, level=0.9, min_contrasts=3)
    assert low.overall.answered


def test_the_overall_row_is_held_to_the_same_minimum():
    y = np.zeros(4)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9)
    assert a.overall.refusal == "4 contrasts; the minimum is 10"


def test_an_empty_tranche_and_a_single_contrast_read_correctly():
    h = np.r_[np.ones(20), [5.0]]
    y = np.zeros(h.size)
    a = coverage_audit(y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 1, 2, 5])
    assert a.tranches[1].refusal == "0 contrasts; the minimum is 10"
    assert a.tranches[2].refusal == "1 contrast; the minimum is 10"


# ------------------------------------------------------- errors in the call


def _base(**kw):
    y = np.zeros(20)
    args = dict(observed=y, prediction=y, lower=y - 1, upper=y + 1, level=0.9)
    args.update(kw)
    return args


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"observed": np.zeros(19)}, "same length"),
        ({"upper": np.r_[np.full(19, 1.0), np.nan]}, "upper contains NaN"),
        ({"lower": np.ones(20), "upper": np.zeros(20)}, "lower exceeds upper at 20"),
        ({"tranches": [0, 1]}, "tranches need horizons"),
        ({"tranches": [0, 1], "horizons": np.ones(19)}, "horizons must be the same"),
        ({"tranches": [1], "horizons": np.ones(20)}, "at least two boundaries"),
        ({"tranches": [0, 2, 2], "horizons": np.ones(20)}, "strictly increasing"),
        ({"min_contrasts": 0}, "at least 1"),
        ({"level": 1.0}, r"level must be"),
        ({"confidence": 0.0}, r"confidence must be"),
    ],
)
def test_bad_inputs_raise(kwargs, match):
    with pytest.raises(ValueError, match=match):
        coverage_audit(**_base(**kwargs))


# --------------------------------------------------------- report sections


def test_json_without_tranches_keeps_the_tranche_keys_as_null():
    d = coverage_audit(**_base()).to_dict()
    json.dumps(d, allow_nan=False)
    assert d["section"] == "coverage"
    assert d["tranches"] is None and d["boundaries"] is None and d["n_outside"] is None
    assert d["overall"]["n_contrasts"] == 20
    assert "independent" in d["note"]


def test_json_with_tranches_and_a_refusal():
    h = np.r_[np.ones(15), np.full(5, 2.0)]
    d = coverage_audit(**_base(horizons=h, tranches=[0, 1, 2])).to_dict()
    back = json.loads(json.dumps(d, allow_nan=False))
    assert back["boundaries"] == [0.0, 1.0, 2.0]
    assert back["n_outside"] == 0
    first, second = back["tranches"]
    assert first["answered"] is True and first["n_contrasts"] == 15
    assert second["answered"] is False
    assert second["refusal"] == "5 contrasts; the minimum is 10"
    assert second["coverage"] is None and second["n_contrasts"] == 5


def test_html_default_has_one_data_row():
    out = coverage_audit(**_base()).to_html()
    assert out.startswith('<section class="otwin-coverage">') and out.endswith(
        "</section>"
    )
    assert out.count("<tr") == 2  # header + overall
    assert "Coverage of the stated 90 % range" in out
    assert "<script" not in out and "<style" not in out


def test_html_with_tranches_shows_refusals_in_place_of_numbers():
    h = np.r_[np.ones(15), np.full(5, 2.0), [9.0]]
    y = np.zeros(21)
    out = coverage_audit(
        y, y, y - 1, y + 1, level=0.9, horizons=h, tranches=[0, 1, 2]
    ).to_html(heading_level=3)
    assert "<h3>" in out
    assert out.count("<tr") == 4  # header, overall, two tranches
    assert '<tr class="refusal"><td>(1, 2]</td><td>5</td>' in out
    assert "Not computed: 5 contrasts; the minimum is 10." in out
    assert "<p>1 contrast falls outside every tranche;" in out
