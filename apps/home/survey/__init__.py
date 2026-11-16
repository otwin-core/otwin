"""Otwin Home survey: a home described by selectors, turned into a twin.

The first step of the wizard asks only what a householder knows: where the
home is, its kind, size and age, what heats it and its hot water, how warm
it is kept, what it cooks on, how many people live there and which appliances they use. No
physics is typed in. :func:`build_twin` turns the answers into a twin with
typical values; calibration then corrects those from the home's own
electricity.

>>> from survey import HomeDescription, build_twin
>>> twin = build_twin(HomeDescription(size="m", heating="heat_pump"), backend="numpy")
>>> round(twin.model.parameters["zone.envelope.conductance"])
150
"""

from __future__ import annotations

from .questions import PROVINCES, QUESTIONS, Option, Province, Question, questions_json
from .twin import FLOOR_AREA, HomeDescription, assumptions, build_twin, home_summary

__all__ = [
    "QUESTIONS",
    "PROVINCES",
    "Question",
    "Option",
    "Province",
    "questions_json",
    "HomeDescription",
    "build_twin",
    "assumptions",
    "home_summary",
    "FLOOR_AREA",
]
