# Calibrated intervals

A prediction interval is a promise: *90 % of the time the truth lands inside*.
Conformal prediction is the machinery that makes the promise checkable, and
{mod}`otwin.forecast.conformal` is where it is built.

## Why conformal rather than the model's own uncertainty

A conformal band needs one assumption — that the calibration errors and the test
errors are **exchangeable** — and in exchange it makes no assumption about the
model at all. It works identically on a Gaussian process, a fade law, a neural
network or a lookup table. The likelihood does not have to be right, which
matters because on a physical asset it usually is not.

## The trap, stated once and loudly

**The residuals you calibrate on must be forecast errors of the same kind you
are about to make.**

The tempting shortcut is to take the fitted model's own in-sample residuals and
quantile them. That is not a smaller version of the right thing; it is a
different quantity. A model that interpolates its training data has in-sample
residuals an order of magnitude smaller than its $h$-step-ahead errors, so the
band comes out roughly ten times too narrow. Measured on a lithium-ion capacity
twin: **1.5 % delivered coverage at a 90 % target.**

{func}`~otwin.forecast.rolling_origin_residuals` makes the honest thing the easy
thing. It refits the whole pipeline at earlier origins *inside* the training
window and collects genuine $h$-step-ahead errors. It costs one refit per
origin, and that cost is the entire difference between a band that means
something and one that does not.

## The finite-sample quantile

With $n$ calibration residuals and a target level $\alpha$, the conformal
half-width is the $k$-th order statistic of $|{\rm residual}|$ where

$$
k = \left\lceil \alpha\,(n+1) \right\rceil
$$

The $n+1$ is not a rounding detail — it is what makes the guarantee hold in
finite samples rather than asymptotically. It also means a calibration set can
be **exactly large enough to be too small**: at $\alpha = 0.9$ and $n = 9$,
$k = 9$ and the band is the sample maximum; at $n = 8$, $k = 9 > n$ and the
honest answer is infinite.

`otwin` returns infinity, with a warning, rather than clipping the rank to $n$
and returning the sample maximum:

```python
import numpy as np
from otwin.forecast import conformal_quantile

residuals = np.array([0.1, -0.2, 0.15])
print(conformal_quantile(residuals, level=0.9))
```

```text
inf
```

Clipping would return a number that is narrower than the guarantee requires and
silent about it. An infinite interval is useless, but it is *visibly* useless.

:::{note}
`0.9 * 10` is `9.000000000000002` in binary floating point, which asked for rank
10 out of 10 and turned a just-large-enough calibration set into a refusal. The
product is rounded to twelve decimals before the ceiling. On a rolling-origin
calibration set this bug cost the sparsest horizons — exactly the ones that set
the extrapolated end of a horizon-aware band.
:::

## Three constructions

### `split_conformal`

One half-width for every horizon. Correct on average over the horizons in the
calibration set, and too narrow early / too wide late whenever error grows with
horizon — which for a degradation forecast it always does.

Right when the error process is genuinely stationary in $h$.

### `horizon_conformal`

A half-width that **grows with the horizon**, fitted as a power law
(`fit="log"`, the default) or linearly (`fit="linear"`) over the calibrated
range and extrapolated beyond it.

```python
from otwin.forecast import horizon_conformal, rolling_origin_residuals

rng = np.random.default_rng(0)
k = np.arange(600)
capacity = 1.0 - 0.00025 * k - 0.00000012 * k**2 + rng.normal(0, 0.0015, k.size)

def refit_forecast(history, horizon):
    idx = np.arange(history.size)
    coeffs = np.polyfit(idx[-200:], history[-200:], 2)
    return np.polyval(coeffs, np.arange(history.size, history.size + horizon))

residuals, horizons = rolling_origin_residuals(
    refit_forecast, capacity, step=10, max_horizon=60
)
band = horizon_conformal(residuals, horizons, level=0.9, max_horizon=90)

print(f"method        : {band.method}")
print(f"calibrated on : {band.n_calibration} residuals")
print(f"h=1  half-width {band.half_width[0]:.5f}")
print(f"h=60 half-width {band.half_width[59]:.5f}")
print(f"h=90 half-width {band.half_width[89]:.5f}  extrapolated={bool(band.extrapolated[89])}")
```

```text
method        : horizon_conformal
calibrated on : 2250 residuals
h=1  half-width 0.00230
h=60 half-width 0.00272
h=90 half-width 0.00276  extrapolated=True
```

{attr}`~otwin.forecast.ConformalBand.extrapolated` is the honest part. Beyond
the calibrated range the width is a fitted growth law, not a conformal
guarantee, and the object says which is which instead of letting you assume.

`min_per_horizon` guards the thin end: a horizon with three residuals behind it
cannot support a 90 % band, and the default floor is derived from the level (9
at 90 %) rather than picked.

### `AdaptiveConformal`

Online conformal inference (ACI). The band corrects itself as observations
arrive, widening after a miss and narrowing after a run of hits. For a twin
running against a live asset whose error distribution drifts, this is the one
that keeps the promise; the two above assume exchangeability that a drifting
asset eventually violates.

## Measuring what you built

Building a band and reporting its nominal level is not calibration. Measure it:

| Function | Reports |
|---|---|
| {func}`~otwin.forecast.picp` | delivered coverage |
| {func}`~otwin.forecast.mpiw` | mean width — a band can always be widened |
| {func}`~otwin.forecast.interval_score` | Gneiting–Raftery, trades the two off |
| {func}`~otwin.forecast.coverage_curve` | coverage across nominal levels |
| {func}`~otwin.forecast.expected_calibration_error` | mean gap, nominal vs empirical |

{meth}`~otwin.interfaces.TwinManifest.calibrated_by` requires
`empirical_coverage` and rejects a percentage where a fraction belongs, so a
twin cannot record a calibration it never measured.
