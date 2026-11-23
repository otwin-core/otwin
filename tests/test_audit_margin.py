"""Margin above a reference curve, and the risk of not delivering it.

These tests check four things. The probability is a count of residuals with no
distribution assumed. The margin at a stated risk keeps its promise on residuals
it has not seen. Too few residuals give a refusal with the count and no number.
The section serialises to JSON and HTML in a form an audit report can embed.
"""

import json

import numpy as np
import pytest

from otwin.audit import DEFAULT_RISK_LEVELS, MarginRisk, margin_risk, min_residuals_for

# ---------------------------------------------------------------- the counting


def test_probability_is_the_share_of_residuals_below_the_margin():
    res = np.array([-3.0, -1.0, 0.0, 2.0, 5.0] * 4)  # n = 20
    r = margin_risk(res, reference=1.0, margins=[-3.0, 0.0, 0.5, 5.0, 6.0])
    assert r.answered
    # strictly below: [-3 -> 0], [0 -> -3,-1], [0.5 -> -3,-1,0], [5 -> all but 5], [6 -> all]
    assert r.n_short.tolist() == [0, 8, 12, 16, 20]
    assert r.n_residuals.tolist() == [20] * 5
    np.testing.assert_allclose(r.probabilities, [0.0, 0.4, 0.6, 0.8, 1.0])


def test_a_residual_equal_to_the_margin_counts_as_delivered():
    """Delivering exactly reference + m keeps the promise of margin m."""
    res = np.full(25, 2.0)
    r = margin_risk(res, reference=0.0, margins=[2.0, np.nextafter(2.0, 3.0)])
    assert r.probabilities.tolist() == [0.0, 1.0]


def test_margins_keep_the_order_they_were_given_in():
    res = np.arange(50.0)
    r = margin_risk(res, 0.0, [30.0, 10.0, 20.0])
    assert r.margins.tolist() == [30.0, 10.0, 20.0]
    assert r.n_short.tolist() == [30, 10, 20]


def test_no_normality_is_assumed():
    """A two-point mixture, which a normal fit gets badly wrong.

    95 % of the time the asset is 10 above the reference, 5 % of the time it
    is 10 below. A normal fit with this sample's mean and standard deviation
    puts the probability of falling short of the reference at about 2 %, under
    half the true value. The count gives 5 %, which is the true value.
    """
    res = np.array([10.0] * 95 + [-10.0] * 5)
    r = margin_risk(res, 100.0, [0.0])
    assert r.probabilities[0] == pytest.approx(0.05)
    mu, sd = res.mean(), res.std()
    from math import erf, sqrt

    normal_says = 0.5 * (1 + erf((0.0 - mu) / (sd * sqrt(2))))
    assert normal_says < 0.025  # the assumption this function refuses to make


def test_probability_is_monotone_in_the_margin():
    rng = np.random.default_rng(3)
    res = rng.standard_t(df=2, size=400)
    margins = np.linspace(-5, 5, 41)
    p = margin_risk(res, 0.0, margins).probabilities
    assert np.all(np.diff(p) >= 0)


# ---------------------------------------------------------- the margin at risk


def test_default_risk_levels_are_five_ten_and_twenty_percent():
    assert DEFAULT_RISK_LEVELS == (0.05, 0.10, 0.20)
    r = margin_risk(np.arange(100.0), 0.0, [0.0])
    assert r.risk_levels == (0.05, 0.10, 0.20)
    assert r.margin_at_risk.size == 3


def test_margin_at_risk_is_the_rank_corrected_order_statistic():
    """floor(risk (n + 1))-th smallest, not the plain sample quantile."""
    res = np.arange(1.0, 101.0)  # n = 100
    r = margin_risk(res, 0.0, [0.0])
    # floor(0.05*101)=5, floor(0.10*101)=10, floor(0.20*101)=20
    assert r.margin_at_risk.tolist() == [5.0, 10.0, 20.0]
    # The plug-in quantile is larger, so it promises more than the data supports.
    assert float(np.quantile(res, 0.05)) > r.margin_at_risk[0]


