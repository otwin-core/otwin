"""Tests for :mod:`otwin.advise` — the ISO 13374 Advisory Generation block.

The value of this module is entirely in what it refuses. A permissive bug here
is invisible: every request is answered, every answer looks reasonable, and the
only symptom is a confident number about an operating point the model has never
been shown. So the tests below are weighted towards the refusals, and the ones
that assert a request is *admitted* always pair with a neighbouring request
that must be refused — an envelope that says yes to everything passes any test
that only checks the happy path.

The refusal that is easiest to get backwards is ``max_horizon=None``. Read as
"no limit configured" it permits every horizon; read as documented — "no
horizon was ever validated" — it refuses every horizon. That one has its own
test, and it asserts the refusal at both a trivial and an enormous horizon so
that an off-by-one or a truthiness bug cannot satisfy it.
"""

import numpy as np
import pytest

from otwin.advise import Breach, Envelope, OutsideEnvelope, Verdict
from otwin.interfaces import Provenance, TwinManifest

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _manifest(
    validation: dict | None = None, calibration: dict | None = None
) -> TwinManifest:
    """A minimal but real :class:`TwinManifest`.

    The envelope reads its manifest by ``getattr``, so a stub object would pass
    these tests. A real manifest is used instead so that the property the
    validation check depends on — ``is_validated``, which is deliberately
    stricter than truthiness — is the one actually under test.
    """
    return TwinManifest(
        name="bank-A",
        model_class="port_hamiltonian",
        model_kind="battery",
        n_states=2,
        n_inputs=1,
        parameters={"capacity": 40.0},
        provenance=Provenance.now("0.2.0"),
        validation=validation,
        calibration=calibration,
    )


VALIDATED = {
    "leakage_free": True,
    "horizon": 500,
    "state_bounds": [[0.0, 1.0], [280.0, 330.0]],
}
CALIBRATED = {"method": "conformal", "empirical_coverage": 0.94}


# --------------------------------------------------------------------------
# 1. one breach at a time
# --------------------------------------------------------------------------


def test_horizon_beyond_the_validated_limit_is_refused() -> None:
    """A horizon past what was validated is a refusal, and it names both numbers.

    An operator who is told "no" needs to know how far they may go instead;
    a refusal without the limit is an outage, not an advisory. The admitted
    case is asserted alongside so that a check which refused everything — the
    trivially safe bug — cannot pass.
    """
    env = Envelope(max_horizon=500)

    assert env.check(horizon=500)  # the boundary itself was validated
    assert env.check(horizon=499)

    v = env.check(horizon=501)
    assert not v
    assert [b.kind for b in v.breaches] == ["horizon"]
    assert v.breaches[0].observed == 501.0
    assert v.breaches[0].limit == 500.0
    assert "beyond the validated forecast horizon" in str(v.breaches[0])


def test_unvalidated_horizon_refuses_every_horizon() -> None:
    """``max_horizon=None`` means *nothing* was validated, so nothing is answerable.

    This is the inversion that matters. Read as "no configured limit", ``None``
    silently licenses every horizon on exactly the twins that have never been
    validated at all — the failure mode is unbounded and completely silent.

    Both a one-step and a billion-step request are asserted, because a bug that
    compared ``horizon > (self.max_horizon or 0)`` would refuse the large one
    and admit the small one, and a test at a single horizon would miss it.
    """
    env = Envelope(max_horizon=None)

    for horizon in (0, 1, 10, 10**9):
        v = env.check(horizon=horizon)
        assert not v, horizon
        assert [b.kind for b in v.breaches] == ["horizon"], horizon
        assert "no forecast horizon has been validated" in v.breaches[0].detail
        # There is no limit to quote, so none is invented.
        assert v.breaches[0].observed is None
        assert v.breaches[0].limit is None

    # Teeth on the other side: the refusal is about the question, not about the
    # envelope existing. Ask nothing about horizon and nothing is refused.
    assert env.check(state=None, horizon=None)


