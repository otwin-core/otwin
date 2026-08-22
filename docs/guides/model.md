# Model — `otwin.model`

The asset, written as an energy balance. The theory is in
[Port-Hamiltonian systems](../concepts/port-hamiltonian.md) and
[Irreversible systems](../concepts/irreversible.md); this page is how to get one
built and running.

## Start from the catalogue

| Function | Asset | Kind |
|---|---|---|
| {func}`~otwin.model.mass_spring_damper` | canonical mechanical PHS | PHS |
| {func}`~otwin.model.dc_motor` | electrical + mechanical, gyrator-coupled | PHS |
| {func}`~otwin.model.water_tank` | tank with an open drain | PHS, dissipative |
| {func}`~otwin.model.pumped_hydro` | two-reservoir grid-scale store | PHS, conservative |
| {func}`~otwin.model.heat_exchanger` | counter-flow exchanger | `ModulatedIPHS` |
| {func}`~otwin.model.effectiveness_ntu` | steady-state ε-NTU duty | — |
| {func}`~otwin.model.kern_seaton_fouling` | fouling resistance over time | `FoulingLaw` |

Reading one of these is the fastest way to learn how to write your own: each
carries the reference it came from, its state vector, its ports and its
structure matrices in the docstring.

## Build your own

Three classes, in increasing order of what they promise:

{class}`~otwin.model.PortHamiltonianSystem`
: $\dot{x} = (J-R)\nabla H + gu$. Pass `H`, `J`, `R`, `g`, and `grad_H` whenever
  you have it.

{class}`~otwin.model.IrreversiblePHS`
: adds $L(x)\nabla S(x)$ and enforces $L \succeq 0$, so $\sigma \ge 0$ is
  structural.

{class}`~otwin.model.ModulatedIPHS`
: $\gamma(x)\,J\nabla H$, the Ramírez–Maschke–Sbarbaro form. $\sigma$ is checked
  on every call because for this form it is a property of $\gamma$, not of the
  structure.

{class}`~otwin.model.PortHamiltonianNN` learns $H$, $J$ and $R$ from data with
the skew/PSD/bounded-below constraints built into the parameterisation, so the
learned model is passive by construction rather than by regularisation. Needs
`pip install "otwin[nn]"`.

## Check what you built

```{code-block} python
from otwin.model import check_psd, check_skew_symmetric
```

Both return `(verdict, residual)`. Run them once on a freshly assembled
structure. A `J` that is not skew is not a slightly wrong model — it is a model
with no passivity guarantee at all.

{func}`~otwin.model.numerical_gradient` is the central-difference fallback used
when you do not supply `grad_H`. It is there so that a model without an analytic
gradient still works, not because it is a good idea: on a stiff Hamiltonian it
is the difference between an adiabatic energy drift of 1e-13 and one of 1e-6.

## Integrate

{func}`~otwin.model.integrate_phs` is the entry point;
{func}`~otwin.model.implicit_midpoint` is the scheme;
{func}`~otwin.model.newton_step` is the damped Newton solve underneath, exposed
because a failed step is something you sometimes need to inspect.
{func}`~otwin.model.integrate` and
{func}`~otwin.model.integrate_with_inputs` are the generic-ODE paths for models
that are not port-Hamiltonian.

See [Structure-preserving integration](../concepts/integration.md) for what the
solver preserves and why the fast path is guarded.

## Training losses

For fitting a model against data while keeping its structure:
{func}`~otwin.model.derivative_loss` (mean-squared error between predicted and
target derivatives) and {func}`~otwin.model.passivity_penalty` (a soft penalty
on energy growth at zero input).

Use the penalty as a diagnostic, not as the guarantee. A soft penalty that
happens to reach zero on your training set is not the same as a structure that
cannot violate passivity at any parameter value — and the second is what makes
the model trustworthy off-distribution.

## Next

[Forecast](forecast.md) — running the model forward, and being honest about it.
