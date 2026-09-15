# Simulation

Running a compiled model: the time grid, the solvers, the inputs, control
laws, batches, and what comes back.

```python
import numpy as np
import otwin
from otwin.components.catalogue import mass_spring_damper

model = otwin.compile(mass_spring_damper(m=1.0, k=20.0, c=0.3, position=1.0))
run = model.simulate(t_span=(0, 10), dt=0.01)
print(f"{len(run.t)} points, t in [{run.t[0]:g}, {run.t[-1]:g}], {run.x.shape[1]} states, solver={run.stats['method']}")
print(f"{run.stats['steps']} steps, {run.stats['newton_iterations']} Newton iterations, "
      f"{run.stats['rhs_evals']} evaluations")
```

```text
1001 points, t in [0, 10], 2 states, solver=midpoint
1000 steps, 1000 Newton iterations, 3000 evaluations
```

`print(run)` adds the backend that ran it, `rust` with the engine installed
and `numpy` without.

## The grid

`t_span=(t0, t1), dt=...` builds a uniform grid; `t=...` takes any strictly
increasing array. The state is reported at every grid point. With the
adaptive solver the engine takes as many internal steps as the tolerance
needs between grid points and still reports exactly on the grid.

## Solvers

| `solver=` | what it is | when |
|---|---|---|
| `"midpoint"` (default) | implicit midpoint rule, Newton with the analytic Jacobian, halving on failure | the default: it preserves the discrete power balance, so stored energy cannot be created by the integrator |
| `"rk45"` | Dormand-Prince 5(4) with error control (`rtol`, `atol`) | smooth problems where accuracy per cost matters more than structure |
| `"rk4"` | classical Runge-Kutta, fixed step | a reference; fast and simple |
| `"euler"` | explicit Euler | to see what a bad integrator does |

```python
for solver in ("midpoint", "rk4", "rk45", "euler"):
    r = model.simulate(t_span=(0, 10), dt=0.01, solver=solver)
    print(f"{solver:<9} final extension {r['spring.extension'][-1]:+.6f} m   "
          f"energy gained on the worst step {r.energy_balance()['max_violation']:.1e} J")
```

```text
midpoint  final extension +0.174715 m   energy gained on the worst step 0.0e+00 J
rk4       final extension +0.173548 m   energy gained on the worst step 0.0e+00 J
rk45      final extension +0.173548 m   energy gained on the worst step 0.0e+00 J
euler     final extension +0.457081 m   energy gained on the worst step 2.0e-02 J
```

The midpoint rule is second order, so at this step size its phase lags the
fifth-order answer by a millimetre; halve `dt` and the gap divides by four. What
it never does is what Euler does here: create energy. On a long run with a
loose step that is the difference between a battery model that self-charges and
one that does not. `Trajectory.energy_balance()` reports the worst step.

## Inputs

`inputs` accepts, per input name, a number, an array over the grid, or a
function of time. A bare array of shape `(len(t), n_inputs)` also works.
Inputs left out are zero. `interp="linear"` interpolates between grid points
inside a step; the default holds the value.

```python
t = np.linspace(0, 10, 1001)
a = model.simulate(t=t, inputs={"force": 2.0})
b = model.simulate(t=t, inputs={"force": lambda tt: 2.0 * (tt > 5.0)})
c = model.simulate(t=t, inputs={"force": np.where(t > 5.0, 2.0, 0.0)})
print(np.allclose(b.x, c.x))
```

```text
True
```

## Control laws

A law that reads the state is written as an expression over the model's own
quantities and compiled in. `model.symbol(name)` returns a handle on any state,
output, input or parameter; {mod}`otwin.expr` supplies `maximum`, `minimum`,
`where`, `sqrt`, `exp`, `abs`, `tanh`. The closed input becomes an output of
the new model.

```python
v = model.symbol("mass.velocity")
closed = model.closed_loop(force=-5.0 * v)          # extra damping, as a control law
print(closed.n_inputs, "force" in closed.output_names)
```

```text
0 True
```

`model.simulate(inputs={"force": -5.0 * v})` does the same in one call. A
Python callable `f(t, x)` is also accepted; it is sampled at each grid point
and held over the step, one engine call per step. That is the right model of a
digital controller running at the grid rate and the wrong one of a valve.

## Batches

Many runs at once, in parallel in the engine: `x0s` is `(N, n_states)`,
`parameters` optionally one parameter set per run.

```python
x0s = np.column_stack([np.linspace(0.5, 1.5, 200), np.zeros(200)])
out = model.simulate_batch(x0s, t)
print(out["x"].shape, out["energy"].shape)
```

```text
(200, 1001, 2) (200, 1001)
```

This is the workhorse for Monte Carlo over initial conditions, parameter
sweeps and ensemble forecasts.

## Stepping by hand

`step` advances one interval and returns a :class:`~otwin.State`. Estimators
work this way; so does anything that needs to look at the state between steps.

```python
s = model.initial_state()
s1 = model.step(s, {"force": 0.0}, dt=0.01)
print(s1)
print(round(model.outputs(s1)["spring.force"], 4))
```

```text
State(t=0.01; spring.extension=0.999002, mass.momentum=-0.199601)
19.98
```

## What comes back

A :class:`~otwin.Trajectory`, indexed by name: states (`spring.extension`),
inputs (`force`), every derived quantity (`damper.power`, `mass.velocity`),
`energy`, `supplied_power`, `t`. `run.x` is the raw `(len(t), n_states)`
array, `run.final()` the last state, `run.stats` the solver's own account of
itself. `run.keys()` lists everything.

## Parameters

Parameters are symbolic in the compiled model. `model.parameters` shows them,
`model.set_parameters({"spring.stiffness": 40.0})` changes one in place and
`model.with_parameters(...)` returns a copy. Nothing is recompiled. That is
what makes parameter sweeps and {func}`otwin.fit_parameters` cheap.

## Saving

`model.save("drive.otwin.json")` writes the model definition, not the state,
as human-readable JSON; `otwin.Model.load(path)` reads it back without the
components that made it, on whichever backend is available.
