"""OPC UA, read-only, and secured unless the caller explicitly opts out.

:class:`OpcUaSource` reads a stated list of OPC UA nodes as named measurement
channels. It produces the same :class:`~otwin.io.source.Sample` objects as
:class:`~otwin.io.ModbusSource`: host-clock timestamps, SI values and a
quality flag per channel. :mod:`otwin.signal` and :mod:`otwin.estimate` take
them without knowing which protocol they came from. It can poll (:meth:`read`)
or subscribe (:meth:`subscribe`, then :meth:`drain`). It can also browse a
server's address space to find the nodes to map.

It needs the optional extra ``otwin[opcua]`` (asyncua, LGPL-3.0-or-later). The
configuration objects in this module, :class:`OpcUaChannel`,
:class:`OpcUaSecurity` and :func:`load_opcua_config`, work without it, so a
configuration can be checked on a machine that will never connect.

It never writes
---------------

A twin that reads a plant must not be able to change it. This is enforced in
three places:

* **The API.** There is no write, call or method-invocation entry point.
* **The configuration.** A channel with ``access`` other than ``"read"``, or
  a configuration with any write-like key (``write``, ``writable``,
  ``allow_write``, ``setpoint``, ``commands``, ...), raises
  :class:`ReadOnlyViolation` before any connection is made.
* **The wire.** Every request the client sends passes an allow-list of
  read-only services (:data:`READ_ONLY_SERVICES`, OPC UA Part 4):
  session management, Read, Browse, TranslateBrowsePaths and the
  subscription services. Write, Call, AddNodes, DeleteNodes, AddReferences,
  DeleteReferences, HistoryUpdate, RegisterServer and every other service are
  refused before they leave the process. This holds even for code that
  reaches into the underlying asyncua client.

How the connection is secured (OPC UA Parts 2, 4, 6 and 7)
----------------------------------------------------------

* **Security policy.** The default is ``Basic256Sha256`` with
  ``SignAndEncrypt``. ``Aes128_Sha256_RsaOaep`` and ``Aes256_Sha256_RsaPss``
  are also accepted. ``Basic128Rsa15`` and ``Basic256`` are refused: Part 7
  deprecates them because they rely on SHA-1. ``None`` is refused unless
  :meth:`OpcUaSecurity.insecure` is used, and even then it warns, records
  ``None`` in the manifest and never sends a password.
* **The server certificate is validated before anything is sent to the
  server beyond endpoint discovery.** The checks follow Part 4 §6.1.3: the
  certificate is in the trust list or chains to a CA that is, it is inside its
  validity period, its ApplicationUri matches the server's, the endpoint host
  name is in its subjectAltName, its key usage allows signing and key
  encipherment, its RSA key is 2048 to 4096 bits, and it is signed with SHA-256
  or stronger. For a certificate a CA issued, a current CRL from that CA must
  show it is not revoked. The validated certificate is then pinned for the
  session, and asyncua refuses a different one in CreateSession.
  asyncua's own path, which takes the certificate from an unsecured
  GetEndpoints response and trusts it, is never used.
* **The client's ApplicationUri** is read from its own certificate's
  subjectAltName, so the two always match, as Part 4 §5.6.2 requires.
* **Passwords are never sent in clear.** The server's UserName token policy
  decides how a password is protected (Part 4 §7.41). It is encrypted with
  the token's own policy, or the channel's policy when the token names none.
  If the token policy is None, the password travels inside the channel
  unencrypted, so the connection is refused unless the channel is
  SignAndEncrypt. asyncua would only log a warning and send it.
* **No credentials in URLs or manifests.** An endpoint with ``user:pass@`` is
  rejected. :meth:`OpcUaSource.acquisition` records the token type, the
  policy and the server certificate's SHA-256 thumbprint, never a username or
  password. A configuration file may name an environment variable for the
  password, but may not contain one.

:func:`create_self_signed_certificate` writes a client (or test server)
certificate with the extensions Part 6 requires. The server's administrator
still has to place it in the server's trust list.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import importlib
import ipaddress
import itertools
import json
import math
import os
import re
import threading
import time
import warnings
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .source import (
    MissingDependencyError,
    QualityTracker,
    Sample,
    TagSpec,
    si_unit,
    to_si,
)

__all__ = [
    "OpcUaSource",
    "OpcUaChannel",
    "OpcUaSecurity",
    "BrowseEntry",
    "ReadOnlyViolation",
    "OpcUaSecurityError",
    "OpcUaConfigurationError",
    "InsecureConnectionWarning",
    "load_opcua_config",
    "validate_server_certificate",
    "create_self_signed_certificate",
    "parse_node_id",
    "READ_ONLY_SERVICES",
    "SECURITY_POLICIES",
]

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ReadOnlyViolation(PermissionError):
    """Something asked this client to write, call or modify. It never does."""


class OpcUaConfigurationError(ValueError):
    """A configuration this client cannot honour: an unknown option, a node that
    does not exist or is not a readable numeric scalar, or a unit that
    contradicts the server's EngineeringUnits."""


class OpcUaSecurityError(ConnectionError):
    """The connection could not be secured as configured.

    Attributes:
        status: The OPC UA status code name that describes the failure, such as
            ``"BadCertificateUntrusted"`` (Part 4, Table 106), where one
            applies.
    """

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(f"{status}: {message}" if status else message)
        self.status = status


class InsecureConnectionWarning(UserWarning):
    """A connection was opened with security policy None."""


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

_POLICY_BASE = "http://opcfoundation.org/UA/SecurityPolicy#"

#: Security policies this client accepts, by name, with their URIs (Part 7).
SECURITY_POLICIES: dict[str, str] = {
    "None": _POLICY_BASE + "None",
    "Basic256Sha256": _POLICY_BASE + "Basic256Sha256",
    "Aes128_Sha256_RsaOaep": _POLICY_BASE + "Aes128_Sha256_RsaOaep",
    "Aes256_Sha256_RsaPss": _POLICY_BASE + "Aes256_Sha256_RsaPss",
}

_ASYNCUA_POLICY_CLASS = {
    "Basic256Sha256": "SecurityPolicyBasic256Sha256",
    "Aes128_Sha256_RsaOaep": "SecurityPolicyAes128Sha256RsaOaep",
    "Aes256_Sha256_RsaPss": "SecurityPolicyAes256Sha256RsaPss",
}

#: Deprecated by OPC UA Part 7 (1.04): both depend on SHA-1.
_DEPRECATED_POLICIES = ("Basic128Rsa15", "Basic256")

_MODES = ("None", "Sign", "SignAndEncrypt")

#: The only OPC UA services this client will send (Part 4): discovery, session
#: management, reading and browsing, and the subscription services. Anything
#: else is refused before it reaches the wire.
READ_ONLY_SERVICES: frozenset[str] = frozenset(
    {
        "GetEndpointsRequest",
        "FindServersRequest",
        "CreateSessionRequest",
        "ActivateSessionRequest",
        "CloseSessionRequest",
        "ReadRequest",
        "BrowseRequest",
        "BrowseNextRequest",
        "TranslateBrowsePathsToNodeIdsRequest",
        "CreateSubscriptionRequest",
        "ModifySubscriptionRequest",
        "SetPublishingModeRequest",
        "DeleteSubscriptionsRequest",
        "CreateMonitoredItemsRequest",
        "ModifyMonitoredItemsRequest",
        "SetMonitoringModeRequest",
        "DeleteMonitoredItemsRequest",
        "PublishRequest",
        "RepublishRequest",
    }
)

#: Keys that ask for writing. Any of them, at any level of a configuration,
#: is a ReadOnlyViolation, whatever its value.
_WRITE_KEYS = frozenset(
    {
        "write",
        "writes",
        "writable",
        "writeable",
        "allow_write",
        "allow_writes",
        "write_enabled",
        "enable_write",
        "read_write",
        "setpoint",
        "setpoints",
        "command",
        "commands",
        "outputs",
        "method",
        "methods",
        "call",
    }
)

#: Built-in numeric DataTypes (Part 6, §5.1.2): Boolean .. Double, plus
#: Duration (a Double). A Sample carries floats, so nothing else is mapped.
_NUMERIC_DATATYPES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 290}

#: AccessLevel bit 0, CurrentRead (Part 3, §8.57).
_CURRENT_READ = 0x01

