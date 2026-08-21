# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until version 1.0.0 the public API may change between minor versions. Pin an
exact version in anything you depend on.

## [Unreleased]

Seven changes, all found by rewriting a ten-notebook digital-twin study to run on the
library instead of on hand-rolled code. Every existing call path is unchanged: the new
arguments are optional and the new modules are additive.

### Added

- **Conformal prediction intervals** (`otwin.forecast.conformal`). `Interval.method`
  listed `"conformal"` as a legal value and nothing produced one, so the package could
  measure a band but not build one. Adds `conformal_quantile`, `split_conformal`,
  `horizon_conformal`, `AdaptiveConformal`, `ConformalBand` and
  `rolling_origin_residuals`. `conformal_quantile` returns an infinite half-width when
  the calibration set is too small for the requested level, rather than clipping the
  rank and returning the sample maximum — which is narrower than the guarantee requires
  and silent about it.
- **State-dependent ports.** `integrate_phs`, `implicit_midpoint` and
  `integrate_with_inputs` accept `u` as a callable `u(t, x)`, for a machine that holds a
  set point rather than following a schedule: a constant-power converter, a thermostat,
  a pump-turbine at rated power. The law is evaluated at the step midpoint inside the
  implicit solve, so the discrete power balance is preserved; the closed-form `"linear"`
  path is refused rather than silently applied to a system the feedback has made
  nonlinear. The realised port trajectory is returned as `result["u"]`.
- **The modulated irreversible form** (`otwin.model.ModulatedIPHS`, built by
  `IrreversiblePHS.from_modulated`). `ẋ = γ(x)·J∇H + gu` — the Ramírez–Maschke–Sbarbaro
  structure most of the irreversible-PHS literature is written in, and not a notational
  variant of the additive `L∇S` coupling already implemented. `σ ≥ 0` is checked on every
  dynamics call, since for this form it is a property of `γ` and not of the structure.
- **Heat exchanger in the catalogue.** `heat_exchanger()` as a two-node counter-flow
  `ModulatedIPHS`, `effectiveness_ntu()` for the steady-state ε-NTU duty, and
  `kern_seaton_fouling()` returning a `FoulingLaw` — an empirical law with no `rhs`,
  because fouling has no conserved energy and no port.
- **Exogenous drivers in `evaluate()`.** `exog=` is split by the protocol in force and
  passed as `exog_past` / `exog_future`, for a twin whose future depends on something the
  target does not determine. Every column is checked against the target at shifts up to
  five steps and an exact match is refused: a covariate carrying the answer defeats the
  leakage-free interface as completely as passing the test array did. `EvalReport.n_exog`
  records that drivers were used.
- **`TwinManifest.validated_by()` and `.calibrated_by()`.** Builders for the two dicts
  whose key names decide whether a twin is allowed to answer. `validated_by` derives
  `leakage_free` from the protocol and returns `False` for `random_split`;
  `calibrated_by` requires `empirical_coverage` and rejects a percentage where a fraction
  belongs.
- **`grad_H` and `grad_S` on `IrreversiblePHS`.** The constructor had no gradient slot, so
  `∇H` was always finite-differenced — on a stiff Hamiltonian the difference between an
  adiabatic energy drift of 1e-13 and one of 1e-6, which is the first-law check this class
  exists to make, quietly weakened.

### Fixed

- **A conformal rank was one too large at exactly the levels people use.**
  `0.9 * 10` is `9.000000000000002` in binary floating point, so `⌈level·(n+1)⌉`
  asked for rank 10 out of 10 calibration points and declared a set that is
  exactly large enough to be too small. The product is rounded to twelve decimals
  before the ceiling. On a rolling-origin calibration set this cost the sparsest
  horizons — the ones that set the extrapolated end of a horizon-aware band.
- **A validity refusal now names the key it read.** A manifest recording
  `protocol="rolling_origin"` and `picp=0.87` was refused with "this twin has never been
  validated under a leakage-free protocol" — true of the record, false of the work, and
  no help in finding the cause. `Envelope` now distinguishes an empty record from one
  that is present but does not assert `leakage_free=True` or carry
  `empirical_coverage`, and names the builder that sets it.

## [0.2.0] — 2026-08-13

First consolidated release. Thirteen separate packages were merged into one
distribution named `otwin`, and the result was audited before publication.

### Added

