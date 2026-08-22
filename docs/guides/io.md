# Acquire — `otwin.io`

Reading a device, or a dataset, in a way that lets you say afterwards where each
number came from.

:::{important}
Connectors are **read-only**. `otwin` can read a Modbus or SunSpec device and
cannot write to one. Closed-loop actuation is deliberately out of scope.
:::

## Quality is not optional

Every value carries a {class}`~otwin.io.Quality` flag. A sensor that returns a
plausible number after a failed read is more dangerous than one that returns
nothing, so `otwin` never silently substitutes. {class}`~otwin.io.QualityTracker`
turns per-tag read outcomes into values-plus-flags, and the flag travels with
the value through conditioning and into the forecast.

## SunSpec

{class}`~otwin.io.SunSpecSource` discovers a model chain and reads it. Models 1,
701, 702, 704, 713, 802, 803, 804 and 805 are supported.

```python
from otwin.io import SunSpecSimulator, SunSpecSource

# The simulator drives the identical decode path as a live device, so you can
# develop and test the whole pipeline without hardware.
source = SunSpecSource(transport=SunSpecSimulator())
sample = source.read()
print(sorted(sample.values)[:5])
```

```text
['m1.DA', 'm701.A', 'm701.ACType', 'm701.AL1', 'm701.AL2']
```

Two behaviours worth knowing:

**A corrupt scale factor degrades one point, not the sample.** `10.0 ** exponent`
on a bad `sunssf` register used to raise `OverflowError` out of `read()` and lose
every other model on the chain. The exponent is now range-checked against the
SunSpec specification and the affected points degrade through the quality ladder.

**State of charge is ranked by readability.** Models 713 and 802 both publish it.
The choice used to be made on publication order and then refused if that one read
badly — even with the other answering cleanly. Candidates are now ranked by
readability first, so the model preference breaks ties rather than overriding
them.

## Generic Modbus

{class}`~otwin.io.ModbusSource` reads a register map you describe, with
{class}`~otwin.io.ModbusSimulator` as its offline counterpart.
{func}`~otwin.io.load_register_map` reads that description from YAML or JSON, so
the map is data rather than code.

{func}`~otwin.io.decode_registers` and {func}`~otwin.io.encode_value` are the
raw pair underneath, exposed because register-level debugging is a normal part
of commissioning.

## Units

{func}`~otwin.io.to_si` converts to SI — W, Wh, A, C, V, K, Hz, s —
{func}`~otwin.io.si_unit` says which unit that will be, and
{func}`~otwin.io.normalise` does both in one call.

{class}`~otwin.io.UnknownUnitError` is deliberately an error rather than a
pass-through. A unit string nobody recognised is a modelling question, not a
formatting one, and passing it through unconverted is how a kilowatt becomes a
watt three blocks downstream.

## Datasets

{func}`~otwin.io.load` fetches a registered dataset as a DataFrame,
{func}`~otwin.io.describe` gives its licence and citation,
{func}`~otwin.io.verify` checks a local file against its registered checksum,
and {func}`~otwin.io.path_for` says where it would be cached whether or not it
is there.

## Next

[Condition](signal.md) — putting what you just read onto a uniform grid.
