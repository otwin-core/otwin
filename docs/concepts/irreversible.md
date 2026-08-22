# Irreversible systems

A plain PHS gets the first law for free: the skew part of the structure cannot
create energy. It says nothing about the second. For a reactor, a heat
exchanger or any process where entropy production is the phenomenon rather than
a nuisance, you need the second law to be part of the model.

`otwin` implements **both** forms the literature uses. They are not notational
variants of each other — getting from one to the other is a derivation — which
is why both are here.

## Form 1: additive entropy coupling

{class}`~otwin.model.IrreversiblePHS`:

$$
\begin{align}
\dot{x} &= \bigl(J(x) - R(x)\bigr)\nabla H(x) + L(x)\,\nabla S(x) + g(x)\,u \\
y &= g(x)^{\mathsf T}\nabla H(x) \\
\sigma(x) &= \nabla S^{\mathsf T} L \,\nabla S \;\ge\; 0
\end{align}
$$

$S(x)$ is entropy or availability, $L(x)$ the irreversible coupling. The second
law holds **iff $L \succeq 0$** — it is a property of the structure, so it can
be checked once and relied on.

The library enforces it rather than assuming it. With `validate=True` (the
default) $L$ is checked on first use and a `ValueError` is raised if it is not
PSD.

## Form 2: modulated skew interconnection

{class}`~otwin.model.ModulatedIPHS`, the Ramírez–Maschke–Sbarbaro form that
most of the irreversible-PHS literature is written in:

$$
\begin{align}
\dot{x} &= \gamma(x)\,J(x)\,\nabla H(x) - R(x)\nabla H(x) + g(x)\,u \\
\sigma(x) &= \nabla S(x)^{\mathsf T}\,\gamma(x) J(x)\nabla H(x) \;\ge\; 0
\end{align}
$$

A **scalar modulating function** $\gamma$ multiplies a skew interconnection.

Here is the part worth being careful about. $\gamma J$ is skew for *any* scalar
$\gamma$, so with $R = 0$ and the ports closed,
$\mathrm{d}H/\mathrm{d}t = \nabla H^{\mathsf T}\gamma J \nabla H = 0$
identically — the first law is still structural. **The second law is not.**
Nothing about a skew matrix forces $\nabla S^{\mathsf T}\dot{x} \ge 0$.

In the reactor case it holds because $\gamma = r/T$ is built from the affinity
so that $\operatorname{sign}(r) = \operatorname{sign}(A)$ — a property of *that
model*, not of the form. So `ModulatedIPHS` evaluates and checks $\sigma$ on
every dynamics call, which is the same bargain `IrreversiblePHS` strikes with
$L \succeq 0$, paid at a different time.

## Which to use

| | Additive `L∇S` | Modulated `γ·J∇H` |
|---|---|---|
| Second law from | $L \succeq 0$, structural | $\gamma$, model-specific |
| Checked | once, on first use | every dynamics call |
| Natural for | heat conduction, diffusive coupling | reaction kinetics, affinity-driven transport |
| Literature | van der Schaft & Maschke | Ramírez, Maschke & Sbarbaro |

{meth}`~otwin.model.IrreversiblePHS.from_modulated` builds one from the other
when you need to move between them.

## A worked irreversible model

{func}`~otwin.model.heat_exchanger` returns a two-node counter-flow exchanger
as a `ModulatedIPHS`:

```python
from otwin.model import effectiveness_ntu, heat_exchanger

hx = heat_exchanger(UA=40_000.0, C_hot=500_000.0, C_cold=800_000.0)
print(type(hx).__name__, "with", hx.n_states, "states")

eps = effectiveness_ntu(UA=40_000.0, C_hot=500_000.0, C_cold=800_000.0)
print(f"effectiveness = {eps:.4f}")
```

```text
ModulatedIPHS with 2 states
effectiveness = 0.0751
```

{func}`~otwin.model.effectiveness_ntu` is the steady-state ε-NTU duty, for
sizing and for cross-checking the dynamic model against the design point.

## Fouling is not a port-Hamiltonian system

{func}`~otwin.model.kern_seaton_fouling` returns a
{class}`~otwin.model.FoulingLaw`, and that class deliberately has no `rhs`:

$$
R_f(t) = R_f^{\infty}\left(1 - e^{-t/\tau}\right)
$$

Fouling has no conserved energy and no power port. Dressing an empirical trend
law up as a physical structure would let it inherit guarantees it has not
earned. It is typed as
{class}`~otwin.interfaces.EmpiricalLawModel` instead, and the envelope machinery
treats it accordingly.
