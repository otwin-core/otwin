# Structure-preserving integration

[Port-Hamiltonian systems](port-hamiltonian.md) established that stored energy
obeys $\mathrm{d}H/\mathrm{d}t \le y^{\mathsf T}u$. That is a statement about the
continuous system. A generic ODE solver does not know it and will not respect
it: run explicit Runge–Kutta on a lossless oscillator for long enough and the
energy drifts, monotonically, in whichever direction the local truncation error
happens to point.

The guarantee has to survive discretisation or it was never usable.

## Implicit midpoint

{func}`~otwin.model.implicit_midpoint` solves, at each step,

$$
x_{n+1} = x_n + \Delta t \; f\!\left(t_{n+\frac12},\; \frac{x_n + x_{n+1}}{2}\right)
$$

Evaluating the vector field at the *midpoint of the step* is what makes the
scheme symplectic on the conservative part and, for a quadratic Hamiltonian,
exactly energy-preserving. The discrete power balance holds to solver tolerance
rather than to truncation order.

The price is that $x_{n+1}$ appears on both sides: every step is a root find.

## The Jacobian a PHS hands you

Write the step as a residual $F(x_{n+1}) = 0$. Damped Newton needs

$$
\frac{\partial F}{\partial x_{n+1}} = I - \frac{\Delta t}{2}\,
\left.\frac{\partial f}{\partial x}\right|_{x_m}
$$

and a port-Hamiltonian model supplies $\partial f/\partial x$ almost for free.
For $f = (J-R)\nabla H + gu$ with state-independent $J$, $R$, $g$:

$$
\frac{\partial f}{\partial x} = (J - R)\,\nabla^2 H
$$

When that matrix is the same at every step — constant structure matrices,
constant $\nabla^2 H$, fixed step — it is **LU factorised once** before the loop.
That is roughly a **140× speedup** over a generic `fsolve` path at $n = 50$,
with the energy bound held to 1e-9.

Supply `hess_H(x)` on your model and {func}`~otwin.model.integrate_phs` will use
it. Supply `jac_rhs(x, u, t)` and it takes precedence.

## How constancy is decided

$J$, $R$, $g$ and $\nabla^2 H$ are evaluated at four well-separated,
deterministic probe states around `x0` and compared. This is a **heuristic**,
and the library is explicit about what a wrong answer costs, because it differs
by path:

- On the **Newton** path a wrong Jacobian costs convergence *rate* only. The
  residual is still driven to `newton_tol`, so the trajectory is unchanged.
  Safe by construction.
- On the **closed-form linear** path a wrong $M$ is a wrong *answer*. That path
  therefore additionally requires the drift $f(x, 0) - Mx$ to be identical at
  every probe — an independent check that a coincidental match is unlikely to
  pass.

Override it when you know better:

```{code-block} python
integrate_phs(phs, x0, t, u=u, constant_structure=False)  # never take the fast path
integrate_phs(phs, x0, t, u=u, constant_structure=True)   # assert it without probing
```

## State-dependent ports

Some machines hold a set point rather than following a schedule: a
constant-power converter, a thermostat, a pump-turbine at rated power. Pass `u`
as a **port law** `u(t, x) -> u`:

```python
import numpy as np
from otwin.model import integrate_phs, water_tank

tank = water_tank()

def hold_level(t, x):
    """Inflow that opposes the level error — a proportional controller."""
    return np.array([0.5 * (2.0 - x[0])])

t = np.linspace(0.0, 20.0, 201)
res = integrate_phs(tank, np.array([1.0]), t, u=hold_level)
print(f"level {res['x'][0, 0]:.3f} -> {res['x'][-1, 0]:.3f}")
print(f"realised port at the end: {res['u'][-1, 0]:.4f}")
```

```text
level 1.000 -> 1.376
realised port at the end: 0.3118
```

The law is evaluated at the step midpoint *inside* the implicit solve, so the
discrete power balance is preserved. The realised port trajectory comes back as
`result["u"]` — worth checking, because a feedback law is part of the model and
you should be able to see what it actually did.

`method="linear"` is **refused** with a port law rather than silently applied.
Feedback makes the system nonlinear; the closed-form path would return a
confident wrong answer.
