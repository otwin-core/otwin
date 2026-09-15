# Grey-box models

The compiled model is what the physics says. Almost every real asset does
something the physics leaves out. This page is about adding that without
rewriting anything.

$$\dot{x} = f_{\text{physics}}(x, u;\ \theta) + f_{\text{residual}}(x, u;\ \phi)$$

Three ways to write the residual. In none of them do you touch the physics.

## Name the phenomenon, let the data size it

You know *what* is missing (quadratic drag, a leak, a contact resistance) but
not how much. Write it as one symbolic term with a new parameter. It is
compiled into the model and runs in the engine like everything else.

```python
import numpy as np
import otwin
from otwin.components.catalogue import mass_spring_damper

physics = otwin.compile(mass_spring_damper(m=1.0, k=2.0, c=0.3, position=1.0))
v = physics.symbol("mass.velocity")

grey = physics.with_residual({"mass.momentum": -physics.parameter("drag") * v * abs(v)},
                             parameters={"drag": 0.1})
print(grey.param_names[-1], grey.representation)
```

```text
drag port-hamiltonian + residual
```

`drag` is now a parameter like `spring.stiffness`: `set_parameters` changes
it, and {func}`otwin.fit_parameters` estimates it from measured outputs. The
plant below is the same physics with the true drag, measured with a little
noise:

```python
plant = physics.with_residual({"mass.momentum": -0.9 * v * abs(v)})
t = np.linspace(0, 8, 161)
measured = plant.simulate(t=t)["spring.extension"] + np.random.default_rng(0).normal(0, 1e-3, t.size)

fit = otwin.fit_parameters(grey, t, {"spring.extension": measured}, ["drag", "spring.stiffness"])
print(fit)
print(fit.identifiability)
```

```text
FitResult(drag=0.900957, spring.stiffness=2.00025; cost=7.374e-05, evaluations=21, identified={'drag': True, 'spring.stiffness': True})
identifiability: all identified (161 rows, 161 units, condition number 1.79)
  drag: identified (collinearity R²=0.265, bootstrap CV=0.00)
  spring.stiffness: identified (collinearity R²=0.265, bootstrap CV=0.00)
```

Twenty-one simulations in the engine, both values recovered, and a verdict on
whether the data determined them. `fit.model` is the calibrated model. The
search runs in the logarithm of every positive parameter, so scales that differ
by orders of magnitude are no trouble; `bounds=` constrains it, `weights=`
weighs outputs against each other.

The identifiability check is not decoration. Fit the same two parameters on
ten samples that barely leave the initial condition and the drag coefficient
is chosen by the noise, which the report says:

```python
short = otwin.fit_parameters(grey, t[:10], {"spring.extension": measured[:10]},
                             ["drag", "spring.stiffness"])
print(short.identifiability.verdicts)
```

```text
{'drag': False, 'spring.stiffness': True}
```

Record the verdicts in the manifest and the envelope refuses to extrapolate
through the undetermined one. See [Identifiability](../concepts/identifiability.md).

## Learn the residual

When you cannot name the phenomenon, learn it. {func}`otwin.hybrid.residual_data`
gives the training target, what the physics leaves unexplained, from measured
states and derivatives:

```python
from otwin.hybrid import residual_data

rng = np.random.default_rng(1)
X = rng.uniform(-1, 1, size=(60, 2))
dXdt = np.array([plant.rhs(x) for x in X])          # measured derivatives, in real life
target = residual_data(physics, X, dXdt)
print(np.abs(target[:, 0]).max(), np.allclose(target[:, 1], -0.9 * X[:, 1] * np.abs(X[:, 1])))
```

```text
0.0 True
```

Fit anything to `(X, target)` and hand it to {class}`otwin.HybridModel`:
a {class}`~otwin.forecast.GPPHS` (whose predictive standard deviation grows
where the data ran out), a {class}`~otwin.model.PortHamiltonianNN`, or any
object with `predict(X)` or `rhs(x, u, t)`. The hybrid keeps the physics'
states, names, energy and `observe`, so it drops into the estimators and the
forecast protocols unchanged.

```python
hybrid = otwin.HybridModel(physics, lambda x, u, t: np.array([0.0, -0.9 * x[1] * abs(x[1])]))
print(np.allclose(hybrid.simulate(t=t).x, plant.simulate(t=t).x, atol=1e-8))
```

```text
True
```

`mask=` restricts the residual to the states it may touch. The physics runs in
the engine; the residual is Python, so the time loop is Python too. That is
the price of a residual you could not write down.

## Write the equations yourself

{class}`otwin.CustomDynamics` wraps any `f(x, u, t)` with the model surface
(`simulate`, `step`, `rhs`, `observe`, `energy`), and
`CustomDynamics.from_phs(...)` does the same for a hand-written
{class}`~otwin.model.PortHamiltonianSystem`. It is the escape hatch; see
[The advanced API](model.md).

## Which one

| you know | use |
|---|---|
| the form of the missing term, not its size | `with_residual` + `fit_parameters` |
| nothing about the missing term, but you have data | `HybridModel` with a GP or a network |
| the whole right-hand side, and no component fits | `CustomDynamics` |

The first keeps everything in the engine and gives you an identifiability
verdict. Prefer it when you can; a named phenomenon with a fitted coefficient
is a claim you can defend, a learned residual is a fit you can only measure.
