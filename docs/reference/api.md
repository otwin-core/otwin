# API reference

Every entry is generated from the source. The docstrings you read here are the
ones `pytest --doctest-modules` executes on each commit, so an example that
does not run is a failing test, not a stale page; and every public name has
one, which CI checks.

The reference is ordered by what you are doing, not by file. Each task names
the functions and classes it needs and links to the module page that
documents them in full. If you are looking for a capability rather than a
name, [Modeling](../modeling/index.md) and [Digital twins](../digital-twins/index.md) go task by task with running code.

## Describe

Components, ports and connections: what exists and what touches what.

- {class}`~otwin.system.System` and {func}`~otwin.system.chain` (the `>>` operator): the component graph.
- {mod}`otwin.components`: the library, by domain: {mod}`~otwin.components.electrical`,
  {mod}`~otwin.components.mechanical`, {mod}`~otwin.components.rotational`,
  {mod}`~otwin.components.hydraulic`, {mod}`~otwin.components.thermal`,
  {mod}`~otwin.components.twoport`, {mod}`~otwin.components.composite`,
  {mod}`~otwin.components.battery`, and {mod}`~otwin.components.fundamental`
  for a domain the library does not name. The
  [Component reference](components.md) lists each one with its
  ports, parameters, states and outputs.
- {mod}`otwin.components.base`: {class}`~otwin.components.base.Component`,
  {class}`~otwin.components.base.Composite`, {class}`~otwin.components.base.Port`,
  {class}`~otwin.components.base.Parameter` and the branch types, for writing your own.
- {mod}`otwin.expr`: the symbolic expressions component laws are written in
  (`piecewise`, `interp`, `sqrt`, `where`, ...).

## Compile

- {func}`~otwin.api.compile`: system to model. Raises {class}`~otwin.compiler.CompileError`
  on a system that cannot be compiled and warns with {class}`~otwin.compiler.StructureWarning`
  on one that compiles but cannot be guaranteed passive.
- {mod}`otwin.ir`: what the compiler produces, {class}`~otwin.ir.PhysicalSystemIR`
  (nodes, branches, states) and {class}`~otwin.ir.PHSIR` (the port-Hamiltonian
  form `J`, `R`, `G`, `H`), both serialisable.
- {mod}`otwin.compiler`: the passes, for those working on the compiler itself.

## Simulate

- {class}`~otwin.runtime.model.Model`: `simulate`, `initial_state`, `step`, `outputs`,
  `with_parameters`, `energy`, `summary`, `structure`, `ir`, `save`/`load`.
- {class}`~otwin.runtime.model.State` and {class}`~otwin.runtime.model.Trajectory`: what `step` and
  `simulate` return, indexable by name.
- {mod}`otwin.runtime.backends`: the Rust engine and the NumPy fallback;
  {func}`~otwin.runtime.backends.engine_available` says which one you have.
- {class}`~otwin.runtime.custom.CustomDynamics` ({mod}`otwin.runtime.custom`): hand-written
  `f(x, u, t)` when a system is not made of components.
- {mod}`otwin.model`: the hand-written port-Hamiltonian models
  ({class}`~otwin.model.phs.PortHamiltonianSystem`, {mod}`~otwin.model.iphs`,
  {mod}`~otwin.model.phnn`), the reference {mod}`~otwin.model.library`, and
  the {mod}`~otwin.model.integrators`.

## Read the asset

- {mod}`otwin.io`: {class}`~otwin.io.source.Source`, {class}`~otwin.io.source.Sample`,
  {class}`~otwin.io.source.TagSpec`; the SunSpec and Modbus sources
  ({mod}`~otwin.io.sunspec`, {mod}`~otwin.io.modbus`) and their simulators
  ({mod}`~otwin.io.simulator`); {func}`~otwin.io.loader.load` and the dataset registry.
- {mod}`otwin.signal`: {func}`~otwin.signal.condition.resample`, {func}`~otwin.signal.condition.find_gaps`,
  {func}`~otwin.signal.condition.coverage`: irregular samples onto a grid, with the gaps named.

## Fit what the physics leaves out

- {func}`~otwin.hybrid.fit_parameters` ({mod}`otwin.hybrid`): calibrate named
  parameters from measurements; returns a {class}`~otwin.hybrid.FitResult`
  with the identifiability verdict.
- {class}`~otwin.hybrid.HybridModel`: compiled physics plus a residual
  (symbolic, learned, or any callable); {func}`~otwin.hybrid.residual_data`
  builds the training set.
- {func}`~otwin.estimate.identifiability` and
  {class}`~otwin.estimate.IdentifiabilityReport`: can the data determine
  these coefficients at all.

## Estimate

- {class}`~otwin.estimate.linear.KalmanFilter`, {class}`~otwin.estimate.kalman.ExtendedKalmanFilter`
  and {class}`~otwin.estimate.kalman.FilterResult`.
