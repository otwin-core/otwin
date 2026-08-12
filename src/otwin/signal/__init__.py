"""Data Manipulation (ISO 13374 block DM): make the measurements usable.

Between a register read and a model sits a layer nobody writes papers about
and every deployment needs: irregular timestamps, gaps where the link dropped,
samples arriving out of order because two RTUs disagree about the time, one tag
in kW and its neighbour in W.

Getting this wrong does not raise an error. It produces a slightly wrong number
that survives all the way to a maintenance decision.

Unit normalisation lives next door in :func:`otwin.io.to_si`, because units
belong to the tag, and the tag comes from the acquisition layer.
"""

from .condition import Gap, coverage, find_gaps, resample, sort_samples

__all__ = ["resample", "find_gaps", "sort_samples", "coverage", "Gap"]
