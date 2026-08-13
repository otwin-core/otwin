"""Tests that run when PyTorch is absent.

Both existing test modules begin with ``pytest.importorskip("torch")``, so in a
torch-free environment pytest collected nothing and exited with code 5 — which
GitHub reports as a failed job whose log says "skipped". A red build for the
wrong reason is worse than a red build.

Everything here is pure Python and exercises the parts of the package that do
not need torch: the lazy-import shim, and the fact that asking for a
torch-backed object without torch produces a message that tells you what to
install rather than a traceback from three frames down.
"""

from __future__ import annotations

import importlib
import re
from importlib import metadata

import pytest

import otwin.model as otwin_learn


def test_import_is_cheap_and_does_not_pull_torch() -> None:
    """`import otwin.model as otwin_learn` must work with no torch installed."""
    assert otwin_learn.__version__


def test_public_names_are_declared() -> None:
    assert set(otwin_learn.__all__) >= {
        "PortHamiltonianNN",
        "derivative_loss",
        "passivity_penalty",
    }


def test_unknown_attribute_raises_attribute_error_not_import_error() -> None:
    with pytest.raises(AttributeError):
        otwin_learn.definitely_not_a_real_name  # noqa: B018 - the access is the test


@pytest.mark.skipif(
    importlib.util.find_spec("torch") is not None,
    reason="torch is installed; this test is about the message when it is not",
)
def test_missing_torch_says_what_to_install() -> None:
    """The failure mode users actually hit, pinned.

    The message must name a distribution that exists. This test had the right
    idea and the wrong fact: it was written when the learned models shipped as
    a separate `otwin-learn` distribution, and it asserted that the message
    must NOT say `otwin[...]`. The thirteen packages were then merged into one
    called `otwin`, which inverted the truth without touching the test -- so
    the suite actively defended an instruction that resolves to nothing on
    PyPI.

    Asserted against the installed metadata now, not against a string, so the
    same drift cannot happen again.
    """
    # The shim resolves the NAME without torch -- the ImportError fires on
    # construction, which is the moment torch is actually needed. Worth pinning:
    # `hasattr(otwin_learn, "PortHamiltonianNN")` being True says nothing about
    # whether you can build one.
    cls = otwin_learn.PortHamiltonianNN
    with pytest.raises(ImportError) as exc:
        cls(n_states=2, n_inputs=1)
    message = str(exc.value)
    assert "torch" in message.lower()

    named = re.findall(r"otwin\[([a-z0-9,\s_.-]+)\]", message)
    assert named, f"message does not say what to install. Got: {message}"
    declared = {
        e.lower() for e in (metadata.metadata("otwin").get_all("Provides-Extra") or [])
    }
    for group in named:
        for extra in (e.strip().lower() for e in group.split(",")):
            assert extra in declared, (
                f"message names extra {extra!r}, which pip does not accept. "
                f"Declared: {sorted(declared)}. Got: {message}"
            )
    assert "otwin-learn" not in message, (
        f"otwin-learn was one of the pre-merge distributions and is not on "
        f"PyPI. Got: {message}"
    )
