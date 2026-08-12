"""Tests for the dataset registry.

The registry stores identity, not bytes. These tests check that the identity is
complete and that verification actually refuses a wrong file — the one job this
package has.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from otwin.io import DATASETS, cache_dir, describe, load, verify
from otwin.io.loader import path_for


def test_every_dataset_carries_full_provenance():
    """A dataset without a citation or a licence is a liability, not an asset."""
    for name, d in DATASETS.items():
        assert d.name == name
        assert len(d.description) > 40, f"{name}: description too thin"
        assert d.source, f"{name}: no source"
        assert d.license, f"{name}: no licence"
        assert d.citation, (
            f"{name}: no citation — using data without citing it is free-riding"
        )
        assert len(d.sha256) == 64, f"{name}: sha256 is not a sha256"
        assert d.size_bytes > 0


def test_describe_tells_you_how_to_cite():
    text = describe("nasa_battery_discharge")
    assert "cite as" in text
    assert "NASA" in text
    assert "licence" in text


def test_unknown_dataset_names_the_known_ones():
    with pytest.raises(KeyError, match="known:"):
        describe("a_dataset_that_does_not_exist")


def test_cache_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OTWIN_DATA_DIR", str(tmp_path / "custom"))
    assert cache_dir() == tmp_path / "custom"
    monkeypatch.delenv("OTWIN_DATA_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg" / "otwin" / "data"


def test_verify_rejects_a_file_with_the_wrong_checksum(tmp_path, monkeypatch):
    """The important one.

    A truncated download or a substituted file produces results that are wrong
    in a way nothing downstream can detect. This must be an error, never a
    warning.
    """
    monkeypatch.setenv("OTWIN_DATA_DIR", str(tmp_path))
    p = path_for("nasa_battery_discharge")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("Voltage_measured,Current_measured\n1.0,2.0\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify("nasa_battery_discharge", p)


def test_verify_accepts_a_file_that_matches(tmp_path, monkeypatch):
    """Round-trip the mechanism itself against a synthetic entry."""
    from otwin.io.registry import Dataset

    content = b"a,b\n1,2\n"
    p = tmp_path / "synthetic.csv"
    p.write_bytes(content)

    DATASETS["_synthetic"] = Dataset(
        name="_synthetic",
        description="x" * 50,
        source="test",
        license="test",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        citation="test",
    )
    try:
        assert verify("_synthetic", p) is True
    finally:
        del DATASETS["_synthetic"]


def test_missing_file_explains_where_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setenv("OTWIN_DATA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError) as exc:
        load("nasa_battery_discharge")
    msg = str(exc.value)
    assert "Download it from" in msg
    assert "Cite as" in msg
    assert "OTWIN_DATA_DIR" in msg


def test_no_data_files_are_committed():
    """The whole point of the dataset registry.

    A CSV committed here would defeat it, and ``git rm`` would not undo it --
    the blob stays in history forever.

    Ask git, not the filesystem. An earlier version of this test walked
    ``root.rglob("*")`` and excluded ``.git`` and ``tests`` by name, which meant
    it failed the moment anyone put a virtualenv in the repository -- scikit-learn
    ships ``iris.csv``, and site-packages is not "committed" by any reading. The
    exclusion list would have had to grow forever (``.venv``, ``venv``, ``build``,
    ``dist``, ``node_modules``, ...) and would still have been answering the wrong
    question. ``git ls-files`` answers the question the test name asks.
    """
    root = Path(__file__).resolve().parent.parent
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.split("\0")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git worktree (installed from an sdist?)")

    data_suffixes = {".csv", ".zip", ".parquet", ".h5", ".hdf5", ".npy", ".npz", ".mat"}
    offenders = [
        f
        for f in tracked
        if f and Path(f).suffix.lower() in data_suffixes and not f.startswith("tests/")
    ]
    assert not offenders, (
        f"data files must not be committed: {offenders}. Register them in "
        f"DATASETS with a URL and a checksum instead; the point of the registry "
        f"is that the bytes never enter this repository's history."
    )
