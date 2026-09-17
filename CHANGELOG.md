# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

From 2.0.0 the public API changes only with a major version. Pin an exact
version in anything you depend on.

## [Unreleased]

### Added

- `docs/reference/components.md`: every component with its constructor,
  ports, parameters (unit, value, validity rule, meaning), states, inputs and
  outputs, generated from the components by `docs/generate_components.py`
  and checked in CI.
- A docstring on every public name (checked in CI with `interrogate`), and
  a one-line meaning on every component parameter.

### Changed

- The documentation overview (`docs/index.md`) is a continuous introduction
  to what Otwin is, what it is not, the elements of a model, the compiler,
  the model, the twin layer and the three worked systems, aligned with the
  README.
- The API reference is ordered by task (describe, compile, simulate, read
  the asset, fit, estimate, forecast, validate) ahead of the per-module
  listing.

## [2.0.1] — 2026-09-17

### Changed

- The README diagrams are SVG images rendered from Mermaid sources in
  `assets/diagrams/` (`python assets/render_diagrams.py`), so they show on
  PyPI and anywhere else the README is read. CI checks that every image is
  up to date with its source.
- PyPI keywords and the short description now describe what Otwin is for
  (a physics engine for engineering systems, its domains and uses) rather
  than its internals.

## [2.0.0] — 2026-09-17

An engineer describes a physical system with components and connections and
compiles it. The compiler writes the equations. `f(x, u)` is generated, `H`,
`J`, `R` and `G` are an intermediate representation, and the question the
release answers is whether a system can be built without writing any of them.
The two examples in `examples/` are the answer: a battery module and a pump
station, both real maintenance problems, neither with an equation in it.

Version 1.0.0 was merged but never released; its content is in this entry.
Nothing from 0.4 is removed.

### Added in 2.0

- **`Component`, `Port`, `Connection`, `PhysicalSystem`** as the engineer's
  three abstractions, defined in words at the top of `otwin.components.base`
  and `otwin.system`. A port knows its domain and its two variables; a
  `Connection` refuses mixed domains at construction and says what to use
  instead; `otwin.System` (an alias of `PhysicalSystem`) is inspectable before
  compiling: `components`, `connections`, `ports`, `parameters`, `domains`,
  `unconnected()`, `summary()`.
- **The fundamental components** `Storage`, `Dissipator`, `Source`,
  `Reference` in `otwin.components.fundamental`: the roles every library
  component plays, written once with the domain as an argument. They compile
  to the same model as their domain-specific conveniences.
- **`Battery(capacity, ocv, resistance, rc_branches, thermal)`** — an
  equivalent-circuit cell or pack: the open-circuit voltage curve as the
  energy of the charge store (its gradient *is* the table), a series
  resistance, one RC pair per polarisation branch, and, with `thermal`, a
  thermal mass warmed by the ohmic losses and a `thermal` port. Outputs `soc`,
  `voltage`, `current`, `temperature`, `heat_flow`.
- **`Pump(curve)` or `Pump(shutoff, max_flow)`**, **`Filter(resistance,
  fouling)`** in `otwin.components.hydraulic`, and **`Losses(*components)`** in
  `otwin.components.thermal`: the dissipated power of any components delivered
  as heat into a thermal port, with nothing written about the power.
- **`a >> b >> c` with one-port components** anywhere in the chain (a tank, a
  ground, an atmosphere joins the node between its neighbours), so
  `tank >> pipe >> pump >> filter >> Atmosphere()` compiles and steps.
- **`otwin.compile(system, dt=...)`** and **`model.step(state)`** without a
  time step: the step API of the instructions, `state = model.initial_state();
  state = model.step(state, inputs)`.
- **Flow-first laws.** `ResistorBranch(inverse=...)` gives the across variable
  as a function of the flow (a pump curve, `dp = K Q |Q|`). When a series
  element fixes the flow — an inertance, inductor, spring, flow source, or
  another such element — the compiler reads the across off it instead of
  inverting the law; otherwise it says which series element is missing.
  `Pipe` and `Orifice` carry both forms.
- **Tabulated curves in the engine.** `expr.piecewise`, `expr.interp` and
  `expr.interp_integral` (a measured curve, and the exact integral of one to
  use as a storage energy) lower to a `pw` instruction in the Rust engine and
  to the NumPy backend with identical results.
