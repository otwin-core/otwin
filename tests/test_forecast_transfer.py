"""Leave-one-unit-out transfer validation.

These tests check four things. A held-out unit never reaches its own
calibration: through the mapping ``fit`` receives, through a duplicate of
itself, or numerically, which a closed form checks. Each contrast is recorded
with the right origin, horizon, observation, signed error and membership. The
forecaster sees only the past. The summary is the tranche report from
:func:`otwin.audit.coverage_audit` on the same contrasts.
"""

import json
import subprocess
import sys

import numpy as np
import pytest

from otwin.audit import coverage_audit
from otwin.forecast import TransferValidation, transfer_validation
from otwin.forecast.transfer import _assert_not_self_calibrated


def _fleet(k=4, n=40, seed=0):
    rng = np.random.default_rng(seed)
    return {f"u{i}": float(i) + rng.normal(0.0, 0.1, n) for i in range(k)}


def _mean_fit(half_width=0.3):
    """Predict the pooled calibration mean, with a fixed half-width."""

    def fit(cal):
        mu = float(np.mean(np.concatenate(list(cal.values()))))

        def forecaster(history, horizon):
            p = np.full(horizon, mu)
            return p, p - half_width, p + half_width

        return forecaster

    return fit


# ------------------------------------------------- no self-calibration


def test_fit_never_receives_the_held_out_unit():
    fleet = _fleet()
    seen = []

    def fit(cal):
        seen.append(tuple(cal))
        return _mean_fit()(cal)

    tv = transfer_validation(fleet, fit, [0, 4], level=0.9)
    ids = list(fleet)
    assert seen == [tuple(u for u in ids if u != h) for h in ids]
    assert tv.calibration_units == {h: tuple(u for u in ids if u != h) for h in ids}


def test_units_run_one_after_another_in_order():
    order = []

    def fit(cal):
        missing = [u for u in ("a", "b", "c") if u not in cal]
        order.append(missing[0])
        return _mean_fit()(cal)

    fleet = {u: np.arange(20.0) + i for i, u in enumerate("abc")}
    transfer_validation(fleet, fit, [0, 2], level=0.9)
    assert order == ["a", "b", "c"]


def test_leave_one_out_mean_matches_its_closed_form():
    """If the held-out unit leaked into its mean, the error would be off.

    Unit i sits at i squared. The pooled mean over the others is
    (sum - own) / (K - 1). With the unit included, it would be sum / K
    instead. No level equals the fleet mean (6), so the two always differ.
    """
    k, n = 5, 30
    fleet = {i: np.full(n, float(i**2)) for i in range(k)}
    tv = transfer_validation(fleet, _mean_fit(), [0, 1], level=0.9)
    c = tv.contrasts
    total = sum(fleet[i].mean() for i in range(k))
    for i in range(k):
        rows = c.unit == i
        expected_pred = (total - fleet[i].mean()) / (k - 1)
        np.testing.assert_allclose(c.prediction[rows], expected_pred, rtol=1e-12)
        assert not np.allclose(c.prediction[rows], total / k)


def test_the_invariant_check_fails_on_each_kind_of_breach():
    a, b, c = np.zeros(5), np.ones(5), np.full(5, 2.0)
    ids = ["a", "b", "c"]
    _assert_not_self_calibrated("a", {"b": b, "c": c}, ids, a)  # clean
    with pytest.raises(AssertionError, match="in its own calibration set"):
        _assert_not_self_calibrated("a", {"a": a, "b": b, "c": c}, ids, a)
    with pytest.raises(AssertionError, match="expected exactly the other units"):
        _assert_not_self_calibrated("a", {"b": b}, ids, a)
    with pytest.raises(AssertionError, match="shares memory"):
        _assert_not_self_calibrated("a", {"b": a[:3], "c": c}, ids, a)


