"""What `pip install otwin` actually delivers.

Every other test in this suite runs against the source tree. These run against
the *distribution* — the metadata pip reads, the marker files a type checker
looks for, the install instructions the package prints at the user. That is a
different surface, and it fails in ways a source-tree test cannot see.

Both defects pinned here were found by building a wheel and installing it into
a container that had never seen this repository: the type-marker file was
absent while the classifiers advertised ``Typing :: Typed``, and the learned-
model path told the user to install a distribution that does not exist. The
test suite was green through both.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import pytest

import otwin

PACKAGE_ROOT = Path(otwin.__file__).parent


def _declared_extras() -> set[str]:
    """Extras pip will actually accept, read from the installed metadata."""
    return {
        e.lower() for e in (metadata.metadata("otwin").get_all("Provides-Extra") or [])
    }


def test_the_package_ships_a_py_typed_marker() -> None:
    """Without it, every annotation in this library is invisible downstream.

    PEP 561 says a type checker must ignore an installed package that has no
    ``py.typed`` marker, however completely it is annotated. This package is
    annotated throughout and mypy-clean, and it advertises ``Typing :: Typed``
    in its classifiers — so an engineer who installs it and runs mypy over
    their own code has every right to expect their call sites to be checked.

    Before this marker existed, mypy reported
    ``Skipping analyzing "otwin.advise": module is installed, but missing
    library stubs or py.typed marker`` and passed over two real type errors in
    the calling file.
    """
    marker = PACKAGE_ROOT / "py.typed"
    assert marker.is_file(), (
        f"{marker} is missing. The classifiers claim 'Typing :: Typed' and the "
        f"source is fully annotated, but PEP 561 makes a type checker ignore "
        f"all of it without this file."
    )


def test_typed_classifier_and_marker_agree() -> None:
    """Claiming Typed in the metadata and not shipping the marker is a lie."""
    classifiers = metadata.metadata("otwin").get_all("Classifier") or []
    claims_typed = any(c.strip() == "Typing :: Typed" for c in classifiers)
    has_marker = (PACKAGE_ROOT / "py.typed").is_file()
    assert claims_typed == has_marker, (
        f"classifier says typed={claims_typed} but py.typed present={has_marker}"
    )


def test_every_install_instruction_in_the_source_names_a_real_extra() -> None:
    """An error message that sends the user to a package that does not exist.

    This library imports its heavy dependencies lazily and tells the user what
    to install when one is missing. That message is the whole user experience
    of an optional dependency: it is read by someone who is already stuck.

    ``phnn.py`` said ``pip install otwin-learn[torch]``. Neither the
    distribution nor the extra existed — both were left over from the split
    packages this one was merged from. A student following it would get
    ``No matching distribution found for otwin-learn``, and an unclaimed name
    on PyPI is a name someone else can claim.

    Checked against the metadata pip itself reads, so it cannot drift again
    when an extra is renamed.
    """
    declared = _declared_extras()
    assert declared, "otwin declares no extras; the metadata read is wrong"

    pattern = re.compile(r"otwin\[([a-z0-9,\s_.-]+)\]")
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            for extra in (e.strip().lower() for e in match.group(1).split(",")):
                if extra and extra not in declared:
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(PACKAGE_ROOT)}:{line} names extra "
                        f"{extra!r}, which is not declared"
                    )
    assert not offenders, (
        "\n".join(["install instructions name extras that do not exist:", *offenders])
        + f"\ndeclared extras: {sorted(declared)}"
    )


def test_no_source_file_points_at_one_of_the_old_split_distributions() -> None:
    """Thirteen packages became one. Nothing may still send users to the old names.

    ``otwin-learn``, ``otwin-phs``, ``otwin-base`` and the rest were separate
    distributions before the merge. None of them is on PyPI, and none of them
    will be.
    """
    stale = re.compile(r"otwin[-_](learn|phs|base|io|uq|forecast|estimate|agents)\b")
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in stale.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(
                f"{path.relative_to(PACKAGE_ROOT)}:{line} mentions {match.group(0)!r}"
            )
    assert not offenders, "\n".join(
        ["source refers to distributions that no longer exist:", *offenders]
    )


@pytest.mark.parametrize("extra", ["modbus", "sunspec", "nn", "gp", "field", "all"])
def test_the_documented_extras_are_all_declared(extra: str) -> None:
    """The extras the READMEs and error messages promise, pinned one by one.

    A renamed extra is a silent break: ``pip install 'otwin[nn]'`` on an extra
    that no longer exists installs the base package and exits zero.
    """
    assert extra in _declared_extras()
