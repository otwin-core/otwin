"""The read-only OPC UA client, against a real asyncua server on localhost.

Every live test starts an asyncua server inside the test process, bound to
127.0.0.1, with values the test sets itself and certificates the test
generates. Nothing leaves the machine. The tests check five things:

* the values arrive as the same Samples the Modbus sources produce, and flow
  through otwin.signal and otwin.estimate unchanged;
* nothing can make the client write, including code that reaches past its API
  into the asyncua client, and a configuration that asks to write is refused;
* the connection is secured as OPC UA Parts 4, 6 and 7 require: the server
  certificate is validated before any credential is sent, deprecated and
  insecure policies are refused, and passwords are never sent in clear;
* the endpoint and the node mapping are recorded in the TwinManifest, with
  no secret in it;
* the certificate checks each reject with the right status code.

The configuration tests, which need neither asyncua nor a network, are in
test_io_opcua_config.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from otwin.interfaces import Provenance, TwinManifest
from otwin.io import (
    InsecureConnectionWarning,
    OpcUaChannel,
    OpcUaConfigurationError,
    OpcUaSecurity,
    OpcUaSecurityError,
    OpcUaSource,
    ReadOnlyViolation,
    Source,
    samples_to_arrays,
)

PLANT_NS = "urn:otwin:test:plant"
SERVER_URI = "urn:otwin:test:server"
CLIENT_URI = "urn:otwin:test:client"

# ==========================================================================
# Certificates: Part 4 §6.1.3, checked without a server
# ==========================================================================

asyncua = pytest.importorskip("asyncua", reason="the live OPC UA tests need otwin[opcua]")
from asyncua import Server, ua  # noqa: E402
from asyncua.crypto.permission_rules import User, UserRole  # noqa: E402
from asyncua.server.user_managers import UserManager  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: E402

from otwin.io import create_self_signed_certificate, validate_server_certificate  # noqa: E402

DER = serialization.Encoding.DER


def _cert(
    subject,
    key,
    *,
    issuer=None,
    issuer_key=None,
    uri=SERVER_URI,
    hosts=("localhost", "127.0.0.1"),
    ca=False,
    days=30,
    start=None,
    eku=(ExtendedKeyUsageOID.SERVER_AUTH,),
    digest=None,
    key_encipherment=True,
):
    """A certificate for the validation tests. Self-signed unless an issuer is given."""
    digest = digest or hashes.SHA256()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    start = start or datetime.now(timezone.utc) - timedelta(minutes=5)
    alt = [x509.UniformResourceIdentifier(uri)] if uri else []
    for h in hosts:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    b = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer.subject if issuer else name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=key_encipherment,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    if alt:
        b = b.add_extension(x509.SubjectAlternativeName(alt), critical=False)
    if eku:
        b = b.add_extension(x509.ExtendedKeyUsage(list(eku)), critical=False)
    return b.sign(issuer_key or key, digest)


def _crl(ca, ca_key, revoked=()):
    now = datetime.now(timezone.utc)
    b = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca.subject)
        .last_update(now)
        .next_update(now + timedelta(days=7))
    )
    for serial in revoked:
        b = b.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(now)
            .build()
        )
    return b.sign(ca_key, hashes.SHA256())


@pytest.fixture(scope="module")
def keys():
    return {
        k: rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for k in ("srv", "ca", "other")
    }


def _check(cert, trusted, **kw):
    args = {"application_uri": SERVER_URI, "host": "127.0.0.1", **kw}
    return validate_server_certificate(cert.public_bytes(DER), trusted=trusted, **args)


def test_a_directly_trusted_self_signed_certificate_passes(keys):
    c = _cert("server", keys["srv"])
    assert _check(c, [c]) == c


@pytest.mark.parametrize(
    "build, kw, status",
    [
        (
            lambda k: _cert("server", k["srv"]),
            {"trusted_override": "other"},
            "BadCertificateUntrusted",
        ),
        (
            lambda k: _cert(
                "server",
                k["srv"],
                start=datetime.now(timezone.utc) - timedelta(days=40),
                days=30,
            ),
            {},
            "BadCertificateTimeInvalid",
        ),
        (
            lambda k: _cert("server", k["srv"]),
            {"application_uri": "urn:someone:else"},
            "BadCertificateUriInvalid",
        ),
        (
            lambda k: _cert("server", k["srv"], hosts=("plc.example",)),
            {},
            "BadCertificateHostNameInvalid",
        ),
        (
            lambda k: _cert("server", k["srv"], eku=(ExtendedKeyUsageOID.CLIENT_AUTH,)),
            {},
            "BadCertificateUseNotAllowed",
        ),
        (
            lambda k: _cert("server", k["srv"], key_encipherment=False),
            {},
            "BadCertificateUseNotAllowed",
        ),
        (
            lambda k: _cert("server", k["srv"], digest=hashes.SHA224()),
            {},
            "BadCertificatePolicyCheckFailed",
        ),  # below SHA-256; cryptography no longer signs SHA-1
        (
            lambda k: _cert(
                "server", rsa.generate_private_key(public_exponent=65537, key_size=1024)
            ),
            {},
            "BadCertificatePolicyCheckFailed",
        ),
        (
            lambda k: _cert("server", k["srv"], uri=None, hosts=()),
            {},
            "BadCertificateInvalid",
        ),  # no subjectAltName at all
    ],
)
def test_each_part_4_check_rejects_with_its_status_code(keys, build, kw, status):
    c = build(keys)
    trusted = (
        [_cert("impostor", keys["other"])] if kw.pop("trusted_override", None) else [c]
    )
    with pytest.raises(OpcUaSecurityError) as e:
        _check(c, trusted, **kw)
    assert e.value.status == status


def test_a_ca_issued_certificate_needs_the_ca_and_its_crl(keys):
    ca = _cert("plant CA", keys["ca"], uri=None, hosts=(), ca=True, eku=())
    srv = _cert("server", keys["srv"], issuer=ca, issuer_key=keys["ca"])
    with pytest.raises(OpcUaSecurityError) as e:
        _check(srv, [_cert("impostor", keys["other"])])
    assert e.value.status == "BadCertificateChainIncomplete"
    with pytest.raises(OpcUaSecurityError) as e:
        _check(srv, [ca])  # no CRL
    assert e.value.status == "BadCertificateRevocationUnknown"
    assert _check(srv, [ca], require_crl=False) == srv
    assert _check(srv, [ca], crls=[_crl(ca, keys["ca"])]) == srv
    with pytest.raises(OpcUaSecurityError) as e:
        _check(srv, [ca], crls=[_crl(ca, keys["ca"], revoked=[srv.serial_number])])
    assert e.value.status == "BadCertificateRevoked"
    forged = _crl(
        _cert("plant CA", keys["other"], uri=None, hosts=(), ca=True, eku=()),
        keys["other"],
    )
    with pytest.raises(OpcUaSecurityError) as e:  # a CRL the CA did not sign
        _check(srv, [ca], crls=[forged])
    assert e.value.status == "BadCertificateRevocationUnknown"


def test_generated_certificates_meet_part_6(tmp_path):
    cert_path = create_self_signed_certificate(
        tmp_path / "own" / "c.der",
        tmp_path / "own" / "k.pem",
        application_uri=CLIENT_URI,
        host_names=("localhost", "127.0.0.1"),
    )
    c = x509.load_der_x509_certificate(cert_path.read_bytes())
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.UniformResourceIdentifier) == [CLIENT_URI]
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)
    ku = c.extensions.get_extension_for_class(x509.KeyUsage).value
    assert ku.digital_signature and ku.key_encipherment and ku.data_encipherment
    assert c.signature_hash_algorithm.name == "sha256" and c.public_key().key_size == 2048
    assert (tmp_path / "own" / "k.pem").stat().st_mode & 0o077 == 0  # the key is private


# ==========================================================================
# A real server on localhost
# ==========================================================================


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _eu(code: str, text: str) -> ua.EUInformation:
    uid = 0
    for ch in code:
        uid = (uid << 8) | ord(ch)
    return ua.EUInformation(
        NamespaceUri="http://www.opcfoundation.org/UA/units/un/cefact",
        UnitId=uid,
        DisplayName=ua.LocalizedText(text),
        Description=ua.LocalizedText(text),
    )


class _Users(UserManager):
    """Admin for every accepted user, so the server itself would accept a write.

    That way, the only thing stopping a write in these tests is the client.
    """

    def __init__(self):
        self.seen = []  # (username, password) the server received

    def get_user(self, iserver, username=None, password=None, certificate=None):
        self.seen.append((username, password))
        if username is None:
            return User(role=UserRole.Admin)
        return (
            User(role=UserRole.Admin)
            if (username, password) == ("operator", "s3cret")
            else None
        )


class PlantServer:
    """An asyncua server in its own thread and event loop, on 127.0.0.1."""

    def __init__(self, pki: Path):
        self.pki = pki
        self.port = _free_port()
        self.endpoint = f"opc.tcp://127.0.0.1:{self.port}/otwin/"
        self.users = _Users()
        self.client_uris: list[str] = []
        self.tokens: list[str | None] = []
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.run(self._start())

    def run(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _start(self):
        s = Server(user_manager=self.users)
        await s.init()
        s.set_endpoint(self.endpoint)
        s.set_server_name("otwin test plant")
        await s.set_application_uri(SERVER_URI)
        s.set_security_policy(
            [
                ua.SecurityPolicyType.NoSecurity,
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                ua.SecurityPolicyType.Basic256Sha256_Sign,
                ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt,
            ]
        )
        s.set_identity_tokens([ua.AnonymousIdentityToken, ua.UserNameIdentityToken])
        await s.load_certificate(str(self.pki / "server.der"))
        await s.load_private_key(str(self.pki / "server.pem"))
        client_der = (self.pki / "client.der").read_bytes()

        async def only_our_client(cert, app):
            # The server side of mutual authentication: it trusts our client
            # certificate and nothing else.
            self.client_uris.append(app.ApplicationUri)
            if cert.public_bytes(DER) != client_der:
                raise asyncua.common.utils.ServiceError(
                    ua.StatusCodes.BadCertificateUntrusted
                )

        s.set_certificate_validator(only_our_client)
        original = s.iserver.decrypt_user_token

        def spy(isession, token):
            self.tokens.append(token.EncryptionAlgorithm)
            return original(isession, token)

        s.iserver.decrypt_user_token = spy

        idx = await s.register_namespace(PLANT_NS)
        objs = s.nodes.objects
        self.vars = {}

        async def var(name, value, vtype, unit=None):
            node = await objs.add_variable(
                ua.NodeId(name, idx), name, ua.Variant(value, vtype)
            )
            if unit is not None:
                await node.add_property(0, "EngineeringUnits", _eu(*unit))
            self.vars[name] = node
            return node

        await var("Pump.Power", 250.0, ua.VariantType.Double, ("KWT", "kW"))
        await var("Tank.Fill", 62.5, ua.VariantType.Float, ("P1", "%"))
        await var("Cabinet.Temperature", 31.5, ua.VariantType.Double, ("CEL", "°C"))
        await var("Breaker.Closed", True, ua.VariantType.Boolean)
        await var("Cycles", 1450, ua.VariantType.UInt32)
        await var("Serial", "PCS-0042", ua.VariantType.String)
        await var("Vector", [1.0, 2.0], ua.VariantType.Double)
        secret = await var("Secret", 7.0, ua.VariantType.Double)
        for a in (ua.AttributeIds.AccessLevel, ua.AttributeIds.UserAccessLevel):
            await secret.write_attribute(
                a, ua.DataValue(ua.Variant(0, ua.VariantType.Byte))
            )
        setpoint = await var("Pump.Setpoint", 100.0, ua.VariantType.Double)
        await setpoint.set_writable()  # the server would accept a write
        self.server = s
        await s.start()

    def set(self, name, value, vtype=ua.VariantType.Double, status=None):
        dv = (
            ua.DataValue(ua.Variant(value, vtype), StatusCode=ua.StatusCode(status))
            if status
            else ua.Variant(value, vtype)
        )
        self.run(self.vars[name].write_value(dv))

    def get(self, name):
        return self.run(self.vars[name].read_value())

    def stop(self):
        with contextlib.suppress(Exception):
            self.run(self.server.stop())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """Server and client certificates, and the client's trust list in the Part 12 layout."""
    d = tmp_path_factory.mktemp("pki")
    create_self_signed_certificate(
        d / "server.der",
        d / "server.pem",
        application_uri=SERVER_URI,
        host_names=("localhost", "127.0.0.1"),
        common_name="test server",
    )
    create_self_signed_certificate(
        d / "client.der",
        d / "client.pem",
        application_uri=CLIENT_URI,
        host_names=("localhost",),
        common_name="otwin client",
    )
    create_self_signed_certificate(
        d / "impostor.der",
        d / "impostor.pem",
        application_uri=SERVER_URI,
        host_names=("127.0.0.1",),
        common_name="impostor",
    )
    (d / "trusted" / "certs").mkdir(parents=True)
    (d / "trusted" / "certs" / "server.der").write_bytes((d / "server.der").read_bytes())
    (d / "untrusted" / "certs").mkdir(parents=True)
    (d / "untrusted" / "certs" / "impostor.der").write_bytes(
        (d / "impostor.der").read_bytes()
    )
    return d


