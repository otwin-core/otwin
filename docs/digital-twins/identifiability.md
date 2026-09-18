# Identifiability

A fitted coefficient is not a determined one. Every check in `otwin` up to
this point — leakage-free validation, measured coverage, the validity envelope —
takes the model's parameters as given and asks whether the *forecast* holds up.
This page is about the step before that: whether the parameters were fixed by
the measurements at all, or merely by the noise in them.

## The definition

A parameter is **identifiable** from a dataset when two different values of it
would have produced observably different predictions. If two values produce the
same predictions to within the measurement noise, the data cannot tell them
apart. The fit still returns a number — least squares always does — but that
number was selected by the noise, and everything downstream that extrapolates
through it is extrapolating the noise.

The failure is invisible in the fitted window. A non-identified two-term law
fits its training data at least as well as a one-term law, because it has one
more degree of freedom. It reveals itself only outside the window, as a curve
that runs away, and by then the manifest says `validated` and `calibrated`
because both of those were measured *inside* the window.

## Three ways a parameter fails to be identified

`otwin` checks the three that account for every failure met while building the
library. They are different mechanisms and need different tests.

**Collinearity.** The design columns for two parameters are nearly
proportional, so the data fix a combination of the coefficients but not the
split between them. Early in a battery's life, $n^{0.5}$ and $n^{2.5}$ are
both smooth, monotone and small; the data fix $c_1 n^{0.5} + c_2 n^{2.5}$ and
have no opinion on $c_2$ alone until the knee has begun. The check regresses
each column on the others and reports the $R^2$; above 0.95 the column is
redundant.

**Span.** A parameter that is, or implies, a time constant cannot be seen from
a record shorter than that time constant. An asymptotic fouling law
$R_f = R_\infty(1 - e^{-t/\tau})$ fitted to 180 days of a 260-day process
returns an $R_\infty$ that is too low — the plateau it is extrapolating to was
never in the data. The check compares the record span with the fitted time
constant; below a ratio of one the process has not been observed.

**Stability.** Refit on bootstrap resamples and watch the coefficient. The
resampling unit matters: with several observations per cell or per system,
resampling *rows* treats correlated points as independent and overstates
stability. `otwin` resamples **units** when `groups` is given. A coefficient of
variation above 0.5, a sign that flips, or — under non-negative least squares —
a term that is switched off on more than a tenth of the resamples, is a
coefficient the fleet does not determine.

None of these is a proof of identifiability. Together they are what a careful
engineer does by hand before believing a fit, written down so that the verdict
can be recorded and acted on.

## Using it

The two-term capacity-fade law on a short and a long window of the same cell:

```python
import numpy as np
from otwin.estimate import identifiability

rng = np.random.default_rng(0)
n_all = np.arange(1.0, 801.0)
soh = 1 - 2.0e-3 * n_all**0.5 - 2.0e-9 * n_all**2.5 + rng.normal(0, 1.5e-3, n_all.size)

reports = {}
for window in (100, 800):
    n = n_all[:window]
    X = np.column_stack([n**0.5, n**2.5])          # the two-term basis
    reports[window] = identifiability(
        X, 1 - soh[:window], names=("c_slow", "c_knee"), nonneg=True, n_boot=200
    )
    print(f"{window} cycles -> {reports[window].verdicts}")
```

```text
100 cycles -> {'c_slow': True, 'c_knee': False}
800 cycles -> {'c_slow': True, 'c_knee': True}
```

The same law, the same cell, the same fitting code. At 100 cycles the knee
coefficient is not identified; at 800 it is. The report says which check
failed and why:

```python
print(reports[100].parameters[1])
```

```text
c_knee: NOT identified (collinearity R²=0.758, bootstrap CV=0.72)
    bootstrap over 100 units gives CV=0.72 > 0.5; refitting on a resampled fleet returns a different value
    coefficient switches off or changes sign across bootstrap resamples
```

Note what did *not* fail: collinearity is 0.76, below threshold. The columns
are distinguishable in principle; there is simply not enough knee in the first
100 cycles for the fit to land on the same value twice. That is the
distinction between "the basis is wrong" and "the record is too short", and it
matters for what you do next — wait, rather than change the law.

## Recording it, and refusing on it

The verdicts go into the manifest through
{meth}`~otwin.interfaces.TwinManifest.identified_by`, next to `validated_by`
and `calibrated_by`, and {attr}`~otwin.interfaces.TwinManifest.is_identified`
reads them as strictly as `is_validated` does: every estimated parameter must
carry the boolean `True`. An estimated parameter with no verdict is not
identified — *not yet checked* is not *fine*.

```python
from otwin.advise import Envelope
from otwin.interfaces import Provenance, TwinManifest

def twin(report):
    return TwinManifest(
        name="cell-A3", model_class="empirical_law", model_kind="two_term_fade",
        n_states=1, n_inputs=0,
        parameters={"c_slow": 2.0e-3, "c_knee": 2.0e-9},
        estimated=("c_slow", "c_knee"),
        provenance=Provenance(created="2026-08-24T00:00:00Z", otwin_version="0.4.0"),
        validation=TwinManifest.validated_by("rolling_origin", horizon=60),
        calibration=TwinManifest.calibrated_by("horizon_conformal", empirical_coverage=0.90),
        identification=TwinManifest.identified_by(
            "collinearity+bootstrap", parameters=report.verdicts
        ),
    )

envelope = Envelope(state_bounds=[(0.60, 1.00)], max_horizon=60, requires_identified=True)
print(envelope.check(state=[0.9], horizon=30, manifest=twin(reports[100])).explain())
```

```text
outside the validated envelope:
  - identification: extrapolation depends on parameters the data did not determine: c_knee. A fitted value the fleet cannot pin down is a value chosen by the noise

This is a refusal, not a failure. The twin has not been shown to answer this question, and returning a number anyway would hide that.
```

The request was inside the operating range, inside the validated horizon, on a
validated and calibrated twin. It is refused anyway, and the refusal names the
coefficient. On the 800-cycle fit the same request is answered:

```python
print(envelope.check(state=[0.9], horizon=30, manifest=twin(reports[800])).explain())
```

```text
inside the validated envelope (horizon 30 <= 60; operating point inside the identified range; validated, leakage-free; estimated parameters identified)
```

`requires_identified` defaults to `False`, because manifests written before
this release carry no identification record and would otherwise all be refused.
Turn it on for anything that extrapolates. A twin that answers only inside the
window it was fitted on does not need it; a twin that is asked about year eight
does.

## Where this came from

Every result in the replication study that built this library was decided by
identifiability, and the library had no word for it:

- a free exponent $z$ in $1 - c\,n^{z}$, fitted on 100 cycles of a NASA cell,
  extrapolated worse than $z = 1$ fixed — many $(c, z)$ pairs traced the same
  curve through the window and diverged after it;
- a second power term whose coefficient collapsed to an offset at 100 cycles
  of the Severson fleet, and was identified only from 40 % of life;
- the same two-term law fitted to three field capacity tests per system on the
  RWTH home-storage fleet, which ran away at 5.4 years and delivered 78 %
  coverage at a 90 % target — while passing the operating-range, horizon and
  calibration checks.

None of those laws was wrong. None was identified. This page is the check that
would have refused all three.

## What this is not

Identifiability is a property of the pairing of a model with a dataset, not of
the model. The two-term law is identified on the Severson fleet and not on the
RWTH fleet; the check tells you which regime you are in, not which law is
true. And a parameter that passes all three checks can still be biased by a
mis-specified structure — that is what leakage-free validation against a
baseline is for. The two questions are different: *was it determined?* and
*was it right?* This page answers the first.
