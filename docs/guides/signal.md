# Condition — `otwin.signal`

Field data arrives at irregular times, out of order, with holes in it. Every
downstream block assumes a uniform grid. This block bridges the two — without
inventing measurements.

Five names, and they do one thing each.

## Put samples in order

```python
import numpy as np
from otwin.signal import sort_samples

t = np.array([0.0, 30.0, 10.0, 20.0])
v = np.array([1.0, 4.0, 2.0, 3.0])
t_sorted, v_sorted = sort_samples(t, v)
print(t_sorted, v_sorted)
```

```text
[ 0. 10. 20. 30.] [1. 2. 3. 4.]
```

Out-of-order timestamps are common where a logger buffers and flushes. Every
other function here assumes monotone time.

## Find the holes before you fill them

{func}`~otwin.signal.find_gaps` returns a {class}`~otwin.signal.Gap` per
interval longer than `max_gap`, each with `start`, `end`, `duration` and
`n_missing`. Look at them before resampling. A four-hour hole in a ten-second
signal is not a gap to interpolate across; it is an outage, and whatever you
forecast through it is fiction.

## Resample without inventing data

```python
from otwin.signal import coverage, resample

t = np.array([0.0, 10.0, 20.0, 90.0, 100.0])
v = np.array([1.0, 2.0, 3.0, 9.0, 10.0])

t_u, v_u, gaps = resample(t, v, dt=10.0, max_gap=30.0)
print(f"{t_u.size} grid points, {len(gaps)} gap(s)")
print(f"coverage {coverage(v_u):.3f}")
```

```text
11 grid points, 1 gap(s)
coverage 0.455
```

Two things are deliberate here.

**The grid stops at the last whole step.** It used to run half a step past the
final measurement, and {func}`~otwin.signal.coverage` reported the invented
point as measured.

**Coverage is the number to report.** A skill score computed over a window that
was 45 % real measurement and 55 % interpolation is a skill score against your
own interpolator. {func}`~otwin.signal.coverage` is the fraction of the
conditioned series that is a real measurement, and it belongs in the manifest
next to the metrics.

## Next

[Estimate](estimate.md) — recovering the states the grid does not contain.
