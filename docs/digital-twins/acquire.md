# Acquire — `otwin.io`

Reading a device, or a dataset, in a way that lets you say afterwards where each
number came from.

:::{important}
Connectors are **read-only**. `otwin` can read a Modbus, SunSpec or OPC UA
device and cannot write to one. Closed-loop actuation is deliberately out of
scope.
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

## OPC UA

{class}`~otwin.io.OpcUaSource` reads a stated list of OPC UA nodes as named
channels. It produces the same {class}`~otwin.io.Sample` objects as the Modbus
sources, so {mod}`otwin.signal` and {mod}`otwin.estimate` take them unchanged.
It needs `pip install "otwin[opcua]"`, which installs asyncua
(LGPL-3.0-or-later). The configuration objects work without it.

```{code-block} python
from otwin.io import OpcUaChannel, OpcUaSecurity, OpcUaSource, samples_to_arrays

security = OpcUaSecurity(
    certificate="pki/own/certs/otwin.der",     # create_self_signed_certificate() makes one
    private_key="pki/own/private/otwin.pem",
    trust="pki/trusted",                       # the server's certificate, or its CA and CRL
    username="operator", password=password,    # optional
)
channels = [
    OpcUaChannel("p_out", "nsu=urn:plant;s=Pump.Power", "kW"),
    OpcUaChannel("fill", "nsu=urn:plant;s=Tank.Fill", "percent"),
]
with OpcUaSource("opc.tcp://plc.example:4840/", channels, security=security) as src:
    print(src.browse())                        # find the nodes to map
    samples = [src.read() for _ in range(60)]  # or mode="subscribe", then src.drain()
    record = src.acquisition()                 # for TwinManifest(acquisition=...)
t, Y, names = samples_to_arrays(samples)       # what otwin.signal takes
```

**It never writes.**
- There is no write or method-call entry point.
- A configuration that asks to write (`access: read_write`, `writable`,
  `setpoints`, `commands`, ...) raises {class}`~otwin.io.ReadOnlyViolation`
  before connecting.
- Every request passes an allow-list of read-only OPC UA services, so a Write
  or a Call cannot leave the process, even from code that reaches into the
  underlying client.

**It is secured by default**, following OPC UA Parts 2, 4, 6 and 7:
- **Policy and mode.** `Basic256Sha256` with `SignAndEncrypt` is the default;
  the two `Aes` policies are also accepted. The deprecated `Basic128Rsa15` and
  `Basic256` are refused. Policy `None` needs {meth}`~otwin.io.OpcUaSecurity.insecure`,
  and then it warns and is recorded as such.
- **Server certificate.** It is validated before any credential is sent:
  trust list or CA chain, validity, ApplicationUri, host name, key usage,
  RSA key size, SHA-256 or stronger, and revocation through the CA's CRL. It is
  then pinned for the session.
- **Passwords.** A password is never sent readable.
- **Nothing secret is recorded.** Credentials are refused in endpoint URLs and
  in configuration files (name an environment variable instead), and the
  manifest never contains them.

**Units are checked against the server.** If a node has an EngineeringUnits
property (Part 8) that contradicts the channel's unit, the connection is
refused. A kW tag read as W is off by a factor of 1000 and still looks
plausible.

**It refuses nodes it cannot map.** A node that is not a readable numeric
scalar is refused at connection time. It is not read as NaN for ever.

## Units

{func}`~otwin.io.to_si` converts to SI — W, Wh, A, C, V, K, Hz, s —
{func}`~otwin.io.si_unit` says which unit that will be, and
{func}`~otwin.io.normalise` does both in one call.

{class}`~otwin.io.UnknownUnitError` is deliberately an error rather than a
pass-through. A unit string nobody recognised is a modelling question, not a
formatting one, and passing it through unconverted is how a kilowatt becomes a
watt three blocks downstream.

## Datasets

{func}`~otwin.io.load` reads a registered dataset as a DataFrame, and says where to download it when it is not there yet,
{func}`~otwin.io.describe` gives its licence and citation,
{func}`~otwin.io.verify` checks a local file against its registered checksum,
and {func}`~otwin.io.path_for` says where it would be cached whether or not it
is there.

## Next

[Condition](condition.md) — putting what you just read onto a uniform grid.
