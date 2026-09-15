# otwin-engine

The Rust runtime behind [otwin](https://pypi.org/project/otwin/). It loads a
compiled physical model (the intermediate representation `otwin.compile`
produces) and integrates it: expression bytecode, analytic Jacobians, the
implicit midpoint rule, Runge-Kutta 4 and adaptive Dormand-Prince, and
parallel batches.

You do not import this package directly. Install it next to `otwin` and the
`otwin` runtime picks it up:

```bash
pip install otwin[engine]
```

Without it, `otwin` runs the same models on a NumPy reference backend.
