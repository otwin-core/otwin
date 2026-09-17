# Quickstart

Four things, in the order you would actually do them: describe an asset and
compile it, run it, estimate its state from a noisy sensor, and let the twin
decide whether it is entitled to answer.

Every block below runs as written. There is no data file; the measurements are
synthesised so that this page is self-contained.

## 1. Describe the asset and compile it

An electric drive: a voltage supply, a DC motor, and a fan on the shaft whose
torque grows with the square of the speed. You say what exists and what touches
what. You do not write an equation.

Two verbs describe any system. `>>` joins components in a line, the way the
drawing reads; `connect` joins ports where a line is not enough: three things
meeting at one point, or a second circuit attached to a port.

```python
import numpy as np
import otwin
from otwin.components.electrical import VoltageSource, Ground
from otwin.components.composite import DCMotor
from otwin.components.rotational import RotationalDamper, Housing

supply = VoltageSource(None, name="supply")          # None: an input we will choose later
motor = DCMotor(resistance=1.0, inductance=0.5, torque_constant=0.5,
                inertia=0.01, friction=0.1, name="motor")
fan = RotationalDamper(law=lambda w: 0.002 * w * abs(w), name="fan")   # a nonlinear load
gnd, housing = Ground(), Housing()

drive = gnd >> supply >> motor >> gnd        # the electrical loop, closed on ground
drive.connect(motor.shaft, fan.a)            # the shaft: a second circuit, in another domain
drive.connect(fan.b, housing.port)
drive.name = "drive"

model = otwin.compile(drive)
print(model.state_names)
print(model.input_names)
```

```text
['motor.armature.flux', 'motor.rotor.angular_momentum']
['supply']
```

The compiler found two energy stores, the armature inductance and the rotor,
and made them the states. The source left at `None` became the model's one
input. `model.summary()` prints all of it with units; `model.structure()` gives
the matrices of the port-Hamiltonian form the compiler derived, if you want to
see them. See [Components](concepts/components.md) and
[Compilation](concepts/compilation.md) for what happened in between.

## 2. Run it

```python
t = np.linspace(0.0, 3.0, 3001)
run = model.simulate(t=t, inputs={"supply": 24.0})
print(f"speed after 3 s: {run['motor.rotor.angular_velocity'][-1]:.2f} rad/s")
print(f"largest energy-balance violation over {run.stats['steps']} steps: "
      f"{run.energy_balance()['max_violation']:.1e} J")
```

```text
speed after 3 s: 29.36 rad/s
largest energy-balance violation over 3000 steps: 0.0e+00 J
```

Three thousand implicit steps of a nonlinear two-domain model, in the engine,
in a few milliseconds. The trajectory is indexed by name: every state, every
input, and every derived quantity the compiler produced (`fan.torque`,
`supply.power`, `motor.bearing.power`, ...) is in `run.keys()`.

The second line is the property the structure buys. The default solver is the
implicit midpoint rule, which preserves the discrete power balance: stored
energy changes only by what the supply delivers and what the resistances and
dampers remove. Not approximately, and not because the tolerance is tight.

:::{tip}
`inputs` takes a number, an array over the grid, a function of time, or a
feedback law. For a law that reads the state, write it as an expression over
`model.symbol(...)` and the compiler folds it into the model so the solver
evaluates it at every stage. See [Simulation](guides/simulate.md).
:::

## 3. Estimate the state from a noisy sensor

A compiled model is a `TwinModel`: it has `rhs` and `observe`. Tell it which
output the sensor reads and hand it to an estimator.

```python
from otwin.estimate import ExtendedKalmanFilter

model.measurements = ["motor.rotor.angular_velocity"]      # a tachometer

rng = np.random.default_rng(0)
every = slice(None, None, 10)                              # a 100 Hz sensor
ts, truth = t[every], run.x[every]
ys = truth[:, 1:2] / 0.01 + rng.normal(0, 2.0, (ts.size, 1))   # speed = momentum / inertia, plus noise
us = np.full((ts.size, 1), 24.0)

ekf = ExtendedKalmanFilter(model, Q=np.diag([1e-4, 1e-4]), R_meas=np.array([[4.0]]),
                           P0=np.eye(2), x0=np.zeros(2))
res = ekf.filter(ys, us, ts)

err_meas = np.sqrt(np.mean((ys[:, 0] - truth[:, 1] / 0.01) ** 2))
err_ekf = np.sqrt(np.mean((res.x[:, 1] / 0.01 - truth[:, 1] / 0.01) ** 2))
print(f"speed error: sensor {err_meas:.2f} rad/s, filtered {err_ekf:.2f} rad/s")
```

```text
speed error: sensor 2.04 rad/s, filtered 0.80 rad/s
```

The filter also recovers the armature current, which nobody measured. See
[Estimate](guides/estimate.md) for the bounded and the energy-consistent
estimators.

## 4. Let the twin decide what it may answer

A {class}`~otwin.interfaces.TwinManifest` records what the model is and how it
was validated. An {class}`~otwin.advise.Envelope` turns that record into an
answer or a refusal. `model.manifest()` starts the record for a compiled model.

```python
from otwin.advise import Envelope
from otwin.interfaces import TwinManifest

manifest = model.manifest("drive-01")
manifest = TwinManifest.from_dict({
    **manifest.to_dict(),
    "validation": TwinManifest.validated_by("rolling_origin", rmse=0.05, skill_score=0.6),
})
envelope = Envelope(state_bounds=[(0.0, 20.0), (0.0, 1.0)], max_horizon=600)

print(envelope.check(state=[5.0, 0.3], horizon=300, manifest=manifest).explain())
print(envelope.check(state=[5.0, 0.3], horizon=3000, manifest=manifest).explain())
```

```text
inside the validated envelope (horizon 300 <= 600; operating point inside the identified range; validated, leakage-free)
outside the validated envelope:
  - horizon: beyond the validated forecast horizon (asked for 3000, validated to 600)

This is a refusal, not a failure. The twin has not been shown to answer this question, and returning a number anyway would hide that.
```

The `validated_by` record here is stated, not computed, so that the page stays
self-contained. In practice it comes from {func}`~otwin.forecast.evaluate`, and
the band from a conformal calibration; see [Forecast](guides/forecast.md) and
[Advise](guides/advise.md).

## Where next

- [Devices](guides/devices.md): a battery module and a pump line from their data sheets, compiled and stepped.
- [Modelling](guides/modelling.md): every domain, with the component to use for each physical element.
- [Grey-box models](guides/greybox.md): add what the physics leaves out, and fit its coefficients from data.
- [Compilation](concepts/compilation.md): what the compiler does, and how to read a model that surprised you.
- [The advanced API](guides/model.md): writing `H`, `J`, `R`, `g` yourself when no component fits.
