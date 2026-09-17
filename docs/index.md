# Overview

Otwin is the open-source physics engine for engineering systems. You describe
a system as components and connections, the way you would draw it on a
whiteboard, and Otwin compiles that description into an executable dynamical
model. The equations are written by the compiler, not by you. Around the
compiled model sit the tools that connect it to a real asset: state
estimation, parameter calibration, hybrid physics-plus-data models,
forecasting with calibrated uncertainty, validation, and validity envelopes
that let a model refuse a question it was never validated for.

```{code-block} bash
pip install "otwin[engine]"
```

This page is the long version of that paragraph. It introduces every element
of an Otwin model, in the order you meet them, and says where each is
documented in detail. It contains almost no code; the [Quickstart](quickstart.md)
is the short version with code, and the [Component reference](reference/components.md)
is the complete inventory.

## What it is for, and what it is not

Otwin is for the systems engineers maintain: a battery module, a pump line, a
motor drive, a heat exchanger loop, and the larger systems those are parts
of. It covers five physical domains (electrical, mechanical, rotational,
hydraulic, thermal) and lets one model span several of them, because a motor
is electrical on one side and mechanical on the other and a pump is
mechanical on one side and hydraulic on the other.

Otwin is a lumped-parameter engine. A component is a relation between the
quantities at its ports, not a mesh. It does not solve fields: no finite
elements, no computational fluid dynamics, no electromagnetic field
solutions. When such a result matters, its outcome enters an Otwin model as a
component law or a fitted parameter. Otwin is also not a game or robotics
physics engine; there are no rigid-body contacts, collisions or kinematic
chains. Its contact with the world is a measurement, not a camera.

Otwin is also not a data-only forecaster. Its stance is that known physics
should remain structure and data should be used for what the physics does not
know: friction, losses, degradation, unmodelled phenomena, changing
parameters. The two are kept separate enough that both can be inspected,
tested and validated.

## The elements of a model

An Otwin model is written from a small vocabulary. Each item below is a
class or a function you will use by name.

**Components** are the physical parts: a `Resistor`, a `Mass`, a `Tank`, a
`ThermalMass`, a `Pump`, a `Battery`. A component is constructed with its
parameters (`Spring(20.0)`, `Battery(capacity=100.0, ocv=[...])`) and gives
them back by name (`spring.stiffness`). Every component belongs to a domain
and declares one or more relations between the quantities at its ports: an
energy store, a dissipation law, an imposed value, or a lossless coupling.
The [Component reference](reference/components.md) lists all of them with
their ports, parameters, units, states and outputs.

**Ports** are where a component can be joined to another. Each port carries
the two variables of its domain: an *across* variable that is shared at a
junction (voltage, velocity, pressure, temperature) and a *through* variable
that sums to zero there (current, force, flow, heat flow). Two-port components
have ports named `p`/`n`, `a`/`b` or `inlet`/`outlet`; one-port components
(a mass, a tank, the atmosphere) measure against the domain's reference and
have a single `port` or `flange`.

**Connections** join ports into a node. The compiler enforces the one rule
that holds in every domain, shared across variable and zero net through
variable at each node, and refuses to join ports from different domains.
Two verbs write every connection. `>>` joins components in a line, the way
the drawing reads: `tank >> pipe >> pump >> filter >> outfall`, or
`mass >> spring >> ceiling`. `connect` joins ports where a line is not
enough: three things meeting at a point, or a second circuit hanging off a
port. A `>>` chain follows the flow a source pushes, so
`gnd >> supply >> motor >> gnd` reads as the current does. The
[Modelling guide](guides/modelling.md) shows both verbs in each domain.

**Parameters** are the numbers a component was built with: a resistance, a
mass, a tank area. They stay symbolic through compilation. The compiled model
names them `spring.stiffness`, `filter.fouling`, `cell.r0.resistance`, changes
any of them without recompiling (`with_parameters`), and can fit them to
measurements (`fit_parameters`). Each parameter has a unit and a validity
rule, checked at construction.