#: Part 8 §5.6.3: EngineeringUnits use UNECE Recommendation 20 common codes.
_UNECE_NAMESPACE = "http://www.opcfoundation.org/UA/units/un/cefact"
_UNECE = {
    "WTT": "W",
    "KWT": "kW",
    "MAW": "MW",
    "KVA": "kVA",
    "MVA": "MVA",
    "KVR": "kvar",
    "WHR": "Wh",
    "KWH": "kWh",
    "MWH": "MWh",
    "GWH": "GWh",
    "JOU": "J",
    "KJO": "kJ",
    "AMP": "A",
    "4K": "mA",
    "AMH": "Ah",
    "VLT": "V",
    "2Z": "mV",
    "KVT": "kV",
    "CEL": "degC",
    "KEL": "K",
    "HTZ": "Hz",
    "KHZ": "kHz",
    "SEC": "s",
    "C26": "ms",
    "MIN": "min",
    "HUR": "h",
    "OHM": "ohm",
    "SIE": "S",
    "P1": "percent",
    "C62": "1",
}


def _same_unit(a: str, b: str) -> bool:
    """Whether two unit strings name the same unit: same SI unit, same scale and offset."""
    return si_unit(a) == si_unit(b) and all(
        to_si(x, a) == to_si(x, b) for x in (0.0, 1.0)
    )


#: Built-in DataType names (Part 6 §5.1.2), for TagSpec.dtype.
_DATATYPE_NAMES = {
    1: "Boolean",
    2: "SByte",
    3: "Byte",
    4: "Int16",
    5: "UInt16",
    6: "Int32",
    7: "UInt32",
    8: "Int64",
    9: "UInt64",
    10: "Float",
    11: "Double",
    290: "Duration",
}


def _unece_code(unit_id: int) -> str:
    """The common code a Part 8 UnitId encodes: up to four ASCII bytes, high first."""
    out = []
    while unit_id:
        out.append(chr(unit_id & 0xFF))
        unit_id >>= 8
    return "".join(reversed(out))


def _unece_unit_id(code: str) -> int:
    """The Part 8 UnitId of a UNECE common code (the inverse of :func:`_unece_code`)."""
    uid = 0
    for c in code:
        uid = (uid << 8) | ord(c)
    return uid


# --------------------------------------------------------------------------
# Node ids
# --------------------------------------------------------------------------

_NODE_ID = re.compile(
    r"^(?:(?:ns=(?P<ns>\d+)|nsu=(?P<nsu>[^;]+));)?(?P<kind>[isgb])=(?P<id>.+)$", re.S
)


def parse_node_id(text: str) -> tuple[int | None, str | None, str, str]:
    """Split an OPC UA node id string (Part 6, §5.3.1.10).

    Accepts ``ns=<index>;<type>=<id>``, ``nsu=<namespace uri>;<type>=<id>`` and
    a bare ``<type>=<id>`` (namespace 0), where ``<type>`` is ``i`` (numeric),
    ``s`` (string), ``g`` (GUID) or ``b`` (opaque, base64). Prefer ``nsu=``:
    the namespace index of a URI can change when the server restarts, but the
    URI does not.

    Returns:
        ``(namespace_index, namespace_uri, type, identifier)``. Exactly one of
        the first two is set, or both are ``None`` for namespace 0.

    Raises:
        OpcUaConfigurationError: If the string is not a node id.

    Example:
        >>> parse_node_id("nsu=urn:plant;s=Tank.Level")
        (None, 'urn:plant', 's', 'Tank.Level')
        >>> parse_node_id("ns=2;i=1001")
        (2, None, 'i', '1001')
    """
    m = _NODE_ID.match(text.strip()) if isinstance(text, str) else None
    if m is None:
        raise OpcUaConfigurationError(
            f"{text!r} is not an OPC UA node id. Expected forms such as "
            "'ns=2;s=Tank.Level', 'nsu=urn:plant;i=1001' or 'i=2258' (Part 6, §5.3.1.10)."
        )
    if m["kind"] == "i" and not m["id"].isdigit():
        raise OpcUaConfigurationError(
            f"{text!r}: a numeric node id needs digits after 'i='"
        )
    ns = None if m["ns"] is None else int(m["ns"])
    return ns, m["nsu"], m["kind"], m["id"]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OpcUaChannel:
    """One OPC UA node, read as one named measurement channel.

    Attributes:
        name: The tag name in :attr:`Sample.values`.
        node_id: The node to read, e.g. ``"nsu=urn:plant;s=Tank.Level"``.
        unit: The unit the server delivers the value in. Values are converted
            to SI, as for every otwin source. If the node has an
            EngineeringUnits property that names a different unit, the
            connection is refused.
        description: What the number means.
        access: Must be ``"read"``. Anything else raises
            :class:`ReadOnlyViolation`. The field exists so that a
            configuration asking for write access fails loudly.
    """

    name: str
    node_id: str
    unit: str
    description: str = ""
    access: str = "read"

    def __post_init__(self) -> None:
        if self.access != "read":
            raise ReadOnlyViolation(
                f"channel {self.name!r} asks for access={self.access!r}. otwin's OPC UA "
                "client is read-only: it has no write path and refuses any "
                "configuration that asks for one."
            )
        if not isinstance(self.name, str) or not self.name:
            raise OpcUaConfigurationError("a channel needs a non-empty name")
        parse_node_id(self.node_id)
        si_unit(self.unit)  # raises UnknownUnitError for a unit otwin does not know


@dataclass(frozen=True, repr=False)
class OpcUaSecurity:
    """How the connection is secured.

    Attributes:
        certificate: The client's application instance certificate (DER or
            PEM). Its subjectAltName URI is used as the client's
            ApplicationUri.
        private_key: The matching private key (PEM).
        trust: The trust list: a certificate file, or a directory of them.
            This is where the server certificate, or the CA that issued it,
            must be. A directory in the Part 12 layout, with ``certs/`` and
            ``crl/`` subdirectories, is understood.
        crl: Certificate revocation lists, as a file or a directory. A
            ``crl/`` subdirectory of ``trust`` is read as well.
        policy: ``"Basic256Sha256"`` (default), ``"Aes128_Sha256_RsaOaep"`` or
            ``"Aes256_Sha256_RsaPss"``.
        mode: ``"SignAndEncrypt"`` (the default for a secured policy) or
            ``"Sign"``. With policy ``"None"`` it is ``"None"``.
        username, password: A UserName identity token. Leave both unset for
            an anonymous session. The password is never sent readable: if
            the server's token policy would not encrypt it and the channel
            only signs, the connection is refused.
        private_key_password: Passphrase of ``private_key``, if it has one.
        check_hostname: Require the endpoint host in the server certificate's
            subjectAltName (Part 4 §6.1.3). On by default.
        require_crl: For a CA-issued server certificate, require a current
            CRL from the CA. On by default: without one, revocation cannot be
            checked (``BadCertificateRevocationUnknown``).

    Use :meth:`insecure` for security policy None, and then only on a network
    you control.
    """

    certificate: str | Path | None = None
    private_key: str | Path | None = None
    trust: str | Path | None = None
    crl: str | Path | None = None
    policy: str = "Basic256Sha256"
    mode: str | None = None
    username: str | None = None
    password: str | None = field(default=None)
    private_key_password: str | None = field(default=None)
    check_hostname: bool = True
    require_crl: bool = True
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if self.policy in _DEPRECATED_POLICIES:
            raise OpcUaSecurityError(
                f"security policy {self.policy} is deprecated by OPC UA Part 7 because it "
                "relies on SHA-1, and this client does not offer it. Use Basic256Sha256, "
                "Aes128_Sha256_RsaOaep or Aes256_Sha256_RsaPss.",
                "BadSecurityPolicyRejected",
            )
        if self.policy not in SECURITY_POLICIES:
            raise OpcUaConfigurationError(
                f"unknown security policy {self.policy!r}; choose from {sorted(SECURITY_POLICIES)}"
            )
        if self.mode is None:
            object.__setattr__(
                self, "mode", "None" if self.policy == "None" else "SignAndEncrypt"
            )
        if self.mode not in _MODES:
            raise OpcUaConfigurationError(
                f"unknown security mode {self.mode!r}; choose from {_MODES}"
            )
        if (self.policy == "None") != (self.mode == "None"):
            raise OpcUaConfigurationError(
                "security policy None and security mode None go together: a secured "
                f"policy needs Sign or SignAndEncrypt (got policy={self.policy}, mode={self.mode})"
            )
        if self.policy == "None":
            if not self.allow_insecure:
                raise OpcUaSecurityError(
                    "security policy None sends everything in clear and lets anyone on the "
                    "network impersonate the server. Configure a certificate and a trust "
                    "list, or call OpcUaSecurity.insecure() to accept that on a network "
                    "you control.",
                    "BadSecurityPolicyRejected",
                )
            if self.username is not None or self.password is not None:
                raise OpcUaSecurityError(
                    "refusing to send a username and password over security policy None",
                    "BadSecurityModeInsufficient",
                )
            return
        missing = [
            k for k in ("certificate", "private_key", "trust") if getattr(self, k) is None
        ]
        if missing:
            raise OpcUaConfigurationError(
                f"security policy {self.policy} needs {', '.join(missing)}. The trust list "
                "is not optional: without it, any server could claim to be this one. "
                "create_self_signed_certificate() makes a client certificate."
            )
        if (self.username is None) != (self.password is None):
            raise OpcUaConfigurationError("give both username and password, or neither")

    @classmethod
    def insecure(cls) -> OpcUaSecurity:
        """Security policy None: no signing, no encryption, no server authentication.

        Only for a network you control. Opening such a connection raises
        :class:`InsecureConnectionWarning`, the manifest records policy None,
        and no password is ever sent.
        """
        return cls(policy="None", mode="None", allow_insecure=True)

    @property
    def secure(self) -> bool:
        """``True`` unless this is security policy None."""
        return self.policy != "None"

    def __repr__(self) -> str:
        shown = {
            "policy": self.policy,
            "mode": self.mode,
            "certificate": self.certificate,
            "trust": self.trust,
            "username": self.username,
            "password": None if self.password is None else "***",
        }
        return "OpcUaSecurity(" + ", ".join(f"{k}={v!r}" for k, v in shown.items()) + ")"


