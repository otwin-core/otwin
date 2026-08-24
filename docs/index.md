# otwin

**A digital twin you are allowed to trust — or that tells you why you are not.**

`otwin` builds twins of physical assets out of their energy structure, evaluates
their forecasts under protocols that cannot see the future, attaches intervals
whose coverage has been measured rather than assumed, and refuses to answer
questions outside the range it has been shown to work over.

That last part is the unusual one. Most forecasting libraries always return a
number. This one returns a refusal with a reason when the number would be
unjustified:

```text
horizon: beyond the validated forecast horizon (asked for 90, validated to 60)
```

```{code-block} bash
pip install otwin
```

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`rocket` Quickstart
:link: quickstart
:link-type: doc

Twenty lines: integrate a pumped-hydro store, forecast a capacity fade with a
calibrated band, and watch the twin decline a question it cannot support.
:::

:::{grid-item-card} {octicon}`book` Concepts
:link: concepts/index
:link-type: doc

The equations. Port-Hamiltonian form, entropy production, structure-preserving
integration, leakage-free evaluation, conformal bands.
:::

:::{grid-item-card} {octicon}`tools` Guides
:link: guides/index
:link-type: doc

One page per ISO 13374 block: acquire, condition, estimate, model, forecast,
advise.
:::

:::{grid-item-card} {octicon}`code` API reference
:link: api/index
:link-type: doc

Every public name, generated from the docstrings the test suite executes.
:::

::::

## The shape of the library

`otwin` is organised as the six data-processing blocks of **ISO 13374**, the
condition-monitoring standard. This is not decoration: it is why the package can
say where a number came from.

| Block | Module | What it does |
|---|---|---|
| Data Acquisition | {mod}`otwin.io` | Read a device or a dataset, with a quality flag on every value |
| Data Manipulation | {mod}`otwin.signal` | Put irregular samples on a grid without inventing data |
| State Detection | {mod}`otwin.estimate` | Recover the state you cannot measure |
| Health Assessment | {mod}`otwin.model` | What the asset *is*, written as an energy balance |
| Prognostic Assessment | {mod}`otwin.forecast` | What happens next, and how sure |
| Advisory Generation | {mod}`otwin.advise` | What to do — or why the twin will not say |

{mod}`otwin.interfaces` sits underneath all six: the protocols and the
{class}`~otwin.interfaces.TwinManifest` that records how a twin was fitted,
validated and calibrated.

## Four commitments

**Energy structure, not curve fitting.** A port-Hamiltonian model is passive by
construction. With no input, stored energy can only decrease. That property
holds outside the training data, which is exactly where a fitted curve stops
being trustworthy. See [Port-Hamiltonian systems](concepts/port-hamiltonian.md).

**Evaluation that cannot cheat.** {func}`~otwin.forecast.evaluate` never hands
the held-out targets to the model, a reference forecaster is compulsory rather
than optional, and {func}`~otwin.forecast.random_split` warns loudly because a
random split on a time series measures interpolation. See
[Leakage-free evaluation](concepts/leakage.md).

**Intervals whose coverage was measured.** A conformal band built from genuine
h-step-ahead residuals, not from the model's own in-sample errors — a shortcut
that on a lithium-ion capacity twin produced 1.5 % delivered coverage at a 90 %
target. See [Calibrated intervals](concepts/conformal.md).

**Coefficients that were determined, not chosen.** A fitted parameter the data
cannot pin down is a parameter chosen by the noise, and a forecast that
extrapolates through it is extrapolating the noise — while passing every
in-window check. {func}`~otwin.estimate.identifiability` tests collinearity,
record span and bootstrap stability per coefficient, the manifest records the
verdict, and the envelope can refuse on it. See
[Identifiability](concepts/identifiability.md).

```{toctree}
:hidden:
:maxdepth: 2

install
quickstart
concepts/index
guides/index
api/index
changelog
```
