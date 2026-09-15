# otwin

**Describe the machine. Otwin derives the physics.**

`otwin` is a physics-based digital-twin framework with a compiled dynamics
engine. You describe a physical asset as components and connections, the way
you would draw it. Otwin compiles the description into a physically consistent
model, runs it in a Rust engine, keeps it in step with the asset from
measurements, forecasts with intervals whose coverage has been measured, and
refuses to answer questions the twin was never validated for.

That last part is the unusual one. Most forecasting libraries always return a
number. This one returns a refusal with a reason when the number would be
unjustified:

```text
horizon: beyond the validated forecast horizon (asked for 90, validated to 60)
```

```{code-block} bash
pip install "otwin[engine]"
```

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`rocket` Quickstart
:link: quickstart
:link-type: doc

Twenty lines: build a drive from components, compile it, simulate it in the
engine, estimate its state from a noisy sensor, and watch the twin decline a
question it cannot support.
:::

:::{grid-item-card} {octicon}`book` Concepts
:link: concepts/index
:link-type: doc

What a component is, what the compiler does with it, and the mathematics
underneath: port-Hamiltonian form, structure-preserving integration,
leakage-free evaluation, conformal bands.
:::

:::{grid-item-card} {octicon}`tools` Guides
:link: guides/index
:link-type: doc

Task by task: model in each physical domain, simulate, add what the physics
leaves out, estimate, forecast, advise.
:::

:::{grid-item-card} {octicon}`code` API reference
:link: api/index
:link-type: doc

Every public name, generated from the docstrings the test suite executes.
:::

::::

## The shape of the library

Two layers. The **engine** compiles and executes physical systems. The
**framework** describes them and does everything a twin needs around them.

| Layer | Module | What it does |
|---|---|---|
| framework | {mod}`otwin.components` | The physical primitives: electrical, mechanical, rotational, hydraulic, thermal, two-ports, composites |
| framework | {class}`otwin.System` | The component graph: what exists and what is connected |
| engine | {func}`otwin.compile` | The model compiler: graph to intermediate representation to executable model |
| engine | {class}`otwin.Model` | The compiled model: simulate, step, energy, outputs, structure |
| framework | {mod}`otwin.hybrid` | Grey-box models: symbolic residuals, learned residuals, parameter fitting |
| framework | {mod}`otwin.estimate` | Recover the state you cannot measure |
| framework | {mod}`otwin.forecast` | What happens next, and how sure |
| framework | {mod}`otwin.advise` | What to do, or why the twin will not say |
| framework | {mod}`otwin.io`, {mod}`otwin.signal` | Read a device or a dataset; put irregular samples on a grid |
| advanced | {mod}`otwin.model` | Hand-written port-Hamiltonian and irreversible models |

{mod}`otwin.interfaces` sits underneath all of it: the protocols and the
{class}`~otwin.interfaces.TwinManifest` that records how a twin was built,
fitted, validated and calibrated.

## Four commitments

**The equations come from the description.** You connect a mass, a spring and
a damper; the compiler writes Newton's law in port-Hamiltonian form, with the
energy balance built into the structure. With no input, stored energy can only
decrease, and the default integrator preserves that step by step. See
[Compilation](concepts/compilation.md).

**Evaluation that cannot cheat.** {func}`~otwin.forecast.evaluate` never hands
the held-out targets to the model, a reference forecaster is compulsory rather
than optional, and {func}`~otwin.forecast.random_split` warns loudly because a
random split on a time series measures interpolation. See
[Leakage-free evaluation](concepts/leakage.md).

**Intervals whose coverage was measured.** A conformal band built from genuine
h-step-ahead residuals, not from the model's own in-sample errors. See
[Calibrated intervals](concepts/conformal.md).

**Coefficients that were determined, not chosen.** A fitted parameter the data
cannot pin down is a parameter chosen by the noise.
{func}`~otwin.estimate.identifiability` tests collinearity, record span and
bootstrap stability per coefficient; {func}`otwin.fit_parameters` runs it on
every fit; the manifest records the verdict; the envelope can refuse on it. See
[Identifiability](concepts/identifiability.md).

```{toctree}
:hidden:
:maxdepth: 2

install
quickstart
concepts/index
guides/index
developer/index
api/index
changelog
```