def _check_endpoint(endpoint: str) -> tuple[str, str, int]:
    """Validate an ``opc.tcp://`` endpoint and return ``(endpoint, host, port)``."""
    parts = urlsplit(endpoint)
    if parts.scheme != "opc.tcp":
        raise OpcUaConfigurationError(
            f"endpoint {endpoint!r}: only the opc.tcp transport (UA TCP, Part 6 §7.2) is "
            "supported"
        )
    if "@" in parts.netloc:
        raise OpcUaConfigurationError(
            "the endpoint URL carries credentials. Put the username and password in "
            "OpcUaSecurity, so they are neither logged nor written into a manifest."
        )
    if not parts.hostname:
        raise OpcUaConfigurationError(f"endpoint {endpoint!r} has no host")
    return endpoint, parts.hostname, parts.port or 4840


def _reject_write_keys(doc: Any, where: str = "configuration") -> None:
    """Raise ReadOnlyViolation if any key at any depth asks for writing."""
    if isinstance(doc, Mapping):
        for k, v in doc.items():
            key = str(k).lower()
            if key in _WRITE_KEYS:
                raise ReadOnlyViolation(
                    f"{where} contains {k!r}. otwin's OPC UA client is read-only and "
                    "refuses any configuration that asks it to write, call a method or "
                    "drive an output."
                )
            if key == "access" and v != "read":
                raise ReadOnlyViolation(
                    f"{where} asks for access={v!r}; only 'read' is possible"
                )
            _reject_write_keys(v, f"{where}.{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            _reject_write_keys(v, f"{where}[{i}]")


_SOURCE_OPTIONS = {
    "endpoint",
    "mode",
    "sampling_interval",
    "publishing_interval",
    "timeout",
    "max_stale_seconds",
    "normalise_units",
    "check_units",
    "name",
}
_SECURITY_OPTIONS = {
    "policy",
    "mode",
    "certificate",
    "private_key",
    "trust",
    "crl",
    "username",
    "password_env",
    "private_key_password_env",
    "check_hostname",
    "require_crl",
    "allow_insecure",
}
_CHANNEL_OPTIONS = {"name", "node_id", "unit", "description", "access"}


def load_opcua_config(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Read an OPC UA configuration from a YAML or JSON file, or a mapping.

    The format::

        endpoint: opc.tcp://plc.example:4840/
        mode: poll                       # or subscribe
        sampling_interval: 1.0           # seconds
        security:
          policy: Basic256Sha256
          mode: SignAndEncrypt
          certificate: pki/own/certs/otwin.der
          private_key: pki/own/private/otwin.pem
          trust: pki/trusted               # certs/ and crl/ inside are read
          username: operator
          password_env: OTWIN_OPCUA_PASSWORD   # never the password itself
        channels:
          - {name: p_out, node_id: "nsu=urn:plant;s=Pump.Power", unit: kW}

    Relative paths are resolved against the file's directory.

    Returns:
        Keyword arguments for :class:`OpcUaSource`: ``endpoint``,
        ``channels`` (a list of :class:`OpcUaChannel`), ``security`` (an
        :class:`OpcUaSecurity`) and any other options given.

    Raises:
        ReadOnlyViolation: If anything in it asks for writing.
        OpcUaConfigurationError: On an unknown key, a password written into
            the file, a missing environment variable, or a malformed channel.
        OpcUaSecurityError: If the security section is insecure or deprecated.
    """
    base = Path(".")
    if isinstance(source, Mapping):
        doc: Any = dict(source)
    else:
        p = Path(source)
        base = p.parent
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                yaml = importlib.import_module("yaml")
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise ImportError(
                    "reading a YAML configuration requires PyYAML: pip install pyyaml. "
                    "A JSON configuration needs no extra dependency."
                ) from exc
            doc = yaml.safe_load(text)
        else:
            doc = json.loads(text)
    if not isinstance(doc, Mapping):
        raise OpcUaConfigurationError(
            "an OPC UA configuration is a mapping at the top level"
        )

    _reject_write_keys(doc)

    unknown = set(doc) - _SOURCE_OPTIONS - {"security", "channels"}
    if unknown:
        raise OpcUaConfigurationError(f"unknown option(s) {sorted(unknown)}")
    if "endpoint" not in doc or "channels" not in doc:
        raise OpcUaConfigurationError("a configuration needs 'endpoint' and 'channels'")

    sec = dict(doc.get("security") or {})
    if "password" in sec or "private_key_password" in sec:
        raise OpcUaConfigurationError(
            "a configuration file must not contain a password. Name an environment "
            "variable with password_env (or private_key_password_env) instead."
        )
    bad = set(sec) - _SECURITY_OPTIONS
    if bad:
        raise OpcUaConfigurationError(f"unknown security option(s) {sorted(bad)}")

    def secret(env_key: str) -> str | None:
        name = sec.pop(env_key, None)
        if name is None:
            return None
        if name not in os.environ:
            raise OpcUaConfigurationError(
                f"environment variable {name!r} ({env_key}) is not set"
            )
        return os.environ[name]

    password = secret("password_env")
    key_password = secret("private_key_password_env")
    for k in ("certificate", "private_key", "trust", "crl"):
        if sec.get(k) is not None:
            sec[k] = str(
                (base / sec[k]) if not Path(sec[k]).is_absolute() else Path(sec[k])
            )
    security = OpcUaSecurity(**sec, password=password, private_key_password=key_password)

    if not isinstance(doc["channels"], list):
        raise OpcUaConfigurationError("'channels' must be a list")
    channels = []
    for i, entry in enumerate(doc["channels"]):
        if not isinstance(entry, Mapping):
            raise OpcUaConfigurationError(f"channel {i} is not a mapping")
        extra = set(entry) - _CHANNEL_OPTIONS
        if extra:
            raise OpcUaConfigurationError(f"channel {i}: unknown key(s) {sorted(extra)}")
        channels.append(OpcUaChannel(**entry))

    options = {k: v for k, v in doc.items() if k not in ("security", "channels")}
    return {**options, "channels": channels, "security": security}


# --------------------------------------------------------------------------
# Certificates (Part 4 §6.1.3, Part 6 §6.2)
# --------------------------------------------------------------------------


def _x509() -> Any:
    """``cryptography.x509``, which arrives with asyncua."""
    try:
        return importlib.import_module("cryptography.x509")
    except ImportError as exc:
        raise _missing_asyncua() from exc


def _split_der_chain(data: bytes) -> list[bytes]:
    """Split concatenated DER certificates, as a ServerCertificate field may hold a chain."""
    out, i = [], 0
    while i < len(data):
        if data[i] != 0x30 or i + 2 > len(data):
            raise OpcUaSecurityError(
                "the server certificate is not DER", "BadCertificateInvalid"
            )
        n = data[i + 1]
        if n < 0x80:
            length, header = n, 2
        else:
            k = n & 0x7F
            length, header = int.from_bytes(data[i + 2 : i + 2 + k], "big"), 2 + k
        out.append(data[i : i + header + length])
        i += header + length
    if not out:
        raise OpcUaSecurityError(
            "the server sent no certificate", "BadCertificateInvalid"
        )
    return out


def _load_pem_or_der(path: Path, kind: str) -> list[Any]:
    """Every certificate (``kind="cert"``) or CRL (``kind="crl"``) in a file."""
    x509 = _x509()
    data = path.read_bytes()
    if b"-----BEGIN" in data:
        if kind == "cert":
            return list(x509.load_pem_x509_certificates(data))
        return [
            x509.load_pem_x509_crl(block)
            for block in re.findall(
                rb"-----BEGIN X509 CRL-----.+?-----END X509 CRL-----", data, re.S
            )
        ]
    return [
        x509.load_der_x509_certificate(data)
        if kind == "cert"
        else x509.load_der_x509_crl(data)
    ]


def _load_dir(location: str | Path | None, kind: str) -> list[Any]:
    """Certificates or CRLs from a file, a directory, or a Part 12 directory."""
    if location is None:
        return []
    p = Path(location)
    if not p.exists():
        raise OpcUaConfigurationError(f"{kind} location {p} does not exist")
    if p.is_file():
        return _load_pem_or_der(p, kind)
    sub = p / ("certs" if kind == "cert" else "crl")
    root = sub if sub.is_dir() else p
    suffixes = (
        {".der", ".pem", ".crt", ".cer"} if kind == "cert" else {".crl", ".pem", ".der"}
    )
    items: list[Any] = []
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() in suffixes:
            try:
                items.extend(_load_pem_or_der(f, kind))
            except ValueError as exc:
                raise OpcUaConfigurationError(
                    f"{f} is not a valid {kind}: {exc}"
                ) from exc
    return items


def _fail(status: str, message: str) -> OpcUaSecurityError:
    """An OpcUaSecurityError carrying a Part 4 status code."""
    return OpcUaSecurityError(message, status)


def validate_server_certificate(
    certificate: bytes,
    *,
    trusted: Sequence[Any],
    crls: Sequence[Any] = (),
    application_uri: str | None,
    host: str | None,
    require_crl: bool = True,
    now: datetime | None = None,
) -> Any:
    """Validate a server's application instance certificate (Part 4 §6.1.3).

    Args:
        certificate: The DER certificate the server sent, possibly followed
            by its issuer chain.
        trusted: The trust list. A certificate in it is trusted directly. Any
            other certificate must chain to a CA in it.
        crls: Revocation lists. For each CA-issued certificate in the chain,
            a current CRL signed by its issuer is required when
            ``require_crl`` is set.
        application_uri: The server's ApplicationUri, which must appear as a
            URI in the certificate's subjectAltName. ``None`` skips the check.
        host: The endpoint host, which must appear as a DNS name or IP
            address in the subjectAltName. ``None`` skips the check.
        require_crl: Fail when revocation cannot be determined.
        now: The time to check validity at (default: now).

    Returns:
        The validated leaf certificate (``cryptography.x509.Certificate``).

    Raises:
        OpcUaSecurityError: With the Part 4 status code of the first check
            that fails.
    """
    x509 = _x509()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID

    der = serialization.Encoding.DER
    now = now or datetime.now(timezone.utc)
    if not trusted:
        raise _fail(
            "BadCertificateUntrusted",
            "the trust list is empty, so no server can be trusted",
        )
    try:
        chain = [x509.load_der_x509_certificate(c) for c in _split_der_chain(certificate)]
    except ValueError as exc:
        raise _fail(
            "BadCertificateInvalid", f"the server certificate cannot be parsed: {exc}"
        ) from exc
    leaf = chain[0]
    trusted_der = {c.public_bytes(der) for c in trusted}

    # Trust: the leaf itself is in the trust list, or a chain leads to a CA that is.
    path = [leaf]
    if leaf.public_bytes(der) in trusted_der:
        if leaf.issuer == leaf.subject:
            try:
                leaf.verify_directly_issued_by(leaf)
            except Exception as exc:
                raise _fail(
                    "BadCertificateInvalid",
                    "the self-signed certificate's signature is invalid",
                ) from exc
    else:
        pool = list(chain[1:]) + list(trusted)
        current = leaf
        for _ in range(8):
            candidates = [
                c for c in pool if c.subject == current.issuer and c is not current
            ]
            issuer = None
            for cand in candidates:
                try:
                    current.verify_directly_issued_by(cand)
                except Exception:
                    continue
                issuer = cand
                break
            if issuer is None:
                if current.issuer == current.subject or candidates:
                    raise _fail(
                        "BadCertificateUntrusted",
                        f"{current.subject.rfc4514_string()} is not in the trust list and "
                        "does not chain to a CA that is",
                    )
                raise _fail(
                    "BadCertificateChainIncomplete",
                    f"the issuer of {current.subject.rfc4514_string()} "
                    f"({current.issuer.rfc4514_string()}) is not available",
                )
            try:
                bc = issuer.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value
                ku = issuer.extensions.get_extension_for_class(x509.KeyUsage).value
            except x509.ExtensionNotFound as exc:
                raise _fail(
                    "BadCertificateIssuerUseNotAllowed",
                    "an issuing certificate lacks CA extensions",
                ) from exc
            if not bc.ca or not ku.key_cert_sign:
                raise _fail(
                    "BadCertificateIssuerUseNotAllowed",
                    f"{issuer.subject.rfc4514_string()} is not a CA",
                )
            path.append(issuer)
            if issuer.public_bytes(der) in trusted_der:
                break
            current = issuer
        else:
            raise _fail(
                "BadCertificateChainIncomplete", "the certificate chain is too long"
            )

    # Validity period of every certificate on the path.
    for i, cert in enumerate(path):
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise _fail(
                "BadCertificateTimeInvalid"
                if i == 0
                else "BadCertificateIssuerTimeInvalid",
                f"{cert.subject.rfc4514_string()} is valid from {cert.not_valid_before_utc} "
                f"to {cert.not_valid_after_utc}",
            )

    # Security policy checks (Part 7): RSA 2048..4096, SHA-256 or stronger.
    key = leaf.public_key()
    if not isinstance(key, rsa.RSAPublicKey) or not 2048 <= key.key_size <= 4096:
        raise _fail(
            "BadCertificatePolicyCheckFailed",
            "the server key must be RSA, 2048 to 4096 bits",
        )
    alg = leaf.signature_hash_algorithm
    if alg is None or alg.name not in ("sha256", "sha384", "sha512"):
        raise _fail(
            "BadCertificatePolicyCheckFailed",
            f"the certificate is signed with {getattr(alg, 'name', 'no hash')}; SHA-256 or stronger is required",
        )

    # subjectAltName: ApplicationUri and host name.
    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound as exc:
        raise _fail(
            "BadCertificateInvalid", "the certificate has no subjectAltName"
        ) from exc
    if application_uri is not None and application_uri not in san.get_values_for_type(
        x509.UniformResourceIdentifier
    ):
        raise _fail(
            "BadCertificateUriInvalid",
            f"the server's ApplicationUri {application_uri!r} is not in its certificate",
        )
    if host is not None:
        names = {n.lower() for n in san.get_values_for_type(x509.DNSName)}
        ips = set(san.get_values_for_type(x509.IPAddress))
        try:
            ok = ipaddress.ip_address(host) in ips
        except ValueError:
            ok = host.lower() in names
        if not ok:
            raise _fail(
                "BadCertificateHostNameInvalid",
                f"the endpoint host {host!r} is not in the server certificate's subjectAltName",
            )

    # Key usage: an application instance certificate signs and encrypts keys.
    try:
        ku = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise _fail(
            "BadCertificateUseNotAllowed", "the certificate has no keyUsage"
        ) from exc
    if not (ku.digital_signature and ku.key_encipherment):
        raise _fail(
            "BadCertificateUseNotAllowed",
            "keyUsage must include digitalSignature and keyEncipherment",
        )
    with contextlib.suppress(x509.ExtensionNotFound):
        eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        if ExtendedKeyUsageOID.SERVER_AUTH not in eku:
            raise _fail(
                "BadCertificateUseNotAllowed",
                "extendedKeyUsage does not include serverAuth",
            )

    # Revocation, for every certificate a CA issued.
    for i, (child, issuer) in enumerate(itertools.pairwise(path)):
        usable = []
        for crl in crls:
            if crl.issuer != issuer.subject:
                continue
            try:
                if not crl.is_signature_valid(issuer.public_key()):
                    continue
            except Exception:
                continue
            nxt = crl.next_update_utc
            if nxt is not None and nxt < now:
                continue
            usable.append(crl)
        if not usable:
            if require_crl:
                raise _fail(
                    "BadCertificateRevocationUnknown"
                    if i == 0
                    else "BadCertificateIssuerRevocationUnknown",
                    f"no current CRL from {issuer.subject.rfc4514_string()}; revocation cannot be checked",
                )
            continue
        if any(
            c.get_revoked_certificate_by_serial_number(child.serial_number) is not None
            for c in usable
        ):
            raise _fail(
                "BadCertificateRevoked" if i == 0 else "BadCertificateIssuerRevoked",
                f"{child.subject.rfc4514_string()} has been revoked",
            )
    return leaf


def _uri_of(certificate: Any) -> str:
    """The URI in a certificate's subjectAltName (its ApplicationUri)."""
    x509 = _x509()
    try:
        uris = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound:
        uris = []
    if len(uris) != 1:
        raise OpcUaConfigurationError(
            "the client certificate must carry exactly one URI in its subjectAltName: "
            "the client's ApplicationUri (Part 4 §5.6.2, Part 6 §6.2.2)"
        )
    return str(uris[0])


def create_self_signed_certificate(
    certificate_path: str | Path,
    private_key_path: str | Path,
    *,
    application_uri: str,
    host_names: Sequence[str] = ("localhost",),
    common_name: str = "otwin",
    days: int = 365,
    key_size: int = 2048,
) -> Path:
    """Write a self-signed application instance certificate (Part 6 §6.2.2).

    The certificate carries the ApplicationUri and the host names in its
    subjectAltName, the key usages OPC UA requires (digitalSignature,
    nonRepudiation, keyEncipherment, dataEncipherment, keyCertSign) and both
    serverAuth and clientAuth. It is RSA, signed with SHA-256. The private
    key is written unencrypted with permissions 0600. Keep it on the machine
    that uses it.

    The server must trust the certificate before it will accept a secured
    connection: copy ``certificate_path`` into the server's trust list.

    Returns:
        ``certificate_path`` (DER).
    """
    x509 = _x509()
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if not 2048 <= key_size <= 4096:
        raise OpcUaConfigurationError("key_size must be 2048 to 4096 bits (Part 7)")
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    alt: list[Any] = [x509.UniformResourceIdentifier(application_uri)]
    for h in host_names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cp, kp = Path(certificate_path), Path(private_key_path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    kp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return cp


# --------------------------------------------------------------------------
# The optional dependency
# --------------------------------------------------------------------------


def _missing_asyncua() -> MissingDependencyError:
    """The error that says how to install the extra, and what to do without it."""
    return MissingDependencyError(
        "OPC UA I/O requires the 'asyncua' package, which is not installed. "
        "Install it with:\n"
        "    pip install 'otwin[opcua]'\n"
        "or directly:\n"
        "    pip install asyncua\n"
        "asyncua is licensed LGPL-3.0-or-later. It is an optional extra and is never "
        "bundled with otwin. OpcUaChannel, OpcUaSecurity and load_opcua_config work "
        "without it, so a configuration can be checked anywhere. If asyncua cannot be "
        "installed on this machine, have a gateway republish the OPC UA tags over "
        "Modbus and read them with otwin.io.ModbusSource, or work from recorded data "
        "with otwin.io.load."
    )


def _import_asyncua() -> Any:
    """Import asyncua, or raise the error that says how to install it."""
    try:
        return importlib.import_module("asyncua")
    except ImportError as exc:
        raise _missing_asyncua() from exc


# --------------------------------------------------------------------------
# The live source
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BrowseEntry:
    """One node found by :meth:`OpcUaSource.browse`.

    Attributes:
        node_id: ``ns=<index>;...`` form, valid for this session.
        expanded_node_id: ``nsu=<uri>;...`` form, stable across restarts.
            Prefer it in a configuration.
        browse_name: The node's BrowseName, ``<index>:<name>``.
        display_name: Its DisplayName text.
        node_class: ``"Object"``, ``"Variable"``, ...
        depth: How many references from the starting node.
        data_type: For a Variable, the numeric id of its DataType when it is
            in namespace 0, else its node id string. ``None`` otherwise.
        readable: For a Variable, whether the current user may read it.
        numeric: For a Variable, whether its DataType is one this client maps.
    """

    node_id: str
    expanded_node_id: str
    browse_name: str
    display_name: str
    node_class: str
    depth: int
    data_type: int | str | None = None
    readable: bool | None = None
    numeric: bool | None = None


class _Loop:
    """An asyncio loop in a daemon thread, so the source can offer a blocking API."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="otwin-opcua", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        """Run the loop forever, in the thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro: Any, timeout: float) -> Any:
        """Run ``coro`` on the loop and wait up to ``timeout`` seconds for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        """Stop the loop and close it. Idempotent."""
        if self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        with contextlib.suppress(Exception):
            self.loop.close()


class OpcUaSource:
    """Read named channels from an OPC UA server. Never writes.

    Args:
        endpoint: ``opc.tcp://host:port/path``, without credentials.
        channels: The nodes to read, each as a named :class:`OpcUaChannel`.
        security: How to secure the connection. Required: there is no safe
            default certificate or trust list. Use
            :meth:`OpcUaSecurity.insecure` for policy None.
        mode: ``"poll"`` (each :meth:`read` sends one Read request for every
            channel) or ``"subscribe"`` (the server pushes changes).
        sampling_interval: Seconds between server samples in subscribe mode.
        publishing_interval: Seconds between publish responses in subscribe
            mode. Defaults to ``sampling_interval``.
        timeout: Seconds to wait for any request.
        max_stale_seconds: See :class:`~otwin.io.source.QualityTracker`.
        normalise_units: Convert every value to SI (default).
        check_units: Refuse to connect if a node's EngineeringUnits (Part 8)
            names a unit other than the channel's (default).
        name: Overrides the string recorded in :attr:`Sample.source`.

    Raises:
        ReadOnlyViolation: Never at construction for a valid configuration.
            Raised if anything later tries to send a service that is not
            read-only.
        OpcUaConfigurationError: On a malformed endpoint, duplicate channel
            names or an unknown mode.
        MissingDependencyError: If asyncua is not installed.

    Quality follows the StatusCode of each value (Part 4 §7.39). Good gives
    ``"good"``. Uncertain gives ``"stale"`` with the server's value, because
    Uncertain is how a server says the value is its last usable one. Bad, a
    lost connection or a non-numeric value gives the last good value as
    ``"stale"``, or NaN as ``"bad"``. Timestamps are the host clock when the
    read started (poll) or when the notification arrived (subscribe), as for
    every otwin source. The servers' SourceTimestamps are kept in
    :attr:`source_timestamps`.

    Like :class:`~otwin.io.ModbusSource`, :meth:`read` does not raise for a
    network failure: it degrades the quality and records the error in
    :attr:`last_error`. It does raise for a security failure or a
    configuration the server contradicts. Those are not transient, and
    returning NaN forever would hide them.
    """

    def __init__(
        self,
        endpoint: str,
        channels: Sequence[OpcUaChannel],
        *,
        security: OpcUaSecurity,
        mode: str = "poll",
        sampling_interval: float = 1.0,
        publishing_interval: float | None = None,
        timeout: float = 5.0,
        max_stale_seconds: float | None = None,
        normalise_units: bool = True,
        check_units: bool = True,
        name: str | None = None,
    ) -> None:
        self.endpoint, self._host, self._port = _check_endpoint(endpoint)
        self.channels = list(channels)
        if not self.channels:
            raise OpcUaConfigurationError("a source with no channels reads nothing")
        for c in self.channels:
            if not isinstance(c, OpcUaChannel):
                raise OpcUaConfigurationError(
                    f"channels must be OpcUaChannel, got {type(c).__name__}"
                )
        names = [c.name for c in self.channels]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise OpcUaConfigurationError(f"duplicate channel names: {dupes}")
        if not isinstance(security, OpcUaSecurity):
            raise OpcUaConfigurationError("security must be an OpcUaSecurity")
        if mode not in ("poll", "subscribe"):
            raise OpcUaConfigurationError(
                f"mode must be 'poll' or 'subscribe', got {mode!r}"
            )
        if sampling_interval <= 0 or (
            publishing_interval is not None and publishing_interval <= 0
        ):
            raise OpcUaConfigurationError("intervals must be positive")
        self.security = security
        self.mode = mode
        self.sampling_interval = float(sampling_interval)
        self.publishing_interval = float(publishing_interval or sampling_interval)
        self.timeout = float(timeout)
        self.normalise_units = bool(normalise_units)
        self.check_units = bool(check_units)
        self.name = name or endpoint
        self.last_error: Exception | None = None
        self.source_timestamps: dict[str, float | None] = {}
        self._quality = QualityTracker(max_stale_seconds=max_stale_seconds)
        self._ua = _import_asyncua()
        self._loop: _Loop | None = None
        self._client: Any = None
        self._nodes: list[Any] = []
        self._resolved: list[dict[str, Any]] = []
        self._session: dict[str, Any] = {}
        self._subscription: Any = None
        self._latest: dict[str, tuple[float, str]] = {}
        self._pending: deque[Sample] = deque(maxlen=100_000)
        self._lock = threading.Lock()
        self._flush_scheduled = False
        self._by_node: dict[str, OpcUaChannel] = {}
        self._healthy = False
        self._closed = False

    # ------------------------------------------------------------ connecting

    def connect(self) -> None:
        """Open the secure channel and session, and check every channel.

        Called automatically by :meth:`read`, :meth:`browse` and
        :meth:`subscribe`.

        Raises:
            OpcUaSecurityError: If the server cannot be authenticated, offers
                no endpoint with the configured policy and mode, or rejects
                the identity token.
            OpcUaConfigurationError: If a channel's node is missing, not a
                readable numeric scalar, or in a different unit.
            ConnectionError, TimeoutError, OSError: If the server cannot be
                reached.
        """
        if self._closed:
            raise ConnectionError("this source is closed")
        if self._client is not None:
            return
        if not self.security.secure:
            warnings.warn(
                f"OPC UA connection to {self.endpoint} uses security policy None: nothing is "
                "signed or encrypted, and the server is not authenticated.",
                InsecureConnectionWarning,
                stacklevel=3,
            )
        if self._loop is None:
            self._loop = _Loop()
        try:
            self._loop.run(self._connect(), self.timeout * 4)
        except Exception as exc:
            self._loop.run(self._disconnect(), self.timeout)
            status = _security_status(exc, self._ua)
            if status is not None:
                raise OpcUaSecurityError(
                    f"the server refused the session: {exc}", status
                ) from exc
            raise

    async def _connect(self) -> None:
        """Discover, validate the server certificate, open the session, check the channels."""
        ua = self._ua.ua
        client = self._ua.Client(self.endpoint, timeout=self.timeout)
        client.name = "otwin"
        client.description = "otwin read-only OPC UA client"
        client.product_uri = "urn:otwin:opcua-client"
        _install_read_only_guard(client)
        sec = self.security
        session: dict[str, Any] = {
            "policy": sec.policy,
            "policy_uri": SECURITY_POLICIES[sec.policy],
            "mode": sec.mode,
            "user_token": "username" if sec.username else "anonymous",
        }

        if sec.secure:
            own = _load_pem_or_der(Path(sec.certificate), "cert")[0]  # type: ignore[arg-type]
            if (
                not own.not_valid_before_utc
                <= datetime.now(timezone.utc)
                <= own.not_valid_after_utc
            ):
                raise OpcUaSecurityError(
                    "the client certificate is outside its validity period",
                    "BadCertificateTimeInvalid",
                )
            client.application_uri = _uri_of(own)
            trusted = _load_dir(sec.trust, "cert")
            if not trusted:
                raise OpcUaConfigurationError(
                    f"the trust list {sec.trust} holds no certificates"
                )
            crls = _load_dir(sec.crl, "crl")
            if (Path(str(sec.trust)) / "crl").is_dir():  # Part 12 layout: trust/crl
                crls += _load_dir(Path(str(sec.trust)) / "crl", "crl")

            # Discovery (GetEndpoints) is the one exchange OPC UA defines without
            # security. Nothing secret is sent, and its answer is not trusted:
            # the certificate in it is validated before it is used.
            endpoints = await client.connect_and_get_server_endpoints()
            wanted_mode = getattr(ua.MessageSecurityMode, str(sec.mode))
            match = [
                e
                for e in endpoints
                if e.SecurityPolicyUri == SECURITY_POLICIES[sec.policy]
                and e.SecurityMode == wanted_mode
                and str(e.EndpointUrl).startswith("opc.tcp")
            ]
            if not match:
                offered = sorted(
                    {
                        (e.SecurityPolicyUri.rsplit("#", 1)[-1], e.SecurityMode.name)
                        for e in endpoints
                    }
                )
                raise OpcUaSecurityError(
                    f"the server offers no endpoint with {sec.policy}/{sec.mode}; it offers {offered}",
                    "BadSecurityPolicyRejected",
                )
            ep = match[0]
            token_type = (
                ua.UserTokenType.UserName if sec.username else ua.UserTokenType.Anonymous
            )
            if not any(t.TokenType == token_type for t in ep.UserIdentityTokens or []):
                raise OpcUaSecurityError(
                    f"the endpoint does not accept {token_type.name} identity tokens",
                    "BadIdentityTokenRejected",
                )
            leaf = validate_server_certificate(
                bytes(ep.ServerCertificate),
                trusted=trusted,
                crls=crls,
                application_uri=ep.Server.ApplicationUri,
                host=self._host if sec.check_hostname else None,
                require_crl=sec.require_crl,
            )
            from cryptography.hazmat.primitives import serialization

            leaf_der = leaf.public_bytes(serialization.Encoding.DER)
            policy_cls = getattr(
                importlib.import_module("asyncua.crypto.security_policies"),
                _ASYNCUA_POLICY_CLASS[sec.policy],
            )
            await client.set_security(
                policy_cls,
                certificate=str(sec.certificate),
                private_key=str(sec.private_key),
                private_key_password=sec.private_key_password,
                server_certificate=leaf_der,
                mode=wanted_mode,
            )
            expected_uri = ep.Server.ApplicationUri

            async def recheck(cert: Any, app: Any) -> None:
                """At CreateSession: the same certificate, for the same application."""
                # CreateSession: the same certificate, for the same application.
                if cert.public_bytes(serialization.Encoding.DER) != leaf_der:
                    raise OpcUaSecurityError(
                        "CreateSession returned a different server certificate",
                        "BadCertificateInvalid",
                    )
                if app.ApplicationUri != expected_uri:
                    raise OpcUaSecurityError(
                        "CreateSession named a different server application",
                        "BadCertificateUriInvalid",
                    )

            client.certificate_validator = recheck
            session.update(
                server_application_uri=expected_uri,
                server_certificate_sha256=hashlib.sha256(leaf_der).hexdigest(),
                server_certificate_subject=leaf.subject.rfc4514_string(),
                server_certificate_not_after=leaf.not_valid_after_utc.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                trusted_directly=leaf_der
                in {c.public_bytes(serialization.Encoding.DER) for c in trusted},
                client_application_uri=client.application_uri,
            )

        if sec.username:
            client.set_user(sec.username)
            client.set_password(sec.password)
            _install_password_rule(client, ua)

        self._client = client
        await client.connect()
        negotiated = client.security_policy.URI
        if negotiated != SECURITY_POLICIES[sec.policy]:
            raise OpcUaSecurityError(
                "the session was not opened with the configured policy",
                "BadSecurityPolicyRejected",
            )
        self._session = session
        await self._resolve_channels()
        self._healthy = True
        if self.mode == "subscribe":
            await self._subscribe()

    async def _resolve_channels(self) -> None:
        """Turn node ids into nodes, and check each is a readable numeric scalar in the stated unit."""
        ua = self._ua.ua
        client = self._client
        ns_array = list(await client.get_namespace_array())
        nodes, resolved = [], []
        for ch in self.channels:
            ns, nsu, kind, ident = parse_node_id(ch.node_id)
            if nsu is not None:
                if nsu not in ns_array:
                    raise OpcUaConfigurationError(
                        f"channel {ch.name!r}: namespace {nsu!r} is not on the server "
                        "(BadNodeIdUnknown)"
                    )
                ns = ns_array.index(nsu)
            ns = ns or 0
            if ns >= len(ns_array):
                raise OpcUaConfigurationError(
                    f"channel {ch.name!r}: namespace index {ns} is not on the server"
                )
            text = f"ns={ns};{kind}={ident}"
            node = client.get_node(ua.NodeId.from_string(text))
            nodes.append(node)
            resolved.append(
                {
                    "name": ch.name,
                    "node_id": text,
                    "expanded_node_id": f"nsu={ns_array[ns]};{kind}={ident}",
                    "namespace_uri": ns_array[ns],
                    "unit": si_unit(ch.unit) if self.normalise_units else ch.unit,
                    "raw_unit": ch.unit,
                }
            )

        ids = [n.nodeid for n in nodes]

        async def attr(a: Any) -> list[Any]:
            """One attribute of every channel node, in one Read request."""
            return list(await client.uaclient.read_attributes(ids, a))

        A = ua.AttributeIds
        classes, types, ranks = (
            await attr(A.NodeClass),
            await attr(A.DataType),
            await attr(A.ValueRank),
        )
        access, user_access = await attr(A.AccessLevel), await attr(A.UserAccessLevel)
        for ch, r, nc, dt, vr, al, ual in zip(
            self.channels,
            resolved,
            classes,
            types,
            ranks,
            access,
            user_access,
            strict=True,
        ):
            if not nc.StatusCode.is_good():
                raise OpcUaConfigurationError(
                    f"channel {ch.name!r}: node {ch.node_id} does not exist ({nc.StatusCode.name})"
                )
            if nc.Value.Value != ua.NodeClass.Variable:
                raise OpcUaConfigurationError(
                    f"channel {ch.name!r}: {ch.node_id} is not a Variable"
                )
            dtype = dt.Value.Value
            if dtype.NamespaceIndex != 0 or dtype.Identifier not in _NUMERIC_DATATYPES:
                raise OpcUaConfigurationError(
                    f"channel {ch.name!r}: {ch.node_id} has DataType {dtype.to_string()}, which is "
                    "not a numeric scalar. A Sample carries floats only."
                )
            if vr.Value.Value != -1:
                raise OpcUaConfigurationError(
                    f"channel {ch.name!r}: {ch.node_id} is not a scalar (ValueRank {vr.Value.Value})"
                )
            for label, level in (("AccessLevel", al), ("UserAccessLevel", ual)):
                if not (int(level.Value.Value or 0) & _CURRENT_READ):
                    raise OpcUaConfigurationError(
                        f"channel {ch.name!r}: {ch.node_id} is not readable ({label} lacks CurrentRead)"
                    )
            r["data_type"] = int(dtype.Identifier)
        for ch, r, node in zip(self.channels, resolved, nodes, strict=True):
            eu = await _engineering_units(node, ua)
            if eu is not None:
                r["engineering_units"] = eu
                if (
                    self.check_units
                    and eu["unit"] is not None
                    and not _same_unit(eu["unit"], ch.unit)
                ):
                    raise OpcUaConfigurationError(
                        f"channel {ch.name!r} states unit {ch.unit!r}, but the server's "
                        f"EngineeringUnits for {ch.node_id} say {eu['display_name']!r} "
                        f"({eu['unit']}). A unit mix-up is invisible downstream, so the "
                        "connection is refused. Fix the channel's unit, or pass check_units=False."
                    )
        self._nodes, self._resolved = nodes, resolved

    async def _disconnect(self) -> None:
        """Close the session and channel, quietly. The next read reconnects."""
        client, self._client = self._client, None
        self._subscription = None
        self._healthy = False
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()

    # ------------------------------------------------------------ browsing

    def browse(self, start: str = "i=85", *, max_depth: int = 3) -> list[BrowseEntry]:
        """List the nodes below ``start``, following hierarchical references.

        Uses only the Browse and Read services. ``i=85`` is the Objects folder.

        Args:
            start: The node to start from.
            max_depth: How many levels to descend.
        """
        self.connect()
        assert self._loop is not None
        return self._loop.run(self._browse(start, max_depth), self.timeout * 10)

    async def _browse(self, start: str, max_depth: int) -> list[BrowseEntry]:
        """Breadth-first Browse along hierarchical references, then one Read for variables."""
        ua = self._ua.ua
        client = self._client
        ns_array = list(await client.get_namespace_array())
        ns, nsu, kind, ident = parse_node_id(start)
        if nsu is not None:
            ns = ns_array.index(nsu)
        root = client.get_node(ua.NodeId.from_string(f"ns={ns or 0};{kind}={ident}"))
        out: list[BrowseEntry] = []
        frontier, seen = [(root, 0)], {root.nodeid.to_string()}
        while frontier:
            node, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            refs = await node.get_references(
                refs=ua.ObjectIds.HierarchicalReferences,
                direction=ua.BrowseDirection.Forward,
            )
            for ref in refs:
                nid = ref.NodeId
                key = nid.to_string()
                if key in seen or nid.NamespaceIndex >= len(ns_array):
                    continue
                seen.add(key)
                child = client.get_node(nid)
                text = key if key.startswith("ns=") else f"ns=0;{key}"
                ident_part = text.split(";", 1)[1]
                out.append(
                    BrowseEntry(
                        node_id=text,
                        expanded_node_id=f"nsu={ns_array[nid.NamespaceIndex]};{ident_part}",
                        browse_name=ref.BrowseName.to_string(),
                        display_name=ref.DisplayName.Text or "",
                        node_class=ref.NodeClass.name,
                        depth=depth + 1,
                    )
                )
                frontier.append((child, depth + 1))
        variables = [i for i, e in enumerate(out) if e.node_class == "Variable"]
        if variables:
            ids = [ua.NodeId.from_string(out[i].node_id) for i in variables]
            types = await client.uaclient.read_attributes(ids, ua.AttributeIds.DataType)
            levels = await client.uaclient.read_attributes(
                ids, ua.AttributeIds.UserAccessLevel
            )
            for i, t, lv in zip(variables, types, levels, strict=True):
                dt = t.Value.Value if t.StatusCode.is_good() else None
                out[i] = dataclasses.replace(
                    out[i],
                    data_type=None
                    if dt is None
                    else (
                        int(dt.Identifier) if dt.NamespaceIndex == 0 else dt.to_string()
                    ),
                    readable=bool(
                        lv.StatusCode.is_good()
                        and int(lv.Value.Value or 0) & _CURRENT_READ
                    ),
                    numeric=dt is not None
                    and dt.NamespaceIndex == 0
                    and dt.Identifier in _NUMERIC_DATATYPES,
                )
        return out

    # ------------------------------------------------------------ the Source contract

    def tags(self) -> list[TagSpec]:
        """One :class:`TagSpec` per channel, in configuration order.

        ``dtype`` is the node's OPC UA DataType once connected.
        """
        dtypes = {r["name"]: r.get("data_type", -1) for r in self._resolved}
        return [
            TagSpec(
                name=c.name,
                unit=si_unit(c.unit) if self.normalise_units else c.unit,
                description=c.description or f"OPC UA node {c.node_id}",
                dtype=_DATATYPE_NAMES.get(dtypes.get(c.name, -1), "opcua"),
                raw_unit=c.unit,
            )
            for c in self.channels
        ]

    def _value(self, ch: OpcUaChannel, raw: Any) -> float | None:
        """A Variant value as a float in the delivered unit, or ``None`` if not numeric."""
        if isinstance(raw, bool):
            raw = float(raw)
        if not isinstance(raw, (int, float)) or (
            isinstance(raw, float) and not math.isfinite(raw)
        ):
            return None
        return to_si(float(raw), ch.unit) if self.normalise_units else float(raw)

    def _apply(
        self,
        ch: OpcUaChannel,
        dv: Any,
        now: float,
        values: dict[str, float],
        quality: dict[str, str],
    ) -> None:
        """One DataValue into a value and a quality flag."""
        status = dv.StatusCode
        variant = dv.Value
        value = None if variant is None else self._value(ch, variant.Value)
        ts = dv.SourceTimestamp
        self.source_timestamps[ch.name] = (
            None
            if ts is None
            else ts.replace(tzinfo=ts.tzinfo or timezone.utc).timestamp()
        )
        if value is not None and (status is None or status.is_good()):
            values[ch.name], quality[ch.name] = value, "good"
            self._quality.record_good(ch.name, value, now)
        elif value is not None and status.is_uncertain():
            values[ch.name], quality[ch.name] = value, "stale"
        else:
            values[ch.name], quality[ch.name] = self._quality.resolve_failed(ch.name, now)

    def _degraded(self, now: float) -> Sample:
        """A Sample in which every channel failed this cycle."""
        values: dict[str, float] = {}
        quality: dict[str, str] = {}
        for ch in self.channels:
            values[ch.name], quality[ch.name] = self._quality.resolve_failed(ch.name, now)
        return Sample(timestamp=now, values=values, quality=quality, source=self.name)

    def read(self) -> Sample:
        """Read every channel once.

        In poll mode this sends one Read request for all channels. In
        subscribe mode it returns the latest notified values.

        A network failure degrades quality instead of raising, and the next
        call reconnects. Security and configuration failures raise.
        """
        now = time.time()
        self.last_error = None
        if self._client is not None and not self._healthy and self._loop is not None:
            self._loop.run(self._disconnect(), self.timeout)  # reconnect below
        try:
            self.connect()
        except (
            OpcUaSecurityError,
            OpcUaConfigurationError,
            ReadOnlyViolation,
            MissingDependencyError,
        ):
            raise
        except Exception as exc:
            self.last_error = exc
            return self._degraded(now)
        assert self._loop is not None
        if self.mode == "subscribe":
            return self._snapshot(now)
        try:
            dvs = self._loop.run(
                self._client.uaclient.read_attributes(
                    [n.nodeid for n in self._nodes], self._ua.ua.AttributeIds.Value
                ),
                self.timeout,
            )
        except Exception as exc:
            self.last_error = exc
            self._loop.run(self._disconnect(), self.timeout)
            return self._degraded(now)
        values: dict[str, float] = {}
        quality: dict[str, str] = {}
        for ch, dv in zip(self.channels, dvs, strict=True):
            self._apply(ch, dv, now, values, quality)
        return Sample(timestamp=now, values=values, quality=quality, source=self.name)

    # ------------------------------------------------------------ subscriptions

    def subscribe(self, wait_for_initial: bool = True) -> None:
        """Start the subscription, in subscribe mode.

        The server reports each channel's current value first, then every
        change. With ``wait_for_initial``, this returns once every channel has
        reported, or after ``timeout`` seconds. Use :meth:`drain` for the
        series and :meth:`read` for the latest values.
        """
        if self.mode != "subscribe":
            raise OpcUaConfigurationError("subscribe() needs mode='subscribe'")
        self.connect()
        if wait_for_initial:
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                with self._lock:
                    if len(self._latest) == len(self.channels):
                        return
                time.sleep(0.01)

    async def _subscribe(self) -> None:
        """Create the subscription and one monitored item per channel."""
        handler = _Notifications(self)
        sub = await self._client.create_subscription(
            self.publishing_interval * 1000.0, handler
        )
        handles = await sub.subscribe_data_change(
            self._nodes, sampling_interval=self.sampling_interval * 1000.0
        )
        bad = [
            c.name
            for c, h in zip(self.channels, handles, strict=True)
            if not isinstance(h, int)
        ]
        if bad:
            raise OpcUaConfigurationError(f"the server would not monitor {bad}")
        self._subscription = sub
        self._by_node = {
            n.nodeid.to_string(): c
            for n, c in zip(self._nodes, self.channels, strict=True)
        }

    def _notify(self, node_id: str, dv: Any) -> None:
        """A data change, in the loop thread: update the latest values and queue a Sample."""
        ch = self._by_node.get(node_id)
        if ch is None:
            return
        now = time.time()
        values: dict[str, float] = {}
        quality: dict[str, str] = {}
        self._apply(ch, dv, now, values, quality)
        with self._lock:
            self._latest[ch.name] = (values[ch.name], quality[ch.name])
            if not self._flush_scheduled:
                # Changes delivered in the same publish response become one Sample.
                self._flush_scheduled = True
                asyncio.get_running_loop().call_soon(self._flush)

    def _flush(self) -> None:
        """Queue one Sample for the notifications received since the last flush."""
        with self._lock:
            self._flush_scheduled = False
            self._pending.append(self._snapshot_locked(time.time()))

    def _snapshot_locked(self, now: float) -> Sample:
        """The latest values as a Sample. The caller holds the lock."""
        values: dict[str, float] = {}
        quality: dict[str, str] = {}
        for ch in self.channels:
            if self._healthy and ch.name in self._latest:
                values[ch.name], quality[ch.name] = self._latest[ch.name]
            else:
                values[ch.name], quality[ch.name] = self._quality.resolve_failed(
                    ch.name, now
                )
        return Sample(timestamp=now, values=values, quality=quality, source=self.name)

    def _snapshot(self, now: float) -> Sample:
        """The latest values as a Sample."""
        with self._lock:
            return self._snapshot_locked(now)

    def _lost(self, reason: str) -> None:
        """Mark the subscription unhealthy, so values degrade and the next read reconnects."""
        self._healthy = False
        self.last_error = ConnectionError(reason)

    def drain(self) -> list[Sample]:
        """Every Sample produced by the subscription since the last call, oldest first."""
        with self._lock:
            out = list(self._pending)
            self._pending.clear()
        return out

    # ------------------------------------------------------------ provenance

    def acquisition(self) -> dict[str, Any]:
        """The record for :attr:`TwinManifest.acquisition <otwin.interfaces.TwinManifest.acquisition>`.

        It holds the endpoint, the security policy and mode, the server
        certificate's SHA-256 thumbprint and ApplicationUri, the identity
        token type, and for every channel the node id in both forms, the
        namespace URI, the DataType, the unit and any EngineeringUnits. It
        never holds a username, password or key. Connects if necessary.
        """
        from otwin.interfaces import TwinManifest

        self.connect()
        fields: dict[str, Any] = {"security": dict(self._session), "mode": self.mode}
        if self.mode == "subscribe":
            fields.update(
                sampling_interval_s=self.sampling_interval,
                publishing_interval_s=self.publishing_interval,
            )
        return TwinManifest.acquired_by(
            "opc-ua", endpoint=self.endpoint, channels=self._resolved, **fields
        )

    # ------------------------------------------------------------ lifecycle

    def close(self) -> None:
        """Delete the subscription, close the session and the channel. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.run(self._disconnect(), self.timeout)
            self._loop.stop()

    def __enter__(self) -> OpcUaSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"OpcUaSource({self.endpoint!r}, channels={len(self.channels)}, mode={self.mode!r}, "
            f"policy={self.security.policy}/{self.security.mode})"
        )


class _Notifications:
    """asyncua subscription handler: forwards data changes to the source."""

    def __init__(self, source: OpcUaSource) -> None:
        self._source = source

    def datachange_notification(self, node: Any, val: Any, data: Any) -> None:
        """Forward one data change to the source."""
        self._source._notify(node.nodeid.to_string(), data.monitored_item.Value)

    def status_change_notification(self, status: Any) -> None:
        """A subscription status change. Anything not Good means the data stopped."""
        code = getattr(status, "Status", None)
        if code is not None and not code.is_good():
            self._source._lost(f"subscription status changed to {code.name}")


async def _engineering_units(node: Any, ua: Any) -> dict[str, Any] | None:
    """The node's EngineeringUnits property (Part 8 §5.6.3), or ``None``."""
    try:
        prop = await node.get_child("0:EngineeringUnits")
        eu = await prop.read_value()
    except Exception:
        return None
    if eu is None or not hasattr(eu, "UnitId"):
        return None
    code = _unece_code(int(eu.UnitId)) if eu.NamespaceUri == _UNECE_NAMESPACE else None
    return {
        "namespace_uri": eu.NamespaceUri,
        "unit_id": int(eu.UnitId),
        "unece_code": code,
        "display_name": getattr(eu.DisplayName, "Text", None),
        "unit": _UNECE.get(code) if code else None,
    }


#: Status codes that mean the server rejected who we are or how we connected,
#: not that the network failed. These raise rather than degrade.
_SECURITY_STATUS_PREFIXES = (
    "BadCertificate",
    "BadSecurity",
    "BadIdentity",
    "BadUser",
    "BadNonce",
    "BadApplicationSignature",
    "BadSessionNotActivated",
)


def _security_status(exc: BaseException, ua_mod: Any) -> str | None:
    """The status code name if ``exc`` is a security rejection, else ``None``."""
    ua = ua_mod.ua
    code = getattr(exc, "code", None)
    if code is not None:
        with contextlib.suppress(Exception):
            name = ua.StatusCode(code).name
            if name.startswith(_SECURITY_STATUS_PREFIXES):
                return name
    if isinstance(exc, ua.UaError) and "certificate mismatch" in str(exc).lower():
        return "BadCertificateInvalid"
    return None


def _install_read_only_guard(client: Any) -> None:
    """Refuse, on this client, every service request that is not read-only.

    Every request asyncua sends, from the session or from a Node, passes
    through ``UaClient._send_request``. Wrapping it here means a Write or a
    Call cannot leave the process, whoever builds it.
    """
    uaclient = client.uaclient
    original = uaclient._send_request

    async def guarded(request: Any, *args: Any, **kwargs: Any) -> Any:
        """Send ``request`` only if it is a read-only service."""
        service = type(request).__name__
        if service not in READ_ONLY_SERVICES:
            raise ReadOnlyViolation(
                f"refused to send {service}: otwin's OPC UA client only sends read-only "
                "services and never writes to, or calls methods on, a server"
            )
        return await original(request, *args, **kwargs)

    uaclient._send_request = guarded


def _install_password_rule(client: Any, ua: Any) -> None:
    """Refuse to send a password that would cross the network in clear.

    The UserTokenPolicy's SecurityPolicyUri decides how the password is
    protected (Part 4 §7.41). If it names a policy, the password is encrypted
    with it. If it is empty, the secure channel's policy is used, and asyncua
    applies that rule itself. If it names policy None, the password travels
    unencrypted inside the channel, which is only safe when the channel
    encrypts. asyncua then logs a warning and sends it anyway. Here that case
    is refused before the token is built.
    """
    none_uri = SECURITY_POLICIES["None"]
    original = client._add_user_auth

    def add_user_auth(params: Any, username: str | None, password: str | None) -> None:
        effective = client.server_policy(ua.UserTokenType.UserName).SecurityPolicyUri
        if (
            effective == none_uri
            and client.security_policy.Mode != ua.MessageSecurityMode.SignAndEncrypt
        ):
            raise OpcUaSecurityError(
                "the server's UserName token policy does not encrypt the password, and "
                "the channel only signs: the password would cross the network readable. "
                "Use security mode SignAndEncrypt.",
                "BadSecurityModeInsufficient",
            )
        original(params, username, password)

    client._add_user_auth = add_user_auth
