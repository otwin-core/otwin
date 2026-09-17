# Compiler development

Where to look when changing how systems are compiled, and what to keep true.

## The stages, and where they live

All of it is `src/otwin/compiler.py`, one function per stage:

| stage | function | what it produces |
|---|---|---|
| validation | `_validate_components` | unique names, valid parameter values |
| nodes | `_build_nodes` | union-find over connected ports; one reference node; domain check per node; dangling-port errors |
| branches | `_collect_branches` | the flat list of constitutive relations; the representation flag (thermal storages make it pseudo-port-Hamiltonian) |
| symbols | `_declare_symbols` | state symbols, effort placeholders `__effort.i`, parameters, ports (inputs first, then constants) |
| potentials | `_pin_potentials` | BFS over across-storages and across-sources from the reference; every node's potential as an expression in efforts and inputs, or an unknown `__phi.n` per unpinned group; a cycle is a dependent-storage error |
| unknowns | `_solve_unknowns` | one conservation equation per unpinned group, two per two-port; coefficients by differentiation (a coefficient that still depends on an unknown is a nonlinear loop); symbolic Gaussian elimination, constant pivots first |
| assembly | `_assemble` | through variables by peeling the pin trees from the leaves; `dx/dt` per state; port outputs; every branch's across and through for the outputs. Run twice: once with laws as written, once with laws as frozen secant conductances |
| structure | `_extract_structure` | `A = d(rhs)/d(efforts)` on the structural form; `J = (A - Aᵀ)/2`, `R = -(A + Aᵀ)/2`, `G = d(rhs)/d(ports)`, `D = d(y)/d(ports)`; secants substituted back |
| finish | `compile_system` | substitute efforts by `grad_H`, differentiate for the Jacobian, rename parameter symbols to `<component>.<name>`, build the `PHSIR`, run the PSD check |

## Invariants to keep

- **The executable and structural forms agree.** `rhs` is what runs; `J`, `R`,
  `G`, `D` are what is reported. For linear laws they are the same expression;
  for nonlinear ones the structural form uses `law(v)/v`. The tests in
  `tests/engine/test_compiler.py` and the property tests check both.
- **`J` is exactly skew.** It is built as `(A - Aᵀ)/2`, so this holds
  structurally; do not compute it any other way.
- **Every symbol in every final expression is a state, an input, a parameter
  or `t`.** `PHSIR.lower()` fails loudly otherwise, and so does the engine.
- **Parameters stay symbolic.** Never fold a parameter value into an
  expression; `set_parameters` and `fit_parameters` depend on it.
- **Errors are physical.** A refusal names components and ports and says
  what to change. Add a test for every new refusal.
- **The engine stays ignorant.** Anything the runtime needs must fit in the
  lowered IR. If a feature needs the engine to know about components, the
  design is wrong.

## The expression layer

`otwin.expr` is deliberately small: constants, symbols, the arithmetic
operators, `sqrt exp log abs tanh sin cos sign max min gt where`. Simplification
happens in the constructors (`add`, `mul`, `div`, ...), which is why `x - x`
is `0` and `(2 x) / (2 m)` is `x / m` without a separate pass; `_rebuild`
routes `substitute` through the same constructors. Structural equality and
hashing are by value. Adding an operator means: a constructor, a case in
`_diff`, `_eval`, `_fmt`, `_codegen` (NumPy backend) and `Instr` in
`crates/otwin-core/src/expr.rs`, plus a round-trip test.

## Adding a backend

A backend implements the interface in `otwin/runtime/backends.py`: `rhs`,
`jacobian`, `energy`, `grad_h`, `outputs`, `port_outputs`, `supplied_power`,
`step`, `simulate`, `simulate_batch`, over the lowered IR. `select_backend`
chooses it. The parity test in `tests/engine/test_model_api.py` compares any
two backends on every solver; run it against the NumPy reference.

## What is not there yet

Differential algebraic constraints (two rigidly joined inertias, a capacitor
loop) are refused rather than reduced; events (a valve that opens, a contact,
a mode switch) are not in the IR; units are checked at the domain level, not
dimensionally. The IR has room for all three (`PhysicalSystemIR.branches`
records what would need constraining; the runtime's step interface is where an
event would land). Add them behind the same contract.
