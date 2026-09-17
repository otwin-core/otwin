# Architecture

Two layers. The **framework** describes systems and does everything a twin
needs around a model. The **engine** compiles and executes them. The boundary
between them is one data structure, the intermediate representation, and one
rule: Python never runs inside the numerical loop.

```text
                       USER
                         |
        +----------------v-----------------+
        |  Python framework                |
        |  otwin.components  otwin.System  |     describe
        |  otwin.compiler -> otwin.ir      |     compile (front end)
        |  otwin.runtime.Model             |     drive
        |  estimate  forecast  advise  io  |     the twin around the model
        +----------------+-----------------+
                         |  lowered IR: expressions as bytecode-ready JSON
        +----------------v-----------------+
        |  otwin-engine  (PyO3)            |     bindings, zero-copy NumPy
        |  otwin-core    (Rust)            |     expression VM, Model, State,
        |                                  |     integrators, batches
        +----------------------------------+
```

## Where the code lives

```text
src/otwin/
  expr.py            symbolic expressions: build, simplify, differentiate, serialise, lower
  ir.py              PhysicalSystemIR, PHSIR: the contract between compiler and runtime
  components/        one module per domain; base.py holds Component, Branch, Port
  system.py          System, chain
  compiler.py        graph -> IR: nodes, pins, symbolic elimination, J/R split, Jacobian
  api.py             otwin.compile
  runtime/
    model.py         Model, State, Trajectory: the user-facing compiled model
    backends.py      RustBackend and NumpyBackend over the same lowered IR
    custom.py        CustomDynamics: a Python f(x, u, t) with the Model surface
  hybrid.py          with_residual support, HybridModel, fit_parameters
  model/ estimate/ forecast/ advise/ io/ signal/ interfaces/   the 0.x packages, unchanged
crates/
  otwin-core/        the engine crate: expr.rs, model.rs, solver.rs, error.rs
  otwin-engine/      the PyO3 module `otwin_engine`, built with maturin, its own wheel
```

## The contract: the lowered IR

`PHSIR.lower()` produces a JSON-serialisable dict:

```text
n_states, n_inputs, n_params, param_values
rhs          [expr]           dx/dt, one per state
jacobian     [expr] | null    n*n, row-major, d(rhs)/dx
energy       expr
grad_H       [expr]
port_outputs [expr]           y, one per port
port_values  [expr]           u of each port: an input slot or a parameter slot
output_names [str], outputs [expr]
```

Every `expr` is a nested list, `["mul", ["const", 2.0], ["ref", 3]]`, where
`ref` indexes a flat evaluation table `[states, inputs, params, t]`. The Rust
side parses each tree once into a postfix program and evaluates it on a stack
with no allocation. The NumPy backend generates a Python function from the
same tree. Both are tested against each other on every solver.

The engine knows nothing about components, domains or port-Hamiltonian
structure. It executes `rhs`, uses `jacobian` for the implicit solver, and
reports `energy` and the supplied power from the port lists. That is
deliberate: a model with no structure at all (a learned right-hand side, a
future DAE backend) goes through the same door.

## Why the compiler front end is Python

The specification that motivated 1.0 placed the compiler in Rust. It is in
Python for one reason: the NumPy fallback. A user without the binary wheel must
still be able to compile and run a model, and a compiler that exists in two
languages is a compiler that disagrees with itself. The IR is the contract, and
it is small enough that a Rust compiler could be added later behind the same
contract without touching the runtime.

## Ownership across the boundary

A Python `Model` holds a `RustBackend`, which holds one `otwin_engine.Model`.
That object owns the bytecode and the parameter vector. Every call crosses the
boundary with NumPy arrays; `simulate` releases the GIL for the whole run and
returns freshly allocated arrays the Python side owns. Nothing on the Python
side points into Rust memory after a call returns. Batches run on a Rayon
thread pool with one scratch buffer per thread.

## The runtime

`Model` is stateless apart from its parameters; `State` is a small value type
(values plus a time); `Trajectory` is the result of a run, indexed by name.
`step` and `simulate` are the two entry points; estimators use `rhs`,
`jacobian` and `observe`. The solvers are the implicit midpoint rule (Newton
on the analytic Jacobian, modified-Newton reuse, step halving on failure),
classical RK4, Dormand-Prince 5(4) with error control, and explicit Euler.

## Testing

`tests/engine/` holds the expression tests, the compiler tests (including the
refusals), golden models against closed forms, regression against the 0.4
hand-written models, Rust/NumPy parity, property tests on random passive
networks, the model API and the grey-box layer. `cargo test -p otwin-core`
covers the expression VM and the solvers on their own. `benchmarks/bench_engine.py`
times the 0.4 integrator against both backends.

## Building

```bash
pip install -e ".[dev]"                                   # the Python framework
pip install maturin
maturin build --release -m crates/otwin-engine/Cargo.toml -o dist   # the engine wheel
pip install dist/otwin_engine-*.whl
cargo test -p otwin-core
pytest -q
```

Without the wheel installed the whole suite still runs; the Rust
parametrisations are skipped.