- **One package instead of thirteen.** `otwin` now contains the whole
  modelling, estimation and validation stack. The module layout follows the six
  data-processing blocks of ISO 13374: `otwin.io` (data acquisition),
  `otwin.signal` (data manipulation), `otwin.estimate` (state detection),
  `otwin.model` (health assessment), `otwin.forecast` (prognostic assessment)
  and `otwin.advise` (advisory generation).
- **Field connectors.** SunSpec Modbus (models 1, 701, 702, 704, 713, 802, 803,
  804, 805) and generic Modbus TCP/RTU, both read-only, both with a simulator
  that drives the identical decode path so the library can be developed and
  tested without hardware.
- **Validity envelopes** (`otwin.advise`). A forecast request outside the
  operating range the model was identified over, or beyond the horizon it was
  validated to, returns a refusal with a reason rather than a number.
- **Leakage-free forecast validation** (`otwin.forecast.protocol`). Held-out
  targets are not reachable from the model under evaluation; the split is
  out-of-sample and a reference forecaster is compulsory rather than optional.
- **Structure-preserving integration.** Implicit midpoint with an analytic
  Jacobian, `I - (dt/2)(J - R)grad^2 H`, factorised once and reused. Roughly
  140x faster than the previous `fsolve` path at n = 50, with the energy bound
  held to 1e-9.
- **Type information for downstream users.** The package ships a PEP 561
  `py.typed` marker, so a project that installs `otwin` and runs mypy gets its
  own call sites checked.
- **Supply-chain hardening.** Every GitHub Action pinned to a commit SHA;
  CodeQL with the extended query pack; OpenSSF Scorecard publishing results;
  Dependabot.

### Fixed

Four defects, each found by a test written against the behaviour rather than
against the implementation, and each now covered by a regression test verified
to fail on the previous code.

- **Forecast evaluation could see the held-out data.** `protocol.py` passed the
  test window to `model.predict()` at two separate call sites, so a reported
  skill score measured interpolation rather than forecasting. The test targets
  are no longer an argument to the function that asks the model for a
  prediction.
- **An unrecorded operating range admitted any operating point.**
  `advise/envelope.py` skipped the state check entirely when `state_bounds` was
  `None`, so a twin with no identified range returned a clean verdict for a
  state of charge of 1e12. An absent range is now a refusal, matching the rule
  the horizon check already followed.
- **Resampling ran past the last measurement.** `signal/condition.py` built its
  grid up to half a step beyond the final sample and `coverage()` reported the
  invented point as measured. The grid now stops at the last whole step.
- **A corrupt SunSpec scale factor destroyed the whole sample.**
  `io/sunspec.py` computed `10.0 ** exponent` unguarded and outside the
  per-model error handling, so one bad `sunssf` register raised `OverflowError`
  out of `read()` and lost every other model on the chain. The exponent is now
  range-checked against the SunSpec specification and the affected points
  degrade through the existing quality ladder.
- **State of charge was lost when one of two views went dark.**
  `SunSpecSource.soc()` chose between models 713 and 802 on publication order
  and then refused if that one read bad — even with the other answering
  cleanly. Candidates are now ranked by readability first, so the model
  preference breaks ties rather than overriding them.
- **The learned-model path named a package that does not exist.**
  `model/phnn.py` instructed users to `pip install otwin-learn[torch]`, left
  over from the pre-merge distributions. It now names the real extra,
  `otwin[nn]`, checked in CI against the metadata pip itself reads.

### Changed

- The source distribution no longer carries the README artwork. Every image is
  referenced by absolute URL, so the 2.1 MB of PNGs were downloaded by everyone
  installing from source and displayed to nobody. sdist 3.07 MB to 0.83 MB.
- `dev` extra no longer pulls PyTorch. Two test modules need it and both skip
  cleanly without it; use `pip install -e ".[dev,nn]"` to run them.

### Verification

489 tests, 92 % statement coverage, mypy clean across 39 modules, ruff clean.
`otwin.io.sunspec`, `otwin.io.source`, `otwin.io.loader`, `otwin.advise` and
`otwin.signal` are at 100 %. The distribution is additionally tested as
installed — built as a wheel and imported in a container that has never seen
this repository.

### Known limitations

- Python only. Julia and MATLAB implementations are open contributor positions.
- Connectors are read-only. Closed-loop actuation is deliberately out of scope.
- No production deployment on an operating asset is known to the maintainer.

[Unreleased]: https://github.com/otwin-core/otwin/compare/v0.2.0...HEAD
[0.2.0]: https://github.comit/otwin-core/otwin/releases/tag/v0.2.0
