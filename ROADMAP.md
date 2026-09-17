# Roadmap

Otwin compiles a description of a physical system, written as components and
connections, into an executable model. The roadmap follows one question: can
an engineer build the system they maintain without writing its equations?
Each phase widens the set of systems for which the answer is yes.

Dates are not promised. Phases are ordered; a phase is done when its examples
run from `pip install otwin` with every printed number checked by hand. The
open items of each phase live in
[Discussions › Ideas & Architecture](https://github.com/otwin-core/otwin/discussions/categories/ideas-architecture);
concrete, agreed work is tracked in [Issues](https://github.com/otwin-core/otwin/issues).

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

### 4. The component library

More of the devices engineers actually maintain, each built from primitives
and shipped with a hand-checked example: heat exchangers, valves and check
valves, membranes, converters and inverters, transformers for the grid side,
compressors, PV strings. Priorities are set by what people ask for in
Discussions; the four most useful contributions are listed in
[CONTRIBUTING.md](CONTRIBUTING.md).

### 5. Identification

Fitting the parameters a data sheet does not give, from measurements, with
identifiability as a first-class result: `fit_parameters` on any compiled
model, and a clear answer when the data cannot determine a parameter.

### 6. Learned residuals

What the physics leaves out, learned from data and kept separate from the
structure: Gaussian processes, neural residuals and symbolic models attached
to a compiled model without touching its energy bookkeeping.

### 7. The Digital Twin runtime

Measurements in, state estimation, forecasts with measured coverage,
validation, validity envelopes and refusal, on the compiled model of a real
asset, running continuously.

## In parallel

The [otwin-spec](https://github.com/otwin-core/otwin-spec) contract grows with
every phase, so that a physical model means the same thing in every
implementation, and Julia and MATLAB implementations can be tested against it.
