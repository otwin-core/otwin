# What is Otwin?

Otwin is a physics engine for the systems engineers maintain: a battery module, a
pump line, a motor drive, a heat exchanger loop, and the larger systems those are
parts of. You describe the system as components and connections. Otwin turns that
description into an executable dynamical model and gives you the tools to keep that
model in step with a real machine.

This page says what the tool is for, what it is not for, and how its parts fit
together. [Architecture](architecture.md) is the same answer in terms of software
layers. [Install](install.md) and the [Quickstart](quickstart.md) are the short
route to a running model.

## The problem it is built for

An engineering system is neither fully known nor fully unknown.

You usually know the conservation laws, the topology of the circuit or the pipework,
where energy is stored and how the parts are joined. You usually do not know
friction, losses, fouling, ageing, the load that was never metered, or the drift of
a sensor.

A model built only from first principles will be confidently wrong about the second
list. A model fitted only from data throws away the first list and will extrapolate
into physical nonsense, because nothing in it forbids that. Otwin keeps the two
apart on purpose. The known physics is structure. Data is used for what the physics
does not know. Both can be inspected and tested separately.

## What it covers

Five physical domains, and one model may span several of them, because a motor is
electrical on one side and mechanical on the other, and a pump is mechanical on one
side and hydraulic on the other.

| Domain | Across variable | Through variable |
|---|---|---|
| electrical | voltage [V] | current [A] |
| mechanical | velocity [m/s] | force [N] |
| rotational | angular velocity [rad/s] | torque [N m] |
| hydraulic | pressure [Pa] | volumetric flow [m³/s] |
| thermal | temperature [K] | heat flow [W] |

Otwin is a lumped-parameter engine. A component is a relation between the quantities
at its ports, not a mesh. It does not solve fields, so there is no finite element
method, no computational fluid dynamics and no electromagnetic field solution. When
such a result matters, its outcome enters an Otwin model as a component law or as a
fitted parameter.

It is not a game or robotics physics engine either. There are no rigid-body
contacts, no collisions and no kinematic chains. Its contact with the world is a
measurement, not a camera.

## What you get from a compiled model

`otwin.compile(system)` returns a `Model`. From there you can

- simulate over a time span, or step one interval at a time from a `State`, which is
  how a model runs alongside a real asset;
- read every quantity by name, including each state, each component's across,
  through and power, each device's own outputs such as `cell.soc` or
  `pump.pressure_rise`, and the stored energy;
- change any parameter without recompiling, and fit parameters to measurements;
- run hundreds of variants at once for a sweep or a Monte Carlo study;
- save the model as readable JSON and load it again without the components that
  built it.

[Simulation](../modeling/simulate.md) covers all of that with the calls.

## From a model to a twin

A simulation model describes a system. A Digital Twin represents one particular
asset and keeps its model in step with what that asset measures. The twin layer adds
state estimation, calibration, hybrid models, forecasting with measured coverage,
leakage-free validation, and a record of what has been demonstrated so that a
question outside it gets a refusal instead of a number.

[Digital twins](../digital-twins/index.md) is that half of the library.

## The two layers

The **engine** compiles and executes physical systems. The **framework** describes
them and does everything a twin needs around them.

| Layer | Module | What it does |
|---|---|---|
| framework | {mod}`otwin.components` | The physical primitives, per domain, plus two-ports and composite devices |
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
{class}`~otwin.interfaces.TwinManifest` that records how a twin was built, fitted,
validated and calibrated.

The compiled model runs on a Rust engine, installed with
`pip install "otwin[engine]"`, or on a NumPy backend when that wheel is absent. Both
give the same results and the test suite holds them together.

## What an Otwin model means

The meaning of an Otwin model is written down independently of this implementation.
[otwin-spec](https://github.com/otwin-core/otwin-spec) is the normative
specification and its conformance suite: physical fixtures with closed-form answers,
thermodynamic constraints and manifest validity. Any implementation can be tested
against it, and this one is.

[The specification](../specification/index.md) explains what that separation buys
you, and [Conformance](../specification/conformance.md) shows what the tests
actually check.

```{toctree}
:hidden:
:maxdepth: 1

architecture
design-principles
install
quickstart
```