**Inputs** are sources whose value is `None`: a `VoltageSource(None)`, a
`CurrentSource(None)`, a `FlowSource(None)`. They become the inputs of the
compiled model, supplied at run time. A source with a number is a constant
parameter instead.

**Composites** are devices built from these primitives: `DCMotor`, `Pump`,
`Battery`. Inside a composite there is nothing an engineer would not draw on
a whiteboard, and its parts are ordinary components named `<device>.<part>`,
so `cell.r0.power` and `pump.water.flow_momentum` are outputs like any other.
You can write your own composite in the same way; the
[Developer guide](developer/components.md) explains how.

**The system** is the collection of components and connections. `>>` returns
one; `System(...)` builds one explicitly. `system.summary()` lists what it
contains, `system.unconnected()` names any port left dangling.

## What the compiler does

`otwin.compile(system)` turns the system into a model. It finds the states
(the energy stores: charge in a capacitor, momentum of a mass, volume in a
tank, heat in a thermal mass, momentum of the water in a pump), pins the
across variables through them, reads the through variables off the component
laws, and writes `dx/dt = f(x, u)`. It also writes the model in
port-Hamiltonian form, the structure that makes energy bookkeeping exact:
with no input, stored energy can only decrease, and the default integrator
preserves that step by step.

The compiler checks the model before any number is computed: dangling ports,
connections across domains, storage elements that would fix the same
quantity twice, resistive laws that cannot be solved at their node. What it
finds is reported by component name. The [Compilation](concepts/compilation.md)
page explains the passes; `model.ir()`, `model.structure()` and
`model.summary()` show what the compiler produced for a given system. None of
that is needed to use the model.

The compiled model runs on a Rust engine (`otwin-engine`, installed with
`pip install "otwin[engine]"`) or, without it, on a NumPy backend. Both give
the same results; the test suite holds them together.

## What you do with a model

A compiled `Model` simulates over a time span (`model.simulate`), or steps one
time step at a time from a `State` (`model.initial_state`, `model.step`), which
is how a model runs alongside a real asset. `model.outputs(state)` returns
every quantity by name: each state, each component's across, through and
power, each device's own outputs (`cell.soc`, `cell.voltage`,
`pump.pressure_rise`), and the stored energy. `model.state_names`,
`model.param_names` and `model.input_names` tell you what those names are.
The [Simulation guide](guides/simulate.md) and [Devices](guides/devices.md)
walk through a battery module and a pump line end to end, and every number
they print is checked by hand and in the test suite.

Where the physics is incomplete, the model is the structural prior and data
fills the rest. `fit_parameters` calibrates named parameters from
measurements and reports whether the data could determine them
([Identifiability](concepts/identifiability.md)). A residual model, a
Gaussian process or a neural network learns what the physics leaves out,
without replacing the physics ([Grey-box models](guides/greybox.md)).

## From model to Digital Twin

A simulation model describes a system. A Digital Twin represents one
particular asset and keeps its model in step with what that asset measures.
Otwin's twin layer does four things with the compiled model.

It **estimates** the state you cannot measure from the sensors you have, with
Kalman filters or moving-horizon estimation over the compiled dynamics
([Estimation](guides/estimate.md)). It **forecasts** what happens next with
intervals whose coverage was measured on held-out data, not assumed
([Forecasting](guides/forecast.md), [Calibrated intervals](concepts/conformal.md)).
It **validates** out of sample without leaking the future into the fit, and
requires a reference forecaster so that a model is always compared with
something ([Leakage-free evaluation](concepts/leakage.md)). And it records
all of that in a **validity envelope**: the horizons, ranges and conditions
the twin was validated for, so that a question outside them returns a refusal
with a reason rather than a number ([Envelopes](concepts/envelopes.md),
[Advise](guides/advise.md)).

```text
horizon: beyond the validated forecast horizon (asked for 90, validated to 60)
```