@pytest.fixture(scope="module")
def plant(pki):
    srv = PlantServer(pki)
    assert srv.endpoint.startswith("opc.tcp://127.0.0.1:")  # localhost only
    yield srv
    srv.stop()


def secure(pki, **kw):
    args = {
        "certificate": pki / "client.der",
        "private_key": pki / "client.pem",
        "trust": pki / "trusted",
    }
    return OpcUaSecurity(**{**args, **kw})


CHANNELS = [
    OpcUaChannel("p_out", f"nsu={PLANT_NS};s=Pump.Power", "kW", "pump power"),
    OpcUaChannel("fill", f"nsu={PLANT_NS};s=Tank.Fill", "percent"),
    OpcUaChannel("t_cab", f"nsu={PLANT_NS};s=Cabinet.Temperature", "degC"),
    OpcUaChannel("breaker", f"nsu={PLANT_NS};s=Breaker.Closed", "1"),
    OpcUaChannel("cycles", f"nsu={PLANT_NS};s=Cycles", "count"),
]


@pytest.fixture
def source(plant, pki):
    plant.set("Pump.Power", 250.0)
    src = OpcUaSource(
        plant.endpoint,
        CHANNELS,
        security=secure(pki, username="operator", password="s3cret"),
    )
    yield src
    src.close()


