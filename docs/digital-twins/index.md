# Digital twins

A simulation model describes a kind of system. A Digital Twin represents **one
particular asset** and is kept in step with what that asset measures. This section
is the distance between the two.

```text
Physical model
       ↓
Real asset
       ↓
Measurements
       ↓
State estimation
       ↓
Calibration
       ↓
Forecasting
       ↓
Uncertainty
       ↓
Validation
       ↓
Validity envelope
```

The questions at the end of that chain are engineering questions. How much longer
can this transformer run above nameplate before the winding reaches its limit. How
much can this battery bank commit to the market next week and still deliver it. How
many weeks of margin are left before the duty pump can no longer hold its setpoint.

Answering them needs a model that is right by construction where the physics is
known, able to represent what the physics does not know, fast enough to run
repeatedly against real data, calibrated and validated against observations, and
explicit about the limits of what it has demonstrated. The first two are the
[physics](../physics/index.md). The rest is this section.

## The steps

| Step | What it does | Page |
|---|---|---|
| Acquire | read a device or a dataset, with a quality flag on every value | [Acquire](acquire.md) |
| Condition | put irregular samples on a uniform grid without inventing data | [Condition](condition.md) |
| Estimate | recover the states nobody measured | [Estimate](estimate.md) |
| Calibrate | fit the parameters the data can determine, and say which ones it cannot | [Identifiability](identifiability.md) |
| Fill the gaps | learn what the physics leaves out, without replacing the physics | [Grey-box models](hybrid.md) |
| Forecast | run it forward | [Forecast](forecast.md) |
| Quantify | intervals whose coverage was measured, not assumed | [Calibrated intervals](uncertainty.md) |
| Validate | out of sample, against a baseline, with no leakage | [Leakage-free evaluation](validation.md) |
| Record | what was fitted, validated and calibrated, and how | [The twin manifest](manifest.md) |
| Decide or refuse | answer only inside what was demonstrated | [Validity envelopes](envelopes.md), [Advise](advise.md) |

The module layout follows the six data-processing blocks of ISO 13374, the standard
for condition monitoring and diagnostics of machines, so that a number can be traced
back through them to the register it was read from. See [The six
blocks](iso13374.md).

## What makes it a twin rather than a simulation

Three things, and each of them is a refusal to accept something convenient.

**The state is estimated, not assumed.** A real asset does not tell you its state of
charge or its internal temperature. An estimator recovers it from the sensors that
exist, and the energy-consistent observer will reject a correction that would
manufacture stored energy, so filtering cannot quietly break the property the model
was chosen for.

**Uncertainty is measured, not declared.** A stated ninety per cent interval means
nothing until ninety per cent coverage has been observed on data the model never
saw. Otwin calibrates on genuine out-of-sample forecast errors, and returns an
infinite interval rather than a comfortable-looking one when the calibration set is
too small to support the level requested.

**The scope of the claim is recorded.** The manifest says what was fitted, under
which protocol it was validated, to what horizon, and with what measured coverage.
The envelope reads that record and refuses questions outside it, naming the boundary
that was crossed. A twin with no manifest is not a twin with a permissive envelope.
It is one that cannot answer.

```{toctree}
:hidden:
:maxdepth: 1

iso13374
acquire
condition
estimate
hybrid
identifiability
forecast
uncertainty
validation
manifest
envelopes
advise
```
