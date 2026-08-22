<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/otwin_wm.png"  width="40%">

 
# Model. Estimate. Quantify. Validate.

</div>


Otwin is a Python library used to build Digital Twins of physical equipment from physics, data or both, keep them in step with the machine from live measurements, and forecast with an uncertainty band whose coverage has been measured and a skill score earned out of sample against a reference that is hard to beat.

<br>

<div align="center">
  
[![PyPI](https://img.shields.io/pypi/v/otwin?color=1a4fd6&cacheSeconds=3600)](https://pypi.org/project/otwin/)
[![Python](https://img.shields.io/pypi/pyversions/otwin?cacheSeconds=3600)](https://pypi.org/project/otwin/)
[![CI](https://github.com/otwin-core/otwin/actions/workflows/ci.yml/badge.svg)](https://github.com/otwin-core/otwin/actions/workflows/ci.yml)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14061/badge)](https://www.bestpractices.dev/projects/14061)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/otwin-core/otwin/badge)](https://scorecard.dev/viewer/?uri=github.com/otwin-core/otwin)


[![License](https://img.shields.io/badge/license-Apache%202.0-brightgreen?style=flat-square)](https://opensource.org/license/apache-2-0)

<br>

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/overview.png"  width="100%">

</div>

<br>

## What otwin is for

A digital twin is a model of one particular physical asset (machine, pump, battery bank, heat exchanger, chemical reactor, a complete process) kept up to date from that asset's own measurements and run forward to support decissions about it. 

> Electrical grid. This distribution transformer keeps running above nameplate on hot afternoons. How much longer can it do that before the winding reaches its thermal limit?
> 
> Renewable generation and storage. This battery bank is three years into its life. How much can I commit to the market next week and still be certain of delivering it?

> Water treatment. The transfer pumps need more power every month for the same flow. How many weeks of margin are left before the duty pump can no longer hold its setpoint?

> How much capacity does this Li-ion battery still have? When will it cross the retirement threshold?


<br>
 
## Choosing the model structure

Physical assets like real equipment or complete processess are rarely fully known or fully unknown. Otwin provides five model classes and the manifest records which one you used, because the guarantees available to you depend on the answer.

Digital Twins can be classified as:
| Type |Description |
|---|---|
| <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/White_box.png" height="80"> | Whithe-box models: We know the exact equations and it's parameters so we can model the asset behavior for long time horizons and different scales|
| <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="80">| Grey-box models: we have a descriptive equation, rooted in physical principles, that roughly explain asset behavior. We collect data from the real asset and use this data to fine-tune the descriptive equation. These models are also called **Hybrid Digital Twins** because they combine a white-box model (the equation) and a black-box models (the part we learn from the data) |
| <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Black_box.png" height="80"> | Black-box models: These models use real data for modelling the asset using Machine Learning methods. They are black because we do not have the answer to the question why the model ooutput is this?. Data-driven models, despite being widely used, has a limitation for engineering applications: fundamental laws of physics can be violeted because nothing constrain the model with the reallity. So unseen data, longer time horizons or different range scales can't be predicted from the data without the guarantee that they are not going to violate any physical law | 



| Model class | AI model | What you provide | Where it comes from | What the structure guarantees |
|---|---|---|---|---|
| `port_hamiltonian` | <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/White_box.png" height="40"> | `H`, `J`, `R`, `g` — energy, exchange, dissipation, ports | Known physics | Energy bounded by port supply, for any parameters and any step size |
| `irreversible_phs` | <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/White_box.png" height="40"> |The above plus entropy `S` and either `L` or a modulating `gamma` | Known physics with irreversible transport | The above, plus entropy production `sigma >= 0` on every call |
| `empirical_law` | <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="40"> |A trend law and its parameters | Fitted to data; no energy function exists | Nothing structural. Everything here is earned by validation |
| `learned_phs` |<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="40"> |Network widths; `J`, `R`, `H`, `g` are learned | Data, with physics imposed on the architecture | Skew `J` and PSD `R` hold **by construction**, whatever the weights learn |
| `composite` | <img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="40"> |A physical prior plus a learned or empirical correction | Both | Inherits a basic physical structure that is validated with the observed data |


The library computes which side you are on rather than taking your word for it:

```
TwinManifest.is_white_box   ->   True only when estimated == ()
```

A white-box twin can be validated against an exact answer. A grey-box twin cannot, and must be
validated against held-out data with a baseline instead. Both paths are supported by Otwin.

<br>

## What makes otwin different

Three things:

- **1. The uncertainty is measured, not declared.** A stated 90 % interval means nothing until
somebody counts how often it contains the truth. `Interval.is_validated` stays `False` until it has
been counted. The conformal example below finishes at a measured 90 % on sixty held-out cycles
against a 90 % target; when the calibration set is too small to support the level requested, the
library returns an infinite half-width, loudly, rather than a comfortable-looking one.

- **2. The validation is leakage-free and beats something.** Partitions are out-of-sample by default,
a reference forecaster is mandatory, and the report leads with the skill score against the *hardest*
of persistence, drift, mean and seasonal-naive. The model is handed history and a horizon, never the
test values.

- **3. The twin can say no.** Operating range, forecast horizon and calibration status are recorded in
the manifest, and a request outside them is refused with a reason rather than answered with a
number.

<br>

## What you can do with Otwin

| Task | Module | Application|
|---|---|---|
| Write and simulate a physical model | `otwin.model` | Tank, cell, machine, thermal network, drivetrain, reactor, exchanger |
| Learn what the physics does not tell you | `otwin.model`, `otwin.forecast` | Structure-constrained networks, GP residuals over a physical prior, empirical trend laws |
| Read live data from equipment | `otwin.io` | SunSpec Modbus, Modbus TCP/RTU, plus simulators so you can work without hardware |
| Clean and align that data | `otwin.signal` | Resampling, gap detection, out-of-order samples, coverage reporting |
| Correct model state from measurements | `otwin.estimate` | Extended Kalman filter, moving-horizon estimation with state bounds, energy-consistent observer |
| Quantify uncertainty | `otwin.forecast` | Conformal bands, ensembles, CRPS, PIT, coverage curves, recalibration |
| Measure the forecast | `otwin.forecast` | Out-of-sample protocols, reference forecasters, skill scores |
| Record where the model is valid | `otwin.advise` | Operating range and horizon the model was validated over |

<br>

## Quick install

```bash
pip install otwin
```

Otwin uses just NumPy and SciPy libraries. Connectors, learned models and Gaussian-process intervals are
optional, so if you only want the modelling and validation layers you don't nee to install a Modbus
stack or a Neural Network library.

```bash
pip install "otwin[field]"     # Modbus and SunSpec connectors
pip install "otwin[gp]"        # Gaussian-process residuals and intervals
pip install "otwin[nn]"        # learned models (pulls in PyTorch)
pip install "otwin[all]"       # everything
```

Requires Python 3.10 or later.

<br>

## Get started

A mass on a spring with a damper. Two energy stores — the spring and the moving mass — and one
lossy element.

```python
import numpy as np
from otwin.model import PortHamiltonianSystem, integrate_phs

# State: x[0] = spring displacement q [m], x[1] = momentum p = m*v [kg m/s]
# k = 2 N/m, m = 1 kg, c = 0.3 N s/m
osc = PortHamiltonianSystem(
    H      = lambda x: 0.5 * 2.0 * x[0]**2 + 0.5 * x[1]**2,   # stored energy [J]
    grad_H = lambda x: np.array([2.0 * x[0], x[1]]),          # [force, velocity]
    J      = lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),   # spring <-> mass exchange
    R      = lambda x: np.array([[0.0, 0.0], [0.0, 0.3]]),    # the damper
    g      = lambda x: np.array([[0.0], [1.0]]),              # external force on the mass
    n_states=2, n_inputs=1,
)

t   = np.linspace(0, 20, 400)      # 20 s
u   = np.zeros((400, 1))           # ports closed: no external force
sol = integrate_phs(osc, np.array([1.0, 0.0]), t, u)

E = np.array([osc.energy(x) for x in sol["x"]])
print(f"Stored energy: {E[0]:.4f} J at t=0  ->  {E[-1]:.4f} J at t=20 s")
print(f"Largest single-step energy INCREASE: {max(np.max(np.diff(E)), 0.0):.2e} J")
```

```
Stored energy: 1.0000 J at t=0  ->  0.0024 J at t=20 s
Largest single-step energy INCREASE: 0.00e+00 J
```

That second line `Largest single-step energy INCREASE: 0.00e+00 J` show that with no force applied, stored energy never rises because the model form makes it impossible.

If you want to see a full workflow that simulates a grid-scale battery bank end to end. The workflow read the device, condition the signal, estimate state, forecast, validate, and refuse the questions it has not earned the right to answer. No hardware required.

```bash
git clone https://github.com/otwin-core/otwin.git
cd otwin && pip install -e ".[dev]"
python examples/bess_end_to_end.py
```

<br>

<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="80"> 

</div> 

## When the physics is known

Choose a port-Hamiltonian structure and conservation stops being something you check and becomes
something you cannot violate: it is an algebraic property of how the model is written, so it
survives any parameter set, any step size and any length of run.

In the first example below, stored energy does not rise on a single step of a 400-step simulation
with the ports closed, where `scipy.integrate.solve_ivp` on the same right-hand side gains
`3.2e-05 J`. On the reference cases the same structure reproduces closed-form answers to the limit of
double precision — a pumped-hydro round-trip efficiency agrees with its analytic value to a relative
error of `9.6e-16` — and the irreversible form holds the second law across a full reactor run in
which the same process written as a plain energy balance violates it on 91 % of steps.

*What none of this gives you:* accuracy. A model with the wrong parameters is still wrong — it is
simply wrong without violating the energy balance. Accuracy is measured separately, and that is what
the rest of the library is for.

<br>

### Writing a first-principles model using Port Hamniltonian Systems

You describe the system with **four functions of the state**. The dynamics follow from them:

```
ẋ = dx/dt = ( J(x) - R(x) ) @ grad_H(x)  +  g(x) @ u        # how the state moves (for example how energy changes)
y     = g(x).T @ grad_H(x)                              # what the port delivers
```

| You write | It means | Water tank example |
|---|---|---|
| `H(x)` | Total stored energy [J] | `0.5 * rho * g * A * h**2` |
| `grad_H(x)` | Gradient of that energy — the **effort** variable: pressure, voltage, force, temperature | Pressure at the base |
| `J(x)` | Power routed **between** internal stores, losslessly. Must satisfy `J = -J.T` | Zero — only one store |
| `R(x)` | Dissipation to heat. Must be positive semidefinite | Outlet orifice loss |
| `g(x)` | The ports — where power crosses the boundary | Inlet pipe |

`u` is the port input (a flow: m³/s, A, N) and `y` the port output (an effort: Pa, V, m/s). Their
product `y.T @ u` is power in watts.

![storage](https://raw.githubusercontent.com/otwin-core/otwin/main/assets/storage.png)

### Applications

|  | What `J`, `R`, `H`, `g` already are to you |
|---|---|
| Mechanical | A bond graph. `J` is the junction structure with its transformers and gyrators, `R` the R-elements, `H` the C- and I-elements |
| Electrical | An equivalent circuit. `grad_H` are node voltages and branch currents, `J` the lossless interconnection, `R` the resistive network |
| Chemical / process | An energy balance on a control volume, with internal exchange separated from irreversible loss |
| Control | A dissipative system in the sense of Willems. `H` is the storage function, `y.T @ u` the supply rate |

The library only asks you to write the four parts down separately instead of collapsing them into a
single right-hand side.

![dc](https://raw.githubusercontent.com/otwin-core/otwin/main/assets/dc.png)

### A complete model

![tank](https://raw.githubusercontent.com/otwin-core/otwin/main/assets/tank_block.png)

```python
import numpy as np
from otwin.model import PortHamiltonianSystem

A, a, c_d, rho, g_acc = 1.0, 0.1, 0.6, 1000.0, 9.81   # area, orifice, Cd, density, gravity

tank = PortHamiltonianSystem(
    H      = lambda x: 0.5 * rho * g_acc * A * float(x[0])**2,       # energy of the column
    grad_H = lambda x: np.array([rho * g_acc * A * x[0]]),           # pressure at the base [Pa]
    J      = lambda x: np.zeros((1, 1)),                             # one store, nothing circulates
    R      = lambda x: np.array([[c_d * a * np.sqrt(2 * g_acc / max(float(x[0]), 1e-9))
                                  / (rho * g_acc * A**2)]]),         # Torricelli outflow
    g      = lambda x: np.array([[1.0]]),                            # inlet pipe
    n_states=1, n_inputs=1,
)

for name, (ok, margin) in tank.check_structure(np.array([2.0])).items():
    print(f"{name:8s} {'pass' if ok else 'FAIL'}   margin {margin:.3e}")
```

```
J_skew   pass   margin 0.000e+00
R_psd    pass   margin 1.916e-05
```

`check_structure` is worth running every time you write a model. It catches sign errors and
mis-transposed matrices immediately, before they turn into a plausible-looking wrong answer.

This model ships as `otwin.model.water_tank`. Also in the library you can find other examples: `mass_spring_damper`,
`dc_motor`, `pumped_hydro` and `heat_exchanger`.

### The port as feedback

A converter holding constant power, a thermostat, a droop-controlled inverter, a level valve — in
all of them `u` depends on the state. If you pass a callable, the control law is evaluated at the step
midpoint inside the implicit solve, which keeps the discrete power balance intact:

```python
import numpy as np
from otwin.model import water_tank, integrate_phs

tank = water_tank()
t    = np.linspace(0, 600, 601)          # 10 minutes

# Inlet valve on level feedback: u is not a schedule, it is a control law.
res = integrate_phs(tank, np.array([2.0]), t,
                    u=lambda t, x: np.array([max(0.0, 5.0 * (1.5 - float(x[0])))]))

h, q = np.array(res["x"])[:, 0], np.array(res["u"])[:, 0]
print(f"level  {h[0]:.3f} m -> {h[-1]:.3f} m")
print(f"inflow {q[0]:.3f} -> {q[-1]:.3f} m3/s   (outflow at that level: "
      f"{0.6 * 0.1 * np.sqrt(2 * 9.81 * h[-1]):.3f} m3/s)")
```

```
level  2.000 m -> 1.436 m
inflow 0.000 -> 0.319 m3/s   (outflow at that level: 0.319 m3/s)
```

The tank settles below its 1.5 m setpoint, because proportional-only control leaves an offset. `res["u"]` is what the port actually did. with a governing law there is no schedule to read back.

### Processes that produce entropy

A chemical reaction, heat conduction, a heat exchanger — any irreversible process needs more than
reversible-plus-dissipative. `IrreversiblePHS` adds an entropy term to Port Hamiltonian Systems with `sigma >= 0` enforced
structurally; `IrreversiblePHS.from_modulated(...)` gives the Ramírez–Maschke–Sbarbaro form that
most chemical reactor and heat exchanger models fall out. The `IrreversiblePHS` checked on every
call the second law. `otwin.model.heat_exchanger` is a worked instance, with `effectiveness_ntu` for its steady-state check.

<br>

<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Grey_box.png" height="80"> 

</div> 

## The grey area: governing equations are not fully known

This is the most common case we can find. Combine all governing equations can be mathematically tricky and computationally unfeasible. These limitation can be managed with an hybrid approach combining basic governing equation plus observed data.

### The system only degrades

Capacity fade, wear, fatigue and corrosion have no conserved energy function and no port. Forcing
them into a port-Hamiltonian frame is the most common conceptual error in this field, so otwin
refuses to help you do it: `EmpiricalLawModel` deliberately does **not** extend `TwinModel`, because
a fade law has no state derivative and a stub `rhs` returning zeros would be exactly that error
wearing a disguise.

What you write instead is a transparent trend law with fitted parameters and a bounded residual.
`FoulingLaw` and `kern_seaton_fouling` ship as worked instances for exchanger fouling. Everything
downstream — estimate, quantify, validate — is unchanged, which is the whole point.

### The structure is known and the content is not

`PortHamiltonianNN` learns `H`, `J`, `R` and `g` as networks, with `J = A - A.T` and `R = L @ L.T`
so that skew-symmetry and positive semidefiniteness hold **by construction, whatever the weights
learn**. Passivity is not a training objective that might be reached; it is a property of the
parameterisation. `derivative_loss` and `passivity_penalty` are the training terms — the penalty
only conditions the optimisation, since the structure has already made violation impossible.

### The physics is right in form and wrong in detail

The most useful hybrid in practice. Keep the analytic model as a prior and learn the residual, so
the mean stays physically consistent and the correction carries calibrated uncertainty:

```python
import numpy as np
from otwin.forecast import GPPHS

# The plant has quadratic drag. The analytic model we trust only knows linear damping,
# so the physics is right in structure and wrong in the loss term.
def truth(x, u):
    return np.array([x[1], -2.0*x[0] - 0.9*x[1]*abs(x[1])])

def phs_prior(x, u):
    return np.array([x[1], -2.0*x[0] - 0.3*x[1]])

rng  = np.random.default_rng(0)
X    = rng.uniform(-1.2, 1.2, size=(120, 2))
dXdt = np.array([truth(x, None) for x in X])

np.random.seed(0)   # GPPHS does not yet seed its own hyperparameter restarts
hybrid = GPPHS(n_states=2, prior_dynamics=phs_prior).fit(X, dXdt)

test  = rng.uniform(-1.0, 1.0, size=(40, 2))
exact = np.array([truth(x, None) for x in test])
mean, std = hybrid.predict(test, return_std=True)

err_prior  = np.sqrt(np.mean((np.array([phs_prior(x, None) for x in test]) - exact)**2))
err_hybrid = np.sqrt(np.mean((mean - exact)**2))
far        = hybrid.predict(np.array([[3.0, 3.0]]), return_std=True)[1].mean()

print(f"prior alone   RMSE on dx/dt : {err_prior:.4f}")
print(f"prior + GP    RMSE on dx/dt : {err_hybrid:.4f}")
print(f"GP std inside the fitted range : {std.mean():.4f}")
print(f"GP std far outside it          : {far:.4f}")
```

```
prior alone   RMSE on dx/dt : 0.1731
prior + GP    RMSE on dx/dt : 0.0055
GP std inside the fitted range : 0.0056
GP std far outside it          : 0.4593
```

Thirty times closer on the derivative, and — the part that matters operationally — the predictive
standard deviation is two orders of magnitude larger at a state the GP has never seen. The
correction knows when it is extrapolating even though the prior does not.

Two notes on running this yourself. scikit-learn will warn that one state dimension has nothing
to learn — it is right: the prior already gets that row exactly, and a residual GP fitted to
zeros is the correct answer. And `GPPHS` does not currently seed the restarts of its own
hyperparameter search, so without the `np.random.seed` line above the last digits move between
runs.

### The parameters themselves are uncertain

A measured orifice, a tolerance band on a capacitance, a coefficient quoted to two figures. Propagate
it by making the spread the model:

```python
import numpy as np
from otwin.model import water_tank
from otwin.forecast import Ensemble

# Parameter uncertainty, not measurement noise: the orifice was measured to +/-10 %.
members = [water_tank(a=a) for a in (0.090, 0.095, 0.100, 0.105, 0.110)]
ens     = Ensemble(members)

t, u  = np.linspace(0, 5, 101), np.zeros((101, 1))
band  = ens.forecast_interval(np.array([2.0]), t, u, level=0.90)
plant = water_tank(a=0.102).forecast(np.array([2.0]), t, u)["x"]   # the real orifice

for k in (0, 50, 100):
    print(f"t={t[k]:4.2f} s   band {band['lower'][k,0]:.3f}..{band['upper'][k,0]:.3f} m"
          f"   plant {plant[k,0]:.3f} m")
print(f"plant inside the band on {np.mean((plant >= band['lower']) & (plant <= band['upper'])):.0%} of steps")
```

```
t=0.00 s   band 2.000..2.000 m   plant 2.000 m
t=2.50 s   band 1.107..1.236 m   plant 1.156 m
t=5.00 s   band 0.476..0.656 m   plant 0.542 m
plant inside the band on 100% of steps
```

An ensemble of identical deterministic members has zero spread. That is correct, not a bug — the
members must genuinely differ for the spread to mean anything.



## Estimating state from measurements

| Estimator | Use it when |
|---|---|
| `ExtendedKalmanFilter` | The standard case: nonlinear model, Gaussian-ish noise |
| `MovingHorizonEstimator` | The state has physical bounds. A state of charge is not allowed to be 1.05 |
| `EnergyConsistentObserver` | The correction itself must respect the energy balance |

The moving-horizon estimator accepts **box constraints on the state**, and on the reference case it
is also 39 % more accurate for it. The energy-consistent observer limits any correction so it cannot
increase stored energy beyond what the ports supplied; the trade-off is in the docstring — with
ports closed the allowed increase is zero, so a correction that merely reflects an under-energetic
prior is rejected too.

---

## Quantifying uncertainty

An interval has meaning if it's **coverage** has been measured: a stated 90 % interval should
contain the truth about 90 % of the time.

```python
import numpy as np
from otwin.forecast import rolling_origin_residuals, horizon_conformal

rng      = np.random.default_rng(0)
cycles   = np.arange(300)
capacity = 1.0 - 2.6e-4*cycles - 4.0e-3*np.sqrt(cycles) + rng.normal(0, 1.5e-3, 300)

class FadeLaw:
    """Fits C = C0 - a*n - b*sqrt(n) to the history, then extrapolates it."""
    def forecast(self, history, horizon):
        h = np.asarray(history, float).ravel()
        n = np.arange(len(h))
        coef, *_ = np.linalg.lstsq(np.column_stack([np.ones_like(n), n, np.sqrt(n)]), h, rcond=None)
        f = np.arange(len(h), len(h) + horizon)
        return (np.column_stack([np.ones_like(f), f, np.sqrt(f)]) @ coef).reshape(-1, 1)

train = capacity[:240]
def refit_forecast(history, horizon):
    return FadeLaw().forecast(history, horizon).ravel()

# Refit at earlier origins and keep genuine h-step-ahead errors -- not in-sample residuals.
residuals, horizons = rolling_origin_residuals(refit_forecast, train, step=5, max_horizon=60)
band = horizon_conformal(residuals, horizons, level=0.90, max_horizon=60)

lower, upper = band.apply(refit_forecast(train, 60))
truth = capacity[240:300]                      # the 60 cycles the band never saw

print(f"{residuals.size} residuals over horizons 1..{horizons.max()}")
print(f"half-width {(upper[0]-lower[0])/2:.4f} at h=1, {(upper[-1]-lower[-1])/2:.4f} at h=60")
print(f"measured coverage: {np.mean((truth >= lower) & (truth <= upper)):.0%}  (target 90%)")
```

```
1590 residuals over horizons 1..60
half-width 0.0023 at h=1, 0.0030 at h=60
measured coverage: 90%  (target 90%)
```


## Validating a forecast

A model is not validated until its forecasts have been compared, out of sample, against a reference
that is hard to beat. Same series and same `FadeLaw` as above:

```python
from otwin.forecast import evaluate

print(evaluate(FadeLaw(), capacity.reshape(-1, 1),
               protocol="rolling_origin", n_folds=5, horizon=30))
```

```
EvalReport (rolling_origin, 5 folds)
────────────────────────────────────────────────────────────────
Skill Score (vs best baseline): 0.77 (77% better)
Baseline: persistence

Point Metrics:
  RMSE      0.0017 (baseline: 0.0074)
  MAE       0.0014 (baseline: 0.0064)
  NRMSE     0.1141
  MASE      0.8292
  THEIL_U   0.2395
────────────────────────────────────────────────────────────────
```

Three conventions are built into that one call, because each corrects a mistake that is easy to make
and hard to notice:

- **Partitions are out-of-sample by default.** A random split on a time series trains on Tuesday and
  Thursday to predict Wednesday, which measures interpolation. `random_split` exists, warns loudly,
  and marks the report.
- **A reference forecaster is required, and the report leads with the skill score.** Model error
  divided by reference error, against the *hardest* of persistence, drift, mean and seasonal-naive.
  `R²` is available but never shown first: on a trending series it commonly reads above 0.95 for a
  model that loses to repeating the last observed value.
- **The model is given history and a horizon, never the test values.** If you supply exogenous
  drivers with `exog=`, every column is checked against the target first, and the report records
  that drivers were used — a skill score computed with the future of the drivers in hand is not
  comparable with one computed without.


## Recording where the model is valid

The manifest carries which structure you chose, which parameters were estimated, how the model was
validated and how the band was calibrated. The envelope turns that record into an answer or a
refusal.

```python
from otwin.advise import Envelope
from otwin.interfaces import TwinManifest, Provenance

twin = TwinManifest(
    name="cell-A3",
    model_class="empirical_law",          # one of: port_hamiltonian, irreversible_phs,
    model_kind="capacity_fade",           #         empirical_law, learned_phs, composite
    n_states=1, n_inputs=1,
    parameters={"C0": 0.9993, "a": 2.61e-4, "b": 4.02e-3},
    estimated=("C0", "a", "b"),           # three parameters came from data, so: grey box
    provenance=Provenance(created="2026-08-22", otwin_version="0.3.0", seed=0),
    validation=TwinManifest.validated_by("rolling_origin", rmse=0.0017, skill_score=0.77),
    calibration=TwinManifest.calibrated_by("horizon_conformal", empirical_coverage=0.90,
                                           level=0.90, max_horizon=60),
)
print("white box?", twin.is_white_box, " validated?", twin.is_validated)

envelope = Envelope(state_bounds=[(0.60, 1.00)], max_horizon=60)
print(envelope.check(state=[0.83], horizon=30,  manifest=twin).explain())
print(envelope.check(state=[0.83], horizon=180, manifest=twin).explain())
```

```
white box? False  validated? True
inside the validated envelope (horizon 30 <= 60; operating point inside the identified range;
validated, leakage-free)

outside the validated envelope:
  - horizon: beyond the validated forecast horizon (asked for 180, validated to 60)

This is a refusal, not a failure. The twin has not been shown to answer this question, and
returning a number anyway would hide that.
```

Same discipline as stating the calibration range of an instrument: a reading outside the calibrated
range is reported as such, not returned as a number. `is_validated` is deliberately strict —
`leakage_free` must be the boolean `True`, not merely truthy, because manifests arrive from MATLAB
and Julia where a boolean can round-trip as `1` or as the string `"false"`.

---

## The workflow, end to end

The modules follow the six data-processing blocks of **ISO 13374**, so the layout matches the
reference architecture used in condition-monitoring practice.

| Stage | Module | What happens |
|---|---|---|
| Data acquisition | `otwin.io` | Read the device over SunSpec or Modbus; normalise units |
| Data manipulation | `otwin.signal` | Resample to a uniform grid, find gaps, report coverage |
| State detection | `otwin.estimate` | Correct model state from measurements |
| Health assessment | `otwin.model` | Simulate the physical, learned or empirical model |
| Prognostic assessment | `otwin.forecast` | Forecast, score against a reference, calibrate the band |
| Advisory generation | `otwin.advise` | Report whether the request is inside the validated envelope |


## The otwin project

| Repository | What it is |
|---|---|
| [**otwin**](https://github.com/otwin-core/otwin) | The library. Start here |
| [**otwin-spec**](https://github.com/otwin-core/otwin-spec) | The specification and its conformance suite — reference cases with closed-form answers, used to verify that any implementation is correct, in any language |
| [**otwin-hybrid**](https://github.com/otwin-core/otwin-hybrid) | A worked case in Python, Julia and R: predicting end of life of a lithium-ion cell from the first 40 % of its life. Opens in Colab in one click |
| [**otwin-systems**](https://github.com/otwin-core/otwin-systems) | The growing catalogue of physical models, each shipped with a closed-form result it must reproduce |

Julia and MATLAB implementations are open for contributors — `otwin-spec` tests over a subprocess
interface, so a second-language implementation has an objective completion criterion: pass the suite
unmodified. See [CONTRIBUTING.md](CONTRIBUTING.md) for that and for a list of self-contained project
topics.


## Issues, contribution and citation
- **Questions and bugs** — [open an issue](https://github.com/otwin-core/otwin/issues)
- **Contributing** — [CONTRIBUTING.md](CONTRIBUTING.md). The catalogue of physical models is the
  easiest place to start, and each contribution is a system you already know plus one closed-form
  result it must reproduce
- **Citing** — each repository carries a `CITATION.cff`

Some references:

- van der Schaft, A. & Jeltsema, D. (2014). *Port-Hamiltonian Systems Theory: An Introductory
  Overview.* Foundations and Trends in Systems and Control.
- Willems, J. C. (1972). *Dissipative dynamical systems.* Arch. Rational Mech. Anal. 45(5).
- Karnopp, D., Margolis, D. & Rosenberg, R. *System Dynamics: Modeling, Simulation, and Control of
  Mechatronic Systems.* Wiley.
- Ramírez, H., Maschke, B. & Sbarbaro, D. (2013). *Irreversible port-Hamiltonian systems.* Chemical
  Engineering Science 89.
- Greydanus, S., Dzamba, M. & Yosinski, J. (2019). *Hamiltonian Neural Networks.* NeurIPS 32.
- Rasmussen, C. E. & Williams, C. K. I. (2006). *Gaussian Processes for Machine Learning.* MIT Press.
- Vovk, V., Gammerman, A. & Shafer, G. (2005). *Algorithmic Learning in a Random World.* Springer.
- Gneiting, T. & Raftery, A. E. (2007). *Strictly proper scoring rules, prediction, and estimation.*
  JASA 102(477).
- ISO 13374 — *Condition monitoring and diagnostics of machines.*
- ISO 13381-1:2015 — *Condition monitoring and diagnostics of machines: prognostics.*

Licensed under Apache 2.0.