def test_state_below_and_above_the_identified_range_are_both_refused() -> None:
    """Extrapolation is refused in both directions, and the breach says which.

    A model identified over 0-100 % state of charge has seen nothing at 110 %,
    and nothing at -5 % either. Asserting only the upper side would pass an
    implementation that clipped instead of comparing.
    """
    env = Envelope(state_bounds=[(0.0, 1.0), (280.0, 330.0)])

    assert env.check(state=[0.5, 300.0])
    assert env.check(state=[0.0, 330.0])  # closed interval: the bounds are inside

    low = env.check(state=[-0.01, 300.0])
    assert not low
    assert [b.kind for b in low.breaches] == ["state"]
    assert "state 0 below the identified range" in low.breaches[0].detail
    assert low.breaches[0].observed == pytest.approx(-0.01)
    assert low.breaches[0].limit == 0.0

    high = env.check(state=[0.5, 331.0])
    assert not high
    assert "state 1 above the identified range" in high.breaches[0].detail
    assert high.breaches[0].observed == 331.0
    assert high.breaches[0].limit == 330.0

    # A `None` entry is an explicitly unconstrained state and must be skipped
    # rather than treated as a zero-width bound.
    loose = Envelope(state_bounds=[None, (280.0, 330.0)])
    assert loose.check(state=[1e9, 300.0])
    assert not loose.check(state=[1e9, 400.0])


def test_unvalidated_manifest_is_refused() -> None:
    """A twin with no leakage-free validation on record cannot answer anything.

    ``is_validated`` is stricter than truthiness on purpose — a manifest that
    round-tripped through MATLAB may carry ``1`` or ``"true"`` — and this check
    inherits that strictness. Asserting the near-misses here is what stops the
    envelope from re-introducing a looser test of its own.
    """
    env = Envelope(max_horizon=500)

    good = _manifest(validation=VALIDATED)
    v = env.check(horizon=10, manifest=good)
    assert v
    assert "validated, leakage-free" in v.checked

    for validation in (None, {}, {"leakage_free": False}, {"leakage_free": 1}):
        bad = _manifest(validation=validation)
        v = env.check(horizon=10, manifest=bad)
        assert not v, validation
        assert [b.kind for b in v.breaches] == ["validation"], validation
        assert "never been validated" in v.breaches[0].detail

    # Opting out is possible, and must genuinely bypass the check rather than
    # merely soften the message.
    lenient = Envelope(max_horizon=500, requires_validated=False)
    v = lenient.check(horizon=10, manifest=_manifest(validation=None))
    assert v
    assert not any(b.kind == "validation" for b in v.breaches)
    assert "validated, leakage-free" not in v.checked


def test_calibration_is_required_only_when_an_interval_is_wanted() -> None:
    """Asking for a point forecast must not be blocked by missing calibration.

    The asymmetry is the whole point. An uncalibrated band is a decoration with
    no demonstrated meaning and must be refused; the point forecast underneath
    it is unaffected, and refusing that too would push callers to disable the
    envelope entirely — which loses the interval check as well.
    """
    env = Envelope(max_horizon=500)
    uncalibrated = _manifest(validation=VALIDATED, calibration=None)

    with_band = env.check(horizon=10, manifest=uncalibrated, wants_interval=True)
    assert not with_band
    assert [b.kind for b in with_band.breaches] == ["calibration"]
    assert "never been measured" in with_band.breaches[0].detail

    without_band = env.check(horizon=10, manifest=uncalibrated, wants_interval=False)
    assert without_band
    assert not without_band.breaches
    assert not any("coverage" in c for c in without_band.checked)

    # And a calibrated twin passes with the measured number on the record, so
    # the check is reading real evidence rather than the presence of a key.
    calibrated = _manifest(validation=VALIDATED, calibration=CALIBRATED)
    v = env.check(horizon=10, manifest=calibrated, wants_interval=True)
    assert v
    assert "coverage measured at 0.94" in v.checked

    # A calibration section that exists but never recorded a coverage number is
    # not calibrated. This is the shape a half-finished pipeline writes.
    partial = _manifest(validation=VALIDATED, calibration={"method": "conformal"})
    assert not env.check(horizon=10, manifest=partial, wants_interval=True)

    # Opting out is honoured.
    lenient = Envelope(max_horizon=500, requires_calibrated=False)
    assert lenient.check(horizon=10, manifest=uncalibrated, wants_interval=True)