# -------------------------------------------------------------- reading


def test_browse_finds_the_plant_nodes(source):
    entries = {
        e.browse_name.split(":", 1)[1]: e for e in source.browse("i=85", max_depth=1)
    }
    p = entries["Pump.Power"]
    assert (
        p.node_class == "Variable"
        and p.expanded_node_id == f"nsu={PLANT_NS};s=Pump.Power"
    )
    assert p.readable and p.numeric and p.data_type == 11
    assert entries["Serial"].numeric is False
    assert entries["Secret"].readable is False


def test_a_poll_reads_every_channel_in_si(source):
    s = source.read()
    assert isinstance(source, Source)
    assert s.values == pytest.approx(
        {
            "p_out": 250_000.0,
            "fill": 0.625,
            "t_cab": 304.65,
            "breaker": 1.0,
            "cycles": 1450.0,
        }
    )
    assert set(s.quality.values()) == {"good"}
    assert s.source == source.endpoint
    tags = {t.name: t for t in source.tags()}
    assert (
        tags["p_out"].unit == "W"
        and tags["p_out"].raw_unit == "kW"
        and tags["p_out"].dtype == "Double"
    )
    assert tags["fill"].dtype == "Float" and tags["breaker"].dtype == "Boolean"
    assert all(v is not None for v in source.source_timestamps.values())


