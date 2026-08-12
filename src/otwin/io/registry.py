"""The dataset registry.

Raw data does not belong in git. A 21 MB CSV in version control makes every
clone slow forever, and the file is not even ours to redistribute — it is the
NASA Ames Prognostics Center's.

So this package stores **identity, not bytes**: where each dataset comes from,
what it should hash to, and how to load it. The download is on first use and is
verified against the checksum, so a truncated or substituted file fails loudly
rather than producing quietly wrong science.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Dataset", "DATASETS"]


@dataclass(frozen=True)
class Dataset:
    """Identity and provenance of a dataset.

    Attributes:
        name: Short identifier used by otwin.io.load.
        description: What it contains.
        source: Who produced it and where it came from.
        license: Terms of use. Check before redistributing anything.
        url: Canonical download location. None means it must be fetched
            manually — some sources require accepting terms in a browser.
        sha256: Checksum of the expected file.
        size_bytes: Expected size, as a cheap first check.
        citation: How to cite the data. Using someone's dataset without citing
            it is the most common form of academic free-riding.
        columns: Column names, where the format is stable.
    """

    name: str
    description: str
    source: str
    license: str
    sha256: str
    size_bytes: int
    citation: str
    url: str | None = None
    columns: tuple[str, ...] = field(default_factory=tuple)


DATASETS: dict[str, Dataset] = {
    "nasa_battery_discharge": Dataset(
        name="nasa_battery_discharge",
        description=(
            "Discharge cycles from the NASA Li-ion battery aging dataset. Used "
            "for the State-of-Health and Remaining-Useful-Life examples. Each "
            "row is one measurement within a discharge cycle."
        ),
        source=(
            "NASA Ames Prognostics Center of Excellence, Li-ion Battery Aging "
            "Dataset (B0005-B0018). Redistributed here unmodified."
        ),
        license=(
            "US Government work, public domain. Cite the source; do not imply "
            "NASA endorsement."
        ),
        url=("https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"),
        sha256="42067a9d7422b8a680ac4ae6562e87f38961a3c50b0da27e2d4fde78af9459e5",
        size_bytes=21568242,
        citation=(
            "Saha, B. & Goebel, K. (2007). Battery Data Set. NASA Ames "
            "Prognostics Data Repository, NASA Ames Research Center, "
            "Moffett Field, CA."
        ),
    ),
}
