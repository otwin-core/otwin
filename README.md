<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/brand/otwin-github-header-1a.png" width="100%">

# Digital twins of engineering equipment, with forecasts you can check

[![License](https://img.shields.io/github/license/otwin-core/otwin?color=1a4fd6\&cacheSeconds=86400)](https://github.com/otwin-core/otwin/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/otwin?color=1a4fd6\&cacheSeconds=3600)](https://pypi.org/project/otwin/)
[![crates.io](https://img.shields.io/crates/v/otwin-core?color=1a4fd6&logo=rust&label=crates.io)](https://crates.io/crates/otwin-core)
[![Python](https://img.shields.io/github/actions/workflow/status/otwin-core/otwin/ci.yml?branch=main\&label=python\&logo=github)](https://github.com/otwin-core/otwin/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/otwin-core/otwin/badge)](https://scorecard.dev/viewer/?uri=github.com/otwin-core/otwin)
[![REUSE status](https://api.reuse.software/badge/github.com/otwin-core/otwin)](https://api.reuse.software/info/github.com/otwin-core/otwin)
[![SLSA 2](https://slsa.dev/images/gh-badge-level2.svg)](https://github.com/otwin-core/otwin/attestations)

</div>

<br>

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-battery-twin.gif" width="100%" alt="A battery cell on a cycler. The twin follows its capacity cycle by cycle, forecasts it with a 90 % range, and asks for a replacement before the cell reaches end of life.">

<sub>Real data from 44 cells the twin never saw (Severson et al., 2019). The replacement order came before end of life on every cell, a median of 76 cycles ahead. The fade law is fitted with SciPy. Otwin calibrates the range on 126 other cells, measures how often it holds on the unseen ones, and applies the rule. For a stated 90 % it held 96 % of the time, so the range is wider than it needs to be. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/battery_twin.py)</sub>

<br>

# What Otwin does

A digital twin is a model of **one particular machine**, kept up to date with that machine's own measurements and used to decide what to do with it: when to clean a filter, when to replace a cell, when to call on reserve power.

Otwin is an open-source Python library for building those twins and for checking them. It does four things:

- **Build a physical model from parts.** You connect tanks, pipes, pumps, masses, springs, cells and inertias the way you would draw them. Otwin writes the equations and runs them in a Rust engine. The compiled model carries its own energy balance, so you can check at every step that it never creates energy.
- **Fit it to the machine.** It estimates what a data sheet does not give, such as fouling or inertia, from measurements, and says when the data cannot determine a value.
- **Forecast with a range that has been tested.** The range comes from the errors the model actually made on data it never saw, and Otwin measures whether a stated 90 % really holds 90 % of the time.
- **Refuse when the evidence is not there.** If a question goes beyond what the twin was validated for, or there is not yet enough data to support a range, Otwin says so instead of returning a number.

The last two work with any model you can call from Python, not only with models built in Otwin.

# Otwin and the tools you already use

Most industrial models are built in two families of tools, and they are very good at it:

- **Modelica**, through Dymola, OpenModelica or Wolfram SystemModeler, with decades of libraries for fluids, power plants, batteries, buildings and vehicles. Models move between these tools as **FMU** files, defined by the open [FMI](https://fmi-standard.org) standard.
- **Julia**, through [ModelingToolkit](https://github.com/SciML/ModelingToolkit.jl) and the SciML ecosystem, and [Dyad](https://juliahub.com/products/dyad) from JuliaHub, which builds on the same ecosystem and adds AI agents that check the physics of the models they write.

If your model already lives in one of them, keep it there. Otwin adds what those tools are not built to answer once a model is connected to one real machine: how far off are its forecasts out of sample, is it better than a trivial guess, and when should someone act. The two examples below run a Modelica model and a ModelingToolkit model through Otwin. Today an external model enters as a Python function. Reading FMUs directly, with parameter fitting, is on the [roadmap](ROADMAP.md).

# Install

```bash
pip install "otwin[engine]"
```

`otwin` needs only NumPy and SciPy. The `engine` extra adds the compiled Rust runtime, with wheels for Linux, macOS and Windows. Without it every model runs on the NumPy reference backend, more slowly. The engine on its own is the Rust crate [`otwin-core`](https://crates.io/crates/otwin-core), for running a compiled model where Python is not available.

# Quick start

A mass hanging from a spring and a damper, under gravity. You describe what exists and what touches what. Nobody writes Newton's law.

`>>` joins parts in a line, the way the drawing reads. `connect` joins ports where a line is not enough: here the damper and the weight meet the mass at the same point.

<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/Spring.png" height="200">

</div>

```python
import otwin
from otwin.components.mechanical import Mass, Spring, Damper, ForceSource, Fixed

mass = Mass(1.0, name="mass")
spring = Spring(20.0, name="spring")
damper = Damper(0.3, name="damper")
weight = ForceSource(1.0 * 9.81, name="weight")
ceiling = Fixed(name="ceiling")

system = mass >> spring >> ceiling                     # the line
system.connect(mass.flange, damper.a, weight.flange)   # the damper and the weight meet the mass
system.connect(damper.b, ceiling.port)                 # the damper's other end

model = otwin.compile(system)
run = model.simulate(t_span=(0, 20), dt=0.05)
q = run["spring.extension"]

print(f"Static equilibrium q* = m g / k = {weight.force / spring.stiffness:.3f} m")
print(f"Lowest point reached: q = {q.max():.3f} m")
print(f"Final position: q = {q[-1]:.3f} m")
print(f"Largest energy violation: {run.energy_balance()['max_violation']:.1e} J")
```

```text
Static equilibrium q* = m g / k = 0.491 m
Lowest point reached: q = 0.932 m
Final position: q = 0.477 m
Largest energy violation: 0.0e+00 J
```

The mass settles where the spring holds its weight, and the energy account closes exactly. `model.summary()` shows what the compiler built: states, parameters, units.

# A Modelica model, checked with Otwin

A storage tank in a water network is dosed with chlorine once a day, and the residual must not fall below 0.20 mg/L before the next dose. The engineer's model is a first-order decay with the rate measured in a bottle test, exported from a Modelica tool as an FMU. The real tank loses chlorine faster, because its walls consume it too.

To keep the example runnable anywhere, the FMU here is `Dahlquist.fmu`, the first-order decay `dx/dt = -k x` published by the Modelica Association in its Reference FMUs. With your own FMU only the file name and the variable names change.

```bash
pip install "otwin[engine]" fmpy
curl -LO https://github.com/modelica/Reference-FMUs/releases/download/v0.0.39/Reference-FMUs-0.0.39.zip
unzip -j Reference-FMUs-0.0.39.zip 3.0/Dahlquist.fmu
```

```python
import numpy as np
from fmpy import extract, simulate_fmu
from otwin.forecast import rolling_origin_residuals, horizon_conformal, picp

FMU = extract("Dahlquist.fmu")   # dx/dt = -k x, exported by a Modelica tool
K_LAB, DOSE = 0.05, 1.0          # bottle-test decay [1/h], residual after each daily dose [mg/L]

def fmu_forecast(history, horizon):
    """The Modelica model run forward from the last reading, redosed every 24 h."""
    t, x, out = len(history) - 1, float(history[-1]), []
    while len(out) < horizon:
        if (t + 1) % 24 == 0:                                  # the daily dose
            t, x = t + 1, DOSE
            out.append(DOSE)
            continue
        steps = min(horizon - len(out), 23 - t % 24)
        r = simulate_fmu(FMU, stop_time=steps, output_interval=1,
                         start_values={"x": x, "k": K_LAB})
        out += list(r["x"][1:steps + 1])
        t, x = t + steps, out[-1]
    return np.array(out)

# the real tank: walls take chlorine too (k = 0.065 1/h), sensor noise 2 %
rng = np.random.default_rng(0)
hours = np.arange(30 * 24)
truth = DOSE * np.exp(-0.065 * (hours % 24))
reading = truth * (1 + rng.normal(0, 0.02, hours.size))

train, test = reading[:20 * 24], reading[20 * 24:]
res, h = rolling_origin_residuals(fmu_forecast, train, step=6, min_train=24, max_horizon=24)
band = horizon_conformal(res, h, level=0.9, max_horizon=24)

ys, lo, up = [], [], []
for k in range(20 * 24, 30 * 24 - 24, 6):
    lower, upper = band.apply(fmu_forecast(reading[:k], 24))
    ys.append(reading[k:k + 24]); lo.append(lower); up.append(upper)
print(f"{res.size} out-of-sample errors from the Modelica model")
print(f"coverage of the 90 % band on 10 unseen days: {picp(np.concatenate(ys), np.concatenate(lo), np.concatenate(up)):.0%}")
now = 20 * 24 + 6                                              # day 21, 06:00
forecast = fmu_forecast(reading[:now], 17)                     # until 23:00
lower, _ = band.apply(forecast)
print(f"lowest chlorine before the next dose, Modelica model alone: {forecast.min():.3f} mg/L")
print(f"lowest chlorine before the next dose, lower edge of the band: {lower.min():.3f} mg/L")
print(f"what the tank actually reached: {truth[now + 1:now + 18].min():.3f} mg/L (limit 0.20)")
```

```text
1788 out-of-sample errors from the Modelica model
coverage of the 90 % band on 10 unseen days: 91%
lowest chlorine before the next dose, Modelica model alone: 0.301 mg/L
lowest chlorine before the next dose, lower edge of the band: 0.202 mg/L
what the tank actually reached: 0.224 mg/L (limit 0.20)
```

The Modelica model, run as it is, says the tank stays comfortably above the limit. Otwin measured how wrong that model had been over twenty days and turned it into a range that held 91 % of the time on ten days it never saw. The lower edge of that range is at the limit, and the tank went closer to it than the model said. The model was not changed. What changed is that its forecast now comes with evidence.

# A ModelingToolkit model, checked with Otwin

The same idea with a model written in Julia. A storage tank is filled at a constant rate and drawn down by a town whose demand follows a daily curve. The model uses the design demand profile. The real town has deeper morning and evening peaks.

```bash
pip install "otwin[engine]" juliacall
python -c 'from juliacall import Main as jl; jl.seval("import Pkg; Pkg.add([\"ModelingToolkit\", \"OrdinaryDiffEq\"])")'
```

The first run downloads Julia and compiles the packages, which takes around twenty minutes. Later runs start in about thirty seconds. The model, in `tank.jl`:

```julia
using ModelingToolkit, OrdinaryDiffEq
using ModelingToolkit: t_nounits as t, D_nounits as D
@parameters area=400.0 inflow=60.0 demand=60.0       # m², m³/h, m³/h (daily mean)
@variables level(t)=3.0                               # m
eqs = [D(level) ~ (inflow - demand * (1 + 0.6 * sin(2pi * t / 24 - pi / 2))) / area]
@mtkcompile tank = System(eqs, t)
prob = ODEProblem(tank, [], (0.0, 24.0))
function forecast(level0, t0, horizon)
    p = remake(prob; u0 = [tank.level => level0], tspan = (t0, t0 + horizon))
    solve(p, Tsit5(); saveat = t0+1:t0+horizon)[tank.level]
end
```

And in Python:

```python
import numpy as np
from juliacall import Main as jl
from otwin.forecast import evaluate

jl.include("tank.jl")            # the ModelingToolkit model of the storage tank

class JuliaTank:
    """Forecast the level from the last reading with the ModelingToolkit model."""
    def forecast(self, history, horizon):
        t0 = float(len(history) - 1)
        return np.asarray(jl.forecast(float(np.ravel(history)[-1]), t0, horizon)).reshape(-1, 1)

# the real tank: the morning and evening peaks are deeper than the design profile, sensor noise 1 cm
rng = np.random.default_rng(0)
hours = np.arange(30 * 24, dtype=float)
draw = 60.0 * (1 + 0.8 * np.sin(2 * np.pi * hours / 24 - np.pi / 2))
level = 3.0 + np.concatenate([[0.0], np.cumsum((60.0 - draw[:-1]) / 400.0)])
reading = level + rng.normal(0, 0.01, hours.size)

print(evaluate(JuliaTank(), reading.reshape(-1, 1), protocol="rolling_origin",
               n_folds=5, horizon=24, seasonal_period=24))
```

```text
EvalReport (rolling_origin, 5 folds)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Skill Score: -8.66 (866% WORSE than baseline)
Baseline: seasonal_naive

Point Metrics:
  RMSE      0.1270 (baseline: 0.0131)
  MAE       0.1055 (baseline: 0.0103)
  NRMSE     0.1373
  MASE      9.6318
  THEIL_U   0.2860

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

The model solves its equations correctly, and it is still worse than the simplest possible forecast: tomorrow's level is today's level at the same hour. `evaluate` scores any model against the hardest of several trivial baselines, on data the model has not seen, before anyone relies on it. Here that comparison says the demand profile has to be fitted to the town before the twin is used.

# Three twins, three decisions

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-grid-twin.gif" width="100%" alt="A power grid twin estimates the real inertia of the grid from every small disturbance and warns two hours ahead that a large trip could push frequency below 49.2 Hz.">

<sub>**Power grid.** The grid is modelled as a single rotating mass with Otwin's rotational parts. Every small disturbance gives an estimate of how much spinning mass is holding the frequency: across 43 disturbances the median error was 1.1 %. The operator's plan says the grid is safe at midday. The measured grid is lighter, so the twin asks for fast battery response two hours ahead. Simulated grid with measurement noise. The fit assumes the load response and the governors are known exactly. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/grid_twin.py)</sub>

<br>

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-pump-twin.gif" width="100%" alt="A pump feeding a filter press. The twin estimates cloth fouling from the pressure drop and shows when cleaning becomes cheaper than the extra energy.">

<sub>**Pump and filter press.** The line is built and simulated with Otwin's hydraulic parts. Nobody can measure how fouled the filter cloths are. The twin estimates it from a pressure-drop sensor with 2 % noise and shows when cleaning costs less than the extra energy the pump is using. The cleaning month counts hydraulic energy only. With the losses of the pump and its motor, the electricity bill brings it forward. Simulated plant. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/pump_twin.py)</sub>

# What is in the library

| You want to | Otwin gives you |
|---|---|
| Describe a system from parts | Components in the electrical, mechanical, rotational, hydraulic and thermal domains, two-ports that couple them, and devices such as `Battery`, `Pump`, `Filter` and `DCMotor`. See [COMPONENTS.md](COMPONENTS.md). |
| Run it fast | `otwin.compile`, the Rust engine, and the same numbers from the NumPy backend. |
| Fit it to measurements | `otwin.fit_parameters`, with a verdict on whether each parameter is determined by the data. |
| Follow states you cannot measure | Extended Kalman filter, moving-horizon estimation with bounds, and an observer whose corrections cannot add energy. |
| Forecast with a tested range | Rolling-origin errors, conformal ranges that grow with the horizon, coverage measured on unseen data. |
| Know whether the model is any good | `otwin.forecast.evaluate`, which scores against trivial baselines on data the model has not seen. |
| Stop the twin from answering beyond its evidence | `otwin.advise.Envelope` and `model.manifest()`, which record what was validated and refuse outside it. |
| Learn what the physics leaves out | Residual models (Gaussian processes, neural networks) on top of a compiled model. |
| Read field data | Modbus TCP/RTU and SunSpec connectors, as optional extras. |

The [documentation](https://otwin.readthedocs.io) explains each piece, with examples whose printed numbers are checked in CI.

# Examples

Two scripts start from a maintenance problem, build the system from its data sheet, and end with a number checked by hand.

| Script | The problem | What decides it |
|---|---|---|
| [The battery module that runs hot](examples/battery_that_runs_hot.py) | A module reads a few degrees more than at commissioning. Aged cells, or a clogged air filter? | The voltage jump when the current reverses: only aged cells move it. |
| [The pump that asks for more every month](examples/pump_station_that_asks_for_more.py) | The drive is turned up month after month to hold the flow through a fouling filter. | The month at which the extra pumping energy has paid for a cleaning. |

The notebooks each answer one engineering question and open in Colab.

| # | Notebook | Question | Data |
|---|---|---|---|
| 01 | [A model that cannot invent energy](examples/otwin_01_a_model_that_cannot_invent_energy.ipynb) | How do you know the equations obey the physical structure? | Simulation |
| 02 | [When the process makes entropy](examples/otwin_02_when_the_process_makes_entropy.ipynb) | How do you write a reactor model that cannot violate the second law? | Simulation |
| 03 | [Scoring a forecast so it cannot flatter you](examples/otwin_03_scoring_a_forecast.ipynb) | How good is a forecast when it is evaluated out of sample? | NASA PCoE |
| 04 | [A band whose 90 % means 90 %](examples/otwin_04_a_band_whose_90_means_90.ipynb) | How do you calibrate a prediction range? | NASA PCoE |
| 05 | [From a noisy sensor to a state you can trust](examples/otwin_05_from_a_noisy_sensor_to_a_state.ipynb) | How do you estimate a state from imperfect measurements? | NASA PCoE |
| 06 | [The twin that says no](examples/otwin_06_the_twin_that_says_no.ipynb) | What should a twin do outside what it was validated for? | Simulation |
| 07 | [All of it, on eight years of field data](examples/otwin_07_field_data.ipynb) | Does the protocol hold on real systems? | RWTH field data |
| 08 | [Does the physics earn its place?](examples/otwin_08_does_the_physics_earn_its_place.ipynb) | Does structured physics improve the prediction? | RWTH field data |

# The Otwin project

| Repository | What it is |
|---|---|
| [**otwin**](https://github.com/otwin-core/otwin) | This library: components, compiler, Rust engine, estimation, forecasting and validation. |
| [**otwin-spec**](https://github.com/otwin-core/otwin-spec) | What an Otwin model means, written down, with a test suite any implementation must pass. |
| [**otwin-hybrid**](https://github.com/otwin-core/otwin-hybrid) | A complete battery degradation twin that combines physics and machine learning, in Python, Julia and R. |

Where the project is going, phase by phase, and what it builds on: [ROADMAP.md](ROADMAP.md).

Questions, ideas and things you have built go to [Discussions](https://github.com/otwin-core/otwin/discussions). Bugs and agreed work go to [Issues](https://github.com/otwin-core/otwin/issues). A new component, a reference case or an example is the easiest way to contribute: see [CONTRIBUTING.md](CONTRIBUTING.md).

Each repository includes a `CITATION.cff`. Otwin is released under the [Apache License 2.0](LICENSE).