def test_margin_at_risk_agrees_with_the_probability_table():
    """Feeding the margin back in gives a probability no larger than its risk."""
    rng = np.random.default_rng(11)
    for n in (19, 20, 37, 100, 999):
        res = rng.gamma(2.0, size=n) - 1.0
        r = margin_risk(res, 0.0, [0.0])
        back = margin_risk(res, 0.0, r.margin_at_risk)
        assert np.all(back.probabilities <= np.array(r.risk_levels) + 1e-12), n


def test_margin_at_risk_holds_on_residuals_it_has_not_seen():
    """The finite-sample statement: over many draws, P(next < margin) <= risk.

    For continuous residuals it is exactly j/(n+1): 1/20 at n = 19 and 5 %.
    At n = 30 the plain 5 % sample quantile sits above the 2nd smallest
    residual (risk above 2/31 = 6.5 %); this returns the 1st (1/31 = 3.2 %).
    """
    rng = np.random.default_rng(7)
    trials = 5000
    for n in (19, 30, 60):
        breaks = np.zeros(3)
        for _ in range(trials):
            draw = rng.normal(size=n + 1)
            r = margin_risk(draw[:n], 0.0, [0.0])
            breaks += draw[n] < r.margin_at_risk
        observed = breaks / trials
        # three standard errors of slack on the Monte Carlo estimate
        slack = 3 * np.sqrt(0.2 * 0.8 / trials)
        assert np.all(observed <= np.array(DEFAULT_RISK_LEVELS) + slack), (n, observed)


def test_a_negative_margin_at_risk_means_the_reference_cannot_be_promised():
    res = np.linspace(-5.0, 1.0, 100)  # usually short of the reference
    r = margin_risk(res, 10.0, [0.0])
    assert np.all(r.margin_at_risk < 0)
    assert np.all(r.promised(0.05) < 10.0)


def test_promised_curve_is_reference_plus_margin():
    ref = np.array([100.0, 95.0, 90.0])
    r = margin_risk(np.arange(40.0), ref, [0.0])
    np.testing.assert_allclose(r.promised(0.10), ref + r.margin_at_risk[1])
    with pytest.raises(ValueError, match="not one of the stated levels"):
        r.promised(0.07)


def test_custom_risk_levels():
    r = margin_risk(np.arange(1.0, 201.0), 0.0, [0.0], risk_levels=[0.01, 0.5])
    # floor(0.01*201)=2, floor(0.5*201)=100
    assert r.margin_at_risk.tolist() == [2.0, 100.0]


# ------------------------------------------------------------------ the refusal


def test_minimum_count_per_risk_level():
    assert min_residuals_for(0.05) == 19
    assert min_residuals_for(0.10) == 9
    assert min_residuals_for(0.20) == 4
    # brute force from the definition
    for risk in (0.01, 0.03, 0.05, 0.07, 0.1, 0.2, 0.25, 0.3, 0.5):
        n = min_residuals_for(risk)
        assert int(np.floor(round(risk * (n + 1), 12))) >= 1
        assert int(np.floor(round(risk * n, 12))) < 1


def test_too_few_residuals_is_a_refusal_naming_the_count():
    r = margin_risk(np.arange(18.0), 0.0, [0.0, 1.0])
    assert not r.answered
    assert not r
    assert r.refusal == "18 residuals; at least 19 are needed for a margin at 5 % risk"
    assert (r.n_available, r.n_required) == (18, 19)
    # no number anywhere
    assert r.probabilities is None
    assert r.n_residuals is None
    assert r.n_short is None
    assert r.margin_at_risk is None
    with pytest.raises(ValueError, match="18 residuals"):
        r.promised(0.05)


def test_exactly_the_minimum_is_answered():
    r = margin_risk(np.arange(19.0), 0.0, [0.0])
    assert r.answered
    assert r.margin_at_risk[0] == 0.0  # 1st smallest of 19


def test_stated_minimum_is_honoured_and_named():
    r = margin_risk(np.arange(30.0), 0.0, [0.0], min_residuals=50)
    assert not r.answered
    assert r.refusal == "30 residuals; the stated minimum is 50"
    assert margin_risk(np.arange(50.0), 0.0, [0.0], min_residuals=50).answered


