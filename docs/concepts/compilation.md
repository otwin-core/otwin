# Compilation

What the engine computes from what you described. You do not need this page to
use otwin. Read it when a model surprises you, or when you want to know why
the energy balance is a property of the model rather than a hope about the
solver.

## The pipeline

```text
System
  -> flatten composites; validate names and parameter values
  -> nodes: the union of connected terminals, plus one reference node
  -> branches: storages, resistors, sources, two-ports
  -> potentials: storages and across-sources pin potential differences
  -> one conservation equation per unpinned node group,
     two constraint equations per two-port
  -> solve them symbolically (linear in the unknowns, or refuse)
  -> recover every through variable by peeling the trees of pinned branches
  -> dx/dt for every state, in two forms
  -> J, R, G, D read off the structural form
  -> analytic Jacobian of the executable form
  -> PHSIR
```

Every step works on symbolic expressions ({mod}`otwin.expr`), so the result is
exact and serialisable, and the engine can evaluate and differentiate it
without calling Python.

## Two intermediate representations

The **Physical System IR** ({class}`~otwin.ir.PhysicalSystemIR`) is the
resolved description: components, nodes, branches, states, parameters, inputs,
every name unique and every connection checked. It says what the system is and
carries no equations. `model.ir().physical` is where to look when you want to
know which node a terminal ended up on.

The **PHS IR** ({class}`~otwin.ir.PHSIR`) is the mathematical form:

$$\dot{x} = \big(J(x) - R(x)\big)\nabla H(x) + G(x)\,u, \qquad
  y = G(x)^{\top}\nabla H(x) + D(x)\,u$$

with every entry an expression in the states and parameters. It also carries
the right-hand side already multiplied out (what the runtime executes), the
Jacobian of that right-hand side (what the implicit solver uses), the energy
and its gradient, the port outputs and the named outputs. `model.ir()` returns
it; `model.to_json()` and `Model.save` write it as human-readable JSON;
`Model.load` reads it back without the components.

Port-Hamiltonian form is *an* internal representation. The runtime executes the
right-hand side and knows nothing about $J$ or $R$; a model added through
{class}`otwin.CustomDynamics` has neither and runs the same way. What the
structure gives, when it exists, is the next section.

## Why the split into J and R

Write the assembled right-hand side as $\dot{x} = A(x)\nabla H + G u$. The
compiler reads $A$ off by differentiation with respect to the efforts
$\nabla H$, then sets $J = (A - A^{\top})/2$ and $R = -(A + A^{\top})/2$. The
skew part is exactly skew because it was built that way. The symmetric part
collects the dissipative laws, and along $\nabla H$ its quadratic form is the
power leaving through resistors, dampers, orifices and thermal resistances:

$$\frac{dH}{dt} = -\nabla H^{\top} R\, \nabla H + y^{\top} u .$$

With the sources at zero and $R \succeq 0$, stored energy cannot rise. That is
an algebraic property of the model, true at every state and every step size.
The compiler evaluates $R$ at the initial state and warns if it is not positive
semidefinite, which happens exactly when a law returns power to the system: a
damper with a negative coefficient, a resistor law with the wrong sign.

For a nonlinear law, $R$ is not what the runtime uses. The executable form
keeps the law as written, `through = law(across)`, and $R$ carries the
*secant* conductance `law(v) / v`, guarded at zero by the slope of the law
there. That keeps the reported structure exact where it is defined and keeps
the simulation free of divisions by zero.

## Constant sources are ports too

A weight on a mass, an ambient temperature, a fixed supply voltage: sources with
a value are constant parameters, and they are still ports. `G` has a column for
each, the port output `y` has an entry for each, and the power they supply
enters the balance. `Trajectory.energy_balance()` checks, step by step, that
stored energy rose by no more than all the ports together supplied.

## Thermal models

Temperature times heat flow is not a power. The compiler treats the thermal
domain with the same machinery and reports the result as
`pseudo-port-hamiltonian`: the storage function $E^2/2C$ it builds for a
thermal mass is a Lyapunov function whose gradient is the temperature, not a
physical energy. The equations that come out are the ordinary lumped heat
balances and they are correct; the energy audit on a thermal model is a
stability statement, not a first-law one. Entropy-carrying models with a real
energy live in the advanced API, {class}`~otwin.model.IrreversiblePHS`.

## What the compiler refuses

Errors name components and terminals, before anything is simulated.

| the compiler says | what it means | what to do |
|---|---|---|
| incompatible connection | terminals of two domains on one node | couple the domains with a `Transformer` or `Gyrator` |
| not connected to anything | a two-terminal component with a loose end | connect it, or to `Ground` |
| dependent storages or sources | two capacitors in parallel, two inertias on one shaft, a source across a storage | merge them, or put a resistor, damper or stiff spring between |
| nonlinear algebraic loop | a nonlinear law on a node no storage or source pins | make that element linear, or add a small storage to the node |
| singular | a node whose potential nothing determines | give it a path to the reference |
| stores no energy | no capacitor, mass, tank, inertia or thermal mass | there is no state to integrate |

Algebraic loops through *linear* elements are solved at compile time; the
result is a right-hand side with the loop already eliminated. Differential
constraints (two rigidly joined inertias) are refused rather than turned into
a DAE. That is a design choice for this version, not a permanent one; the IR
has room for constraints.

## Reading a compiled model

```python
import otwin
from otwin.components.catalogue import mass_spring_damper

model = otwin.compile(mass_spring_damper(m=1.0, k=20.0, c=0.3))
ir = model.ir()
print(ir.state_names(), ir.ports)
print(ir.rhs[1])
print(model.structure()["R"])
```

```text
['spring.extension', 'mass.momentum'] ['force']
input:force - (param:spring.stiffness * state:spring.extension + param:damper.damping * (state:mass.momentum / param:mass.mass))
[[0.  0. ]
 [0.  0.3]]
```

The right-hand side reads as the equation a person would write:
$\dot p = F - kq - c\,p/m$. Parameters are symbolic, which is what makes
`set_parameters` and `fit_parameters` possible without recompiling.
