# Leakage-free evaluation

A forecast skill score is a claim about the future. It is worth exactly as much
as the care taken to stop the evaluation seeing the answer — and the ways that
care fails are boring, mechanical and extremely common.

## The three failures this module is built against

**Passing the test window to the model.** `otwin` 0.1 did this at two separate
call sites: `protocol.py` handed the held-out targets to `model.predict()`, so
every reported skill score measured *interpolation*. The fix was structural, not
a patch — the test targets are no longer an argument to the function that asks
the model for a prediction. The interface is
`forecast(history, horizon) -> values`, and it is the only thing
{func}`~otwin.forecast.evaluate` calls.

**Random splits on a time series.** Shuffling rows and holding out 20 % lets the
model interpolate between neighbouring samples. {func}`~otwin.forecast.random_split`
exists — some problems genuinely are exchangeable — but it is opt-in and warns
loudly every time. {func}`~otwin.forecast.temporal_holdout` is the default and
{func}`~otwin.forecast.rolling_origin` is what you should report.

**No baseline.** A skill score against nothing is a number with no scale.
{class}`~otwin.interfaces.Baseline` is compulsory rather than optional: if your
twin cannot beat {func}`~otwin.forecast.persistence`, that is the finding.

## Splitters

| Splitter | Leakage-free | Use |
|---|---|---|
| {func}`~otwin.forecast.temporal_holdout` | yes | quick check; default |
| {func}`~otwin.forecast.rolling_origin` | yes | reporting; expanding or sliding window |
| {func}`~otwin.forecast.random_split` | **no** | only when the data is genuinely exchangeable |

## Baselines you have to beat

{func}`~otwin.forecast.persistence` (repeat the last value),
{func}`~otwin.forecast.mean_forecast`, {func}`~otwin.forecast.drift` (linear
extrapolation from the last two points), and
{func}`~otwin.forecast.seasonal_naive`. {func}`~otwin.forecast.get_best_baseline`
picks the strongest by RMSE, which is the honest comparator — beating the
*weakest* baseline is not evidence of anything.

Persistence is a much harder opponent than it looks on a slowly-degrading asset.
That is the point.

## Evaluating

```python
import numpy as np
from otwin.forecast import evaluate

rng = np.random.default_rng(1)
k = np.arange(400)
series = 1.0 - 0.0004 * k + rng.normal(0, 0.002, k.size)

class FadeLaw:
    """A model exposing the only interface `evaluate` will call."""

    def forecast(self, history, horizon):
        idx = np.arange(history.size)
        coeffs = np.polyfit(idx[-150:], history[-150:], 1)
        return np.polyval(coeffs, np.arange(history.size, history.size + horizon))

report = evaluate(FadeLaw(), series, protocol="rolling_origin", horizon=20, n_folds=5)
print(f"protocol      : {report.split_protocol}  ({report.n_folds} folds)")
print(f"RMSE          : {report.point_metrics['rmse']:.5f}")
print(f"MASE          : {report.point_metrics['mase']:.3f}")
print(f"best baseline : {report.baseline_name} at RMSE {report.baseline_metrics['rmse']:.5f}")
print(f"skill score   : {report.skill_score():+.3f}")
```

```text
protocol      : rolling_origin  (5 folds)
RMSE          : 0.00178
MASE          : 0.660
best baseline : persistence at RMSE 0.00514
skill score   : +0.653
```

{meth}`~otwin.forecast.EvalReport.skill_score` is a method, not an attribute —
it is computed against the baseline rather than stored. `MASE` below 1 means the
model beats a naive forecast on the same scale; `data_hash` and `seed` on the
report are what make the number reproducible six months later.

A model that does not expose `forecast(history, horizon)` raises
{class}`~otwin.forecast.ForecastInterfaceError` rather than falling back to
something that might leak.

## Exogenous drivers

Some twins depend on something the target does not determine — ambient
temperature, dispatch schedule, throughput. Pass `exog=` and the protocol splits
it in step with the target, handing the model `exog_past` and `exog_future`
separately.

Every column is checked against the target at shifts up to five steps **in both
directions**, and an exact match is refused. A covariate carrying the answer
defeats the leakage-free interface as completely as passing the test array did,
and it is much harder to notice by eye.

## Recording it

{meth}`~otwin.interfaces.TwinManifest.validated_by` builds the record the
envelope reads:

```python
from otwin.interfaces import TwinManifest

print(TwinManifest.validated_by(protocol="rolling_origin", horizon=60))
print(TwinManifest.validated_by(protocol="random_split", horizon=60))
```

```text
{'protocol': 'rolling_origin', 'leakage_free': True, 'horizon': 60}
{'protocol': 'random_split', 'leakage_free': False, 'horizon': 60}
```

`leakage_free` is *derived* from the protocol, not asserted by the caller. You
cannot record a random split as leakage-free by writing it down.