# --------------------------------------------------------------------------
# 2. extrapolation
# --------------------------------------------------------------------------


def test_zero_extrapolation_admits_nothing_outside_the_bounds() -> None:
    """The default tolerates no extrapolation at all, not "a little".

    A default of even one percent would be a physical claim about a model the
    library knows nothing about. The value asserted below is one part in ten
    thousand outside the range: small enough to be a rounding artifact, and
    still refused.
    """
    env = Envelope(state_bounds=[(0.0, 1.0)])
    assert env.max_extrapolation == 0.0

    assert env.check(state=[1.0])
    assert not env.check(state=[1.0001])
    assert not env.check(state=[-0.0001])


def test_extrapolation_slack_scales_with_each_states_own_range() -> None:
    """Ten percent of a 1-wide range is 0.1; of a 50-wide range it is 5.

    If the slack were a global constant, or taken from the first state, the
    narrow state would be given far too much rope and the wide one far too
    little. Two states of deliberately different width are checked in the same
    envelope so that a single shared constant cannot satisfy both halves.
    """
    env = Envelope(
        state_bounds=[(0.0, 1.0), (280.0, 330.0)],  # widths 1 and 50
        max_extrapolation=0.1,
    )

    # Each state, just inside its own slack and just outside it.
    assert env.check(state=[1.09, 300.0])
    assert not env.check(state=[1.11, 300.0])
    assert env.check(state=[0.5, 334.9])
    assert not env.check(state=[0.5, 335.1])

    # The narrow state's slack must not have been borrowed from the wide one:
    # 5.0 of absolute slack would admit 1.11, and 0.1 would refuse 334.9. Both
    # are already asserted above, so the two widths are genuinely independent.
    v = env.check(state=[1.11, 300.0])
    assert v.breaches[0].limit == pytest.approx(1.1)
    v = env.check(state=[0.5, 335.1])
    assert v.breaches[0].limit == pytest.approx(335.0)

    # And the slack is symmetric below the range.
    assert env.check(state=[-0.09, 275.1])
    assert not env.check(state=[-0.11, 300.0])
    assert not env.check(state=[0.5, 274.9])


# --------------------------------------------------------------------------
# 3. from_manifest
# --------------------------------------------------------------------------


def test_from_manifest_reads_what_was_recorded() -> None:
    """The envelope is built from the record, not from the caller's optimism."""
    env = Envelope.from_manifest(_manifest(validation=VALIDATED))

    assert env.max_horizon == 500
    assert env.state_bounds == [[0.0, 1.0], [280.0, 330.0]]
    assert env.requires_validated is True
    assert env.requires_calibrated is True
    assert env.max_extrapolation == 0.0

    assert env.check(state=[0.5, 300.0], horizon=100)
    assert not env.check(state=[0.5, 300.0], horizon=600)
    assert not env.check(state=[1.5, 300.0], horizon=100)


def test_from_manifest_leaves_unrecorded_fields_refusing() -> None:
    """A manifest that recorded no horizon yields an envelope that refuses one.

    "Not written down" and "unlimited" are the same JSON and opposite claims.
    A twin whose validation section is missing entirely is the least trustworthy
    artifact this library handles, and it must not end up with the most
    permissive envelope.
    """
    for validation in (None, {}, {"leakage_free": True}):
        env = Envelope.from_manifest(_manifest(validation=validation))
        assert env.max_horizon is None, validation
        assert env.state_bounds is None, validation
        assert not env.check(horizon=1), validation

    # Only the horizon is missing here, so only the horizon is refused: the
    # state bounds that *were* recorded still do their job.
    env = Envelope.from_manifest(
        _manifest(validation={"leakage_free": True, "state_bounds": [[0.0, 1.0]]})
    )
    assert env.max_horizon is None
    assert env.state_bounds == [[0.0, 1.0]]
    assert env.check(state=[0.5])
    assert not env.check(state=[2.0])