def test_a_stated_minimum_below_what_the_risk_needs_is_raised():
    """Below 19 residuals the 5 % margin is the sample minimum with no guarantee."""
    r = margin_risk(np.arange(10.0), 0.0, [0.0], min_residuals=5)
    assert not r.answered
    assert r.n_required == 19
    assert "at least 19 are needed for a margin at 5 % risk" in r.refusal
    # with only 20 % asked for, 10 residuals are enough
    assert margin_risk(np.arange(10.0), 0.0, [0.0], risk_levels=[0.2]).answered


def test_no_residuals_is_a_refusal_not_an_error():
    r = margin_risk([], 0.0, [0.0])
    assert r.refusal == "0 residuals; at least 19 are needed for a margin at 5 % risk"


def test_one_residual_reads_as_singular():
    assert margin_risk([1.0], 0.0, [0.0]).refusal.startswith("1 residual;")


# --------------------------------------------------------- errors in the call


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"residuals": [np.nan] * 30}, "residuals contain NaN"),
        ({"reference": []}, "reference curve is empty"),
        ({"reference": [1.0, np.inf]}, "reference curve contains"),
        ({"margins": []}, "margins is empty"),
        ({"margins": [np.nan]}, "margins contain"),
        ({"risk_levels": []}, "risk_levels is empty"),
        ({"risk_levels": [0.0]}, r"in \(0, 1\)"),
        ({"risk_levels": [1.0]}, r"in \(0, 1\)"),
    ],
)
def test_bad_inputs_raise(kwargs, match):
    args = {"residuals": np.arange(30.0), "reference": 0.0, "margins": [0.0]}
    args.update(kwargs)
    with pytest.raises(ValueError, match=match):
        margin_risk(**args)


# ------------------------------------------------------------ report section


def test_json_section_round_trips_without_numpy_types():
    r = margin_risk(np.arange(40.0), [1.0, 2.0], [0.0, 5.0])
    d = r.to_dict()
    text = json.dumps(d, allow_nan=False)
    back = json.loads(text)
    assert back["section"] == "margin_risk"
    assert back["answered"] is True
    assert back["refusal"] is None
    assert back["reference"] == [1.0, 2.0]
    assert back["margins"] == [0.0, 5.0]
    assert back["probabilities"] == [0.0, 0.125]
    assert back["n_residuals"] == [40, 40]
    assert back["n_short"] == [0, 5]
    assert [e["risk"] for e in back["margin_at_risk"]] == [0.05, 0.10, 0.20]
    assert [e["margin"] for e in back["margin_at_risk"]] == [1.0, 3.0, 7.0]


def test_json_refusal_carries_counts_and_no_numbers():
    d = margin_risk(np.arange(7.0), 0.0, [0.0]).to_dict()
    json.dumps(d, allow_nan=False)
    assert d["answered"] is False
    assert d["refusal"].startswith("7 residuals")
    assert (d["n_available"], d["n_required"]) == (7, 19)
    for key in ("probabilities", "n_residuals", "n_short", "margin_at_risk"):
        assert d[key] is None, key


def test_html_section_has_both_tables():
    out = margin_risk(np.arange(100.0), 0.0, [0.0, 10.0]).to_html()
    assert out.startswith('<section class="otwin-margin-risk">')
    assert out.endswith("</section>")
    assert out.count("<table>") == 2
    assert "<td>10.0 %</td><td>10</td><td>100</td>" in out
    assert "<tr><td>5 %</td><td>4</td></tr>" in out
    assert "<script" not in out and "<style" not in out


def test_html_refusal_has_no_table():
    out = margin_risk(np.arange(3.0), 0.0, [0.0]).to_html(heading_level=3)
    assert "<h3>" in out
    assert "<table>" not in out
    assert 'class="refusal"' in out and "3 residuals" in out


def test_result_type_is_exported():
    assert isinstance(margin_risk(np.arange(20.0), 0.0, [0.0]), MarginRisk)