def test_samples_flow_through_signal_and_estimate_unchanged(source, plant):
    from otwin.estimate.linear import KalmanFilter
    from otwin.signal.condition import resample, sort_samples

    source.connect()  # so the handshake is not inside the first sampling interval
    samples = []
    for k in range(25):
        plant.set("Pump.Power", 200.0 + 2.0 * k)
        samples.append(source.read())
        time.sleep(0.01)
    t, Y, names = samples_to_arrays(samples, ["p_out", "fill"])
    t, Y = sort_samples(t[::-1], Y[::-1])  # any order in, time order out
    assert names == ["p_out", "fill"] and Y.shape == (25, 2)
    tg, yg, gaps = resample(
        t, Y, dt=0.02, max_gap=2.0
    )  # tolerance stated, not timing-dependent
    assert np.all(np.isfinite(yg[:, 0])) and not gaps
    kf = KalmanFilter(
        A=np.eye(1),
        B=None,
        C=np.eye(1),
        Q=np.array([[1e6]]),
        R_meas=np.array([[1.0]]),
        P0=np.array([[1e10]]),
        x0=np.array([Y[0, 0]]),
    )
    res = kf.filter(Y[:, :1], None)
    assert res.x[-1, 0] == pytest.approx(248_000.0, rel=0.01)