def test_explicit_overrides_beat_the_manifest() -> None:
    """An override is how a caller narrows an envelope, or accepts a known risk.

    It must win over the recorded value — otherwise the argument is a no-op
    that reads like a safety control.
    """
    manifest = _manifest(validation=VALIDATED)

    env = Envelope.from_manifest(manifest, max_horizon=10)
    assert env.max_horizon == 10
    assert env.state_bounds == [[0.0, 1.0], [280.0, 330.0]]  # untouched
    assert not env.check(horizon=100)  # the manifest would have allowed this

    env = Envelope.from_manifest(
        manifest,
        state_bounds=[(0.0, 0.9), None],
        max_extrapolation=0.5,
        requires_calibrated=False,
    )
    assert env.state_bounds == [(0.0, 0.9), None]
    assert env.max_extrapolation == 0.5
    assert env.requires_calibrated is False
    assert env.check(state=[1.3, 1e6], horizon=1)  # 0.9 + 0.5*0.9 = 1.35
    assert not env.check(state=[1.4, 1e6], horizon=1)

    # An override can also supply what the manifest never recorded.
    bare = Envelope.from_manifest(_manifest(validation=None), max_horizon=7)
    assert bare.check(horizon=7)
    assert not bare.check(horizon=8)


# --------------------------------------------------------------------------
# 4. Verdict and Breach as reportable objects
# --------------------------------------------------------------------------


def test_verdict_is_truthy_only_when_answerable() -> None:
    """``if env.check(...)`` is the intended idiom, so ``__bool__`` must be exact.

    A ``Verdict`` is a non-empty object, so the default truthiness of an
    instance is ``True``. Without ``__bool__`` every refusal would read as an
    approval at every call site in the library.
    """
    assert bool(Verdict(answerable=True)) is True
    assert bool(Verdict(answerable=False, breaches=[Breach("k", "d")])) is False
    assert not Verdict(answerable=False)
    # The refusal is falsy even though the object carries content.
    refused = Verdict(answerable=False, breaches=[Breach("k", "d")], checked=["a"])
    assert refused.breaches and refused.checked
    assert not refused


def test_explain_reports_the_reasons_on_both_branches() -> None:
    """``explain()`` is what a human reads, so both branches must be complete."""
    env = Envelope(state_bounds=[(0.0, 1.0)], max_horizon=500)

    ok = env.check(state=[0.5], horizon=10)
    text = ok.explain()
    assert "inside the validated envelope" in text
    for entry in ok.checked:
        assert entry in text

    refused = env.check(state=[9.0], horizon=900)
    text = refused.explain()
    assert "outside the validated envelope" in text
    for breach in refused.breaches:
        assert str(breach) in text
    # The framing matters: this is a refusal to answer, not a crash, and the
    # text says so, because the alternative is a caller who "fixes" it by
    # disabling the envelope.
    assert "This is a refusal, not a failure" in text

    # A verdict with no checks at all still explains itself honestly rather
    # than claiming an approval it never earned evidence for.
    assert "no checks configured" in Verdict(answerable=True).explain()


def test_verdict_to_dict_carries_every_field() -> None:
    """The verdict has to survive the trip into a report, a log or a JSON API.

    Every field of every breach is asserted, because a serialiser that dropped
    ``observed`` and ``limit`` would still produce a plausible-looking record
    in which nobody could tell how far outside the envelope the request was.
    """
    env = Envelope(state_bounds=[(0.0, 1.0)], max_horizon=500)
    verdict = env.check(state=[9.0], horizon=900)

    d = verdict.to_dict()
    assert d["answerable"] is False
    assert d["checked"] == verdict.checked
    assert len(d["breaches"]) == len(verdict.breaches) == 2
    assert {b["kind"] for b in d["breaches"]} == {"horizon", "state"}

    for entry, breach in zip(d["breaches"], verdict.breaches, strict=True):
        assert entry == {
            "kind": breach.kind,
            "detail": breach.detail,
            "observed": breach.observed,
            "limit": breach.limit,
        }

    # Reconstructing from the dict gives back an equal verdict: nothing needed
    # to explain the refusal was lost on the way out.
    rebuilt = Verdict(
        answerable=d["answerable"],
        breaches=[Breach(**b) for b in d["breaches"]],
        checked=list(d["checked"]),
    )
    assert rebuilt == verdict
    assert rebuilt.explain() == verdict.explain()

    # The lists are copies, so a consumer mutating the dict cannot reach back
    # into the verdict it came from.
    d["checked"].append("fabricated")
    assert "fabricated" not in verdict.checked

    clean = env.check(state=[0.5], horizon=10).to_dict()
    assert clean["answerable"] is True
    assert clean["breaches"] == []
    assert clean["checked"]


