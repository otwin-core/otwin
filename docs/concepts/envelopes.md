# Validity envelopes

Everything else in `otwin` produces evidence. The envelope is what turns
evidence into a decision, and it is the part that makes this library different
from one that always returns a number.

## The rule

A twin may answer a question when **all** of the following hold:

1. the operating point is inside the range the model was identified over
2. the horizon is inside the horizon it was validated to
3. the validation was **leakage-free**
4. if an interval is requested, the calibration recorded **measured** coverage
5. if `requires_identified` is set, every estimated parameter is recorded as
   **identified** — determined by the data, not chosen by the noise
   (see [Identifiability](identifiability.md))

Fail any of them and {meth}`~otwin.advise.Envelope.check` returns a
{class}`~otwin.advise.Verdict` that is falsy and carries a
{class}`~otwin.advise.Breach` per reason.

## Absence is refusal, not permission

This is the design decision worth arguing about, so here is the argument.

`otwin` 0.1 skipped the state check entirely when `state_bounds` was `None`. A
twin with no identified range therefore returned a clean verdict for a state of
charge of $10^{12}$. That is the failure mode of every "sensible default":
the unconfigured case is the *most* dangerous one, because nobody chose it.

An absent range is now a refusal. So is an absent manifest, an absent validation
record, and an absent calibration when an interval is asked for. If you have not
established that the twin works there, it will not pretend.

## Using it

```python
import numpy as np
import otwin
from otwin.advise import Envelope
from otwin.interfaces import Provenance, TwinManifest

manifest = TwinManifest(
    name="cell-A12 capacity twin",
    model_class="empirical_law",
    model_kind="grey_box",
    n_states=1,
    n_inputs=0,
    provenance=Provenance(created="2026-08-22T10:00:00Z",
                          otwin_version=otwin.__version__),
    validation=TwinManifest.validated_by(protocol="rolling_origin", horizon=60),
    calibration=TwinManifest.calibrated_by(
        method="horizon_conformal", level=0.9, empirical_coverage=0.91
    ),
)

envelope = Envelope(
    state_bounds=[(0.70, 1.02)],
    max_horizon=60,
    requires_validated=True,
    requires_calibrated=True,
    requires_identified=False,
    max_extrapolation=0.0,
)
```

| Parameter | Meaning |
|---|---|
| `state_bounds` | per-state `(low, high)`, or `None` for a state with no constraint |
| `max_horizon` | the horizon the twin was validated to |
| `requires_validated` | refuse unless the record asserts `leakage_free=True` |
| `requires_calibrated` | refuse an interval unless coverage was measured |
| `requires_identified` | refuse unless every estimated parameter carries an identification verdict of `True` |
| `max_extrapolation` | how far outside the bounds is tolerated, as a fraction of range |

`max_extrapolation=0.0` is strict: the calibrated range is the answerable range.
Raising it to `0.05` says you will accept 5 % beyond, which is a judgement about
your asset that the library will not make for you.

## Reading a refusal

```python
verdict = envelope.check(
    state=np.array([0.92]), horizon=90, manifest=manifest, wants_interval=True
)
print(bool(verdict))
for breach in verdict.breaches:
    print(breach)
```

```text
False
horizon: beyond the validated forecast horizon (asked for 90, validated to 60)
```

A refusal names the field it read and the two numbers it compared. That was not
always true: a manifest recording `protocol="rolling_origin"` and `picp=0.87`
used to be refused with *"this twin has never been validated under a
leakage-free protocol"* — true of the record, false of the work, and no help in
finding the cause. The envelope now distinguishes an empty record from one that
is present but does not assert what is needed, and names the builder that sets
it.

A refusal on identification names the parameter:
`identification: extrapolation depends on parameters the data did not
determine: c_knee`. That is the check the other four cannot make: a law whose
second term was fitted to noise is inside its range, inside its horizon,
validated and calibrated — and runs away at the far end anyway. It is off by
default so that manifests written before 0.4.0 keep working; set it for any
twin that extrapolates.

If you want the refusal as an exception rather than a value, catch
{class}`~otwin.advise.OutsideEnvelope`.

## What this is not

The envelope does not make a twin correct. It makes the *scope* of the claim
explicit and machine-checkable. A twin can be inside its envelope and still
wrong — the model may be a bad model. What the envelope removes is the other
failure: a confident number produced far outside anything that was ever tested,
with nothing in the output to indicate it.
