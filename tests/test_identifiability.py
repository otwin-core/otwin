"""Identifiability: the fourth ground for refusal.

Every replication result was decided by whether a fitted coefficient was
determined by the data. These tests pin the three failure modes the check is
built to catch, and the manifest/envelope contract that lets a twin refuse on
them.
"""

from __future__ import annotations

import numpy as np
import pytest

from otwin.advise import Envelope
from otwin.estimate import IdentifiabilityReport, identifiability
from otwin.interfaces import Provenance, TwinManifest


def _manifest(**kw):
    base = dict(
        name="t",
        model_class="empirical_law",
        model_kind="two_term_fade",
        n_states=1,
        n_inputs=0,
        provenance=Provenance.now("0.0.0"),
        parameters={"c1": 0.01, "c2": 0.002},
        estimated=("c1", "c2"),
        validation=TwinManifest.validated_by("rolling_origin", horizon=100),
        calibration=TwinManifest.calibrated_by("split_conformal", empirical_coverage=0.9),
    )
    base.update(kw)
    return TwinManifest(**base)


# --------------------------------------------------------------- collinearity
def test_proportional_columns_are_not_identified():
    """Two powers of n on a short window: the data fix the sum, not the split."""
    n = np.arange(1.0, 101.0)
    X = np.column_stack([n**0.5, n**0.6])
    y = 0.01 * n**0.5 + 0.002 * n**0.6
    rep = identifiability(X, y, names=("c1", "c2"), n_boot=50)
    assert isinstance(rep, IdentifiabilityReport)
    assert not rep.identified
    assert all(
        "reproduced from the others" in r for p in rep.parameters for r in p.reasons
    )
    assert rep.verdicts == {"c1": False, "c2": False}


def test_separated_columns_are_identified():
    """A slow and a genuinely fast term over a long record are told apart."""
    rng = np.random.default_rng(0)
    n = np.arange(1.0, 1001.0)
    X = np.column_stack([n**0.5, n**2.0])
    y = 0.01 * n**0.5 + 1e-7 * n**2 + rng.normal(0, 0.005, n.size)
    rep = identifiability(X, y, names=("c1", "c2"), n_boot=100, nonneg=True)
    assert rep.identified
    assert rep.condition_number < 10


# ---------------------------------------------------------------------- span
def test_time_constant_longer_than_record_is_not_identified():
    """Kern–Seaton: τ cannot be seen from a record shorter than τ."""
    t = np.linspace(0, 180, 60)
    X = (1 - np.exp(-t / 260.0)).reshape(-1, 1)
    y = 5e-4 * X[:, 0]
    rep = identifiability(
        X, y, names=("R_inf",), span=180.0, time_constants={"R_inf": 260.0}, n_boot=0
    )
    p = rep.parameters[0]
    assert not p.identified
    assert p.span_ratio == pytest.approx(180 / 260)
    assert any("has not been observed" in r for r in p.reasons)


def test_span_check_passes_when_record_covers_the_time_constant():
    t = np.linspace(0, 900, 60)
    X = (1 - np.exp(-t / 260.0)).reshape(-1, 1)
    rep = identifiability(
        X,
        5e-4 * X[:, 0],
        names=("R_inf",),
        span=900.0,
        time_constants={"R_inf": 260.0},
        n_boot=0,
    )
    assert rep.identified


# ----------------------------------------------------------------- stability
def test_three_points_per_unit_fails_the_bootstrap():
    """The RWTH case: a second coefficient fitted to three tests per system."""
    rng = np.random.default_rng(1)
    rows, ys, grp = [], [], []
    for s in range(12):
        for t in rng.uniform(0.5, 6.0, 3):
            rows.append([t, t**2.5])
            ys.append(0.02 * t + rng.normal(0, 0.03))
            grp.append(s)
    rep = identifiability(
        np.array(rows),
        np.array(ys),
        names=("a", "b"),
        groups=grp,
        nonneg=True,
        n_boot=200,
    )
    b = rep.parameters[1]
    assert not b.identified
    assert (b.cv is not None and b.cv > rep.thresholds["max_cv"]) or not b.sign_stable


