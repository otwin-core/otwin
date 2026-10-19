# Roadmap

Otwin turns a model of a physical asset into a digital twin whose answers can
be checked. It has two parts. The modelling part compiles a description
written as components and connections into an executable model, so an
engineer can build the system they maintain without writing its equations.
The twin part connects a model to the asset's measurements and says, with the
evidence behind it, what the asset is doing, what it is likely to do next,
when to act, and when the evidence is not enough to answer.

This document is the reference for what Otwin will build, what it will not
build, and why. Dates are not promised. Phases are ordered. A phase is done
when its examples run from `pip install otwin` and every printed number is
checked against a closed form or an independent reference. Open items are
discussed in
[Discussions › Ideas & Architecture](https://github.com/otwin-core/otwin/discussions/categories/ideas-architecture);
agreed work is tracked in [Issues](https://github.com/otwin-core/otwin/issues).

## Where Otwin sits

Engineering already has mature tools for building and simulating models of
equipment:

- [Modelica](https://modelica.org) and the tools built on it, such as Dymola,
  OpenModelica and Wolfram SystemModeler, with open and commercial libraries
  for batteries, power plants, hydraulics, buildings and vehicles.
- [FMI](https://fmi-standard.org), the open standard these tools use to
  exchange models. An FMU is the file it produces.
- [ModelingToolkit](https://github.com/SciML/ModelingToolkit.jl) and the SciML
  ecosystem in Julia, and [Dyad](https://juliahub.com/products/dyad) from
  JuliaHub, which combine component modelling with scientific machine
  learning and, in Dyad, AI agents that check the physics of what they write.
- Domain projects such as [PyBaMM](https://pybamm.org) for batteries and
  [OpenIPSL](https://github.com/OpenIPSL/OpenIPSL) for power systems.

These tools answer the question "how do I simulate this equipment?", and
answer it well. Many represent decades of work. Otwin does not try to replace
them.

Otwin's own contribution is what comes after a model exists, when it is
connected to one real asset and used to make decisions about it:

- forecast ranges whose stated coverage is measured on data the model never
  saw;
- a refusal, with the reason, when a question falls outside what the twin has
  been shown to handle;
- a rule that turns a forecast into a decision: act now, act by a given time,
  or there is not yet enough evidence to say;
- a record of what the twin knew at every step, so any answer can be traced;
- an audit of whether an existing model's forecasts keep their promise,
  whichever tool built the model.

Otwin keeps its own modelling layer, because a twin is easier to check when it
can see inside its model: the energy bookkeeping of a compiled Otwin model is
what lets an estimator correct the state without inventing energy. That layer
grows only where a twin needs it and no open model already covers the case.
Where a good model exists, Otwin imports it.

## How we decide what to build

1. **Look before building.** Before a new component family, library or phase
   starts, we survey the open and commercial tools that already cover it, for
   at most two working days, and answer two questions: who already does this,
   and who relies on it. The result is posted in the Discussion for that item
   before any code is written.
2. **Import, do not rewrite.** A model that exists elsewhere comes in through a
   standard interface, such as FMI, or as an optional integration. Otwin does
   not re-implement it.
3. **Keep the core small.** Integrations ship as optional extras, such as
   `otwin[fmi]`, and depend only on permissively licensed packages.
   `pip install otwin` stays compact.
4. **Rust only where the result can be checked.** The engine grows only where
   its output can be validated against an external reference: a closed form,
   a Reference FMU from the Modelica Association, or an established open
   implementation.
5. **Promise only what can be checked.** Otwin cannot see inside an imported
   model, so it never claims an energy guarantee for one, and the twin's
   record says so.
6. **Tests stand on their own.** Every test uses data generated in the test, a
   closed-form answer or a public reference model.
7. **New physics comes with a conformance case.** Every new law adds a
   reference case to [otwin-spec](https://github.com/otwin-core/otwin-spec),
   with a deliberately wrong variant that the suite must catch.

## Done

### 1. The abstractions

`Component`, `Port`, `Connection` and `PhysicalSystem` as the engineer's
surface. Two verbs: `>>` for a line, `connect` where a line is not enough.
The compiler boundary: `otwin.compile(system)` and nothing else.

### 2. Fundamental components and the first devices

`Storage`, `Dissipator`, `Source`, `Reference` in any domain; the domain
libraries (electrical, mechanical, rotational, hydraulic, thermal); the
two-ports. `Battery`, `Pump`, `Filter`, `Losses`, `DCMotor` as devices built
from primitives. `compile()` and `step()`.

### 3. The compiled representation, made explicit

Port-Hamiltonian intermediate representation (`H`, `J`, `R`, `G`), the Rust
engine and the NumPy backend giving the same numbers, tabulated curves and
flow-first laws in the compiler. Two examples from real maintenance problems:
a battery module that runs hot and a pump station that asks for more every
month.

## Next

### 4. The components a twin needs

Devices are added when a twin of a water, process or energy system needs them
and no open model already covers the case. Each one is built from primitives
and ships with a hand-checked example. The first two items:

- **Valves and check valves.** A valve whose opening is either a parameter or
  an input of the model, so that a controller can drive it. A check valve
  that blocks reverse flow apart from a stated leak and never creates energy.
  A closed valve in series with the inertia of the water is a water hammer:
  the compiler refuses it with a reason, or requires a stated minimum leak,
  and never divides by zero. Done when a tank draining through a valve matches
  its closed form, a fully open valve reproduces an orifice, and two tanks
  joined by a check valve never gain energy.
- **Nonlinear algebraic networks.** Today the compiler refuses a node where
  nonlinear laws meet and no storage element fixes the pressure or voltage,
  such as a valve and a nozzle in series, or two valves in parallel. The
  compiler will keep those potentials as algebraic unknowns and solve them
  with Newton's method at every step, in both backends, from a consistent
  initial state. It must also start from rest, where the usual flow laws are
  flat or vertical at zero flow. When Newton does not converge, Otwin stops
  with the reason. Done when a tank draining through a valve and an orifice in
  series matches the closed form of the combined law, two valves in parallel
  split the flow in the ratio of their openings, and the NumPy and Rust
  results agree.

Further devices, such as heat exchangers, membranes, converters and
compressors, each start with the survey in rule 1. Otwin's components are
lumped: one state per store. Models distributed in space, such as long pipes
or the profile along a heat exchanger, are imported (phase 8).

### 5. Identification

Fitting the parameters a data sheet does not give, from measurements, with
identifiability as a first-class result: `fit_parameters` on any compiled or
imported model, and a clear answer when the data cannot determine a parameter.

Next in this phase:

- **How far off a parameter may be.** Every fitted value comes with an
  interval computed from the sensitivities the fit already has. How far this
  item goes is an open question below.
- **Following a parameter as data arrives.** Refit window by window and keep
  the history, for parameters that drift, such as filter fouling or grid
  inertia.

### 6. Learned residuals

What the physics leaves out, learned from data and kept separate from the
structure, so the learned part never touches the model's energy bookkeeping.

Before this phase continues, it goes through the survey in rule 1: universal
differential equations in SciML, the hybrid models in Dyad, and the
residual-learning tools in the battery projects. The phase is reshaped by
what that survey finds.

### 7. The Digital Twin runtime

Measurements in, state estimation, forecasts with measured coverage,
validation, validity envelopes and refusal, on the model of a real asset,
running continuously.

Next in this phase:

- **A record of what the twin knew.** One row per time step with the
  measurement, the estimate, the forecast and its range, the number of
  residuals behind the range, and the decision with its reason. Versioned, so
  any report or screen can read it. A step without a range stores nothing,
  never zero.
- **A decision rule.** When the unfavourable edge of the range crosses a limit
  with enough notice, say when to act. When there are too few residuals behind
  the range, say so in numbers, for example "5 of the 9 needed". When the
  notice asked for goes beyond the horizon the twin was validated on, refuse.
- **Fleets.** Calibrate on many units of the same equipment and test on a
  batch the twin never saw, with no unit in both.
- **A calibration audit.** Given forecasts, ranges and observations from Otwin
  or from any other tool, report for each stated level the coverage actually
  observed, with its own confidence interval, the mean width of the range, and
  the point where coverage started to drift. A range that covers more than it
  states is reported as wider than it needs to be, not as a success.

### 8. Working with the tools engineers already use

Most industrial models already exist. They were built in Modelica tools,
often with commercial libraries, and they represent years of work. Otwin
answers two questions for those models, without asking anyone to rebuild
them: does the forecast hold what it promises, and when should I act?

- **FMU import.** Load an FMU exported from any FMI 2.0 or 3.0 tool and use it
  like an Otwin model: fit its parameters to measurements, calibrate a
  forecast range on data it never saw, audit that range, and apply the
  decision rule. Otwin reads FMUs through FMPy, as the optional extra
  `otwin[fmi]`. An imported model is recorded as such and carries no energy
  guarantee. Done when a Reference FMU from the Modelica Association is
  fitted, forecast, audited and given a decision in a runnable example.
- **Listed where engineers look.** Otwin is added to the tools list of the FMI
  standard as a tool that imports FMUs.

## What Otwin does not build

These needs are real, and other projects already meet them well. Otwin uses
their work instead of duplicating it.

| Need | Where it already exists | What Otwin does |
| --- | --- | --- |
| Models distributed in space: long pipes, heat exchangers, conduction | Modelica libraries; method-of-lines tools in Julia | Imports them as FMUs |
| Power-system networks: buses, lines, generators and their controls | OpenIPSL and other Modelica libraries | Imports them as FMUs |
| Full electrochemical battery models and their degradation | PyBaMM, with PyBOP for parameter fitting | See the first open question |
| Fluid properties such as steam and moist air | CoolProp, iapws, Modelica.Media | Uses them as dependencies when a component needs them |
| Exporting Otwin models as FMUs, or a Modelica library of Otwin blocks | Modelica tools already exchange models as FMUs | Not planned; reconsidered if users ask to run the twin inside their own tool |
| Translating Modelica source into Otwin components | Modelica compilers | Not planned; FMU import covers the need |
| A general modelling language, with or without AI agents | Modelica, ModelingToolkit, Dyad | Not planned |

## Open questions

Each of these is settled in Discussions before any work starts on it.

1. **Ageing models.** Write simple empirical laws for capacity fade and
   fouling growth inside Otwin, or take battery models from PyBaMM as an
   optional source (`otwin[pybamm]`) and add to the engine only a reduced
   single-particle model, validated against PyBaMM.
2. **Drawing the plant.** Whether the twin's record should also hold where
   each component sits on a diagram, so Otwin can draw the plant with its
   latest values, or whether drawing stays with the tools that already do it.
3. **Parameter intervals.** Stop at the intervals the calibration audit
   needs, or go on to carry each parameter's interval through the model to
   every output.

## In parallel

The [otwin-spec](https://github.com/otwin-core/otwin-spec) contract grows with
every phase, so that a physical model means the same thing in every
implementation, and Julia and MATLAB implementations can be tested against it.
Each new law, starting with valves and nonlinear algebraic networks, adds a
reference case with a closed-form answer and a wrong variant the suite must
catch.
