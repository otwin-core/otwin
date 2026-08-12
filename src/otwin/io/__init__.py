"""Data Acquisition — ISO 13374 block DA.

ISO 13374-1 splits condition monitoring into six blocks. This package is the
first one: Data Acquisition. Its whole job is to turn whatever a field device
puts on a wire into timestamped, SI-normalised, quality-flagged numbers, and
then to stop. Nothing here filters, estimates, forecasts or advises — those
are blocks DM, SD, HA and AG, and they live in :mod:`otwin.signal`,
:mod:`otwin.estimate`, :mod:`otwin.forecast` and :mod:`otwin.advise`.

Two sources of numbers
----------------------

**Recorded data** — :mod:`otwin.io.loader` and :mod:`otwin.io.registry`. A
registry of public datasets stored as identity and checksum rather than bytes,
fetched on demand and verified before use.

**Live data** — exactly two protocols, on purpose:

* **Modbus TCP/RTU** (:class:`ModbusSource`, via the optional ``pymodbus``
  extra, BSD-3-Clause). The lowest common denominator: every PCS, BMS and
  meter speaks it.
* **SunSpec Modbus** (:class:`SunSpecSource`, via the optional ``pysunspec2``
  extra, Apache-2.0). Self-describing DER models, and one of the three
  interfaces IEEE 1547-2018 permits for distributed energy resources.

Both optional packages are genuinely optional. This package imports, and its
entire test suite runs, with neither installed — see :class:`ModbusSimulator`
and :class:`SunSpecSimulator`, which serve real register images in-process so
that the decoding, scale-factor and unit logic is exercised rather than
mocked. A missing package is reported only when a live connection is
attempted, with a message naming the package and the extra.

What is deliberately out of scope
---------------------------------

**IEC 61850, IEC 60870-5-104 and DNP3 are not implemented here, and will not
be.** The reason is licensing, not difficulty:

* *IEC 61850* — libiec61850, the only mature implementation, is GPL-3.0 or a
  paid commercial licence. Linking it into an Apache-2.0 library would
  relicense the library.
* *DNP3* — opendnp3 was archived by its maintainers in 2022 and receives no
  security fixes; its successor, stepfunc/dnp3, carries a licence that
  prohibits production use without a commercial agreement.
* *IEC 60870-5-104* — the same picture: the usable implementations are
  copyleft or commercial.

Sites that need those protocols run them in an **out-of-process gateway** — a
separately licensed component, in its own process, that terminates the
protocol and republishes to Modbus, a historian or a message bus, which this
package then reads. That keeps the licence boundary at a process boundary
where it is enforceable, and keeps a protocol stack that must be certified out
of a library that must not be.

OPC UA and MQTT are also absent, for a different reason: they are transports
rather than instrument protocols, and adding them here would make this package
a general-purpose integration layer instead of a data-acquisition block.
"""

from __future__ import annotations

from .loader import cache_dir, describe, load, path_for, verify
from .modbus import (
    DTYPE_REGISTERS,
    MODBUS_MAX_REGISTERS_PER_READ,
    ModbusSource,
    PymodbusTransport,
    RegisterSpec,
    decode_registers,
    encode_value,
    load_register_map,
)
from .registry import DATASETS, Dataset
from .simulator import ModbusSimulator, SimulatedFault, SunSpecSimulator
from .source import (
    KNOWN_UNITS,
    MissingDependencyError,
    Quality,
    QualityTracker,
    RegisterTransport,
    Sample,
    Source,
    TagSpec,
    TransportError,
    UnknownUnitError,
    normalise,
    si_unit,
    to_si,
)
from .sunspec import (
    MODEL_NAMES,
    SUNSPEC_BASE_ADDRESSES,
    SUPPORTED_MODELS,
    ModelDef,
    ModelInstance,
    PointDef,
    PySunSpec2Transport,
    SunSpecSource,
    compare_model_defs,
    load_model_def,
)

__all__ = [
    # recorded data (unchanged, re-exported so existing imports keep working)
    "DATASETS",
    "Dataset",
    "cache_dir",
    "describe",
    "load",
    "path_for",
    "verify",
    # the common contract
    "Sample",
    "TagSpec",
    "Source",
    "Quality",
    "QualityTracker",
    "RegisterTransport",
    "MissingDependencyError",
    "UnknownUnitError",
    "TransportError",
    "to_si",
    "si_unit",
    "normalise",
    "KNOWN_UNITS",
    # raw Modbus
    "ModbusSource",
    "RegisterSpec",
    "PymodbusTransport",
    "decode_registers",
    "encode_value",
    "load_register_map",
    "DTYPE_REGISTERS",
    "MODBUS_MAX_REGISTERS_PER_READ",
    # SunSpec
    "SunSpecSource",
    "PySunSpec2Transport",
    "ModelDef",
    "ModelInstance",
    "PointDef",
    "load_model_def",
    "compare_model_defs",
    "SUNSPEC_BASE_ADDRESSES",
    "SUPPORTED_MODELS",
    "MODEL_NAMES",
    # simulators
    "ModbusSimulator",
    "SunSpecSimulator",
    "SimulatedFault",
]
