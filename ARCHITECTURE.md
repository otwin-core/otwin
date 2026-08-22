#  Source layout

`src`-layout, so the installed package is what the tests import — a flat layout lets
`import otwin` resolve against the working directory and hides a missing entry in the
wheel until someone else installs it.

```
otwin/
├── pyproject.toml            PEP 517/518 build config + PEP 621 metadata
├── README.md                 long_description (readme = "README.md")
├── CHANGELOG.md
├── LICENSE  NOTICE  SECURITY.md  CODE_OF_CONDUCT.md  CONTRIBUTING.md  MAINTAINERS.md
├── conftest.py               pytest root config
│
├── src/
│   └── otwin/
│       ├── __init__.py       re-exports the interfaces layer; defines __version__
│       ├── py.typed          PEP 561 marker — this package ships inline types
│       │
│       ├── interfaces/       the contract. Types and protocols only, no algorithms
│       │   ├── protocols.py      TwinModel, PortHamiltonianModel, IrreversibleModel,
│       │   │                     EmpiricalLawModel, Estimator, Baseline, Splitter, ...
│       │   ├── results.py        Forecast, Interval, MetricSet, Report
│       │   └── manifest.py       TwinManifest, Provenance
│       │
│       ├── io/               DA — acquisition and units
│       │   ├── source.py         Source, Sample, Quality, QualityTracker
│       │   ├── sunspec.py        SunSpecSource, SunSpecSimulator, PySunSpec2Transport
│       │   ├── modbus.py         ModbusSource, ModbusSimulator, PymodbusTransport
│       │   ├── registry.py       register maps, unit normalisation, to_si
│       │   └── loader.py         bundled datasets: DATASETS, load, describe, verify
│       │
│       ├── signal/           DM — conditioning
│       │   └── condition.py      resample, find_gaps, coverage, sort_samples, Gap
│       │
│       ├── model/            HA — the physics
│       │   ├── phs.py            PortHamiltonianSystem
│       │   ├── iphs.py           IrreversiblePHS, ModulatedIPHS
│       │   ├── integrators.py    integrate, integrate_phs, integrate_with_inputs
│       │   ├── solvers.py        implicit_midpoint, newton_step
│       │   ├── linalg.py         check_psd, check_skew_symmetric, numerical_gradient
│       │   ├── library.py        water_tank, dc_motor, pumped_hydro, heat_exchanger,
│       │   │                     mass_spring_damper, FoulingLaw, kern_seaton_fouling
│       │   ├── phnn.py           PortHamiltonianNN                  [extra: nn]
│       │   └── losses.py         derivative_loss, passivity_penalty [extra: nn]
│       │
│       ├── estimate/         SD — state correction
│       │   ├── linear.py         KalmanFilter, FilterResult
│       │   ├── kalman.py         ExtendedKalmanFilter
│       │   ├── mhe.py            MovingHorizonEstimator
│       │   └── energy.py         EnergyConsistentObserver, EnergyFilterResult
│       │
│       ├── forecast/         PA — prediction and its evidence
│       │   ├── protocol.py       evaluate — the single entry point
│       │   ├── splitters.py      temporal_holdout, rolling_origin, random_split
│       │   ├── baselines.py      persistence, drift, mean_forecast, seasonal_naive,
│       │   │                     get_best_baseline
│       │   ├── metrics.py        rmse, mae, nrmse, mase, theil_u, skill_score, picp,
│       │   │                     mpiw, interval_score, sharpness
│       │   ├── conformal.py      split_conformal, horizon_conformal, AdaptiveConformal,
│       │   │                     conformal_quantile, rolling_origin_residuals,
│       │   │                     ConformalBand
│       │   ├── calibration.py    crps, pit_values, coverage_curve, recalibrate,
│       │   │                     expected_calibration_error
│       │   ├── ensemble.py       Ensemble
│       │   ├── gp_phs.py         GPPHS                              [extra: gp]
│       │   └── report.py         EvalReport
│       │
│       └── advise/           AG — the validated envelope
│           └── envelope.py       Envelope, Verdict, Breach, OutsideEnvelope
│
├── tests/                    pytest, 636 tests
├── examples/                 bess_end_to_end.py — the full chain, no hardware
├── benchmarks/               integrator and forecasting benchmarks + recorded results
├── fuzz/                     ClusterFuzzLite targets: decode_point, manifest, sunspec
└── assets/                   images referenced by the README
```

The two-letter codes are the ISO 13374 data-processing blocks — DA, DM, SD, HA, PA, AG.
The package layout follows them so that a reader who knows the reference architecture
already knows where to look.


# Dependency graph

```
otwin                     numpy>=1.24, scipy>=1.10          <- the whole core
│
├── otwin[modbus]         + pymodbus>=3.6,<4.0
├── otwin[sunspec]        + pysunspec2>=1.1, pymodbus>=3.6,<4.0
├── otwin[field]          = modbus + sunspec                 <- real equipment
├── otwin[nn]             + torch>=2.0                       <- learned models
├── otwin[gp]             + scikit-learn>=1.3                <- GP residuals
├── otwin[all]            = modbus + sunspec + nn + gp
└── otwin[dev]            = modbus + sunspec + gp
                          + pytest, pytest-cov, hypothesis, ruff, mypy
```

`dev` deliberately excludes `torch`: it is roughly a 2 GB download, only two test modules
need it, both skip cleanly without it, and `tests/test_without_torch.py` exists to keep
the torch-free path green. Use `.[dev,nn]` for the learned-model tests.

Optional imports are deferred, not top-level, so `import otwin.model` succeeds without
PyTorch installed and raises a named, actionable `ImportError` only when the feature is
touched. `otwin.model` and `otwin.forecast` implement this with a module-level
`__getattr__` (**PEP 562**), which is what lets `from otwin.forecast import GPPHS` fail
with an install instruction rather than a `ModuleNotFoundError` from inside scikit-learn.

> **Undeclared soft dependency.** `otwin.io.load()` imports `pandas` lazily and raises
> `ImportError: reading a dataset needs pandas, which otwin does not require.` pandas
> appears in no dependency list and in no extra, so it is the one optional feature with
> no `otwin[...]` to install. Either give it an extra (`otwin[data]`) or leave it
> deliberate — but it is a fourth optional path, not a third.