def test_a_subscription_delivers_each_change_as_a_sample(plant, pki):
    plant.set("Pump.Power", 10.0)
    with OpcUaSource(
        plant.endpoint,
        CHANNELS[:2],
        security=secure(pki),
        mode="subscribe",
        sampling_interval=0.05,
    ) as src:
        src.subscribe()
        assert src.read().values["p_out"] == pytest.approx(10_000.0)
        src.drain()
        for v in (11.0, 12.0, 13.0):
            plant.set("Pump.Power", v)
            time.sleep(0.3)
        series = src.drain()
        seen = [s.values["p_out"] for s in series]
        assert seen[-3:] == pytest.approx([11_000.0, 12_000.0, 13_000.0])
        assert all(set(s.values) == {"p_out", "fill"} for s in series)  # a stable key set
        assert np.all(np.diff([s.timestamp for s in series]) >= 0)


def test_uncertain_is_stale_and_bad_falls_back_then_goes_bad(plant, pki):
    plant.set("Pump.Power", 40.0)
    with OpcUaSource(
        plant.endpoint, CHANNELS[:1], security=secure(pki), max_stale_seconds=0.3
    ) as src:
        assert src.read().quality["p_out"] == "good"
        plant.set("Pump.Power", 41.0, status=ua.StatusCodes.UncertainLastUsableValue)
        s = src.read()
        assert (s.values["p_out"], s.quality["p_out"]) == (41_000.0, "stale")
        plant.set("Pump.Power", 0.0, status=ua.StatusCodes.BadSensorFailure)
        s = src.read()
        assert (s.values["p_out"], s.quality["p_out"]) == (
            40_000.0,
            "stale",
        )  # the last good value
        time.sleep(0.4)
        s = src.read()
        assert np.isnan(s.values["p_out"]) and s.quality["p_out"] == "bad"
    plant.set("Pump.Power", 250.0)


def test_an_unreachable_server_degrades_and_does_not_raise():
    ch = [OpcUaChannel("p", "ns=2;s=P", "kW")]
    with pytest.warns(InsecureConnectionWarning):
        src = OpcUaSource(
            f"opc.tcp://127.0.0.1:{_free_port()}",
            ch,
            security=OpcUaSecurity.insecure(),
            timeout=1.0,
        )
        s = src.read()
    assert s.quality == {"p": "bad"} and np.isnan(s.values["p"])
    assert src.last_error is not None
    src.close()


# -------------------------------------------------------------- never writes


def test_nothing_can_make_it_write(source, plant):
    source.read()
    before = plant.get("Pump.Setpoint")
    client = source._client  # reaching past the API on purpose
    node = client.get_node(ua.NodeId.from_string("ns=2;s=Pump.Setpoint"))
    with pytest.raises(ReadOnlyViolation, match="WriteRequest"):
        source._loop.run(node.write_value(999.0), 5)
    with pytest.raises(ReadOnlyViolation, match="CallRequest"):
        source._loop.run(
            client.nodes.server.call_method(
                "0:GetMonitoredItems", ua.Variant(1, ua.VariantType.UInt32)
            ),
            5,
        )
    with pytest.raises(ReadOnlyViolation, match="AddNodesRequest"):
        source._loop.run(client.nodes.objects.add_variable(2, "Injected", 1.0), 5)
    assert plant.get("Pump.Setpoint") == before == 100.0
    assert source.read().quality["p_out"] == "good"  # and it keeps reading


# -------------------------------------------------------------- channel checks


@pytest.mark.parametrize(
    "channel, message",
    [
        (OpcUaChannel("x", f"nsu={PLANT_NS};s=Serial", "1"), "not a numeric scalar"),
        (OpcUaChannel("x", f"nsu={PLANT_NS};s=Secret", "1"), "not readable"),
        (OpcUaChannel("x", f"nsu={PLANT_NS};s=Vector", "1"), "not a scalar"),
        (OpcUaChannel("x", f"nsu={PLANT_NS};s=Missing", "1"), "does not exist"),
        (OpcUaChannel("x", "nsu=urn:no:such:namespace;s=X", "1"), "not on the server"),
        (OpcUaChannel("x", f"nsu={PLANT_NS};s=Pump.Power", "W"), "EngineeringUnits"),
        (
            OpcUaChannel("x", f"nsu={PLANT_NS};s=Cabinet.Temperature", "K"),
            "EngineeringUnits",
        ),
    ],
)
def test_a_channel_the_server_contradicts_is_refused(plant, pki, channel, message):
    with (
        OpcUaSource(plant.endpoint, [channel], security=secure(pki)) as src,
        pytest.raises(OpcUaConfigurationError, match=message),
    ):
        src.read()


