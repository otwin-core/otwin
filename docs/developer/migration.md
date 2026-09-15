# Migration map: from a modelling library to a compiled engine

This page records what the library looked like before the engine, what each
public name became, and why the new layout is the way it is. Read it if you
maintained code against otwin 0.x or if you want to know where a decision
came from.

## What 0.4 was

Six packages arranged after the ISO 13374 processing blocks, composing through
protocols in `otwin.interfaces`:

| Package | Contents in 0.4 | Fate in 1.0 |
|---|---|---|
| `otwin.model` | `PortHamiltonianSystem`, `IrreversiblePHS`, `ModulatedIPHS`, `integrate_phs`, `implicit_midpoint`, `integrate`, `integrate_with_inputs`, catalogue functions (`water_tank`, `mass_spring_damper`, `dc_motor`, `pumped_hydro`, `heat_exchanger`), `PortHamiltonianNN`, fouling laws | Retained as the **advanced API**. Nothing removed. `PortHamiltonianSystem` and the callable-based integrators are the escape hatch for physics the component library does not cover |
| `otwin.estimate` | `KalmanFilter`, `ExtendedKalmanFilter`, `MovingHorizonEstimator`, `EnergyConsistentObserver`, `identifiability` | Retained unchanged. A compiled `otwin.Model` satisfies `TwinModel`, so every estimator consumes it directly |
| `otwin.forecast` | `evaluate`, splitters, baselines, metrics, conformal bands, `Ensemble`, `GPPHS` | Retained unchanged. `Model.forecast` and `GPPHS(prior_dynamics=model.rhs)` bridge to the compiled model |
| `otwin.advise` | `Envelope`, `Verdict`, `Breach` | Retained unchanged |
| `otwin.io`, `otwin.signal` | SunSpec, Modbus, datasets, resampling | Retained unchanged |
| `otwin.interfaces` | protocols, results, `TwinManifest` | Retained. `TwinManifest.model_class` gains the value `"compiled"` |

## What 1.0 adds

| New package | Role |
|---|---|
| `otwin.expr` | A small symbolic expression type. Every constitutive law, energy term and control law the compiler sees is an `Expr`, so the engine can evaluate, differentiate and serialise it without calling back into Python |
| `otwin.components` | The physical primitives, one module per domain (`electrical`, `mechanical`, `rotational`, `hydraulic`, `thermal`, `twoport`, `composite`). A component declares ports, parameters, states and laws. It contains no numerics |
| `otwin.system` | `System`: the component graph. `connect` joins terminals into nodes. Domain and unit checks happen here, before compilation |
| `otwin.ir` | `PhysicalSystemIR` (what the user described, resolved) and `PHSIR` (the port-Hamiltonian form `ẋ = (J − R)∇H + G u`, `y = Gᵀ∇H + D u`, all entries `Expr`). Both serialise to JSON |
| `otwin.compiler` | Front end: graph → `PhysicalSystemIR` → `PHSIR`. Nodal analysis with symbolic elimination, structural error reporting, J/R split, symbolic gradient and Jacobian |
| `otwin.runtime` | `Model`, `State`, `Trajectory`. Owns the compiled representation and dispatches to a backend |
| `otwin.runtime.backends` | `rust` (the `otwin_engine` extension, default when installed) and `numpy` (reference implementation of the same IR, used as fallback and as the oracle in regression tests) |
| `otwin_engine` (separate wheel, `crates/otwin-engine`) | PyO3 bindings over the `otwin-core` crate: expression bytecode, state, integrators, power balance. The numerical inner loop lives here |

The compiler front end is Python rather than Rust. That is a deliberate
departure from the original specification: the numpy fallback is only useful
if a model can be compiled without the extension, and a compiler that exists
twice is a compiler that disagrees with itself. The IR is the contract. The
Rust crate consumes it and never sees a component.

## Public API classification

| Name | 0.4 status | 1.0 status |
|---|---|---|
| `otwin.model.PortHamiltonianSystem` | primary | retained, advanced |
| `otwin.model.integrate_phs` and friends | primary | retained, advanced; `Model.simulate` is the recommended path |
| `otwin.model.water_tank`, `mass_spring_damper`, `dc_motor`, `pumped_hydro` | catalogue | retained; each now has a component twin in `otwin.components.catalogue` with a regression test against the old function |
| `otwin.model.heat_exchanger`, `IrreversiblePHS`, `ModulatedIPHS` | catalogue / class | retained, advanced (entropy-carrying models have no primitive yet) |
| `otwin.model.PortHamiltonianNN` | learned model | retained |
| `otwin.estimate.*`, `otwin.forecast.*`, `otwin.advise.*`, `otwin.io.*`, `otwin.signal.*` | primary | retained unchanged |
| `otwin.System`, `otwin.compile`, `otwin.Model`, `otwin.components.*` | — | **new primary API** |
| `otwin.CustomDynamics` | — | new advanced API: wrap an `f(x, u, t)` callable as a `Model` (numpy backend only) |

No name is removed in 1.0. Deprecation warnings are not emitted either: the
advanced API is a supported layer, not a leftover.

## Notebook inventory

| Notebook | Physics | Model definition in 0.4 | Migration |
|---|---|---|---|
| 01 A model that cannot invent energy | pumped hydro with penstock friction; flywheel with speed-dependent bearing loss | two `PortHamiltonianSystem` with hand-written `H`, `R` | rebuilt from `Reservoir`, `Penstock`, `Inertia`, `RotationalDamper(law=...)`; numbers compared to the 0.4 run |
| 02 When the process makes entropy | adiabatic reactor, entropy state | `IrreversiblePHS.from_modulated` | stays on the advanced API; the notebook now says so and why |
| 03 Scoring a forecast | capacity fade law | `EmpiricalLawModel` only | imports unchanged |
| 04 A band whose 90 % means 90 % | conformal bands | no physics model | unchanged |
| 05 From a noisy sensor to a state | flywheel + EKF / MHE / energy observer | `PortHamiltonianSystem` wrapped in a `TwinModel` shim | flywheel from components; the compiled `Model` goes straight into the estimators |
| 06 The twin that says no | manifest and envelope | no physics model | unchanged |
| 07 Field data | fade laws on RWTH data | empirical | unchanged |
| 08 Does the physics earn its place | fade laws + residual learners | empirical | unchanged |

## Test inventory

0.4 shipped 636 tests in `tests/`. All of them are kept and still pass. 1.0
adds `tests/engine/` (expressions, compiler, golden models, Rust/numpy parity,
regression against the 0.4 catalogue, property tests) and `crates/otwin-core`
carries its own `cargo test` suite.

## Dependency map

```
otwin            numpy, scipy                    pure Python, always installable
otwin[engine]    + otwin-engine                  the Rust runtime (binary wheel)
otwin[modbus]    + pymodbus
otwin[sunspec]   + pysunspec2, pymodbus
otwin[nn]        + torch
otwin[gp]        + scikit-learn
otwin[all]       every extra above
otwin[dev]       test and lint tooling, without torch
```

`otwin` never imports `otwin_engine` at module level. The runtime probes for
it once and falls back to numpy with a single `EngineNotAvailable` warning.
