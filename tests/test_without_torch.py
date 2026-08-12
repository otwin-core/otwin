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

    The message must name a distribution that exists. An earlier version said
    `pip install otwin[torch]`, and there is no `otwin` package.
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
    assert "otwin[" not in message, (
        "error message names a distribution that does not exist; "
        f"say otwin-learn[torch] instead. Got: {message}"
    )
