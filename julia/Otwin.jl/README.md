# Otwin.jl

**Otwin.jl wraps the Python implementation of [Otwin](https://github.com/otwin-core/otwin) through [PythonCall](https://github.com/JuliaPy/PythonCall.jl). It does not reimplement any of it.** The first time you load the package, [CondaPkg](https://github.com/JuliaPy/CondaPkg.jl) installs the Python side: a private Python and the `otwin` package from PyPI. You do not need a Python of your own.

Every simulation, fit, calibration and audit runs in Python's `otwin`. Otwin.jl converts Julia values in and out, so the numbers you get from Julia are the same numbers Otwin gives in Python.

```julia
using Pkg
Pkg.add(url = "https://github.com/otwin-core/otwin", subdir = "julia/Otwin.jl")
```

> **Python version needed.** Models, fitting and calibrated forecasts work with
> `otwin` 2.0.1, the current release on PyPI. `coverage_audit`, `margin_risk`
> and `transfer_validation` need the next release. Until it is out, they
> raise an error that says so. To use them now, see
> [Using a Python you manage](#using-a-python-you-manage).

## What it does

Build or load a model, fit it to measurements, forecast with a calibrated
range, and audit the range on data the model never saw.

```julia
using Otwin

# Build: Otwin's components, called with Julia keywords
hyd  = components(:hydraulic)
tank = hyd.Tank(20.0; level = 2.0, name = "tank")
out  = hyd.Orifice(0.002; discharge_coefficient = 0.6, name = "outlet")
pump = hyd.FlowSource(; name = "pump")
air  = hyd.Atmosphere(; name = "air")
sys  = system(tank, out, pump, air)
connect!(sys, tank.port, out.a, pump.a)
connect!(sys, out.b, pump.b, air.port)
model = compile(sys)                                   # or load_model("tank.json")

# Fit: measurement vectors in, a FitResult out
fit = fit_parameters(model, t, "tank.level" => reading, ["outlet.discharge_coefficient"];
                     inputs = Dict("pump" => pump_flow))   # a vector, a number or f(t)
fit.values                                             # Dict("outlet.discharge_coefficient" => 0.69)
fit.identified                                         # Dict("outlet.discharge_coefficient" => true)

# Forecast with a calibrated range, from any forecaster f(history, horizon) -> Vector
cal  = rolling_origin_residuals(forecaster, reading[1:720]; step = 6, max_horizon = 36)
band = calibrate(cal.residuals, cal.horizons; level = 0.9, max_horizon = 36)
fc   = forecast(forecaster, reading, 36, band)         # (prediction, lower, upper, extrapolated)

# Audit: observed coverage, bias and width, by horizon tranche
audit = coverage_audit(observed, prediction, lower, upper;
                       level = 0.9, horizons = horizon, tranches = [0, 6, 18, 36])
audit.tranches[2].coverage                             # Float64, or nothing if refused
to_html(audit); to_json(audit)                         # the report sections Otwin renders
```

| Function | Returns | Python it calls |
|---|---|---|
| `components`, `system`, `connect!`, `chain`, `compile` | `Model` | `otwin.components`, `otwin.System`, `otwin.compile` |
| `load_model`, `save_model` | `Model`, path | `Model.load`, `Model.save` |
| `simulate(model, t; x0, inputs, solver)` | `Trajectory`: `tr["tank.level"]` | `Model.simulate` |
| `fit_parameters(model, t, measurements, names)` | `FitResult` | `otwin.fit_parameters` |
| `rolling_origin_residuals(f, series)` | `(residuals, horizons)` | `otwin.forecast.rolling_origin_residuals` |
| `calibrate(res, hor; level, method)` | `Band` | `horizon_conformal`, `split_conformal` |
| `interval(band, pred)`, `forecast(f, history, h, band)` | `NamedTuple` | `ConformalBand.apply` |
| `coverage_audit(obs, pred, lo, up; level, tranches)` | `CoverageAudit` | `otwin.audit.coverage_audit` |
| `margin_risk(residuals, reference, margins)` | `MarginRisk` | `otwin.audit.margin_risk` |
| `transfer_validation(units, fit, horizon_levels; level)` | `TransferValidation` | `otwin.forecast.transfer_validation` |

**Julia types in and out.**
- **Inputs:** series are `Vector`s. Anything keyed by a model name is a `Dict` or a `Pair`. Inputs can also be Julia functions of time.
- **Forecasters:** forecasters, and the `fit` passed to `transfer_validation`, are ordinary Julia functions. Python calls them.
- **Results:** results are structs of `Vector{Float64}`, `Dict` and `NamedTuple`.
- **Refusals:** where Otwin refuses to give a number, for example a tranche with too few contrasts or a margin with too few residuals, the field is `nothing` and `refusal` says why. It is never zero.
- **Tables:** `table(x)` gives a column table (a `NamedTuple` of vectors), with refusals as `missing`.
- **DataFrames:** DataFrames is optional. Load it and `DataFrame(audit)` works on every audit result.
- **Escape hatch:** every wrapper keeps the Python object as `x.py`, for anything not wrapped.

## Examples

Both run in CI on every change to this package or to the Python package.

```bash
cd julia/Otwin.jl
julia --project=examples -e 'using Pkg; Pkg.instantiate()'
julia --project=examples examples/water_tank.jl       # about 15 s
julia --project=examples examples/mtk_comparison.jl   # first run compiles ModelingToolkit
```

- [`examples/water_tank.jl`](examples/water_tank.jl): a storage tank fed by a
  pump, draining through an outlet, with a town drawing water that the model
  does not know about. The example fits the outlet, saves and reloads the
  model, calibrates a 90 % range on five days and audits it on three unseen
  days by horizon. The audit finds where the range holds and where it does
  not.
- [`examples/mtk_comparison.jl`](examples/mtk_comparison.jl): the same tank
  written in ModelingToolkit and simulated with OrdinaryDiffEq. The two models
  agree to micrometres over a day. Otwin.jl then calibrates and audits the
  forecasts of both in the same way, and prints a table that compares them.

## Using a Python you manage

To use an existing Python instead of the one CondaPkg builds, for example a
checkout of otwin installed with `pip install -e .`, set two variables before
starting Julia:

```bash
export JULIA_CONDAPKG_BACKEND=Null
export JULIA_PYTHONCALL_EXE=/path/to/that/python
```

This is how CI tests the package against the Python in the same commit.

## What it does not do

Otwin.jl adds no numerics. If something is not computed by Python's `otwin`,
it is not in this package. A Julia-native implementation would be checked
against the [otwin-spec](https://github.com/otwin-core/otwin-spec) conformance
suite, not against this wrapper.
