# Estimate — `otwin.estimate`

The state you want is rarely the quantity you measure. You measure terminal
voltage and want state of charge; you measure two temperatures and want the
internal energy split. This block recovers it.

## Which estimator

| Class | Model | Use when |
|---|---|---|
| {class}`~otwin.estimate.KalmanFilter` | linear, $x_{k+1} = Ax_k + Bu_k + w$ | the dynamics genuinely are linear |
| {class}`~otwin.estimate.ExtendedKalmanFilter` | any twin exposing `dynamics` | the standard nonlinear choice |
| {class}`~otwin.estimate.EnergyConsistentObserver` | a port-Hamiltonian twin | you care that the estimate stays physical |
| {class}`~otwin.estimate.MovingHorizonEstimator` | any, with constraints | states have hard bounds, or outliers are a problem |

All four take the same core arguments — the model, process noise `Q`,
measurement noise `R_meas`, initial covariance `P0` — and return a
{class}`~otwin.estimate.FilterResult` from a full pass.

## The energy-consistent observer

This is the one specific to what `otwin` is for.

An EKF correction step is a least-squares update. Nothing in it knows about your
energy function, so on a passive model it will cheerfully push the state to a
point of *higher* stored energy than physics allows — and once it has, every
guarantee argued for in [Port-Hamiltonian systems](../concepts/port-hamiltonian.md)
is gone, silently, in the middle of a run.

{class}`~otwin.estimate.EnergyConsistentObserver` rejects a measurement
correction that would manufacture energy. It returns an
{class}`~otwin.estimate.EnergyFilterResult` — a `FilterResult` plus the energy
audit, so you can see how often the constraint bound and by how much.

A constraint that binds constantly is telling you something: either `R_meas` is
too optimistic about your sensor, or the model is wrong. Read the audit rather
than turning the check off.

## Moving-horizon estimation

{class}`~otwin.estimate.MovingHorizonEstimator` solves a constrained problem
over a sliding window instead of a single recursive update. Costlier per step,
and worth it for two reasons: hard bounds on states (a state of charge is in
$[0, 1]$, not merely usually) and robustness to outliers, since a single bad
measurement is outvoted by the rest of the window rather than dragging the
estimate with it.

## Next

[Model](model.md) — the structure all of these estimate the state of.
