<div align="center">

# A twin that can say no

**Digital twins whose physics is checked, not claimed.**

[![CI](https://img.shields.io/github/actions/workflow/status/otwin-core/otwin/ci.yml?style=flat-square&label=CI)](https://github.com/otwin-core/otwin/actions)
[![Type test](https://img.shields.io/badge/type%20test-conformant-0d7a52?style=flat-square)](https://github.com/otwin-core/otwin-spec)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-brightgreen?style=flat-square)](https://opensource.org/license/apache-2-0)

</div>

---

Every model gives you a number. That is the problem.

Ask a fitted model what a battery bank will do 900 cycles out, in an operating
range it never saw, and it answers. Confidently. With no indication that the
question was outside anything it was ever shown to handle. The expensive
mistake in industry is not imprecision — it is **confidence**.

An Otwin twin is built so it can refuse.

```python
from otwin.advise import Envelope

envelope = Envelope.from_manifest(twin)
verdict = envelope.check(state=[0.42], horizon=900, manifest=twin)

print(verdict.explain())
```

```
outside the validated envelope:
  - horizon: beyond the validated forecast horizon (asked for 900, validated to 500)
  - calibration: interval coverage has never been measured, so the band has no
    demonstrated meaning

This is a refusal, not a failure. The twin has not been shown to answer this
question, and returning a number anyway would hide that.
```

Three things make that refusal possible, and each of them is checked rather
than asserted.

---

## 1. The physics cannot be violated, by algebra

A twin here is an **energy-based model** — a bond graph written in state-space
form. If you have drawn an effort–flow diagram, you already know this:

$$\dot{x} = \bigl(J(x) - R(x)\bigr)\nabla H(x) + g(x)u, \qquad y = g(x)^\top \nabla H(x)$$

| Term | What it is | What you already call it |
|---|---|---|
| $H(x)$ | stored energy | the C and I elements — springs, inertias, tank level, state of charge |
| $\nabla H(x)$ | effort variables | voltage, force, pressure, temperature |
| $J(x)$ | routes power between stores, consuming none | the junction structure — gyrators, transformers |
| $R(x)$ | removes power, can never add it | the R elements — friction, damping, ohmic loss |
| $g(x)$ | where power crosses the boundary | the terminals |

Because $J$ is power-conserving and $R$ is dissipative, the power balance

$$\frac{dH}{dt} = -\nabla H^\top R\,\nabla H + y^\top u \;\leq\; y^\top u$$

holds **by construction rather than by fitting**. With the terminals open,
stored energy cannot increase. Not approximately. Not for well-chosen
parameters. Not only inside the range you fitted. At any step size, over any
horizon.

That is the energy balance you already draw by hand on a whiteboard, running
continuously inside the model. It catches sign-convention errors, sensor drift,
and the specific failure where a fitted model looks excellent on held-out data
and then invents energy at a horizon nobody tested.

**And it survives composition.** Interconnect two energy-based models through
their ports and the result is another one, with the same guarantee. So a bank
model is built out of string models — cell → module → string → bank → PCS →
point of interconnection — and nothing needs refitting at any level. Nothing
else in this space offers that.

## 2. The claim is checked by something that can fail

A model declaring this structure is making a falsifiable claim. That claim is
invisible on a test set: a model with a subtly wrong $J$ scores beautifully on
held-out data and then drifts exactly where the structure was supposed to
protect you.

So it gets a **type test** — [`otwin-spec`](https://github.com/otwin-core/otwin-spec),
in the sense IEC and IEEE use the term: a one-time design verification against
reference cases with closed-form answers.

```bash
pip install otwin-spec
otwin-conformance python
```

The suite ships **deliberately broken implementations** and asserts each is
caught by the check meant to catch it — including one adapter that contains no
model, no integrator and no physics at all, which scored 8/8 bright green until
the runner stopped sending it the answer key.

## 3. Nothing is validated until someone measured it

```python
from otwin.forecast import evaluate

report = evaluate(model, data, protocol="rolling_origin")
```

The model is handed its history and an integer horizon. **It is never handed
the test targets** — there is no argument through which the answer could reach
it. Out-of-sample partitions are the default, a reference forecaster is
mandatory, and the headline number is skill, because the only question that
matters is whether this beats the obvious thing. R² will read 0.99 on a model
that loses to repeating yesterday's value.

`Interval.is_validated` is `False` until coverage has actually been measured on
held-out data. **Not yet checked is not the same as fine.**

---

## Install

```bash
pip install otwin                  # modelling, estimation, validation
pip install "otwin[field]"         # + SunSpec Modbus and Modbus TCP/RTU
```

Base install is NumPy and SciPy. Nothing heavier, and nothing under a copyleft
licence, is ever a hard requirement.

## The shape of it

The package follows the **ISO 13374** processing blocks, so the layout is the
one a condition-monitoring engineer already has in their head:

| Block | Module | What it does |
|---|---|---|
| **DA** — Data Acquisition | `otwin.io` | SunSpec Modbus (models 701/702/704/713, 802–805), Modbus TCP/RTU |
| **DM** — Data Manipulation | `otwin.signal` | resampling that will not interpolate across an outage, gaps, out-of-order samples, units |
| **SD** — State Detection | `otwin.estimate` | EKF, moving-horizon estimation with real state bounds, and an energy-consistent observer |
| **HA** — Health Assessment | `otwin.model` | the energy-based model itself |
| **PA** — Prognostic Assessment | `otwin.forecast` | forecasts, skill against a reference, calibrated bands |
| **AG** — Advisory Generation | `otwin.advise` | the validity envelope, and the refusal |

### The estimator will not cheat either

A standard Kalman correction can *increase* the stored energy of a passive
model with zero input. The filter quietly injects power through the back door
and the guarantee that justified the whole approach is gone. `otwin.estimate`
ships an observer that cannot do that — it scales any correction back to fit
inside the measured energy balance, and records when it had to.

A clamp that fires constantly means your process and measurement covariances
are wrong, and it tells you that too.

## Where this has been presented

**IEEE PES General Meeting 2026** — invited to the panel *AI-powered Digital
Twins for Grid-Scale Energy Storage* by Sel Ly of **Sandia National
Laboratories**. Paper 26PESGM2792, *Physics-Informed Digital Twin for
Grid-Scale Storage: Calibrated Forecasts for Predictive Maintenance and
Real-Time Optimization*.

That is an invited talk, not a deployment. **There is no production installation
of this library and no named user yet** — if you are running one, an issue
saying so is the single most useful thing anyone could contribute right now.

## Where it started

A [2021 Towards Data Science post](https://towardsdatascience.com/how-to-build-a-digital-twin-b31058fd5d3e/)
about building a digital twin of a lithium-ion battery. That worked example is
still here, rebuilt and honest about its own results, in
[`otwin-hybrid`](https://github.com/otwin-core/otwin-hybrid) — including the
part where a straight line beats the physics on RMSE.

## Contributing

The three things that would help most, in order:

1. **A reference case.** A physical system with a closed-form answer that no
   current case covers. Thermal, electrical, chemical, mechanical. Goes in
   [`otwin-spec`](https://github.com/otwin-core/otwin-spec) and needs a fault
   injection test proving the check works — a check without one is untested
   code protecting untested code.
2. **A Julia or MATLAB implementation.** The type test judges implementations
   over a subprocess boundary, so it can grade a language this repository knows
   nothing about. A minimal native core plus an adapter — roughly a thousand
   lines — is a complete contribution, and it comes with a maintainer slot.
   **Both slots are open.**
3. **A register map.** If you have a PCS or BMS whose Modbus map is not
   SunSpec, the map itself is useful even without code.

There is one maintainer. Governance is deliberately absent — a steering council
of one person is theatre. See [MAINTAINERS.md](MAINTAINERS.md).

## Citing

See [CITATION.cff](CITATION.cff). The structure follows van der Schaft &
Jeltsema (2014), *Port-Hamiltonian Systems Theory*. Irreversible systems follow
Ramírez, Maschke & Sbarbaro (2013).

## License

Apache 2.0.