def test_the_invariant_check_survives_python_O():
    """A bare ``assert`` would be stripped by -O; this check must not be."""
    code = (
        "import numpy as np\n"
        "from otwin.forecast.transfer import _assert_not_self_calibrated as f\n"
        "a = np.zeros(3)\n"
        "try:\n"
        "    f('a', {'a': a}, ['a', 'b'], a)\n"
        "except AssertionError:\n"
        "    print('raised')\n"
    )
    out = subprocess.run(
        [sys.executable, "-O", "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "raised"


def test_the_same_array_under_two_ids_is_rejected():
    x = np.arange(30.0)
    with pytest.raises(ValueError, match="'a' and 'b' are the same data"):
        transfer_validation({"a": x, "b": x, "c": x + 1}, _mean_fit(), [0, 2], level=0.9)


def test_overlapping_views_are_rejected():
    base = np.arange(50.0)
    fleet = {"a": base[:30], "b": base[20:], "c": base[:10] * 7}
    with pytest.raises(ValueError, match="'a' and 'b' are the same data"):
        transfer_validation(fleet, _mean_fit(), [0, 2], level=0.9)


def test_equal_data_under_two_ids_is_rejected():
    with pytest.raises(ValueError, match="same data"):
        transfer_validation(
            [np.arange(30.0), np.arange(30.0), np.ones(30)],
            _mean_fit(),
            [0, 2],
            level=0.9,
        )


def test_fit_and_forecaster_get_read_only_copies():
    fleet = _fleet(k=3)
    before = {u: s.copy() for u, s in fleet.items()}

    def fit(cal):
        for s in cal.values():
            with pytest.raises(ValueError):
                s[0] = 99.0

        def forecaster(history, horizon):
            with pytest.raises(ValueError):
                history[0] = 99.0
            p = np.zeros(horizon)
            return p, p - 1, p + 1

        return forecaster

    transfer_validation(fleet, fit, [0, 2], level=0.9, min_history=5, step=10)
    for u in fleet:
        np.testing.assert_array_equal(fleet[u], before[u])


# --------------------------------------------------------- the contrasts


def test_forecaster_sees_exactly_the_past():
    fleet = {u: np.arange(25.0) * (i + 1) for i, u in enumerate("xyz")}
    calls = []

    def fit(cal):
        held = next(u for u in "xyz" if u not in cal)

        def forecaster(history, horizon):
            origin = len(history)
            np.testing.assert_array_equal(history, fleet[held][:origin])
            calls.append((held, origin, horizon))
            p = np.zeros(horizon)
            return p, p, p

        return forecaster

    transfer_validation(fleet, fit, [0, 5], level=0.9, min_history=8, step=6)
    # origins 8, 14, 20; horizon truncated to what is left: 25 - 20 = 5
    assert calls == [(u, o, 5) for u in "xyz" for o in (8, 14, 20)]


def test_contrast_columns():
    y = {"a": np.arange(10.0), "b": np.arange(10.0) + 100}

    def fit(cal):
        def forecaster(history, horizon):
            p = np.full(horizon, history[-1])  # persistence
            return p, p - 1.5, p + 1.5

        return forecaster

    tv = transfer_validation(y, fit, [0, 3], level=0.9, min_history=6, step=2)
    c = tv.contrasts
    # origins 6 and 8; horizons 3 and then 2 (truncated at the end)
    a = c.unit == "a"
    assert c.origin[a].tolist() == [6, 6, 6, 8, 8]
    assert c.horizon[a].tolist() == [1, 2, 3, 1, 2]
    assert c.observed[a].tolist() == [6.0, 7.0, 8.0, 8.0, 9.0]
    assert c.prediction[a].tolist() == [5.0, 5.0, 5.0, 7.0, 7.0]
    assert c.error[a].tolist() == [1.0, 2.0, 3.0, 1.0, 2.0]
    assert c.covered[a].tolist() == [True, False, False, True, False]
    assert len(c) == 10
    assert tv.n_contrasts_per_unit == {"a": 5, "b": 5}


def test_a_range_edge_counts_as_covered():
    """Each series is a line; the forecaster's upper edge lies exactly on it."""
    y = {"a": np.arange(10.0), "b": np.arange(10.0) * 2}

    def fit(cal):
        def forecaster(history, horizon):
            slope = history[-1] - history[-2]
            on_the_line = history[-1] + slope * np.arange(1, horizon + 1)
            return on_the_line - 1, on_the_line - 2, on_the_line

        return forecaster

    tv = transfer_validation(y, fit, [0, 2], level=0.9, min_history=2)
    np.testing.assert_array_equal(tv.contrasts.observed, tv.contrasts.upper)
    assert tv.contrasts.covered.all()


def test_sequence_units_get_integer_ids():
    tv = transfer_validation(
        [np.arange(20.0), np.arange(20.0) + 1], _mean_fit(), [0, 2], level=0.9
    )
    assert set(tv.contrasts.unit) == {0, 1}
    assert tv.calibration_units == {0: (1,), 1: (0,)}


def test_a_unit_too_short_for_any_origin_gives_zero_contrasts():
    fleet = {
        "long": np.arange(30.0),
        "short": np.arange(3.0) + 50,
        "mid": np.arange(30.0) + 9,
    }
    tv = transfer_validation(fleet, _mean_fit(), [0, 2], level=0.9, min_history=5)
    assert tv.n_contrasts_per_unit["short"] == 0
    assert "short" not in set(tv.contrasts.unit)
    assert "short" in tv.calibration_units["long"]  # still used to calibrate others


# ----------------------------------------------------------- the summary


def test_summary_is_the_tranche_report_on_the_contrasts():
    fleet = _fleet(k=5, n=60, seed=3)
    tv = transfer_validation(fleet, _mean_fit(1.5), [0, 2, 5], level=0.8)
    c = tv.contrasts
    again = coverage_audit(
        c.observed,
        c.prediction,
        c.lower,
        c.upper,
        level=0.8,
        horizons=c.horizon,
        tranches=[0, 2, 5],
    )
    assert tv.audit == again
    assert tv.overall_coverage == pytest.approx(c.covered.mean())
    assert tv.median_bias == pytest.approx(np.median(c.error))
    assert list(tv.tranche_coverage) == ["(0, 2]", "(2, 5]"]
    h = c.horizon
    assert tv.tranche_coverage["(0, 2]"] == pytest.approx(c.covered[h <= 2].mean())
    assert tv.tranche_coverage["(2, 5]"] == pytest.approx(c.covered[h > 2].mean())


def test_transfer_exposes_a_unit_the_fleet_does_not_represent():
    """One unit runs well above the rest: its contrasts are the misses."""
    rng = np.random.default_rng(5)
    fleet = {f"u{i}": 10 + rng.normal(0, 0.2, 50) for i in range(5)}
    fleet["odd"] = 13 + rng.normal(0, 0.2, 50)
    tv = transfer_validation(fleet, _mean_fit(1.0), [0, 3], level=0.9)
    c = tv.contrasts
    assert c.covered[c.unit == "odd"].mean() == 0.0
    assert np.median(c.error[c.unit == "odd"]) > 2.0


def test_a_thin_tranche_is_refused_with_its_count():
    fleet = _fleet(k=3, n=12)
    tv = transfer_validation(
        fleet, _mean_fit(), [0, 1, 11], level=0.9, min_history=10, min_contrasts=7
    )
    # origins 10, 11: horizon 1 has 3 units x 2 origins = 6 contrasts
    assert tv.tranche_coverage["(0, 1]"] is None
    refused = tv.audit.tranches[0]
    assert refused.refusal == "6 contrasts; the minimum is 7"


def test_json():
    tv = transfer_validation(_fleet(), _mean_fit(), [0, 2, 4], level=0.9)
    d = json.loads(json.dumps(tv.to_dict(), allow_nan=False))
    assert d["section"] == "transfer_validation"
    assert d["calibration_units"]["u0"] == ["u1", "u2", "u3"]
    assert d["coverage"]["boundaries"] == [0.0, 2.0, 4.0]
    cols = json.loads(json.dumps(tv.contrasts.to_dict(), allow_nan=False))
    assert set(cols) == {
        "unit",
        "origin",
        "horizon",
        "observed",
        "prediction",
        "lower",
        "upper",
        "error",
        "covered",
    }
    assert len(cols["unit"]) == d["n_contrasts"]
    assert isinstance(tv, TransferValidation)


# ---------------------------------------------------- errors in the call


def _forecaster_returning(value):
    def fit(cal):
        return lambda history, horizon: value(horizon)

    return fit


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"units": {"a": np.arange(20.0)}}, "at least two units"),
        ({"units": [np.zeros((5, 2)), np.ones((5, 2))]}, "1-D"),
        ({"units": [np.arange(20.0), np.r_[np.arange(19.0), np.nan]]}, "NaN or Inf"),
        ({"horizon_levels": [3]}, "at least two"),
        ({"horizon_levels": [0, 2, 2]}, "strictly increasing"),
        ({"horizon_levels": [0, 0.5]}, "at least 1 step"),
        ({"min_history": 0}, "at least 1"),
        ({"step": 0}, "at least 1"),
        ({"min_history": 100}, "no unit is longer"),
        (
            {"fit": _forecaster_returning(lambda h: None)},
            r"must return \(prediction, lower, upper\)",
        ),
        (
            {
                "fit": _forecaster_returning(
                    lambda h: (np.zeros(h), np.zeros(h), np.zeros(h + 1))
                )
            },
            "steps for a horizon",
        ),
        (
            {"fit": _forecaster_returning(lambda h: (np.full(h, np.nan),) * 3)},
            "NaN or Inf",
        ),
        (
            {
                "fit": _forecaster_returning(
                    lambda h: (np.zeros(h), np.ones(h), np.zeros(h))
                )
            },
            "lower > upper",
        ),
    ],
)
def test_bad_inputs_raise(kwargs, match):
    args = {
        "units": [np.arange(20.0), np.arange(20.0) + 1],
        "fit": _mean_fit(),
        "horizon_levels": [0, 3],
        "level": 0.9,
    }
    args.update(kwargs)
    with pytest.raises(ValueError, match=match):
        transfer_validation(**args)
