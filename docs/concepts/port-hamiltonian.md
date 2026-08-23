# Port-Hamiltonian systems

A port-Hamiltonian system (PHS) writes a physical asset as an energy balance
rather than as a curve through data. The payoff is a guarantee that holds
*outside* the range you fitted on, which is precisely where a fitted curve
stops meaning anything.

## The form

$$
\begin{align}
\dot{x} &= \bigl(J(x) - R(x)\bigr)\,\nabla H(x) + g(x)\,u \\
y &= g(x)^{\mathsf T}\,\nabla H(x)
\end{align}
$$

| Symbol | Meaning | Constraint |
|---|---|---|
| $H(x)$ | stored energy | bounded below |
| $J(x)$ | interconnection | $J = -J^{\mathsf T}$ (skew-symmetric) |
| $R(x)$ | dissipation | $R \succeq 0$ (positive semidefinite) |
| $g(x)$ | input map | — |
| $u,\;y$ | port variables | $y^{\mathsf T}u$ is power |

$J$ routes energy between stores without creating or destroying any — it is
skew, so $\nabla H^{\mathsf T} J \nabla H = 0$ identically. $R$ is where energy
leaves. $g$ is the port through which the outside world does work on the asset.

## Why the structure is the point

Differentiate the stored energy along a trajectory:

$$
\frac{\mathrm{d}H}{\mathrm{d}t}
= \nabla H^{\mathsf T}\dot{x}
= \underbrace{-\nabla H^{\mathsf T} R\, \nabla H}_{\le\,0\ \text{since } R \succeq 0}
\;+\; y^{\mathsf T}u
\;\le\; y^{\mathsf T}u
$$

The skew part vanished. What remains says the stored energy can grow only by as
much as the port supplies — **passivity**, and it follows from the *shape* of
the model, not from the parameter values, not from the training data, and not
from the accuracy of the integrator.

That is the whole argument for using this form on an asset. A neural network
fitted to a discharge curve will extrapolate to a battery that generates energy;
this cannot, at any parameter setting.

## In the library

{class}`~otwin.model.PortHamiltonianSystem` takes the four functions directly:

```python
import numpy as np
from otwin.model import PortHamiltonianSystem

m, k, b = 1.0, 4.0, 0.3          # mass, stiffness, damping

phs = PortHamiltonianSystem(
    H=lambda x: 0.5 * x[0] ** 2 / m + 0.5 * k * x[1] ** 2,
    J=lambda x: np.array([[0.0, -1.0], [1.0, 0.0]]),
    R=lambda x: np.array([[b, 0.0], [0.0, 0.0]]),
    g=lambda x: np.array([[1.0], [0.0]]),
    n_states=2,
    n_inputs=1,
    grad_H=lambda x: np.array([x[0] / m, k * x[1]]),
)

x = np.array([1.0, 0.5])
print(f"H = {phs.energy(x):.4f}")
print(f"dH/dt with the port closed = {phs.power_balance(x, np.zeros(1))['dH_dt']:.6f}")
```

```text
H = 1.0000
dH/dt with the port closed = -0.300000
```

Pass `grad_H` whenever you have it. Without it the gradient is finite-
differenced, and on a stiff Hamiltonian that is the difference between an
adiabatic energy drift of 1e-13 and one of 1e-6 — quietly weakening the exact
check the class exists to make.

`lambda` for `H`, `J`, `R` and `g` is the intended style, not a shortcut. A
port-Hamiltonian system *is* four functions, and the notation matches the
mathematics on the page. (The library's own lint config exempts `E731` for this
reason.)

## The catalogue

Rather than writing the four functions yourself, start from a worked model:

| Function | Asset | States |
|---|---|---|
| {func}`~otwin.model.mass_spring_damper` | canonical mechanical PHS | momentum, displacement |
| {func}`~otwin.model.dc_motor` | electrical + mechanical, gyrator-coupled | flux linkage, angular momentum |
| {func}`~otwin.model.water_tank` | tank with an open drain (dissipative) | volume |
| {func}`~otwin.model.pumped_hydro` | two-reservoir grid-scale store | two volumes |
| {func}`~otwin.model.heat_exchanger` | counter-flow, irreversible | two temperatures |

## Checking the structure

The two constraints are checkable, and checking them is cheap:

```python
from otwin.model import check_psd, check_skew_symmetric

print(check_skew_symmetric(phs.J(x)))
print(check_psd(phs.R(x)))
```

```text
(True, 0.0)
(True, 0.0)
```

Both return `(verdict, residual)`. The residual is how far the matrix is from
the property — useful when a structure is assembled numerically and you want to
know whether a failure is a genuine modelling error or floating-point dust.

A `J` that is not skew or an `R` that is not PSD is not a slightly wrong model.
It is a model with no passivity guarantee at all, which means every argument on
this page stops applying to it.

## Next

- [Irreversible systems](irreversible.md) — when entropy production has to be
  explicit, and the two forms the literature uses
- [Structure-preserving integration](integration.md) — how to advance the state
  without destroying what this page established
