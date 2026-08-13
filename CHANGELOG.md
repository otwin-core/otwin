# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until version 1.0.0 the public API may change between minor versions. Pin an
exact version in anything you depend on.

## [Unreleased]

Nothing yet.

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