- **Two examples as maintenance problems**, run as tests and checked by hand:
  `examples/battery_that_runs_hot.py` (aged cells or clogged cooling, told
  apart with the module's own two sensors) and
  `examples/pump_station_that_asks_for_more.py` (a year of filter fouling, the
  drive turned up to hold the flow, the month at which cleaning pays).

### Fixed

- CodeQL quality findings: NaN checks use `math.isnan`; `Expr` defines
  `<=`/`>=` alongside `<`/`>`; the chord-Newton retry is an explicit
  `retried` flag instead of an unused loop variable;
  `ExtendedKalmanFilter.__init__` calls its own `reset`, not a subclass's;
  torch-backed names leave `otwin.model.__all__` (still reachable as
  attributes and in `dir()`, so `import *` never needs torch); two tests
  lose an `if False` toggle.

### Added (the engine, formerly 1.0.0)

- **Component library.** `otwin.components` with electrical (`Resistor`,
  `Capacitor`, `Inductor`, `VoltageSource`, `CurrentSource`, `Ground`),
  mechanical (`Mass`, `Spring`, `Damper`, `ForceSource`, `VelocitySource`,
  `Fixed`), rotational (`Inertia`, `TorsionSpring`, `RotationalDamper`,
  `TorqueSource`, `SpeedSource`, `Housing`), hydraulic (`Tank`, `Orifice`,
  `Pipe`, `FluidInertance`, `FlowSource`, `PressureSource`, `Atmosphere`),
  thermal (`ThermalMass`, `ThermalResistance`, `Convection`, `HeatSource`,
  `Ambient`) primitives, the two-ports `Transformer` and `Gyrator`, the
  composite `DCMotor`, and a `catalogue` that rebuilds every reference system
  of `otwin.model.library` from components. Resistive elements take a
  nonlinear `law=`.
- **`otwin.System`** — the component graph. `connect` joins ports into a
  node and checks domains; `a >> b >> c` chains two-port parts.
- **`otwin.compile`** — the model compiler. Nodal analysis with symbolic
  elimination produces a `PHSIR` whose entries are expressions: `J` exactly
  skew, `R` read off the dissipative laws, `G` and `D` for the ports, the
  right-hand side and its analytic Jacobian. Errors name ports and
  components: incompatible domains, dangling ports, dependent storages,
  nonlinear algebraic loops, singular networks.
- **`otwin.Model`** — the compiled model: `simulate`, `step`, `simulate_batch`,
  `rhs`, `jacobian`, `energy`, `outputs`, `observe`, `power_balance`,
  `check_structure`, `structure`, `summary`, `set_parameters`,
  `with_parameters`, `closed_loop`, `save`/`load`. It satisfies `TwinModel`,
  so `otwin.estimate` and `otwin.forecast` take it directly.
- **Compiled control laws.** `model.symbol("tank.level")` and
  `model.closed_loop(inlet=...)` (or `simulate(inputs={"inlet": expr})`) fold a
  feedback law into the model so the engine evaluates it at every solver
  stage. Python callables `f(t, x)` are still accepted and run sample-and-hold.
- **`otwin.expr`** — the symbolic expression type behind all of the above:
  differentiation, simplification, JSON serialisation, lowering to the engine.
- **The Rust engine.** `otwin-core` (expression bytecode, compiled model,
  integrators: implicit midpoint, RK4, adaptive Dormand-Prince, Euler, and
  parallel batches) and `otwin-engine` (PyO3 bindings, published as its own
  wheel). `pip install otwin[engine]` installs it; without it the same models
  run on a NumPy reference backend with identical results.
- **`otwin.CustomDynamics`** — the advanced escape hatch: a user-written
  `f(x, u, t)` with the `Model` surface, and `CustomDynamics.from_phs(...)` to
  wrap a hand-written `PortHamiltonianSystem`.
- **Tests.** `tests/engine`: expressions, compiler, golden models against
  closed forms, regression against the 0.4 hand-written models to 1e-8,
  Rust/NumPy parity on every solver, property tests on random passive
  networks. `cargo test` on the core crate.
- **Supply chain.** Two workflows, *Python* and *Rust*, each with its own
  badge; every engine wheel carries signed build provenance like the Python
  distribution (SLSA level 2); the tree is REUSE-compliant (`REUSE.toml`,
  `LICENSES/`, `reuse lint` in CI).

### Changed

- The README, the documentation and notebooks 01 and 05 describe systems with
  components; the mathematics moves to *Compilation* and *Advanced API*.
- `TwinManifest.model_class` accepts `"compiled"`.

### Unchanged, on purpose

- Every name in `otwin.model`, `otwin.estimate`, `otwin.forecast`,
  `otwin.advise`, `otwin.io`, `otwin.signal` and `otwin.interfaces`. The
  hand-written port-Hamiltonian API is the advanced layer, not a deprecated one.

## [0.4.0] — 2026-08-24

One new capability, and a fourth ground for refusal. Additive: every existing
call path and every manifest written by 0.3.x is unchanged; the new envelope
check is off unless asked for.

### Added

- **Identifiability — the fourth ground for refusal.** `otwin.estimate.identifiability(X, y, ...)`
  reports, per fitted coefficient, whether the data determined it: collinearity of
  the design columns (the early-life two-term law), record span against a fitted
  time constant (the Kern–Seaton trap, previously a docstring warning only), and
  stability under a bootstrap over *units* rather than rows (the field-data case
  of three tests per system). `TwinManifest.identified_by(...)` records the
  verdicts and `TwinManifest.is_identified` reads them as strictly as
  `is_validated`. `Envelope(requires_identified=True)` refuses a forecast that
  leans on an undetermined coefficient and names it. Default off, so existing
  manifests are unaffected; set it for anything that extrapolates. Motivation:
  in the replication series every result — a free exponent on 100 cycles, a
  second mechanism fitted to three points per system — was decided by
  identifiability, and the library had no way to say so.
- **Documentation.** A concept page, *Identifiability*, with the definition,
  the three failure modes, the executed example and the three cases from the
  replication series; the envelope rule now has five clauses; the front page
  has four commitments; the README gains a step between validating the forecast
  and recording the envelope.

## [0.3.1] — 2026-08-22

Documentation. No change to the library's behaviour, and no change to its public
API: `pip install otwin==0.3.1` runs the same code as `0.3.0`.

### Added

- **A manual.** Sphinx + MyST at <https://otwin.readthedocs.io/>: install,
  a quickstart that goes from an energy balance to a calibrated band to a
  refusal, seven concept pages carrying the equations, one guide per ISO 13374
  block, and a reference section generated from the docstrings the test suite
  already executes. `[project.urls] Documentation` now points there rather than
  at a README anchor, which is the only reason this release exists — a docs site
  is built from the repository, but the link on PyPI comes from the package
  metadata.
- **The documentation examples are tested.** `tests/test_docs_examples.py` runs
  every ```python block in the manual in document order, one namespace per page,
  and compares what it prints against the output the page claims. Prose that
  stays plausible while its code stops running is the normal way documentation
  fails, and nothing else catches it.
- **A `docs` job in CI**, building with `-W`, so a broken cross-reference fails a
  pull request rather than rendering as ordinary text nobody notices.

### Fixed

- Four docstring defects, each invisible to pytest, ruff and mypy and each found
  by building the manual: a section underline one character short in
  `estimate/energy.py`; ASCII structure diagrams in `model/library.py` indented
  under plain text, which reStructuredText reads as definition lists; a bare
  `|...|` pair in the Jacobian expression in `model/integrators.py`, read as a
  substitution reference; and a field in `forecast/conformal.py` annotated
  `npt.NDArray[np.bool_]`, whose trailing underscore is a hyperlink reference to
  a target that does not exist once autodoc renders it. That one is now a named
  `BoolArray`, which the source reads better for.
- The `0.2.0` link at the foot of this file pointed at `github.comit`.

## [0.3.0] — 2026-08-21

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

[Unreleased]: https://github.com/otwin-core/otwin/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/otwin-core/otwin/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/otwin-core/otwin/compare/v0.4.0...v2.0.0
[0.4.0]: https://github.com/otwin-core/otwin/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/otwin-core/otwin/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/otwin-core/otwin/releases/tag/v0.3.0
[0.2.0]: https://github.com/otwin-core/otwin/releases/tag/v0.2.0
