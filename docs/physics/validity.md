# Model validity

A model can be wrong in three different ways, and they are caught at three different
times. Knowing which is which saves a long afternoon.

| Question | When it is answered | What answers it |
|---|---|---|
| Is this topology physically meaningful? | at compile time | the compiler refuses, by component name |
| Did the model obey its own energy statement? | after a run | `Trajectory.energy_balance()` |
| Does the structure satisfy its constraints? | on the compiled model | the positive-semidefinite and skew checks |
| Does the model describe the real asset? | against measurements | the [twin layer](../digital-twins/index.md), not this page |

## What the compiler already refused

A model that compiled has no dangling two-port ends, no connections across domains,
no pair of storages fixing the same quantity twice, no node whose potential nothing
determines, and no nonlinear law sitting on a node nothing pins. Each of those is
reported where it happens, with the components named and the fix stated. The table
is in [Compilation](compilation.md).

That is a real guarantee and it is a narrow one. It says the drawing makes physical
sense. It says nothing about whether the numbers in it describe your machine.

## What the compiler produced

Three calls show you the model that came out. None of them is needed to run it.

```{code-block} python
model.summary()      # states with their units, parameters, constant sources, representation
model.structure()    # the matrices of the port-Hamiltonian form: J, R, G, D
model.ir()           # the intermediate representation, including the right-hand side
```

`model.summary()` ends with a **representation** line, and it has two values.

`port-hamiltonian` means the energy audit on this model is a first-law statement.
Stored energy changes by exactly what the ports supplied minus what the resistive
laws removed.

`pseudo-port-hamiltonian` means the model contains a thermal store, or a frozen
heat-generation term such as `Losses`. Temperature times heat flow is not a power,
so the quantity the compiler tracks is a storage function rather than a physical
energy. The heat balances are exact and the model is correct. The audit on it is a
stability statement, not a conservation one. See [Physical
semantics](physical-semantics.md) and [Irreversible systems](irreversible.md).

## Checking a run

Every trajectory carries its own audit.

```{code-block} python
run = model.simulate(t_span=(0, 10), dt=0.01)
run.energy_balance()["max_violation"]     # the worst step, in joules
```

The number is how much stored energy rose beyond what every port together supplied,
on the worst single step of the run. With the default implicit midpoint solver it is
zero, because that scheme preserves the discrete power balance. With an explicit
solver and a loose step it is not, and the size of it is the size of the physics the
integrator invented. On a long run that is the difference between a battery model
that self-discharges and one that charges itself.

This check is cheap, it is available on every run, and it is the first thing to look
at when a simulation drifts. [Structure-preserving integration](integration.md)
explains what the default solver preserves and what it costs.

## Checking a structure

For a model written by hand rather than compiled, the two constraints that make the
energy statement true are worth checking once on a freshly assembled structure.

```{code-block} python
from otwin.model import check_psd, check_skew_symmetric

check_skew_symmetric(phs.J(x))   # (verdict, residual)
check_psd(phs.R(x))              # (verdict, residual)
```

Both return a verdict and a residual, the residual being how far the matrix is from
the property. That distinction matters: it tells you whether a failure is a
modelling error or floating-point dust.

A `J` that is not skew, or an `R` that is not positive semidefinite, is not a
slightly wrong model. It is a model with no passivity guarantee at all, and every
argument for preferring a structured model to a fitted curve stops applying to it.

The compiler builds `J` as an exactly skew matrix by construction, so for a compiled
model the check that can fail is the one on `R`, and it fails exactly when a law
returns power to the system: a damper with a negative coefficient, a resistance law
with the wrong sign. The compiler evaluates `R` at the initial state and warns.

## What validity does not mean

None of this makes a model right about your machine. A structurally perfect model
with the wrong pipe diameter is a structurally perfect wrong answer. The checks on
this page establish that the model is internally consistent physics. Whether it
describes one particular asset is a different question, answered by measurements,
and it has its own half of this documentation: [leakage-free
validation](../digital-twins/validation.md), [measured
coverage](../digital-twins/uncertainty.md), [identifiability](../digital-twins/identifiability.md)
and the [validity envelope](../digital-twins/envelopes.md) that records the answer.

And whether *Otwin itself* computes what an Otwin model is supposed to mean is a
third question again, answered by the [conformance
suite](../specification/conformance.md) against physical fixtures with closed-form
solutions.
