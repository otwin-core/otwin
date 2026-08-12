"""Advisory Generation (ISO 13374 block AG): what to do, or why we won't say.

The interesting part of an advisory layer is not what it recommends. It is
what it refuses. See :mod:`otwin.advise.envelope`.
"""

from .envelope import Breach, Envelope, OutsideEnvelope, Verdict

__all__ = ["Envelope", "Verdict", "Breach", "OutsideEnvelope"]
