<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/brand/otwin-github-header-1a.png" width="100%" alt="otwin: open digital twins of real equipment">

[![License](https://img.shields.io/github/license/otwin-core/otwin?color=EC3013\&cacheSeconds=86400)](https://github.com/otwin-core/otwin/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/otwin?color=EC3013\&cacheSeconds=3600)](https://pypi.org/project/otwin/)
[![crates.io](https://img.shields.io/crates/v/otwin-core?color=EC3013&logo=rust&label=crates.io)](https://crates.io/crates/otwin-core)
[![Python](https://img.shields.io/github/actions/workflow/status/otwin-core/otwin/ci.yml?branch=main\&label=python\&logo=github)](https://github.com/otwin-core/otwin/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/otwin-core/otwin/badge)](https://scorecard.dev/viewer/?uri=github.com/otwin-core/otwin)
[![REUSE status](https://api.reuse.software/badge/github.com/otwin-core/otwin)](https://api.reuse.software/info/github.com/otwin-core/otwin)

</div>

**Otwin tells you whether a model of a real machine can be trusted, and turns its forecasts into decisions.** Bring the model from Modelica, from Julia, or build it with Otwin's own components.

```bash
pip install "otwin[engine]"
```

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/readme/otwin-what-it-adds.png" width="100%" alt="Models from Modelica, Julia or Otwin go into Otwin with the machine's own measurements. Otwin answers four questions: how wrong has the model been, is it better than a trivial guess, does its 90 % range hold 90 %, and when should someone act.">

# Why Otwin, if Modelica and Julia already exist?

Modelica, ModelingToolkit and Dyad are where engineering models are built, and they do it well. Otwin does not replace them. It answers the questions that come after, once a model is connected to one real machine: how wrong has it been on data it never saw, is it better than a trivial forecast, does its 90 % range really hold 90 % of the time, and when should someone act. The two examples below take a model from each of those worlds and check it.

<br>

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/readme/otwin-modelica-chlorine.png" width="100%" alt="Chlorine in a storage tank over a day. The Modelica model alone predicts a minimum of 0.30 mg/L. Otwin's 90 % range reaches down to 0.20 mg/L. The tank actually reached 0.22 mg/L.">

The Modelica model, run as it is, says the chlorine stays well above the limit. Otwin measured how wrong it had been over twenty days and turned that into a range that held 91 % of the time on ten days it never saw. The tank went closer to the limit than the model said, and stayed inside the range.

<details>
<summary><b>The code</b> · <code>pip install "otwin[engine]" fmpy</code> · runs in about two seconds</summary>

The FMU here is `Dahlquist.fmu`, the first-order decay `dx/dt = -k x` that the Modelica Association publishes in its Reference FMUs, so the example runs anywhere. With your own FMU only the file name and the variable names change.

```bash
curl -LO https://github.com/modelica/Reference-FMUs/releases/download/v0.0.39/Reference-FMUs-0.0.39.zip
unzip -j Reference-FMUs-0.0.39.zip 3.0/Dahlquist.fmu
```

```python
import numpy as np
from fmpy import extract, simulate_fmu

from otwin.forecast import horizon_conformal, picp, rolling_origin_residuals

FMU = extract("Dahlquist.fmu")  # dx/dt = -k x, exported by a Modelica tool
K_LAB, DOSE = 0.05, 1.0  # bottle-test decay [1/h], residual after each daily dose [mg/L]


def fmu_forecast(history, horizon):
    """The Modelica model run forward from the last reading, redosed every 24 h."""
    t, x, out = len(history) - 1, float(history[-1]), []
    while len(out) < horizon:
        if (t + 1) % 24 == 0:  # the daily dose
            t, x = t + 1, DOSE
            out.append(DOSE)
            continue
        steps = min(horizon - len(out), 23 - t % 24)
        r = simulate_fmu(
            FMU, stop_time=steps, output_interval=1, start_values={"x": x, "k": K_LAB}
        )
        out += list(r["x"][1 : steps + 1])
        t, x = t + steps, out[-1]
    return np.array(out)


# the real tank: walls take chlorine too (k = 0.065 1/h), sensor noise 2 %
rng = np.random.default_rng(0)
hours = np.arange(30 * 24)
truth = DOSE * np.exp(-0.065 * (hours % 24))
reading = truth * (1 + rng.normal(0, 0.02, hours.size))

train, test = reading[: 20 * 24], reading[20 * 24 :]
res, h = rolling_origin_residuals(
    fmu_forecast, train, step=6, min_train=24, max_horizon=24
)
band = horizon_conformal(res, h, level=0.9, max_horizon=24)

ys, lo, up = [], [], []
for k in range(20 * 24, 30 * 24 - 24, 6):
    lower, upper = band.apply(fmu_forecast(reading[:k], 24))
    ys.append(reading[k : k + 24])
    lo.append(lower)
    up.append(upper)
print(f"{res.size} out-of-sample errors from the Modelica model")
coverage = picp(np.concatenate(ys), np.concatenate(lo), np.concatenate(up))
print(f"coverage of the 90 % band on 10 unseen days: {coverage:.0%}")
now = 20 * 24 + 6  # day 21, 06:00
forecast = fmu_forecast(reading[:now], 17)  # until 23:00
lower, _ = band.apply(forecast)
print(
    f"lowest chlorine before the next dose, Modelica model alone: {forecast.min():.3f} mg/L"
)
print(
    f"lowest chlorine before the next dose, lower edge of the band: {lower.min():.3f} mg/L"
)
print(
    f"what the tank actually reached: {truth[now + 1 : now + 18].min():.3f} mg/L (limit 0.20)"
)
```

```text
1788 out-of-sample errors from the Modelica model
coverage of the 90 % band on 10 unseen days: 91%
lowest chlorine before the next dose, Modelica model alone: 0.301 mg/L
lowest chlorine before the next dose, lower edge of the band: 0.202 mg/L
what the tank actually reached: 0.224 mg/L (limit 0.20)
```

Full script: [`examples/modelica_fmu_chlorine.py`](examples/modelica_fmu_chlorine.py). Today an external model enters Otwin as a Python function. Reading FMUs directly, with parameter fitting, is on the [roadmap](ROADMAP.md).

</details>

<br>

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/readme/otwin-julia-tank.png" width="100%" alt="Water level in a storage tank. The ModelingToolkit model with the design demand profile misses the real peaks; repeating yesterday's levels follows them closely. The model's error is 12.7 cm against 1.3 cm for the trivial forecast.">

The ModelingToolkit model solves its equations correctly and is still about ten times worse than repeating yesterday's levels, because the town does not follow the design demand profile. Otwin scores every model against the hardest of several trivial forecasts, on data it has not seen, before anyone relies on it.

<details>
<summary><b>The code</b> · <code>pip install "otwin[engine]" juliacall</code> · the first run sets up Julia, about twenty minutes</summary>

```bash
python -c 'from juliacall import Main as jl; jl.seval("import Pkg; Pkg.add([\"ModelingToolkit\", \"OrdinaryDiffEq\"])")'
```

The model, in `tank.jl`:

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

jl.include("tank.jl")  # the ModelingToolkit model of the storage tank


class JuliaTank:
    """Forecast the level from the last reading with the ModelingToolkit model."""

    def forecast(self, history, horizon):
        t0 = float(len(history) - 1)
        last = float(np.ravel(history)[-1])
        return np.asarray(jl.forecast(last, t0, horizon)).reshape(-1, 1)


# the real tank: deeper morning and evening peaks than the design profile,
# level sensor noise 1 cm
rng = np.random.default_rng(0)
hours = np.arange(30 * 24, dtype=float)
draw = 60.0 * (1 + 0.8 * np.sin(2 * np.pi * hours / 24 - np.pi / 2))
level = 3.0 + np.concatenate([[0.0], np.cumsum((60.0 - draw[:-1]) / 400.0)])
reading = level + rng.normal(0, 0.01, hours.size)

report = evaluate(
    JuliaTank(),
    reading.reshape(-1, 1),
    protocol="rolling_origin",
    n_folds=5,
    horizon=24,
    seasonal_period=24,
)
print(report)
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

Full scripts: [`examples/julia_mtk_tank.py`](examples/julia_mtk_tank.py) and [`examples/tank.jl`](examples/tank.jl).

</details>

# Build a model from parts

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/readme/otwin-quickstart.gif" width="100%" alt="A mass hangs from a spring and a damper. It bounces and settles at the equilibrium the compiler derived, while the energy supplied by gravity always equals the energy stored plus the energy turned into heat.">

When there is no model yet, you can build one in Otwin. You say what exists and what touches what: `>>` joins parts in a line, the way the drawing reads, and `connect` joins ports where a line is not enough. Otwin writes the equations, runs them in a Rust engine, and keeps an energy account you can check at every step.

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

`model.summary()` shows what the compiler built: states, parameters and units. The components cover electrical, mechanical, rotational, hydraulic and thermal systems, with devices such as `Battery`, `Pump`, `Filter` and `DCMotor`: see [COMPONENTS.md](COMPONENTS.md).

# Three twins, three decisions

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-battery-twin.gif" width="100%" alt="A battery cell on a cycler. The twin follows its capacity cycle by cycle, forecasts it with a 90 % range, and asks for a replacement before the cell reaches end of life.">

<sub>**Battery health, on real data.** 44 cells the twin never saw (Severson et al., 2019). The replacement order came before end of life on every cell, a median of 76 cycles ahead. The fade law is fitted with SciPy. Otwin calibrates the range on 126 other cells and measures how often it holds on the unseen ones: 96 % for a stated 90 %, so the range is wider than it needs to be. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/battery_twin.py)</sub>

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-grid-twin.gif" width="100%" alt="A power grid twin estimates the real inertia of the grid from every small disturbance and warns two hours ahead that a large trip could push frequency below 49.2 Hz.">

<sub>**Power grid.** A single rotating mass built from Otwin's rotational parts. Every small disturbance gives an estimate of the spinning mass that holds the frequency: across 43 disturbances the median error was 1.1 %. The measured grid is lighter than the operator's plan, so the twin asks for fast battery response two hours ahead. Simulated grid with measurement noise. The fit assumes the load response and the governors are known exactly. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/grid_twin.py)</sub>

<img src="https://raw.githubusercontent.com/otwin-core/.github/main/profile/assets/gifs/otwin-pump-twin.gif" width="100%" alt="A pump feeding a filter press. The twin estimates cloth fouling from the pressure drop and shows when cleaning becomes cheaper than the extra energy.">

<sub>**Pump and filter press.** The line is built and simulated with Otwin's hydraulic parts. The twin estimates how fouled the filter cloths are from a pressure sensor with 2 % noise, and shows when cleaning costs less than the extra energy the pump uses. The cleaning month counts hydraulic energy only. With the losses of the pump and its motor, the electricity bill brings it forward. Simulated plant. [Script](https://github.com/otwin-core/.github/blob/main/profile/assets/gifs/pump_twin.py)</sub>

# More

<details>
<summary><b>What is in the library</b></summary>

| You want to | Otwin gives you |
|---|---|
| Describe a system from parts | Components in five physical domains, two-ports that couple them, and devices built from them. See [COMPONENTS.md](COMPONENTS.md). |
| Run it fast | `otwin.compile`, the Rust engine, and the same numbers from the NumPy backend. |
| Fit it to measurements | `otwin.fit_parameters`, with a verdict on whether each parameter is determined by the data. |
| Follow states you cannot measure | Extended Kalman filter, moving-horizon estimation with bounds, and an observer whose corrections cannot add energy. |
| Forecast with a tested range | Rolling-origin errors and conformal ranges that grow with the horizon, with coverage measured on unseen data. |
| Know whether a model is any good | `otwin.forecast.evaluate`, which scores against trivial baselines on data the model has not seen. |
| Stop a twin answering beyond its evidence | `otwin.advise.Envelope` and `model.manifest()`, which record what was validated and refuse outside it. |
| Learn what the physics leaves out | Residual models, Gaussian processes or neural networks, on top of a compiled model. |
| Read field data | Modbus TCP/RTU and SunSpec connectors, as optional extras. |

The [documentation](https://otwin.readthedocs.io) explains each piece, with examples whose printed numbers are checked in CI.

</details>

<details>
<summary><b>Install options</b></summary>

`pip install otwin` needs only NumPy and SciPy, and runs every model on the NumPy reference backend. The `engine` extra adds the compiled Rust runtime, with wheels for Linux, macOS and Windows. Other extras: `modbus` and `sunspec` for field data, `gp` and `nn` for learned residuals. The engine on its own is the Rust crate [`otwin-core`](https://crates.io/crates/otwin-core), for running a compiled model where Python is not available.

</details>

<details>
<summary><b>Examples and notebooks</b></summary>

| Script | The problem |
|---|---|
| [The battery module that runs hot](examples/battery_that_runs_hot.py) | Aged cells, or a clogged air filter? The voltage jump when the current reverses tells them apart. |
| [The pump that asks for more every month](examples/pump_station_that_asks_for_more.py) | The month at which the extra pumping energy has paid for a cleaning. |
| [A Modelica model, checked](examples/modelica_fmu_chlorine.py) | Chlorine in a storage tank, with an FMU as the model. |
| [A ModelingToolkit model, checked](examples/julia_mtk_tank.py) | A storage tank level, with a Julia model called from Python. |

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

The images on this page are drawn by the scripts in [`assets/readme`](assets/readme) from the same examples.

</details>

# The Otwin project

| Repository | What it is |
|---|---|
| [**otwin**](https://github.com/otwin-core/otwin) | This library: components, compiler, Rust engine, estimation, forecasting and validation. |
| [**otwin-spec**](https://github.com/otwin-core/otwin-spec) | What an Otwin model means, written down, with a test suite any implementation must pass. |
| [**otwin-hybrid**](https://github.com/otwin-core/otwin-hybrid) | A complete battery degradation twin that combines physics and machine learning, in Python, Julia and R. |

Where the project is going, and what it builds on: [ROADMAP.md](ROADMAP.md). Questions and ideas go to [Discussions](https://github.com/otwin-core/otwin/discussions), bugs and agreed work to [Issues](https://github.com/otwin-core/otwin/issues). A new component, a reference case or an example is the easiest way to contribute: see [CONTRIBUTING.md](CONTRIBUTING.md).

Each repository includes a `CITATION.cff`. Otwin is released under the [Apache License 2.0](LICENSE).
