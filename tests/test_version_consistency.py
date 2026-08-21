"""The version string exists in two places, so it can disagree with itself.

`pyproject.toml` carries the version the wheel is built with; `otwin.__version__`
is what a running program reports and what a `TwinManifest` stamps into its
provenance. Nothing connected them. Bump one and forget the other and every
manifest written by that release records a version that was never published,
which is exactly the kind of provenance defect the manifest exists to prevent.

The release workflow already refuses a tag that disagrees with `pyproject.toml`.
This is the other half of that check, and it belongs in the suite rather than in
CI because it is a property of the source tree, not of the release.

The version is read with a regex rather than a TOML parser. `tomllib` is stdlib
only from 3.11 and this package supports 3.10, so importing it here would make
the test that guards the support floor the one thing that cannot run on it.
Adding `tomli` as a dependency to read one field would be worse.
"""

import re
from pathlib import Path

import otwin

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _declared_version() -> str:
    """The `version = "..."` line from the `[project]` table.

    Anchored to the start of a line so that a `version` key nested inside some
    other table cannot be picked up by accident.
    """
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    assert match is not None, 'no top-level `version = "..."` in pyproject.toml'
    return match.group(1)


def test_pyproject_and_dunder_version_agree():
    declared = _declared_version()
    assert otwin.__version__ == declared, (
        f"otwin.__version__ is {otwin.__version__!r} but pyproject.toml says "
        f"{declared!r}. Both have to move together: the first is what a manifest "
        f"records, the second is what pip installs."
    )


def test_version_is_a_release_number_not_a_placeholder():
    """Catches `0.0.0`, `dev`, and a bump that was started and not finished."""
    assert re.fullmatch(r"\d+\.\d+\.\d+([ab]\d+|rc\d+)?", otwin.__version__), (
        f"{otwin.__version__!r} is not a PEP 440 release version"
    )
    assert otwin.__version__ != "0.0.0"


def test_the_changelog_has_an_entry_for_this_version():
    """A release with no changelog entry is a release nobody can read."""
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{otwin.__version__}]" in changelog, (
        f"CHANGELOG.md has no '## [{otwin.__version__}]' heading. Move the "
        f"Unreleased section under it before tagging."
    )


def test_the_test_suite_does_not_import_beyond_the_supported_python():
    """The floor this package claims is 3.10, so the tests have to run on it.

    `tomllib` is the trap: stdlib from 3.11, the obvious way to read the version
    out of `pyproject.toml`, and green on every developer machine because nobody
    develops on the oldest version they support. Only the 3.10 job sees it, and
    only after the push. A grep is a blunt instrument and it costs a second.
    """
    too_new = {
        "tomllib": "3.11",  # use a regex, or add tomli for 3.10
        "asyncio.taskgroups": "3.11",
    }
    offenders = []
    for path in sorted((ROOT / "tests").glob("*.py")) + sorted(
        (ROOT / "src").rglob("*.py")
    ):
        text = path.read_text()
        for module, version in too_new.items():
            pattern = rf"^\s*(?:import {re.escape(module)}|from {re.escape(module)} )"
            for line in text.splitlines():
                if re.match(pattern, line) and "except ImportError" not in text:
                    offenders.append(
                        f"{path.relative_to(ROOT)}: {module} needs {version}"
                    )
    assert not offenders, (
        "these imports are newer than the supported Python floor:\n  "
        + "\n  ".join(offenders)
    )
