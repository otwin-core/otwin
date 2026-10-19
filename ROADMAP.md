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

On the grid side, the first step is a synchronous area in hertz and megawatts:
system inertia, primary control and fast frequency response as components, so
a frequency twin reads the way a grid engineer draws it. Buses and lines come
after.

### 5. Identification

Fitting the parameters a data sheet does not give, from measurements, with
identifiability as a first-class result: `fit_parameters` on any compiled
model, and a clear answer when the data cannot determine a parameter.

Next in this phase:

- **How far off a parameter may be.** Every fitted value comes with an
  interval, and that interval can be carried through the model to the outputs
  you care about.
- **Following a parameter as data arrives.** Refit window by window and keep
  the history, for parameters that drift, such as fouling or grid inertia.
- **Ageing laws.** Fade, fouling growth and wear as empirical laws inside
  Otwin, fitted and checked like any other model.

### 6. Learned residuals

What the physics leaves out, learned from data and kept separate from the
structure: Gaussian processes, neural residuals and symbolic models attached
to a compiled model without touching its energy bookkeeping.

### 7. The Digital Twin runtime

Measurements in, state estimation, forecasts with measured coverage,
validation, validity envelopes and refusal, on the compiled model of a real
asset, running continuously.

### 8. Working with the relevant enginnering tools 

Most industrial models already exist. They were built in Modelica tools such as
Dymola, OpenModelica or Wolfram SystemModeler, often with commercial libraries
for batteries, power plants, hydraulics or vehicles, and they represent years
of work. Those tools answer the question "how do I simulate this equipment?".
They do not answer "does my forecast hold what it promises?" or "when do I
act?". Otwin should answer those two questions for the models engineers
already have, and not ask anyone to rebuild them.

FMI is the open standard these tools use to exchange models, and an FMU is the
file it produces. This phase connects Otwin to that world in both directions,
in this order.

**Bring their models in: FMU import.** Load an FMU exported from any FMI 3.0 or
2.0 tool and use it like an Otwin model: fit its parameters to measurements,
calibrate a forecast range on data it never saw, audit whether that range
holds, and apply a decision rule. Otwin cannot see inside an FMU, so it will
say so: an imported model carries no energy guarantee, and the twin's record
states it plainly. Done when a Reference FMU from the Modelica Association is
fitted, forecast and audited in a runnable example.

**Take Otwin out to their tools: FMU export.** Write a compiled Otwin model as
an FMI 3.0 FMU, built from the Rust engine, so it runs inside Dymola,
OpenModelica or SystemModeler like any other component and keeps its energy
guarantee. Then export the whole twin, not only the model: measurements go in
as inputs, and the estimated state, the edges of the forecast range and the
decision come out as ordinary signals an engineer can plot in their own tool.
Done when an exported model passes the FMI compliance checker, runs in
OpenModelica on Linux and macOS, and matches Otwin to numerical precision.

**Meet Modelica users where they work: an Otwin Modelica library.** A small
open package, under Apache 2.0, whose blocks are Otwin twins with Modelica
icons and connectors: a twin, its forecast range and its decision. It builds on
the export, not on the import. Done when its examples run in OpenModelica in
continuous integration and the package is listed with the other Modelica
libraries.

**Read Modelica source.** Translate the basic electrical, rotational and
heat-transfer components of the Modelica Standard Library into Otwin
components, through Rumoca, an open Modelica compiler written in Rust. Each
equation is sorted into what stores energy, what dissipates it and what
supplies it; a component that cannot be sorted is refused with a reason rather
than imported without a guarantee. This needs algebraic loops in the compiler
first, and fluid components wait until the translator supports them. Done when
translated components give the same numbers as native ones on systems with a
known answer.

What this phase does not try to do: replace a Modelica tool, or compete with
its component libraries. Otwin is the layer on top that turns a model into a
twin that can be checked.

Next in this phase:

- **A record of what the twin knew.** One row per time step with the
  measurement, the estimate, the forecast and its range, the evidence behind
  the range and the decision, ready for any screen or report.
- **A decision rule.** When the unfavourable edge of the range crosses a
  limit with enough notice, say when to act. When the evidence is too thin,
  say that instead.
- **Fleets.** Calibrate on many units of the same equipment and test on a
  batch the twin never saw.

## In parallel

The [otwin-spec](https://github.com/otwin-core/otwin-spec) contract grows with
every phase, so that a physical model means the same thing in every
implementation, and Julia and MATLAB implementations can be tested against it.
