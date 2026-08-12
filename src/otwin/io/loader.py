"""Fetch, verify and load registered datasets."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .registry import DATASETS, Dataset

__all__ = ["cache_dir", "describe", "verify", "load", "path_for"]


def cache_dir() -> Path:
    """Where datasets are cached.

    Honours ``OTWIN_DATA_DIR``, then ``XDG_CACHE_HOME``, then ``~/.cache``.
    """
    if env := os.environ.get("OTWIN_DATA_DIR"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "otwin" / "data"


def path_for(name: str) -> Path:
    """Local path a dataset would be cached at, whether or not it is present."""
    return cache_dir() / f"{name}.csv"


def _dataset(name: str) -> Dataset:
    if name not in DATASETS:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(DATASETS)}")
    return DATASETS[name]


def describe(name: str) -> str:
    """A human-readable description, including licence and citation."""
    d = _dataset(name)
    present = path_for(name).exists()
    return "\n".join(
        [
            f"{d.name}",
            f"  {d.description}",
            f"  source:   {d.source}",
            f"  licence:  {d.license}",
            f"  size:     {d.size_bytes / 1e6:.1f} MB",
            f"  cached:   {'yes, at ' + str(path_for(name)) if present else 'no'}",
            f"  cite as:  {d.citation}",
        ]
    )


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def verify(name: str, path: Path | None = None) -> bool:
    """Check a local file against its registered checksum.

    Raises:
        FileNotFoundError: If the file is not there.
        ValueError: If the checksum does not match. This is deliberately an
            error rather than a warning: a dataset that is not what it claims
            to be produces results that are wrong in a way nothing downstream
            can detect.
    """
    d = _dataset(name)
    p = Path(path) if path else path_for(name)
    if not p.exists():
        raise FileNotFoundError(f"{p} does not exist")
    got = _sha256(p)
    if got != d.sha256:
        raise ValueError(
            f"checksum mismatch for {name}:\n"
            f"  expected {d.sha256}\n"
            f"  got      {got}\n"
            f"The file is not the registered dataset. It may be truncated, a "
            f"different version, or something else entirely. Delete {p} and "
            f"fetch it again rather than proceeding."
        )
    return True


def load(name: str, path: str | Path | None = None, verify_checksum: bool = True) -> Any:
    """Load a dataset as a pandas DataFrame.

    Args:
        name: A key of :data:`DATASETS`.
        path: Load from here instead of the cache.
        verify_checksum: Check the file against its registered hash first.
            Turn this off only if you know why you are doing it.

    Raises:
        ImportError: If pandas is not installed.
        FileNotFoundError: With instructions, if the file must be fetched
            manually.
    """
    # Check for the file before checking for pandas. Both are real failures,
    # but "you have not downloaded the data yet" is the common one and the one
    # the user can act on, and it does not need pandas to diagnose. Importing
    # first turned a missing dataset into "install pandas", which sends someone
    # off to fix the wrong thing.
    d = _dataset(name)
    p = Path(path) if path else path_for(name)
    if not p.exists():
        raise FileNotFoundError(
            f"{name} is not cached at {p}.\n\n"
            f"Download it from:\n  {d.url}\n\n"
            f"then place the extracted CSV at that path, or pass path=... "
            f"explicitly. Set OTWIN_DATA_DIR to change the cache location.\n\n"
            f"Licence: {d.license}\nCite as: {d.citation}"
        )

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "reading a dataset needs pandas, which otwin does not require.\n"
            "    pip install pandas"
        ) from exc

    if verify_checksum:
        verify(name, p)
    return pd.read_csv(p)
