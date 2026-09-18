# Architecture

What Otwin is made of, and where each concern lives. Nothing here is needed to run a
model. It is here because knowing the shape of a tool is what lets you predict how
it will behave when something goes wrong.

Otwin is a compiler and a runtime with a modelling library in front and a digital
twin layer on top. Five stages, each with a boundary that can be inspected.

```{mermaid}
flowchart TD
    A["<b>Modelling layer</b><br/>components · ports · connections · parameters"]
    B["<b>Compiler</b><br/>nodal analysis · symbolic elimination"]
    C["<b>Intermediate representation</b><br/>states · equations · structure · Jacobian"]
    D["<b>Runtime</b><br/>Rust engine, or NumPy reference backend"]
    E["<b>Compiled model</b><br/>simulate · step · outputs · energy"]
    F["<b>Digital twin layer</b><br/>estimate · calibrate · forecast · validate · refuse"]

    A --> B --> C --> D --> E --> F
```

## The modelling layer

This is the part you write. A component is a physical part with ports, parameters
and one or more constitutive relations. A connection joins ports into a node. A
{class}`otwin.System` is the set of both.

The layer checks what it can check without doing any physics: that names are unique,
that parameter values are valid, that a connection does not join a hydraulic port to
a thermal one. It holds no equations. `system.summary()` lists what it contains and
`system.unconnected()` names any port left dangling.

[Modeling](../modeling/index.md) is this layer in full. The meaning of a component,
a port and a connection is in [Physical semantics](../physics/physical-semantics.md).

## The compiler

`otwin.compile(system)` is where the equations are written. It flattens composite
devices, works out which node each port belongs to, finds the energy stores and
makes them the states, applies the conservation law at every node, solves the
resulting algebraic system symbolically and produces `dx/dt = f(x, u)` together with
every output quantity by name.

It refuses before it computes. A dangling port, a connection between two domains,
two storages that would fix the same quantity twice, a nonlinear law on a node that
nothing pins: each of these is reported by component and port name, with what to
change. A model that compiles is a model whose topology is physically meaningful.

[Compilation](../physics/compilation.md) describes the passes and the refusals.

## The intermediate representation

The compiler does not hand equations to the runtime as Python. It produces two data
structures, and they are the contract between the two halves of the project.

The **Physical System IR** ({class}`~otwin.ir.PhysicalSystemIR`) is the resolved
description of the system: components, nodes, branches, states, parameters and
inputs, with every name unique and every connection checked. It says what the system
is and carries no equations. Look here to find out which node a port ended up on.

The **PHS IR** ({class}`~otwin.ir.PHSIR`) is the mathematical form: the energy
function, the structure matrices, the right-hand side already multiplied out, its
analytic Jacobian, the port outputs and the named outputs, every entry a symbolic
expression in the states and parameters. `model.ir()` returns it. `model.to_json()`
writes it as readable JSON and `Model.load` reads it back without the components
that produced it.

Parameters stay symbolic all the way through, which is why
`model.set_parameters({"spring.stiffness": 40.0})` and
{func}`otwin.fit_parameters` cost nothing and never recompile.

## The runtime

The intermediate representation lowers to a flat form where every expression is a
small tree over an evaluation table of states, inputs, parameters and time. Two
backends execute that same form.

`otwin-engine` is the Rust runtime, distributed as a binary wheel. It parses each
expression once into a postfix program and evaluates it on a stack with no
allocation. It releases the interpreter lock for the length of a run and runs
batches on a thread pool. The NumPy backend generates a Python function from the
same trees and is the reference. Both are tested against each other on every solver.

The runtime knows nothing about components, domains or port-Hamiltonian structure.
It executes a right-hand side, uses the Jacobian for the implicit solver and reports
the energy and the supplied power from the port lists. That is deliberate. A model
with no physical structure at all, such as a learned right-hand side added through
{class}`otwin.CustomDynamics`, goes through the same door and gets the same
interface.

## The compiled model

{class}`otwin.Model` is what you hold. It simulates, steps, reports outputs by name,
reports its own energy balance, exposes its structure and its intermediate
representation, and carries its parameters. It is stateless apart from those
parameters. {class}`otwin.State` is a small value type, and
{class}`otwin.Trajectory` is the result of a run, indexed by name.

[Simulation](../modeling/simulate.md) is the whole surface.

## The digital twin layer

Everything above describes a system. This layer attaches the model to one particular
asset. It reads devices and datasets, puts irregular samples on a uniform grid,
estimates the states nobody measured, fits the parameters the data can determine,
learns what the physics leaves out, forecasts with intervals whose coverage was
measured, validates without leaking the future into the fit, and records all of it
in a {class}`~otwin.interfaces.TwinManifest` so that a prediction can be traced back
to its evidence.

These modules are laid out as the six data-processing blocks of ISO 13374, the
standard for condition monitoring of machines, so that a reader who knows the
reference architecture already knows where to look. See [The six
blocks](../digital-twins/iso13374.md).

## Why the boundaries are where they are

**Python describes, Rust executes.** The numerical loop never calls back into
Python. That is what makes a hundred thousand steps cheap, and it is why the
contract between the two is a data structure rather than a set of callbacks.

**The compiler front end is in Python.** A user without the binary wheel must still
be able to compile and run a model, and a compiler that exists in two languages is a
compiler that disagrees with itself. The intermediate representation is the
contract, and it is small enough that a second compiler could be added behind it
without touching the runtime.

**The engine stays ignorant of physics.** Anything the runtime needs has to fit in
the lowered representation. If a feature would require the engine to know what a
component is, the design is wrong.

**The meaning of a model is written down elsewhere.** The specification and its
conformance suite live in their own repository, so that an implementation in another
language can be judged by the same tests as this one. See [The
specification](../specification/index.md).

## The project

| Repository | What it is |
|---|---|
| [otwin](https://github.com/otwin-core/otwin) | The framework, the compiler and the engine. This documentation. |
| [otwin-spec](https://github.com/otwin-core/otwin-spec) | The normative specification and the conformance suite |
| [otwin-hybrid](https://github.com/otwin-core/otwin-hybrid) | A worked case in Python, Julia and R: end of life of a lithium-ion cell from the first 40 % of its life |

The engine lives in this repository under `crates/`. `otwin-core` is a plain Rust
crate with no Python in it, and `otwin-engine` provides the bindings and is
published as its own wheel. [Internals](../developer/internals.md) is the code-level
map for anyone working on either.
