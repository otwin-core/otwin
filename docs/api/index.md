# API reference

Every entry below is generated from the source. The docstrings you are reading
are the same ones `pytest --doctest-modules` executes on each commit, so an
example here that does not run is a failing test, not a stale page.

The engine layer first (describe, compile, run), then the six data-processing
blocks of ISO 13374. If you are looking for a capability rather than a name,
start from [the guides](../guides/index.md).

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