def test_the_unit_check_can_be_turned_off(plant, pki):
    ch = [OpcUaChannel("x", f"nsu={PLANT_NS};s=Pump.Power", "W")]
    with OpcUaSource(plant.endpoint, ch, security=secure(pki), check_units=False) as src:
        assert src.read().values["x"] == pytest.approx(250.0)


# -------------------------------------------------------------- security


def test_an_untrusted_server_is_refused_before_any_credential_is_sent(plant, pki):
    plant.users.seen.clear()
    sessions_before = len(plant.client_uris)
    sec = secure(pki, trust=pki / "untrusted", username="operator", password="s3cret")
    with (
        OpcUaSource(plant.endpoint, CHANNELS[:1], security=sec) as src,
        pytest.raises(OpcUaSecurityError) as e,
    ):
        src.read()
    assert e.value.status == "BadCertificateUntrusted"
    assert plant.users.seen == []  # no password sent
    assert len(plant.client_uris) == sessions_before  # not even CreateSession


def test_the_session_is_what_was_configured(source, plant, pki):
    source.read()
    c = source._client
    assert c.security_policy.URI.endswith("#Basic256Sha256")
    assert c.security_policy.Mode == ua.MessageSecurityMode.SignAndEncrypt
    assert plant.client_uris[-1] == CLIENT_URI  # taken from the client certificate
    assert ("operator", "s3cret") in plant.users.seen


def test_aes256_rsapss_works_and_an_unoffered_policy_is_named(plant, pki):
    with OpcUaSource(
        plant.endpoint, CHANNELS[:1], security=secure(pki, policy="Aes256_Sha256_RsaPss")
    ) as src:
        assert src.read().quality["p_out"] == "good"
        assert src._client.security_policy.URI.endswith("#Aes256_Sha256_RsaPss")
    with (
        OpcUaSource(
            plant.endpoint,
            CHANNELS[:1],
            security=secure(pki, policy="Aes128_Sha256_RsaOaep"),
        ) as src,
        pytest.raises(OpcUaSecurityError, match="offers no endpoint") as e,
    ):
        src.read()
    assert e.value.status == "BadSecurityPolicyRejected"
    assert "Basic256Sha256" in str(e.value)


def test_sign_only_works_without_a_password(plant, pki):
    with OpcUaSource(
        plant.endpoint, CHANNELS[:1], security=secure(pki, mode="Sign")
    ) as src:
        assert src.read().quality["p_out"] == "good"
        assert src._client.security_policy.Mode == ua.MessageSecurityMode.Sign


def test_a_wrong_password_raises_rather_than_degrading(plant, pki):
    sec = secure(pki, username="operator", password="wrong")
    with (
        OpcUaSource(plant.endpoint, CHANNELS[:1], security=sec) as src,
        pytest.raises(OpcUaSecurityError) as e,
    ):
        src.read()
    assert e.value.status.startswith(("BadUser", "BadIdentity"))


def test_an_empty_token_policy_encrypts_the_password_with_the_channel_policy(plant, pki):
    """Part 4 §7.41: an empty token policy means the channel's policy encrypts it."""
    tokens = [
        t
        for ep in plant.server.iserver.endpoints
        for t in ep.UserIdentityTokens
        if t.TokenType == ua.UserTokenType.UserName
    ]
    saved = [t.SecurityPolicyUri for t in tokens]
    try:
        for t in tokens:
            t.SecurityPolicyUri = ""
        plant.tokens.clear()
        with OpcUaSource(
            plant.endpoint,
            CHANNELS[:1],
            security=secure(pki, username="operator", password="s3cret"),
        ) as src:
            assert src.read().quality["p_out"] == "good"
        assert (
            plant.tokens
            and plant.tokens[-1] == "http://www.w3.org/2001/04/xmlenc#rsa-oaep"
        )
    finally:
        for t, uri in zip(tokens, saved, strict=True):
            t.SecurityPolicyUri = uri


