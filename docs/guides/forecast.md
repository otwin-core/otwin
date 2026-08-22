# Forecast — `otwin.forecast`

What happens next, and how sure. The largest module in the package, and the one
with the most ways to fool yourself — so it is built to make the honest path the
easy one.

The reasoning is in [Leakage-free evaluation](../concepts/leakage.md) and
[Calibrated intervals](../concepts/conformal.md). This page is the map.

## The one interface

`otwin` asks a model for exactly one thing:

```{code-block} python
def forecast(self, history, horizon): ...
```

`history` is everything up to the origin. `horizon` is how many steps ahead.
There is no argument through which the held-out targets could arrive, which is
the point: a model that does not expose this raises
{class}`~otwin.forecast.ForecastInterfaceError` rather than falling back to
something that might leak.

## Splitting

| | |
|---|---|
| {func}`~otwin.forecast.temporal_holdout` | last fraction held out; the default |
| {func}`~otwin.forecast.rolling_origin` | expanding or sliding window; report this |
| {func}`~otwin.forecast.random_split` | **opt-in, warns loudly** — measures interpolation on a time series |

## Baselines

{func}`~otwin.forecast.persistence`, {func}`~otwin.forecast.mean_forecast`,
{func}`~otwin.forecast.drift`, {func}`~otwin.forecast.seasonal_naive`.
{func}`~otwin.forecast.get_best_baseline` picks the strongest by RMSE — the only
honest comparator, since beating the weakest proves nothing.

## Evaluating

{func}`~otwin.forecast.evaluate` runs the whole thing and returns an
{class}`~otwin.forecast.EvalReport` carrying `split_protocol`, `n_folds`,
`point_metrics`, `baseline_metrics`, `probabilistic_metrics`, `data_hash`,
`seed` and `n_exog`. {meth}`~otwin.forecast.EvalReport.skill_score` is a method
— computed against the baseline, not stored. `to_markdown()` renders it for a
report; `to_json()` / `from_json()` round-trip it.

`data_hash` and `seed` are what make a number reproducible six months later. A
metric without them is an anecdote.

## Metrics

**Point:** {func}`~otwin.forecast.rmse`, {func}`~otwin.forecast.mae`,
{func}`~otwin.forecast.nrmse`, {func}`~otwin.forecast.mase`,
{func}`~otwin.forecast.theil_u`, {func}`~otwin.forecast.skill_score`.

**Interval and probabilistic:** {func}`~otwin.forecast.picp` (delivered
coverage), {func}`~otwin.forecast.mpiw` / {func}`~otwin.forecast.sharpness`
(width), {func}`~otwin.forecast.interval_score` (trades the two off),
{func}`~otwin.forecast.crps`, {func}`~otwin.forecast.pit_values`,
{func}`~otwin.forecast.coverage_curve`,
{func}`~otwin.forecast.expected_calibration_error`.

Report coverage **and** width together. Either alone is trivially gameable: a
band from $-\infty$ to $\infty$ has perfect coverage.

## Building intervals

{func}`~otwin.forecast.rolling_origin_residuals`
: genuine $h$-step-ahead residuals. Start here. Everything below is only as good
  as what you feed it.

{func}`~otwin.forecast.conformal_quantile`
: the finite-sample quantile, $k = \lceil \alpha(n+1)\rceil$. Returns infinity
  when the calibration set cannot support the level.

{func}`~otwin.forecast.split_conformal`
: one half-width for every horizon.

{func}`~otwin.forecast.horizon_conformal`
: a half-width that grows with the horizon, with
  {attr}`~otwin.forecast.ConformalBand.extrapolated` marking where the guarantee
  stops.

{class}`~otwin.forecast.AdaptiveConformal`
: online conformal inference for a live asset whose error distribution drifts.

{func}`~otwin.forecast.recalibrate`
: a monotonic recalibration map from calibration-set PIT values, when the shape
  of the predictive distribution is wrong rather than its width.

{class}`~otwin.forecast.Ensemble`
: quantile intervals from a collection of members.

## Exogenous drivers

Pass `exog=` to {func}`~otwin.forecast.evaluate` and the protocol splits it in
step with the target, handing the model `exog_past` and `exog_future`. Every
column is checked against the target at shifts up to five steps in both
directions and an exact match is refused — a covariate carrying the answer
defeats the interface as completely as passing the test array did, and is far
harder to spot by eye.

## Next

[Advise](advise.md) — deciding whether the forecast you just made may be used.
