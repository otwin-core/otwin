# Contributing

Practices follow [ColPrac](https://github.com/SciML/ColPrac).

## The three most useful contributions

1. **A reference case.** A physical system with a closed-form answer that no
   current case covers, for [`otwin-spec`](https://github.com/otwin-core/otwin-spec).
   It needs four things: the system and its parameters, an analytically known
   result, a stated rationale for what goes wrong without the check, and a
   **fault injection test** proving the check catches the fault it was written
   for. The last is not optional — a check without one is untested code
   protecting untested code.
2. **A Julia or MATLAB implementation.** See [MAINTAINERS.md](MAINTAINERS.md).
   Both slots are open and the definition of done is objective.
3. **A register map.** If you run a PCS or BMS whose Modbus map is not SunSpec,
   the map itself is useful even with no code attached.

## Dependency licence policy

This is a hard rule, not a preference, and it is the reason the connector layer
looks the way it does.

- **The base install carries NumPy and SciPy.** Nothing else.
- **Nothing under a copyleft licence is ever a hard requirement.** LGPL and MPL
  dependencies may be optional extras. GPL dependencies may not be vendored at
  all.
- **Three protocols are deliberately out of scope**, because in 2026 no
  permissively licensed Python path to them exists:

  | Protocol | Why not |
  |---|---|
  | IEC 61850 | `libiec61850` is GPL-3.0 or commercial; its SWIG bindings are explicitly unsupported by their own maintainers |
  | IEC 60870-5-104 | `c104` is GPL-3.0, and capped at Python < 3.13 |
  | DNP3 (IEEE 1815) | `opendnp3` was archived read-only in Sept 2022; its successor `stepfunc/dnp3` prohibits commercial and production use |

  Use an out-of-process gateway (61850 → OPC UA or MQTT) and read that with a
  supported connector. A pull request adding any of the three as a dependency
  will be declined however good the code is.

## Standards claims

Sort every claim into one of four buckets and keep it there:

- **Implemented and tested** — ISO 13374 architecture, SunSpec model
  conformance, IEC 63278-1 AAS submodel export.
- **Aligned to, stated as design intent with a mapping table** — ISO 13381-1,
  IEEE 1856-2017, IEC 61850-7-420 Ed. 2.0.
- **Vocabulary borrowed, stated as vocabulary** — ISA-95 / IEC 62264,
  ISO/IEC 9646, ISO 23247, ANSI/ISA-18.2.
- **Never claimed** — IEEE 1547 / 1547.1 compliance, ISA/IEC 62443
  certification, UL 1741 SB. **A library cannot be IEEE 1547 compliant; a DER
  device can.** 1547.1 Clause 6 is an interoperability test performed on
  hardware. Say what the code supports; never say what it is certified to.

One claim in the wrong bucket undoes the argument the type test exists to make.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

`[dev]` deliberately leaves out PyTorch — it is a ~2 GB download and only two
test modules need it. They skip cleanly without it, and `test_without_torch.py`
exists to keep that path green. If you are working on the learned models:

```bash
pip install -e ".[dev,nn]"
```

Doctests run as part of the suite, so every example in a docstring is executed.

New code needs the test that would fail without it. In particular:

- A new integrator needs an **energy-conservation** test, not only an accuracy
  test. That distinction is the point of the package.
- A new splitter needs a **leakage** test — a demonstration that no test index
  precedes a train index it should not.
- A new reference forecaster needs to be **genuinely hard to beat**. A straw man
  makes every model look good and is worse than nothing.
- A new connector needs a **simulator** so it can be tested in CI without
  hardware, and the simulator must drive the same decode path as the real
  source. A test that bypasses the decoder tests nothing.

## Git

Never commit to `main`. Every change opens a branch and a pull request.