def test_breach_str_quotes_the_numbers_only_when_it_has_them() -> None:
    """A breach with measurements says how far out; one without stays silent.

    Formatting ``None`` into "asked for None, validated to None" would be worse
    than the plain sentence, and formatting ``0.0`` as if it were missing would
    hide a genuine boundary violation — so the guard has to be ``is None``, not
    falsiness.
    """
    assert str(Breach("validation", "never validated")) == ("validation: never validated")
    assert str(Breach("horizon", "too far", observed=900.0, limit=500.0)) == (
        "horizon: too far (asked for 900, validated to 500)"
    )

    # Half-populated breaches fall back to the plain form rather than printing
    # a partial comparison.
    assert str(Breach("horizon", "too far", observed=900.0)) == "horizon: too far"
    assert str(Breach("horizon", "too far", limit=500.0)) == "horizon: too far"

    # Zero is a real observation, not a missing one.
    assert str(Breach("state", "below", observed=0.0, limit=0.5)) == (
        "state: below (asked for 0, validated to 0.5)"
    )


# --------------------------------------------------------------------------
# 5. require()
# --------------------------------------------------------------------------


def test_require_raises_with_the_verdict_attached() -> None:
    """At an automated boundary a refusal must stop the caller, not annotate it.

    The verdict rides on the exception so that a dispatch system can log which
    check failed instead of only that something did — and the message is the
    same text a human would have been shown.
    """
    env = Envelope(state_bounds=[(0.0, 1.0)], max_horizon=500)

    with pytest.raises(OutsideEnvelope) as excinfo:
        env.require(state=[0.5], horizon=900)

    exc = excinfo.value
    assert isinstance(exc, RuntimeError)  # catchable without importing the module
    assert not exc.verdict
    assert [b.kind for b in exc.verdict.breaches] == ["horizon"]
    assert str(exc) == exc.verdict.explain()
    assert "outside the validated envelope" in str(exc)

    # Inside the envelope it returns the same verdict `check` would have, so a
    # caller can read the evidence rather than only the absence of an exception.
    verdict = env.require(state=[0.5], horizon=100)
    assert verdict
    assert verdict == env.check(state=[0.5], horizon=100)
    assert verdict.checked


# --------------------------------------------------------------------------
# 6. malformed requests and multiple breaches
# --------------------------------------------------------------------------


def test_state_of_the_wrong_dimension_is_a_breach_not_a_crash() -> None:
    """A caller who passes three states to a two-state envelope gets a refusal.

    This is the request most likely to arrive from a mis-wired pipeline, and it
    is exactly the one that must not raise: a ``ValueError`` out of a safety
    check reads as a library fault and gets caught and ignored somewhere up the
    stack, whereas a breach is reported through the same channel as every other
    refusal. The message quotes both dimensions so the mismatch is diagnosable.
    """
    env = Envelope(state_bounds=[(0.0, 1.0), (280.0, 330.0)], max_horizon=500)

    v = env.check(state=[0.5, 300.0, 42.0], horizon=10)
    assert not v
    assert [b.kind for b in v.breaches] == ["state"]
    assert "envelope describes 2 states, got 3" in v.breaches[0].detail

    # Too few is equally a mismatch.
    v = env.check(state=[0.5], horizon=10)
    assert not v
    assert "envelope describes 2 states, got 1" in v.breaches[0].detail

    # A scalar state against a one-state envelope is legal, not a mismatch.
    assert Envelope(state_bounds=[(0.0, 1.0)]).check(state=0.5)
    assert Envelope(state_bounds=[(0.0, 1.0)]).check(state=np.array(0.5))

    # A mismatch must not suppress the checks that could still run.
    assert "horizon 10 <= 500" in v.checked


