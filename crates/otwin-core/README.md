# otwin-core

The physics engine behind [Otwin](https://github.com/otwin-core/otwin), the
open-source physics engine for engineering systems. Otwin's Python compiler
turns a description of a physical system (components and connections) into a
port-Hamiltonian model whose entries are symbolic expressions. This crate
runs that model: it loads the lowered form of the intermediate
representation, evaluates `dx/dt = f(x, u, t)`, the Jacobian, the stored
energy and the outputs, and integrates in time with fixed-step and adaptive
methods that keep the energy balance exact.

Nothing in this crate knows what a resistor or a pump is. The compiler
decides what the equations are; the engine executes them. That split is what
lets the same engine serve every physical domain and any implementation of
the [Otwin specification](https://github.com/otwin-core/otwin-spec).

```toml
[dependencies]
otwin-core = "2"
```

```rust
use otwin_core::{simulate, Inputs, Method, Model, Options};

// The lowered IR is JSON: `model.ir().lower()` on the Python side writes it.
let model = Model::from_json_str(include_str!("mass_spring.json"))?;

let x0 = vec![0.0; model.n_states];          // the initial state is the caller's
let t: Vec<f64> = (0..=400).map(|k| k as f64 * 0.05).collect();
let run = simulate(&model, &x0, &t, &Inputs::none(), Method::Midpoint, &Options::default())?;

// run.x is len(t) x n_states, row-major; run.energy has the stored energy at each point
println!("final state {:?}", &run.x[run.x.len() - model.n_states..]);
# Ok::<(), otwin_core::EngineError>(())
```

`step` advances one time step from a state, which is how a model runs
alongside a real asset; `simulate_batch` runs many parameter sets or initial
states in parallel with Rayon. `Method::Midpoint` is the implicit midpoint
rule, the structure-preserving default; `Rk4`, `Rk45` (adaptive) and `Euler`
are there for comparison and for stiff or throwaway work.

Most users never call this crate directly: `pip install "otwin[engine]"`
installs it as the `otwin-engine` Python extension and the Python `Model`
uses it for every simulation. Use the crate on its own to run a compiled
Otwin model where Python is not available, or to build another front end on
the same engine.

Licensed under Apache-2.0. Source, issues and discussions at
[github.com/otwin-core/otwin](https://github.com/otwin-core/otwin).