The `TwinManifest` records how a twin was built, fitted, validated and
calibrated, so a prediction can always be traced back to the evidence behind
it. [`otwin.io`](guides/io.md) reads the asset (SunSpec, Modbus, a dataset),
and [`otwin.signal`](guides/signal.md) puts irregular samples on a grid.

## Three systems

The README carries three worked systems, each drawn as an engineer would
draw it and each ending in a hand check of the number the model produced.

A **mass on a spring** under gravity: `mass >> spring >> ceiling`, a damper
and the weight meeting at the mass; the compiled model settles at
`weight.force / spring.stiffness` with an energy violation of zero.

A **battery module**: a `Battery` with an OCV table, a series resistance, two
RC pairs and a thermal mass, in a loop with a current load, its thermal port
on a `Convection` to the ambient. One hour at 50 A takes it from 0.9 to 0.4
state of charge, 3.152 V and 33.8 °C, all three checked by hand.

A **pump line**: `Tank >> Pipe >> Pump >> Filter >> Atmosphere`. Clean, the
line carries 235 m³/h; with the filter fouled to twice its resistance,
196 m³/h at a higher pump head, which is the whole story of a filter that
asks for more. [Devices](guides/devices.md) has both device examples with
their hand calculations.

## The shape of the library

Two layers. The **engine** compiles and executes physical systems. The
**framework** describes them and does everything a twin needs around them.

| Layer | Module | What it does |
|---|---|---|
| framework | {mod}`otwin.components` | The physical primitives: electrical, mechanical, rotational, hydraulic, thermal, two-ports, composites, battery |
| framework | {class}`otwin.System` | The component graph: what exists and what is connected |
| engine | {func}`otwin.compile` | The model compiler: graph to intermediate representation to executable model |
| engine | {class}`otwin.Model` | The compiled model: simulate, step, energy, outputs, structure |
| framework | {mod}`otwin.hybrid` | Grey-box models: symbolic residuals, learned residuals, parameter fitting |
| framework | {mod}`otwin.estimate` | Recover the state you cannot measure |
| framework | {mod}`otwin.forecast` | What happens next, and how sure |
| framework | {mod}`otwin.advise` | What to do, or why the twin will not say |
| framework | {mod}`otwin.io`, {mod}`otwin.signal` | Read a device or a dataset; put irregular samples on a grid |
| advanced | {mod}`otwin.model` | Hand-written port-Hamiltonian and irreversible models |

{mod}`otwin.interfaces` sits underneath all of it: the protocols and the
{class}`~otwin.interfaces.TwinManifest` that records how a twin was built,
fitted, validated and calibrated.

## The specification

What an Otwin model means is written down independently of this
implementation. [otwin-spec](https://github.com/otwin-core/otwin-spec) is
the normative specification and its conformance suite: physical fixtures with
closed-form answers, thermodynamic constraints, manifest validity. Any
implementation can be tested against it, and this one is. The
[Port-Hamiltonian](concepts/port-hamiltonian.md) and
[Compilation](concepts/compilation.md) pages give the mathematics the
specification rests on.

## Where to go next

[Install](install.md) and the [Quickstart](quickstart.md) get a drive
compiled, simulated and estimated in twenty lines. The [Guides](guides/index.md)
go task by task: model in each domain, simulate, add what the physics leaves
out, estimate, forecast, advise. The [Concepts](concepts/index.md) pages give
the reasoning behind each design choice. The
[Component reference](reference/components.md) is every component with every
parameter, and the [API reference](api/index.md) is every public name,
generated from docstrings the test suite executes. The [Developer guide](developer/index.md)
is for writing components and working on the compiler. Questions, ideas and
systems you have built go to [Discussions](https://github.com/otwin-core/otwin/discussions).

```{toctree}
:hidden:
:maxdepth: 2

install
quickstart
concepts/index
guides/index
reference/components
developer/index
api/index
changelog
```
