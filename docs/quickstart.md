# Quickstart

Three things, in the order you would actually do them: model an asset, forecast
its degradation with an honest interval, and let the twin decide whether it is
entitled to answer.

Every block below runs as written. There is no data file — the fade series is
synthetic so that this page is self-contained.

## 1. A model that obeys physics

{func}`~otwin.model.pumped_hydro` returns a two-reservoir store as a
port-Hamiltonian system: water is moved between reservoirs through a reversible
pump-turbine, and the stored energy is gravitational potential energy.

```python
import numpy as np
import otwin
from otwin.model import integrate_phs, pumped_hydro

plant = pumped_hydro()

x0 = np.array([2.0e6, 8.0e6])          # upper, lower reservoir volumes (m³)
t = np.linspace(0.0, 3600.0, 361)      # one hour, 10 s steps
u = np.full((t.size, 1), 50.0)         # pump 50 m³/s upward for the whole hour

result = integrate_phs(plant, x0, t, u=u)

H = np.array([plant.energy(x) for x in result["x"]])
print(f"stored energy rose by {(H[-1] - H[0]) / H[0]:.1%}")
```

```text
stored energy rose by 9.5%
```

The integrator is implicit midpoint with an analytic Jacobian, chosen because it
preserves the discrete power balance rather than merely approximating the
trajectory. Turn the pump off and the energy cannot rise — not because the
solver is accurate, but because the structure forbids it. That guarantee is what
survives outside the data you fitted on.

`result` also carries `t`, the realised port trajectory `u`, and the solver's
own diagnostics (`success`, `n_newton_iter`, `n_feval`, `message`).

:::{tip}
`u` is either an `(n_points, n_inputs)` trajectory or a **port law**
`u(t, x) -> u` for a state-dependent port — a converter holding constant power,
a thermostat, a droop control. A bare `(n_inputs,)` array is not a constant
input; it is read as a one-step schedule.
:::

## 2. A forecast with an interval you can defend

The trap here is worth stating before the code. It is tempting to take the
fitted model's own in-sample residuals and quantile them. That is not a smaller
version of the right thing, it is a different quantity: a model that
interpolates its training data has in-sample residuals an order of magnitude
smaller than its h-step-ahead errors. Measured on a lithium-ion capacity twin,
that shortcut delivered **1.5 % coverage at a 90 % target**.

{func}`~otwin.forecast.rolling_origin_residuals` exists to make the honest thing
the easy thing. It refits the whole pipeline at earlier origins *inside* the
training window and collects genuine h-step-ahead errors.

```python
from otwin.forecast import horizon_conformal, rolling_origin_residuals

rng = np.random.default_rng(0)
k = np.arange(600)
capacity = 1.0 - 0.00025 * k - 0.00000012 * k**2 + rng.normal(0, 0.0015, k.size)

def refit_forecast(history, horizon):
    """Refit the fade law on `history` alone and project `horizon` steps."""
    idx = np.arange(history.size)
    coeffs = np.polyfit(idx[-200:], history[-200:], 2)
    return np.polyval(coeffs, np.arange(history.size, history.size + horizon))

residuals, horizons = rolling_origin_residuals(
    refit_forecast, capacity, step=10, max_horizon=60
)
print(f"{residuals.size} residuals over horizons {horizons.min()}–{horizons.max()}")

band = horizon_conformal(residuals, horizons, level=0.9, max_horizon=90)
print(f"half-width at h=1:  {band.half_width[0]:.5f}")
print(f"half-width at h=60: {band.half_width[59]:.5f}")
print(f"extrapolated beyond h={int(np.argmax(band.extrapolated)) + 1}")
```

```text
2250 residuals over horizons 1–60
half-width at h=1:  0.00230
half-width at h=60: 0.00272
extrapolated beyond h=61
```

The band widens with the horizon because forecast error does, and
{attr}`~otwin.forecast.ConformalBand.extrapolated` marks the steps no
calibration residual ever reached. Those steps are a fitted growth law, not a
conformal guarantee, and the object says so rather than letting you assume
otherwise.

Use {func}`~otwin.forecast.split_conformal` instead when one half-width for
every horizon is genuinely right — a stationary error process, not a
degradation forecast.

## 3. A twin that knows what it does not know

Everything above is a claim. {class}`~otwin.advise.Envelope` is what turns those
claims into a decision, by reading the record the twin carries with it.

```python
from otwin.advise import Envelope
from otwin.interfaces import Provenance, TwinManifest

manifest = TwinManifest(
    name="cell-A12 capacity twin",
    model_class="empirical_law",
    model_kind="grey_box",
    n_states=1,
    n_inputs=0,
    provenance=Provenance(
        created="2026-08-22T10:00:00Z",
        otwin_version=otwin.__version__,
        script="docs/quickstart.md",
        seed=0,
        data_source="synthetic capacity fade",
    ),
    validation=TwinManifest.validated_by(protocol="rolling_origin", horizon=60),
    calibration=TwinManifest.calibrated_by(
        method="horizon_conformal", level=0.9, empirical_coverage=0.91
    ),
)

envelope = Envelope(
    state_bounds=[(0.70, 1.02)],   # the capacity range it was identified over
    max_horizon=60,               # the horizon it was validated to
    max_extrapolation=0.0,
)

for state, horizon in [(0.92, 30), (0.92, 90), (0.55, 30)]:
    verdict = envelope.check(
        state=np.array([state]), horizon=horizon,
        manifest=manifest, wants_interval=True,
    )
    print(f"state {state}, horizon {horizon:>2} -> {bool(verdict)}")
    for breach in verdict.breaches:
        print(f"    {breach}")
```

```text
state 0.92, horizon 30 -> True
state 0.92, horizon 90 -> False
    horizon: beyond the validated forecast horizon (asked for 90, validated to 60)
state 0.55, horizon 30 -> False
    state: state 0 below the identified range (asked for 0.55, validated to 0.7)
```

A {class}`~otwin.advise.Verdict` is truthy when the question can be answered and
carries a {class}`~otwin.advise.Breach` per reason when it cannot. Note what
`max_extrapolation=0.0` bought: the 90-step request was refused even though the
band object would happily have returned a half-width for it, because those steps
were extrapolated rather than calibrated.

An absent record is a refusal, not a pass. A twin with no `state_bounds` does not
get a clean verdict for a state of charge of 1e12.

## Where to go next

- [Port-Hamiltonian systems](concepts/port-hamiltonian.md) — the structure, and
  why passivity is the point
- [Leakage-free evaluation](concepts/leakage.md) — what
  {func}`~otwin.forecast.evaluate` refuses to do for you
- [Calibrated intervals](concepts/conformal.md) — the three constructions and
  when each is right
- [Guides](guides/index.md) — one page per ISO 13374 block
