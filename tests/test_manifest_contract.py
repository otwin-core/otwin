"""The two keys that decide whether a twin is allowed to answer.

`TwinManifest.is_validated` reads `validation["leakage_free"] is True`, and
`Envelope` reads `calibration["empirical_coverage"]`. Neither name appears in
the attribute documentation of the field it governs, so a manifest built by
hand with `protocol="rolling_origin"` and `picp=0.87` — both perfectly sensible
records of real work — is refused, correctly and silently.

The behaviour is right and stays right. What is tested here is that the refusal
now says which key is missing, and that there is a builder which sets it.
"""

import pytest

import otwin
from otwin.advise import Envelope
from otwin.interfaces import Provenance, TwinManifest


def _manifest(**kwargs):
    return TwinManifest(
        name="fade-A",
        model_class="empirical_law",
        model_kind="battery_soh_fade",
        n_states=1,
        n_inputs=0,
        provenance=Provenance.now(otwin.__version__),
        **kwargs,
    )


def test_validated_by_sets_the_key_is_validated_reads():
    m = _manifest(validation=TwinManifest.validated_by("rolling_origin", theil_u=0.64))
    assert m.is_validated
    assert m.validation["protocol"] == "rolling_origin"
    assert m.validation["theil_u"] == 0.64


def test_a_random_split_cannot_claim_to_be_leakage_free_by_default():
    """The builder must not launder a protocol into a claim it does not support."""
    assert TwinManifest.validated_by("random_split")["leakage_free"] is False
    assert not _manifest(
        validation=TwinManifest.validated_by("random_split")
    ).is_validated
    # An explicit override is still available, because only the caller knows
    # what a protocol named something else actually did.
    assert (
        TwinManifest.validated_by("my_scheme", leakage_free=True)["leakage_free"] is True
    )


def test_calibrated_by_refuses_a_percentage():
    """0.87 and 87 differ by two orders of magnitude and one reads as excellent."""
    with pytest.raises(ValueError, match=r"fraction in \[0, 1\]"):
        TwinManifest.calibrated_by("split_conformal", empirical_coverage=87)
    assert TwinManifest.calibrated_by(
        "split_conformal", empirical_coverage=0.87, level=0.90
    ) == {"method": "split_conformal", "empirical_coverage": 0.87, "level": 0.90}


def test_a_plausible_hand_built_manifest_is_refused_and_told_why():
    """The failure this test exists for: right record, wrong key, useless message."""
    plausible = _manifest(
        validation={"protocol": "rolling_origin", "theil_u": 0.64},
        calibration={"method": "conformal", "picp": 0.87, "level": 0.90},
    )
    env = Envelope(state_bounds=[(0.70, 1.00)], max_horizon=68)
    verdict = env.check(state=[0.85], horizon=40, manifest=plausible, wants_interval=True)

    assert not verdict.answerable
    explanation = verdict.explain()
    assert "leakage_free" in explanation
    assert "empirical_coverage" in explanation
    assert "validated_by" in explanation and "calibrated_by" in explanation
    # The old message claimed the twin had never been validated. It had been;
    # the record just did not say so in the word the check reads.
    assert "never been validated" not in explanation


def test_an_empty_record_still_says_never_validated():
    """Do not lose the plain case while improving the subtle one."""
    bare = _manifest()
    env = Envelope(state_bounds=[(0.70, 1.00)], max_horizon=68)
    explanation = env.check(
        state=[0.85], horizon=40, manifest=bare, wants_interval=True
    ).explain()
    assert "never been validated" in explanation
    assert "never been measured" in explanation


def test_the_builders_produce_a_manifest_the_envelope_accepts():
    built = _manifest(
        validation=TwinManifest.validated_by("rolling_origin", horizon=68, theil_u=0.64),
        calibration=TwinManifest.calibrated_by(
            "split_conformal", empirical_coverage=0.87, level=0.90
        ),
    )
    env = Envelope(state_bounds=[(0.70, 1.00)], max_horizon=68)
    verdict = env.check(state=[0.85], horizon=40, manifest=built, wants_interval=True)
    assert verdict.answerable
    assert "coverage measured at 0.87" in verdict.explain()


def test_builders_survive_a_json_round_trip():
    """A manifest is an interchange format; the keys have to cross the boundary."""
    built = _manifest(
        validation=TwinManifest.validated_by("temporal_holdout"),
        calibration=TwinManifest.calibrated_by("ensemble", empirical_coverage=0.91),
    )
    back = TwinManifest.from_dict(built.to_dict())
    assert back.is_validated
    assert back.calibration["empirical_coverage"] == 0.91