- {class}`~otwin.estimate.mhe.MovingHorizonEstimator`: estimation as an
  optimisation over a window, with bounds.
- {class}`~otwin.estimate.energy.EnergyConsistentObserver` and
  {class}`~otwin.estimate.energy.EnergyFilterResult`: a filter that cannot create
  energy the physics does not allow.

## Forecast

- {func}`~otwin.forecast.protocol.evaluate` and {class}`~otwin.forecast.report.EvalReport`: the
  one entry point for out-of-sample evaluation.
- Protocols: {func}`~otwin.forecast.splitters.temporal_holdout`,
  {func}`~otwin.forecast.splitters.rolling_origin`, {func}`~otwin.forecast.splitters.random_split`
  (which warns, because a random split on a time series measures interpolation).
- Baselines, compulsory in every evaluation: {func}`~otwin.forecast.baselines.persistence`,
  {func}`~otwin.forecast.baselines.drift`, {func}`~otwin.forecast.baselines.mean_forecast`,
  {func}`~otwin.forecast.baselines.seasonal_naive`, {func}`~otwin.forecast.baselines.get_best_baseline`.
- Metrics: {func}`~otwin.forecast.metrics.rmse`, {func}`~otwin.forecast.metrics.mae`,
  {func}`~otwin.forecast.metrics.nrmse`, {func}`~otwin.forecast.metrics.mase`,
  {func}`~otwin.forecast.metrics.theil_u`, {func}`~otwin.forecast.metrics.skill_score`,
  {func}`~otwin.forecast.metrics.crps`, {func}`~otwin.forecast.metrics.picp`,
  {func}`~otwin.forecast.metrics.mpiw`, {func}`~otwin.forecast.calibration.interval_score`.
- Uncertainty: {func}`~otwin.forecast.conformal.split_conformal`,
  {func}`~otwin.forecast.conformal.horizon_conformal`, {class}`~otwin.forecast.conformal.ConformalBand`,
  {class}`~otwin.forecast.conformal.AdaptiveConformal`,
  {func}`~otwin.forecast.conformal.rolling_origin_residuals`; {class}`~otwin.forecast.ensemble.Ensemble`;
  calibration diagnostics {func}`~otwin.forecast.calibration.pit_values`,
  {func}`~otwin.forecast.calibration.coverage_curve`, {func}`~otwin.forecast.calibration.expected_calibration_error`,
  {func}`~otwin.forecast.calibration.recalibrate`, {func}`~otwin.forecast.calibration.sharpness`.
- {class}`~otwin.forecast.gp_phs.GPPHS` ({mod}`otwin.forecast.gp_phs`, needs `otwin[gp]`):
  a Gaussian process residual on the port-Hamiltonian structure.

## Validate and advise

- {class}`~otwin.advise.envelope.Envelope`, {class}`~otwin.advise.envelope.Verdict`,
  {class}`~otwin.advise.envelope.Breach`, {class}`~otwin.advise.envelope.OutsideEnvelope`: the
  validity envelope and the refusal it returns with a reason.
- {class}`~otwin.interfaces.manifest.TwinManifest` and {class}`~otwin.interfaces.manifest.Provenance`
  ({mod}`otwin.interfaces.manifest`): how a twin was built, fitted, validated
  and calibrated.
- {mod}`otwin.interfaces`: the protocols every model, estimator, baseline and
  splitter implements ({class}`~otwin.interfaces.protocols.TwinModel`, {class}`~otwin.interfaces.protocols.Estimator`,
  {class}`~otwin.interfaces.protocols.Baseline`, {class}`~otwin.interfaces.protocols.Splitter`, {class}`~otwin.interfaces.protocols.EvaluationProtocol`,
  {class}`~otwin.interfaces.protocols.UncertaintyModel`) and the result types
  ({class}`~otwin.interfaces.results.Forecast`, {class}`~otwin.interfaces.results.Interval`, {class}`~otwin.interfaces.results.MetricSet`,
  {class}`~otwin.interfaces.results.Report`).

## Every module

The complete, generated listing, one page per module.

```{eval-rst}
.. autosummary::
   :toctree: generated
   :recursive:

   otwin
   otwin.components
   otwin.system
   otwin.compiler
   otwin.ir
   otwin.expr
   otwin.runtime
   otwin.hybrid
   otwin.io
   otwin.signal
   otwin.estimate
   otwin.model
   otwin.forecast
   otwin.advise
   otwin.interfaces
```

## Identifiability report

Two classes are documented here rather than on a module page, because the function
{func}`~otwin.estimate.identifiability` shares its name with the module that
defines them.

```{eval-rst}
.. currentmodule:: otwin.estimate

.. autoclass:: IdentifiabilityReport
   :members:

.. autoclass:: ParameterVerdict
   :members:
```