def _username_tokens(plant, mode):
    return [
        t
        for ep in plant.server.iserver.endpoints
        if ep.SecurityMode == mode
        for t in ep.UserIdentityTokens
        if t.TokenType == ua.UserTokenType.UserName
    ]


def test_over_sign_only_the_password_is_encrypted_by_its_token_policy(plant, pki):
    plant.tokens.clear()
    sec = secure(pki, mode="Sign", username="operator", password="s3cret")
    with OpcUaSource(plant.endpoint, CHANNELS[:1], security=sec) as src:
        assert src.read().quality["p_out"] == "good"
    assert plant.tokens[-1] == "http://www.w3.org/2001/04/xmlenc#rsa-oaep"


def test_a_password_that_would_travel_readable_is_never_sent(plant, pki):
    """Token policy None over a channel that only signs: refuse, send nothing."""
    tokens = _username_tokens(plant, ua.MessageSecurityMode.Sign)
    saved = [t.SecurityPolicyUri for t in tokens]
    try:
        for t in tokens:
            t.SecurityPolicyUri = "http://opcfoundation.org/UA/SecurityPolicy#None"
        plant.users.seen.clear()
        sec = secure(pki, mode="Sign", username="operator", password="s3cret")
        with (
            OpcUaSource(plant.endpoint, CHANNELS[:1], security=sec) as src,
            pytest.raises(OpcUaSecurityError, match="readable") as e,
        ):
            src.read()
        assert e.value.status == "BadSecurityModeInsufficient"
        assert all(pw != "s3cret" for _, pw in plant.users.seen)
    finally:
        for t, uri in zip(tokens, saved, strict=True):
            t.SecurityPolicyUri = uri


def test_policy_none_warns_and_says_so_in_the_manifest(plant):
    with (
        pytest.warns(InsecureConnectionWarning),
        OpcUaSource(
            plant.endpoint, CHANNELS[:1], security=OpcUaSecurity.insecure()
        ) as src,
    ):
        assert src.read().quality["p_out"] == "good"
        acq = src.acquisition()
    assert acq["security"]["policy"] == "None"
    assert "server_certificate_sha256" not in acq["security"]


# -------------------------------------------------------------- the manifest


def test_the_endpoint_and_mapping_are_recorded_with_no_secret(source, pki):
    source.read()
    acq = source.acquisition()
    assert acq["protocol"] == "opc-ua" and acq["endpoint"] == source.endpoint
    ch = {c["name"]: c for c in acq["channels"]}
    assert list(ch) == [c.name for c in CHANNELS]
    assert ch["p_out"]["expanded_node_id"] == f"nsu={PLANT_NS};s=Pump.Power"
    assert (
        ch["p_out"]["node_id"].endswith(";s=Pump.Power")
        and ch["p_out"]["namespace_uri"] == PLANT_NS
    )
    assert (ch["p_out"]["unit"], ch["p_out"]["raw_unit"], ch["p_out"]["data_type"]) == (
        "W",
        "kW",
        11,
    )
    assert ch["p_out"]["engineering_units"]["unece_code"] == "KWT"
    sec = acq["security"]
    assert (sec["policy"], sec["mode"], sec["user_token"]) == (
        "Basic256Sha256",
        "SignAndEncrypt",
        "username",
    )
    assert (
        sec["server_certificate_sha256"]
        == hashlib.sha256((pki / "server.der").read_bytes()).hexdigest()
    )
    assert sec["server_application_uri"] == SERVER_URI and sec["trusted_directly"] is True

    m = TwinManifest(
        name="pump-7",
        model_class="compiled",
        model_kind="pump",
        n_states=1,
        n_inputs=1,
        provenance=Provenance.now("2.0.1"),
        acquisition=acq,
    )
    text = m.to_json()
    assert "s3cret" not in text and "operator" not in text and "PRIVATE KEY" not in text
    back = TwinManifest.from_dict(json.loads(text))
    assert back.acquisition == json.loads(json.dumps(acq))
    assert (
        "acquisition"
        not in TwinManifest(
            name="x",
            model_class="compiled",
            model_kind="x",
            n_states=1,
            n_inputs=0,
            provenance=Provenance.now("2.0.1"),
        ).to_dict()
    )