def test_every_simultaneous_breach_is_reported() -> None:
    """Fixing one reason and being refused again for the next is a bad workflow.

    All four checks run independently and all four reasons come back together,
    both in ``breaches`` and in the text a human reads. A short-circuiting
    implementation would pass every single-breach test in this file.
    """
    env = Envelope(state_bounds=[(0.0, 1.0), (280.0, 330.0)], max_horizon=500)
    manifest = _manifest(validation={"leakage_free": False}, calibration=None)

    v = env.check(state=[9.0, 999.0], horizon=900, manifest=manifest, wants_interval=True)

    assert not v
    kinds = [b.kind for b in v.breaches]
    assert kinds.count("horizon") == 1
    assert kinds.count("state") == 2  # both states are out of range, separately
    assert kinds.count("validation") == 1
    assert kinds.count("calibration") == 1
    assert len(v.breaches) == 5

    text = v.explain()
    for breach in v.breaches:
        assert str(breach) in text
    assert text.count("  - ") == 5

    # Nothing passed, so nothing is claimed to have passed.
    assert v.checked == []


def test_a_clean_verdict_is_evidence_not_silence() -> None:
    """An answerable verdict must list what was checked and what it found.

    A ``Verdict(answerable=True, checked=[])`` is indistinguishable from an
    envelope that was never configured — the failure mode where a twin is
    "inside the envelope" because no envelope exists. Every check that ran and
    passed therefore leaves a record, including the measured coverage number,
    so the approval can be audited rather than trusted.
    """
    env = Envelope(state_bounds=[(0.0, 1.0), (280.0, 330.0)], max_horizon=500)
    manifest = _manifest(validation=VALIDATED, calibration=CALIBRATED)

    v = env.check(state=[0.5, 300.0], horizon=100, manifest=manifest, wants_interval=True)

    assert v
    assert v.breaches == []
    assert v.checked == [
        "horizon 100 <= 500",
        "operating point inside the identified range",
        "validated, leakage-free",
        "coverage measured at 0.94",
    ]
    assert v.to_dict()["checked"] == v.checked
    for entry in v.checked:
        assert entry in v.explain()


# --------------------------------------------------------------------------
# Regression: an unrecorded operating range is a refusal, not a licence
# --------------------------------------------------------------------------


def test_absent_state_bounds_refuse_every_operating_point():
    """The inverse of the max_horizon rule, and it used to be backwards.

    Until this was fixed, `check` skipped the state test entirely when
    `state_bounds` was None, so a twin with no recorded operating range
    returned a clean, evidence-carrying verdict for any state whatsoever --
    a state of charge of 1e12 came back answerable with zero breaches.

    `from_manifest` documents the intended rule: a field the manifest does not
    carry "stays None, which is a refusal rather than a default". This asserts
    it on the axis where it was violated.
    """
    env = Envelope(state_bounds=None, max_horizon=500)

    for absurd in ([0.5], [1e12], [-1e12], [0.0]):
        verdict = env.check(state=absurd, horizon=10)
        assert not verdict, f"state {absurd} was admitted with no recorded range"
        kinds = [b.kind for b in verdict.breaches]
        assert "state" in kinds, f"no state breach for {absurd}: {kinds}"


def test_absent_state_bounds_do_not_refuse_when_no_state_is_asked_about():
    """The refusal must be about the question, not about the envelope.

    A caller asking only about a horizon has not asked anything the missing
    operating range can answer, so the absent bounds must stay silent. This is
    exactly how the horizon check behaves when `horizon` is not supplied, and
    the asymmetry would be a bug in the other direction.
    """
    env = Envelope(state_bounds=None, max_horizon=500)
    verdict = env.check(horizon=10)
    assert verdict, verdict.explain()
    assert not any(b.kind == "state" for b in verdict.breaches)