def test_bootstrap_resamples_units_not_rows():
    """With groups, resampling is by unit; the report says how many."""
    rng = np.random.default_rng(2)
    t = rng.uniform(0, 5, 60)
    grp = np.repeat(np.arange(20), 3)
    rep = identifiability(
        t.reshape(-1, 1), 0.02 * t + rng.normal(0, 0.01, 60), groups=grp, n_boot=50
    )
    assert rep.n_units == 20 and rep.n_rows == 60


def test_report_serialises_and_prints():
    n = np.arange(1.0, 51.0)
    rep = identifiability(n.reshape(-1, 1), 0.01 * n, names=("c",), n_boot=20)
    d = rep.to_dict()
    assert d["parameters"][0]["name"] == "c" and isinstance(d["identified"], bool)
    assert "identifiability" in str(rep)


def test_shape_mismatch_is_a_programming_error():
    with pytest.raises(ValueError):
        identifiability(np.ones((5, 2)), np.ones(4))


# ------------------------------------------------------------------ manifest
def test_identified_by_requires_booleans():
    with pytest.raises(ValueError):
        TwinManifest.identified_by("bootstrap_over_units", parameters={"c1": 1})


def test_is_identified_is_strict():
    m = _manifest()
    assert not m.is_identified, "no record means not identified"
    m = _manifest(identification=TwinManifest.identified_by("x", parameters={"c1": True}))
    assert not m.is_identified, "every estimated parameter needs a verdict"
    m = _manifest(
        identification=TwinManifest.identified_by(
            "x", parameters={"c1": True, "c2": False}
        )
    )
    assert not m.is_identified
    m = _manifest(
        identification=TwinManifest.identified_by(
            "x", parameters={"c1": True, "c2": True}
        )
    )
    assert m.is_identified
    # a truthy non-boolean that slipped past the builder (hand-written dict) is not a verdict
    m = _manifest(identification={"method": "x", "parameters": {"c1": True, "c2": 1}})
    assert not m.is_identified


def test_white_box_is_identified_by_construction():
    assert _manifest(estimated=()).is_identified


def test_identification_round_trips_through_json(tmp_path):
    m = _manifest(
        identification=TwinManifest.identified_by(
            "x", parameters={"c1": True, "c2": True}
        )
    )
    p = m.save(tmp_path / "m.json")
    back = TwinManifest.load(p)
    assert back.is_identified and back.identification == m.identification


# ------------------------------------------------------------------ envelope
def test_envelope_refuses_unidentified_parameter_by_name():
    m = _manifest(
        identification=TwinManifest.identified_by(
            "x", parameters={"c1": True, "c2": False}
        )
    )
    env = Envelope(max_horizon=100, requires_identified=True)
    v = env.check(horizon=50, manifest=m)
    assert not v
    b = [x for x in v.breaches if x.kind == "identification"]
    assert len(b) == 1 and "c2" in b[0].detail and "c1" not in b[0].detail.split(":")[1]


def test_envelope_refuses_when_identification_never_recorded():
    env = Envelope(max_horizon=100, requires_identified=True)
    v = env.check(horizon=50, manifest=_manifest())
    assert not v and any("never recorded" in b.detail for b in v.breaches)


def test_envelope_answers_when_identified_and_default_is_lenient():
    m = _manifest(
        identification=TwinManifest.identified_by(
            "x", parameters={"c1": True, "c2": True}
        )
    )
    strict = Envelope(max_horizon=100, requires_identified=True)
    assert strict.check(horizon=50, manifest=m)
    assert any("identified" in c for c in strict.check(horizon=50, manifest=m).checked)
    lenient = Envelope(max_horizon=100)
    assert lenient.check(horizon=50, manifest=_manifest()), (
        "default is off for older manifests"
    )


def test_report_feeds_manifest_and_envelope_end_to_end():
    """The whole chain: fit -> report -> manifest -> refusal, on the early-life two-term law."""
    n = np.arange(1.0, 101.0)
    X = np.column_stack([n**0.5, n**0.6])
    rep = identifiability(
        X, 0.01 * n**0.5 + 0.002 * n**0.6, names=("c1", "c2"), n_boot=30
    )
    m = _manifest(
        identification=TwinManifest.identified_by(
            "collinearity+bootstrap",
            parameters=rep.verdicts,
            condition_number=rep.condition_number,
        )
    )
    v = Envelope(max_horizon=100, requires_identified=True).check(horizon=80, manifest=m)
    assert not v and "c1, c2" in v.explain()
