"""The OPC UA client's configuration, checked with neither asyncua nor a network.

Node ids, the read-only rules, the security rules and the message a missing
extra gives. These run in every environment, including one where
``otwin[opcua]`` is not installed. The live tests are in test_io_opcua.py.
"""

from __future__ import annotations

import json
import sys

import pytest

from otwin.interfaces import TwinManifest
from otwin.io import (
    MissingDependencyError,
    OpcUaChannel,
    OpcUaConfigurationError,
    OpcUaSecurity,
    OpcUaSecurityError,
    OpcUaSource,
    ReadOnlyViolation,
    load_opcua_config,
    parse_node_id,
)


def test_node_ids_follow_part_6():
    assert parse_node_id("ns=2;s=Tank.Level") == (2, None, "s", "Tank.Level")
    assert parse_node_id("nsu=urn:plant;i=1001") == (None, "urn:plant", "i", "1001")
    assert parse_node_id("i=2258") == (None, None, "i", "2258")
    for bad in ("Tank.Level", "ns=x;s=a", "i=abc", "ns=2;q=1", ""):
        with pytest.raises(OpcUaConfigurationError):
            parse_node_id(bad)


@pytest.mark.parametrize("access", ["write", "read_write", "rw", "Read"])
def test_a_channel_that_asks_to_write_is_refused(access):
    with pytest.raises(ReadOnlyViolation, match="read-only"):
        OpcUaChannel("p", "ns=2;s=Pump.Power", "kW", access=access)


@pytest.mark.parametrize(
    "doc",
    [
        {"writable": True},
        {"allow_write": False},  # even asking for it to be off is a write option
        {"setpoints": [{"name": "sp", "node_id": "ns=2;s=SP", "unit": "kW"}]},
        {"security": {"policy": "None", "allow_insecure": True, "write_enabled": True}},
        {
            "channels": [
                {"name": "p", "node_id": "ns=2;s=P", "unit": "kW", "access": "read_write"}
            ]
        },
        {"channels": [{"name": "p", "node_id": "ns=2;s=P", "unit": "kW", "write": 1.0}]},
        {"commands": {"start": "ns=2;s=Pump.Start"}},
    ],
)
def test_a_configuration_that_asks_to_write_is_refused(doc):
    base = {
        "endpoint": "opc.tcp://127.0.0.1:4840",
        "security": {"policy": "None", "allow_insecure": True},
        "channels": [{"name": "p", "node_id": "ns=2;s=P", "unit": "kW"}],
    }
    with pytest.raises(ReadOnlyViolation):
        load_opcua_config({**base, **doc})


def test_the_source_offers_no_way_to_write():
    public = [n for n in dir(OpcUaSource) if not n.startswith("_")]
    for word in ("write", "set_value", "call", "method", "command", "setpoint"):
        assert not [n for n in public if word in n.lower()], public


def test_configuration_errors(tmp_path, monkeypatch):
    base = {
        "endpoint": "opc.tcp://127.0.0.1:4840",
        "security": {"policy": "None", "allow_insecure": True},
        "channels": [{"name": "p", "node_id": "ns=2;s=P", "unit": "kW"}],
    }
    with pytest.raises(OpcUaConfigurationError, match="unknown option"):
        load_opcua_config({**base, "polling": 1})
    with pytest.raises(OpcUaConfigurationError, match="unknown key"):
        load_opcua_config({**base, "channels": [{**base["channels"][0], "scale": 2}]})
    with pytest.raises(OpcUaConfigurationError, match="must not contain a password"):
        load_opcua_config(
            {**base, "security": {"policy": "Basic256Sha256", "password": "x"}}
        )
    sec = {
        "policy": "Basic256Sha256",
        "certificate": "c.der",
        "private_key": "k.pem",
        "trust": "trusted",
        "username": "operator",
        "password_env": "OTWIN_TEST_PW_UNSET",
    }
    monkeypatch.delenv("OTWIN_TEST_PW_UNSET", raising=False)
    with pytest.raises(OpcUaConfigurationError, match="OTWIN_TEST_PW_UNSET"):
        load_opcua_config({**base, "security": sec})
    monkeypatch.setenv("OTWIN_TEST_PW_UNSET", "s3cret")
    cfg = load_opcua_config({**base, "security": sec})
    assert cfg["security"].password == "s3cret"
    assert "s3cret" not in repr(cfg["security"])  # a repr is not a leak
    # A file, with relative paths resolved against it.
    path = tmp_path / "plant.json"
    path.write_text(json.dumps({**base, "security": sec}))
    cfg = load_opcua_config(path)
    assert cfg["security"].certificate == str(tmp_path / "c.der")


def test_security_rules_of_parts_4_and_7():
    pki = {"certificate": "c.der", "private_key": "k.pem", "trust": "t"}
    for old in ("Basic128Rsa15", "Basic256"):
        with pytest.raises(OpcUaSecurityError, match="deprecated") as e:
            OpcUaSecurity(policy=old, **pki)
        assert e.value.status == "BadSecurityPolicyRejected"
    with pytest.raises(OpcUaSecurityError, match="insecure"):
        OpcUaSecurity(policy="None", mode="None")
    with pytest.raises(OpcUaConfigurationError, match="trust"):
        OpcUaSecurity(certificate="c.der", private_key="k.pem")  # no trust list
    assert (
        OpcUaSecurity(mode="Sign", username="u", password="p", **pki).mode == "Sign"
    )  # judged at connect
    with pytest.raises(OpcUaSecurityError, match="over security policy None"):
        OpcUaSecurity(
            policy="None", mode="None", allow_insecure=True, username="u", password="p"
        )
    with pytest.raises(OpcUaConfigurationError):
        OpcUaSecurity(policy="Basic256Sha256", mode="None", **pki)
    assert OpcUaSecurity(**pki).policy == "Basic256Sha256"
    assert OpcUaSecurity(**pki).mode == "SignAndEncrypt"


def test_endpoints_must_be_opc_tcp_and_carry_no_credentials():
    pytest.importorskip("asyncua")
    ch = [OpcUaChannel("p", "ns=2;s=P", "kW")]
    with pytest.raises(OpcUaConfigurationError, match="credentials"):
        OpcUaSource(
            "opc.tcp://operator:s3cret@127.0.0.1:4840",
            ch,
            security=OpcUaSecurity.insecure(),
        )
    with pytest.raises(OpcUaConfigurationError, match="opc.tcp"):
        OpcUaSource("https://127.0.0.1:4843", ch, security=OpcUaSecurity.insecure())
    with pytest.raises(ValueError, match="credentials"):
        TwinManifest.acquired_by(
            "opc-ua", endpoint="opc.tcp://u:p@h:4840", channels=[{"name": "p"}]
        )


def test_missing_extra_says_how_to_proceed(monkeypatch):
    monkeypatch.setitem(sys.modules, "asyncua", None)
    ch = [OpcUaChannel("p", "nsu=urn:plant;s=Pump.Power", "kW")]  # still fine without it
    with pytest.raises(MissingDependencyError) as e:
        OpcUaSource("opc.tcp://127.0.0.1:4840", ch, security=OpcUaSecurity.insecure())
    message = str(e.value)
    assert "pip install 'otwin[opcua]'" in message
    assert "pip install asyncua" in message
    assert "LGPL" in message
    assert "ModbusSource" in message and "otwin.io.load" in message
    assert isinstance(e.value, ImportError)
