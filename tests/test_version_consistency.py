"""The version string exists in two places, so it can disagree with itself.

`pyproject.toml` carries the version the wheel is built with; `otwin.__version__`
is what a running program reports and what a `TwinManifest` stamps into its
provenance. Nothing connected them. Bump one and forget the other and every
manifest written by that release records a version that was never published,
which is exactly the kind of provenance defect the manifest exists to prevent.

The release workflow already refuses a tag that disagrees with `pyproject.toml`.
This is the other half of that check, and it belongs in the suite rather than in
CI because it is a property of the source tree, not of the release.
"""

import re
from pathlib import Path

import tomllib

import otwin

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_pyproject_and_dunder_version_agree():
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
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
    changelog = (PYPROJECT.parent / "CHANGELOG.md").read_text()
    assert f"## [{otwin.__version__}]" in changelog, (
        f"CHANGELOG.md has no '## [{otwin.__version__}]' heading. Move the "
        f"Unreleased section under it before tagging."
    )
