<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/otwin_wm.png" width="35%">

# Otwin: An open-source physics engine and Digital Twin framework for engineering systems

### Build, compile, and run physical models — then connect them to real assets.

<br>

[![License](https://img.shields.io/github/license/otwin-core/otwin?color=1a4fd6&cacheSeconds=86400)](https://github.com/otwin-core/otwin/blob/main/LICENSE)

[![PyPI](https://img.shields.io/pypi/v/otwin?color=1a4fd6&cacheSeconds=3600)](https://pypi.org/project/otwin/)
[![Rust](https://img.shields.io/github/actions/workflow/status/otwin-core/otwin/rust.yml?branch=main&label=rust&logo=github)](https://github.com/otwin-core/otwin/actions/workflows/rust.yml)
[![Python](https://img.shields.io/github/actions/workflow/status/otwin-core/otwin/ci.yml?branch=main&label=python&logo=github)](https://github.com/otwin-core/otwin/actions/workflows/ci.yml)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14061/badge)](https://www.bestpractices.dev/projects/14061)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/otwin-core/otwin/badge)](https://scorecard.dev/viewer/?uri=github.com/otwin-core/otwin)
[![REUSE status](https://api.reuse.software/badge/github.com/otwin-core/otwin)](https://api.reuse.software/info/github.com/otwin-core/otwin)
[![SLSA 2](https://slsa.dev/images/gh-badge-level2.svg)](https://github.com/otwin-core/otwin/attestations)

</div>

<br>

## What can you do with Otwin?

If you work with physical systems, Otwin lets you describe the system **as components and connections**, instead of hand-writing the equations.

```python
system = otwin.System(
    mass,
    spring,
    damper,
    force,
    fixed,
)

system.connect(
    mass.flange,
    spring.a,
    damper.a,
    force.flange,
)

system.connect(
    spring.b,
    damper.b,
    fixed.port,
)

model = otwin.compile(system)

run = model.simulate(
    t_span=(0, 20),
    dt=0.05,
)
```

Otwin turns that physical model into compiled, executable dynamics.

```text
components + connections
          │
          ▼
      Otwin compiler
          │
          ▼
    physical model IR
          │
          ▼
   Rust physics engine
          │
          ▼
       TwinModel
```

The same model can then be used for:
* simulation
* state estimation
* parameter calibration
* hybrid physics + data models
* forecasting
* uncertainty quantification
*validation

And because Otwin understands the physical structure, it can catch invalid model topologies before the numerical solver runs.

## The core idea

Most simulation software stops at:

```
physical model → simulation

Otwin extends the stack:

physical system
      │
      ▼
physical model
      │
      ▼
compiler
      │
      ▼
physics engine
      │
      ├── simulation
      ├── estimation
      ├── calibration
      ├── forecasting
      └── validation
             │
             ▼
        Digital Twin
```

The result is not just a simulation model. It is a model that can be executed, connected to measurements, calibrated, tested and validated against a real system.

## Why Otwin?
Model physical systems, not equations Describe components and how they connect:

```python
motor = DCMotor(...)
load = RotationalDamper(...)

system.connect(
    motor.shaft,
    load.a,
)
```

Otwin derives the system dynamics from the physical structure.

## Compile the physics

The Python model is compiled through an intermediate representation into a high-performance Rust runtime.

```
Python API
    ↓
Physical System IR
    ↓
Port-Hamiltonian IR
    ↓
Rust dynamics engine
    ↓
TwinModel
```
Keep physics and data together Known physics remains explicit. Unknown parameters and unmodelled behaviour can be learned from measurements.

```
known physics ────────┐
                      ├──→ hybrid model ──→ prediction
measured behaviour ───┘
```

Make validation part of the model A forecast is not just a number. Otwin can keep track of the evidence supporting it:

```
model
  ├── parameters
  ├── calibration
  ├── validation
  ├── uncertainty
  └── validity envelope
```

When a prediction falls outside the validated envelope, the Digital Twin can say so instead of silently extrapolating.
Owin is being developed around an open specification and conformance suite.

## otwin-spec

The Otwin specification defines the physical and structural contract independently of the Python implementation. The goal is to make an Otwin model something that can be specified, implemented and independently tested. This gives the project a path beyond a single library:

```
Specification
      +
Reference implementation
      +
Conformance suite
      +
Open ecosystem
```

The Python package is the reference implementation today. The specification is the contract that allows the ecosystem to grow beyond it.

#### Otwin is an open physics modeling and execution stack: describe an engineering system, compile its physics, connect it to real measurements, and build a Digital Twin whose predictions can be tested.
